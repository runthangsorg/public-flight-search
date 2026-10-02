"""The one-booking rule: five travellers in ONE unit, never three rooms.

Owner rule: 5 travellers in ONE booking — a 2-bedroom villa or suite, or two
rooms on the same booking. A resort whose only verified option is three
separate rooms is not a deal: it belongs in the "Strict filters applied" list
with that reason, and no card may claim a three-room quote is "without paying
for 3 scattered rooms".
"""

from __future__ import annotations

from pathlib import Path
import unittest

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    collect_holiday_deals,
    filter_resorts,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
DEC = ROOT / "examples" / "dec_holiday_config.json"
UNCAPPED_GBP = 60000.0

#: Catalogue resorts whose only verified unit is three separate rooms.
THREE_ROOM_RESORTS = (
    "InterContinental Muscat",
    "Nungwi Dreams by Mantis",
    "Sofitel Mauritius L'Impérial Resort & Spa",
)


def _resort(name: str, board: str = "Half Board") -> dict:
    return {"name": name, "board": board}


class ThreeRoomResortTests(unittest.TestCase):
    def test_three_room_resorts_are_filtered_with_that_reason(self):
        for name in THREE_ROOM_RESORTS:
            with self.subTest(resort=name):
                arch = hol.SUITE_ARCHITECTURE[name]
                self.assertEqual(arch.get("rooms_in_unit"), 3)
                kept, dropped = filter_resorts([_resort(name)])
                self.assertEqual(kept, [], "a 3-room unit must never be a card")
                self.assertEqual(
                    [reason for _, reason in dropped],
                    ["needs 3 rooms — breaks the one-unit rule"],
                )

    def test_no_card_in_either_season_needs_three_rooms(self):
        for config_path in (JULY, DEC):
            config = load_holiday_config(config_path.read_text(encoding="utf-8"))
            for deal in collect_holiday_deals(config, max_budget_gbp=UNCAPPED_GBP):
                with self.subTest(config=config_path.name, resort=deal.resort_name):
                    arch = hol.SUITE_ARCHITECTURE[deal.resort_name]
                    self.assertLess(int(arch.get("rooms_in_unit", 1)), 3)
                    self.assertNotIn("3 rooms", deal.unit_architecture)

    def test_the_filtered_list_names_each_three_room_resort(self):
        config = load_holiday_config(DEC.read_text(encoding="utf-8"))
        collect_holiday_deals(config, max_budget_gbp=5000.0)
        listed = {name for name, _ in hol.LAST_FILTERED_OUT}
        self.assertIn("InterContinental Muscat", listed)


UNKNOWN_UNIT_REASON = "unit not verified - cannot confirm one booking for 5"

#: Catalogue resorts whose unit is not shown at all, so neither a one-unit
#: booking nor a two-room booking can be confirmed for five.
UNKNOWN_UNIT_RESORTS = (
    "Grand Fiesta Americana Coral Beach Cancún All Inclusive Spa & Resort",
    "Anantara Rasananda Koh Phangan Villas",
)


class UnknownUnitTests(unittest.TestCase):
    def test_an_unknown_unit_cannot_confirm_one_booking(self):
        for name in UNKNOWN_UNIT_RESORTS:
            with self.subTest(resort=name):
                arch = hol.SUITE_ARCHITECTURE[name]
                self.assertIn("unit not shown", arch["suite_type"])
                kept, dropped = filter_resorts([_resort(name)])
                self.assertEqual(kept, [], "an unknown unit must never be a card")
                self.assertEqual(
                    [reason for _, reason in dropped], [UNKNOWN_UNIT_REASON]
                )

    def test_no_card_has_an_unknown_unit(self):
        for config_path in (JULY, DEC):
            config = load_holiday_config(config_path.read_text(encoding="utf-8"))
            for deal in collect_holiday_deals(config, max_budget_gbp=UNCAPPED_GBP):
                with self.subTest(config=config_path.name, resort=deal.resort_name):
                    self.assertIn(deal.rooms_in_unit, (1, 2))


class NoFalseThreeRoomClaimTests(unittest.TestCase):
    def test_a_card_never_claims_three_rooms_is_not_three_rooms(self):
        config = load_holiday_config(DEC.read_text(encoding="utf-8"))
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        html = render_holiday_report(
            config, generated_at="2026-09-06T12:00:00+00:00", deals=deals
        )
        self.assertNotIn("without paying for 3 scattered rooms", html)


if __name__ == "__main__":
    unittest.main()
