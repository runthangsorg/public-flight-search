"""Mexico and Japan: the H9 destinations, gated exactly as every other resort.

Owner direction 2026-10-04 ("ensure mexico, japan, multi-stop holidays are
also considered too"), research read 2026-10-04.

The point of these tests is not that the new properties exist. It is that
adding them loosened nothing: a suite whose occupancy no official page
confirms is FILTERED and named, an unheated-pool claim is never invented, no
TripAdvisor rating is typed in that the engine has not read, and the two
seasons price the same resort the way their own evidence supports.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import unittest

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    SUMMER_RESORT_CATALOG,
    SUITE_ARCHITECTURE,
    WINTER_RESORT_CATALOG,
    collect_holiday_deals,
    filter_resorts,
    load_holiday_config,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
DEC = ROOT / "examples" / "dec_holiday_config.json"

#: Synthetic and deliberately not the owner's budget.
UNCAPPED_GBP = 40000.0

NEW_JULY_RESORTS = (
    "Grand Velas Riviera Maya",
    "Dreams Tulum Resort & Spa",
    "Halekulani Okinawa",
    "Melati Beach Resort & Spa",
)


def _config(path: Path, budget: float | None = None):
    config = load_holiday_config(path.read_text(encoding="utf-8"))
    return config if budget is None else dataclasses.replace(config, max_budget_gbp=budget)


def _names(deals) -> set[str]:
    return {deal.resort_name for deal in deals}


def _filtered() -> dict[str, str]:
    return dict(hol.LAST_FILTERED_OUT)


class NewCatalogueEntriesTests(unittest.TestCase):
    def test_every_new_resort_is_in_the_catalogue_it_belongs_to(self):
        summer = {r["name"] for rs in SUMMER_RESORT_CATALOG.values() for r in rs}
        winter = {r["name"] for rs in WINTER_RESORT_CATALOG.values() for r in rs}
        for name in NEW_JULY_RESORTS:
            self.assertIn(name, summer, name)
        # Grand Velas sells in December too: Riviera Maya is warm and dry there.
        self.assertIn("Grand Velas Riviera Maya", winter)
        # The winter Riviera Maya entry keeps Coral Beach as well.
        self.assertIn(
            "Grand Fiesta Americana Coral Beach Cancún All Inclusive Spa & Resort", winter
        )

    def test_no_new_entry_claims_a_tripadvisor_rating_the_engine_did_not_read(self):
        for name in NEW_JULY_RESORTS:
            with self.subTest(resort=name):
                self.assertIsNone(SUITE_ARCHITECTURE[name]["tripadvisor"])

    def test_no_dated_rate_is_claimed_where_none_was_read(self):
        # Only Melati had an exact-date read (Google Hotels, 20-27 Jul 2027).
        # The other three had no dated public rate on 2026-10-04, so they are
        # estimates and say so.
        by_name = {
            r["name"]: r
            for rs in SUMMER_RESORT_CATALOG.values() for r in rs
        }
        self.assertEqual(by_name["Melati Beach Resort & Spa"]["confidence"], "market-supported")
        for name in ("Grand Velas Riviera Maya", "Dreams Tulum Resort & Spa", "Halekulani Okinawa"):
            with self.subTest(resort=name):
                self.assertEqual(by_name[name]["confidence"], "estimate")

    def test_the_derived_nightlies_match_their_stated_basis(self):
        # Each comment names the research's own dated range and the nights it
        # covers; the figure in the catalogue is that mid-point over those
        # nights. If a rate is ever re-derived, this says so out loud.
        cases = (
            ("Grand Velas Riviera Maya", 12600.0, 7, 1800.0),
            ("Dreams Tulum Resort & Spa", 6900.0, 6, 1150.0),
            ("Halekulani Okinawa", 10500.0, 7, 1500.0),
        )
        for name, mid, nights, nightly in cases:
            with self.subTest(resort=name):
                self.assertAlmostEqual(mid / nights, nightly, places=2)

    def test_july_board_is_what_each_hotel_actually_sells(self):
        by_name = {r["name"]: r for rs in SUMMER_RESORT_CATALOG.values() for r in rs}
        # Both Mexican properties are all-inclusive only; Halekulani sells
        # room-only or B&B and never all-inclusive.
        for name in ("Grand Velas Riviera Maya", "Dreams Tulum Resort & Spa"):
            self.assertEqual(hol.board_code(by_name[name]["board"]), "AI", name)
        self.assertEqual(hol.board_code(by_name["Halekulani Okinawa"]["board"]), "BB")


class UnverifiedOccupancyIsFilteredTests(unittest.TestCase):
    """Two properties cannot prove one booking sleeps 5, so they do not card."""

    def _filtered_names(self, budget: float | None = UNCAPPED_GBP) -> dict[str, str]:
        collect_holiday_deals(_config(JULY, budget))
        return _filtered()

    def test_dreams_tulum_is_filtered_for_unverified_occupancy(self):
        self.assertIn("Dreams Tulum Resort & Spa", self._filtered_names())
        self.assertIsNone(SUITE_ARCHITECTURE["Dreams Tulum Resort & Spa"]["rooms_in_unit"])

    def test_halekulani_is_filtered_for_unverified_occupancy(self):
        self.assertIn("Halekulani Okinawa", self._filtered_names())
        self.assertIsNone(SUITE_ARCHITECTURE["Halekulani Okinawa"]["rooms_in_unit"])

    def test_a_filtered_property_is_never_silently_absent(self):
        # The report names both, with the reason, so the reader knows they were
        # considered and why they are not offers.
        filtered = self._filtered_names()
        for name in ("Dreams Tulum Resort & Spa", "Halekulani Okinawa"):
            with self.subTest(resort=name):
                self.assertTrue(filtered.get(name), f"{name} vanished without a reason")

    def test_the_two_properties_that_could_prove_a_unit_do_card(self):
        deals = collect_holiday_deals(_config(JULY, UNCAPPED_GBP))
        names = _names(deals)
        self.assertIn("Grand Velas Riviera Maya", names)
        self.assertIn("Melati Beach Resort & Spa", names)


class DecemberPoolClaimTests(unittest.TestCase):
    def test_grand_velas_is_not_filtered_for_a_pool_nobody_stated(self):
        # Its pool temperature was never published, so the December >= 28°C gate
        # is not applied and the report says "heated pool not stated". Claiming
        # 0°C would filter it on a fact no source published.
        deals = collect_holiday_deals(_config(DEC, UNCAPPED_GBP))
        self.assertIn("Grand Velas Riviera Maya", _names(deals))
        self.assertIsNone(SUITE_ARCHITECTURE["Grand Velas Riviera Maya"]["pool_heated_c"])
        self.assertNotIn("Grand Velas Riviera Maya", _filtered())

    def test_coral_beach_carries_its_own_sites_heating_claim(self):
        # Its own site (read 2026-10-04) says the lagoon pools are heated
        # "from now until March", which covers December. That claim is carried
        # on the deal, and the December >= 28°C gate is NOT applied because the
        # site states no temperature.
        config = _config(DEC, UNCAPPED_GBP)
        deals = {d.resort_name: d for d in collect_holiday_deals(config)}
        coral = next(d for n, d in deals.items() if n.startswith("Grand Fiesta Americana"))
        joined = " ".join(coral.highlights) + " " + coral.beach
        self.assertIn("heated", joined)
        self.assertIn("March", joined)

    def test_both_mexican_resorts_are_over_the_december_budget_not_filtered(self):
        config = _config(DEC)
        collect_holiday_deals(config)
        over = {row["resort_name"] for row in hol.LAST_OVER_BUDGET}
        self.assertIn("Grand Velas Riviera Maya", over)
        self.assertNotIn("Grand Velas Riviera Maya", _filtered())


class JulyMexicoHonestyTests(unittest.TestCase):
    def test_no_london_nonstop_is_claimed_for_july_cancun(self):
        by_name = {r["name"]: r for rs in SUMMER_RESORT_CATALOG.values() for r in rs}
        for name in ("Grand Velas Riviera Maya", "Dreams Tulum Resort & Spa"):
            with self.subTest(resort=name):
                self.assertIn("no London nonstop", by_name[name]["routing"])
                self.assertEqual(by_name[name]["airport"], "CUN")
        # The December entry may use the nonstop: the service runs then.
        winter = {r["name"]: r for rs in WINTER_RESORT_CATALOG.values() for r in rs}
        self.assertIn("nonstop", winter["Grand Velas Riviera Maya"]["airline"])

    def test_the_july_business_carrier_never_names_a_nonstop_to_cancun(self):
        carrier = hol.BUSINESS_CARRIER_BY_AIRPORT["CUN"]
        self.assertIn("11 Apr 2027", carrier)
        self.assertIn("connects", carrier)

    def test_okinawa_routing_states_the_tokyo_change(self):
        by_name = {r["name"]: r for rs in SUMMER_RESORT_CATALOG.values() for r in rs}
        routing = by_name["Halekulani Okinawa"]["routing"]
        self.assertIn("no London nonstop", routing)
        self.assertEqual(by_name["Halekulani Okinawa"]["airport"], "OKA")

    def test_okinawa_is_typhoon_season_and_says_so_on_the_card(self):
        self.assertIn(7, hol.WET_MONTHS_BY_DESTINATION["okinawa"])
        # It does not card (no confirmed unit), so its warning is checked on
        # the watch row's climate text and the season map instead.
        self.assertIn("typhoon", hol.FAR_EAST_WATCH["okinawa"]["climate"])


if __name__ == "__main__":
    unittest.main()