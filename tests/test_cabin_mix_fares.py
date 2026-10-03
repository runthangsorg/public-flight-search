"""A fare that mixes cabins may not stand in for a pure-cabin fare.

Owner brief 2026-10-03, H7. A flight-evidence record may carry an optional
string ``cabin_mix`` written by the private engine — free text such as
"Premium Economy long-haul + Economy hop". It is NOT a per-passenger split.

The danger is silence. Such a record carries a single ``cabin_class``, and
without a seam it would file itself under Business or Economy and quietly
become that option: a reader would be shown a mixed-cabin total as the price
of five people in one cabin, which is a different proposition at a different
price. So a mixed record is filed under its own ``MIXED`` cabin, can never be
returned by a pure-cabin lookup, and is rendered on a line of its own.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone

from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)
from public_flight_search.live_verify import (
    MIXED_CABIN,
    LiveFareEvidence,
    evidence_for,
    load_live_flight_evidence,
)

#: Long haul on purpose: only a long-haul card carries the (a)/(b)/(c) flight
#: options a mixed-cabin fare has to stay out of.
CONFIG_JSON = """
{
  "report_title": "Cabin mix test",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2026-12-22"],
  "return_dates": ["2026-12-30"],
  "destinations": [
    {"key": "zanzibar", "label": "Zanzibar", "airports": ["ZNZ"], "flight_hours": 11.67}
  ]
}
"""

NOW = datetime(2026, 12, 21, tzinfo=timezone.utc)
MIX_TEXT = "Premium Economy long-haul + Economy hop"


def _record(**overrides) -> dict:
    """One whole-party, exact-date, five-traveller fare read from LHR."""
    record = {
        "airport": "ZNZ",
        "basis": "whole_party_return_total",
        "total_gbp": 4200.0,
        "source_url": "https://example.invalid/zanzibar-search",
        "observed_at": "2026-12-20T09:00:00+00:00",
        "exact_dates": {"outbound": "2026-12-22", "return": "2026-12-30"},
        "travellers": 5,
        "origin": "LHR",
        "cabin_class": "ECONOMY",
        "carrier": "Example Air",
    }
    record.update(overrides)
    return record


class _Loader:
    """Loads synthetic records through the real loader. Nothing is fetched."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Uncapped: the brief is about what the CARD does with a mixed fare, so
        # the resort has to become a card rather than an over-budget listing.
        self.config = dataclasses.replace(
            load_holiday_config(CONFIG_JSON), max_budget_gbp=60000.0
        )

    def load(self, records) -> dict:
        path = os.path.join(self._tmp.name, "evidence.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"travellers": 5, "evidence": records}, handle)
        return dict(
            load_live_flight_evidence(self.config, path=path, now=NOW)
        )

    def close(self):
        self._tmp.cleanup()


class MixedCabinLoaderTests(unittest.TestCase):
    def setUp(self):
        self.loader = _Loader()
        self.addCleanup(self.loader.close)

    def test_a_mixed_record_keeps_its_text(self):
        offers = self.loader.load([_record(cabin_mix=MIX_TEXT)])
        mixed = [
            evidence
            for evidence in offers.values()
            if evidence.cabin_mix == MIX_TEXT
        ]
        self.assertEqual(len(mixed), 1, "the mixed record did not load")

    def test_a_mixed_record_is_filed_under_the_mixed_cabin(self):
        offers = self.loader.load([_record(cabin_mix=MIX_TEXT)])
        self.assertIn(
            MIXED_CABIN,
            {key[1] for key in offers},
            "a mixed fare must be filed under MIXED, never under a pure cabin",
        )

    def test_a_mixed_record_never_fills_the_economy_slot(self):
        """The failure this brief exists to prevent."""
        offers = self.loader.load(
            [_record(cabin_class="ECONOMY", cabin_mix=MIX_TEXT)]
        )
        self.assertIsNone(
            evidence_for(
                offers, "ZNZ", "ECONOMY", "2026-12-22", "2026-12-30", "LHR"
            ),
            "a mixed-cabin fare stood in for five people in one cabin",
        )

    def test_a_mixed_record_never_fills_the_business_slot(self):
        offers = self.loader.load(
            [_record(cabin_class="BUSINESS", cabin_mix=MIX_TEXT)]
        )
        self.assertIsNone(
            evidence_for(
                offers, "ZNZ", "BUSINESS", "2026-12-22", "2026-12-30", "LHR"
            ),
            "a mixed-cabin fare was offered as the Business option",
        )

    def test_the_mixed_fare_is_still_reachable_as_its_own_cabin(self):
        offers = self.loader.load([_record(cabin_mix=MIX_TEXT)])
        found = evidence_for(
            offers, "ZNZ", MIXED_CABIN, "2026-12-22", "2026-12-30", "LHR"
        )
        self.assertIsNotNone(found, "the mixed fare must still be reachable")
        self.assertEqual(found.total_gbp, 4200.0)
        self.assertEqual(found.cabin_mix, MIX_TEXT)

    def test_mixed_is_not_a_reportable_cabin(self):
        """The seam has to be one-way, or the guard is a naming convention."""
        from public_flight_search.live_verify import EVIDENCE_CABINS

        self.assertNotIn(
            MIXED_CABIN,
            EVIDENCE_CABINS,
            "MIXED must not be a cabin the loader will accept as pure",
        )

    def test_a_record_with_no_cabin_mix_behaves_exactly_as_before(self):
        """The seam is additive: nothing changes for a pure-cabin record."""
        offers = self.loader.load([_record(cabin_class="ECONOMY")])
        self.assertEqual({key[1] for key in offers}, {"ECONOMY"})
        found = evidence_for(
            offers, "ZNZ", "ECONOMY", "2026-12-22", "2026-12-30", "LHR"
        )
        self.assertIsNotNone(found, "a pure record must still price its cabin")
        self.assertEqual(found.cabin_mix, "")
        self.assertFalse(found.mixed_cabin)

    def test_an_unknown_field_is_ignored(self):
        offers = self.loader.load([_record(some_future_field={"a": 1})])
        self.assertEqual({key[1] for key in offers}, {"ECONOMY"})

    def test_a_non_string_cabin_mix_is_ignored_not_crashed_on(self):
        for value in (17, {"a": 1}, ["x"], True):
            with self.subTest(cabin_mix=value):
                offers = self.loader.load([_record(cabin_mix=value)])
                self.assertEqual(
                    {key[1] for key in offers},
                    {"ECONOMY"},
                    "a cabin_mix that is not text must leave the record pure",
                )

    def test_an_empty_cabin_mix_is_not_a_mix(self):
        offers = self.loader.load([_record(cabin_mix="   ")])
        self.assertEqual({key[1] for key in offers}, {"ECONOMY"})


class MixedCabinCardTests(unittest.TestCase):
    """What the card does with a fare it may not use as an option."""

    def setUp(self):
        self.loader = _Loader()
        self.addCleanup(self.loader.close)

    def _deals(self, records):
        return collect_holiday_deals(
            self.loader.config, live_flight_offers=self.loader.load(records)
        )

    def _mixed_rows(self, deals):
        return [
            option
            for deal in deals
            for option in deal.flight_options
            if option["kind"] == "mixed_cabin"
        ]

    def test_the_mixed_fare_is_offered_as_its_own_option(self):
        deals = self._deals([_record(cabin_mix=MIX_TEXT)])
        rows = self._mixed_rows(deals)
        self.assertTrue(rows, "the mixed fare never reached the card")
        self.assertEqual(rows[0]["flight_cost"], 4200.0)
        self.assertEqual(rows[0]["cabin_mix"], MIX_TEXT)

    def test_the_mixed_fare_is_not_business_and_not_economy(self):
        """£4,200 must appear ONLY on the mixed row, never on a pure one."""
        deals = self._deals([_record(cabin_mix=MIX_TEXT)])
        pure_kinds = ("business", "economy", "premium_economy")
        for deal in deals:
            for option in deal.flight_options:
                if option["kind"] not in pure_kinds:
                    continue
                with self.subTest(resort=deal.resort_name, kind=option["kind"]):
                    self.assertNotEqual(
                        float(option["flight_cost"]),
                        4200.0,
                        f"the mixed fare was priced into the "
                        f"{option['kind']} option",
                    )

    def test_the_card_names_the_mix_on_its_own_line(self):
        deals = self._deals([_record(cabin_mix=MIX_TEXT)])
        html = render_holiday_report(
            self.loader.config,
            generated_at="2026-12-21T00:00:00+00:00",
            deals=deals,
        )
        self.assertIn("mixed cabins", html)
        self.assertIn(MIX_TEXT, html)

    def test_the_mix_sits_next_to_the_fare_label(self):
        deals = self._deals([_record(cabin_mix=MIX_TEXT)])
        html = render_holiday_report(
            self.loader.config,
            generated_at="2026-12-21T00:00:00+00:00",
            deals=deals,
        )
        # The fare figure and the mix text must appear on the SAME line, or
        # the reader has to join them up themselves.
        lines = [line for line in re.split(r"<br\s*/?>", html) if "mixed cabins" in line]
        self.assertTrue(lines, "no line carries the mixed-cabin fare")
        with self.subTest(line=lines[0][:200]):
            self.assertIn("£4,200", lines[0])
            self.assertIn(MIX_TEXT, lines[0])

    def test_no_mix_leaves_the_card_exactly_as_it_was(self):
        """The additive seam, asserted on the rendered report."""
        pure = render_holiday_report(
            self.loader.config,
            generated_at="2026-12-21T00:00:00+00:00",
            deals=self._deals([_record()]),
        )
        self.assertNotIn("mixed cabins", pure)
        self.assertEqual(
            self._mixed_rows(self._deals([_record()])), []
        )

    def test_a_mix_is_not_invented_when_no_fare_was_read(self):
        """require_evidence: no benchmark for a cabin mix, so no line."""
        deals = self._deals([_record()])
        html = render_holiday_report(
            self.loader.config,
            generated_at="2026-12-21T00:00:00+00:00",
            deals=deals,
        )
        self.assertNotIn("mixed cabins", html)

    def test_an_over_budget_listing_also_names_the_mix(self):
        """The over-budget table shows options too, and must not hide it there."""
        import public_flight_search.holidays as hol

        capped = dataclasses.replace(self.loader.config, max_budget_gbp=5000.0)
        collect_holiday_deals(
            capped, live_flight_offers=self.loader.load([_record(cabin_mix=MIX_TEXT)])
        )
        rows = [
            option
            for row in hol.LAST_OVER_BUDGET
            for option in row["flight_options"]
            if option["kind"] == "mixed_cabin"
        ]
        self.assertTrue(rows, "the over-budget listing dropped the mix")
        self.assertEqual(rows[0]["cabin_mix"], MIX_TEXT)
