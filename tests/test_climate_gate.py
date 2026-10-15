"""The climate gate: monsoon areas are REMOVED, never merely flagged.

Owner direction 2026-10-15, 20:45 BST: "avoid all monsoon areas, remove from
the hotels and locations". The committed table
(``data/climate_exclusions.json``) says which places are off-limits in which
months, and one gate is applied everywhere the report picks a place to STAY:
the config's own destinations (including a live secret config), the catalogue
resorts, the two-centre stops and the watch list. A **connection** through an
excluded airport — a leg with no nights, HKT→BKK→USM — is not a stay and is
allowed. A **warning** area (Japan's tsuyu) never removes anything: the stay
survives with a ⚠ line.

Every fixture here is synthetic: the shipped July config and the committed
table are the real data under test; no budget, party address, name or path
from the owner's setup appears anywhere.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import public_flight_search.holiday_email as holiday_email
import public_flight_search.holidays as hol
from public_flight_search import climate
from public_flight_search.holiday_email import (
    _multi_centre_rows,
    render_holiday_report_compact,
    warning_lines,
)
from public_flight_search.holidays import (
    collect_holiday_deals,
    far_east_watch_rows,
    load_holiday_config,
    stopover_legs,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
UNCAPPED_GBP = 60000.0
NOW = "2026-10-15T21:00:00+00:00"

#: What a secret config that still lists HKT would look like — the gate must
#: work on whatever the config says, including the JULY_HOLIDAY_SEARCH_CONFIG_
#: JSON secret no test can read.
STILL_LISTS_KHAO_LAK = """
{
  "report_title": "A config the gate has not seen",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 6,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "khao_lak", "label": "Khao Lak, Thailand (Andaman side)",
     "airports": ["HKT"], "flight_hours": 14.5}
  ]
}
"""

#: A December trip to Phuket: outside months 5-10, so the Andaman exclusion
#: does not touch it.
DECEMBER_PHUKET = """
{
  "report_title": "Phuket in December",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 6,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-17"],
  "return_dates": ["2026-12-27"],
  "destinations": [
    {"key": "phuket", "label": "Phuket, Thailand", "airports": ["HKT"],
     "flight_hours": 13.5}
  ]
}
"""


def _july_uncapped():
    config = load_holiday_config(JULY.read_text(encoding="utf-8"))
    return dataclasses.replace(config, max_budget_gbp=UNCAPPED_GBP)


def _excluded_names() -> list[str]:
    return [str(row.get("name", "")) for row in hol.LAST_CLIMATE_EXCLUDED]


class GateRemovesTheStayTests(unittest.TestCase):
    """The shipped config is clean, and a config that is not still fails."""

    def test_the_shipped_july_config_names_no_excluded_place(self):
        config = _july_uncapped()
        html = render_holiday_report_compact(
            config, generated_at=NOW, deals=collect_holiday_deals(config),
        )
        self.assertNotIn("Khao Lak", html)
        self.assertNotIn("Bangkok", html)
        self.assertNotIn("Left out for the monsoon", html)

    def test_a_secret_config_that_still_lists_hkt_is_still_gated(self):
        config = load_holiday_config(STILL_LISTS_KHAO_LAK)
        deals = collect_holiday_deals(config)
        self.assertEqual([d.resort_name for d in deals], [])
        self.assertIn("Khao Lak", _excluded_names())

    def test_the_glance_table_and_the_watch_list_lose_it_too(self):
        config = load_holiday_config(STILL_LISTS_KHAO_LAK)
        html = render_holiday_report_compact(
            config, generated_at=NOW, deals=collect_holiday_deals(config),
        )
        self.assertNotIn("Pullman", html)
        self.assertNotIn("On the watch list", html)

    def test_the_notes_line_names_what_was_left_out(self):
        config = load_holiday_config(STILL_LISTS_KHAO_LAK)
        html = render_holiday_report_compact(
            config, generated_at=NOW, deals=collect_holiday_deals(config),
        )
        self.assertIn(
            "Left out for the monsoon: Khao Lak "
            "(dates fall in their rainy season).",
            html,
        )

    def test_the_two_centre_block_loses_a_trip_with_a_monsoon_stop(self):
        # MC-02 (Khao Lak + Koh Phangan) was deleted from the committed file,
        # so the gate's own work is proven on a trip built here instead.
        trips = [
            SimpleNamespace(
                id="TEST-01", title="Khao Lak 7 nights + Koh Phangan 7 nights",
                stops=(
                    SimpleNamespace(place="Khao Lak, Phuket province",
                                    airport="HKT", nights=7),
                    SimpleNamespace(place="Koh Phangan (Nathon)",
                                    airport="USM", nights=7),
                ),
                total_nights=14, cost_low_gbp=11757, cost_high_gbp=15607,
                fits=lambda budget: True, price_label=lambda: "cost range",
                why="test", catch="test", legs=(("LHR", "HKT"), ("HKT", "BKK"),
                                               ("BKK", "USM"), ("USM", "LHR")),
            ),
        ]
        saved = holiday_email.load_multi_centre
        holiday_email.load_multi_centre = lambda config: tuple(trips)
        try:
            config = _july_uncapped()
            rows = _multi_centre_rows(config)
        finally:
            holiday_email.load_multi_centre = saved
        self.assertEqual([r["trip"].id for r in rows], [])
        self.assertIn("Khao Lak", _excluded_names())


class ConnectionIsNotAStayTests(unittest.TestCase):
    """A leg with no nights is not a stay (HKT→BKK→USM must survive)."""

    def test_an_excluded_airport_with_no_nights_is_not_excluded(self):
        area = climate.exclusion_for(
            text="", airports=["HKT"], stay_months=set(),
        )
        self.assertIsNone(area)

    def test_the_same_airport_with_nights_is_excluded(self):
        area = climate.exclusion_for(
            text="", airports=["HKT"], stay_months={7},
        )
        self.assertIsNotNone(area)

    def test_the_stopover_legs_through_an_excluded_hub_are_untouched(self):
        legs = stopover_legs("DOH", "HKT", "2027-06-26", "2027-07-10")
        self.assertEqual(
            legs,
            (
                ("LHR", "DOH", "2027-06-26"),
                ("DOH", "HKT", "2027-06-28"),
                ("HKT", "DOH", "2027-07-10"),
                ("DOH", "LHR", "2027-07-12"),
            ),
        )


class OutsideTheMonthsTests(unittest.TestCase):
    """The exclusion owns months 5-10; a December stay is not its business."""

    def test_a_december_trip_to_phuket_survives(self):
        config = load_holiday_config(DECEMBER_PHUKET)
        hol.LAST_CLIMATE_EXCLUDED = ()
        rows = far_east_watch_rows(config)
        self.assertEqual([row["key"] for row in rows], ["phuket"])
        self.assertEqual(_excluded_names(), [])


class TokyoStaysWithItsWarningTests(unittest.TestCase):
    """Japan's main-island cities stay allowed; the tsuyu line rides along."""

    def test_the_tokyo_two_centre_trip_survives_with_the_tsuyu_line(self):
        config = _july_uncapped()
        hol.LAST_CLIMATE_EXCLUDED = ()
        rows = _multi_centre_rows(config)
        tokyo = [r for r in rows if r["trip"].id == "MC-07"]
        self.assertTrue(tokyo, "MC-07 (Tokyo + Okinawa) must survive the gate")
        warnings = " ".join(tokyo[0].get("warnings") or [])
        self.assertIn("tsuyu", warnings)

    def test_a_tokyo_card_carries_the_warning_and_keeps_its_place(self):
        deal = SimpleNamespace(
            resort_name="A Tokyo hotel",
            destination_key="japan",
            destination_label="Tokyo, Japan",
            airport="HND",
            outbound_date="2027-07-10",
            return_date="2027-07-20",
            monsoon_months=(),
            total_package_price_gbp=1000.0,
            board_basis="BB",
            hotel_rate_basis="market-supported",
            atol_protected=None,
        )
        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        warnings = warning_lines(deal, config)
        self.assertTrue(any("tsuyu" in line for line in warnings), warnings)
        # The warning never removes: the gate itself says nothing about it.
        self.assertIsNone(
            climate.exclusion_for(
                text="Tokyo, Japan", airports=["HND"], stay_months={7},
            )
        )


if __name__ == "__main__":
    unittest.main()
