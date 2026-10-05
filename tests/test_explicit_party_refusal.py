"""A unit check refuses the party only when the exporter says so
(BRIEF-H17 §1–§3, 2026-10-06).

``unit_check_blocks_party`` used to ask two questions of the WHOLE finding — is a
refusal word anywhere in it, is a party named anywhere in it — and removed a
resort when both were. The dealsearch side caught the cost of that by hand: a
finding whose last clause was about *our own reading* ("...so it cannot be
re-checked and is not replaced by a rate") beside "5 adults" read as the hotel
refusing five adults, and it would have dropped a card for a hotel that does take
five. The wording was fixed there; the matcher was not.

So there are two rules now, and this file pins both:

1. **The exporter's own ``refuses_party`` decides.** True blocks the party,
   False never blocks — whatever the words beside it say. All 79 checks in the
   shipped evidence carry it, and exactly one is True.
2. **Without it, the wording must be a refusal of the party**: a refusal word and
   the party it refuses in the same clause, at most six words apart. Anything
   unrecognised keeps the card.
3. The job summary counts both, so the fallback's reach is visible instead of
   hypothetical.

Every fixture here is synthetic in its own fields: real property names, real
readings' own GBP figures, no budget, party address, name or path from the
owner's setup.
"""

from __future__ import annotations

import json
import tempfile
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holidays import collect_holiday_deals, load_holiday_config
from public_flight_search.hotel_evidence import (
    consume_hotel_skip_log,
    consume_hotel_unit_check_basis,
    load_hotel_evidence,
    unit_check_blocks_party,
)

GARRYA = "Garrya Tongsai Bay Samui"
NOW = "2026-10-06T09:00:00+00:00"
CARD_PAIR = ("2027-06-28", "2027-07-12")

#: One priceable pair (the card's own), 5 travellers, a ceiling above anything
#: this fixture can price: these tests are about whether a resort is removed.
CONFIG = """
{
  "report_title": "An explicit party refusal",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 12,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-06-28"],
  "return_dates": ["2027-07-12"],
  "destinations": [
    {"key": "koh_samui", "label": "Koh Samui", "airports": ["USM"],
     "flight_hours": 14.92}
  ]
}
"""

#: The engine's own words for a refusal of ONE room, followed by the two rooms
#: on one booking that DO take the party — the wording BRIEF-H17 §1 must read as
#: no refusal at all when the exporter says so.
REFUSED_ONE_ROOM = (
    "5 adults in one room refused: 'Rooms cannot accommodate more than 3 "
    "adults.' / '...3 guests.'; sold as 2 Beachfront Suites in one booking"
)

#: The near miss, in the dealsearch export's own pre-fix words: a real 3-bedroom
#: villa for six guests at a published nightly, so the hotel takes the party,
#: and a last clause about OUR reading that a text matcher reads as a refusal.
NEAR_MISS = (
    "Google Hotels, 5 adults, 2027-06-27..2027-07-09: NO 5-guest row at all - "
    "the page offered only other occupancies: [('AMRETA 3 BEDROOM PRIVATE POOL "
    "VILLA - STAY A', 6, 'AI', 244.0)]. The card's estimate came from a 20-27 "
    "Jul read made by the old parser, whose raw capture no longer exists, so it "
    "cannot be re-checked and is not replaced by a rate."
)

#: The real sold-out wording: nothing on the page, which is not a refusal.
SOLD_OUT = "1 room x 5 adults: 'No rooms available for selected dates'"


def _read(**overrides) -> dict:
    """One qualifying read for the card's OWN pair: two rooms, one booking, 5
    adults, Bed & Breakfast, a GBP nightly."""
    record = {
        "property_name": GARRYA,
        "destination_key": "koh_samui",
        "season": "summer",
        "vendor": "Example brand booking engine",
        "check_in": CARD_PAIR[0],
        "check_out": CARD_PAIR[1],
        "nights": 14,
        "party": {"adults": 5, "children": 0},
        "booking_shape": "two_rooms_one_booking",
        "units": [{"name": "Beachfront Suite - King", "adults": 3},
                  {"name": "Beachfront Suite - King", "adults": 2}],
        "board": "BB",
        "rate_name": "Beachfront Suite · 5 guests",
        "price_basis": "nightly_room_rate",
        "currency": "GBP",
        "prices_shown": [{"unit": "Beachfront Suite - King", "nightly": 655.71,
                          "provider": "Example Hotels"}],
        "derived_stay_total": {
            "value": 9180.0,
            "currency": "GBP",
            "how": "nightly price shown x 14 nights",
        },
        "source_url": "https://example.invalid/booking?dateIn=2027-06-28",
        "observed_at": "2026-10-05T08:10:00+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    record.update(overrides)
    return record


def _check(**overrides) -> dict:
    """One unit check in the real export's shape, ``refuses_party`` stated by
    default so each test says which answer it is about."""
    check = {
        "property_name": GARRYA,
        "destination_key": "koh_samui",
        "season": "summer",
        "vendor": "Accor ALL",
        "dates": [CARD_PAIR[0], CARD_PAIR[1]],
        "finding": REFUSED_ONE_ROOM,
        "refuses_party": False,
        "source_url": "https://example.invalid/brand/hotel/1",
        "observed_at": "2026-10-02T14:51:52+00:00",
    }
    check.update(overrides)
    return check


def _run(checks=(), rates=(), config_json: str = CONFIG):
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"schema": "holiday_hotel_evidence/1", "rates": list(rates),
               "unit_checks": list(checks)}, handle)
    handle.close()
    config = load_holiday_config(config_json)
    loaded = load_hotel_evidence(config, path=handle.name, now=NOW)
    consume_hotel_skip_log()
    basis = consume_hotel_unit_check_basis()
    deals = collect_holiday_deals(config, max_budget_gbp=10 ** 9,
                                  hotel_evidence=loaded)
    consume_hotel_skip_log()
    return config, loaded, deals, basis


def _names(deals):
    return {deal.resort_name for deal in deals}


class TheFieldDecidesTests(unittest.TestCase):
    """§1: True blocks the party, False never blocks, whatever the words say."""

    def test_false_keeps_a_resort_the_wording_alone_would_have_removed(self):
        # No rate at all, so the H4b "nothing to book" branch cannot save it:
        # only the field can, and it says no.
        _config, _loaded, deals, _basis = _run([_check()])
        self.assertIn(GARRYA, _names(deals))

    def test_true_removes_a_resort_the_wording_alone_would_have_kept(self):
        # The words here contain no refusal vocabulary at all — a page that
        # showed one row for six guests and no price. The exporter says the
        # property will not take the party, and that is the answer.
        _config, _loaded, deals, _basis = _run([
            _check(finding=("Google Hotels, 5 adults: one option only - "
                            "'Example - 6 guests', no price shown"),
                   refuses_party=True)])
        self.assertNotIn(GARRYA, _names(deals))

    def test_the_removal_still_states_the_finding_and_its_dates(self):
        _config, _loaded, deals, _basis = _run([_check(refuses_party=True)])
        saved = hol.LAST_FILTERED_OUT
        try:
            reasons = dict(saved)
        finally:
            hol.LAST_FILTERED_OUT = saved
        self.assertIn(GARRYA, reasons)
        self.assertIn(REFUSED_ONE_ROOM, reasons[GARRYA])
        self.assertIn(CARD_PAIR[0], reasons[GARRYA])

    def test_false_stops_a_note_about_the_party_from_being_printed(self):
        # With a qualifying rate the finding is informational (H4b). A check the
        # field says does not refuse the party prints nothing about one.
        _config, _loaded, deals, _basis = _run([_check()], [_read()])
        deal = next(deal for deal in deals if deal.resort_name == GARRYA)
        self.assertEqual(deal.hotel_unit_note, "")
        self.assertIsNotNone(deal.hotel_evidence)

    def test_true_with_a_qualifying_rate_still_becomes_a_note(self):
        _config, _loaded, deals, _basis = _run(
            [_check(refuses_party=True)], [_read()])
        deal = next(deal for deal in deals if deal.resort_name == GARRYA)
        self.assertIn("5 adults in one room refused", deal.hotel_unit_note)

    def test_the_field_reaches_the_record(self):
        _config, _loaded, _deals, _basis = _run(
            [_check(refuses_party=True), _check(finding=SOLD_OUT,
                                                refuses_party=False)])
        self.assertEqual(
            sorted(check.refuses_party for check in _all_checks()),
            [False, True])

    def test_a_check_with_no_field_carries_none(self):
        check = _check()
        check.pop("refuses_party")
        _config, _loaded, _deals, _basis = _run([check])
        self.assertEqual([record.refuses_party for record in _all_checks()], [None])

    def test_a_field_that_is_not_a_boolean_is_not_an_answer(self):
        # A string, a number and a null are all "the exporter did not say", and
        # none of them may stand in for an answer nobody gave.
        for stated in ("true", 1, None):
            with self.subTest(stated=stated):
                _config, _loaded, _deals, _basis = _run(
                    [_check(refuses_party=stated)])
                self.assertEqual(
                    [record.refuses_party for record in _all_checks()], [None])


def _all_checks():
    """Every unit check the last load indexed."""
    from public_flight_search import hotel_evidence as he

    return [
        check
        for entry in he._SUPPLEMENTAL_BY_PROPERTY.values()
        for check in entry.get("unit_checks", ()) or ()
    ]


class TextFallbackTests(unittest.TestCase):
    """§2: no stated answer, so the wording has to carry it — narrowly."""

    def test_the_owners_four_cases(self):
        for finding, expected in (
            ("5 adults in one room refused", True),
            ("the estimate cannot be re-checked; Google lists 5 adults with "
             "breakfast", False),
            ("Rooms cannot accommodate more than 3 adults", True),
            ("two units available: 2+2 and 3+2", False),
        ):
            with self.subTest(finding=finding):
                self.assertEqual(
                    unit_check_blocks_party(finding, 5), expected, finding)

    def test_the_real_near_miss_does_not_block(self):
        self.assertFalse(unit_check_blocks_party(NEAR_MISS, 5))

    def test_a_refusal_and_a_party_in_different_clauses_do_not_block(self):
        self.assertFalse(unit_check_blocks_party(
            "no priced row for 5 adults; the estimate cannot be re-checked", 5))

    def test_a_party_seven_words_away_does_not_block(self):
        # Six words is the ceiling; seven is a different clause.
        self.assertFalse(unit_check_blocks_party(
            "cannot accommodate this party of six grown adults tonight", 5))

    def test_a_refusal_six_words_away_still_blocks(self):
        self.assertTrue(unit_check_blocks_party(
            "one booking cannot be confirmed for 5 adults here", 5))

    def test_a_party_alone_keeps_the_resort(self):
        for finding in ("5 adults in one room, sold as 2 rooms",
                        "5 guests, breakfast, no problem noted",
                        "no rooms were quoted for these dates"):
            with self.subTest(finding=finding):
                self.assertFalse(unit_check_blocks_party(finding, 5), finding)

    def test_nothing_unrecognised_keeps_the_card(self):
        for finding in ("", "   ", "the room list rendered but no rate table did",
                        "the capture was taken before the prices rendered"):
            with self.subTest(finding=finding):
                self.assertFalse(unit_check_blocks_party(finding, 5), finding)

    def test_a_field_overrides_the_wording_in_both_directions(self):
        self.assertFalse(unit_check_blocks_party(
            REFUSED_ONE_ROOM, 5, refuses_party=False))
        self.assertTrue(unit_check_blocks_party(
            NEAR_MISS, 5, refuses_party=True))


class JobSummaryTests(unittest.TestCase):
    """§3: how many unit checks were decided by the field, and how many by text."""

    def _summary(self, checks) -> dict:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"schema": "holiday_hotel_evidence/1", "rates": [],
                   "unit_checks": list(checks)}, handle)
        handle.close()
        _config, _loaded, _deals, basis = _run(checks)
        return basis

    def test_the_two_mechanisms_are_counted_separately(self):
        stated = [_check(refuses_party=True), _check(refuses_party=False)]
        unstated = []
        for finding in (SOLD_OUT, REFUSED_ONE_ROOM, "two units available: 2+2"):
            check = _check(finding=finding)
            check.pop("refuses_party")
            unstated.append(check)
        basis = self._summary(stated + unstated)
        self.assertEqual(basis["total"], 5)
        self.assertEqual(basis["field"], 2)
        self.assertEqual(basis["text"], 3)

    def test_a_file_with_no_unit_checks_counts_nothing(self):
        self.assertEqual(self._summary([]),
                         {"total": 0, "field": 0, "text": 0})

    def test_the_counts_are_read_once_per_load(self):
        # Same shape as ``consume_hotel_skip_log``: the census belongs to THIS
        # load, so a caller that asks twice does not see the first answer twice.
        self._summary([_check()])
        _config, _loaded, _deals, basis = _run([])
        self.assertEqual(basis, {"total": 0, "field": 0, "text": 0})


class SurfacedInTheRunTests(unittest.TestCase):
    """The counts the job summary publishes, from a real planner run."""

    def test_the_summary_names_both_mechanisms(self):
        import os
        from pathlib import Path
        from unittest.mock import patch

        from public_flight_search.jobs import run_holiday_planner

        root = Path(__file__).parents[1]
        payload = (root / "examples" / "july_holiday_config.json").read_text(
            encoding="utf-8")
        stated = _check(refuses_party=True)
        unstated = _check(finding=SOLD_OUT)
        unstated.pop("refuses_party")
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"schema": "holiday_hotel_evidence/1", "rates": [],
                   "unit_checks": [stated, unstated]}, handle)
        handle.close()
        absent = tempfile.mkdtemp(prefix="no-evidence-")
        env = {
            "JULY_HOLIDAY_SEARCH_CONFIG_JSON": payload,
            "HOLIDAY_HISTORY_PATH": os.path.join(absent, "h.jsonl"),
        }
        with patch.dict(os.environ, env, clear=True):
            result = run_holiday_planner(
                dry_run=True, expect_season="july",
                hotel_evidence_path=handle.name,
                live_evidence_path=os.path.join(absent, "absent-live.json"))
        self.assertEqual(result["unit_checks_loaded"], 2)
        self.assertEqual(result["unit_checks_decided_by_field"], 1)
        self.assertEqual(result["unit_checks_decided_by_text"], 1)


if __name__ == "__main__":
    unittest.main()