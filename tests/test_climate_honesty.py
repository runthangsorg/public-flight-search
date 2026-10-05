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
from types import SimpleNamespace
import unittest

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    FAR_EAST_WATCH,
    SUMMER_RESORT_CATALOG,
    WINTER_RESORT_CATALOG,
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
MONSOON_RESORT = "Pullman Khao Lak Resort"
#: The month names the report itself prints, so a test can name a card's own
#: travel month without pasting it (the July window departs in June).
MONTH_NAMES = ("", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December")
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
        deals = collect_holiday_deals(config)
        monsoon_card = next(d for d in deals if d.resort_name == MONSOON_RESORT)
        html = render_holiday_report(
            config, generated_at="2026-09-30T00:00:00+00:00", deals=deals,
        )
        # The month is the CARD's own, read off its dates rather than pasted:
        # the owner's July window departs 25-30 June 2027, so a July card can
        # leave in June and the warning has to name the month the family
        # actually flies in.
        month = MONTH_NAMES[hol.deal_travel_month(monsoon_card)]
        self.assertIn(
            "Monsoon season (approximate climatology) for your "
            + month + " travel month", html,
        )
        # Not just the destination label: the card header warning is separate.
        self.assertIn("⚠️ Monsoon", html)


class WetSeasonNamingTests(unittest.TestCase):
    """A destination names its OWN wet season; only a monsoon is a monsoon.

    H9 (2026-10-04) added a Caribbean destination whose wet months are the
    Atlantic hurricane season. Calling that a monsoon would tell the reader to
    expect months of rain, which is a different and wrong claim.
    """

    def _deal(self, **kwargs):
        base = dict(
            destination_key="riviera_maya",
            outbound_date="2027-07-10",
            return_date="2027-07-22",
            monsoon_months=(),
        )
        base.update(kwargs)
        return SimpleNamespace(**base)

    def test_a_hurricane_season_is_not_called_a_monsoon(self):
        season, hazard = hol.wet_season_words(self._deal())
        self.assertIn("Hurricane", season)
        self.assertNotIn("Monsoon", season)
        self.assertIn("sargassum", hazard)
        compact = hol.wet_season_words_compact(self._deal())
        self.assertIn("Hurricane season", compact[0])
        self.assertNotIn("Monsoon", compact[0])

    def test_an_asian_destination_still_gets_the_monsoon_wording(self):
        deal = self._deal(destination_key="khao_lak", monsoon_months=(5, 6, 7))
        self.assertEqual(hol.wet_season_words(deal), hol.DEFAULT_WET_SEASON)
        self.assertEqual(
            hol.wet_season_words_compact(deal), hol.DEFAULT_WET_SEASON_COMPACT
        )

    def test_a_resort_with_its_own_months_is_a_monsoon_wherever_it_is(self):
        # A resort's own monsoon_months wins: Khao Lak in Thailand is a real
        # monsoon even though the naming map has no entry for it.
        deal = self._deal(destination_key="khao_lak", monsoon_months=(5, 6, 7, 8, 9, 10))
        self.assertEqual(hol.wet_season_words(deal), hol.DEFAULT_WET_SEASON)

    def test_the_riviera_maya_card_warns_about_storms_not_rains(self):
        # Uncapped: at the July example's own budget this resort is priced out
        # (about GBP 30,000 for 14 nights), and a card that does not exist
        # cannot carry a warning. The warning under test is on the card.
        config = _july_uncapped()
        deals = collect_holiday_deals(config)
        grand_velas = [d for d in deals if d.resort_name == "Grand Velas Riviera Maya"]
        self.assertTrue(grand_velas, "Grand Velas must card for a July Riviera Maya trip")
        html = render_holiday_report(
            config, generated_at="2026-10-04T00:00:00+00:00", deals=deals
        )
        # The Riviera Maya cards warn about the Atlantic hurricane season and
        # the sargassum it brings, never about monsoon rain.
        month = MONTH_NAMES[hol.deal_travel_month(grand_velas[0])]
        self.assertIn(f"Hurricane season for your {month} travel month", html)
        self.assertIn("sargassum", html)
        # Khao Lak on the Andaman side is a real monsoon and still says so.
        self.assertIn(
            "Monsoon season (approximate climatology) for your " + month, html
        )


class WetMonthsCoverageTests(unittest.TestCase):
    """Every catalogue destination declares its wet/storm months (or an
    explicit empty tuple): approximate climatology, never a silent gap."""

    def test_every_catalogue_destination_has_an_explicit_entry(self):
        keys = (
            set(WINTER_RESORT_CATALOG)
            | set(SUMMER_RESORT_CATALOG)
            | set(FAR_EAST_WATCH)
        )
        self.assertTrue(keys)
        for key in sorted(keys):
            with self.subTest(key=key):
                self.assertIn(key, hol.WET_MONTHS_BY_DESTINATION)

    def test_entries_are_valid_month_tuples(self):
        for key, months in hol.WET_MONTHS_BY_DESTINATION.items():
            with self.subTest(key=key):
                self.assertIsInstance(months, tuple)
                self.assertEqual(tuple(sorted(set(months))), months)
                for month in months:
                    self.assertTrue(1 <= month <= 12)

    def test_the_storm_seasons_match_the_owner_list(self):
        expected = {
            "phuket": (5, 6, 7, 8, 9, 10),
            "krabi": (5, 6, 7, 8, 9, 10),
            "khao_lak": (5, 6, 7, 8, 9, 10),
            "koh_samui": (10, 11, 12),
            "koh_phangan": (10, 11, 12),
            "bali": (1, 2, 3, 11, 12),
            "lombok": (1, 2, 3, 11, 12),
            "da_nang": (9, 10, 11, 12),
            "singapore": (1, 11, 12),
            "langkawi": (9, 10, 11),
            "penang": (9, 10, 11),
            "phu_quoc": (5, 6, 7, 8, 9, 10),
            "zanzibar": (4, 5, 11),
            "mauritius": (1, 2, 3),
            "riviera_maya": (6, 7, 8, 9, 10, 11),
            "okinawa": (6, 7, 8, 9),  # typhoon season (H9, 2026-10-04)
        }
        for key, months in expected.items():
            with self.subTest(key=key):
                self.assertEqual(hol.WET_MONTHS_BY_DESTINATION[key], months)

    def test_a_dry_destination_carries_an_explicit_empty_tuple(self):
        self.assertEqual(hol.WET_MONTHS_BY_DESTINATION["tenerife"], ())


if __name__ == "__main__":
    unittest.main()
