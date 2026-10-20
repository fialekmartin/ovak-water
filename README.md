# OVAK Water for Home Assistant

Neoficiální vlastní integrace pro **Home Assistant OS / Home Assistant Core**. Čte denní spotřebu vody z OVAK přes zákaznický portál ZIS a SSO do eMIS. Zdroj inspirace pro přihlašovací postup: [Node-RED_OVAK](https://github.com/Meridian85/Node-RED_OVAK).

> **Stav:** `0.1.4`, komunitní neoficiální integrace, testovaná v konkrétní instalaci uživatele. Není schválená ani podporovaná OVAK. Změny na portálu mohou přístup rozbít.

## Funkce

- Přihlášení uživatelským jménem a heslem do ZIS OVAK, přechod přes SSO do eMIS.
- Jednou denně synchronizace v **nastavitelný čas** v časové zóně Home Assistantu (výchozí `06:00`).
- Senzor **Včerejší spotřeba** v m³; poslední hodnota se obnoví po restartu i změně konfigurace bez kontaktování portálu.
- Doplnění nových denních statistik do existující externí řady `ovak:water_consumption` (Energy dashboard).
- Jednorázová **automatická migrace historie** přes `tools/migrate_history.py` (ZIS/SSO → validace → Recorder; dry-run) nebo import ze souboru `tools/import_history.py`.

## Důležité: historická statistika je podmínka

Integrace **nevytváří počáteční historii automaticky**. Pro jednorázový import použijte nástroj v `tools/import_history.py` podle [návodu](docs/HISTORY_IMPORT.md). Před první synchronizací musí v Recorderu existovat externí statistika s ID `ovak:water_consumption`, jejíž denní hodnoty jsou přiřazeny k půlnoci **následujícího dne** a průběžný součet (`sum`) odpovídá již importované historii. Jinak integrace zaznamená chybu a nic nezapíše.

Nepropojujte stejnou spotřebu současně s další kumulativní statistikou – mohlo by dojít k dvojímu vykazování. Před testováním si vytvořte zálohu HA.

## Import historie

**Doporučená varianta bez cookies:** [Automatické stažení a import](docs/AUTOMATED_MIGRATION.md).

Ruční import z JSON: [docs/HISTORY_IMPORT.md](docs/HISTORY_IMPORT.md).

## Instalace (ruční)

1. Zkopírujte adresář `custom_components/ovak` do `/config/custom_components/ovak`.
2. Restartujte Home Assistant.
3. V **Nastavení → Zařízení a služby → Přidat integraci** vyhledejte **OVAK Water**.
4. Zadejte údaje pro ZIS OVAK.
5. V **Konfigurovat** nastavte čas denní synchronizace.
6. V **Nástroje pro vývojáře → Stavy** sledujte `sensor.ovak_water_vcerejsi_spotreba`.

Přístupové údaje se ukládají do konfiguračního záznamu HA. **Nevkládejte je do repozitáře, issue, logů ani exportovaného HAR.**

### HACS (custom repository)

V HACS otevřete nabídku **Custom repositories**, vložte URL svého GitHub repozitáře, zvolte kategorii **Integration** a nainstalujte. Následně restartujte HA a přidejte integraci. Nejde o publikaci ve výchozím katalogu HACS.

## Aktualizace

Přepište `custom_components/ovak`, restartujte Home Assistant. Stávající konfiguraci ani historii není nutné mazat.

## Omezení

- Pravidelná synchronizace probíhá v určený čas, **ne ihned po restartu**.
- První senzor zůstává nedostupný do synchronizace, pokud ještě nemá uloženou hodnotu.
- Opravy historických odečtů nejsou implementovány.
- Při velkém historickém skluzu se zpracovává omezené období (max. 31 dnů na cyklus).
- Autentizace může přestat fungovat při změně portálu, CAPTCHA nebo SSO.
- Skript a komponenta neposkytují oficiální API OVAK.

## Diagnostika

V HA otevřete **Nastavení → Systém → Protokoly** a filtrujte `custom_components.ovak`. Další diagnostické logování lze zapnout přes:

```yaml
logger:
  logs:
    custom_components.ovak: debug
```

Nikdy nezveřejňujte kompletní HAR ani hodnoty session cookies či autentizačních URL.

## Vývoj a ověření

```bash
python3 -m compileall -q custom_components/ovak
python3 -m json.tool custom_components/ovak/manifest.json >/dev/null
```

Vlastní integrace používá interní Recorder API Home Assistantu, proto doporučujeme ověřit kompatibilitu při aktualizacích Home Assistant Core.

## Licence

MIT – viz [LICENSE](LICENSE). Tento repozitář není spojený s OVAK ani SUEZ.
