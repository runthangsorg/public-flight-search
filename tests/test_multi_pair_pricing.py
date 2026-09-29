"""Pricing every date pair in the nights band, from every configured origin.

WHY this file exists
--------------------
Until 2026-09-29 the collector priced ONE pair — the shortlist's middle —
from ``origins[0]``, whatever else the config offered. A 7x7 December window
therefore bought nine (now forty-nine) combinations and used one of them,
and an evidence file full of LGW/STN fares could never price a card because
the loader only accepted the single pair and the single origin.

These tests are the contract for the widening:

* the nights band decides which pairs are candidates, and a band that matches
  nothing must not take the report to zero deals;
* the cheapest candidate wins, with its own dates, nights, origin and ground
  cost carried onto the card;
* a benchmark may only price the declared origin — flight benchmarks carry no
  origin, so a cheaper LGW departure inferred from an LHR benchmark would be
  a fabricated origin;
* an observed fare may win from any configured origin, and only from one;
* evidence is attached to the pair it was read for: one observation never
  stands in for dates nobody observed.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from public_flight_search.holidays import (
    ConfigError,
    collect_holiday_deals,
    load_holiday_config,
    priceable_date_pairs,
    nights_between,
)
from public_flight_search.live_verify import (
    _target_date_pair,
    evidence_for,
    load_live_flight_evidence,
)

ROOT = Path(__file__).parents[1]
DEC_CONFIG = ROOT / "examples" / "dec_holiday_config.json"
JULY_CONFIG = ROOT / "examples" / "july_holiday_config.json"

#: Two 7-9 night pairs plus one 11-night pair, so the band can be shown to
#: filter and the collector can be shown to prefer the cheaper length.
BAND_JSON = """
{
  "report_title": "Band test",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR", "LTN"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2026-12-19", "2026-12-20"],
  "return_dates": ["2026-12-27", "2026-12-28"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"], "flight_hours": 4.5}
  ]
}
"""

OBSERVED_AT = "2026-09-23T00:00:00+00:00"


def _load(payload: str):
    return load_holiday_config(payload)


def _record(
    *,
    outbound: str,
    returning: str,
    total: float = 500.0,
    origin: str = "LHR",
    travellers: int = 5,
    cabin: str = "ECONOMY",
) -> dict:
    return {
        "airport": "AYT",
        "cabin_class": cabin,
        "basis": "whole_party_return_total",
        "total_gbp": total,
        "source_url": "https://example.invalid/hunt",
        "observed_at": OBSERVED_AT,
        "travellers": travellers,
        "origin": origin,
        "exact_dates": {"outbound": outbound, "return": returning},
    }


class TestNightsBandIsConfigurable(unittest.TestCase):
    def test_defaults_are_six_to_ten_nights(self):
        config = _load(
            BAND_JSON.replace('"origins": ["LHR", "LTN"],', '"origins": ["LHR"],')
        )
        self.assertEqual(config.min_nights, 6)
        self.assertEqual(config.max_nights, 10)

    def test_the_band_is_read_from_the_config(self):
        config = _load(
            BAND_JSON.replace(
                '"destinations": [', '"min_nights": 8, "max_nights": 8,\n  "destinations": ['
            )
        )
        self.assertEqual((config.min_nights, config.max_nights), (8, 8))
        self.assertEqual(
            priceable_date_pairs(config),
            (("2026-12-19", "2026-12-27"), ("2026-12-20", "2026-12-28")),
        )

    def test_a_band_that_matches_nothing_falls_back_to_every_pair(self):
        # A misconfigured band must not silence the report: zero deals is an
        # outage, not a quiet market (see test_example_configs).
        config = _load(
            BAND_JSON.replace(
                '"destinations": [', '"min_nights": 40, "max_nights": 60,\n  "destinations": ['
            )
        )
        self.assertEqual(len(priceable_date_pairs(config)), 4)

    def test_min_greater_than_max_is_rejected(self):
        with self.assertRaises(ConfigError):
            _load(
                BAND_JSON.replace(
                    '"destinations": [',
                    '"min_nights": 9, "max_nights": 3,\n  "destinations": [',
                )
            )

    def test_a_nights_bound_is_an_integer(self):
        with self.assertRaises(ConfigError):
            _load(
                BAND_JSON.replace(
                    '"destinations": [',
                    '"min_nights": "eight",\n  "destinations": [',
                )
            )

    def test_the_shipped_configs_state_their_band(self):
        for path in (DEC_CONFIG, JULY_CONFIG):
            with self.subTest(config=path.name):
                config = _load(path.read_text(encoding="utf-8"))
                self.assertEqual((config.min_nights, config.max_nights), (6, 10))


class TestTheDecemberWindowIsWideAndInsideTheBand(unittest.TestCase):
    def test_the_owner_window_is_seven_by_seven(self):
        config = _load(DEC_CONFIG.read_text(encoding="utf-8"))
        outbound = [str(day) for day in config.outbound_dates]
        returning = [str(day) for day in config.return_dates]
        self.assertEqual(outbound, [f"2026-12-{day:02d}" for day in range(17, 24)])
        self.assertEqual(returning, [f"2026-12-{day:02d}" for day in range(25, 32)])

    def test_every_priced_pair_sits_in_the_stay_band(self):
        config = _load(DEC_CONFIG.read_text(encoding="utf-8"))
        priced = priceable_date_pairs(config)
        self.assertTrue(priced)
        for pair in priced:
            with self.subTest(pair=pair):
                self.assertGreaterEqual(nights_between(pair), config.min_nights)
                self.assertLessEqual(nights_between(pair), config.max_nights)

    def test_the_headline_pair_is_still_twenty_december(self):
        # 20 Dec +/- 3 days, eight nights: the pair the evidence contract
        # states and the dates a benchmark-only run displays.
        config = _load(DEC_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(_target_date_pair(config), ("2026-12-20", "2026-12-28"))
        self.assertIn(("2026-12-20", "2026-12-28"), priceable_date_pairs(config))


class TestCollectorPricesEveryCandidate(unittest.TestCase):
    def test_the_cheapest_priced_pair_wins_with_its_own_dates_and_nights(self):
        config = _load(BAND_JSON)
        deals = collect_holiday_deals(config, max_budget_gbp=10**9)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                # 20 Dec -> 27 Dec is the only seven-night pair in the band.
                self.assertEqual(deal.return_date, "2026-12-27")
                self.assertEqual(deal.nights, 7)

    def test_a_cheaper_observed_fare_on_another_priced_pair_wins(self):
        from public_flight_search.live_verify import LiveFareEvidence

        config = _load(BAND_JSON)
        headline = _target_date_pair(config)
        other = next(
            pair for pair in priceable_date_pairs(config) if pair != headline
        )
        offers = {
            ("AYT", "ECONOMY", other[0], other[1], "LHR"): LiveFareEvidence(
                airport="AYT",
                total_gbp=1.0,
                basis="whole_party_return_total",
                source_url="https://example.invalid/hunt",
                observed_at=OBSERVED_AT,
                cabin_class="ECONOMY",
            )
        }
        deals = collect_holiday_deals(
            config, max_budget_gbp=10**9, live_flight_offers=offers
        )
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertEqual(
                    (deal.outbound_date, deal.return_date),
                    other,
                    "the cheaper observed pair must be the dates shown",
                )
                self.assertEqual(deal.confidence, "verified-exact-date")
                self.assertEqual(deal.flight_price_total_gbp, 1.0)

    def test_a_benchmark_never_prices_a_cheaper_second_origin(self):
        # LTN ground is GBP14.50 against LHR's GBP16.50, so an origin-blind
        # benchmark would pick LTN for two pounds — and claim a departure
        # airport nothing was priced from.
        config = _load(BAND_JSON)
        deals = collect_holiday_deals(config, max_budget_gbp=10**9)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertEqual(deal.origin, "LHR")
                self.assertEqual(deal.uk_ground_gbp, 16.50)
                self.assertEqual(deal.flight_price_basis, "benchmark_supplied")

    def test_an_observed_fare_from_another_origin_wins_with_its_ground_cost(self):
        from public_flight_search.live_verify import LiveFareEvidence

        config = _load(BAND_JSON)
        outbound, returning = _target_date_pair(config)
        offers = {
            ("AYT", "ECONOMY", outbound, returning, "LTN"): LiveFareEvidence(
                airport="AYT",
                total_gbp=1.0,
                basis="whole_party_return_total",
                source_url="https://example.invalid/hunt",
                observed_at=OBSERVED_AT,
                cabin_class="ECONOMY",
            )
        }
        deals = collect_holiday_deals(
            config, max_budget_gbp=10**9, live_flight_offers=offers
        )
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertEqual(deal.origin, "LTN")
                self.assertEqual(deal.uk_ground_gbp, 14.50)
                self.assertEqual(deal.confidence, "verified-exact-date")

    def test_no_combination_under_budget_drops_the_resort(self):
        config = _load(BAND_JSON)
        deals = collect_holiday_deals(config, max_budget_gbp=1.0)
        self.assertEqual(deals, ())


class TestEvidenceIsAttachedToThePairItWasReadFor(unittest.TestCase):
    def setUp(self):
        self.config = _load(BAND_JSON)
        self._tmpdir = tempfile.TemporaryDirectory()
        self.now = datetime.fromisoformat(OBSERVED_AT)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _load_evidence(self, records: list[dict]):
        path = f"{self._tmpdir.name}/evidence.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"evidence": records}, handle)
        return load_live_flight_evidence(
            self.config, path=path, now=self.now
        )

    def test_a_record_for_any_priced_pair_is_kept(self):
        headline = _target_date_pair(self.config)
        other = next(
            pair
            for pair in priceable_date_pairs(self.config)
            if pair != headline
        )
        loaded = self._load_evidence(
            [_record(outbound=other[0], returning=other[1])]
        )
        self.assertEqual(len(loaded), 1)
        self.assertIsNotNone(
            evidence_for(
                loaded,
                "AYT",
                "ECONOMY",
                other[0],
                other[1],
                "LHR",
                headline=headline,
            )
        )
        # ...and for the pair it was NOT read for.
        self.assertIsNone(
            evidence_for(
                loaded, "AYT", "ECONOMY", headline[0], headline[1], "LHR",
                headline=headline,
            )
        )

    def test_a_record_for_a_pair_outside_the_band_is_rejected(self):
        loaded = self._load_evidence(
            [_record(outbound="2026-12-20", returning="2026-12-31")]  # 11 nights
        )
        self.assertEqual(loaded, {})

    def test_a_record_from_a_configured_origin_is_kept(self):
        outbound, returning = _target_date_pair(self.config)
        loaded = self._load_evidence(
            [_record(outbound=outbound, returning=returning, origin="LTN")]
        )
        self.assertEqual(len(loaded), 1)

    def test_a_record_from_an_unconfigured_origin_is_rejected(self):
        outbound, returning = _target_date_pair(self.config)
        loaded = self._load_evidence(
            [_record(outbound=outbound, returning=returning, origin="STN")]
        )
        self.assertEqual(loaded, {})

    def test_records_for_different_pairs_are_kept_side_by_side(self):
        pairs = priceable_date_pairs(self.config)
        self.assertGreater(len(pairs), 1)
        loaded = self._load_evidence(
            [_record(outbound=outbound, returning=returning) for outbound, returning in pairs]
        )
        self.assertEqual(len(loaded), len(pairs))


if __name__ == "__main__":
    unittest.main()
