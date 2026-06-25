# FCW HMM – Daten

Diese Daten versorgen die **HMM-App**. `matches.json` (Spielplan) wird
**automatisch** aus dem offiziellen SFL-PDF erzeugt.

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
- `.github/workflows/update-schedule.yml` – die Automatik (GitHub Action)
- `matches.json` – wird erzeugt und von der App geladen
