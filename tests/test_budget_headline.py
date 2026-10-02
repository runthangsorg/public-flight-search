"""T12c: the budget line leads with the option that FITS.

The owner's rule tests the budget on EACH option, so a card must never headline
the Business gap alone. A Bali watch row at £12,000 said only "£10,650 over the
£12,000 budget" — the Business figure — while its Economy option (£10,950) fits.
The same applied to a long-haul resort card whose headline price is Business while
the card itself exists because an Economy option fits.

The budget line now leads with the cheapest option that fits, naming its cabin
and total, and only then states the cabins that do not fit and by how much.
"""

from __future__ import annotations

import dataclasses
from html import escape
from pathlib import Path
import unittest

from public_flight_search.holidays import (
    budget_headline,
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


def _watch_line(html: str, label: str) -> str:
    """The one watch-card line for a destination label."""
    rows = [chunk for chunk in html.split("<tr><td") if escape(label) in chunk]
    assert rows, f"no watch card for {label!r}"
    return rows[0]


class BudgetHeadlineHelperTests(unittest.TestCase):
    """The shared helper both card types use."""

    def test_it_leads_with_the_cheapest_option_that_fits(self):
        html = budget_headline(
            [("Business", 22650.0, False), ("Premium Economy", 15630.0, False),
             ("Economy", 10950.0, True)],
            12000.0,
        )
        self.assertIn("fits the £12,000 budget on Economy (about £10,950)", html)
        self.assertLess(html.index("fits the"), html.index("over"))
        self.assertIn("Business £10,650 over", html)
        self.assertIn("Premium Economy £3,630 over", html)

    def test_a_row_over_on_every_option_says_only_that_it_is_over(self):
        html = budget_headline(
            [("Business", 30900.0, False), ("Economy", 15300.0, False)],
            12500.0,
        )
        self.assertNotIn("fits the", html)
        self.assertIn("over the £12,500 budget", html)
        self.assertIn("Economy £2,800 over", html)

    def test_nothing_is_said_without_options_or_without_a_budget(self):
        self.assertEqual(budget_headline([], 12000.0), "")
        self.assertEqual(budget_headline([("Economy", 10950.0, True)], 0.0), "")

    def test_nothing_is_said_when_every_option_fits(self):
        self.assertEqual(
            budget_headline([("Business", 9000.0, True), ("Economy", 4000.0, True)], 12000.0),
            "",
        )


class FarEastWatchBudgetLineTests(unittest.TestCase):
    def test_a_watch_row_that_fits_on_economy_says_so_first(self):
        config = _july(12000.0)
        bali = {r["key"]: r for r in far_east_watch_rows(config)}["bali"]
        line = _watch_line(render_far_east_watch(config), bali["label"])
        self.assertIn("fits the £12,000 budget on Economy (about £10,950)", line)
        # The Business gap is still stated, after the option that fits.
        self.assertIn("Business £10,650 over", line)
        self.assertLess(line.index("fits the"), line.index("Business £10,650 over"))

    def test_a_watch_row_over_on_every_option_keeps_the_over_wording(self):
        # £12,500 keeps Tokyo a full card (its cheapest option is £15,300, under
        # the 25% collapse limit of £15,625) while it is over on EVERY cabin.
        config = _july(12500.0)
        tokyo = {r["key"]: r for r in far_east_watch_rows(config)}["japan"]
        line = _watch_line(render_far_east_watch(config), tokyo["label"])
        self.assertNotIn("fits the", line)
        self.assertIn("over the £12,500 budget", line)

    def test_a_watch_row_within_budget_on_every_cabin_says_nothing_about_budget(self):
        config = _july(200000.0)
        bali = {r["key"]: r for r in far_east_watch_rows(config)}["bali"]
        line = _watch_line(render_far_east_watch(config), bali["label"])
        self.assertNotIn("budget", line)


class ResortCardBudgetLineTests(unittest.TestCase):
    """A long-haul card's headline price is Business; its budget line is not."""

    def test_a_resort_card_whose_economy_option_fits_says_so(self):
        config = _july(12000.0)
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00", deals=deals,
        )
        checked = 0
        for deal in deals:
            options = {
                str(o["kind"]): o for o in deal.flight_options
                if o["kind"] in ("business", "economy", "premium_economy")
            }
            if not options or all(o["within_budget"] for o in options.values()):
                continue
            checked += 1
            line = html[html.index(escape(deal.resort_name)):]
            economy = options["economy"]
            business = options["business"]
            self.assertIn(
                "fits the £12,000 budget on Economy (about £"
                + f'{float(economy["true_d2d"]):,.0f}' + ")",
                line,
            )
            if not business["within_budget"]:
                self.assertIn(
                    "Business £" + f'{float(business["true_d2d"]) - 12000.0:,.0f}' + " over",
                    line,
                )
        self.assertGreater(checked, 0, "no July card mixes a fitting and a breaching cabin")


if __name__ == "__main__":
    unittest.main()