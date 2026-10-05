"""A rate read that could not price this card says WHICH reason
(BRIEF-H16 §2, 2026-10-06).

BRIEF-H15 §2 named one reason — the board — and printed it as
``A rate read for 20–28 Dec was Bed & Breakfast at £731 a night; the All
Inclusive price here is the catalogue's estimate.`` A read can be refused for
three other reasons and the reader had no way to learn which: one villa is not
two rooms on one booking, a rate quoted for three adults is not a rate for five,
and a booking of the same shape can still cover a different number of rooms.
So the sentence became the owner's general one —

    A rate read for <dates> was not used (<reason in words>); the price here is
    the catalogue's estimate.

— and every reason is named in the same clause.

The second half of §2 is the case nobody could see at all: a property whose OWN
dates were checked and came back with no priced row for the party. Garrya
Tongsai Bay's four June pairs, the card's 28 Jun–12 Jul among them, are recorded
that way, so its card could say that somebody looked for these exact dates and
found nothing, and that the stay below is estimated from the 20–27 Jul read.

Every fixture is synthetic in its own fields: real property names, real reads'
own GBP figures, no budget, party address, name or path from the owner's setup.
"""

from __future__ import annotations

from html import unescape
import json
import tempfile
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    board_line,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import collect_holiday_deals, load_holiday_config
from public_flight_search.hotel_evidence import (
    consume_hotel_skip_log,
    load_hotel_evidence,
)

GARRYA = "Garrya Tongsai Bay Samui"
NOW = "2026-10-06T09:00:00+00:00"
CARD_PAIR = ("2027-06-28", "2027-07-12")
NEAR_PAIR = ("2027-07-20", "2027-07-27")

#: One priceable pair (the card's own), 5 travellers, a ceiling above anything
#: this fixture can price: these tests are about which sentence a card carries,
#: and the budget rules have their own file.
CONFIG = """
{
  "report_title": "A refused read says why",
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

#: Garrya books 2 rooms on one booking — two Beachfront Suites of 3 and 2
#: adults — so every reason below has something real to differ from.
CARD_SHAPE = "two_rooms_one_booking"
CARD_ROOMS = 2


def _read(**overrides) -> dict:
    """One rate read for Garrya, in the real export's shape: 20–27 Jul, BB,
    two rooms on one booking, 5 adults, a GBP nightly."""
    record = {
        "property_name": GARRYA,
        "destination_key": "koh_samui",
        "season": "summer",
        "vendor": "Example brand booking engine",
        "check_in": NEAR_PAIR[0],
        "check_out": NEAR_PAIR[1],
        "nights": 7,
        "party": {"adults": 5, "children": 0},
        "booking_shape": CARD_SHAPE,
        "units": [{"name": "Beachfront Suite - King", "adults": 3},
                  {"name": "Beachfront Suite - King", "adults": 2}],
        "board": "BB",
        "rate_name": "Beachfront Suite · 5 guests",
        "price_basis": "nightly_room_rate",
        "currency": "GBP",
        "prices_shown": [{"unit": "Beachfront Suite - King", "nightly": 655.71,
                          "provider": "Example Hotels"}],
        "derived_stay_total": {
            "value": 4590.0,
            "currency": "GBP",
            "how": ("nightly price shown x 7 nights; the listing shows a nightly "
                    "figure, not the stay total"),
        },
        "source_url": "https://example.invalid/booking?dateIn=2027-07-20",
        "observed_at": "2026-10-05T08:10:00+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    record.update(overrides)
    return record


def _no_row_check(**overrides) -> dict:
    """A unit check in the real file's words: the page showed no priced row for
    the party and told the reader to contact the property."""
    check = {
        "property_name": GARRYA,
        "destination_key": "koh_samui",
        "season": "summer",
        "vendor": "Google Hotels",
        "dates": [CARD_PAIR[0], CARD_PAIR[1]],
        "finding": ("Google Hotels, 5 adults, 2027-06-28..2027-07-12: no priced "
                    "row at all (the page asks the reader to contact the "
                    "property)"),
        "source_url": "https://example.invalid/google?q=tongsai",
        "observed_at": "2026-10-05T14:39:54+00:00",
        "refuses_party": False,
    }
    check.update(overrides)
    return check


def _write(payload: dict) -> str:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    return handle.name


def _run(rates=(), checks=()):
    """One synthetic run, with the given reads and unit checks loaded."""
    config = load_holiday_config(CONFIG)
    loaded = load_hotel_evidence(
        config,
        path=_write({"schema": "holiday_hotel_evidence/1",
                     "rates": list(rates),
                     "unit_checks": list(checks)}),
        now=NOW,
    )
    consume_hotel_skip_log()
    deals = collect_holiday_deals(
        config, max_budget_gbp=float(config.max_budget_gbp),
        hotel_evidence=loaded,
    )
    consume_hotel_skip_log()
    return config, loaded, deals


def _deal(deals):
    for deal in deals:
        if deal.resort_name == GARRYA:
            return deal
    raise AssertionError(f"no card for {GARRYA}: {[d.resort_name for d in deals]}")


class BookingShapeTests(unittest.TestCase):
    """One unit is not two rooms on one booking: two different bookings."""

    def test_a_read_on_one_unit_is_named_as_a_shape_refusal(self):
        # The read is refused on SHAPE, so the card falls back to the
        # catalogue — and says so.
        config, loaded, deals = _run([_read(booking_shape="single_unit",
                                            units=[{"name": "Garden Suite",
                                                    "adults": 5}])])
        deal = _deal(deals)
        self.assertEqual(
            deal.hotel_read_refused,
            "A rate read for 20–27 Jul was not used (it is one unit, and this "
            "card is 2 rooms on one booking); the price here is the catalogue's "
            "estimate.")

    def test_the_shape_word_names_the_reads_own_room_count(self):
        config, loaded, deals = _run([_read(booking_shape="single_unit",
                                            units=[{"name": "Garden Suite",
                                                    "adults": 5}])])
        self.assertIn("it is one unit", _deal(deals).hotel_read_refused)


class PartyTests(unittest.TestCase):
    """A rate quoted for three adults is not a rate for this party of five."""

    #: 3 adults + 2 children IS the report's party of five, so the loader admits
    #: it — BRIEF-H15 §1's party gate counts people, not adults — and the
    #: sentence has to be able to say this is not a read for five adults.
    SMALLER_ADULTS_READ = _read(party={"adults": 3, "children": 2})

    def test_a_read_for_a_smaller_party_is_named(self):
        # Exercised on the classifier, which is where the rule lives: the
        # pricing path does not treat a party as a gate, so a collect run would
        # price the card from this read and print nothing. The sentence still has
        # to be able to say what differed.
        resort = {"name": GARRYA, "board": "Bed & Breakfast"}
        loaded = self._loaded()
        self.assertEqual(
            hol.read_refusal_caution(resort, loaded, *CARD_PAIR,
                                     arch=hol.SUITE_ARCHITECTURE[GARRYA],
                                     travellers=5, stay=None),
            "A rate read for 20–27 Jul was not used (it was quoted for 3 "
            "adults, and this card is for 5); the price here is the catalogue's "
            "estimate.")

    def _loaded(self):
        loaded = load_hotel_evidence(
            load_holiday_config(CONFIG),
            path=_write({"schema": "holiday_hotel_evidence/1",
                         "rates": [self.SMALLER_ADULTS_READ]}),
            now=NOW,
        )
        consume_hotel_skip_log()
        return loaded

    def test_the_read_is_still_admitted_by_the_loader(self):
        # The point of the example: the gate counts people, so this read reaches
        # the card at all and the party difference is real.
        self.assertEqual(len(self._loaded()), 1)

    def test_a_read_for_the_reports_own_party_is_not_a_party_refusal(self):
        config, loaded, deals = _run([_read()])
        deal = _deal(deals)
        # Nothing refused it, so it priced the stay and there is no sentence.
        self.assertEqual(deal.hotel_read_refused, "")
        self.assertEqual(deal.hotel_rate_basis, "read-rate-estimate")


class RoomsTests(unittest.TestCase):
    """The same declared shape can still cover a different number of rooms."""

    ONE_ROOM_READ = _read(units=[{"name": "Beachfront Suite - King",
                                  "adults": 5}])

    def test_a_read_that_names_one_room_is_named(self):
        # Declared as two rooms on one booking but describing a single room: the
        # shape matches, the room count does not. Exercised on the classifier for
        # the reason given in ``PartyTests`` — a room count is not a gate today.
        loaded = load_hotel_evidence(
            load_holiday_config(CONFIG),
            path=_write({"schema": "holiday_hotel_evidence/1",
                         "rates": [self.ONE_ROOM_READ]}),
            now=NOW,
        )
        consume_hotel_skip_log()
        resort = {"name": GARRYA, "board": "Bed & Breakfast"}
        self.assertEqual(
            hol.read_refusal_caution(resort, loaded, *CARD_PAIR,
                                     arch=hol.SUITE_ARCHITECTURE[GARRYA],
                                     travellers=5, stay=None),
            "A rate read for 20–27 Jul was not used (it covers 1 room, and this "
            "card is 2); the price here is the catalogue's estimate.")

    def test_a_read_naming_the_cards_own_rooms_is_not_a_rooms_refusal(self):
        loaded = load_hotel_evidence(
            load_holiday_config(CONFIG),
            path=_write({"schema": "holiday_hotel_evidence/1",
                         "rates": [_read()]}),
            now=NOW,
        )
        consume_hotel_skip_log()
        resort = {"name": GARRYA, "board": "All Inclusive"}
        # Only the board differs here, so only the board may be named.
        self.assertIn("it was Bed & Breakfast",
                      hol.read_refusal_caution(
                          resort, loaded, *CARD_PAIR,
                          arch=hol.SUITE_ARCHITECTURE[GARRYA],
                          travellers=5, stay=None))


class BoardTests(unittest.TestCase):
    """The reason BRIEF-H15 §2 already had, unchanged in substance."""

    def test_the_board_reason_still_leads_with_the_read_and_its_nightly(self):
        # Garrya's catalogue board is Bed & Breakfast, so this read matches and
        # prices the card. The BOARD branch is exercised on the resort record
        # instead — the shape, party and rooms are the same as the card's, so
        # nothing else can be the reason.
        resort = {"name": GARRYA, "board": "All Inclusive"}
        loaded = load_hotel_evidence(
            load_holiday_config(CONFIG),
            path=_write({"schema": "holiday_hotel_evidence/1",
                         "rates": [_read()]}),
            now=NOW,
        )
        consume_hotel_skip_log()
        self.assertEqual(
            hol.read_refusal_caution(resort, loaded, *CARD_PAIR,
                                     arch=hol.SUITE_ARCHITECTURE[GARRYA],
                                     travellers=5, stay=None),
            "A rate read for 20–27 Jul was not used (it was Bed & Breakfast at "
            "£656 a night, and this card is All Inclusive); the price here is "
            "the catalogue's estimate.")

    def test_the_shape_is_judged_before_the_board_for_a_near_read(self):
        # Both differ, and only one of them is what actually stopped the read:
        # ``hotel_rates_near`` filters on shape before anything else sees it, so
        # naming the board would name a reason that was never the gate.
        resort = {"name": GARRYA, "board": "All Inclusive"}
        loaded = load_hotel_evidence(
            load_holiday_config(CONFIG),
            path=_write({"schema": "holiday_hotel_evidence/1",
                         "rates": [_read(booking_shape="single_unit",
                                         units=[{"name": "Garden Suite",
                                                 "adults": 5}])]}),
            now=NOW,
        )
        consume_hotel_skip_log()
        sentence = hol.read_refusal_caution(
            resort, loaded, *CARD_PAIR,
            arch=hol.SUITE_ARCHITECTURE[GARRYA], travellers=5, stay=None)
        self.assertIn("it is one unit", sentence)
        self.assertNotIn("Bed & Breakfast", sentence)


class OwnDatesCheckedTests(unittest.TestCase):
    """§2's second half: these dates were checked and nothing was priced."""

    def test_the_card_says_a_check_of_these_dates_found_no_priced_row(self):
        config, loaded, deals = _run([_read()], [_no_row_check()])
        deal = _deal(deals)
        self.assertEqual(
            deal.hotel_read_refused,
            "A check of these dates found no priced row for 5 adults, so the "
            "stay is estimated from a read rate for 20–27 Jul.")

    def test_the_stay_below_it_is_still_the_20_27_july_nightly(self):
        config, loaded, deals = _run([_read()], [_no_row_check()])
        deal = _deal(deals)
        self.assertEqual(deal.hotel_rate_basis, "read-rate-estimate")
        self.assertAlmostEqual(deal.hotel_price_total_gbp,
                               4590.0 / 7 * 14, places=2)
        self.assertIn("estimate from a read rate for 20–27 Jul",
                      board_line(deal, travellers=5))

    def test_it_names_the_catalogue_when_there_is_no_read_to_carry(self):
        # Nothing read and these dates came back empty: "no priced row" with
        # nothing after it would leave the reader guessing between a catalogue
        # guess and a real nightly, which are very different to book against.
        config, loaded, deals = _run([], [_no_row_check()])
        deal = _deal(deals)
        self.assertEqual(
            deal.hotel_read_refused,
            "A check of these dates found no priced row for 5 adults, so the "
            "stay here is the catalogue's estimate.")

    def test_a_check_for_other_dates_is_not_about_these_dates(self):
        config, loaded, deals = _run([_read()], [
            _no_row_check(dates=[NEAR_PAIR[0], NEAR_PAIR[1]])])
        self.assertEqual(_deal(deals).hotel_read_refused, "")

    def test_a_check_that_names_no_dates_cannot_claim_these_dates(self):
        config, loaded, deals = _run([_read()], [_no_row_check(dates=[])])
        self.assertEqual(_deal(deals).hotel_read_refused, "")

    def test_a_refusal_of_the_party_is_not_an_absence(self):
        # "5 adults in one room refused, sold as 2 suites" is a LIMIT, not a
        # search that came back empty — and H4's unit-check rule removes the
        # resort for it, so there is no card left to print an absence on. The
        # refusal is stated where it is: in the Notes.
        saved = hol.LAST_FILTERED_OUT
        try:
            config, loaded, deals = _run([_read()], [
                _no_row_check(finding=(
                    "5 adults in one room refused: 'Rooms cannot accommodate "
                    "more than 3 adults.'; sold as 2 Beachfront Suites in one "
                    "booking"), refuses_party=True)])
            self.assertNotIn(GARRYA, [d.resort_name for d in deals])
            reasons = dict(hol.LAST_FILTERED_OUT)
            self.assertIn(GARRYA, reasons)
            self.assertIn("5 adults in one room refused", reasons[GARRYA])
        finally:
            hol.LAST_FILTERED_OUT = saved

    def test_a_check_for_another_party_does_not_speak_for_this_one(self):
        config, loaded, deals = _run([_read()], [
            _no_row_check(finding=("Google Hotels, 3 adults, "
                                   "2027-06-28..2027-07-12: no priced row at "
                                   "all"))])
        self.assertEqual(_deal(deals).hotel_read_refused, "")

    def test_the_field_decides_the_party_and_not_the_absence(self):
        # BRIEF-H17 §1. ``refuses_party`` is the exporter's answer to whether
        # the property refuses the party in one booking, and it is asked nowhere
        # else: a check whose words report a search that came back empty still
        # raises the absence sentence whatever it says about refusing, because
        # sold out is not a refusal and this sentence is about the price.
        config, loaded, deals = _run([_read()], [_no_row_check()])
        self.assertIn("found no priced row for 5 adults",
                      _deal(deals).hotel_read_refused)


class SurfaceTests(unittest.TestCase):
    """One sentence, three renderers: the e-mail, its twin and the page."""

    def setUp(self):
        self.config, _loaded, deals = _run([_read()], [_no_row_check()])
        self.deal = _deal(deals)
        self.sentence = self.deal.hotel_read_refused

    def test_the_compact_email_carries_it(self):
        html = render_holiday_report_compact(
            self.config, generated_at=NOW, deals=[self.deal])
        self.assertIn(self.sentence, unescape(html))

    def test_the_plain_text_email_carries_the_same_words(self):
        text = render_holiday_report_compact_text(
            self.config, generated_at=NOW, deals=[self.deal])
        self.assertIn(self.sentence, text)

    def test_the_audit_page_carries_the_same_words(self):
        html = hol.render_holiday_report(
            self.config, generated_at=NOW, deals=[self.deal])
        self.assertIn("Rate read not used:", html)
        self.assertIn(self.sentence, unescape(html))

    def test_it_is_not_one_of_the_two_capped_warnings(self):
        # BRIEF-H16 §2: "Not a capped warning, as in §2". The caution is its own
        # field and its own line, so a card with two warnings still carries it.
        from public_flight_search.holiday_email import warning_lines

        self.assertNotIn(self.sentence, warning_lines(self.deal, self.config))


if __name__ == "__main__":
    unittest.main()