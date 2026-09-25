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
  "cabin_classes": ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"]}
  ]
}
"""


def _evidence(basis: str, total: float, *, exact: bool = True, cabin: str = "ECONOMY") -> LiveFareEvidence:
    return LiveFareEvidence(
        airport="AYT",
        total_gbp=total,
        basis=basis,
        source_url="https://example.invalid/search",
        observed_at="2026-09-16T00:00:00+00:00",
        exact_date_match=exact,
        cabin_class=cabin,
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
            # benchmark and WHICH cabin the benchmark was taken in, rather
            # than leaving either ambiguous.
            expected = "benchmark_supplied" if deal.cabin_class == "ECONOMY" else (
                f"benchmark_supplied_{deal.cabin_class.lower()}"
            )
            self.assertEqual(deal.flight_price_basis, expected)

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
            {("AYT", "ECONOMY"): _evidence("whole_party_return_total", 1234.56)}
        )
        promoted = [d for d in deals if d.confidence == "verified-exact-date"]
        self.assertTrue(promoted, "whole-party exact-date evidence should promote")
        for deal in promoted:
            self.assertEqual(deal.flight_price_total_gbp, 1234.56)
            self.assertEqual(deal.flight_price_basis, "whole_party_return_total")
            self.assertEqual(deal.source_url, "https://example.invalid/search")

    def test_business_card_prices_only_from_business_evidence(self):
        # The 2026-09-22 cabin-seam fix: an ECONOMY fare must never price (or
        # LIVE-verify) the Business card of the same airport.
        economy_only = self._deals(
            {("AYT", "ECONOMY"): _evidence("whole_party_return_total", 1234.56)}
        )
        business = [
            d
            for d in economy_only
            if getattr(d, "cabin_class", "") == "BUSINESS"
        ]
        self.assertTrue(business)
        for deal in business:
            self.assertNotEqual(deal.confidence, "verified-exact-date")

        both = self._deals(
            {
                ("AYT", "ECONOMY"): _evidence("whole_party_return_total", 1234.56),
                ("AYT", "BUSINESS"): _evidence(
                    "whole_party_return_total", 3100.0, cabin="BUSINESS"
                ),
            }
        )
        business_promoted = [
            d for d in both if d.cabin_class == "BUSINESS" and d.confidence == "verified-exact-date"
        ]
        self.assertTrue(business_promoted, "BUSINESS evidence should verify BUSINESS cards")
        for deal in business_promoted:
            self.assertEqual(deal.flight_price_total_gbp, 3100.0)


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
        import tempfile
        from datetime import datetime, timezone

        self.config = load_holiday_config(CONFIG_JSON)
        self.outbound, self.return_date = _target_date_pair(self.config)
        self.assertEqual(
            (self.outbound, self.return_date), ("2026-12-22", "2026-12-30")
        )
        self.stale = "2026-09-01T00:00:00+00:00"
        # The age reference is pinned, never the wall clock: these fixtures use
        # literal observed_at values, and measuring them against `now()` made
        # every one a time bomb that went stale 72h after it was written. The
        # loader takes `now` for exactly this; pin it so the assertions test
        # the rejection RULES (party, origin, dates, staleness) and not the
        # calendar.
        self.now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
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
        offers = try_live_flight_offers(self.config, path=path, now=self.now)
        self.assertEqual(set(offers), {("AYT", "ECONOMY")})
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
        offers = try_live_flight_offers(self.config, path=path, now=self.now)
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
        self.assertEqual(
            dict(try_live_flight_offers(self.config, path=path, now=self.now)), {}
        )
        self.assertIn("do not match", consume_skip_log()[0])

    def test_wrong_party_size_is_rejected(self):
        path = self._write([self._rec(travellers=2)])
        self.assertEqual(
            dict(try_live_flight_offers(self.config, path=path, now=self.now)), {}
        )
        self.assertIn("party", consume_skip_log()[0])

    def test_wrong_origin_is_rejected(self):
        # A whole-party fare read from a different departure airport answers
        # a different question, and the report's UK ground cost is origin-
        # specific — so origin must match too.
        path = self._write([self._rec(origin="LGW")])
        self.assertEqual(
            dict(try_live_flight_offers(self.config, path=path, now=self.now)), {}
        )
        self.assertIn("origin", consume_skip_log()[0])

    def test_stale_observation_is_kept_but_never_labelled_live(self):
        """The 2026-09-25 correction. A whole-party exact-date fare observed four
        days ago is real evidence for the exact dates and party this report
        prices; it is merely not current. Dropping it reverted the whole report
        to typical-price benchmarks the moment the 72h bound passed, and did so
        silently. It now prices the card and carries the age in its label.

        The two proposals that must NOT be reintroduced: labelling it
        ``verified-exact-date`` (a stale observation claiming to be live), and
        widening ``EVIDENCE_MAX_AGE_HOURS`` so the drop stops happening while
        the label still lies.
        """
        path = self._write([self._rec(observed_at=self.stale)])
        offers = try_live_flight_offers(self.config, path=path, now=self.now)
        self.assertEqual(set(offers), {("AYT", "ECONOMY")})
        evidence = offers[("AYT", "ECONOMY")]
        self.assertTrue(evidence.stale)
        self.assertTrue(evidence.usable)
        self.assertFalse(evidence.promotable)
        self.assertEqual(evidence.confidence, "stale-cache")
        # The fare still prices the card, and the card says what it is.
        deals = {
            d.resort_name: d
            for d in collect_holiday_deals(
                self.config, live_flight_offers=offers
            )
        }
        stale_deals = [d for d in deals.values() if d.confidence == "stale-cache"]
        self.assertTrue(stale_deals, "the aged fare must still price a card")
        deal = stale_deals[0]
        self.assertNotEqual(deal.confidence, "verified-exact-date")
        self.assertEqual(deal.flight_price_total_gbp, 2000.0)
        self.assertEqual(deal.flight_price_basis, "whole_party_return_total")
        self.assertEqual(deal.live_observed_at, self.stale)
        self.assertTrue(deal.source_url.startswith("https://"))
        # A cheap but load-bearing consequence: nothing in the report may carry
        # the live label off this run's evidence.
        self.assertEqual(
            [d for d in deals.values() if d.confidence == "verified-exact-date"], []
        )

    def test_the_card_says_observed_not_live_and_never_live_verified(self):
        """The label is the whole point of keeping an aged fare: if the card still
        reads 🟢 LIVE VERIFIED then nothing improved. Render the real report with
        the real stale evidence and check the chip."""
        from public_flight_search.holidays import (
            collect_holiday_deals,
            render_holiday_report,
        )

        path = self._write([self._rec(observed_at=self.stale)])
        offers = try_live_flight_offers(self.config, path=path, now=self.now)
        deals = collect_holiday_deals(self.config, live_flight_offers=offers)
        html = render_holiday_report(
            self.config, generated_at="2026-09-25T13:00:00Z", deals=deals
        )
        # The Economy card is not this fixture's headline (the report leads with
        # the cheapest cabin, and the premium benchmark is cheaper than the real
        # Economy fare), so the aged figure surfaces in the alternate-cabins row.
        # Either way it must never read live.
        self.assertIn("🟠 observed earlier, not live", html)
        self.assertNotIn("🟢 live observed", html)
        self.assertNotIn("🟢 LIVE VERIFIED", html)

    def test_a_stale_headline_fare_says_observed_not_live(self):
        """Same rule where the aged fare IS the headline: the card chip itself."""
        from public_flight_search.holidays import (
            collect_holiday_deals,
            render_holiday_report,
        )

        path = self._write([self._rec(observed_at=self.stale)])
        offers = try_live_flight_offers(self.config, path=path, now=self.now)
        stale_deal = next(
            d
            for d in collect_holiday_deals(self.config, live_flight_offers=offers)
            if d.confidence == "stale-cache"
        )
        html = render_holiday_report(
            self.config, generated_at="2026-09-25T13:00:00Z", deals=[stale_deal]
        )
        self.assertIn("🟠 OBSERVED, NOT LIVE", html)
        self.assertNotIn("🟢 LIVE VERIFIED", html)
        self.assertNotIn("🟡 BENCHMARK PRICE", html)
        # AUDITABLE, not decorative: when it was observed and where it came from.
        self.assertIn("observed 2026-09-01", html)
        self.assertIn("fare source", html)

    def test_an_ancient_observation_is_dropped_outright(self):
        """Past the stale-cache ceiling it is not evidence of anything, so it must
        not stand in for a current price. 30 days is the ceiling."""
        from public_flight_search.live_verify import (
            EVIDENCE_STALE_CACHE_MAX_AGE_HOURS,
        )

        with self.subTest("just inside the ceiling is kept"):
            path = self._write(
                [self._rec(observed_at="2026-08-22T12:00:00+00:00")]
            )
            offers = try_live_flight_offers(self.config, path=path, now=self.now)
            self.assertTrue(offers[("AYT", "ECONOMY")].stale)
        with self.subTest("past the ceiling is dropped"):
            path = self._write(
                [self._rec(observed_at="2026-08-01T12:00:00+00:00")]
            )
            self.assertEqual(
                dict(try_live_flight_offers(self.config, path=path, now=self.now)),
                {},
            )
            self.assertIn("expired", consume_skip_log()[0])
        self.assertEqual(EVIDENCE_STALE_CACHE_MAX_AGE_HOURS, 24 * 30)

    def test_future_observation_is_rejected(self):
        path = self._write([self._rec(observed_at="2030-01-01T00:00:00+00:00")])
        self.assertEqual(
            dict(try_live_flight_offers(self.config, path=path, now=self.now)), {}
        )
        self.assertIn("future", consume_skip_log()[0])

    def test_missing_source_url_is_rejected(self):
        path = self._write([self._rec(source_url="not-a-url")])
        self.assertEqual(
            dict(try_live_flight_offers(self.config, path=path, now=self.now)), {}
        )
        self.assertIn("source_url", consume_skip_log()[0])

    def test_bad_total_is_rejected(self):
        path = self._write([self._rec(total_gbp=-5)])
        self.assertEqual(
            dict(try_live_flight_offers(self.config, path=path, now=self.now)), {}
        )

    def test_missing_file_returns_empty_without_error(self):
        import os

        path = os.path.join(self._tmpdir.name, "absent.json")
        self.assertEqual(
            dict(try_live_flight_offers(self.config, path=path, now=self.now)), {}
        )

    def test_freshest_observation_wins_per_airport(self):
        path = self._write(
            [
                self._rec(total_gbp=1111.0, observed_at="2026-09-20T00:00:00+00:00"),
                self._rec(total_gbp=2222.0, observed_at="2026-09-21T00:00:00+00:00"),
            ]
        )
        offers = try_live_flight_offers(self.config, path=path, now=self.now)
        self.assertEqual(offers[("AYT", "ECONOMY")].total_gbp, 2222.0)
        consume_skip_log()

    def test_business_entry_is_accepted_and_keyed_separately(self):
        # July's report is BUSINESS-led: a whole-party business fare must
        # survive the loader and land on the BUSINESS key.
        path = self._write(
            [
                self._rec(
                    cabin_class="BUSINESS",
                    total_gbp=3150.0,
                    carrier="Turkish Airlines",
                )
            ]
        )
        offers = try_live_flight_offers(self.config, path=path, now=self.now)
        self.assertEqual(set(offers), {("AYT", "BUSINESS")})
        self.assertEqual(offers[("AYT", "BUSINESS")].total_gbp, 3150.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
