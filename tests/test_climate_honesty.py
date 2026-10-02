"""Climate honesty: a monsoon resort can never win the climate award.

Owner brief 2026-10-02: a resort flagged as monsoon season for the travel
month (Khao Lak, on Thailand's Andaman side, in July) must never win
"Best Summer Climate", and its card must carry a visible warning. The climate
award ranks only among in-season resorts.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import re
import unittest

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    SUMMER_RESORT_CATALOG,
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
MONSOON_RESORT = "Pullman Khao Lak Resort"
UNCAPPED_GBP = 60000.0


def _july_uncapped():
    config = load_holiday_config(JULY.read_text(encoding="utf-8"))
    return dataclasses.replace(config, max_budget_gbp=UNCAPPED_GBP)


def _climate_award(html: str) -> str:
    match = re.search(
        r"Best Summer Climate:</strong> ([^<]+)", html
    )
    if match is None:
        return ""
    return match.group(1)


class MonsoonClimateTests(unittest.TestCase):
    def test_khao_lak_is_flagged_monsoon_for_july(self):
        resort = next(
            r for rs in SUMMER_RESORT_CATALOG.values() for r in rs
            if r["name"] == MONSOON_RESORT
        )
        self.assertIn(7, resort["monsoon_months"])

    def test_monsoon_resort_is_recognised_from_its_deal(self):
        deals = collect_holiday_deals(_july_uncapped())
        khao_lak = next(d for d in deals if d.destination_key == "khao_lak")
        self.assertEqual(khao_lak.resort_name, MONSOON_RESORT)
        self.assertTrue(hol.deal_in_monsoon(khao_lak))
        in_season = next(d for d in deals if d.destination_key == "koh_samui")
        self.assertFalse(hol.deal_in_monsoon(in_season))

    def test_monsoon_resort_never_wins_best_summer_climate(self):
        config = _july_uncapped()
        html = render_holiday_report(
            config, generated_at="2026-09-30T00:00:00+00:00",
            deals=collect_holiday_deals(config),
        )
        self.assertIn("Best Summer Climate", html)
        self.assertNotIn(MONSOON_RESORT, _climate_award(html))
        self.assertTrue(_climate_award(html).strip())

    def test_monsoon_card_header_carries_a_visible_warning(self):
        config = _july_uncapped()
        html = render_holiday_report(
            config, generated_at="2026-09-30T00:00:00+00:00",
            deals=collect_holiday_deals(config),
        )
        self.assertIn("Monsoon season for your July travel month", html)
        # Not just the destination label: the card header warning is separate.
        self.assertIn("⚠️ Monsoon", html)


if __name__ == "__main__":
    unittest.main()
