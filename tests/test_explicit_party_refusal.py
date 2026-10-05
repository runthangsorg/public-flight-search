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
KHAO_LAK = "Pullman Khao Lak Resort"
NOW = "2026-10-06T09:00:00+00:00"
CARD_PAIR = ("2027-06-28", "2027-07-12")
NEAR_PAIR = ("2027-07-20", "2027-07-27")

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

    def test_the_real_refusal_is_removed_on_its_field_alone(self):
        # The shipped file's one true refusal, in its own shape: a check that
        # also reports "no priced row", for a pair this run prices, with no rate
        # for it. The absence sentence is about the price and is not what removes
        # the resort; the exporter's answer is, and it removes it.
        config, _loaded, deals, _basis = _run([
            _check(finding=("Google Hotels, 5 adults, 2027-06-28..2027-07-12: "
                            "no priced row at all - the page says 'Call or visit "
                            "website for rates and availability'"),
                   refuses_party=True)])
        self.assertNotIn(GARRYA, _names(deals))
        saved = hol.LAST_FILTERED_OUT
        reasons = dict(saved)
        self.assertIn(GARRYA, reasons)
        self.assertIn("no priced row at all", reasons[GARRYA])

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


class PerCardTests(unittest.TestCase):
    """Ruling 2 (BRIEF-H17 §5): every card says it for ITSELF, not one note.

    Two destinations, two properties, each with its own "these dates were
    checked and nothing was priced" check. The ruling keeps the line per card
    rather than moving it to a single note under them, and §4 makes it short
    enough to read there.
    """

    TWO_PLACES = """
{
  "report_title": "An absence on every card",
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
     "flight_hours": 14.92},
    {"key": "khao_lak", "label": "Khao Lak", "airports": ["HKT"],
     "flight_hours": 14.5}
  ]
}
"""

    NO_ROW = ("Google Hotels, 5 adults, {start}..{end}: no priced row at all "
              "(the page asks the reader to contact the property)")

    def _checks(self):
        return [
            _check(finding=self.NO_ROW.format(start=CARD_PAIR[0],
                                             end=CARD_PAIR[1])),
            dict(_check(finding=self.NO_ROW.format(start=CARD_PAIR[0],
                                                   end=CARD_PAIR[1])),
                 property_name=KHAO_LAK, destination_key="khao_lak",
                 vendor="Google Hotels"),
        ]

    def test_every_card_carries_its_own_absence_line(self):
        config, _loaded, deals, _basis = _run(self._checks(),
                                              config_json=self.TWO_PLACES)
        names = _names(deals)
        self.assertIn(GARRYA, names)
        self.assertIn(KHAO_LAK, names)
        for deal in deals:
            if deal.resort_name in (GARRYA, KHAO_LAK):
                self.assertEqual(
                    deal.hotel_read_refused,
                    "A check of these dates found no priced row for 5 adults, "
                    "so the stay here is the catalogue's estimate.",
                    deal.resort_name)

    def test_the_email_says_it_on_each_card_rather_than_once(self):
        from html import unescape

        from public_flight_search.holiday_email import (
            render_holiday_report_compact,
            render_holiday_report_compact_text,
        )

        config, _loaded, deals, _basis = _run(self._checks(),
                                              config_json=self.TWO_PLACES)
        sentence = "A check of these dates found no priced row for 5 adults"
        html = unescape(render_holiday_report_compact(
            config, generated_at=NOW, deals=deals))
        text = render_holiday_report_compact_text(
            config, generated_at=NOW, deals=deals)
        self.assertEqual(html.count(sentence), 2)
        self.assertEqual(text.count(sentence), 2)

    def test_a_read_beside_the_check_leaves_the_tail_to_the_board_line(self):
        # Ruling 1 (BRIEF-H17 §4): with a read for another pair priced the stay,
        # the board line already names the basis, so the sentence stops at the
        # absence. Per card, still.
        config, _loaded, deals, _basis = _run(
            self._checks(), [_read(check_in=NEAR_PAIR[0], check_out=NEAR_PAIR[1],
                                    nights=7,
                                    derived_stay_total={"value": 4590.0,
                                                        "currency": "GBP",
                                                        "how": "nightly x 7"})],
            config_json=self.TWO_PLACES)
        deal = next(deal for deal in deals if deal.resort_name == GARRYA)
        self.assertEqual(deal.hotel_rate_basis, "read-rate-estimate")
        self.assertEqual(deal.hotel_read_refused,
                         "A check of these dates found no priced row for 5 adults.")

    def test_a_card_whose_dates_were_never_checked_says_nothing(self):
        # The same run, with the checks removed: nothing about these dates may
        # be claimed by a card nobody checked them for.
        config, _loaded, deals, _basis = _run(config_json=self.TWO_PLACES)
        for deal in deals:
            self.assertEqual(deal.hotel_read_refused, "")


class EvidenceIsGroupedByBookingShapeTests(unittest.TestCase):
    """§7 (and the shape note from H16): evidence is grouped by booking shape.

    The loader filed a pair read in two shapes as ONE entry holding the cheapest
    rate of the lot, so its ``booking_shape`` was whichever shape happened to be
    cheaper rather than the shape a card books. Two things followed: a card could
    be priced from a one-villa read while naming two rooms, and
    ``hotel_rates_near``'s shape filter — the gate that stops a card being priced
    from another shape's nightly — skipped that entry entirely.

    The evidence is Pullman Lombok Merujani Mandalika's own, which is the only
    property in the file read in both shapes: four ``two_rooms_one_booking``
    reads and four ``single_unit`` reads for one pair, the villa cheaper.
    """

    LOMBOK = "Pullman Lombok Merujani Mandalika Beach Resort"
    CARD_PAIR = ("2027-06-27", "2027-07-09")
    NEAR_PAIR = ("2027-06-25", "2027-07-09")

    LOMBOK_CONFIG = """
{
  "report_title": "Evidence grouped by booking shape",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 12,
  "max_nights": 14,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-06-27"],
  "return_dates": ["2027-07-09"],
  "destinations": [
    {"key": "lombok", "label": "Lombok", "airports": ["LOP"],
     "flight_hours": 24.0}
  ]
}
"""

    #: (rate name, total GBP for the stay, refundable, rooms in the read)
    TWO_ROOM_READS = (
        ("STAY LONGER AND SAVE - BREAKFAST INCLUDED", 14839.40, False, 2),
        ("FLEXIBLE RATE - BREAKFAST INCLUDED", 18281.45, True, 2),
        ("EARLY BOOKER - BREAKFAST INCLUDED", 13900.00, False, 2),
        ("MEMBER RATE - BREAKFAST INCLUDED", 15200.00, False, 2),
    )
    ONE_UNIT_READS = (
        ("STAY LONGER AND SAVE - BREAKFAST INCLUDED", 8754.80, False, 1),
        ("FLEXIBLE RATE - BREAKFAST INCLUDED", 10445.07, True, 1),
        ("EARLY BOOKER - BREAKFAST INCLUDED", 8300.00, False, 1),
        ("MEMBER RATE - BREAKFAST INCLUDED", 9100.00, False, 1),
    )

    def _read(self, pair, shape, name, total, refundable, rooms) -> dict:
        nightly = round(total / _nights(pair), 2)
        return {
            "property_name": self.LOMBOK,
            "destination_key": "lombok",
            "season": "summer",
            "vendor": "Example brand booking engine",
            "check_in": pair[0],
            "check_out": pair[1],
            "nights": _nights(pair),
            "party": {"adults": 5, "children": 0},
            "booking_shape": shape,
            # One unit the shape reads, or two rooms on the one booking, as the
            # hotel describes them: the room count is what a read's own record
            # says, not something the engine infers from the shape.
            "units": [{"name": "Garden Villa", "bedrooms_stated": 2,
                       "guests_stated": "6"}] if rooms == 1 else [
                {"name": "Garden Villa", "bedrooms_stated": 2,
                 "guests_stated": "6"},
                {"name": "Garden Villa", "guests_stated": "6"},
            ],
            "board": "BB",
            "rate_name": name,
            "price_basis": "nightly_room_rate",
            "currency": "GBP",
            "prices_shown": [{"unit": "Garden Villa", "nightly": nightly,
                              "provider": "Example Hotels"}],
            "derived_stay_total": {
                "value": total,
                "currency": "GBP",
                "how": f"nightly price shown x {_nights(pair)} nights",
            },
            "terms": [{"unit": "Garden Villa", "refundable": refundable,
                       "cancellation": "free cancellation until 1 Jun",
                       "payment": "pay on arrival"}],
            "source_url": "https://example.invalid/brand/hotel/A1K2",
            "observed_at": "2026-10-05T08:10:00+00:00",
            "exact_date_match": True,
        }

    def _reads(self, pair):
        return [
            self._read(pair, "two_rooms_one_booking", name, total, refundable,
                       rooms)
            for name, total, refundable, rooms in self.TWO_ROOM_READS
        ] + [
            self._read(pair, "single_unit", name, total, refundable, rooms)
            for name, total, refundable, rooms in self.ONE_UNIT_READS
        ]

    def _loaded(self, pair=None):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"schema": "holiday_hotel_evidence/1",
                   "rates": self._reads(pair or self.CARD_PAIR)}, handle)
        handle.close()
        config = load_holiday_config(self.LOMBOK_CONFIG)
        loaded = load_hotel_evidence(config, path=handle.name, now=NOW)
        consume_hotel_skip_log()
        return config, loaded

    def test_one_pair_read_in_two_shapes_is_two_entries(self):
        _config, loaded = self._loaded()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(
            {entry.booking_shape for entry in loaded.values()},
            {"single_unit", "two_rooms_one_booking"},
        )

    def test_each_entry_holds_only_its_own_shapes_rates(self):
        _config, loaded = self._loaded()
        for entry in loaded.values():
            self.assertEqual(len(entry.rates), 4)
            self.assertEqual({rate.booking_shape for rate in entry.rates},
                             {entry.booking_shape})

    def test_the_card_is_priced_from_a_read_of_its_own_shape(self):
        from public_flight_search.hotel_evidence import hotel_rate_for

        config, loaded = self._loaded()
        entry = hotel_rate_for(loaded, self.LOMBOK, *self.CARD_PAIR,
                               booking_shape="single_unit")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.booking_shape, "single_unit")
        self.assertAlmostEqual(entry.cheapest.price_gbp, 8300.00)
        deal = _lombok(config, loaded)
        self.assertEqual(deal.booking_shape_seen, "single_unit")
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 8300.00)

    def test_a_two_room_read_beside_a_cheaper_one_unit_read_is_still_there(self):
        from public_flight_search.hotel_evidence import hotel_rate_for

        _config, loaded = self._loaded()
        two_rooms = hotel_rate_for(loaded, self.LOMBOK, *self.CARD_PAIR,
                                   booking_shape="two_rooms_one_booking")
        self.assertIsNotNone(two_rooms)
        self.assertAlmostEqual(two_rooms.cheapest.price_gbp, 13900.00)
        # The same pair holds the cheaper one-unit read, so an entry grouped by
        # property and dates alone would have kept that one and lost this.
        one_unit = hotel_rate_for(loaded, self.LOMBOK, *self.CARD_PAIR,
                                  booking_shape="single_unit")
        self.assertLess(one_unit.cheapest.price_gbp, two_rooms.cheapest.price_gbp)

    def test_the_shape_filter_sees_a_two_room_read_beside_a_one_unit_read(self):
        from public_flight_search.hotel_evidence import hotel_rates_near

        # A pair that is NOT the card's, read in both shapes, the one-unit read
        # the cheaper. This is the case the filter could not reach: one merged
        # entry per pair, cheapest inside it the wrong shape, whole entry
        # skipped.
        _config, loaded = self._loaded(self.NEAR_PAIR)
        near = hotel_rates_near(loaded, self.LOMBOK, *self.CARD_PAIR,
                                booking_shape="two_rooms_one_booking")
        self.assertEqual(len(near), 1)
        self.assertEqual(near[0].booking_shape, "two_rooms_one_booking")
        self.assertEqual((near[0].check_in, near[0].check_out), self.NEAR_PAIR)

    def test_the_nearest_read_of_the_cards_own_shape_prices_the_stay(self):
        # The other half of §7, and the half that reaches a card: this property's
        # card books one villa, so a read for another pair prices it as one villa
        # — which is only knowable because the shape is part of the entry.
        config, loaded = self._loaded(self.NEAR_PAIR)
        deal = _lombok(config, loaded)
        self.assertEqual(deal.hotel_rate_basis, "read-rate-estimate")
        self.assertEqual(deal.hotel_rate_read_dates, self.NEAR_PAIR)
        self.assertAlmostEqual(deal.hotel_price_total_gbp,
                               8300.00 / 14 * 12, places=2)


def _lombok(config, loaded):
    deals = collect_holiday_deals(config, max_budget_gbp=10 ** 9,
                                  hotel_evidence=loaded)
    consume_hotel_skip_log()
    return next(deal for deal in deals
                if deal.resort_name == EvidenceIsGroupedByBookingShapeTests.LOMBOK)


def _nights(pair) -> int:
    from datetime import date

    return (date.fromisoformat(pair[1]) - date.fromisoformat(pair[0])).days


if __name__ == "__main__":
    unittest.main()