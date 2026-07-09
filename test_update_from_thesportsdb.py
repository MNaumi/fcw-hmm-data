"""Tests für update_from_thesportsdb.py — Mapping-, Zeit- und Merge-Logik.
Aufruf: python3 -m unittest test_update_from_thesportsdb -v
"""
import unittest

from update_from_thesportsdb import (
    utc_to_local_iso,
    map_team,
    map_competition,
    event_to_match,
    merge,
    season_for,
)


def tsdb_event(**overrides):
    """Realistisches TheSportsDB-Event (Struktur wie eventsnext/eventslast/eventsseason)."""
    e = {
        "idEvent": "2492232",
        "strEvent": "Basel vs Winterthur",
        "strLeague": "Club Friendlies",
        "strHomeTeam": "Basel",
        "strAwayTeam": "Winterthur",
        "dateEvent": "2026-07-11",
        "strTime": "11:00:00",
        "strStatus": "NS",
        "intHomeScore": None,
        "intAwayScore": None,
        "strPostponed": "no",
    }
    e.update(overrides)
    return e


class TestZeitkonvertierung(unittest.TestCase):
    def test_sommerzeit(self):
        # 11:00 UTC am 11.07. = 13:00 MESZ
        self.assertEqual(utc_to_local_iso("2026-07-11", "11:00:00"),
                         "2026-07-11T13:00:00+02:00")

    def test_winterzeit(self):
        # 19:00 UTC am 05.12. = 20:00 MEZ
        self.assertEqual(utc_to_local_iso("2026-12-05", "19:00:00"),
                         "2026-12-05T20:00:00+01:00")


class TestTeamMapping(unittest.TestCase):
    def test_bekannte_teams(self):
        self.assertEqual(map_team("Stade Lausanne Ouchy"), "Stade Lausanne-Ouchy")
        self.assertEqual(map_team("Kriens"), "SC Kriens")
        self.assertEqual(map_team("Wil"), "FC Wil")
        self.assertEqual(map_team("Basel"), "FC Basel")
        self.assertEqual(map_team("St. Gallen"), "FC St. Gallen")

    def test_unbekanntes_team_unveraendert(self):
        self.assertEqual(map_team("Borussia Dortmund"), "Borussia Dortmund")


class TestCompetitionMapping(unittest.TestCase):
    def test_wettbewerbe(self):
        self.assertEqual(map_competition("Swiss Challenge League"), "Challenge League")
        self.assertEqual(map_competition("Swiss Cup"), "Schweizer Cup")
        self.assertEqual(map_competition("Club Friendlies"), "Testspiel")


class TestEventToMatch(unittest.TestCase):
    def test_auswaertsspiel(self):
        m = event_to_match(tsdb_event())
        self.assertEqual(m["opponent"], "FC Basel")
        self.assertFalse(m["isHome"])
        self.assertEqual(m["date"], "2026-07-11T13:00:00+02:00")
        self.assertEqual(m["competition"], "Testspiel")
        self.assertNotIn("homeScore", m)

    def test_heimspiel_mit_endergebnis(self):
        m = event_to_match(tsdb_event(
            strEvent="Winterthur vs St. Gallen",
            strHomeTeam="Winterthur", strAwayTeam="St. Gallen",
            dateEvent="2026-07-01", strTime="16:00:00",
            strStatus="FT", intHomeScore="0", intAwayScore="1"))
        self.assertTrue(m["isHome"])
        self.assertEqual(m["homeScore"], 0)
        self.assertEqual(m["awayScore"], 1)

    def test_laufendes_spiel_liefert_keinen_score(self):
        # Zwischenstände (2H etc.) nicht als Endergebnis übernehmen
        m = event_to_match(tsdb_event(strStatus="2H", intHomeScore="1", intAwayScore="0"))
        self.assertNotIn("homeScore", m)

    def test_ohne_winterthur_none(self):
        self.assertIsNone(event_to_match(tsdb_event(
            strHomeTeam="Aarau", strAwayTeam="Wil")))

    def test_mitternacht_utc_ist_platzhalter(self):
        m = event_to_match(tsdb_event(strTime="00:00:00"))
        self.assertTrue(m["timeTBD"])

    def test_verschobenes_spiel_gilt_als_tbd(self):
        m = event_to_match(tsdb_event(strPostponed="yes"))
        self.assertTrue(m["timeTBD"])


class TestMerge(unittest.TestCase):
    def bestehend_tbd(self):
        return [{
            "id": "A1000010-0000-0000-0000-000000000010",
            "opponent": "Neuchâtel Xamax",
            "date": "2026-10-10T12:00:00+02:00",
            "isHome": False,
            "competition": "Challenge League",
            "timeTBD": True,
        }]

    def test_tbd_zeit_wird_bestaetigt(self):
        incoming = [event_to_match(tsdb_event(
            strHomeTeam="Neuchâtel Xamax", strAwayTeam="Winterthur",
            dateEvent="2026-10-10", strTime="16:00:00"))]
        merged, changes = merge(self.bestehend_tbd(), incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["date"], "2026-10-10T18:00:00+02:00")
        self.assertNotIn("timeTBD", merged[0])
        # Bestehende ID bleibt erhalten
        self.assertEqual(merged[0]["id"], "A1000010-0000-0000-0000-000000000010")
        self.assertEqual(len(changes), 1)

    def test_tbd_bleibt_bei_platzhalterzeit(self):
        incoming = [event_to_match(tsdb_event(
            strHomeTeam="Neuchâtel Xamax", strAwayTeam="Winterthur",
            dateEvent="2026-10-10", strTime="00:00:00"))]
        merged, changes = merge(self.bestehend_tbd(), incoming)
        self.assertTrue(merged[0].get("timeTBD"))
        self.assertEqual(merged[0]["date"], "2026-10-10T12:00:00+02:00")
        self.assertEqual(changes, [])

    def test_match_auch_bei_nachbartag(self):
        # TBD steht auf Sa 10.10., SFL legt das Spiel auf So 11.10.
        incoming = [event_to_match(tsdb_event(
            strHomeTeam="Neuchâtel Xamax", strAwayTeam="Winterthur",
            dateEvent="2026-10-11", strTime="12:15:00"))]
        merged, _ = merge(self.bestehend_tbd(), incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["date"], "2026-10-11T14:15:00+02:00")

    def test_endergebnis_wird_nachgetragen(self):
        existing = [{
            "id": "A1000001-0000-0000-0000-000000000001",
            "opponent": "Yverdon Sport",
            "date": "2026-07-24T20:15:00+02:00",
            "isHome": True,
            "competition": "Challenge League",
        }]
        incoming = [event_to_match(tsdb_event(
            strHomeTeam="Winterthur", strAwayTeam="Yverdon Sport",
            dateEvent="2026-07-24", strTime="18:15:00",
            strStatus="FT", intHomeScore="2", intAwayScore="1"))]
        merged, changes = merge(existing, incoming)
        self.assertEqual(merged[0]["homeScore"], 2)
        self.assertEqual(merged[0]["awayScore"], 1)
        self.assertEqual(merged[0]["id"], "A1000001-0000-0000-0000-000000000001")
        self.assertEqual(len(changes), 1)

    def test_neues_spiel_wird_ergaenzt(self):
        incoming = [event_to_match(tsdb_event())]  # Basel-Testspiel, nicht in existing
        merged, changes = merge([], incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["opponent"], "FC Basel")
        self.assertIn("id", merged[0])
        self.assertEqual(len(changes), 1)

    def test_deterministische_id_fuer_neue_spiele(self):
        a, _ = merge([], [event_to_match(tsdb_event())])
        b, _ = merge([], [event_to_match(tsdb_event())])
        self.assertEqual(a[0]["id"], b[0]["id"])

    def test_bestehendes_wird_nie_geloescht(self):
        merged, changes = merge(self.bestehend_tbd(), [])
        self.assertEqual(len(merged), 1)
        self.assertEqual(changes, [])

    def test_namensvarianten_matchen(self):
        # "FC Basel" (App) vs. gemapptes TheSportsDB-"Basel" darf kein Duplikat erzeugen
        existing = [{
            "id": "FF204185-8803-484B-A27B-4F9C22527736",
            "opponent": "FC Basel",
            "date": "2026-07-11T13:00:00+02:00",
            "isHome": False,
            "competition": "Testspiel",
        }]
        merged, _ = merge(existing, [event_to_match(tsdb_event())])
        self.assertEqual(len(merged), 1)

    def test_ergebnis_sortiert_nach_datum(self):
        existing = [{
            "id": "X", "opponent": "FC Aarau",
            "date": "2026-09-18T20:15:00+02:00",
            "isHome": True, "competition": "Challenge League",
        }]
        merged, _ = merge(existing, [event_to_match(tsdb_event())])  # 11.07.
        self.assertEqual([m["opponent"] for m in merged], ["FC Basel", "FC Aarau"])


class TestSaison(unittest.TestCase):
    def test_saisonwechsel_im_juli(self):
        self.assertEqual(season_for(2026, 7), "2026-2027")
        self.assertEqual(season_for(2027, 1), "2026-2027")
        self.assertEqual(season_for(2027, 6), "2026-2027")
        self.assertEqual(season_for(2027, 7), "2027-2028")


if __name__ == "__main__":
    unittest.main()
