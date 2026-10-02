"""No invented savings: a benchmark comparison is not a saving.

Owner brief 2026-10-02: "save £3,046" and "▼18% vs summer peak · save £3,046"
compare the card against our own benchmark estimate, not a real earlier price.
That must read "£3,046 below our benchmark estimate (not a saving)". The word
"save" is earned only when the comparison is an observed earlier price for the
same resort and dates, from history.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import unittest

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
DEC = ROOT / "examples" / "dec_holiday_config.json"


class _BenchmarkDeal:
    """A deal whose peak comparison is a benchmark (default)."""

    peak_summer_total_gbp = 6860.0
    total_package_price_gbp = 3985.0

    vs_peak_saving_gbp = hol.PackageDeal.vs_peak_saving_gbp
    vs_peak_pct = hol.PackageDeal.vs_peak_pct


class _ObservedDeal(_BenchmarkDeal):
    peak_observed = True


def _dec_report():
    config = load_holiday_config(DEC.read_text(encoding="utf-8"))
    deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
    return deals, render_holiday_report(
        config, generated_at="2026-10-02T00:00:00+00:00", deals=deals
    )


class BenchmarkNotSavingTests(unittest.TestCase):
    def test_badge_calls_a_benchmark_comparison_not_a_saving(self):
        badge = hol.peak_discount_badge(_BenchmarkDeal())
        self.assertNotIn("save £", badge)
        self.assertIn("below our benchmark estimate (not a saving)", badge)
        # A neutral chip, not the green "saving" treatment.
        self.assertNotIn("#16a34a", badge)

    def test_badge_may_say_save_only_for_an_observed_earlier_price(self):
        badge = hol.peak_discount_badge(_ObservedDeal())
        self.assertIn("save £2,875", badge)
        self.assertIn("#16a34a", badge)

    def test_all_deals_default_to_a_benchmark_comparison(self):
        deals, _ = _dec_report()
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertFalse(deal.peak_observed)

    def test_rendered_report_never_says_save_for_a_benchmark(self):
        _, html = _dec_report()
        self.assertNotIn("save £", html)
        self.assertIn("below our benchmark estimate (not a saving)", html)
        # The facts strip must not call a benchmark a "saving" either.
        self.assertNotIn("benchmark saving", html)

    def test_award_headline_does_not_sell_a_benchmark_as_a_discount(self):
        _, html = _dec_report()
        self.assertIn("Furthest below our benchmark estimate", html)
        self.assertNotIn("Biggest Discount", html)

    def test_award_headline_keeps_discount_only_for_an_observed_price(self):
        config = load_holiday_config(DEC.read_text(encoding="utf-8"))
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        observed = [dataclasses.replace(deals[0], peak_observed=True)]
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00", deals=observed
        )
        self.assertIn("Biggest Discount vs Summer Peak", html)
        self.assertNotIn("Furthest below our benchmark estimate", html)


if __name__ == "__main__":
    unittest.main()
