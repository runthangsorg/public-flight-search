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
import math
from pathlib import Path
import unittest

from public_flight_search.holidays import (
    HolidayConfig,
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
    def _fitting_budget(self, key: str) -> tuple[HolidayConfig, float, float]:
        """The July config at a ceiling this watch row's Economy option fits.

        The ceiling and both totals are taken from the row rather than pasted:
        the stay is priced for the nights of the report's headline pair, and
        the owner's July window moved twice in a day (7 nights, then 12-21), so
        a pasted figure here only described one of them. What is under test is
        the LINE, not the price: lead with the cheapest option that fits, then
        state the gaps.
        """
        rows = {r["key"]: r for r in far_east_watch_rows(_july(12000.0))}
        row = rows[key]
        economy = float(row["economy_total_gbp"])
        business = float(row["indicative_total_gbp"])
        budget = float(math.ceil(economy))
        self.assertGreater(budget, 0.0, "the row has no Economy price to fit under")
        self.assertGreater(
            business, budget, "the premise needs a Business option over this ceiling"
        )
        return _july(budget), economy, business

    def test_a_watch_row_that_fits_on_economy_says_so_first(self):
        config, economy, business = self._fitting_budget("bali")
        budget = config.max_budget_gbp
        bali = {r["key"]: r for r in far_east_watch_rows(config)}["bali"]
        line = _watch_line(render_far_east_watch(config), bali["label"])
        self.assertIn(
            f"fits the £{budget:,.0f} budget on Economy (about £{economy:,.0f})", line
        )
        # The Business gap is still stated, after the option that fits. (The
        # anchor is the gap, not the bare word "Business": the row also names
        # the cabin in its flight line.)
        gap = f"Business £{business - budget:,.0f} over"
        self.assertIn(gap, line)
        self.assertLess(line.index("fits the"), line.index(gap))

    def test_a_watch_row_over_on_every_option_keeps_the_over_wording(self):
        # The budget here is synthetic — never the owner's, which is not
        # committed to this PUBLIC repo. At that ceiling Bali still holds a full
        # card (its cheapest option stays under the watch collapse limit,
        # budget * (1 + FAR_EAST_WATCH_COLLAPSE_RATIO)) while it is over on
        # EVERY cabin.
        budget = 12000.0
        config = _july(budget)
        bali = {r["key"]: r for r in far_east_watch_rows(config)}["bali"]
        line = _watch_line(render_far_east_watch(config), bali["label"])
        self.assertNotIn("fits the", line)
        self.assertIn(f"over the £{budget:,.0f} budget", line)

    def test_a_watch_row_within_budget_on_every_cabin_says_nothing_about_budget(self):
        config = _july(200000.0)
        bali = {r["key"]: r for r in far_east_watch_rows(config)}["bali"]
        line = _watch_line(render_far_east_watch(config), bali["label"])
        self.assertNotIn("budget", line)


class ResortCardBudgetLineTests(unittest.TestCase):
    """A long-haul card's headline price is Business; its budget line is not."""

    def test_a_resort_card_whose_economy_option_fits_says_so(self):
        # The December Riviera Maya card: the one route the owner still quotes
        # Business on (a nonstop, 18 Oct 2026 - 11 Apr 2027), so it is the only
        # card left where "the headline is over but Economy fits" is a question
        # with two answers. Since 2026-10-04 a July card has no Business row at
        # all, so this cannot be asked of one.
        root = Path(__file__).parents[1]
        base = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8"))
        # The ceiling is DERIVED from the cards, not pasted: it has to sit
        # between a card's Economy and Business totals for either to breach,
        # and those totals move with the window, the rates and the party.
        uncapped = dataclasses.replace(base, max_budget_gbp=60000.0)
        cards = [
            deal for deal in collect_holiday_deals(uncapped, max_budget_gbp=60000.0)
            if any(o["kind"] == "business" for o in deal.flight_options)
        ]
        self.assertTrue(cards, "no December business card")
        widest = max(
            float(o["economy"]["true_d2d"]) + float(o["business"]["true_d2d"])
            for card in cards
            for o in [{k: v for k, v in (
                (x["kind"], x) for x in card.flight_options if x.get("hub") is None)}]
            if {"business", "economy"} <= set(o)
        )
        ceiling = round(widest / 2.0, 2)
        config = dataclasses.replace(base, max_budget_gbp=ceiling)
        deals = collect_holiday_deals(config, max_budget_gbp=ceiling)
        business_cards = [
            deal for deal in deals
            if any(o["kind"] == "business" for o in deal.flight_options)
        ]
        checked = 0
        for deal in business_cards:
            options = {
                str(o["kind"]): o for o in deal.flight_options
                if o["kind"] in ("business", "economy")
            }
            if not options or all(o["within_budget"] for o in options.values()):
                continue
            checked += 1
            economy, business = options["economy"], options["business"]
            self.assertFalse(business["within_budget"])
            self.assertTrue(economy["within_budget"])
            # ``budget_headline`` is the shared helper both card types render,
            # so the rule is asserted on it directly rather than through a
            # page layout that also has to fit the report's byte budget.
            line = budget_headline(
                [
                    ("Business", float(business["true_d2d"]), bool(business["within_budget"])),
                    ("Economy", float(economy["true_d2d"]), bool(economy["within_budget"])),
                ],
                ceiling,
            )
            self.assertIn(
                f"fits the £{ceiling:,.0f} budget on Economy (about £"
                + f'{float(economy["true_d2d"]):,.0f}' + ")",
                line,
            )
            self.assertIn(
                "Business £" + f'{float(business["true_d2d"]) - ceiling:,.0f}' + " over",
                line,
            )
        self.assertGreater(
            checked, 0, "no December business card mixes a fitting and a breaching cabin"
        )


if __name__ == "__main__":
    unittest.main()