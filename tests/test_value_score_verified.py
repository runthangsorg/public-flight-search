"""T11b: a value score computed from default inputs is not a measurement.

Every July card read "value score 35/100" — the same number on all four. The
cause is that none of those resorts is in ``RESORT_CRITERIA``, so every score
input (luxury, food, winter, mosque, activities, flight quality) fell back to a
neutral default and the resulting "score" measured only the price. A number
derived from missing inputs is not a measurement, so it is not shown: such a
card says nothing about its score and lists "value score" as not verified. A
score is shown only where it is computed from real inputs.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holidays import (
    PackageDeal,
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"


def _deal(name: str, score: float, **overrides) -> PackageDeal:
    base = dict(
        resort_name=name,
        destination_label="Test, Thailand",
        destination_key="khao_lak",
        star_rating=5,
        board_basis="Bed & Breakfast",
        outbound_date="2027-07-20",
        return_date="2027-07-27",
        nights=7,
        airline="Test Air",
        origin_airports=("LHR",),
        destination_airport="HKT",
        flight_price_total_gbp=5000.0,
        hotel_price_total_gbp=2000.0,
        total_package_price_gbp=7000.0,
        price_per_person_gbp=1400.0,
        flight_booking_url="https://example.invalid/flight",
        hotel_booking_url="https://example.invalid/hotel",
        is_under_budget=True,
        value_score=score,
        value_score_verified=(name in hol.RESORT_CRITERIA),
        deal_class=hol._classify_deal_price(1400.0),
    )
    base.update(overrides)
    return PackageDeal(**base)


def _config():
    return load_holiday_config(JULY.read_text(encoding="utf-8"))


def _render(*deals):
    return render_holiday_report(
        _config(), generated_at="2026-10-02T00:00:00+00:00", deals=list(deals),
    )


class ValueScoreVerificationTests(unittest.TestCase):
    def setUp(self):
        self._registered = "Test Criteria Resort" not in hol.RESORT_CRITERIA
        if self._registered:
            hol.RESORT_CRITERIA["Test Criteria Resort"] = {
                "luxury": 9, "food": 8, "winter": 7, "mosque": 9,
                "activities": 8, "flight_quality": 9, "indoor": 5,
                "heated_indoor_pool": True, "mosque_name": "Test Mosque",
                "mosque_walk_minutes": 6,
            }
        self._absent = "Test Bare Resort" in hol.RESORT_CRITERIA
        if self._absent:
            del hol.RESORT_CRITERIA["Test Bare Resort"]

    def tearDown(self):
        if self._registered:
            hol.RESORT_CRITERIA.pop("Test Criteria Resort", None)
        if self._absent:
            hol.RESORT_CRITERIA["Test Bare Resort"] = {}

    def test_a_resort_with_no_criteria_shows_no_score(self):
        html = _render(_deal("Test Bare Resort", 35.0))
        self.assertNotIn("value score 35/100", html)
        self.assertNotIn("value score ", html)

    def test_a_resort_with_no_criteria_lists_value_score_as_not_verified(self):
        html = _render(_deal("Test Bare Resort", 35.0))
        self.assertIn("not verified:", html)
        unknown = html.split("not verified:")[1].split("</span>")[0]
        self.assertIn("value score", unknown)

    def test_a_resort_with_criteria_shows_its_computed_score(self):
        html = _render(_deal("Test Criteria Resort", 72.0))
        self.assertIn("value score 72/100", html)
        unknown = html.split("not verified:")[1].split("</span>")[0]
        self.assertNotIn("value score", unknown)

    def test_an_unverified_score_never_wins_the_value_award(self):
        html = _render(_deal("Test Bare Resort", 99.0))
        self.assertNotIn("Best Overall Value", html)

    def test_the_july_example_shows_no_invented_score(self):
        config = _config()
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertFalse(deal.value_score_verified, deal.resort_name)
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00", deals=deals,
        )
        self.assertNotIn("value score ", html)


if __name__ == "__main__":
    unittest.main()