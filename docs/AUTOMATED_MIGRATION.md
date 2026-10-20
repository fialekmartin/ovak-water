# Automatická migrace historie OVAK → Home Assistant

`tools/migrate_history.py` použije **stejný ZIS/SSO klient** jako integrace `custom_components/ovak/api.py`:

1. Přihlásí se do `zis.ovak.cz` a přejde do eMIS bez ručního přenosu cookies.
2. Načte měsíční stránky `ConsoJour` ve zvoleném intervalu.
3. Ověří, že žádný den nechybí; při chybě **nezapíše do HA nic**.
4. Vypočítá kumulativní `sum` (m³) kompatibilní s integrací.
5. Výchozí režim je **dry-run**. `--apply` povolí jednorázový import do prázdné statistiky.

## Příprava (na počítači, nikoli v HA OS SSH add-onu)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt
```

V kořenovém adresáři projektu vytvoř soubor `ovak_credentials.json` (je v `.gitignore`):

```json
{
  "username": "email@example.com",
  "password": "OVAK_HESLO"
}
```

```bash
chmod 600 ovak_credentials.json
```

## Dry-run bez přístupu k HA

```bash
python tools/migrate_history.py \
  --credentials ovak_credentials.json \
  --from 2022-09-01 \
  --to 2026-10-19 \
  --output ovak-history-private.json
```

Pouze stáhne historii a ověří souvislost dat. Soubor s historií je soukromý a nemá být commitován.
`--output` odmítne přepsat existující soubor.

## Dry-run s kontrolou prázdné statistiky v HA

```bash
export HA_TOKEN='LONG_LIVED_ACCESS_TOKEN'
python tools/migrate_history.py \
  --url http://homeassistant.local:8123 \
  --from 2022-09-01 \
  --to 2026-10-19
```

Provede také **read-only** kontrolu ID `ovak:water_consumption` na HA WebSocket API.
Pokud už statistika existuje, příkaz skončí chybou a nic nezmění.

## První import do nové instalace HA

Před importem vytvoř úplnou zálohu HA. Zastav dosud nenastavenou synchronizaci integrace, aby během importu nedošlo ke kolizi. Import je určen **výhradně pro novou, prázdnou statistiku**.

```bash
python tools/migrate_history.py \
  --url http://homeassistant.local:8123 \
  --from 2022-09-01 \
  --to 2026-10-19 \
  --apply --confirm-new-statistic
```

Bez `--apply` nikdy nezapisuje do HA. Opětovný import do existující řady záměrně odmítne. **Kontrola existence je preflight, nikoli transakční záruka**; během importu nesmí běžet jiný zapisující proces. Selhání uprostřed dávkového importu může zanechat částečná data; tyto chyby řeš ze zálohy, nespouštěj bez kontroly znovu.

## Poznámky

- Používá časové pásmo `Europe/Prague`, každý den se přiřazuje půlnoci následujícího dne. Neodvozuje hodinový průběh.
- `sum` začíná na nule; nejde o fyzický absolutní stav vodoměru.
- WebSocket `ws://` přes běžné HTTP je vhodný pouze v důvěryhodné LAN. Pro vzdálené HA použij HTTPS / WSS.
- Přihlašovací údaje a exporty nikdy neposílej do GitHub issues.
- Automatické přihlášení může selhat při změně webu nebo vyžadované CAPTCHA.
- Verze Pythonu a Home Assistantu mohou změnit rozhraní Recorder API; nejprve otestuj na záloze.
