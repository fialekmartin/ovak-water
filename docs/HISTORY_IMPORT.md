# Jednorázový import historické spotřeby OVAK

Nástroj `tools/import_history.py` převede denní spotřebu do dlouhodobé externí statistiky Home Assistantu **`ovak:water_consumption`**, kterou následně doplňuje vlastní integrace OVAK Water. Skript nezískává data z OVAK: očekává již exportovaný JSON.

## Předpoklady

- Vytvořená **úplná záloha Home Assistantu**.
- Python 3.9+ na Macu nebo Linuxu s přístupem k Home Assistantu.
- Home Assistant účet s oprávněním správce a jeho **Long-Lived Access Token**.
- JSON například `waterConsuption.json` s položkou `history`, každý záznam obsahuje `date` (`YYYY-MM-DD`) a `liters` (nezáporné číslo).
- Historie zahrnuje pouze **ukončené dny**, bez duplicit a mezer.

**Import provádějte jen jednou do nové/prázdné statistiky.** Pokud už je `ovak:water_consumption` v Nástrojích pro vývojáře → Statistiky, importní skript jej záměrně odmítne. **Nemažte existující historii, abyste skript znovu spustili.**

## Spuštění (macOS / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/requirements.txt

# Ověření bez připojení k HA a bez zápisu
python tools/import_history.py /cesta/k/waterConsuption.json

# Jednorázový import
export HA_TOKEN='DOPLN_LONG_LIVED_ACCESS_TOKEN'
python tools/import_history.py /cesta/k/waterConsuption.json \
  --url http://homeassistant.local:8123 --apply --confirm-new-statistic
unset HA_TOKEN
```

Token **neukládejte do repozitáře ani do shell historie**. V zabezpečeném prostředí lze místo `export` načíst token interaktivně. Při vzdáleném připojení používejte HTTPS/WSS.

## Datový model

Denní objem se převádí z litrů na m³ (`1000 l = 1 m³`). Statistiky jsou ukládány v lokální časové zóně `Europe/Prague`: počáteční nulový bod a následně jeden bod za den, připisovaný k **půlnoci následujícího dne**. `sum` a `state` jsou kumulativní objemy od začátku exportu, nikoliv skutečný stav vodoměru.

Po importu zkontrolujte `ovak:water_consumption` v HA → Nástroje pro vývojáře → Statistiky a následně Energy dashboard. Integrace OVAK Water pak může na stejnou statistiku navázat.

## Bezpečnost / omezení

- `--apply` bez `--confirm-new-statistic` nic nezapíše.
- Před zápisem se kontroluje, zda statistika již existuje; pokud ano, import se ukončí.
- Home Assistant ukládá statistiky asynchronně; potvrzený WebSocket požadavek ještě nemusí znamenat dokončený zápis do databáze.
- Při přerušení importu mohou být již některé dávky zapsané. **Nespouštějte znovu naslepo**: nejprve zkontrolujte Recorder a zálohu.
- Skript nepodporuje opravné ani inkrementální importy do existující statistiky; ty řeší integrace pro nové dny.
- Před migrací zkontrolujte, zda historická data odpovídají vašemu měřidlu a zda nejsou chybějící / duplicitní dny.
