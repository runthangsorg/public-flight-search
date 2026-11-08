"""No unplanned nights: a trip is priced with a flight home on the day its plan ends (owner, 8 Nov 2026).

Almost every trip page in the 8 Nov July e-mail said "The plan ends 7 Jul and your flight home is 14 Jul: 7 nights
(7 Jul → 14 Jul) are not planned or priced here." The cause: every trip was dated on ONE date pair, the middle of the
report's priceable pairs (27 Jun → 14 Jul, 17 nights), whatever its own length, and ``multi_centre_wanted`` asked the
private reader for exactly those legs, so every read came back for 14 Jul too.

Now each trip flies home when its plan ends:

* with no read, its legs (and the wanted list the next hunt reads from) end on outbound + the trip's own nights;
* a read whose return is the plan's end wins; else the read on the nearest configured return date at or after it;
* only when no such read exists is a read for later dates used, and then the PRICE line says plainly how many nights
  the total covers and that the extra nights are not priced. The itinerary no longer carries a gap sentence.

Synthetic reads throughout.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from public_flight_search import holiday_email as he
from public_flight_search.multi_centre import load_multi_centre, trip_legs_for_dates

from test_holiday_email_compact import _config, visible_text
from test_multi_centre_reads import _multi_centre_read
from test_price_says_what_it_covers import load
from test_trip_dossiers import _html, _slice, _text

OUTBOUND = "2027-06-27"
TRIP = "AF-06"  # a 10-night package: its plan ends 7 Jul


def _trip(ident=TRIP):
    return next(t for t in load_multi_centre(_config()) if t.id == ident)


def _plan_end(trip, outbound=OUTBOUND) -> str:
    return (datetime.strptime(outbound, "%Y-%m-%d") + timedelta(days=trip.total_nights)).strftime("%Y-%m-%d")


def _read(returning: str, *, ident=TRIP, total=5_000.0) -> dict:
    legs = [list(leg) for leg in trip_legs_for_dates(_trip(ident), OUTBOUND, returning)]
    return _multi_centre_read({"trip": ident, "legs": legs, "season": "summer"}, total=total)


def _row(fares, ident=TRIP, *, complete_only=False):
    config = _config(complete_price_only=complete_only)
    return next(r for r in he._multi_centre_rows(config, fares=fares, complete_only=complete_only)
                if r["trip"].id == ident)


class WithNoReadTheTripFliesHomeWhenItsPlanEndsTests(unittest.TestCase):
    def test_every_trip_and_the_wanted_list_end_on_the_plans_own_last_day(self):
        config = _config()
        wanted = {w["trip"]: w for w in he.multi_centre_wanted(config)}
        for row in he._multi_centre_rows(config):
            with self.subTest(trip=row["trip"].id):
                end = _plan_end(row["trip"], row["outbound"])
                self.assertEqual(row["return"], end)
                self.assertEqual(row["legs"][-1][2], end)
                self.assertEqual(wanted[row["trip"].id]["legs"][-1][2], end)

    def test_no_page_says_nights_are_not_planned(self):
        self.assertNotIn("not planned or priced", visible_text(_html()))
        self.assertNotIn("not planned or priced", _text())


class WhichReadPricesTheTripTests(unittest.TestCase):
    def test_a_read_on_the_plans_last_day_wins_over_a_later_one(self):
        end = _plan_end(_trip())
        row = _row(load([_read("2027-07-14", total=4_000), _read(end, total=5_000)]))
        self.assertEqual(row["return"], end)
        self.assertEqual(row["read"]["total_gbp"], 5_000)

    def test_else_the_nearest_configured_return_at_or_after_the_plans_end(self):
        row = _row(load([_read("2027-07-14", total=4_000), _read("2027-07-09", total=5_000)]))
        self.assertEqual(row["return"], "2027-07-09")
        self.assertEqual(row["read"]["total_gbp"], 5_000)

    def test_a_read_for_later_dates_still_prices_the_trip_and_the_price_line_says_what_it_covers(self):
        fares = load([_read("2027-07-14")])
        row = _row(fares, complete_only=True)
        self.assertEqual(row["return"], "2027-07-14")
        page = visible_text(_slice(_html(fares=fares), f"trip-{TRIP}"))
        header = page[:page.index("Package vs our build")]
        self.assertIn("covers the 10 planned nights", header)
        self.assertIn("the 7 extra nights to 14 Jul are not priced", header)
        self.assertNotIn("not planned or priced", page)
        text = _text(fares=fares)
        block = text[text.index("Zanzibar 8 nights + Nyerere safari 2 nights (TourCompass)\n"):]
        self.assertIn("the 7 extra nights to 14 Jul are not priced", block[:block.index("Package vs our build")])

    def test_a_read_on_the_plans_last_day_needs_no_note(self):
        fares = load([_read(_plan_end(_trip()))])
        page = visible_text(_slice(_html(fares=fares), f"trip-{TRIP}"))
        self.assertNotIn("extra nights", page)
        self.assertNotIn("not planned or priced", page)


if __name__ == "__main__":
    unittest.main()
