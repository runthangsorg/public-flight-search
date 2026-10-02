"""T11: the value score must not contradict the award it wins.

The report gave "Best Overall Value" to a card reading "VALUE 35/100 ·
SPLURGE WATCH FOR PRICE DROP" — a "best" that the same line calls a splurge to
avoid. The card now spells the score out in words, and the award is only given
to a card scoring 50 or more; below that, no value award is shown at all.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holidays import (
    PackageDeal,
    VALUE_AWARD_MIN_SCORE,
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
        deal_class=hol._classify_deal_price(1400.0),
    )
    base.update(overrides)
    return PackageDeal(**base)


class ValueScoreWordingTests(unittest.TestCase):
    def _render(self, deal):
        return render_holiday_report(
            _july(), generated_at="2026-10-02T00:00:00+00:00", deals=[deal],
        )

    def test_the_card_spells_the_score_out_in_words(self):
        html = self._render(_deal("Low Scorer", 35.0))
        self.assertIn("value score 35/100", html)
        # Not the SHOUTED acronym, and not a bare number with no meaning.
        self.assertNotIn("SPLURGE WATCH", html)
        self.assertNotIn(">VALUE 35/100<", html)

    def test_a_low_score_reads_as_a_splurge_in_words(self):
        html = self._render(_deal("Low Scorer", 35.0))
        self.assertIn("luxury splurge", html)
        self.assertIn("watch for a price drop", html)

    def test_a_strong_score_reads_as_value_in_words(self):
        html = self._render(_deal("Strong", 85.0))
        self.assertIn("value score 85/100", html)
        self.assertNotIn("SPLURGE WATCH", html)


class ValueAwardThresholdTests(unittest.TestCase):
    def test_the_threshold_is_fifty(self):
        self.assertEqual(VALUE_AWARD_MIN_SCORE, 50.0)

    def test_no_value_award_when_every_card_scores_below_fifty(self):
        config = _july()
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=[_deal("Low One", 35.0), _deal("Low Two", 20.0)],
        )
        self.assertNotIn("Best Overall Value", html)

    def test_the_award_goes_to_a_card_of_fifty_or_more(self):
        config = _july()
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=[_deal("Good One", 60.0), _deal("Low One", 35.0)],
        )
        self.assertIn("Best Overall Value", html)
        self.assertIn("Good One", html)

    def test_a_card_scoring_exactly_fifty_still_wins(self):
        config = _july()
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=[_deal("Exactly Fifty", 50.0)],
        )
        self.assertIn("Best Overall Value", html)

    def test_the_rendered_july_report_never_awards_a_splurge(self):
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        deals = collect_holiday_deals(config)
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00", deals=deals,
        )
        if "Best Overall Value" in html:
            best = hol.bucket_deals(deals)["value"][0]
            self.assertGreaterEqual(
                best.value_score, VALUE_AWARD_MIN_SCORE,
                "a value award was given to a card below the threshold",
            )


def _july():
    return load_holiday_config(JULY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
