"""Integrity tests for the live flight-evidence boundary.

These exist because the holiday report once crowned a number derived as
``one_way_per_person * travellers * 2`` with the confidence label
``verified-exact-date``. Every test here is written to fail if that class
of fabrication is ever reintroduced.
"""

from __future__ import annotations

import unittest

from public_flight_search.holidays import collect_holiday_deals, load_holiday_config
from public_flight_search.live_verify import (
    LiveFareEvidence,
    try_live_flight_offers,
    live_evidence_unavailable_reason,
)

CONFIG_JSON = """
{
  "report_title": "Evidence boundary test",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2026-12-22"],
  "return_dates": ["2026-12-30"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"]}
  ]
}
"""


def _evidence(basis: str, total: float, *, exact: bool = True) -> LiveFareEvidence:
    return LiveFareEvidence(
        airport="AYT",
        total_gbp=total,
        basis=basis,
        source_url="https://example.invalid/search",
        observed_at="2026-09-16T00:00:00+00:00",
        exact_date_match=exact,
    )


class TestPromotableBases(unittest.TestCase):
    def test_whole_party_bases_are_promotable(self):
        self.assertTrue(
            _evidence("whole_party_return_total", 1000.0).promotable
        )
        self.assertTrue(
            _evidence("whole_party_one_way_total", 600.0).promotable
        )

    def test_per_person_bases_are_never_promotable(self):
        for basis in (
            "per_person_one_way",
            "per_person_return",
            "derived_from_per_person",
            "nightly_room_rate",
        ):
            with self.subTest(basis=basis):
                self.assertFalse(_evidence(basis, 200.0).promotable)

    def test_exact_date_is_required_too(self):
        evidence = _evidence("whole_party_return_total", 1000.0, exact=False)
        self.assertFalse(evidence.promotable)

    def test_a_overnight_hotel_nightly_rate_is_flagged_non_promotable(self):
        self.assertTrue(
            _evidence("nightly_room_rate", 300.0).is_non_promotable_basis
        )


class TestDealLabelling(unittest.TestCase):
    def _deals(self, offers):
        config = load_holiday_config(CONFIG_JSON)
        return collect_holiday_deals(config, live_flight_offers=offers)

    def test_no_evidence_leaves_deals_on_benchmarks(self):
        deals = self._deals(None)
        self.assertTrue(deals, "expected benchmark deals to be produced")
        for deal in deals:
            self.assertNotEqual(deal.confidence, "verified-exact-date")
            # Every benchmark deal states that its flight figure is a
            # benchmark, rather than leaving the basis ambiguous.
            self.assertEqual(deal.flight_price_basis, "benchmark_supplied")

    def test_a_per_person_basis_does_not_promote_and_is_not_multiplied(self):
        # 5 travellers at GBP200 per person is GBP1,000 only if multiplied.
        # The engine must not consume it as a party total at all.
        benchmark_deals = {d.resort_name: d for d in self._deals(None)}
        deals = {
            d.resort_name: d
            for d in self._deals({"AYT": _evidence("per_person_one_way", 200.0)})
        }
        self.assertEqual(set(benchmark_deals), set(deals))
        for name, deal in deals.items():
            with self.subTest(resort=name):
                self.assertNotEqual(deal.confidence, "verified-exact-date")
                self.assertNotEqual(deal.flight_price_total_gbp, 1000.0)
                self.assertEqual(
                    deal.flight_price_total_gbp,
                    benchmark_deals[name].flight_price_total_gbp,
                )

    def test_whole_party_exact_date_evidence_promotes_and_carries_its_basis(self):
        deals = self._deals(
            {"AYT": _evidence("whole_party_return_total", 1234.56)}
        )
        promoted = [d for d in deals if d.confidence == "verified-exact-date"]
        self.assertTrue(promoted, "whole-party exact-date evidence should promote")
        for deal in promoted:
            self.assertEqual(deal.flight_price_total_gbp, 1234.56)
            self.assertEqual(deal.flight_price_basis, "whole_party_return_total")
            self.assertEqual(deal.source_url, "https://example.invalid/search")


class TestNoFabrication(unittest.TestCase):
    def test_http_path_returns_no_evidence_rather_than_a_derived_figure(self):
        import os

        previous = os.environ.get("HOLIDAY_LIVE_FLIGHTS")
        os.environ["HOLIDAY_LIVE_FLIGHTS"] = "1"
        try:
            config = load_holiday_config(CONFIG_JSON)
            offers = try_live_flight_offers(config)
        finally:
            if previous is None:
                os.environ.pop("HOLIDAY_LIVE_FLIGHTS", None)
            else:
                os.environ["HOLIDAY_LIVE_FLIGHTS"] = previous

        # The results page carries no fares in its server-rendered HTML, so
        # the only honest answer is "no evidence".
        self.assertEqual(dict(offers), {})

    def test_unavailable_reason_explains_the_benchmark_fallback(self):
        reason = live_evidence_unavailable_reason()
        self.assertIn("browser", reason.lower())
        self.assertIn("market-supported", reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
