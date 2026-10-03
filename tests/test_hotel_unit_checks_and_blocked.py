"""Unit checks, blocked sources and the rating a card states (brief H4).

Three facts the report was either missing or stating badly:

* a ``unit_checks`` finding that means no single unit will take the party in
  one booking is a reason to DROP the resort, with the finding as the reason.
  Offering a resort we have watched refuse five adults in one booking is worse
  than not offering it;
* a ``blocked`` entry is the difference between "we did not read it" and "we
  could not read it". "TripAdvisor >=4.5 not verified" becomes "TripAdvisor
  blocked (DataDome)" — a bot wall is a fact about the source, and saying so
  stops the card implying the rating was judged and fell short;
* the Google rating is shown with its source and its review count, because a
  bare 4.6 is a number with no denominator.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from public_flight_search import holidays
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_gate_not_applied,
    render_holiday_report,
)
from public_flight_search.hotel_evidence import consume_hotel_skip_log, load_hotel_evidence

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/hotel_evidence_sample.json"

NOW = "2026-10-03T12:00:00+00:00"
RESORT = "Pullman Lombok Merujani Mandalika Beach Resort"

CONFIG = """
{
  "report_title": "Unit checks and blocked sources",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 6,
  "max_nights": 10,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "lombok", "label": "Lombok", "airports": ["LOP"], "flight_hours": 24.0}
  ]
}
"""


def _collect(extra: dict, *, rates=None):
    import json
    import os

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for section, entries in extra.items():
        payload[section] = list(entries)
    if rates is not None:
        payload["rates"] = list(rates)
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    config = load_holiday_config(CONFIG)
    loaded = load_hotel_evidence(config, path=handle.name, now=NOW)
    deals = collect_holiday_deals(config, max_budget_gbp=10 ** 9,
                                  hotel_evidence=loaded)
    consume_hotel_skip_log()
    return deals


def _unit_check(finding: str = "5 adults in one room refused") -> dict:
    return {
        "property_name": RESORT,
        "destination_key": "lombok",
        "season": "summer",
        "dates": ["2027-07-20", "2027-07-27"],
        "vendor": "Example",
        "finding": finding,
        "source_url": "https://example.invalid/check",
        "observed_at": "2026-10-02T14:51:52+00:00",
    }


def _blocked(what: str = "TripAdvisor", reason: str = "DataDome challenge") -> dict:
    return {
        "what": what,
        "property_name": RESORT,
        "reason": reason,
        "source_url": "https://example.invalid/blocked",
        "observed_at": "2026-10-02T15:00:00+00:00",
    }


def _rating(score: float = 4.6, count: str = "1.2k", source: str = "Google") -> dict:
    return {
        "property_name": RESORT,
        "source": source,
        "score": score,
        "scale": 5,
        "review_count": count,
        "where": "Google Hotels hotel page",
        "source_url": "https://example.invalid/rating",
        "observed_at": "2026-10-02T15:18:50+00:00",
    }


class UnitCheckTests(unittest.TestCase):
    def test_a_refusal_removes_the_resort(self):
        deals = _collect({"unit_checks": [_unit_check()]}, rates=[])
        self.assertNotIn(RESORT, [deal.resort_name for deal in deals])

    def test_the_removal_carries_the_finding_as_its_reason(self):
        _collect({"unit_checks": [_unit_check()]}, rates=[])
        # Read through the module: the collector rebinds this global each run,
        # so a name imported at module load would still hold the old value.
        removed = {name: reason for name, reason in holidays.LAST_FILTERED_OUT}
        reason = removed.get(RESORT)
        self.assertIsNotNone(reason, "the removal must be listed with a reason")
        self.assertIn(
            "5 adults in one room refused", reason,
            "the engine's own words, plus the dates they were checked for",
        )
        self.assertIn("2027-07-20", reason)

    def test_the_other_resorts_survive(self):
        deals = _collect({"unit_checks": [_unit_check()]}, rates=[])
        self.assertTrue(deals, "one resort refusing the party must not empty the report")
        self.assertNotIn(RESORT, [deal.resort_name for deal in deals])

    def test_a_check_for_another_property_removes_nothing(self):
        other = _unit_check()
        other["property_name"] = "Some Other Resort"
        deals = _collect({"unit_checks": [other]}, rates=[])
        self.assertIn(RESORT, [deal.resort_name for deal in deals])

    def test_a_unit_check_that_found_nothing_does_not_remove_the_resort(self):
        fine = _unit_check("two units available: 2+2 and 3+2, both one booking")
        deals = _collect({"unit_checks": [fine]}, rates=[])
        self.assertIn(RESORT, [deal.resort_name for deal in deals])


class BlockedSourceTests(unittest.TestCase):
    def test_a_blocked_source_replaces_the_not_verified_claim(self):
        deals = _collect({"blocked": [_blocked()]}, rates=[])
        deal = next(deal for deal in deals if deal.resort_name == RESORT)
        joined = " | ".join(deal.highlights)
        self.assertIn("TripAdvisor blocked (DataDome challenge)", joined)

    def test_the_unverified_claim_is_gone_once_the_block_is_stated(self):
        deals = _collect({"blocked": [_blocked()]}, rates=[])
        deal = next(deal for deal in deals if deal.resort_name == RESORT)
        self.assertNotIn("TripAdvisor ≥4.5 not verified", " | ".join(deal.highlights))

    def test_a_different_reason_is_stated_in_words(self):
        deals = _collect({"blocked": [_blocked(reason="403 for automated requests")]},
                         rates=[])
        deal = next(deal for deal in deals if deal.resort_name == RESORT)
        self.assertIn("TripAdvisor blocked (403 for automated requests)",
                      " | ".join(deal.highlights))

    def test_without_a_block_the_card_says_it_was_not_verified(self):
        deals = _collect({"blocked": []}, rates=[])
        deal = next(deal for deal in deals if deal.resort_name == RESORT)
        self.assertIn("TripAdvisor ≥4.5 not verified", " | ".join(deal.highlights))

    def test_the_gate_banner_says_the_read_was_attempted_and_blocked(self):
        deals = _collect({"blocked": [_blocked()]}, rates=[])
        config = load_holiday_config(CONFIG)
        html = render_holiday_report(config, generated_at=NOW, deals=deals)
        self.assertIn("blocked", html)
        self.assertIn("DataDome", html)

    def test_the_gate_banner_is_unchanged_without_a_block(self):
        plain = render_gate_not_applied(["Example Resort"])
        blocked = render_gate_not_applied(
            ["Example Resort"], blocked_reasons={"Example Resort": "DataDome challenge"})
        self.assertIn("could not be read", plain)
        self.assertNotIn("could not be read", blocked)


class RatingTests(unittest.TestCase):
    def test_the_rating_is_carried_onto_the_card(self):
        deals = _collect({"ratings": [_rating()]}, rates=[])
        deal = next(deal for deal in deals if deal.resort_name == RESORT)
        self.assertIsNotNone(deal.hotel_ratings)

    def test_the_rating_names_its_source_and_review_count(self):
        deals = _collect({"ratings": [_rating()]}, rates=[])
        deal = next(deal for deal in deals if deal.resort_name == RESORT)
        rating = deal.hotel_ratings[0]
        self.assertEqual(rating.source, "Google")
        self.assertAlmostEqual(rating.score, 4.6)
        self.assertEqual(rating.review_count, "1.2k")
        self.assertTrue(rating.source_url.startswith("https://"))

    def test_a_card_with_no_rating_has_none(self):
        deals = _collect({"ratings": []}, rates=[])
        deal = next(deal for deal in deals if deal.resort_name == RESORT)
        self.assertEqual(tuple(deal.hotel_ratings), ())

    def test_the_report_renders_the_rating_with_its_source(self):
        deals = _collect({"ratings": [_rating()]}, rates=[])
        config = load_holiday_config(CONFIG)
        html = render_holiday_report(config, generated_at=NOW, deals=deals)
        self.assertIn("Google", html)
        self.assertIn("1.2k", html)


if __name__ == "__main__":
    unittest.main()