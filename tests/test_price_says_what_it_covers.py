"""Every price says what it covers (owner, 8 Nov 2026).

The 8 Nov July e-mail put "flights read 1 Nov: Business £10,139 · Economy £5,080" beside a trip figure "from £14,695",
and a trip page said "With Business long-haul: £10,139 for 5, the whole trip": the owner could not tell a flights-only
figure from the price of the whole holiday. Now:

* every flights-only figure reads as flights only ("Flights only, 5 people: economy £5,080 · business long-haul £10,139");
* every trip total reads as the whole trip ("Trip total for 5: £14,695 (flights + stays + transfers)", or
  "package price incl. flights" for an operator's package);

in the HTML body, the plain-text part and the full-detail attachment alike. Synthetic reads throughout.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import multi_centre_wanted

from test_holiday_email_compact import _config, _deals, visible_text
from test_multi_centre_reads import _multi_centre_read
from test_trip_dossiers import _attachment, _html, _slice, _text

#: A carrier on the business quality list, so these reads are shown whatever the business-deal rule decides.
GOOD = "Qatar Airways"


def _wanted():
    return {w["trip"]: w for w in multi_centre_wanted(_config())}


def deal_read(trip: str, cabin: str, total: float, *, carrier: str = GOOD, long_hours: int = 12,
              observed: str = "2026-10-22T09:00:00+00:00") -> dict:
    """One SYNTHETIC read whose ``flights`` say which legs are long and in which cabin.

    The first and last legs are the long-haul flights; a ``MIXED`` read flies them in Business and the hops between in
    Economy, exactly as the owner's rule builds it.
    """
    want = _wanted()[trip]
    row = _multi_centre_read(want, observed_at=observed, total=float(total))
    legs = row["legs"]
    flights = []
    for index, (origin, destination, day) in enumerate(legs):
        long_leg = index in (0, len(legs) - 1)
        leg_cabin = "BUSINESS" if (cabin == "MIXED" and long_leg) or cabin == "BUSINESS" else "ECONOMY"
        flights.append({"origin": origin, "destination": destination, "departure_local": f"{day}T10:00:00",
                        "carrier": carrier if long_leg else "SYNTHETIC Hop Air", "stops": 1,
                        "duration": f"{long_hours}h 10m" if long_leg else "1h 05m", "cabin": leg_cabin})
    row.update({"cabin": cabin, "carrier": carrier, "duration": f"{long_hours}h 10m", "flights": flights,
                "source_url": f"https://example.org/SYNTHETIC-{trip}-{cabin}-{int(total)}"})
    if cabin == "MIXED":
        row["cabin_mix"] = "Business on the long-haul legs + Economy hops"
    return row


def load(rows) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "stopover_reads_synthetic.json"
        path.write_text(json.dumps({"schema": hol.STOPOVER_READS_SCHEMA, "rows": list(rows)}), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            _stops, fares = hol.load_batch_reads(str(path))
    hol.consume_stopover_skip_log()
    return fares


#: AF-06 is an operator package (its price includes its own flights); AF-10 is a self-build that itemises its flights.
PACKAGE, BUILD = "AF-06", "AF-10"


def both_products() -> dict:
    return load([deal_read(PACKAGE, "ECONOMY", 5_000), deal_read(PACKAGE, "MIXED", 9_000),
                 deal_read(BUILD, "ECONOMY", 4_000), deal_read(BUILD, "MIXED", 8_000)])


def _overview_text_line(text: str, trip_title_start: str) -> str:
    return next(line for line in text.splitlines() if line.strip().startswith(f"· {trip_title_start}"))


class FlightsOnlyFiguresSayFlightsOnlyTests(unittest.TestCase):
    def setUp(self):
        self.fares = both_products()
        self.text = _text(fares=self.fares)
        self.html = _html(fares=self.fares)

    def test_the_overview_line_names_flights_only_economy_first(self):
        line = _overview_text_line(self.text, "Zanzibar 8 nights")
        self.assertIn("Flights only, 5 people", line)
        self.assertIn("economy £5,000 · business long-haul £9,000", line)
        self.assertNotRegex(line, r"flights read \d+ \w+: Business")

    def test_the_trip_page_flights_line_is_flights_only_not_the_whole_trip(self):
        page = visible_text(_slice(self.html, f"trip-{PACKAGE}"))
        self.assertIn("Flights only, 5 people: £5,000", page)
        self.assertNotIn("the whole trip", page)
        block = self.text[self.text.index("Zanzibar 8 nights + Nyerere"):]
        block = block[block.index("  Flights"):block.index("  What the price covers")]
        self.assertIn("Flights only, 5 people: £5,000", block)
        self.assertNotIn("the whole trip", block)

    def test_the_attachment_says_the_same(self):
        page = visible_text(_slice(_attachment(fares=self.fares), f"trip-{PACKAGE}"))
        self.assertIn("Flights only, 5 people: £5,000", page)
        self.assertNotIn("the whole trip", page)


class TripTotalsSayTheWholeTripTests(unittest.TestCase):
    def setUp(self):
        self.fares = both_products()
        self.text = _text(fares=self.fares)
        self.html = _html(fares=self.fares)

    def test_a_package_total_says_it_includes_flights(self):
        line = _overview_text_line(self.text, "Zanzibar 8 nights")
        self.assertIn("Trip total for 5: from £14,695 (package price incl. flights)", line)
        page = visible_text(_slice(self.html, f"trip-{PACKAGE}"))
        self.assertIn("Trip total for 5", page)
        self.assertIn("package price incl. flights", page)
        self.assertIn("package price incl. flights", visible_text(_slice(_attachment(fares=self.fares),
                                                                          f"trip-{PACKAGE}")))

    def test_an_itemised_build_total_says_flights_stays_and_transfers(self):
        line = _overview_text_line(self.text, "Self-build: Kruger")
        self.assertIn("Trip total for 5 (flights + stays + transfers)", line)
        page = visible_text(_slice(self.html, f"trip-{BUILD}"))
        self.assertIn("Trip total for 5", page)
        self.assertIn("(flights + stays + transfers)", page)
        self.assertNotIn("door to door", page)

    def test_the_overview_table_cells_say_trip_total(self):
        table = visible_text(self.html[self.html.index("Every option at a glance"):self.html.index('id="trips"')])
        self.assertIn("Flights only, 5 people", table)
        self.assertIn("package price incl. flights", table)
        self.assertIn("flights + stays + transfers", table)

    def test_a_resort_card_total_and_its_flight_rows_say_trip_total(self):
        deal = _deals(1)[0]
        html = _html(fares=self.fares, deals=[deal])
        card = visible_text(_slice(html, "deal-0") if 'id="deal-0"' in html else html[html.index('id="resorts"'):])
        self.assertIn("trip total for 5", card)
        self.assertIn("flights + stay + transfers", card)
        text = _text(fares=self.fares, deals=[deal])
        self.assertIn("trip total for 5", text)

    def test_the_quick_answer_says_trip_total(self):
        start = visible_text(self.html[self.html.index('id="start"'):self.html.index("How current this is")])
        self.assertRegex(start, r"Cheapest that fits[^:]*: .*trip total")


if __name__ == "__main__":
    unittest.main()
