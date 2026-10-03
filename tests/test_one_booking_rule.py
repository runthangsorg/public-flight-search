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

#: Catalogue resorts whose only verified unit is three separate rooms. Muscat
#: and Zanzibar were on this list until 2026-10-03 (H6): both turned out to
#: have a one-booking unit (two rooms on the same booking for Muscat, a
#: four-bedroom villa for Zanzibar), and the rule removes a resort for three
#: rooms only while three rooms is what the resort actually has.
THREE_ROOM_RESORTS = ("Sofitel Mauritius L'Impérial Resort & Spa",)


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
        for name in THREE_ROOM_RESORTS:
            with self.subTest(resort=name):
                self.assertIn(name, listed)

    def test_a_resort_with_a_one_booking_unit_is_not_still_called_three_rooms(self):
        """The H6 regression: a confirmed unit must clear the three-room list.

        Leaving Muscat and Zanzibar on this list after their units were checked
        would be the opposite error to the one the rule exists to stop — the
        reader would be told a good resort is three scattered rooms when the
        hotel sells them one booking.
        """
        config = load_holiday_config(DEC.read_text(encoding="utf-8"))
        collect_holiday_deals(config, max_budget_gbp=5000.0)
        reasons = dict(hol.LAST_FILTERED_OUT)
        for name in ("InterContinental Muscat", "Nungwi Dreams by Mantis"):
            with self.subTest(resort=name):
                self.assertNotEqual(
                    reasons.get(name),
                    "needs 3 rooms — breaks the one-unit rule",
                )


UNKNOWN_UNIT_REASON = "unit not verified - cannot confirm one booking for 5"

#: Catalogue resorts whose unit was NOT SHOWN at all — neither a one-unit
#: booking nor a two-room booking could be confirmed for five — until 2026-10-03
#: (H6), when each was checked and a real one-booking unit was found. Cancun's
#: is a two-bedroom suite, Rasananda's a two-bedroom pool villa. They stay here
#: as the regression in both directions: a unit that has been confirmed must
#: not be quietly dropped again, and must not still be described as unknown.
CONFIRMED_UNIT_SINCE_H6 = (
    "Grand Fiesta Americana Coral Beach Cancún All Inclusive Spa & Resort",
    "Anantara Rasananda Koh Phangan Villas",
)


class UnknownUnitTests(unittest.TestCase):
    def test_an_unknown_unit_can_never_confirm_one_booking(self):
        """The rule itself, stated over the whole catalogue.

        An unknown unit ("unit not shown") cannot be read as one booking, so
        ``filter_resorts`` must remove it — and no resort may be carrying that
        mark, because every one in the catalogue has been checked.
        """
        unknown = [
            name
            for name, arch in hol.SUITE_ARCHITECTURE.items()
            if "unit not shown" in str(arch.get("suite_type", "")).lower()
        ]
        self.assertEqual(
            unknown, [], f"resorts still left with no unit shown: {unknown}"
        )

    def test_a_unit_confirmed_since_h6_is_no_longer_treated_as_unknown(self):
        for name in CONFIRMED_UNIT_SINCE_H6:
            with self.subTest(resort=name):
                arch = hol.SUITE_ARCHITECTURE[name]
                self.assertNotIn("unit not shown", str(arch.get("suite_type", "")))
                _, dropped = filter_resorts([_resort(name)])
                self.assertNotIn(
                    UNKNOWN_UNIT_REASON,
                    [reason for _, reason in dropped],
                    "a resort whose unit has been confirmed must not still be "
                    "removed for an unconfirmed one",
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
