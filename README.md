# FCW HMM – Daten

Diese Daten versorgen die **HMM-App**. `matches.json` (Spielplan) wird
**automatisch** aus dem offiziellen SFL-PDF erzeugt und zusammen mit
`testspiele.json` **zweimal täglich** von TheSportsDB angereichert.

## 🤖 Vollautomatik (läuft ohne Zutun)

Die Action `update-from-thesportsdb.yml` läuft täglich um 05:00 und 22:30 UTC
und gleicht mit [TheSportsDB](https://www.thesportsdb.com) ab:

- **Anstoßzeiten**: Sobald die SFL ein „Wochenende offen"-Spiel (timeTBD)
  terminiert, wird die Zeit automatisch eingetragen.
- **Resultate**: Endstände abgeschlossener Spiele landen als
  `homeScore`/`awayScore` in den JSON-Dateien.
- **Neue Spiele**: Noch nicht erfasste Testspiele und Cup-Partien werden ergänzt.

Dabei wird **nie etwas gelöscht** – bestehende Einträge, IDs und manuelle
Korrekturen bleiben erhalten. Das SFL-PDF bleibt die maßgebliche Quelle für
den Liga-Spielplan; TheSportsDB ergänzt nur.

## 🔄 Spielplan aktualisieren – Schritt für Schritt

**Der einfachste Weg:** Malte schickt das neue PDF an Claude → erledigt per CLI.

**Selbst über die Website:**
1. Neues offizielles **SFL-PDF** herunterladen (dieci Challenge League Spielplan).
2. Auf dem Mac die Datei umbenennen in **`schedule.pdf`** (exakt dieser Name!).
3. Hier im Repo oben **„Add file" → „Upload files"**.
4. Die `schedule.pdf` reinziehen (überschreibt die alte).
5. Unten grün **„Commit changes"**.
6. Fertig ✅ – im Tab **„Actions"** läuft die Automatik ~15 Sek und aktualisiert
   `matches.json`. Die App zeigt den neuen Spielplan beim nächsten Start.

> Wichtig: Der Dateiname muss **`schedule.pdf`** sein – sonst startet die Action nicht.

## Dateien
- `schedule.pdf` – offizielles SFL-PDF (Quelle)
- `parse_schedule.py` – Parser (PDF → matches.json)
- `update_from_thesportsdb.py` – Anreicherung (Zeiten, Resultate, neue Spiele)
- `test_update_from_thesportsdb.py` – Tests (`python3 -m unittest`)
- `.github/workflows/update-schedule.yml` – Automatik PDF → matches.json
- `.github/workflows/update-from-thesportsdb.yml` – tägliche Anreicherung
- `matches.json` / `testspiele.json` – werden von der App geladen
