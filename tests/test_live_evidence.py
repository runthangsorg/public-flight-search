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
    _target_date_pair,
    consume_skip_log,
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


class TestEvidenceFileLoader(unittest.TestCase):
    """The committed evidence file is the honest dynamism path: the private
    engine's whole-party observations ride the same transport as history.
    Every rejection here is a fabrication class that must never return."""

    def setUp(self):
        import json
        import tempfile

        self.config = load_holiday_config(CONFIG_JSON)
        self.outbound, self.return_date = _target_date_pair(self.config)
        self.assertEqual(
            (self.outbound, self.return_date), ("2026-12-22", "2026-12-30")
        )
        self.stale = "2026-09-01T00:00:00+00:00"
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, evidence):
        import json
        import os

        path = os.path.join(self._tmpdir.name, "evidence.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"travellers": 5, "evidence": evidence}, handle)
        return path

    def _rec(self, **overrides):
        base = {
            "airport": "AYT",
            "total_gbp": 2000.0,
            "basis": "whole_party_return_total",
            "source_url": "https://example.invalid/search",
            "observed_at": "2026-09-21T00:00:00+00:00",
            "exact_dates": {
                "outbound": self.outbound,
                "return": self.return_date,
            },
            "travellers": 5,
        }
        base.update(overrides)
        return base

    def test_valid_entry_is_accepted_and_promotes_the_deal(self):
        path = self._write([self._rec(total_gbp=1234.5, carrier="Ajet")])
        offers = try_live_flight_offers(self.config, path=path)
        self.assertEqual(set(offers), {"AYT"})
        deals = {
            d.resort_name: d
            for d in collect_holiday_deals(
                self.config, live_flight_offers=offers
            )
        }
        promoted = [
            d for d in deals.values() if d.confidence == "verified-exact-date"
        ]
        self.assertTrue(promoted)
        for deal in promoted:
            self.assertEqual(deal.flight_price_total_gbp, 1234.5)
            self.assertEqual(deal.live_carrier, "Ajet")
            self.assertEqual(deal.flight_price_basis, "whole_party_return_total")
            self.assertTrue(deal.source_url.startswith("https://"))
            self.assertEqual(deal.live_observed_at, "2026-09-21T00:00:00+00:00")

    def test_per_person_basis_is_rejected_not_multiplied(self):
        path = self._write([self._rec(basis="per_person_one_way", total_gbp=200.0)])
        offers = try_live_flight_offers(self.config, path=path)
        self.assertEqual(dict(offers), {})
        self.assertIn("whole-party", consume_skip_log()[0])

    def test_wrong_dates_are_rejected(self):
        path = self._write(
            [
                self._rec(
                    exact_dates={"outbound": "2030-01-01", "return": "2030-01-08"}
                )
            ]
        )
        self.assertEqual(dict(try_live_flight_offers(self.config, path=path)), {})
        self.assertIn("do not match", consume_skip_log()[0])

    def test_wrong_party_size_is_rejected(self):
        path = self._write([self._rec(travellers=2)])
        self.assertEqual(dict(try_live_flight_offers(self.config, path=path)), {})
        self.assertIn("party", consume_skip_log()[0])

    def test_stale_observation_is_rejected(self):
        path = self._write([self._rec(observed_at=self.stale)])
        self.assertEqual(dict(try_live_flight_offers(self.config, path=path)), {})
        self.assertIn("stale", consume_skip_log()[0])

    def test_future_observation_is_rejected(self):
        path = self._write([self._rec(observed_at="2030-01-01T00:00:00+00:00")])
        self.assertEqual(dict(try_live_flight_offers(self.config, path=path)), {})
        self.assertIn("future", consume_skip_log()[0])

    def test_missing_source_url_is_rejected(self):
        path = self._write([self._rec(source_url="not-a-url")])
        self.assertEqual(dict(try_live_flight_offers(self.config, path=path)), {})
        self.assertIn("source_url", consume_skip_log()[0])

    def test_bad_total_is_rejected(self):
        path = self._write([self._rec(total_gbp=-5)])
        self.assertEqual(dict(try_live_flight_offers(self.config, path=path)), {})

    def test_missing_file_returns_empty_without_error(self):
        import os

        path = os.path.join(self._tmpdir.name, "absent.json")
        self.assertEqual(dict(try_live_flight_offers(self.config, path=path)), {})

    def test_freshest_observation_wins_per_airport(self):
        path = self._write(
            [
                self._rec(total_gbp=1111.0, observed_at="2026-09-20T00:00:00+00:00"),
                self._rec(total_gbp=2222.0, observed_at="2026-09-21T00:00:00+00:00"),
            ]
        )
        offers = try_live_flight_offers(self.config, path=path)
        self.assertEqual(offers["AYT"].total_gbp, 2222.0)
        consume_skip_log()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
