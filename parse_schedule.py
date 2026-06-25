#!/usr/bin/env python3
"""Parst das offizielle SFL dieci-Challenge-League-PDF -> matches.json (HMM-App).
Aufruf: python3 parse_schedule.py <pdf> <output.json>
"""
import sys, re, json
from datetime import datetime, timedelta
from pypdf import PdfReader

TEAM = "FC Winterthur"
NAME_MAP = {
    "Yverdon Sport FC": "Yverdon Sport", "FC Wil 1900": "FC Wil",
    "FC Rapperswil-Jona": "Rapperswil-Jona", "FC Stade-Lausanne-Ouchy": "Stade Lausanne-Ouchy",
    "FC Stade Nyonnais": "Stade Nyonnais", "Neuchâtel Xamax FCS": "Neuchâtel Xamax",
    "Etoile Carouge FC": "Étoile Carouge", "FC Aarau": "FC Aarau", "SC Kriens": "SC Kriens",
    "FC Winterthur": "FC Winterthur",
}
def _last_sunday(year, month):
    from calendar import monthrange
    d = datetime(year, month, monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() + 1) % 7)

def offset(dt):
    """Mitteleuropäische Sommerzeit: letzter So März 02:00 .. letzter So Okt 03:00 -> +02:00, sonst +01:00."""
    start = _last_sunday(dt.year, 3).replace(hour=2)
    end = _last_sunday(dt.year, 10).replace(hour=3)
    return "+02:00" if start <= dt < end else "+01:00"

def clean(name):
    name = re.sub(r'\s+blue\s*$', '', name.strip()).strip()
    return NAME_MAP.get(name, name)

def strip_leading(s):
    """Entfernt führende Datum-/Range-/Wochentag-/Zeit-Tokens, übrig bleibt das Heimteam."""
    pat = re.compile(
        r'^\s*('
        r'\d{2}\.-\d{2}\.\d{2}\.\d{2}'   # 18.-20.12.26
        r'|\d{2}\.\d{2}\.\d{4}'          # 24.07.2026
        r'|\d{2}\.\d{2}\.\d{2}'          # 30.10.26
        r'|\d{2}\.-\d{2}\.'              # 09.-11.10. (Rest)
        r'|\d{2}\.\d{2}\.'               # 30.10.
        r'|\d{2}\.'                      # 18.
        r'|Fri-Sun|Mon|Tue|Wed|Thu|Fri|Sat|Sun'
        r'|\d{2}:\d{2}'                  # 20:15
        r'|\d{4}|\d{2}'                  # Jahres-Reste 2026 / 26
        r'|-)\s*')
    while True:
        new = pat.sub('', s)
        if new == s:
            return s.strip()
        s = new

def extract_text(path):
    return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)

def parse(path):
    lines = extract_text(path).splitlines()
    season_year = 2026
    m0 = re.search(r'\d{2}\.\d{2}\.(\d{4})', "\n".join(lines))
    if m0: season_year = int(m0.group(1))

    matches, current_sat = [], None
    for line in lines:
        if "–" not in line:
            continue
        left, right = line.split("–", 1)
        home, away = strip_leading(left), clean(right)

        exact = re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s+\w{3}\s+(\d{2}):(\d{2})', line)
        is_range = re.search(r'\d{2}\.-\d{2}\.|\d{2}\.\d{2}\.\s*-|Fri-Sun', line)

        if exact:
            dd, mo, yyyy, hh, mm = map(int, exact.groups())
            dt = datetime(yyyy, mo, dd, hh, mm)
            tbd, date = False, dt.strftime("%Y-%m-%dT%H:%M:%S") + offset(dt)
        else:
            if is_range:
                r1 = re.search(r'(\d{2})\.-\d{2}\.(\d{2})\.', line)      # 09.-11.10.
                r2 = re.search(r'(\d{2})\.(\d{2})\.\s*-', line)           # 30.10. -
                if r1:   fri = datetime(season_year, int(r1.group(2)), int(r1.group(1)))
                elif r2: fri = datetime(season_year, int(r2.group(2)), int(r2.group(1)))
                else:    fri = None
                if fri: current_sat = fri + timedelta(days=1)
            if current_sat is None:
                continue
            tbd = True
            date = current_sat.strftime("%Y-%m-%dT12:00:00") + offset(current_sat)

        if TEAM not in (home, away):
            continue
        is_home = (home == TEAM)
        matches.append({"opponent": away if is_home else home,
                        "isHome": is_home, "timeTBD": tbd, "date": date})
    return matches

def to_app_json(matches):
    out = []
    for idx, m in enumerate(sorted(matches, key=lambda x: x["date"]), start=1):
        e = {"id": f"A{idx:07d}-0000-0000-0000-{idx:012d}",
             "opponent": clean(m["opponent"]), "date": m["date"],
             "isHome": m["isHome"], "competition": "Challenge League"}
        if m["timeTBD"]: e["timeTBD"] = True
        out.append(e)
    return out

if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "schedule.pdf"
    out = sys.argv[2] if len(sys.argv) > 2 else "matches.json"
    app = to_app_json(parse(pdf))
    print(f"Gefundene FCW-Spiele: {len(app)}")
    for m in app:
        print(f"  {m['date'][:10]} {m['date'][11:16]} {'H' if m['isHome'] else 'A'}  {m['opponent']:24}{' (TBD)' if m.get('timeTBD') else ''}")
    json.dump(app, open(out, "w"), ensure_ascii=False, indent=2)
    print("->", out)
