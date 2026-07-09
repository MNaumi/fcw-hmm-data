#!/usr/bin/env python3
"""Reichert matches.json und testspiele.json mit Daten von TheSportsDB an.

Ergänzt, überschreibt aber nie destruktiv:
- bestätigt Anstoßzeiten von timeTBD-Spielen, sobald sie feststehen
- trägt Endergebnisse abgeschlossener Spiele nach (homeScore/awayScore)
- ergänzt neue Spiele (Testspiele, Cup), die noch nicht erfasst sind
Bestehende Einträge und ihre IDs bleiben erhalten; das SFL-PDF bleibt die
maßgebliche Quelle für den Liga-Spielplan.

Aufruf: python3 update_from_thesportsdb.py [--dry-run]
"""
import json
import sys
import unicodedata
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TEAM_TSDB = "Winterthur"          # Teamname bei TheSportsDB
TEAM_ID = "138984"                # FC Winterthur
LEAGUE_ID = "4713"                # Swiss Challenge League
API = "https://www.thesportsdb.com/api/v1/json/123"
ZURICH = ZoneInfo("Europe/Zurich")

# TheSportsDB-Name -> Name in der App
NAME_MAP = {
    "Winterthur": "FC Winterthur",
    "Stade Lausanne Ouchy": "Stade Lausanne-Ouchy",
    "Kriens": "SC Kriens",
    "Wil": "FC Wil",
    "Aarau": "FC Aarau",
    "Basel": "FC Basel",
    "St. Gallen": "FC St. Gallen",
    "Luzern": "FC Luzern",
    "Union Berlin": "FC Union Berlin",
}

COMPETITION_MAP = {
    "Swiss Challenge League": "Challenge League",
    "Swiss Cup": "Schweizer Cup",
    "Club Friendlies": "Testspiel",
}

FINAL_STATUSES = {"FT", "AET", "PEN", "Match Finished"}


def utc_to_local_iso(date_event, str_time):
    """TheSportsDB liefert UTC -> ISO8601 mit Zürcher Offset."""
    dt = datetime.fromisoformat(f"{date_event}T{str_time}")
    return dt.replace(tzinfo=timezone.utc).astimezone(ZURICH).isoformat(timespec="seconds")


def map_team(name):
    return NAME_MAP.get(name, name)


def map_competition(str_league):
    return COMPETITION_MAP.get(str_league, str_league)


def event_to_match(event):
    """TheSportsDB-Event -> Match-Dict im App-Format; None ohne FCW-Beteiligung."""
    home, away = event.get("strHomeTeam"), event.get("strAwayTeam")
    if TEAM_TSDB not in (home, away):
        return None
    is_home = home == TEAM_TSDB

    time = event.get("strTime") or "00:00:00"
    tbd = time == "00:00:00" or event.get("strPostponed") == "yes"
    if tbd:
        # Konvention wie im PDF-Parser: Platzhalter 12:00 Ortszeit
        date = datetime.fromisoformat(f"{event['dateEvent']}T12:00:00") \
            .replace(tzinfo=ZURICH).isoformat(timespec="seconds")
    else:
        date = utc_to_local_iso(event["dateEvent"], time)

    match = {
        "opponent": map_team(away if is_home else home),
        "date": date,
        "isHome": is_home,
        "competition": map_competition(event.get("strLeague") or ""),
    }
    if tbd:
        match["timeTBD"] = True
    if (event.get("strStatus") in FINAL_STATUSES
            and event.get("intHomeScore") is not None
            and event.get("intAwayScore") is not None):
        match["homeScore"] = int(event["intHomeScore"])
        match["awayScore"] = int(event["intAwayScore"])
    return match


def _norm(name):
    """Namen für den Vergleich normalisieren: Akzente, FC/SC-Präfixe, Bindestriche."""
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    for prefix in ("fc ", "sc "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    s = s.replace("-", " ").replace(".", "")
    return " ".join(s.split())


def _day(iso):
    return datetime.fromisoformat(iso).date()


def _find(entries, incoming):
    """Bestehenden Eintrag zum selben Spiel finden: gleicher Gegner, ±3 Tage."""
    for e in entries:
        if _norm(e["opponent"]) != _norm(incoming["opponent"]):
            continue
        if abs((_day(e["date"]) - _day(incoming["date"])).days) <= 3:
            return e
    return None


def _new_id(match):
    """Deterministische UUID aus Spieltag+Gegner, stabil über Läufe hinweg."""
    key = f"fcw-hmm:{match['date'][:10]}:{_norm(match['opponent'])}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key)).upper()


def merge(existing, incoming):
    """Ergänzt existing um incoming. Löscht nie. -> (merged, Änderungsliste)"""
    merged = [dict(e) for e in existing]
    changes = []
    for inc in incoming:
        if inc is None:
            continue
        target = _find(merged, inc)
        if target is None:
            entry = {"id": _new_id(inc), **inc}
            merged.append(entry)
            changes.append(f"neu: {entry['date'][:10]} {entry['opponent']} ({entry['competition']})")
            continue
        if target.get("timeTBD") and not inc.get("timeTBD"):
            target["date"] = inc["date"]
            target.pop("timeTBD", None)
            changes.append(f"Anstoßzeit fix: {inc['date']} {target['opponent']}")
        if "homeScore" in inc and (target.get("homeScore"), target.get("awayScore")) \
                != (inc["homeScore"], inc["awayScore"]):
            target["homeScore"] = inc["homeScore"]
            target["awayScore"] = inc["awayScore"]
            changes.append(f"Resultat: {target['opponent']} {inc['homeScore']}:{inc['awayScore']}")
    merged.sort(key=lambda m: datetime.fromisoformat(m["date"]))
    return merged, changes


def season_for(year, month):
    """Saison-String für TheSportsDB; Saisonwechsel im Juli."""
    return f"{year}-{year + 1}" if month >= 7 else f"{year - 1}-{year}"


# --- Netzwerk / Dateien -----------------------------------------------------

def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        print(f"WARNUNG: {url} nicht erreichbar ({e}) – übersprungen.")
        return {}


def fetch_events():
    now = datetime.now(ZURICH)
    season = season_for(now.year, now.month)
    events = []
    events += _get(f"{API}/eventsnext.php?id={TEAM_ID}").get("events") or []
    events += _get(f"{API}/eventslast.php?id={TEAM_ID}").get("results") or []
    events += _get(f"{API}/eventsseason.php?id={LEAGUE_ID}&s={season}").get("events") or []
    return events


def update_file(path, incoming, dry_run):
    existing = json.loads(path.read_text()) if path.exists() else []
    merged, changes = merge(existing, incoming)
    for c in changes:
        print(f"{path.name}: {c}")
    if changes and not dry_run:
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    return bool(changes)


def main():
    dry_run = "--dry-run" in sys.argv
    root = Path(__file__).parent
    matches = [m for m in map(event_to_match, fetch_events()) if m]
    # Duplikate über die drei Endpunkte hinweg zusammenführen
    matches, _ = merge([], matches)
    for m in matches:
        m.pop("id", None)

    tests = [m for m in matches if m["competition"] == "Testspiel"]
    league = [m for m in matches if m["competition"] != "Testspiel"]

    changed = update_file(root / "matches.json", league, dry_run)
    changed |= update_file(root / "testspiele.json", tests, dry_run)
    if not changed:
        print("Keine Änderungen.")
    elif dry_run:
        print("Dry-Run: Änderungen gefunden, nichts geschrieben.")
    else:
        print("Änderungen geschrieben.")


if __name__ == "__main__":
    main()
