"""Cabin policy: BUSINESS only when the flight is over 8 hours from London.

Owner rule (2026-09-28): no premium economy anywhere, and BUSINESS only for a
flight OVER 8 hours from London; everything else is ECONOMY. The boundary is
derived in code (``cabin.py``) from each destination's ``flight_hours``, so a
config can no longer price a four-hour hop in Business, as the July 2027
example did. Pinned boundary: 7.9 h -> ECONOMY, 8.1 h -> BUSINESS, and 8.0 h
exactly is not OVER eight hours, so ECONOMY.
"""

import json
import unittest
from pathlib import Path

from public_flight_search.cabin import (
    DEFAULT_FLIGHT_HOURS_LHR,
    cabin_for_flight_hours,
    destination_cabin,
)
from public_flight_search.config import ConfigError
from public_flight_search.holidays import (
    FAR_EAST_PRICE_LABEL,
    FAR_EAST_WATCH,
    collect_holiday_deals,
    destination_cabins,
    far_east_watch_rows,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"
DEC = EXAMPLES / "dec_holiday_config.json"
JULY = EXAMPLES / "july_holiday_config.json"

#: Every destination the planners carried before 2026-09-28. All are under
#: eight hours from London, so every one must now price ECONOMY.
PRE_RULE_DESTINATIONS = {
    "antalya", "malta", "taghazout", "hurghada", "cairo", "muscat", "doha",
    "tenerife", "madeira", "lanzarote", "cape_verde", "fuerteventura",
    "gran_canaria", "paphos",
}
FAR_EAST_DECEMBER = ["phuket", "krabi", "langkawi", "penang", "singapore", "phu_quoc"]
#: July since 2026-09-29: Lombok and Thailand lead (resort cards, no watch
#: row), then the watch destinations. Kota Kinabalu left with Malaysia.
LONG_HAUL_JULY = ["lombok", "koh_samui", "koh_phangan", "khao_lak", "bali", "da_nang", "japan"]
FAR_EAST_JULY = ["bali", "da_nang", "japan"]


def _payload(destinations, **root):
    payload = {
        "report_title": "Cabin test", "party": {"travellers": 5, "rooms": [2, 2, 1]},
        "departure_window": ["06:00", "23:59"], "origins": ["LHR"],
        "outbound_dates": ["2026-12-22"], "return_dates": ["2026-12-30"],
        "destinations": destinations,
    }
    payload.update(root)
    return json.dumps(payload)


class BoundaryTests(unittest.TestCase):
    def test_7_9_hours_is_economy(self):
        self.assertEqual(cabin_for_flight_hours(7.9), "ECONOMY")

    def test_8_1_hours_is_business(self):
        self.assertEqual(cabin_for_flight_hours(8.1), "BUSINESS")

    def test_exactly_8_hours_is_economy(self):
        self.assertEqual(cabin_for_flight_hours(8.0), "ECONOMY")

    def test_premium_economy_is_never_derived(self):
        for hours in (1.0, 4.5, 7.9, 8.0, 8.1, 13.0, 17.25):
            with self.subTest(hours=hours):
                self.assertIn(cabin_for_flight_hours(hours), {"ECONOMY", "BUSINESS"})

    def test_missing_or_bad_hours_refuse_to_guess(self):
        for bad in (None, 0, -1, "long"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                cabin_for_flight_hours(bad)


class LoaderDerivesTheCabinTests(unittest.TestCase):
    def test_config_business_on_a_short_hop_prices_economy(self):
        # The July example's old shape: per-destination BUSINESS on a 4h30 hop.
        config = load_holiday_config(_payload(
            [{"key": "antalya", "label": "Antalya", "airports": ["AYT"],
              "cabin_class": "BUSINESS", "flight_hours": 4.5}],
            cabin_class="BUSINESS", cabin_classes=["BUSINESS", "PREMIUM_ECONOMY"],
        ))
        dest = config.destinations[0]
        self.assertEqual(dest.cabin_class, "ECONOMY")
        self.assertEqual(destination_cabins(config, dest), ("ECONOMY",))
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        self.assertEqual({d.cabin_class for d in deals}, {"ECONOMY"})

    def test_config_economy_on_a_long_haul_prices_business(self):
        config = load_holiday_config(_payload(
            [{"key": "phuket", "label": "Phuket", "airports": ["HKT"],
              "cabin_class": "ECONOMY", "flight_hours": 12.17}],
        ))
        self.assertEqual(destination_cabin(config.destinations[0]), "BUSINESS")

    def test_legacy_config_without_hours_uses_the_built_in_table(self):
        # The live December secret predates flight_hours and names premium
        # economy; until it is reloaded it must still load, and price ECONOMY.
        config = load_holiday_config(_payload(
            [{"key": key, "label": key, "airports": ["XXX"]} for key in sorted(PRE_RULE_DESTINATIONS)],
            cabin_class="ECONOMY", cabin_classes=["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS"],
        ))
        for dest in config.destinations:
            with self.subTest(dest=dest.key):
                self.assertEqual(destination_cabins(config, dest), ("ECONOMY",))
        self.assertEqual(config.cabin_classes, ("ECONOMY",))

    def test_unknown_destination_without_hours_fails_at_load(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload([{"key": "atlantis", "label": "A", "airports": ["XXX"]}]))

    def test_unknown_destination_fields_are_still_rejected(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload(
                [{"key": "malta", "label": "Malta", "airports": ["MLA"], "flight_hours": 3.25, "price": 1}]
            ))

    def test_non_numeric_hours_are_rejected(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload(
                [{"key": "malta", "label": "Malta", "airports": ["MLA"], "flight_hours": "3h15"}]
            ))

    def test_unsupported_cabin_names_still_fail_loudly(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload(
                [{"key": "malta", "label": "Malta", "airports": ["MLA"], "cabin_class": "LIEFLAT"}]
            ))


class CommittedConfigTests(unittest.TestCase):
    def _data(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_every_destination_carries_hours_and_a_source_and_no_cabin(self):
        for path in (DEC, JULY):
            data = self._data(path)
            self.assertNotIn("cabin_class", data, path.name)
            self.assertNotIn("cabin_classes", data, path.name)
            for dest in data["destinations"]:
                with self.subTest(config=path.name, dest=dest["key"]):
                    self.assertIsInstance(dest.get("flight_hours"), (int, float))
                    self.assertGreater(len(dest.get("flight_hours_source", "")), 20)
                    self.assertNotIn("cabin_class", dest)
                    self.assertNotIn("cabin_classes", dest)
                    # The built-in table mirrors the committed hours, so a
                    # legacy secret and the example agree on every cabin.
                    self.assertAlmostEqual(
                        DEFAULT_FLIGHT_HOURS_LHR[dest["key"]], dest["flight_hours"], places=2
                    )

    def test_every_pre_rule_destination_is_kept_and_prices_economy(self):
        for path in (DEC, JULY):
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            for dest in config.destinations:
                if dest.key in PRE_RULE_DESTINATIONS:
                    with self.subTest(config=path.name, dest=dest.key):
                        self.assertLess(dest.flight_hours, 8.0)
                        self.assertEqual(dest.cabin_class, "ECONOMY")
        dec_keys = {d["key"] for d in self._data(DEC)["destinations"]}
        self.assertLessEqual(PRE_RULE_DESTINATIONS, dec_keys, "no December destination was dropped")

    def test_far_east_is_added_ranked_first_and_prices_business(self):
        for path, expected in ((DEC, FAR_EAST_DECEMBER), (JULY, LONG_HAUL_JULY)):
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            keys = [d.key for d in config.destinations]
            self.assertEqual(keys[: len(expected)], expected, path.name)
            for dest in config.destinations[: len(expected)]:
                with self.subTest(config=path.name, dest=dest.key):
                    self.assertGreater(dest.flight_hours, 8.0)
                    self.assertEqual(dest.cabin_class, "BUSINESS")

    def test_far_east_rows_are_in_season_and_labelled_benchmark_unverified(self):
        for path, expected in ((DEC, FAR_EAST_DECEMBER), (JULY, FAR_EAST_JULY)):
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            rows = far_east_watch_rows(config)
            self.assertEqual([r["key"] for r in rows], expected)
            for row in rows:
                with self.subTest(config=path.name, dest=row["key"]):
                    self.assertTrue(row["in_season"])
                    self.assertEqual(row["price_basis"], "benchmark, unverified")
                    self.assertEqual(row["cabin"], "BUSINESS")
                    self.assertIn("tfs=", row["flights_url"])  # dated Google Flights search
                    self.assertGreater(row["indicative_total_gbp"], 0)

    def test_report_leads_with_the_far_east_and_never_calls_it_live(self):
        for path in (DEC, JULY):
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
            html = render_holiday_report(config, generated_at="2026-09-28T12:00:00+00:00", deals=deals)
            with self.subTest(config=path.name):
                start = html.index("Far East first")
                # The next section: the cards, or (a long-haul July priced out
                # by its public budget) the over-budget list.
                ends = [i for i in (html.find("One Family Unit"), html.find("Long-haul resorts priced over")) if i >= 0]
                self.assertTrue(ends, "neither cards nor an over-budget list follow the watch")
                first_card = min(ends)
                self.assertLess(start, first_card)
                block = html[start:first_card]
                self.assertIn(FAR_EAST_PRICE_LABEL, block)
                self.assertNotIn("LIVE VERIFIED", block)
                self.assertNotIn("Premium Economy", html)

    def test_watch_table_covers_only_long_haul_keys(self):
        for key in FAR_EAST_WATCH:
            with self.subTest(key=key):
                self.assertGreater(DEFAULT_FLIGHT_HOURS_LHR[key], 8.0)


if __name__ == "__main__":
    unittest.main()
