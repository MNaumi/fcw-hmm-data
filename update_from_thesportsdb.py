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
import os
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
CUP_LEAGUE_ID = "5489"            # Swiss Cup
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


def _fixture_key(m):
    """Eindeutige Partie über die Saison: Gegner + Wettbewerb + Heim/Auswärts.
    (Jede Paarung findet pro Heimrecht genau einmal statt.)"""
    return (_norm(m["opponent"]), m.get("competition", ""), bool(m.get("isHome")))


def merge(existing, incoming):
    """Ergänzt existing um incoming. Löscht nie. -> (merged, Änderungsliste)"""
    merged = [dict(e) for e in existing]
    changes = []
    for inc in incoming:
        if inc is None:
            continue
        target = _find(merged, inc)
        if target is None:
            # Dubletten-Schutz: Gibt es dieselbe Partie bereits mit FIXEM Termin
            # (ohne timeTBD), aber >3 Tage entfernt, ist das kein neues Spiel,
            # sondern eine Terminabweichung -> nicht anlegen (detect_reschedules
            # meldet sie separat), sonst entstünde ein Geister-Duplikat.
            fk = _fixture_key(inc)
            if any(not e.get("timeTBD") and _fixture_key(e) == fk for e in merged):
                changes.append(f"nicht angelegt (Terminabweichung, siehe Hinweis): "
                               f"{inc['date'][:10]} {inc['opponent']}")
                continue
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


RESCHEDULE_TOLERANCE_DAYS = 3


def detect_reschedules(existing, incoming):
    """Findet fest terminierte Spiele (ohne timeTBD), für die eine Quelle einen
    um mehr als RESCHEDULE_TOLERANCE_DAYS abweichenden Termin meldet.

    Ändert NICHTS am Spielplan (die Quelle ist bekanntlich fehleranfällig) und
    gibt nur Verdachtsfälle zur manuellen Prüfung zurück. Kleine Abweichungen
    (<=3 Tage) gelten als Quellen-Rauschen und werden ignoriert."""
    firm = {}
    for e in existing:
        if e.get("timeTBD"):
            continue
        firm[_fixture_key(e)] = e
    seen, warnings = set(), []
    for inc in incoming:
        key = _fixture_key(inc)
        cur = firm.get(key)
        if cur is None or key in seen:
            continue
        if abs((_day(inc["date"]) - _day(cur["date"])).days) > RESCHEDULE_TOLERANCE_DAYS:
            seen.add(key)
            warnings.append({
                "opponent": cur["opponent"],
                "competition": cur["competition"],
                "current": cur["date"][:10],
                "source": inc["date"][:10],
            })
    return warnings


def format_hinweis(warnings):
    """(Commit-Nachricht, Dateiinhalt) für die Verdachtsfälle. Leer -> ('', '')."""
    if not warnings:
        return "", ""
    parts = [f"{w['opponent']} {w['current']}→{w['source']}" for w in warnings]
    summary = (f"⚠️ Mögliche Terminverschiebung ({len(warnings)}): "
               + "; ".join(parts) + " – bitte prüfen")
    detail = "\n".join(
        f"- {w['competition']}: {w['opponent']} steht in der App am {w['current']}, "
        f"die Datenquelle meldet {w['source']}." for w in warnings)
    return summary, summary + "\n\n" + detail + "\n"


def update_hinweis(path, warnings, dry_run):
    """Schreibt hinweis.txt (Verdachtsfälle) bzw. leert sie, wenn keine mehr da
    sind. Rückgabe: die Commit-Zeile (leer, wenn kein Hinweis)."""
    commit_line, content = format_hinweis(warnings)
    old = path.read_text() if path.exists() else ""
    if content != old:
        print(f"hinweis.txt: {'aktualisiert' if content else 'geleert'} "
              f"({len(warnings)} Verdachtsfälle)")
        if not dry_run:
            path.write_text(content)
    return commit_line


def compute_standings(events):
    """Tabelle (App-Teamname -> Rang) aus beendeten Ligaspielen.

    Der Gratis-Key liefert lookuptable nur gekappt (Top 5), deshalb rechnen
    wir selbst: 3 Punkte/Sieg, Tiebreak Tordifferenz, dann Tore, dann Name.
    Leer, solange noch kein Ligaspiel beendet ist.
    """
    stats = {}  # Name -> [Punkte, Tordifferenz, Tore]
    for e in events:
        if e.get("strLeague") != "Swiss Challenge League":
            continue
        if e.get("strStatus") not in FINAL_STATUSES:
            continue
        if e.get("intHomeScore") is None or e.get("intAwayScore") is None:
            continue
        hs, as_ = int(e["intHomeScore"]), int(e["intAwayScore"])
        home, away = map_team(e["strHomeTeam"]), map_team(e["strAwayTeam"])
        for team in (home, away):
            stats.setdefault(team, [0, 0, 0])
        stats[home][0] += 3 if hs > as_ else 1 if hs == as_ else 0
        stats[away][0] += 3 if as_ > hs else 1 if hs == as_ else 0
        stats[home][1] += hs - as_
        stats[away][1] += as_ - hs
        stats[home][2] += hs
        stats[away][2] += as_
    ranked = sorted(stats.items(),
                    key=lambda kv: (-kv[1][0], -kv[1][1], -kv[1][2], kv[0]))
    return {name: rank for rank, (name, _) in enumerate(ranked, start=1)}


def season_for(year, month):
    """Saison-String für TheSportsDB; Saisonwechsel im Juli."""
    return f"{year}-{year + 1}" if month >= 7 else f"{year - 1}-{year}"


# --- Netzwerk / Dateien -----------------------------------------------------

def _get(url):
    """Rückgabe: geparstes JSON, oder None bei Netz-/HTTP-Fehler (z.B. 429) -
    None ist absichtlich von {} (erfolgreiche, aber leere Antwort) unterscheidbar."""
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        print(f"WARNUNG: {url} nicht erreichbar ({e}) – übersprungen.")
        return None


def fetch_events():
    now = datetime.now(ZURICH)
    season = season_for(now.year, now.month)
    events = []
    events += (_get(f"{API}/eventsnext.php?id={TEAM_ID}") or {}).get("events") or []
    events += (_get(f"{API}/eventslast.php?id={TEAM_ID}") or {}).get("results") or []
    events += (_get(f"{API}/eventsseason.php?id={LEAGUE_ID}&s={season}") or {}).get("events") or []
    events += (_get(f"{API}/eventsseason.php?id={CUP_LEAGUE_ID}&s={season}") or {}).get("events") or []
    return events


def _round_events(data):
    """Events einer eventsround-Antwort, oder None, wenn `data` None ist (der
    Fetch ist fehlgeschlagen, z.B. 429) - im Unterschied zu einer echten,
    erfolgreich leeren Runde (data == {} oder data["events"] leer)."""
    if data is None:
        return None
    return data.get("events") or []


def _is_settled(events):
    """Eine Runde ist abgeschlossen, wenn JEDES Spiel darin ein Endergebnis
    hat - erst dann darf sie gecacht werden, sonst verpasst ein noch offenes
    Spiel (verschoben, läuft gerade) für immer sein Resultat."""
    return bool(events) and all(e.get("strStatus") in FINAL_STATUSES for e in events)


def fetch_league_events(cache=None):
    """Alle Ligaspiele der Saison rundenweise via eventsround.

    Nötig für eine korrekte Tabelle: Der Gratis-Key kappt eventsseason bei 15
    Einträgen (nur ~3 Runden), eventsround liefert pro Aufruf die volle Runde.
    Läuft die Runden hoch, bis zwei aufeinanderfolgende ECHT leer sind
    (Saisonende bzw. noch nicht terminierte Rückrunde) — ein Netz-/429-Fehler
    zählt dabei NICHT als Leer-Treffer (sonst brechen zwei zufällig
    rate-gelimitete Runden die Schleife ab und alle späteren Spieltage samt
    Resultaten fehlen dauerhaft), sondern wird einfach übersprungen.

    `cache` (season -> Rundennummer-String -> Events, siehe rounds_cache.json)
    hält bereits ABGESCHLOSSENE Runden fest: die werden nie wieder per HTTP
    abgefragt, nur noch die wenigen offenen/künftigen Runden. Das senkt die
    Zahl der eventsround-Aufrufe pro Lauf drastisch (Saisonmitte: statt ~20
    nur noch die ein, zwei gerade laufenden Runden) und damit die 429-Quote
    beim stark geteilten Gratis-Key. `cache` wird dabei um frisch
    abgeschlossene Runden ergänzt (Persistieren ist Sache von main())."""
    now = datetime.now(ZURICH)
    season = season_for(now.year, now.month)
    season_cache = cache.setdefault(season, {}) if cache is not None else {}
    events = []
    empty_streak = 0
    for r in range(1, 37):
        key = str(r)
        if key in season_cache:
            events += season_cache[key]
            empty_streak = 0
            continue
        rnd = _round_events(_get(f"{API}/eventsround.php?id={LEAGUE_ID}&r={r}&s={season}"))
        if rnd is None:
            continue  # Fetch-Fehler: kein Rundenende, weiter zur nächsten Runde
        if not rnd:
            empty_streak += 1
            if empty_streak >= 2:
                break
            continue
        empty_streak = 0
        events += rnd
        if _is_settled(rnd):
            season_cache[key] = rnd
    return events


def load_round_cache(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_round_cache(path, cache, dry_run):
    if not dry_run:
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")


def collect_matches(events, league_events):
    """Match-Liste für Datei-Updates UND Verschiebungs-Check aus beiden
    TheSportsDB-Quellen: `events` (next/last/season - vom Gratis-Key gekappt:
    eventsseason bricht nach 15 Einträgen ab, eventslast liefert inzwischen
    oft nur noch das jeweils letzte Spiel) und `league_events` (vollständige
    Liga-Runden via eventsround). Nur mit beiden Quellen werden Resultate
    zuverlässig erfasst - sonst kann ein Resultat dauerhaft verpasst werden,
    sobald ein neueres Spiel es aus eventslast verdrängt, bevor der Workflow
    dazwischen lief."""
    matches = [m for m in map(event_to_match, events + league_events) if m]
    merged, _ = merge([], matches)
    for m in merged:
        m.pop("id", None)
    return merged


def update_file(path, incoming, dry_run):
    existing = json.loads(path.read_text()) if path.exists() else []
    merged, changes = merge(existing, incoming)
    for c in changes:
        print(f"{path.name}: {c}")
    if changes and not dry_run:
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    return bool(changes)


def standings_trustworthy(league_matches, league_events):
    """Nur True, wenn `league_events` mindestens so viele unterschiedliche
    Ligarunden abdeckt, wie laut bereits bekannten FCW-Ligaresultaten
    (`league_matches`, aus matches.json) gespielt sein müssten. Verhindert,
    dass ein Lauf, der wegen Rate-Limiting nur einen Bruchteil der Runden
    abrufen konnte, eine Tabelle schreibt, die auf zu wenigen Runden basiert
    und damit falsch wäre."""
    expected = sum(1 for m in league_matches
                   if m.get("competition") == "Challenge League"
                   and m.get("homeScore") is not None)
    have = len({e.get("intRound") for e in league_events if e.get("intRound") is not None})
    return have >= expected


def update_standings(path, table, dry_run):
    """Schreibt die Tabelle als Snapshot; leere Tabelle lässt die Datei unangetastet."""
    if not table:
        print("Tabelle: keine beendeten Ligaspiele – unverändert.")
        return False
    old = json.loads(path.read_text()) if path.exists() else None
    if old == table:
        return False
    print(f"standings.json: Tabelle aktualisiert ({len(table)} Teams)")
    if not dry_run:
        path.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n")
    return True


def main():
    dry_run = "--dry-run" in sys.argv
    root = Path(__file__).parent
    cache_path = root / "rounds_cache.json"
    round_cache = load_round_cache(cache_path)
    cache_before = json.dumps(round_cache, sort_keys=True)

    events = fetch_events()
    league_events = fetch_league_events(round_cache)   # volle Liga (eventsround) für Tabelle + Verschiebungs-Check
    matches = collect_matches(events, league_events)

    tests = [m for m in matches if m["competition"] == "Testspiel"]
    league = [m for m in matches if m["competition"] != "Testspiel"]

    # Verdacht auf echte Terminverschiebung fester Spiele (Cup aus events,
    # Liga vollständig aus eventsround). Meldet nur, ändert den Plan nicht.
    incoming = matches
    existing_matches = (json.loads((root / "matches.json").read_text())
                        if (root / "matches.json").exists() else [])
    warnings = detect_reschedules(existing_matches, incoming)
    commit_line = update_hinweis(root / "hinweis.txt", warnings, dry_run)
    for w in warnings:
        print(f"HINWEIS: {w['opponent']} App {w['current']} vs. Quelle {w['source']}")

    changed = update_file(root / "matches.json", league, dry_run)
    changed |= update_file(root / "testspiele.json", tests, dry_run)

    # Für den Vertrauens-Check den VOLLEN Stand nehmen (bestehende matches.json
    # + diesmal neu Gefundenes) - nicht nur `league`, das nur die in DIESEM
    # Lauf frisch abgerufenen Spiele enthält und bei Rate-Limiting fast leer
    # sein kann, was den Check sonst wirkungslos macht.
    full_league, _ = merge(existing_matches, league)
    if standings_trustworthy(full_league, league_events):
        changed |= update_standings(root / "standings.json",
                                    compute_standings(league_events), dry_run)
    else:
        print("Tabelle: zu wenige Ligarunden abgerufen (Rate-Limit?) – "
              "unverändert, um keine unvollständige Tabelle zu schreiben.")

    if json.dumps(round_cache, sort_keys=True) != cache_before:
        n = sum(len(v) for v in round_cache.values())
        print(f"rounds_cache.json: {n} abgeschlossene Runde(n) gecacht.")
        save_round_cache(cache_path, round_cache, dry_run)
        changed = True

    if commit_line:
        # Commit-Nachricht für den Workflow (die App zeigt sie auf der
        # Datenstatus-Seite an). Über GITHUB_OUTPUT, falls in der Action.
        out = os.environ.get("GITHUB_OUTPUT")
        if out and not dry_run:
            with open(out, "a", encoding="utf-8") as f:
                f.write(f"commit_message<<HINWEIS_EOF\n{commit_line}\nHINWEIS_EOF\n")
        print("COMMIT-NACHRICHT:", commit_line)

    if not changed and not commit_line:
        print("Keine Änderungen.")
    elif dry_run:
        print("Dry-Run: Änderungen gefunden, nichts geschrieben.")
    else:
        print("Änderungen geschrieben.")


if __name__ == "__main__":
    main()
