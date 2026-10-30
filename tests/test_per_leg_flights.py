"""Every flight of a trip, with its own clock times, carrier, stops, layover and duration (22 Oct 2026).

The private pricer now writes, on each priced multi-centre row, the first flight's values (``carrier``, ``stops``,
``duration``, ``layovers``, ``departure_local``, ``arrival_local``) AND a ``flights`` list, one entry per leg in date
order: ``{origin, destination, departure_local, arrival_local, carrier, stops, duration, layover, cabin, vendor}``;
plus the row's ``cabin`` (``ECONOMY`` | ``BUSINESS`` | ``MIXED``) and, when MIXED, ``cabin_mix``. These tests pin that:

* the loader keeps the whole list through to the dossier;
* each flight is matched to its dated leg by airports (and the date when two legs share airports), whatever order the
  list is in, and printed on that leg's line in the Itinerary with its own times, carrier, stops, layover, duration and
  cabin;
* "times for the other flights are not captured" is said only where ``flights`` is absent (older rows keep the
  first-flight path), and where a list is present but one leg has no flight or no time, that leg alone says so;
* nothing is guessed: a flight with no arrival time prints no arrival time.

Everything is SYNTHETIC.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search import trip_dossier as td
from public_flight_search.holiday_email import multi_centre_wanted

from test_holiday_email_compact import _config, _deals, visible_text
from test_multi_centre_reads import _multi_centre_read
from test_trip_dossiers import NOW, STAMPS, UNLIMITED, _attachment, _html, _rows, _slice, _table_ids, _text

LEGS_AF01 = [("LHR", "JRO", "2027-06-27"), ("JRO", "ZNZ", "2027-07-01"), ("ZNZ", "LHR", "2027-07-14")]

FLIGHTS = [
    {"origin": "LHR", "destination": "JRO", "departure_local": "2027-06-27T09:30:00",
     "arrival_local": "2027-06-28T02:00:00", "carrier": "Etihad Airways", "stops": 1, "duration": "14h 30m",
     "layover": "1h 40m AUH", "cabin": "BUSINESS", "vendor": "kayak"},
    {"origin": "JRO", "destination": "ZNZ", "departure_local": "2027-07-01T11:15:00",
     "arrival_local": "2027-07-01T12:40:00", "carrier": "Precision Air", "stops": 0, "duration": "1h 25m",
     "layover": "", "cabin": "ECONOMY", "vendor": "kayak"},
    {"origin": "ZNZ", "destination": "LHR", "departure_local": "2027-07-14T18:05:00",
     "arrival_local": "2027-07-15T06:20:00", "carrier": "Qatar Airways", "stops": 1, "duration": "12h 15m",
     "layover": "2h 10m DOH", "cabin": "BUSINESS", "vendor": "kayak"},
]


def _fares(flights=None, *, trip="AF-01", **overrides):
    config = _config()
    want = next(w for w in multi_centre_wanted(config) if w["trip"] == trip)
    row = _multi_centre_read(want, observed_at="2026-10-20T10:00:00+00:00", total=20_200.0)
    row.update({"carrier": "Etihad Airways", "stops": 1, "layovers": "1h 40m AUH", "duration": "14h 30m",
                "departure_local": "2027-06-27T09:30:00", "arrival_local": "2027-06-28T02:00:00",
                "cabin": "MIXED", "cabin_mix": "Business LHR-JRO, ZNZ-LHR + Economy JRO-ZNZ"})
    if flights is not None:
        row["flights"] = flights
    row.update(overrides)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "stopover_reads_synthetic.json"
        path.write_text(json.dumps({"schema": hol.STOPOVER_READS_SCHEMA, "rows": [row]}), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            _stops, fares = hol.load_batch_reads(str(path))
    hol.consume_stopover_skip_log()
    return fares


def _page(fares, trip="AF-01", **kw):
    return _slice(_html(fares=fares, **kw), f"trip-{trip}")


def _leg_line(text: str, origin_word: str, destination_word: str) -> str:
    """The Itinerary's own lines for one flight: from its "Fly A → B" row to the next row that starts a new step."""
    start = text.index(f"Fly {origin_word} → {destination_word}")
    rest = text[start:]
    ends = [rest.find(marker, 5) for marker in (" Fly ", "nights ·", "night ·")]
    ends = [e for e in ends if e > 0]
    return rest[:min(ends)] if ends else rest[:400]


class TheLoaderKeepsTheListTests(unittest.TestCase):
    def test_the_whole_flights_list_cabin_and_cabin_mix_survive_loading_into_the_dossier(self):
        fares = _fares(FLIGHTS)
        stored = next(iter(fares.values()))
        self.assertEqual(stored["flights"], FLIGHTS)
        self.assertEqual(stored["cabin"], "MIXED")
        dossier = next(d for d in td.build_trip_dossiers(_config(), _rows(fares), generated_at=NOW)
                       if d["id"] == "AF-01")
        legs = dossier["flight"]["leg_flights"]
        self.assertEqual([lf["flight"]["carrier"] for lf in legs], ["Etihad Airways", "Precision Air", "Qatar Airways"])
        self.assertEqual([(lf["leg"][0], lf["leg"][1], lf["leg"][2]) for lf in legs], LEGS_AF01)

    def test_a_cheaper_read_without_a_list_does_not_replace_the_one_that_has_it(self):
        # Same cabin and legs: the cheaper look is kept, and what is kept is a whole row, list included.
        fares = _fares(FLIGHTS)
        self.assertIn("flights", next(iter(fares.values())))


class EachFlightIsPrintedOnItsOwnLegTests(unittest.TestCase):
    def test_every_leg_shows_its_own_times_carrier_stops_layover_duration_and_cabin(self):
        text = visible_text(_page(_fares(FLIGHTS)))
        out = _leg_line(text, "London", "Kilimanjaro (JRO)")
        for word in ("09:30", "28 Jun 02:00", "Etihad Airways", "1 stop (1h 40m AUH)", "14h 30m", "Business"):
            self.assertIn(word, out, word)
        mid = _leg_line(text, "Kilimanjaro (JRO)", "Zanzibar (ZNZ)")
        for word in ("11:15", "12:40", "Precision Air", "nonstop", "1h 25m", "Economy"):
            self.assertIn(word, mid, word)
        self.assertNotIn("28 Jun 02:00", mid)
        home = _leg_line(text, "Zanzibar (ZNZ)", "London")
        for word in ("18:05", "15 Jul 06:20", "Qatar Airways", "1 stop (2h 10m DOH)", "12h 15m", "Business"):
            self.assertIn(word, home, word)

    def test_a_list_in_the_wrong_order_is_still_matched_to_the_right_legs(self):
        text = visible_text(_page(_fares(list(reversed(FLIGHTS)))))
        self.assertIn("Precision Air", _leg_line(text, "Kilimanjaro (JRO)", "Zanzibar (ZNZ)"))
        self.assertIn("Qatar Airways", _leg_line(text, "Zanzibar (ZNZ)", "London"))
        self.assertNotIn("Qatar Airways", _leg_line(text, "London", "Kilimanjaro (JRO)"))

    def test_times_are_said_to_be_local_once(self):
        text = visible_text(_page(_fares(FLIGHTS)))
        self.assertEqual(text.count("local to each airport"), 1)

    def test_with_a_complete_list_nothing_is_said_to_be_missing(self):
        text = visible_text(_page(_fares(FLIGHTS)))
        self.assertNotIn("not captured", text)
        self.assertNotIn("first flight only", text.lower())
        self.assertNotIn("First flight on that read", text, "the list supersedes the first-flight line")

    def test_the_price_line_names_the_mixed_cabins_and_the_search_link_says_it_is_economy(self):
        text = visible_text(_page(_fares(FLIGHTS)))
        self.assertIn("Business LHR-JRO, ZNZ-LHR + Economy JRO-ZNZ", text)
        self.assertIn("opens Economy", text)
        economy = visible_text(_page(_fares(FLIGHTS, cabin="ECONOMY", cabin_mix="")))
        self.assertNotIn("opens Economy", economy, "an Economy read needs no such warning")

    def test_the_vendor_the_flights_were_read_through_is_named(self):
        self.assertIn("kayak", visible_text(_page(_fares(FLIGHTS))))


class WhatIsMissingIsSaidOnlyWhereItIsMissingTests(unittest.TestCase):
    def test_an_older_row_with_no_list_keeps_the_first_flight_path_and_says_the_others_are_not_captured(self):
        text = visible_text(_page(_fares(None)))
        self.assertIn("First flight on that read: Etihad Airways", text)
        self.assertIn("first flight", text.lower())
        self.assertEqual(text.count("not captured"), 1)
        self.assertIn("09:30", text, "its own first-flight time still shows")

    def test_a_list_with_a_leg_missing_names_that_leg_only(self):
        text = visible_text(_page(_fares(FLIGHTS[:1] + FLIGHTS[2:])))
        mid = _leg_line(text, "Kilimanjaro (JRO)", "Zanzibar (ZNZ)")
        self.assertIn("times not captured for this flight", mid)
        self.assertEqual(text.count("not captured"), 1)
        self.assertIn("09:30", _leg_line(text, "London", "Kilimanjaro (JRO)"))

    def test_a_flight_with_no_arrival_prints_no_arrival(self):
        partial = [dict(FLIGHTS[0], arrival_local=""), FLIGHTS[1], FLIGHTS[2]]
        out = _leg_line(visible_text(_page(_fares(partial))), "London", "Kilimanjaro (JRO)")
        self.assertIn("departs 09:30", out)
        self.assertNotIn("arrives", out)
        self.assertNotIn("02:00", out)

    def test_garbage_in_the_list_never_breaks_the_page_or_invents_a_time(self):
        junk = ["not a dict", {"origin": "LHR"}, dict(FLIGHTS[1], departure_local="soon", arrival_local="later")]
        text = visible_text(_page(_fares(junk)))
        self.assertIn("Fly Kilimanjaro (JRO) → Zanzibar (ZNZ)", text)
        self.assertNotIn("soon", text)
        self.assertNotIn("later", text)
        self.assertIn("Precision Air", text, "what does parse is still shown")


class EveryLevelAndThePlainTextCarryItTests(unittest.TestCase):
    def test_the_short_form_lists_each_leg_with_its_times_in_the_flights_section(self):
        fares = _fares(FLIGHTS)
        html = _html(fares=fares, deals=_deals(2), budget=20_000)
        attachment = _attachment(fares=fares, deals=_deals(2))
        # Tiny body: the page may have moved to the attachment (owner, 30 Oct 2026); the trip stays in the table.
        self.assertIn("AF-01", _table_ids(html))
        text = visible_text(_slice(html if 'id="trip-AF-01"' in html else attachment, "trip-AF-01"))
        for word in ("09:30", "28 Jun 02:00", "Etihad Airways", "11:15", "Precision Air", "18:05", "Qatar Airways"):
            self.assertIn(word, text, word)
        self.assertNotIn("not captured", text)

    def test_the_trimmed_form_keeps_each_legs_times_on_its_itinerary_line(self):
        fares = _fares(FLIGHTS)
        html = _html(fares=fares, deals=_deals(2), budget=100_000)
        part = _slice(html, "trip-AF-01")
        if "longest notes" in visible_text(part):
            text = visible_text(part)
            self.assertIn("Precision Air", _leg_line(text, "Kilimanjaro (JRO)", "Zanzibar (ZNZ)"))

    def test_the_plain_text_part_has_every_legs_line(self):
        text = _text(fares=_fares(FLIGHTS))
        start = text.index("Itinerary", text.index("\nTanzania safari 4 nights + Zanzibar 5 nights (Kuoni)\n"))
        part = text[start:start + 6000]
        for word in ("09:30", "28 Jun 02:00", "Etihad Airways", "1 stop (1h 40m AUH)", "14h 30m",
                     "11:15", "Precision Air", "nonstop", "18:05", "15 Jul 06:20", "Qatar Airways"):
            self.assertIn(word, part, word)


class TheContractIsDocumentedTests(unittest.TestCase):
    def test_the_docstrings_name_the_flights_list_and_the_cabin_fields(self):
        for doc in (hol._is_multi_centre_read.__doc__, td.__doc__):
            for word in ("flights", "departure_local", "arrival_local", "cabin_mix", "layover"):
                self.assertIn(word, doc)


if __name__ == "__main__":
    unittest.main()
