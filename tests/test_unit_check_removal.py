"""A unit check may only remove a resort when there is nothing to book.

Owner brief 2026-10-03 (H4b), after H4 removed two good resorts. The first
unit-check rule matched the words "refused" and "one room" and read
"5 adults in one room refused ... sold as 2 rooms in one booking" as a
refusal of the party. It is not: two rooms on ONE booking is exactly what the
owner's rule allows, the loader had a qualifying rate for both properties, and
July fell from a full set of cards to two.

The corrected rule is narrower and states the thing that actually matters: a
unit check removes a resort only when the loader found NO qualifying
one-booking rate for that property on those dates. When one exists, the
finding is still true and still worth saying — it becomes a note on the card
instead of a removal.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from public_flight_search import holidays
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_hotel_unit_note_line,
    render_holiday_report,
)
from public_flight_search.hotel_evidence import consume_hotel_skip_log, load_hotel_evidence

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/hotel_evidence_sample.json"
JULY = ROOT / "examples/july_holiday_config.json"

NOW = "2026-10-03T12:00:00+00:00"

#: The engine's real wording for a property that solved the party with two
#: rooms on one booking — a refusal of ONE room, not of the party.
FINDING = (
    "5 adults in one room refused: no single unit sleeps 5; "
    "sold as 2 rooms in one booking"
)

CONFIG = """
{
  "report_title": "Unit check removal",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 6,
  "max_nights": 10,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "khao_lak", "label": "Khao Lak", "airports": ["HKT"], "flight_hours": 14.5}
  ]
}
"""

RESORT = "Pullman Khao Lak Resort"


def _payload(*, include_rate: bool) -> dict:
    """Just this property: its rate (or not) and one unit check.

    ``include_rate`` False swaps in the OUTRIGHT refusal — the property has no
    two-bedroom villa at all — which is the only case that may remove a card.
    """
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["rates"] = [rate for rate in data["rates"] if rate["property_name"] == RESORT]
    data["unit_checks"] = [check for check in data["unit_checks"]
                           if check["property_name"] == RESORT]
    data["ratings"] = []
    data["facts"] = []
    data["blocked"] = []
    if not include_rate:
        data["rates"] = []
        for check in data["unit_checks"]:
            check["finding"] = (
                "5 adults in one room refused: the property has no 2-bedroom villa"
            )
    return data


def _deals(*, include_rate: bool, config_json: str = CONFIG):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
    json.dump(_payload(include_rate=include_rate), handle)
    handle.close()
    config = load_holiday_config(config_json)
    loaded = load_hotel_evidence(config, path=handle.name, now=NOW)
    deals = collect_holiday_deals(config, max_budget_gbp=10 ** 9,
                                  hotel_evidence=loaded)
    consume_hotel_skip_log()
    return deals


def _deal(*, include_rate: bool, config_json: str = CONFIG):
    return next(deal for deal in _deals(include_rate=include_rate,
                                        config_json=config_json)
                if deal.resort_name == RESORT)


class ResortStaysWhenItCanBeBookedTests(unittest.TestCase):
    def test_a_two_room_one_booking_rate_keeps_the_resort(self):
        deal = _deal(include_rate=True)
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 1600.00)
        self.assertEqual(deal.booking_shape_seen, "two_rooms_one_booking")

    def test_the_finding_becomes_a_note_not_a_removal(self):
        deal = _deal(include_rate=True)
        self.assertIn("2 rooms in one booking", deal.hotel_unit_note)

    def test_the_note_is_shown_on_the_card(self):
        html = render_hotel_unit_note_line(_deal(include_rate=True))
        self.assertIn("refused", html)
        self.assertIn("2 rooms in one booking", html)

    def test_the_resort_is_not_in_the_removed_list(self):
        _deals(include_rate=True)
        removed = {name for name, _reason in holidays.LAST_FILTERED_OUT}
        self.assertNotIn(RESORT, removed)


class ResortGoesWhenItCannotBeBookedTests(unittest.TestCase):
    def test_a_finding_with_no_qualifying_rate_removes_the_resort(self):
        deals = _deals(include_rate=False)
        self.assertNotIn(RESORT, {deal.resort_name for deal in deals})

    def test_the_removal_states_the_finding(self):
        _deals(include_rate=False)
        removed = {name: reason for name, reason in holidays.LAST_FILTERED_OUT}
        self.assertIn(RESORT, removed)
        self.assertIn("no 2-bedroom villa", removed[RESORT])

    def test_the_other_resorts_stay(self):
        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8")
        json.dump(_payload(include_rate=False), handle)
        handle.close()
        loaded = load_hotel_evidence(config, path=handle.name, now=NOW)
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp,
                                      hotel_evidence=loaded)
        consume_hotel_skip_log()
        names = {deal.resort_name for deal in deals}
        self.assertNotIn(RESORT, names)
        self.assertTrue(names, "removing one resort must not empty the report")


class JulyStillHasItsCardsTests(unittest.TestCase):
    """The regression itself: July is not down to two cards."""

    def test_july_keeps_both_two_room_resorts_and_many_cards(self):
        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        loaded = load_hotel_evidence(config, path=str(FIXTURE), now=NOW)
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp,
                                      hotel_evidence=loaded)
        consume_hotel_skip_log()
        names = {deal.resort_name for deal in deals}
        self.assertIn("Pullman Khao Lak Resort", names)
        self.assertIn("Garrya Tongsai Bay Samui", names)
        self.assertGreater(len(deals), 2,
                           "a unit check that describes a two-room workaround "
                           "must not empty the July report")

    def test_the_july_report_renders_those_cards(self):
        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        loaded = load_hotel_evidence(config, path=str(FIXTURE), now=NOW)
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp,
                                      hotel_evidence=loaded)
        consume_hotel_skip_log()
        html = render_holiday_report(config, generated_at=NOW, deals=deals)
        self.assertIn("Pullman Khao Lak Resort", html)
        self.assertIn("sold as 2 rooms in one booking", html)


if __name__ == "__main__":
    unittest.main()