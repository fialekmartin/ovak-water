#!/usr/bin/env python3
"""ZIS/SSO OVAK -> daily history JSON -> Home Assistant Recorder statistics.

Default is a read-only dry-run. --apply requires --confirm-new-statistic.
Uses the same OVAK API implementation as the HA custom integration.
"""
import argparse
import importlib.util
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_credentials(path: Path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    username = obj.get("username")
    password = obj.get("password")
    if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
        raise ValueError("Credentials JSON musí obsahovat neprázdné username a password")
    return username, password


def validate_days(days: dict, first: date, last: date):
    missing = []
    current = first
    while current <= last:
        if current not in days:
            missing.append(current.isoformat())
        current += timedelta(days=1)
    if missing:
        raise ValueError(f"Chybějící odečty: {', '.join(missing[:10])} (celkem {len(missing)}). Import zastaven.")


def build_export(days: dict, first: date, last: date):
    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "count": len(days),
        "history": [
            {"date": day.isoformat(), "liters": float(liters), "m3": round(liters / 1000, 3)}
            for day, liters in sorted(days.items())
        ],
    }


def check_empty_statistics(importer, url: str, token: str):
    if not token:
        raise ValueError("Pro kontrolu Home Assistantu nastav HA_TOKEN")
    ws = importer.websocket.create_connection(importer.websocket_url(url), timeout=60)
    try:
        importer.expect(ws, "auth_required")
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        importer.expect(ws, "auth_ok")
        ws.send(json.dumps({"id": 900001, "type": "recorder/list_statistic_ids", "statistic_type": "sum"}))
        existing = importer.expect(ws, "result", 900001).get("result")
        if not isinstance(existing, list):
            raise RuntimeError("Nelze ověřit existující statistiky; import zastaven")
        if any(isinstance(item, dict) and item.get("statistic_id") == importer.STATISTIC_ID
               for item in existing):
            raise RuntimeError(
                f"Statistika {importer.STATISTIC_ID} již existuje; import je zablokován. "
                "Původní historii nemaž a nesnaž se ji importovat znovu."
            )
        return ws
    except BaseException:
        ws.close()
        raise


def import_stats(importer, url: str, token: str, stats: list):
    ws = check_empty_statistics(importer, url, token)
    metadata = {
        "statistic_id": importer.STATISTIC_ID,
        "source": "ovak",
        "name": "OVAK spotřeba vody",
        "unit_of_measurement": "m³",
        "unit_class": "volume",
        "has_sum": True,
        "mean_type": 0,
    }
    try:
        for offset in range(0, len(stats), 100):
            request_id = 1000 + offset // 100
            ws.send(json.dumps({
                "id": request_id,
                "type": "recorder/import_statistics",
                "metadata": metadata,
                "stats": stats[offset:offset + 100],
            }, ensure_ascii=False))
            importer.expect(ws, "result", request_id)
            print(f"Importováno {min(offset + 100, len(stats))}/{len(stats)} bodů")
    finally:
        ws.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, default=Path("ovak_credentials.json"),
                        help="Lokální JSON se username/password pro OVAK (výchozí ./ovak_credentials.json)")
    parser.add_argument("--from", dest="first", type=date.fromisoformat,
                        default=date(2022, 9, 1), metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="last", type=date.fromisoformat,
                        default=date.today() - timedelta(days=1), metavar="YYYY-MM-DD")
    parser.add_argument("--output", type=Path, help="Volitelně uložit staženou historii do JSON")
    parser.add_argument("--url", help="Home Assistant URL, např. http://homeassistant.local:8123")
    parser.add_argument("--apply", action="store_true", help="Zapsat do Home Assistantu (jinak DRY RUN)")
    parser.add_argument("--confirm-new-statistic", action="store_true",
                        help="Potvrdit jednorázové vytvoření nové statistiky")
    args = parser.parse_args(argv)

    if args.first > args.last:
        parser.error("--from musí být <= --to")
    if args.last >= date.today():
        parser.error("Import lze provést jen do včerejšího dne")
    if args.apply and (not args.url or not args.confirm_new_statistic):
        parser.error("Pro zápis jsou nutné --url, --apply a --confirm-new-statistic")
    if args.apply and not os.environ.get("HA_TOKEN"):
        parser.error("Pro --apply nastav HA_TOKEN")
    if args.output and args.output.exists():
        parser.error(f"Výstupní soubor již existuje: {args.output}")

    ovak_api = load_module("ovak_http_api", ROOT / "custom_components/ovak/api.py")
    importer = load_module("ovak_history_import", ROOT / "tools/import_history.py")
    username, password = load_credentials(args.credentials)

    print(f"Načítám OVAK {args.first} až {args.last} (jedno nové přihlášení přes ZIS/SSO)")
    days = ovak_api.fetch_days(username, password, args.first, args.last)
    validate_days(days, args.first, args.last)
    exported = build_export(days, args.first, args.last)
    if args.output:
        args.output.write_text(json.dumps(exported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            args.output.chmod(0o600)
        except OSError:
            pass
        print(f"Export uložen: {args.output}")

    # Reuse exact HA transformation/validation of existing one-shot importer.
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "history.json"
        temp_path.write_text(json.dumps(exported), encoding="utf-8")
        stats, first, last, total = importer.load_stats(temp_path)
    print(f"VALIDACE OK: {len(days)} dnů, {len(stats)} bodů, {total} m³, {first}–{last}")

    if not args.apply:
        if args.url:
            ws = check_empty_statistics(importer, args.url, os.environ.get("HA_TOKEN", ""))
            ws.close()
            print("HA kontrola OK: cílová statistika ještě neexistuje")
        print("DRY RUN: žádný zápis do HA. Pro import přidej --apply --confirm-new-statistic --url URL")
        return

    import_stats(importer, args.url, os.environ["HA_TOKEN"], stats)
    print("Hotovo. Ověř statistiku ovak:water_consumption v Home Assistantu.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Chyba migrace: {exc}", file=sys.stderr)
        sys.exit(1)
