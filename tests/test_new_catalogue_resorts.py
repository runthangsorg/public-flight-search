"""The new catalogue resorts form cards when a rate is READ, never before.

Owner brief 2026-10-03 (H6). Seven properties were added so that cards can
form for them once the private engine has rates: four in July (Lombok Lodge,
TUNAK, Kalandara, Anantara Rasananda) and Nungwi's unit corrected to its
four-bedroom Presidential Villa, plus two December units (InterContinental
Muscat on two rooms in one booking, Grand Fiesta Americana's two-bedroom
suite).

The rule that makes this safe: **no price, no card**. A catalogue entry with
no rate must not produce a card priced at zero hotel, and it must not produce
a card priced from a guess either. The brief allows the unit names and public
facts, and nothing else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from public_flight_search.holidays import (
    SUITE_ARCHITECTURE,
    collect_holiday_deals,
    load_holiday_config,
    render_space_note_line,
    resort_catalog,
)
from public_flight_search.hotel_evidence import consume_hotel_skip_log, load_hotel_evidence

NOW = "2026-10-03T12:00:00+00:00"

NEW_SUMMER = (
    "The Lombok Lodge",
    "TUNAK Resort Lombok",
    "Kalandara Resort Lombok",
    "Anantara Rasananda Koh Phangan Villas",
)

CONFIG = """
{
  "report_title": "New catalogue resorts",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 6,
  "max_nights": 10,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "lombok", "label": "Lombok", "airports": ["LOP"], "flight_hours": 24.0},
    {"key": "koh_phangan", "label": "Koh Phangan", "airports": ["USM"], "flight_hours": 14.92},
    {"key": "zanzibar", "label": "Zanzibar", "airports": ["ZNZ"], "flight_hours": 11.67}
  ]
}
"""


def _rate_for(name: str, destination_key: str) -> dict:
    return {
        "property_name": name,
        "destination_key": destination_key,
        "season": "summer",
        "vendor": "Example brand booking engine",
        "check_in": "2027-07-20",
        "check_out": "2027-07-27",
        "nights": 7,
        "party": {"adults": 5, "children": 0},
        "booking_shape": "single_unit",
        "units": [{"name": "TWO BEDROOM VILLA", "guests_stated": "5 guests",
                   "bedrooms_stated": "2 bedrooms"}],
        "rate_name": "FLEXIBLE", "board": "BB",
        "price_basis": "nightly_room_rate", "currency": "GBP", "taxes_included": True,
        "prices_shown": [{"unit": "TWO BEDROOM VILLA", "nightly": 300.00,
                          "provider": "Booking.com"}],
        "terms": [{"unit": "TWO BEDROOM VILLA", "refundable": True,
                   "cancellation": "Free cancellation until 19 Jul 2027",
                   "payment": "Pay at the hotel"}],
        "source_url": "https://example.invalid/booking",
        "observed_at": "2026-10-02T15:02:10+00:00",
        "exact_date_match": True,
        "derived_stay_total": {"value": 2100.00, "currency": "GBP",
                               "how": "nightly x nights"},
    }


def _deals(rates):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
    json.dump({"rates": list(rates)}, handle)
    handle.close()
    config = load_holiday_config(CONFIG)
    loaded = load_hotel_evidence(config, path=handle.name, now=NOW)
    deals = collect_holiday_deals(config, max_budget_gbp=10 ** 9,
                                  hotel_evidence=loaded)
    consume_hotel_skip_log()
    return deals


class NewResortsAreInTheCatalogueTests(unittest.TestCase):
    def setUp(self):
        catalog = resort_catalog(load_holiday_config(CONFIG))
        self.names = {resort["name"]
                      for resorts in catalog.values() for resort in resorts}

    def test_the_four_new_summer_resorts_are_catalogue_entries(self):
        for name in NEW_SUMMER:
            with self.subTest(resort=name):
                self.assertIn(name, self.names)

    def test_each_new_resort_names_the_unit_the_brief_gave(self):
        catalog = resort_catalog(load_holiday_config(CONFIG))
        expected = {
            "The Lombok Lodge": "Two-Bedroom Villa",
            "TUNAK Resort Lombok": "Two-bedroom Cliff Front Private Pool Villa",
            "Kalandara Resort Lombok": "AKASA 2 Bedroom Pool Villa",
            "Anantara Rasananda Koh Phangan Villas": "Two Bedroom Pool Villa",
        }
        for resorts in catalog.values():
            for resort in resorts:
                if resort["name"] in expected:
                    with self.subTest(resort=resort["name"]):
                        self.assertTrue(
                            SUITE_ARCHITECTURE[resort["name"]]["suite_type"]
                            .startswith(expected[resort["name"]]),
                            "the unit name must be the brief's own wording",
                        )

    def test_no_new_resort_carries_a_price(self):
        catalog = resort_catalog(load_holiday_config(CONFIG))
        for resorts in catalog.values():
            for resort in resorts:
                if resort["name"] not in NEW_SUMMER:
                    continue
                with self.subTest(resort=resort["name"]):
                    self.assertNotIn("base_nightly_room_rate_gbp", resort)
                    self.assertNotIn("peak_summer_nightly_room_rate_gbp", resort)
                    self.assertEqual(
                        SUITE_ARCHITECTURE[resort["name"]]["suite_nightly_gbp"], 0.0)

    def test_kalandara_is_all_inclusive_only(self):
        catalog = resort_catalog(load_holiday_config(CONFIG))
        kalandara = [resort for resorts in catalog.values() for resort in resorts
                     if resort["name"] == "Kalandara Resort Lombok"][0]
        self.assertEqual(kalandara["board"], "All Inclusive")

    def test_a_two_bedroom_villa_is_one_unit_not_two_rooms(self):
        for name in NEW_SUMMER:
            if name == "Anantara Rasananda Koh Phangan Villas":
                continue
            with self.subTest(resort=name):
                self.assertEqual(SUITE_ARCHITECTURE[name]["rooms_in_unit"], 1)


class NungwiUnitTests(unittest.TestCase):
    def test_the_unit_is_the_four_bedroom_presidential_villa(self):
        arch = SUITE_ARCHITECTURE["Nungwi Dreams by Mantis"]
        self.assertIn("Presidential Villa", arch["suite_type"])
        self.assertEqual(arch["rooms_in_unit"], 1)

    def test_the_card_flags_that_it_is_more_space_than_five_need(self):
        deals = _deals([_rate_for("Nungwi Dreams by Mantis", "zanzibar")])
        deal = next(deal for deal in deals if deal.resort_name == "Nungwi Dreams by Mantis")
        self.assertIn("4-bedroom villa — more space than 5 need", deal.unit_space_note)

    def test_the_flag_reaches_the_card(self):
        deals = _deals([_rate_for("Nungwi Dreams by Mantis", "zanzibar")])
        deal = next(deal for deal in deals if deal.resort_name == "Nungwi Dreams by Mantis")
        self.assertIn("more space than 5 need", render_space_note_line(deal))

    def test_a_two_bedroom_villa_is_not_flagged_as_too_big(self):
        deals = _deals([_rate_for("The Lombok Lodge", "lombok")])
        deal = next(deal for deal in deals if deal.resort_name == "The Lombok Lodge")
        self.assertEqual(deal.unit_space_note, "")


class NoPriceNoCardTests(unittest.TestCase):
    def test_a_new_resort_makes_no_card_without_a_rate(self):
        deals = _deals([])
        names = {deal.resort_name for deal in deals}
        for name in NEW_SUMMER:
            with self.subTest(resort=name):
                self.assertNotIn(name, names)

    def test_a_new_resort_makes_a_card_once_a_rate_is_read(self):
        deals = _deals([_rate_for("The Lombok Lodge", "lombok")])
        deal = next(deal for deal in deals if deal.resort_name == "The Lombok Lodge")
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 2100.00)
        self.assertEqual(deal.hotel_rate_basis, "exact-date-rate")

    def test_the_card_prices_the_stay_from_the_read_rate_only(self):
        deals = _deals([_rate_for("TUNAK Resort Lombok", "lombok")])
        deal = next(deal for deal in deals if deal.resort_name == "TUNAK Resort Lombok")
        self.assertGreater(deal.hotel_price_total_gbp, 0.0)
        self.assertAlmostEqual(
            deal.total_package_price_gbp,
            deal.flight_price_total_gbp + deal.hotel_price_total_gbp,
            places=2,
        )

    def test_an_all_inclusive_resort_takes_a_qualifying_ai_rate(self):
        deals = _deals([dict(_rate_for("Kalandara Resort Lombok", "lombok"),
                             board="AI", rate_name="ALL INCLUSIVE")])
        names = {deal.resort_name for deal in deals}
        self.assertIn("Kalandara Resort Lombok", names)

    def test_an_all_inclusive_resort_refuses_a_breakfast_only_rate(self):
        # The board rule decides, not the hotel: a BB rate for an AI-only
        # resort is a rate that cannot be had.
        deals = _deals([_rate_for("Kalandara Resort Lombok", "lombok")])
        names = {deal.resort_name for deal in deals}
        self.assertNotIn("Kalandara Resort Lombok", names)


if __name__ == "__main__":
    unittest.main()