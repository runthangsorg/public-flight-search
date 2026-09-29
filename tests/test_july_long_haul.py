"""The July planner is long-haul: Lombok and Thailand, nothing within 6 hours.

Owner instructions of 2026-09-29, for the July 2027 trip:

* "remove anywhere within 6 hour flight from july destinations";
* "include lombok and thailand mostly, dont include singapore, malaysia or
  langkawi".

Until then the only resort catalogue covered nine short-haul keys, so every
July "deal" was short-haul however the config was edited. These tests pin the
July example to the owner's scope and pin the catalogue it now prices from.
"""

from __future__ import annotations

import dataclasses
from html import escape
import json
from pathlib import Path
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holidays import (
    SUMMER_RESORT_CATALOG,
    SUITE_ARCHITECTURE,
    SUMMER_WEATHER,
    WINTER_RESORT_CATALOG,
    collect_holiday_deals,
    filter_resorts,
    is_summer_trip,
    load_holiday_config,
    render_holiday_report,
    resort_catalog,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
DEC = ROOT / "examples" / "dec_holiday_config.json"

#: Airports the owner excluded (Singapore, Malaysia, Langkawi).
EXCLUDED_AIRPORTS = {"SIN", "KUL", "PEN", "BKI", "LGK"}
EXCLUDED_KEYS = {"singapore", "langkawi", "penang", "kota_kinabalu", "kuala_lumpur"}
LOMBOK_KEYS = {"lombok"}
THAILAND_KEYS = {"koh_samui", "koh_phangan", "khao_lak"}
#: The Andaman coast is in its south-west monsoon in July.
ANDAMAN_KEYS = {"khao_lak", "phuket", "krabi"}

#: A budget high enough that every July resort cards. Synthetic: it is not,
#: and must never be, the owner's budget.
UNCAPPED_GBP = 40000.0


def _july():
    return load_holiday_config(JULY.read_text(encoding="utf-8"))


class JulyScopeTests(unittest.TestCase):
    def test_no_july_destination_is_six_hours_or_less(self):
        for dest in _july().destinations:
            with self.subTest(dest=dest.key):
                self.assertGreater(dest.flight_hours, 6.0)

    def test_no_singapore_or_malaysia(self):
        for dest in _july().destinations:
            with self.subTest(dest=dest.key):
                self.assertNotIn(dest.key, EXCLUDED_KEYS)
                self.assertFalse(set(dest.airports) & EXCLUDED_AIRPORTS, dest.airports)

    def test_lombok_and_thailand_lead_and_resolve_to_catalogue_resorts(self):
        config = _july()
        keys = [d.key for d in config.destinations]
        self.assertEqual(set(keys[:4]), LOMBOK_KEYS | THAILAND_KEYS)
        catalog = resort_catalog(config)
        for key in LOMBOK_KEYS | THAILAND_KEYS:
            with self.subTest(key=key):
                kept, dropped = filter_resorts(catalog.get(key, []), is_summer=True)
                self.assertTrue(kept, f"{key} has no resort that survives the filters")
                self.assertEqual(dropped, [])

    def test_thailand_is_mostly_the_gulf_side(self):
        # July: the Gulf (Samui, Phangan) is the drier coast; the Andaman
        # side (Khao Lak) is in monsoon, so it gets at most two resorts and
        # every one of them says so.
        andaman = [r for key in ANDAMAN_KEYS for r in SUMMER_RESORT_CATALOG.get(key, [])]
        gulf = [r for key in ("koh_samui", "koh_phangan") for r in SUMMER_RESORT_CATALOG[key]]
        self.assertLessEqual(len(andaman), 2)
        self.assertGreater(len(gulf), len(andaman))
        for resort in andaman:
            with self.subTest(resort=resort["name"]):
                self.assertIn("monsoon", resort["beach"].lower())
                self.assertIn("MONSOON", resort["destination_label"])

    def test_every_long_haul_cabin_is_business(self):
        for dest in _july().destinations:
            if dest.key in LOMBOK_KEYS | THAILAND_KEYS:
                with self.subTest(dest=dest.key):
                    self.assertEqual(dest.cabin_class, "BUSINESS")


class SummerCatalogueTests(unittest.TestCase):
    def test_catalogues_share_no_key(self):
        self.assertFalse(set(SUMMER_RESORT_CATALOG) & set(WINTER_RESORT_CATALOG))

    def test_season_selects_the_catalogue(self):
        july = _july()
        december = load_holiday_config(DEC.read_text(encoding="utf-8"))
        self.assertTrue(is_summer_trip(july))
        self.assertFalse(is_summer_trip(december))
        self.assertIs(resort_catalog(december), WINTER_RESORT_CATALOG)
        self.assertIs(resort_catalog(), WINTER_RESORT_CATALOG)
        summer = resort_catalog(july)
        for key in SUMMER_RESORT_CATALOG:
            self.assertIn(key, summer)
        for key in WINTER_RESORT_CATALOG:
            self.assertIs(summer[key], WINTER_RESORT_CATALOG[key])

    def test_december_never_prices_a_summer_resort(self):
        december = load_holiday_config(DEC.read_text(encoding="utf-8"))
        summer_names = {r["name"] for rs in SUMMER_RESORT_CATALOG.values() for r in rs}
        deals = collect_holiday_deals(december, max_budget_gbp=UNCAPPED_GBP)
        self.assertTrue(deals)
        self.assertFalse({d.resort_name for d in deals} & summer_names)

    def test_every_summer_resort_is_complete_and_sourced(self):
        for key, resorts in SUMMER_RESORT_CATALOG.items():
            self.assertIn(key, SUMMER_WEATHER, key)
            self.assertIn(key, hol.HOLIDAY_SEARCH_QUERIES, key)
            self.assertIn(key, hol.HOLIDAY_AIRPORTS, key)
            for resort in resorts:
                with self.subTest(resort=resort["name"]):
                    self.assertTrue(resort["hotel_url"].startswith("https://"))
                    self.assertIn(resort["stars"], (4, 5))
                    self.assertIn(resort["confidence"], ("market-supported", "estimate"))
                    self.assertTrue(resort["routing"], "a long-haul resort must state its routing")
                    self.assertIn(resort["airport"], hol.BUSINESS_CARRIER_BY_AIRPORT)
                    arch = SUITE_ARCHITECTURE[resort["name"]]
                    self.assertGreater(arch["suite_nightly_gbp"], 0)
                    # July is the season priced: no peak discount is claimed.
                    self.assertEqual(arch["suite_peak_nightly_gbp"], arch["suite_nightly_gbp"])
                    self.assertEqual(
                        resort["peak_summer_flight_5pax_gbp"], resort["flight_benchmark_5pax_gbp"]
                    )
                    # TripAdvisor could not be read: never a made-up rating.
                    self.assertIsNone(arch["tripadvisor"])
                    self.assertTrue(arch["beach_walkable"])

    def test_lombok_business_says_there_is_no_business_cabin(self):
        self.assertIn("no Business cabin", hol.BUSINESS_CARRIER_BY_AIRPORT["LOP"])


class JulyReportHonestyTests(unittest.TestCase):
    def test_priced_out_resorts_are_listed_not_dropped(self):
        config = _july()
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
        names = {d.resort_name for d in deals} | {
            row["resort_name"] for row in hol.LAST_OVER_BUDGET
        }
        expected = {
            r["name"]
            for key in LOMBOK_KEYS | THAILAND_KEYS
            for r in SUMMER_RESORT_CATALOG[key]
        }
        self.assertEqual(names, expected)
        for row in hol.LAST_OVER_BUDGET:
            with self.subTest(resort=row["resort_name"]):
                self.assertGreater(row["true_d2d"], config.max_budget_gbp)
                self.assertEqual(row["flight_confidence"], "benchmark")
        for deal in deals:
            self.assertLessEqual(deal.true_d2d_gbp, config.max_budget_gbp)
        if hol.LAST_OVER_BUDGET:
            html = render_holiday_report(
                config, generated_at="2026-09-29T00:00:00+00:00", deals=deals
            )
            self.assertIn("Long-haul resorts priced over", html)
            self.assertIn("benchmark estimate", html)

    def test_short_haul_over_budget_resorts_keep_the_old_behaviour(self):
        fixture = load_holiday_config(
            (ROOT / "tests" / "fixtures" / "july_short_haul_config.json").read_text(encoding="utf-8")
        )
        collect_holiday_deals(fixture, max_budget_gbp=100.0)
        self.assertEqual(hol.LAST_OVER_BUDGET, ())

    def test_cards_state_routing_estimates_and_the_rule_not_applied(self):
        config = dataclasses.replace(_july(), max_budget_gbp=UNCAPPED_GBP)
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertEqual(deal.cabin_class, "BUSINESS")
                self.assertTrue(deal.routing)
                # Business priced from the economy benchmark is an estimate.
                self.assertEqual(deal.confidence, "estimate")
        html = render_holiday_report(config, generated_at="2026-09-29T00:00:00+00:00", deals=deals)
        self.assertIn("Routing:", html)
        self.assertNotIn("Nonstop Logistics", html)
        self.assertIn("Rule not applied — TripAdvisor ≥4.5", html)
        for deal in deals:
            self.assertIn(escape(deal.resort_name), html)
        start = html.index("Summer Luxury Deals")
        heading = html[start:start + 900]
        self.assertNotIn("TripAdvisor ≥4.5", heading)
        self.assertNotIn("nonstop flights", heading)
        self.assertNotIn("verified rate", html)
        self.assertIn("criteria scores not assessed", html)

    def test_the_budget_line_names_the_configured_budget(self):
        config = dataclasses.replace(_july(), max_budget_gbp=UNCAPPED_GBP)
        deals = collect_holiday_deals(config)
        html = render_holiday_report(config, generated_at="2026-09-29T00:00:00+00:00", deals=deals)
        self.assertIn("Top Luxury Within £40k", html)
        self.assertNotIn("Within £12k", html)

    def test_example_config_is_valid_json_with_sources(self):
        data = json.loads(JULY.read_text(encoding="utf-8"))
        for dest in data["destinations"]:
            with self.subTest(dest=dest["key"]):
                self.assertGreater(len(dest["flight_hours_source"]), 20)


if __name__ == "__main__":
    unittest.main()
