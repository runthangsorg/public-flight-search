"""T12: a benchmark-only watch destination far over budget is not a card.

The "Far East first" block rendered Bali, Da Nang and Tokyo as full cards even
when the benchmark sat up to £18,900 over the owner's budget. A watch row is not
a bookable deal — it is an unverified estimate — so a row more than 25% over
budget now collapses into ONE compact table line (destination, flight hours,
benchmark total, gap to budget, links) and the rest keep their full cards.
"""

from __future__ import annotations

import dataclasses
from html import escape
from pathlib import Path
import unittest

from public_flight_search.holidays import (
    FAR_EAST_WATCH_COLLAPSE_RATIO,
    collect_holiday_deals,
    far_east_watch_rows,
    load_holiday_config,
    render_far_east_watch,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"


def _july(budget: float):
    return dataclasses.replace(
        load_holiday_config(JULY.read_text(encoding="utf-8")), max_budget_gbp=budget,
    )


def _cheapest_option(row) -> float:
    """The cheapest cabin a watch row offers — what the collapse is judged on."""
    return min(
        float(row[key])
        for key in ("indicative_total_gbp", "economy_total_gbp", "premium_economy_total_gbp")
        if row.get(key) is not None
    )


def _is_collapsed(row, budget: float) -> bool:
    return bool(row["in_season"]) and _cheapest_option(row) > budget * (
        1.0 + FAR_EAST_WATCH_COLLAPSE_RATIO
    )


class FarEastCollapseTests(unittest.TestCase):
    def test_the_collapse_threshold_is_a_quarter_over_budget(self):
        self.assertEqual(FAR_EAST_WATCH_COLLAPSE_RATIO, 0.25)

    def test_a_watch_row_well_over_budget_is_collapsed(self):
        # £5,000: no watch row fits on ANY cabin, so all of them collapse.
        config = _july(5000.0)
        html = render_far_east_watch(config)
        self.assertIn("Too far over budget to show as a card", html)
        # A compact line, not the full card prose.
        self.assertIn("gap to budget", html)
        self.assertNotIn("pp Business + suite", html)

    def test_a_watch_row_near_the_budget_keeps_its_full_card(self):
        config = _july(200000.0)  # nothing is over budget
        html = render_far_east_watch(config)
        self.assertNotIn("Too far over budget to show as a card", html)
        self.assertIn("pp Business + suite", html)

    def test_every_collapsed_row_keeps_its_links(self):
        config = _july(12000.0)
        html = render_far_east_watch(config)
        rows = far_east_watch_rows(config)
        for row in rows:
            with self.subTest(dest=row["key"]):
                self.assertIn(escape(row["label"]), html)
        self.assertIn("Google Flights", html)
        self.assertIn("Booking.com", html)
        self.assertIn("Google Hotels", html)

    def test_a_collapsed_row_states_its_benchmark_and_its_gap(self):
        config = _july(12000.0)
        rows = {r["key"]: r for r in far_east_watch_rows(config)}
        html = render_far_east_watch(config)
        bali = rows["bali"]
        self.assertIn(f'{bali["indicative_total_gbp"]:,.0f}', html)
        self.assertIn("over the £", html)

    def test_the_real_july_report_collapses_its_over_budget_watch_rows(self):
        # The example config's own budget: the watch rows that are wildly over
        # must be compact, and the report must still render its hotel cards.
        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=collect_holiday_deals(config),
        )
        self.assertIn("Far East first", html)
        # The collapse is announced once, and every collapsed destination has
        # exactly one compact line — none is also rendered as a full card.
        self.assertEqual(html.count("Too far over budget to show as a card"), 1)
        collapsed_rows = [
            row for row in far_east_watch_rows(config)
            if _is_collapsed(row, config.max_budget_gbp)
        ]
        self.assertEqual(html.count("gap to budget"), len(collapsed_rows))


class CheapestOptionCollapseTests(unittest.TestCase):
    """T12b: the collapse is judged on the CHEAPEST option.

    The owner's rule tests the budget on EACH option, so a watch row that fits
    on Economy is not out of reach. Judging only the Business benchmark
    collapsed Bali (Economy ~£10,950) and Da Nang (Economy ~£9,050), which both
    fit inside £12,000; Tokyo (Economy ~£15,300, 27% over) still collapses.
    """

    def _cheapest_option(self, row) -> float:
        return _cheapest_option(row)

    def test_a_watch_row_that_fits_on_economy_keeps_its_full_card(self):
        config = _july(12000.0)
        rows = {r["key"]: r for r in far_east_watch_rows(config)}
        # Bali and Da Nang both fit on Economy under £12,000.
        self.assertLessEqual(_cheapest_option(rows["bali"]), 12000.0)
        self.assertLessEqual(_cheapest_option(rows["da_nang"]), 12000.0)
        html = render_far_east_watch(config)
        self.assertIn("pp Business + suite", html)
        collapsed_block = html.split("Too far over budget to show as a card")[1]
        self.assertNotIn("Bali, Indonesia", collapsed_block)
        self.assertNotIn("Da Nang &amp; Hoi An", collapsed_block)

    def test_a_watch_row_over_on_every_option_still_collapses(self):
        config = _july(12000.0)
        rows = {r["key"]: r for r in far_east_watch_rows(config)}
        tokyo = _cheapest_option(rows["japan"])
        self.assertGreater(tokyo, 12000.0 * (1.0 + FAR_EAST_WATCH_COLLAPSE_RATIO))
        html = render_far_east_watch(config)
        collapsed_block = html.split("Too far over budget to show as a card")[1]
        self.assertIn("Tokyo &amp; Hakone", collapsed_block)

    def test_only_tokyo_collapses_in_the_july_example(self):
        config = _july(12000.0)
        html = render_far_east_watch(config)
        self.assertEqual(html.count("Too far over budget to show as a card"), 1)
        self.assertEqual(html.count("gap to budget"), 1)


if __name__ == "__main__":
    unittest.main()
