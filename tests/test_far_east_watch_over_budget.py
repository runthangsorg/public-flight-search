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
import math
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

#: The banner the renderer prints once when it collapses watch rows into single
#: lines. Named here so the "nothing collapsed" assertions test the BANNER'S
#: ABSENCE directly, which is the only form of the check that can fail
#: (REVIEW-H9 P2-3).
_COLLAPSE_BANNER = "Too far over budget to show as a card"


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
        self.assertIn(_COLLAPSE_BANNER, html)
        # A compact line, not the full card prose.
        self.assertIn("gap to budget", html)
        self.assertNotIn("pp Economy + suite", html)

    def test_a_watch_row_near_the_budget_keeps_its_full_card(self):
        config = _july(200000.0)  # nothing is over budget
        html = render_far_east_watch(config)
        self.assertNotIn(_COLLAPSE_BANNER, html)
        self.assertIn("pp Economy + suite", html)

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
        # At the committed £12,000 no July watch row is over the 25% limit
        # (H9), so the check runs against a ceiling that does collapse one.
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")), max_budget_gbp=10000.0
        )
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=collect_holiday_deals(config),
        )
        self.assertIn("Far East first", html)
        # The collapse is announced once, and every collapsed destination has
        # exactly one compact line — none is also rendered as a full card.
        self.assertEqual(html.count(_COLLAPSE_BANNER), 1)
        collapsed_rows = [
            row for row in far_east_watch_rows(config)
            if _is_collapsed(row, config.max_budget_gbp)
        ]
        self.assertEqual(html.count("gap to budget"), len(collapsed_rows))
        # Both July watch rows are over the 25% limit at this ceiling. Asserted
        # against the rows rather than a literal, because the count moves with
        # the headline pair's nights and the owner's window changed on
        # 2026-10-04 (see the class docstring and
        # test_at_the_july_budget_the_dearer_watch_row_collapses).
        self.assertEqual(
            {row["key"] for row in collapsed_rows}, {"bali", "da_nang"}
        )


class CheapestOptionCollapseTests(unittest.TestCase):
    """T12b: the collapse is judged on the CHEAPEST option.

    The owner's rule tests the budget on EACH option, so a watch row that fits
    on Economy is not out of reach. Judging only the Business benchmark
    collapsed Bali and Da Nang, which both fit inside a ceiling that leaves
    their Economy option covered; a row whose cheapest option is over 25% past
    the same ceiling still collapses. (Tokyo left the July config in H9, so the
    row that collapses under a tight ceiling there is Bali.)
    """

    def _cheapest_option(self, row) -> float:
        return _cheapest_option(row)

    def test_a_watch_row_that_fits_on_economy_keeps_its_full_card(self):
        # The ceiling is derived from the rows, not pasted: a watch row is
        # priced for the nights of the report's headline pair, and the owner's
        # July window moved to 12-21 nights, so the figures this test used to
        # quote belonged to a shorter stay. The rule under test is "a row that
        # fits on the cheapest option keeps its card".
        rows = {r["key"]: r for r in far_east_watch_rows(_july(12000.0))}
        bali, da_nang = rows["bali"], rows["da_nang"]
        # Bali and Da Nang both fit on Economy under this ceiling...
        budget = float(math.ceil(max(
            float(bali["economy_total_gbp"]),
            float(da_nang["economy_total_gbp"]),
        )))
        config = _july(budget)
        rows = {r["key"]: r for r in far_east_watch_rows(config)}
        for key in ("bali", "da_nang"):
            with self.subTest(destination=key):
                self.assertLessEqual(_cheapest_option(rows[key]), budget)
        html = render_far_east_watch(config)
        self.assertIn("pp Economy + suite", html)
        # Neither is collapsed, asserted as the ABSENCE of the banner itself
        # rather than as `assertNotIn` against a split of the html. The old form
        # defaulted the split to "" when the banner was missing, so
        # `assertNotIn("Bali", "")` passed for the wrong reason and the check
        # could never fail (REVIEW-H9 P2-3).
        self.assertNotIn(
            _COLLAPSE_BANNER, html,
            "a row that fits on its cheapest option must keep its full card",
        )
        self.assertNotIn("gap to budget", html)
        self.assertIn("Bali, Indonesia", html)
        self.assertIn("Da Nang &amp; Hoi An", html)

    def test_a_watch_row_over_on_every_option_still_collapses(self):
        # £10,000 puts Bali over on every cabin (£14,100 cheapest) and past the
        # 25% collapse limit of £12,500, so it must collapse rather than sit as
        # a full card.
        config = _july(10000.0)
        rows = {r["key"]: r for r in far_east_watch_rows(config)}
        bali = _cheapest_option(rows["bali"])
        self.assertGreater(bali, 10000.0 * (1.0 + FAR_EAST_WATCH_COLLAPSE_RATIO))
        html = render_far_east_watch(config)
        collapsed_block = html.split(_COLLAPSE_BANNER)[1]
        self.assertIn("Bali", collapsed_block)

    def test_every_row_over_the_limit_collapses_and_no_other_does(self):
        # Counted from the rows rather than pasted: which July watch rows
        # collapse depends on the nights of the headline pair, and the owner's
        # window moved to a 17-night headline on 2026-10-04 (it was 14), so a
        # literal count here would be a claim about a window, not about the
        # rule.
        config = _july(10000.0)
        html = render_far_east_watch(config)
        collapsed = [
            row for row in far_east_watch_rows(config)
            if _is_collapsed(row, config.max_budget_gbp)
        ]
        self.assertEqual(html.count(_COLLAPSE_BANNER), 1)
        self.assertEqual(html.count("gap to budget"), len(collapsed))
        self.assertEqual({row["key"] for row in collapsed}, {"bali", "da_nang"})

    def test_at_the_july_budget_the_dearer_watch_row_collapses(self):
        # The committed July example budgets GBP 12,000, and the owner's window
        # moved on 2026-10-04 to depart 25-30 June, which makes the HEADLINE
        # pair 17 nights (it was 14). Both watch rows are priced for that pair,
        # so their suite cost rose: Bali's cheapest option is now past the 25%
        # collapse limit there and Da Nang's is not.
        #
        # So at the July budget the Bali watch is ONE COMPACT LINE, not a card.
        # That is the rule working (an unverified benchmark the family cannot
        # afford is not worth a card), and it is a change from H9, which had a
        # 14-night headline pair and collapsed nothing at this budget.
        config = _july(12000.0)
        html = render_far_east_watch(config)
        rows = {row["key"]: row for row in far_east_watch_rows(config)}
        limit = config.max_budget_gbp * (1.0 + FAR_EAST_WATCH_COLLAPSE_RATIO)
        self.assertGreater(_cheapest_option(rows["bali"]), limit)
        self.assertLessEqual(_cheapest_option(rows["da_nang"]), limit)
        self.assertEqual(html.count(_COLLAPSE_BANNER), 1)
        collapsed_block = html.split(_COLLAPSE_BANNER)[1]
        self.assertIn("Bali", collapsed_block)
        self.assertNotIn("Da Nang", collapsed_block)
        # Da Nang still earns its full card, headed at its own cabin.
        self.assertIn("pp Economy + suite", html)


if __name__ == "__main__":
    unittest.main()
