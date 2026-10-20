#!/usr/bin/env python3
"""Import OVAK daily consumption as Home Assistant long-term water statistics.

Dependencies: pip install websocket-client
Credentials: HA_TOKEN environment variable (Home Assistant administrator token).
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import websocket

STATISTIC_ID = "ovak:water_consumption"
TZ = ZoneInfo("Europe/Prague")


def load_stats(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    history = data["history"]
    if not history:
        raise ValueError("JSON obsahuje prázdnou historii")

    days = {}
    for item in history:
        day = date.fromisoformat(item["date"])
        liters = Decimal(str(item["liters"]))
        if not liters.is_finite() or liters < 0:
            raise ValueError(f"Neplatná spotřeba pro {day}: {liters}")
        if day in days:
            raise ValueError(f"Duplicitní datum: {day}")
        days[day] = liters

    ordered = sorted(days)
    if ordered[-1] >= date.today():
        raise ValueError("Historie obsahuje dnešek nebo budoucí dny; importuj jen dokončené dny")
    for before, after in zip(ordered, ordered[1:]):
        if after - before != timedelta(days=1):
            raise ValueError(f"Chybějící datum mezi {before} a {after}")

    def local_midnight(day):
        return datetime.combine(day, time.min, TZ).isoformat()

    stats = [{"start": local_midnight(ordered[0]), "state": 0.0, "sum": 0.0}]
    cumulative = Decimal("0")
    for day in ordered:
        cumulative += days[day] / Decimal("1000")
        stats.append({
            "start": local_midnight(day + timedelta(days=1)),
            "state": float(cumulative),
            "sum": float(cumulative),
        })
    return stats, ordered[0], ordered[-1], cumulative


def websocket_url(base):
    split = urlsplit(base)
    if split.scheme not in ("http", "https") or not split.netloc:
        raise ValueError("--url musí být http(s) URL Home Assistantu")
    return urlunsplit(("wss" if split.scheme == "https" else "ws", split.netloc,
                       split.path.rstrip("/") + "/api/websocket", "", ""))


def expect(ws, expected_type, message_id=None):
    while True:
        response = json.loads(ws.recv())
        if response.get("type") != expected_type:
            if response.get("type") == "auth_invalid":
                raise RuntimeError("Home Assistant odmítl token")
            if response.get("type") == "result" and response.get("id") == message_id:
                raise RuntimeError(f"Home Assistant: {response}")
            continue
        if message_id is not None and response.get("id") != message_id:
            continue
        if expected_type == "result" and not response.get("success"):
            raise RuntimeError(f"Import odmítnut: {response.get('error')}")
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_file", type=Path, help="Historie waterConsuption.json")
    parser.add_argument("--url", help="Např. http://homeassistant.local:8123")
    parser.add_argument("--apply", action="store_true", help="Odeslat data do HA; bez přepínače pouze validace")
    parser.add_argument("--confirm-new-statistic", action="store_true",
                        help="Potvrzuji první import do prázdné statistiky")
    args = parser.parse_args()

    stats, first, last, total = load_stats(args.json_file)
    print(f"Období: {first} až {last}; denních záznamů: {len(stats)-1}; celkem: {total} m³")
    print(f"Statistika: {STATISTIC_ID}; hodinových bodů: {len(stats)} (denní rozlišení)")
    if not args.apply:
        print("DRY RUN: žádná data nebyla odeslána. Pro import přidej --apply --url URL")
        return

    token = os.environ.get("HA_TOKEN")
    if not token:
        raise ValueError("Chybí HA_TOKEN v prostředí")
    if not args.url:
        raise ValueError("Pro --apply je povinné --url")

    metadata = {
        "statistic_id": STATISTIC_ID,
        "source": "ovak",
        "name": "OVAK spotřeba vody",
        "unit_of_measurement": "m³",
        "unit_class": "volume",
        "has_sum": True,
        "mean_type": 0,
    }
    if not args.confirm_new_statistic:
        raise ValueError("Pro první import je nutné --confirm-new-statistic. Existující statistiku nepřepisuj.")

    ws = websocket.create_connection(websocket_url(args.url), timeout=60)
    try:
        expect(ws, "auth_required")
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        expect(ws, "auth_ok")
        # Fail closed if any existing statistics are registered. Prevent accidental
        # overwriting of the history already maintained by the OVAK integration.
        ws.send(json.dumps({"id": 900001, "type": "recorder/list_statistic_ids",
                            "statistic_type": "sum"}))
        existing = expect(ws, "result", 900001).get("result")
        if not isinstance(existing, list):
            raise RuntimeError("Nelze ověřit existující statistiky; import zastaven")
        if any(isinstance(item, dict) and item.get("statistic_id") == STATISTIC_ID
               for item in existing):
            raise RuntimeError(
                f"Statistika {STATISTIC_ID} již existuje. Import odmítnut kvůli ochraně historie."
            )
        # Small batches so failures are detectable and don't exceed server limits.
        for offset in range(0, len(stats), 100):
            request_id = offset // 100 + 1
            ws.send(json.dumps({
                "id": request_id,
                "type": "recorder/import_statistics",
                "metadata": metadata,
                "stats": stats[offset:offset + 100],
            }, ensure_ascii=False))
            expect(ws, "result", request_id)
            print(f"Potvrzen import {min(offset+100,len(stats))}/{len(stats)}")
    finally:
        ws.close()
    print("Import odeslán. Ověř v Nástroje pro vývojáře → Statistiky.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError,
            websocket.WebSocketException) as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        sys.exit(1)
