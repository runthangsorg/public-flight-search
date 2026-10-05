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
from public_flight_search.hotel_evidence import _run_season

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
                resorts = catalog.get(key, [])
                self.assertTrue(resorts, f"{key} has no catalogue resort")
                kept, dropped = filter_resorts(resorts, is_summer=True)
                # A resort may be filtered (the breakfast rule of 2026-09-30),
                # but only with a stated reason, never silently.
                self.assertEqual(len(kept) + len(dropped), len(resorts))
                for _name, reason in dropped:
                    self.assertTrue(reason)
        for key in ("lombok", "koh_samui", "khao_lak"):
            kept, _ = filter_resorts(catalog[key], is_summer=True)
            self.assertTrue(kept, f"{key} has no resort that survives the filters")

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

    def test_every_long_haul_destination_prices_economy(self):
        # Owner rule 2026-10-04: business class is quoted only for a DIRECT
        # flight. None of the July destinations has a London nonstop on these
        # dates, so every one of them — however far — is Economy.
        for dest in _july().destinations:
            if dest.key in LOMBOK_KEYS | THAILAND_KEYS:
                with self.subTest(dest=dest.key):
                    self.assertEqual(dest.cabin_class, "ECONOMY")


class SummerCatalogueTests(unittest.TestCase):
    def test_summer_view_takes_only_both_season_winter_keys(self):
        # A key in both catalogues (Zanzibar) is priced at July rates in July
        # and December rates in December; December-only winter keys (Doha,
        # Muscat, Mauritius, Mexico) never reach the summer view.
        summer = resort_catalog(_july())
        for key, resorts in WINTER_RESORT_CATALOG.items():
            with self.subTest(key=key):
                if key in hol.BOTH_SEASON_WINTER_KEYS:
                    self.assertIs(summer[key], resorts)
                else:
                    self.assertIsNot(summer.get(key), resorts)

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
        for key in hol.BOTH_SEASON_WINTER_KEYS & set(WINTER_RESORT_CATALOG):
            self.assertIs(summer[key], WINTER_RESORT_CATALOG[key])

    def test_a_late_june_departure_is_still_the_summer_trip(self):
        # The owner's July 2027 window departs 26 and 29 June (2026-10-04). The
        # shipped config also says "July Summer" in its title, which is what
        # kept it a summer trip; this pins the DATE half of the rule on its own,
        # so a title-less config (or a renamed report) cannot quietly turn the
        # summer trip into a winter one and price the wrong catalogue.
        june_only = load_holiday_config(json.dumps({
            "report_title": "Long-haul family trip",
            "party": {"travellers": 5, "rooms": [2, 2, 1]},
            "departure_window": ["06:00", "23:59"],
            "origins": ["LHR"],
            "outbound_dates": ["2027-06-26", "2027-06-29"],
            "return_dates": ["2027-07-10", "2027-07-13"],
            "destinations": [
                {"key": "koh_samui", "label": "Koh Samui", "airports": ["USM"],
                 "flight_hours": 14.92},
            ],
        }))
        self.assertTrue(is_summer_trip(june_only))
        self.assertIs(resort_catalog(june_only), resort_catalog(_july()))
        # ...and the evidence loader agrees, so a rate read for those dates is
        # not skipped as "the season this run prices".
        self.assertEqual(_run_season(june_only), "summer")

    def test_december_never_prices_a_summer_resort(self):
        december = load_holiday_config(DEC.read_text(encoding="utf-8"))
        # Nungwi Dreams is sold in both seasons: its December card must be
        # the winter entry's (half board, December rate), never the July one.
        winter_names = {r["name"] for rs in WINTER_RESORT_CATALOG.values() for r in rs}
        summer_only = {
            r["name"] for rs in SUMMER_RESORT_CATALOG.values() for r in rs
        } - winter_names
        deals = collect_holiday_deals(december, max_budget_gbp=UNCAPPED_GBP)
        self.assertTrue(deals)
        self.assertFalse({d.resort_name for d in deals} & summer_only)
        for deal in deals:
            if deal.resort_name == "Nungwi Dreams by Mantis":
                self.assertEqual(deal.board_basis, "Half Board")

    def test_every_summer_resort_is_complete_and_sourced(self):
        for key, resorts in SUMMER_RESORT_CATALOG.items():
            self.assertIn(key, SUMMER_WEATHER, key)
            self.assertIn(key, hol.HOLIDAY_SEARCH_QUERIES, key)
            self.assertIn(key, hol.HOLIDAY_AIRPORTS, key)
            for resort in resorts:
                with self.subTest(resort=resort["name"]):
                    self.assertTrue(resort["hotel_url"].startswith("https://"))
                    self.assertIn(resort["stars"], (4, 5))
                    self.assertIn(
                        resort["confidence"],
                        # "" is the no-rate entries added 2026-10-03 (H6):
                        # a unit with no rate yet has no basis to claim, and
                        # the collector makes no card from it until the engine
                        # reads one.
                        ("market-supported", "estimate", ""),
                    )
                    if resort["confidence"] == "":
                        self.assertNotIn("base_nightly_room_rate_gbp", resort,
                                         "an entry with no confidence must also carry no rate")
                    self.assertTrue(resort["routing"], "a long-haul resort must state its routing")
                    self.assertIn(resort["airport"], hol.BUSINESS_CARRIER_BY_AIRPORT)
                    arch = SUITE_ARCHITECTURE[resort["name"]]
                    if resort["confidence"] != "":
                        # An entry that claims a basis must carry a rate.
                        # The no-rate entries (H6) are exempt by design.
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
        expected = set()
        no_rate = set()
        # Derived from the keys the July config actually carries with
        # resort entries (H9 added the Riviera Maya and Okinawa), not from a
        # pasted list that could drift from the config.
        for key in (LOMBOK_KEYS | THAILAND_KEYS | {"zanzibar", "riviera_maya", "okinawa"}):
            kept, _ = filter_resorts(
                SUMMER_RESORT_CATALOG[key], is_summer=True,
                island=key in hol.ISLAND_RULE_KEYS,
            )
            for resort in kept:
                # A unit with no rate makes no card until one is read, and is
                # ANNOUNCED rather than silently absent (H6, 2026-10-03).
                if not hol._suite_for(resort).get("suite_nightly_gbp"):
                    no_rate.add(resort["name"])
                else:
                    expected.add(resort["name"])
        self.assertEqual(names, expected)
        filtered = {name for name, _reason in hol.LAST_FILTERED_OUT}
        self.assertTrue(
            no_rate <= filtered,
            "a resort with no rate read must be listed as awaiting one",
        )
        for key in LOMBOK_KEYS | THAILAND_KEYS:
            for resort in SUMMER_RESORT_CATALOG[key]:
                if resort["name"] not in expected:
                    self.assertIn(resort["name"], filtered)
        for row in hol.LAST_OVER_BUDGET:
            with self.subTest(resort=row["resort_name"]):
                self.assertGreater(row["true_d2d"], config.max_budget_gbp)
                self.assertEqual(row["flight_confidence"], "benchmark")
        # Since 2026-09-30 a long-haul card needs only ONE of its three flight
        # options within budget; its Business headline may be over.
        for deal in deals:
            with self.subTest(card=deal.resort_name):
                self.assertTrue(any(o["within_budget"] for o in deal.flight_options))
                for option in deal.flight_options:
                    self.assertEqual(
                        option["within_budget"],
                        option["total_pkg"] <= config.max_budget_gbp
                        and option["true_d2d"] <= config.max_budget_gbp,
                    )
        if hol.LAST_OVER_BUDGET:
            html = render_holiday_report(
                config, generated_at="2026-09-29T00:00:00+00:00", deals=deals
            )
            self.assertIn("Resorts priced over", html)
            # One provenance word per fare (2026-10-02): an unread fare's basis
            # is stated as "benchmark", never "benchmark estimate".
            self.assertIn("(benchmark)", html)

    def test_short_haul_over_budget_is_listed_only_for_uncarded_destinations(self):
        fixture = load_holiday_config(
            (ROOT / "tests" / "fixtures" / "july_short_haul_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(fixture)
        self.assertTrue(deals)
        carded = {d.destination_key for d in deals}
        for row in hol.LAST_OVER_BUDGET:
            self.assertNotIn(row["destination_key"], carded)
        # Priced out entirely, every short-haul destination is stated.
        collect_holiday_deals(fixture, max_budget_gbp=100.0)
        listed = {row["destination_key"] for row in hol.LAST_OVER_BUDGET}
        self.assertTrue({"antalya", "tenerife", "paphos", "hurghada"} <= listed)

    def test_cards_state_routing_estimates_and_the_rule_not_applied(self):
        config = dataclasses.replace(_july(), max_budget_gbp=UNCAPPED_GBP)
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertEqual(deal.cabin_class, "ECONOMY")
                self.assertTrue(deal.routing)
                # Every July route connects, so with no live fare in this run the
                # FLIGHT half of the headline is a benchmark. Asserted on the
                # flight's own basis rather than on ``confidence``, which is the
                # weaker of the two legs for the freshness tag and says
                # "market-supported" when it is a hotel rate that was read.
                self.assertEqual(deal.flight_price_basis, "benchmark_supplied")
                self.assertNotIn(deal.confidence, ("verified-exact-date", "stale-cache"))
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
        # Unassessed criteria are no longer a second caveat line of their own:
        # they join the single "not verified" booking-terms list (2026-10-02).
        self.assertIn("Booking terms:", html)
        self.assertIn("not verified:", html)
        self.assertIn("criteria scores", html)
        self.assertNotIn("criteria scores not assessed", html)

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
