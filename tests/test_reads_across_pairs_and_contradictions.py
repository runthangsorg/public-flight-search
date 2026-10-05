"""A read outside the window still prices, and a contradicted catalogue says so
(owner brief 2026-10-05, H15).

Two things REPLY-H14 flagged as "not in scope here", both of them cases where the
card described something other than the thing it was priced on:

1. **A read on a pair the run does not price was thrown away.** The loader kept a
   read only when its own ``(check_in, check_out)`` was one the run prices, so a
   read for 20–27 Jul could never inform a card on 28 Jun – 12 Jul: Garrya Tongsai
   Bay Samui and The Lombok Lodge both fell back to the catalogue nightly while a
   real nightly for the same property, board, unit and season sat in the same
   file. Such a read is now kept, marked ``pair_is_priceable`` False, and can
   price another pair's nights ONLY as the derived, labelled estimate BRIEF-H14
   §1 already had — never as a price for the dates it was read for, because this
   run does not offer those dates at all. Every other loader gate still refuses
   it.
2. **A card whose own dates were read on another board showed a figure nothing
   supported.** Lara Barut Collection's December card is All Inclusive at the
   catalogue's ~£185 a night; the only read of that property is Bed & Breakfast at
   ~£731 a night. H3's board rule rightly refuses a breakfast rate to price an
   all-inclusive card, so the catalogue stands — but silently. The card now says
   so, once, in the compact e-mail and on the audit page.

Every fixture here is synthetic in its own fields: the property names are the real
ones, the figures are the real reads' own GBP figures, and no budget, party
address, name or path from the owner's setup appears anywhere. A fixture built
from invented prices would make the arithmetic on the card harder to check
against the card it is testing.
"""

from __future__ import annotations

import json
import tempfile
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    board_line,
    render_holiday_report_compact,
)
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
)
from public_flight_search.hotel_evidence import (
    consume_hotel_skip_log,
    hotel_rate_for,
    hotel_rates_near,
    load_hotel_evidence,
)

GARRYA = "Garrya Tongsai Bay Samui"
LOMBOK_LODGE = "The Lombok Lodge"
LARA_BARUT = "Lara Barut Collection"

NOW = "2026-10-05T09:00:00+00:00"

#: One priceable pair, 28 Jun – 12 Jul 2027, so a read for 20–27 Jul is outside
#: the run's window by construction rather than by accident, and the arithmetic
#: on the card has one pair to land on. The ceiling is synthetic and far above
#: everything this fixture can price: these tests are about which number the
#: card carries, and the budget rules have their own file.
OFF_WINDOW_CONFIG = """
{
  "report_title": "A read outside the window",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 12,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-06-28"],
  "return_dates": ["2027-07-12", "2027-07-13"],
  "destinations": [
    {"key": "koh_samui", "label": "Koh Samui", "airports": ["USM"],
     "flight_hours": 14.92}
  ]
}
"""

#: The same window with nothing read: the control for every §1 assertion.
NO_READ_CONTROL = "652.19"

#: December, 17–25 Dec is the pair the card is built on and Lara Barut's only
#: read is 20–28 Dec — a different pair, a different board, and a price four
#: times the catalogue's. All Inclusive is what the catalogue says it sells.
BOARD_CONTRADICTION_CONFIG = """
{
  "report_title": "A contradicted catalogue board",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 7,
  "max_nights": 9,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-17"],
  "return_dates": ["2026-12-25"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"], "flight_hours": 4.5}
  ]
}
"""

BOARD_CONTRADICTION_PAIR = ("2026-12-17", "2026-12-25")
#: The catalogue's own nightly for this card, which is what it is priced at.
LARA_CATALOGUE_NIGHTLY = 185.0


def _garrya_read(**overrides) -> dict:
    """Garrya Tongsai's shape: EUR, two rooms, a converted total, 20–27 Jul."""
    record = {
        "property_name": GARRYA,
        "destination_key": "koh_samui",
        "season": "summer",
        "vendor": "Example brand booking engine",
        "check_in": "2027-07-20",
        "check_out": "2027-07-27",
        "nights": 7,
        "party": {"adults": 5, "children": 0},
        "booking_shape": "two_rooms_one_booking",
        "units": [{"name": "Beachfront Suite - King", "adults": 5}],
        "board": "BB",
        "rate_name": "SUPER ADVANCE SAVER - BED AND BREAKFAST",
        "price_basis": "total_stay_rate",
        "currency": "EUR",
        "prices_shown": [
            {"unit": "Beachfront Suite - King", "public": 2965.64},
            {"unit": "Beachfront Suite - King", "public": 2410.74},
        ],
        "derived_gbp": {
            "value": 4589.98,
            "how": ("public total x ECB EUR/GBP 0.85373 (2026-10-01); "
                    "a conversion, not a GBP price"),
        },
        "source_url": "https://example.invalid/booking?dateIn=2027-07-20",
        "observed_at": "2026-10-05T08:10:00+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    record.update(overrides)
    return record


def _lombok_lodge_read(**overrides) -> dict:
    """The Lombok Lodge's shape: one GBP nightly from an aggregator, 20–27 Jul."""
    record = {
        "property_name": LOMBOK_LODGE,
        "destination_key": "lombok",
        "season": "summer",
        "vendor": "Example aggregator",
        "check_in": "2027-07-20",
        "check_out": "2027-07-27",
        "nights": 7,
        "party": {"adults": 5, "children": 0},
        "booking_shape": "single_unit",
        "units": [{"name": "Two-Bedroom Villa", "guests_stated": "5 guests"}],
        "board": "BB",
        "rate_name": "Two-Bedroom Villa",
        "price_basis": "nightly_room_rate",
        "currency": "GBP",
        "prices_shown": [{"unit": "Two-Bedroom Villa", "nightly": 1718.0,
                          "provider": "Example aggregator"}],
        "derived_stay_total": {
            "value": 12026.0,
            "currency": "GBP",
            "how": ("nightly price shown x 7 nights; the listing shows a nightly "
                    "figure, not the stay total"),
        },
        "source_url": "https://example.invalid/stay/1",
        "observed_at": "2026-10-05T08:10:00+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    record.update(overrides)
    return record


def _lara_barut_read(**overrides) -> dict:
    """Lara Barut's shape: a breakfast rate for a card that is all inclusive."""
    record = {
        "property_name": LARA_BARUT,
        "destination_key": "antalya",
        "season": "winter",
        "vendor": "Example aggregator",
        "check_in": "2026-12-20",
        "check_out": "2026-12-28",
        "nights": 8,
        "party": {"adults": 5, "children": 0},
        "booking_shape": "single_unit",
        "units": [{"name": "Halalbooking", "guests_stated": "5 guests"}],
        "board": "BB",
        "rate_name": "Halalbooking",
        "price_basis": "nightly_room_rate",
        "currency": "GBP",
        "prices_shown": [{"unit": "Halalbooking", "nightly": 731.0,
                          "provider": "Example Hotels"}],
        "derived_stay_total": {
            "value": 5848.0,
            "currency": "GBP",
            "how": ("nightly price shown x 8 nights; the listing shows a nightly "
                    "figure, not the stay total"),
        },
        "source_url": "https://example.invalid/stay/2",
        "observed_at": "2026-10-05T08:10:00+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    record.update(overrides)
    return record


def _write(payload: dict) -> str:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    return handle.name


def _deals(config_payload: str, rates: list[dict]):
    """The deals for one synthetic run, with the given evidence loaded."""
    config = load_holiday_config(config_payload)
    loaded = load_hotel_evidence(
        config,
        path=_write({"schema": "holiday_hotel_evidence/1", "rates": rates}),
        now=NOW,
    )
    consume_hotel_skip_log()
    deals = collect_holiday_deals(
        config,
        max_budget_gbp=float(config.max_budget_gbp),
        hotel_evidence=loaded,
    )
    consume_hotel_skip_log()
    return config, loaded, deals


def _deal(deals, name: str):
    for deal in deals:
        if deal.resort_name == name:
            return deal
    raise AssertionError(f"no card for {name}: {[d.resort_name for d in deals]}")


def _card_html(config, deals) -> str:
    return render_holiday_report_compact(config, generated_at=NOW, deals=deals)


class TestAReadOutsideTheWindowIsStillEvidence(unittest.TestCase):
    """§1: a 20–27 Jul read prices a 28 Jun – 12 Jul card, as an estimate."""

    def setUp(self):
        self.config, self.loaded, self.deals = _deals(
            OFF_WINDOW_CONFIG, [_garrya_read()])
        self.deal = _deal(self.deals, GARRYA)

    def test_the_read_is_loaded_rather_than_dropped(self):
        self.assertEqual(len(self.loaded), 1)
        entry = next(iter(self.loaded.values()))
        self.assertEqual((entry.check_in, entry.check_out),
                         ("2027-07-20", "2027-07-27"))

    def test_the_loaded_entry_is_marked_as_not_a_pair_this_run_prices(self):
        entry = next(iter(self.loaded.values()))
        self.assertFalse(entry.pair_is_priceable)

    def test_it_is_never_an_exact_date_price_for_its_own_dates(self):
        # This run does not offer 20–27 Jul, so "the rate for these dates" can
        # never be it. The entry is reachable, the exact-date lookup is not.
        self.assertIsNone(
            hotel_rate_for(self.loaded, GARRYA, "2027-07-20", "2027-07-27"))
        self.assertIsNone(self.deal.hotel_evidence)
        self.assertNotEqual(self.deal.hotel_rate_basis, "exact-date-rate")

    def test_the_nearest_read_lookup_offers_it(self):
        near = hotel_rates_near(self.loaded, GARRYA, "2027-06-28", "2027-07-12",
                                booking_shape="two_rooms_one_booking")
        self.assertEqual([entry.check_in for entry in near], ["2027-07-20"])

    def test_the_card_is_built_on_the_window_it_prices(self):
        self.assertEqual((self.deal.outbound_date, self.deal.return_date),
                         ("2027-06-28", "2027-07-12"))
        self.assertEqual(self.deal.nights, 14)

    def test_the_stay_is_the_read_nightly_for_the_card_nights(self):
        self.assertAlmostEqual(self.deal.hotel_price_total_gbp,
                               (4589.98 / 7) * 14, places=2)

    def test_the_stay_is_not_the_catalogue_nightly(self):
        catalogue = hol.SUITE_ARCHITECTURE[GARRYA]["suite_nightly_gbp"]
        self.assertAlmostEqual(catalogue, float(NO_READ_CONTROL), places=2)
        self.assertNotAlmostEqual(self.deal.hotel_price_total_gbp,
                                  catalogue * self.deal.nights, places=2)

    def test_the_card_names_the_read_it_came_from(self):
        self.assertEqual(self.deal.hotel_rate_basis, "read-rate-estimate")
        self.assertEqual(tuple(self.deal.hotel_rate_read_dates),
                         ("2027-07-20", "2027-07-27"))
        self.assertIn("estimate from a read rate for 20–27 Jul",
                      board_line(self.deal, travellers=5))

    def test_the_footer_names_the_read_the_stay_came_from(self):
        footer = hol.prices_checked_footer(self.deal, generated_at=NOW)
        self.assertIn("hotel rate estimate from a read for 2027-07-20 to 2027-07-27",
                      footer)
        self.assertNotIn("hotel rate read for these dates", footer)

    def test_no_skip_is_logged_for_a_read_that_was_kept(self):
        # The skip log is the operator's list of what the loader REFUSED. A read
        # that is kept and labelled is not on it, or the log stops meaning what
        # it says.
        config = load_holiday_config(OFF_WINDOW_CONFIG)
        load_hotel_evidence(
            config,
            path=_write({"schema": "holiday_hotel_evidence/1",
                         "rates": [_garrya_read()]}),
            now=NOW,
        )
        skipped = consume_hotel_skip_log()
        self.assertEqual([line for line in skipped
                          if "not a pair this run prices" in line], [])


class TestTheOffWindowReadStillFacesEveryOtherGate(unittest.TestCase):
    """§1 is one gate moved, not one gate removed."""

    def _loaded(self, **overrides):
        config = load_holiday_config(OFF_WINDOW_CONFIG)
        loaded = load_hotel_evidence(
            config,
            path=_write({"schema": "holiday_hotel_evidence/1",
                         "rates": [_garrya_read(**overrides)]}),
            now=NOW,
        )
        consume_hotel_skip_log()
        return loaded

    def test_a_wrong_season_is_still_refused(self):
        self.assertEqual(self._loaded(season="winter"), {})

    def test_a_read_that_was_not_for_these_dates_is_still_refused(self):
        self.assertEqual(self._loaded(exact_date_match=False), {})

    def test_another_partys_rate_is_still_refused(self):
        self.assertEqual(self._loaded(party={"adults": 4, "children": 0}), {})

    def test_a_booking_that_is_not_one_booking_is_still_refused(self):
        self.assertEqual(self._loaded(booking_shape="three_rooms"), {})

    def test_a_room_only_rate_is_still_refused(self):
        self.assertEqual(self._loaded(board="RO"), {})

    def test_an_aged_read_is_still_refused(self):
        self.assertEqual(self._loaded(observed_at="2026-09-20T08:10:00+00:00"), {})

    def test_a_rate_with_no_gbp_figure_is_still_refused(self):
        # A EUR total with no conversion is not a GBP price, inside the window
        # or outside it.
        record = _garrya_read()
        record.pop("derived_gbp")
        self.assertEqual(self._loaded(**{"derived_gbp": None}), {})

    def test_a_read_with_no_source_url_is_still_refused(self):
        self.assertEqual(self._loaded(source_url="example.invalid/booking"), {})

    def test_a_priceable_read_is_still_marked_priceable(self):
        entry = next(iter(self._loaded().values()))
        self.assertFalse(entry.pair_is_priceable)
        inside = next(iter(self._loaded(
            check_in="2027-06-28", check_out="2027-07-12", nights=14).values()))
        self.assertTrue(inside.pair_is_priceable)
        self.assertIsNotNone(
            hotel_rate_for(self._loaded(check_in="2027-06-28",
                                        check_out="2027-07-12", nights=14),
                           GARRYA, "2027-06-28", "2027-07-12"))


class TestAnOffWindowReadReachesAResortWithNoCatalogueRate(unittest.TestCase):
    """The case REPLY-H14 §4 named: a read is the only price a resort has."""

    CONFIG = """
{
  "report_title": "A resort priced only by an off-window read",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 12,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-06-28"],
  "return_dates": ["2027-07-12"],
  "destinations": [
    {"key": "lombok", "label": "Lombok", "airports": ["LOP"],
     "flight_hours": 24.0}
  ]
}
"""

    def test_the_resort_makes_no_card_on_the_catalogue_alone(self):
        # NO PRICE, NO CARD: this entry carries a unit and public facts but no
        # nightly at all, so with nothing read there is nothing to price.
        config, _loaded, deals = _deals(self.CONFIG, [])
        self.assertNotIn(LOMBOK_LODGE, [d.resort_name for d in deals])
        self.assertIn(
            (LOMBOK_LODGE, "no rate read for these dates yet; the card appears "
             "once one is read."),
            hol.LAST_FILTERED_OUT)

    def test_the_off_window_read_is_enough_to_price_it(self):
        config, _loaded, deals = _deals(self.CONFIG, [_lombok_lodge_read()])
        deal = _deal(deals, LOMBOK_LODGE)
        self.assertEqual(deal.nights, 14)
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 1718.0 * 14, places=2)
        self.assertEqual(deal.hotel_rate_basis, "read-rate-estimate")

    def test_it_is_still_named_as_an_estimate_and_not_as_a_read_for_these_dates(self):
        config, _loaded, deals = _deals(self.CONFIG, [_lombok_lodge_read()])
        deal = _deal(deals, LOMBOK_LODGE)
        self.assertIsNone(deal.hotel_evidence)
        self.assertIn("estimate from a read rate for 20–27 Jul",
                      board_line(deal, travellers=5))


if __name__ == "__main__":
    unittest.main()
