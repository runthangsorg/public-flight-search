"""Any flight leg over 8 hours is flown and priced in Business (owner, 8 Nov 2026).

Verbatim: "reject economy where a leg is more than 8hrs, has to be business."

* An Economy read is offered only when EVERY leg is shown to be 8 hours or less. Legs the read itemises are read;
  legs it does not are estimated from the airports (``leg_hours``), and an airport nobody knows is not shown to be
  short, so it is not offered.
* A Business (or Business-long-haul) read is offered whatever it costs over Economy, when the carriers of the long
  legs are on the quality list (Kenya Airways and Ethiopian included). This replaces the earlier "business only when a
  deal" gate for legs over 8 hours.
* Eight hours exactly is not over eight hours.

Synthetic reads throughout.
"""

from __future__ import annotations

import unittest

from public_flight_search import cabin, holiday_email as he
from public_flight_search import leg_hours

from test_price_says_what_it_covers import BUILD, PACKAGE, deal_read, load
from test_holiday_email_compact import _config
from public_flight_search.holiday_email import _multi_centre_rows


def _row(rows, trip_id):
    return next(r for r in _multi_centre_rows(_config(), fares=load(rows)) if r["trip"].id == trip_id)


class LegHoursTests(unittest.TestCase):
    def test_nonstop_estimates_put_the_gulf_under_and_the_far_east_over(self):
        self.assertLessEqual(leg_hours.estimate_hours("LHR", "DOH"), 8.0)
        self.assertLessEqual(leg_hours.estimate_hours("LHR", "DXB"), 8.0)
        self.assertLessEqual(leg_hours.estimate_hours("LHR", "IST"), 8.0)
        self.assertGreater(leg_hours.estimate_hours("LHR", "JNB"), 8.0)
        self.assertGreater(leg_hours.estimate_hours("DOH", "DPS"), 8.0)
        self.assertGreater(leg_hours.estimate_hours("LHR", "MLE"), 8.0)

    def test_an_unknown_airport_has_no_estimate(self):
        self.assertIsNone(leg_hours.estimate_hours("LHR", "ZZZ"))

    def test_economy_is_allowed_only_when_every_leg_is_known_and_at_most_eight(self):
        self.assertTrue(cabin.economy_allowed([7.9, 8.0, 2.0]))
        self.assertFalse(cabin.economy_allowed([7.9, 8.1]))
        self.assertFalse(cabin.economy_allowed([7.0, None]), "a leg nobody measured is not shown to be short")
        self.assertFalse(cabin.economy_allowed([]))


class EconomyReadTests(unittest.TestCase):
    def test_an_economy_read_with_a_leg_over_eight_hours_is_not_offered(self):
        row = _row([deal_read(PACKAGE, "ECONOMY", 5_000, long_hours=12)], PACKAGE)
        self.assertIsNone(row["reads"]["economy"])
        self.assertEqual(row["economy_refused"], "a flight leg is over 8 hours: it needs a business read")

    def test_an_economy_read_whose_legs_are_all_eight_hours_or_less_is_offered(self):
        row = _row([deal_read(PACKAGE, "ECONOMY", 5_000, long_hours=7)], PACKAGE)
        self.assertIsNotNone(row["reads"]["economy"])
        self.assertEqual(row["economy_refused"], "")

    def test_eight_hours_exactly_is_still_economy(self):
        read = deal_read(PACKAGE, "ECONOMY", 5_000, long_hours=7)
        for flight in read["flights"]:
            if flight["duration"].startswith("7h"):
                flight["duration"] = "8h 0m"
        row = _row([read], PACKAGE)
        self.assertIsNotNone(row["reads"]["economy"])


class BusinessReadTests(unittest.TestCase):
    def test_business_is_offered_whatever_the_premium_when_the_carrier_is_a_good_one(self):
        # £15,000 more than economy used to be "not a deal"; for a leg over 8 hours it is simply the only offer.
        row = _row([deal_read(PACKAGE, "ECONOMY", 5_000), deal_read(PACKAGE, "MIXED", 20_000)], PACKAGE)
        self.assertIsNone(row["reads"]["economy"])
        self.assertEqual(row["reads"]["business"]["total_gbp"], 20_000)
        self.assertIsNone(row["business_hidden"])

    def test_a_carrier_off_the_quality_list_is_still_refused(self):
        row = _row([deal_read(PACKAGE, "MIXED", 9_000, carrier="RwandAir")], PACKAGE)
        self.assertIsNone(row["reads"]["business"])
        self.assertIsNone(row["reads"]["economy"])

    def test_the_business_read_carries_the_trip_total_for_an_itemised_trip(self):
        row = _row([deal_read(BUILD, "MIXED", 8_000)], BUILD)
        self.assertEqual([t["key"] for t in row["cabin_totals"]], ["business"])


if __name__ == "__main__":
    unittest.main()
