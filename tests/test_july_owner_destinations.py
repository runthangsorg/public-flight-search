"""The owner's July 2027 destinations enter the catalogue: no price, no card.

Owner list, 17 Oct 2026, in his words: "Tanzania first: a few days' safari from
top lodges, then Zanzibar", "Kenya Mara + Diani", "Kruger + Cape Town (or +
Mauritius)", Japan with Hokkaido and Okinawa, and also Mauritius and Seychelles.
Before this, the July planner could only price six beach keys and no multi-centre
trip at all, so none of those holidays could ever appear.

The rule that keeps adding them safe is the one `test_new_catalogue_resorts.py`
already pins: **no price, no card**. An entry with no read rate produces no card
and never a guessed price; the private rate reader prices it by its `hotel_url`
and its unit later. So every entry added here carries `"board": "unverified"`,
no `board_options`, and no rate fields, and the four trips carry no cost range.

Everything here is offline: no network, no model calls, no private data.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from public_flight_search import multi_centre
from public_flight_search.holidays import (
    HOLIDAY_AIRPORTS,
    HOLIDAY_SEARCH_QUERIES,
    SUMMER_MULTI_CENTRE_TRIPS,
    SUMMER_RESORT_CATALOG,
    WET_MONTHS_BY_DESTINATION,
    collect_holiday_deals,
    load_holiday_config,
    resort_catalog,
    summer_multi_centre_trips,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"

NEW_KEYS = (
    "serengeti", "masai_mara", "diani", "kruger", "cape_town",
    "mauritius", "seychelles", "hokkaido",
)
NEW_NAMES = {
    entry["name"] for key in NEW_KEYS for entry in SUMMER_RESORT_CATALOG[key]
}


def _july():
    return load_holiday_config(JULY.read_text(encoding="utf-8"))


class CatalogueEntryTests(unittest.TestCase):
    def test_every_new_key_loads_through_the_resort_catalogue(self):
        catalog = resort_catalog(_july())
        for key in NEW_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, catalog)
                self.assertGreaterEqual(len(catalog[key]), 2)
                self.assertLessEqual(len(catalog[key]), 3)

    def test_every_new_entry_has_the_fields_a_card_needs(self):
        for key in NEW_KEYS:
            for entry in SUMMER_RESORT_CATALOG[key]:
                with self.subTest(entry=entry.get("name")):
                    for field in ("airport", "name", "hotel_url",
                                  "destination_label", "highlights", "why"):
                        self.assertTrue(entry.get(field), field)
                    self.assertTrue(entry["hotel_url"].startswith("https://"))
                    self.assertIn(entry["stars"], (4, 5))

    def test_no_new_entry_carries_a_price_it_did_not_read(self):
        for key in NEW_KEYS:
            for entry in SUMMER_RESORT_CATALOG[key]:
                with self.subTest(entry=entry["name"]):
                    self.assertEqual(entry["board"], "unverified")
                    self.assertNotIn("board_options", entry)
                    for field in ("base_nightly_room_rate_gbp",
                                  "peak_summer_nightly_room_rate_gbp"):
                        self.assertNotIn(field, entry)
                    # 0.0 is this file's "not priced" sentinel, never a fare.
                    self.assertEqual(entry["flight_benchmark_5pax_gbp"], 0.0)
                    self.assertEqual(entry["peak_summer_flight_5pax_gbp"], 0.0)

    def test_every_new_key_names_its_airport_and_search_query(self):
        for key in NEW_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, HOLIDAY_AIRPORTS)
                self.assertIn(key, HOLIDAY_SEARCH_QUERIES)
                self.assertIn(key, WET_MONTHS_BY_DESTINATION)
                self.assertRegex(HOLIDAY_AIRPORTS[key], r"^[A-Z]{3}$")


class ExampleConfigTests(unittest.TestCase):
    def test_the_example_config_still_loads_and_carries_the_new_keys(self):
        config = _july()
        keys = [destination.key for destination in config.destinations]
        self.assertEqual(len(keys), 16)
        for key in (*NEW_KEYS, "lombok", "koh_samui", "zanzibar", "okinawa",
                    "riviera_maya"):
            with self.subTest(key=key):
                self.assertIn(key, keys)
        for destination in config.destinations:
            with self.subTest(key=destination.key):
                self.assertTrue(destination.airports)
                for airport in destination.airports:
                    self.assertRegex(airport, r"^[A-Z]{3}$")


class MultiCentreTripTests(unittest.TestCase):
    def test_the_four_summer_trips_are_declared(self):
        trips = summer_multi_centre_trips()
        self.assertEqual(len(trips), 4)
        self.assertEqual({trip["id"] for trip in trips},
                         {"SU-01", "SU-02", "SU-03", "SU-04"})

    def test_each_trip_is_a_summer_trip_with_nights_per_stop(self):
        for trip in summer_multi_centre_trips():
            with self.subTest(trip=trip["id"]):
                self.assertEqual(trip["season"], "summer")
                self.assertTrue(trip["stops"])
                for stop in trip["stops"]:
                    self.assertGreater(int(stop["nights"]), 0)
                    self.assertRegex(str(stop["airport"]), r"^[A-Z]{3}$")
                    self.assertTrue(stop["place"])

    def test_every_leg_is_a_pair_of_three_letter_airports(self):
        for trip in summer_multi_centre_trips():
            with self.subTest(trip=trip["id"]):
                self.assertGreaterEqual(len(trip["legs"]), 2)
                for leg in trip["legs"]:
                    self.assertEqual(len(leg), 2)
                    for airport in leg:
                        self.assertRegex(airport, r"^[A-Z]{3}$")

    def test_the_winter_loader_refuses_them_only_for_the_missing_cost_range(self):
        """They are in the winter shape; what stops them is that nothing is priced.

        A cost range is a figure, and this brief supplies none, so the trips are
        declared and shape-checked but deliberately cannot be quoted. This pins
        that: the refusal is the price, not the shape.
        """
        for trip in summer_multi_centre_trips():
            with self.subTest(trip=trip["id"]):
                multi_centre.consume_multi_centre_skip_log()
                self.assertIsNone(multi_centre._trip(trip))
                reasons = multi_centre.consume_multi_centre_skip_log()
                self.assertTrue(
                    any("cost range" in reason for reason in reasons), reasons)

    def test_no_declared_summer_trip_is_priced_from_the_committed_file(self):
        declared = {trip["id"] for trip in SUMMER_MULTI_CENTRE_TRIPS}
        loaded = {trip.id for trip in multi_centre.load_multi_centre(season="summer")}
        self.assertFalse(declared & loaded)


class NoPriceNoCardTests(unittest.TestCase):
    def test_no_new_resort_cards_without_a_rate(self):
        deals = collect_holiday_deals(_july(), max_budget_gbp=10 ** 9)
        self.assertFalse(NEW_NAMES & {deal.resort_name for deal in deals})


if __name__ == "__main__":
    unittest.main()
