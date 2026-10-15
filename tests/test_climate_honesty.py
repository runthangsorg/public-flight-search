"""Climate honesty: a monsoon resort can never win the climate award.

Owner brief 2026-10-02: a resort flagged as monsoon season for the travel
month (Khao Lak, on Thailand's Andaman side, in July) must never win
"Best Summer Climate", and its card must carry a visible warning. The climate
award ranks only among in-season resorts.

Owner update 2026-10-15 (20:45 BST): "avoid all monsoon areas, remove from the
hotels and locations". Khao Lak is no longer flagged on a card — it is not in
the July report at all (the committed climate exclusion table drops it), so
these tests now pin the absence, and the honest naming of the seasons that
remain (Riviera Maya's hurricanes, Okinawa's typhoons).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

import public_flight_search.holidays as hol
from public_flight_search import climate
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
    def test_khao_lak_is_an_excluded_area_for_july(self):
        # The Andaman coast is a committed EXCLUSION, not a card warning: a
        # July stay there is dropped before a card can form.
        area = climate.exclusion_for(
            text="Khao Lak", airports=["HKT"], stay_months={7},
        )
        self.assertIsNotNone(area)
        self.assertEqual(area.id, "andaman-coast")
        self.assertIn(7, area.months)

    def test_the_july_report_has_no_khao_lak_card_at_all(self):
        deals = collect_holiday_deals(_july_uncapped())
        self.assertEqual(
            [d for d in deals if d.destination_key == "khao_lak"], [],
            "Khao Lak is a monsoon coast in July and must not be carded",
        )
        self.assertEqual(
            [d for d in deals if d.resort_name == MONSOON_RESORT], [],
        )
        # ...and the Gulf side, which the monsoon does not reach, still is.
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

    def test_no_card_carries_a_monsoon_warning_in_july(self):
        # Every monsoon-coast place the old warning existed for (Khao Lak,
        # Bangkok, the Andaman islands, the Maldives) is excluded outright in
        # months 5-10, so the July report has nothing left to warn about on
        # that heading — while the seasons that are not monsoons still warn.
        config = _july_uncapped()
        html = render_holiday_report(
            config, generated_at="2026-09-30T00:00:00+00:00",
            deals=collect_holiday_deals(config),
        )
        self.assertNotIn("Monsoon season", html)
        self.assertNotIn(MONSOON_RESORT, html)


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
        self.assertNotIn("Monsoon season", html)


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
