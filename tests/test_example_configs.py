"""Shipped example configs must always produce deals.

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
    def test_every_example_config_yields_deals(self):
        for path in sorted(EXAMPLES.glob("*_holiday_config.json")):
            with self.subTest(config=path.name):
                config = load_holiday_config(path.read_text(encoding="utf-8"))
                deals = collect_holiday_deals(
                    config, max_budget_gbp=config.max_budget_gbp
                )
                self.assertGreater(
                    len(deals),
                    0,
                    f"{path.name} produces zero deals: every destination/cabin "
                    "combination failed the budget gate, which silently "
                    "suppresses all scheduled emails",
                )

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
