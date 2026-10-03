"""Exact-date hotel rates on the cards (owner brief 2026-10-03, H3).

A card priced from the resort catalogue says nothing about what the hotel
actually charges for these dates: the catalogue carries either a modelled
benchmark or an estimate from the nearest dates on sale. Where the private
engine has read a real rate for THIS property and THESE dates, that rate must
price the card — and the card must say where the number came from, because an
exact-date rate with no provenance is indistinguishable from a guess.

What these tests pin:

* a qualifying rate replaces the catalogue/nearest-date estimate;
* its provenance is on the card (when it was read, from whom, and that a
  converted figure is a conversion);
* both rates appear when there are two — the flexible one with its
  cancellation date, and the non-refundable one;
* the booking-terms line is filled from the rate's own published terms;
* with no evidence, every card is byte-for-byte what it was.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_booking_terms,
    render_hotel_rate_line,
)
from public_flight_search.hotel_evidence import (
    consume_hotel_skip_log,
    hotel_rate_provenance,
    load_hotel_evidence,
)

RESORT = "Pullman Lombok Merujani Mandalika Beach Resort"

CONFIG = """
{
  "report_title": "Hotel rate on the card",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 6,
  "max_nights": 10,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "lombok", "label": "Lombok", "airports": ["LOP"], "flight_hours": 24.0}
  ]
}
"""

NOW = "2026-10-03T12:00:00+00:00"


def _rate(**overrides) -> dict:
    base = {
        "property_name": RESORT,
        "destination_key": "lombok",
        "season": "summer",
        "vendor": "Example brand booking engine",
        "check_in": "2027-07-20",
        "check_out": "2027-07-27",
        "nights": 7,
        "party": {"adults": 5, "children": 0},
        "booking_shape": "single_unit",
        "board": "BB",
        "price_basis": "total_stay_rate",
        "currency": "GBP",
        "taxes_included": True,
        "source_url": "https://example.invalid/booking?dateIn=2027-07-20",
        "observed_at": "2026-10-02T15:02:10+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    base.update(overrides)
    return base


def _flexible_rate(**overrides) -> dict:
    return _rate(
        rate_name="FLEXIBLE RATE WITH BREAKFAST",
        prices_shown=[{"unit": "TWO BEDROOM VILLA", "public": 2100.00}],
        terms=[{"unit": "TWO BEDROOM VILLA",
                "cancellation": "Free cancellation until 19 Jul 2027",
                "payment": "Pay at the hotel",
                "refundable": True}],
        **overrides,
    )


def _saver_rate(**overrides) -> dict:
    return _rate(
        rate_name="SAVER NON-REFUNDABLE",
        prices_shown=[{"unit": "TWO BEDROOM VILLA", "public": 1750.00}],
        terms=[{"unit": "TWO BEDROOM VILLA",
                "cancellation": "Non-refundable",
                "payment": "Pay online now",
                "refundable": False}],
        **overrides,
    )


def _evidence_file(rates, **extra) -> str:
    payload = {"schema": "holiday_hotel_evidence/1", "rates": list(rates)}
    payload.update(extra)
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    return handle.name


def _deals(*rates, path=None, **extra):
    """Deals for this run, with the given rates loaded as hotel evidence.

    No rates means an empty evidence file, i.e. the no-evidence case every
    other card still runs in.
    """
    config = load_holiday_config(CONFIG)
    if path is None:
        path = _evidence_file(list(rates), **extra)
    loaded = load_hotel_evidence(config, path=path, now=NOW)
    deals = collect_holiday_deals(
        config, max_budget_gbp=10 ** 9, hotel_evidence=loaded)
    consume_hotel_skip_log()
    return deals


def _deal_for(deals, name: str = RESORT):
    for deal in deals:
        if deal.resort_name == name:
            return deal
    raise AssertionError(f"no card for {name}: {[d.resort_name for d in deals]}")


class TestRateReplacesTheEstimate(unittest.TestCase):
    def test_the_read_rate_prices_the_stay(self):
        deals = _deals(_flexible_rate(), _saver_rate())
        deal = _deal_for(deals)
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 1750.00)

    def test_the_package_total_moves_with_the_read_rate(self):
        deals = _deals(_flexible_rate(), _saver_rate())
        deal = _deal_for(deals)
        self.assertAlmostEqual(
            deal.total_package_price_gbp,
            deal.flight_price_total_gbp + deal.hotel_price_total_gbp,
            places=2,
        )

    def test_the_card_records_that_the_rate_was_read_for_these_dates(self):
        deals = _deals(_flexible_rate(), _saver_rate())
        self.assertEqual(_deal_for(deals).hotel_rate_basis, "exact-date-rate")

    def test_without_evidence_the_catalogue_rate_stands(self):
        deals = _deals()
        deal = _deal_for(deals)
        self.assertNotEqual(deal.hotel_rate_basis, "exact-date-rate")
        self.assertEqual(deal.hotel_evidence, None)

    def test_a_rate_for_another_property_prices_nothing(self):
        deals = _deals(_flexible_rate(property_name="Some Other Resort"))
        self.assertEqual(_deal_for(deals).hotel_evidence, None)

    def test_a_rate_for_other_dates_prices_nothing(self):
        deals = _deals(_flexible_rate(check_in="2027-07-19", check_out="2027-07-26"))
        self.assertEqual(_deal_for(deals).hotel_evidence, None)

    def test_the_property_name_is_matched_without_punctuating_it(self):
        # Exporters and catalogues punctuate hotel names differently; a card
        # must not miss its own rate over a full stop.
        deals = _deals(_flexible_rate(property_name="Pullman Lombok, Merujani Mandalika Beach Resort"))
        self.assertIsNotNone(_deal_for(deals).hotel_evidence)


class TestCardShowsTheRate(unittest.TestCase):
    def setUp(self):
        self.deal = _deal_for(_deals(_flexible_rate(), _saver_rate()))

    def test_both_rates_are_shown(self):
        html = render_hotel_rate_line(self.deal)
        self.assertIn("£1,750", html)
        self.assertIn("£2,100", html)

    def test_the_flexible_rate_leads_with_its_cancellation_date(self):
        html = render_hotel_rate_line(self.deal)
        self.assertIn("FLEXIBLE RATE WITH BREAKFAST", html)
        self.assertIn("Free cancellation until 19 Jul 2027", html)

    def test_a_refundable_rate_is_labelled_with_its_own_name(self):
        # "Flexible" is our word; "super advance saver" is the hotel's. A
        # reader searching that name on the hotel's own site needs to find it.
        saver = _rate(
            rate_name="SUPER ADVANCE SAVER",
            prices_shown=[{"unit": "TWO BEDROOM VILLA", "public": 1451.00}],
            terms=[{"unit": "TWO BEDROOM VILLA",
                    "cancellation": "Free cancellation until 21 May 2027",
                    "payment": "Pay at the hotel",
                    "refundable": True}],
        )
        html = render_hotel_rate_line(_deal_for(_deals(saver, _saver_rate())))
        self.assertIn("SUPER ADVANCE SAVER", html)
        self.assertIn("£1,451", html)
        self.assertIn("Free cancellation until 21 May 2027", html)
        self.assertIn("SAVER NON-REFUNDABLE", html)

    def test_both_rates_are_shown_even_when_the_refundable_one_is_cheaper(self):
        saver = _rate(
            rate_name="SUPER ADVANCE SAVER",
            prices_shown=[{"unit": "TWO BEDROOM VILLA", "public": 1451.00}],
            terms=[{"unit": "TWO BEDROOM VILLA",
                    "cancellation": "Free cancellation until 21 May 2027",
                    "payment": "Pay at the hotel",
                    "refundable": True}],
        )
        html = render_hotel_rate_line(_deal_for(_deals(saver, _saver_rate())))
        self.assertIn("£1,451", html)
        self.assertIn("£1,750", html)

    def test_a_rate_with_no_published_name_falls_back_to_the_generic_label(self):
        unnamed = _rate(
            rate_name="",
            prices_shown=[{"unit": "TWO BEDROOM VILLA", "public": 2100.00}],
            terms=[{"unit": "TWO BEDROOM VILLA",
                    "cancellation": "Free cancellation until 19 Jul 2027",
                    "payment": "Pay at the hotel",
                    "refundable": True}],
        )
        html = render_hotel_rate_line(_deal_for(_deals(unnamed)))
        self.assertIn("Flexible", html)

    def test_a_nightly_rate_is_labelled_as_nightly_x_nights(self):
        nightly = _rate(
            price_basis="nightly_room_rate",
            prices_shown=[{"unit": "TWO BEDROOM VILLA", "public": 150.00}],
            terms=[{"unit": "TWO BEDROOM VILLA",
                    "cancellation": "Free cancellation until 19 Jul 2027",
                    "payment": "Pay at the hotel",
                    "refundable": True}],
        )
        deal = _deal_for(_deals(nightly))
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 1050.00)
        html = render_hotel_rate_line(deal)
        self.assertIn("£1,050", html)
        self.assertIn("derived: nightly x 7 nights", html)

    def test_the_non_refundable_rate_is_labelled_as_such(self):
        html = render_hotel_rate_line(self.deal)
        self.assertIn("SAVER NON-REFUNDABLE", html)

    def test_the_provenance_names_the_vendor_and_the_day_it_was_read(self):
        html = render_hotel_rate_line(self.deal)
        self.assertIn("Example brand booking engine", html)
        self.assertIn("2 Oct", html)

    def test_the_source_page_is_linked(self):
        html = render_hotel_rate_line(self.deal)
        self.assertIn("https://example.invalid/booking?dateIn=2027-07-20", html)

    def test_the_line_states_the_dates_the_rate_was_read_for(self):
        html = render_hotel_rate_line(self.deal)
        self.assertIn("2027-07-20", html)
        self.assertIn("2027-07-27", html)

    def test_a_converted_rate_says_it_is_a_conversion(self):
        converted = _rate(
            rate_name="FLEXIBLE RATE WITH BREAKFAST",
            currency="EUR",
            prices_shown=[{"unit": "TWO BEDROOM VILLA", "public": 2500.00}],
            derived_gbp={"value": 2125.00, "how": "ECB EUR/GBP 0.85 (2026-10-01)"},
            terms=[{"unit": "TWO BEDROOM VILLA",
                    "cancellation": "Free cancellation until 19 Jul 2027",
                    "payment": "Pay at the hotel",
                    "refundable": True}],
        )
        deal = _deal_for(_deals(converted))
        html = render_hotel_rate_line(deal)
        self.assertIn("converted", html.lower())
        self.assertIn("not a GBP price", html)

    def test_provenance_is_a_plain_sentence_a_reader_can_check(self):
        text = hotel_rate_provenance(self.deal.hotel_evidence.cheapest)
        self.assertIn("Example brand booking engine", text)
        self.assertIn("2 Oct", text)

    def test_a_card_with_no_rate_renders_no_line_at_all(self):
        deal = _deal_for(_deals())
        self.assertEqual(render_hotel_rate_line(deal), "")

    def test_a_single_flexible_rate_is_shown_once(self):
        deal = _deal_for(_deals(_flexible_rate()))
        html = render_hotel_rate_line(deal)
        self.assertIn("£2,100", html)
        self.assertNotIn("SAVER NON-REFUNDABLE", html)


class TestBookingTermsComeFromTheRate(unittest.TestCase):
    def setUp(self):
        self.deal = _deal_for(_deals(_flexible_rate(), _saver_rate()))

    def test_cancellation_is_filled_from_the_priced_rate(self):
        html = render_booking_terms(self.deal)
        self.assertIn("Non-refundable", html)
        self.assertNotIn("not verified: cancellation", html)

    def test_payment_is_filled_from_the_priced_rate(self):
        html = render_booking_terms(self.deal)
        self.assertIn("Pay online now", html)
        self.assertNotIn("not verified: deposit", html)

    def test_terms_describe_the_rate_the_card_prices(self):
        # The card's stay price is the cheapest rate, so the terms line must
        # not borrow the flexible rate's generous terms.
        self.assertEqual(self.deal.hotel_evidence.cheapest.rate_name,
                         "SAVER NON-REFUNDABLE")
        self.assertEqual(self.deal.free_cancellation_until, "Non-refundable")
        self.assertEqual(self.deal.deposit_payment, "Pay online now")

    def test_a_card_with_no_rate_leaves_the_terms_unknown(self):
        deal = _deal_for(_deals())
        self.assertIsNone(deal.free_cancellation_until)
        self.assertIsNone(deal.deposit_payment)


class TestNoEvidenceIsNoChange(unittest.TestCase):
    def test_a_missing_file_leaves_every_card_as_it_was(self):
        config = load_holiday_config(CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_hotel_evidence(
                config, path=os.path.join(tmp, "absent.json"), now=NOW)
            deals = collect_holiday_deals(
                config, max_budget_gbp=10 ** 9, hotel_evidence=loaded or None)
        deal = _deal_for(deals)
        self.assertEqual(render_hotel_rate_line(deal), "")
        self.assertNotEqual(deal.hotel_rate_basis, "exact-date-rate")

    def test_a_collector_called_without_hotel_evidence_is_unaffected(self):
        config = load_holiday_config(CONFIG)
        deals = collect_holiday_deals(config, max_budget_gbp=10 ** 9)
        deal = _deal_for(deals)
        self.assertEqual(deal.hotel_evidence, None)
        self.assertEqual(render_hotel_rate_line(deal), "")


class TestThePlannerRunReportsIt(unittest.TestCase):
    """A run with the file seeded must say so; a run without must not lie."""

    def test_a_seeded_file_prices_a_card_and_is_reported(self):
        from unittest.mock import patch

        from public_flight_search.jobs import run_holiday_planner

        path = _evidence_file([_flexible_rate(), _saver_rate()])
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": CONFIG,
                "HOLIDAY_HISTORY_PATH": os.path.join(tmp, "h.jsonl"),
                "HOLIDAY_HOTEL_EVIDENCE_PATH": path,
                "HOLIDAY_LIVE_EVIDENCE_PATH": os.path.join(tmp, "absent.json"),
            }
            with patch.dict(os.environ, env):
                result = run_holiday_planner(dry_run=True)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        self.assertTrue(result["hotel_evidence_file_found"])
        self.assertEqual(result["hotel_rate_properties"], 1)
        self.assertGreaterEqual(result["hotel_rates_priced_cards"], 1)
        self.assertIsNone(result["hotel_evidence_load_error"])

    def test_a_run_without_the_file_reports_no_rates_rather_than_failing(self):
        from unittest.mock import patch

        from public_flight_search.jobs import run_holiday_planner

        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": CONFIG,
                "HOLIDAY_HISTORY_PATH": os.path.join(tmp, "h.jsonl"),
                "HOLIDAY_HOTEL_EVIDENCE_PATH": os.path.join(tmp, "absent.json"),
                "HOLIDAY_LIVE_EVIDENCE_PATH": os.path.join(tmp, "absent.json"),
            }
            with patch.dict(os.environ, env):
                result = run_holiday_planner(dry_run=True)
        self.assertFalse(result["hotel_evidence_file_found"])
        self.assertEqual(result["hotel_rates_priced_cards"], 0)
        self.assertIsNone(result["hotel_evidence_load_error"])


class TestAggregatorRowsOnTheCard(unittest.TestCase):
    """Google Hotels rows, where the rate is sold by somebody other than the
    hotel. The card must say whose price it is: an OTA listing is not the
    hotel's own rate, and a reader who assumes it is will find a different
    price on the hotel's site."""

    def _google_rate(self, **overrides) -> dict:
        base = _rate(
            vendor="Google Hotels",
            price_basis="nightly_room_rate",
            prices_shown=[{"unit": "THREE BEDROOM POOL VILLA", "nightly": 210.00,
                           "provider": "Booking.com"}],
            derived_stay_total={"value": 1470.00, "currency": "GBP",
                                "how": "nightly x nights"},
            terms=[{"unit": "THREE BEDROOM POOL VILLA", "refundable": None,
                    "cancellation": None, "payment": None}],
            units=[{"name": "THREE BEDROOM POOL VILLA", "guests_stated": "5 guests",
                    "bedrooms_stated": "3 bedrooms"}],
            taxes_included=None,
        )
        base.update(overrides)
        return base

    def test_the_stay_total_prices_the_card(self):
        deal = _deal_for(_deals(self._google_rate()))
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 1470.00)

    def test_the_card_says_whose_listing_the_price_is(self):
        html = render_hotel_rate_line(_deal_for(_deals(self._google_rate())))
        self.assertIn("via Booking.com", html)
        self.assertIn("an online travel agent listing, not the hotel", html)

    def test_the_card_carries_the_exporter_own_arithmetic(self):
        html = render_hotel_rate_line(_deal_for(_deals(self._google_rate())))
        self.assertIn("nightly x nights", html)

    def test_a_null_refundable_reads_as_not_stated_not_as_refundable(self):
        html = render_hotel_rate_line(_deal_for(_deals(self._google_rate())))
        self.assertIn("cancellation not stated", html)
        self.assertNotIn("Flexible", html)

    def test_the_booking_terms_line_does_not_invent_a_cancellation_policy(self):
        deal = _deal_for(_deals(self._google_rate()))
        self.assertIsNone(deal.free_cancellation_until)
        self.assertIn("not verified: cancellation", render_booking_terms(deal))

    def test_the_unit_is_shown_as_the_hotel_states_it(self):
        html = render_hotel_rate_line(_deal_for(_deals(self._google_rate())))
        self.assertIn("3 bedrooms", html)

    def test_the_hotel_own_site_is_not_called_an_aggregator(self):
        direct = self._google_rate(
            prices_shown=[{"unit": "THREE BEDROOM POOL VILLA", "nightly": 190.00,
                           "provider": "Direct"}],
            terms=[{"unit": "THREE BEDROOM POOL VILLA", "refundable": True,
                    "cancellation": "Free cancellation until 19 Jul 2027",
                    "payment": "Pay at the hotel"}],
        )
        html = render_hotel_rate_line(_deal_for(_deals(direct)))
        self.assertNotIn("online travel agent", html)

    def test_an_unrecognised_provider_is_named_without_a_claim(self):
        odd = self._google_rate(
            prices_shown=[{"unit": "THREE BEDROOM POOL VILLA", "nightly": 180.00,
                           "provider": "Example Aggregator"}],
        )
        html = render_hotel_rate_line(_deal_for(_deals(odd)))
        self.assertIn("Example Aggregator", html)
        self.assertNotIn("not the hotel", html)


if __name__ == "__main__":
    unittest.main()