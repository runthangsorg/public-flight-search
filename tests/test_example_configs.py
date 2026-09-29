"""Shipped example configs must never produce a silent report.

Regression guard for the 2026-09-21 silence: commit 7bb26c5 flipped the
December example to cabin_classes [BUSINESS, PREMIUM_ECONOMY] only. The
2.5x Business flight multiplier pushed every resort past the GBP 5,000
budget, collect_holiday_deals() returned zero deals, the anti-spam digest
had nothing to report, and the scheduled planner emailed nothing for days
while every GHA run stayed green. A config that yields no deals is a
pipeline outage, not a quiet market — this test fails loudly instead.
"""

from pathlib import Path
import unittest

from public_flight_search.holidays import load_holiday_config, collect_holiday_deals

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class ExampleConfigDealFunnelTests(unittest.TestCase):
    def test_december_example_yields_deals(self):
        path = EXAMPLES / "dec_holiday_config.json"
        config = load_holiday_config(path.read_text(encoding="utf-8"))
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
        self.assertGreater(
            len(deals),
            0,
            f"{path.name} produces zero deals: every destination/cabin "
            "combination failed the budget gate, which silently "
            "suppresses all scheduled emails",
        )

    def test_july_example_is_never_silent(self):
        """The July example is long-haul Business for five since 2026-09-29.

        Under the public example's budget it may card nothing: the live run
        prices the private secret's budget instead. What must never happen is
        the 2026-09-21 failure mode, a report that says nothing. So every
        catalogue-backed July destination is either a card or a row of the
        over-budget list, and the rendered report shows that list.

        Known limit, stated rather than hidden: a config with ZERO cards
        still emails only on a first run or a forced send. The change digest
        is built from cards, so with no cards there is nothing to move, and a
        scheduled run stays quiet. The live secret must therefore price at
        least one card for scheduled July emails to flow.
        """
        from public_flight_search import holidays as hol

        config = load_holiday_config(
            (EXAMPLES / "july_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
        carded = {d.destination_key for d in deals}
        over = {row["destination_key"] for row in hol.LAST_OVER_BUDGET}
        backed = {
            d.key for d in config.destinations
            if hol.resort_catalog(config).get(d.key)
        }
        self.assertTrue(backed, "the July example has no catalogue-backed destination")
        self.assertEqual(backed, carded | over, "a July destination vanished from the report")
        html = hol.render_holiday_report(
            config, generated_at="2026-09-29T00:00:00+00:00", deals=deals
        )
        if over:
            self.assertIn("Long-haul resorts priced over", html)
        if deals:
            self.assertIn("One Family Unit", html)

    def test_dec_example_includes_economy_floor(self):
        # The December watch is the every-run digest: it must keep an Economy
        # floor so at least one cabin is affordable at the GBP 5k ceiling.
        config = load_holiday_config(
            (EXAMPLES / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        cabins = {c.upper() for c in config.cabin_classes}
        self.assertIn("ECONOMY", cabins)


if __name__ == "__main__":
    unittest.main()
