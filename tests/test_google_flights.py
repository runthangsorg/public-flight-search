import asyncio
import os
from pathlib import Path
import tempfile
import unittest
import base64
import json
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

from public_flight_search.config import FlightSearch
from public_flight_search.google_flights import (
    _is_waf_response,
    build_google_flights_url,
    _parse_flight_cards,
    search_google_flights,
)


class BuildGoogleFlightsUrlTests(unittest.TestCase):
    def test_builds_https_booking_entry_url(self):
        url = build_google_flights_url(
            origin="LHR",
            destination="MCT",
            date="2030-09-01",
            travellers=2,
            cabin_class="ECONOMY",
        )
        self.assertTrue(url.startswith("https://www.google.com/travel/flights/search?tfs="))
        self.assertNotIn("?q=", url)
        self.assertIn("curr=GBP", url)
        self.assertNotIn(" ", url)
        payload = base64.b64decode(unquote(url.split("tfs=", 1)[1].split("&", 1)[0]))
        self.assertIn(b"2030-09-01", payload)
        self.assertIn(b"LHR", payload)
        self.assertIn(b"MCT", payload)

    def test_url_contains_origin_and_destination(self):
        url = build_google_flights_url(
            origin="LGW",
            destination="DXB",
            date="2030-12-25",
            travellers=1,
            cabin_class="ECONOMY",
        )
        payload = base64.b64decode(unquote(url.split("tfs=", 1)[1].split("&", 1)[0]))
        self.assertIn(b"LGW", payload)
        self.assertIn(b"DXB", payload)
        self.assertIn(b"2030-12-25", payload)

    def test_one_way_in_query(self):
        url = build_google_flights_url(
            origin="LHR",
            destination="MCT",
            date="2030-09-01",
            travellers=1,
            cabin_class="ECONOMY",
        )
        self.assertIn("tfs=", url)


class ParseFlightCardsTests(unittest.TestCase):
    def _make_search(self, **overrides) -> FlightSearch:
        defaults = dict(
            key="test",
            label="Test",
            origins=("LHR",),
            destinations=("MCT",),
            dates=("2030-09-01",),
            travellers=2,
            cabin_class="ECONOMY",
            departure_window=("00:00", "23:59"),
            max_stops=3,
            max_duration_minutes=1800,
            max_price_per_traveller_gbp=None,
        )
        defaults.update(overrides)
        return FlightSearch(**defaults)

    def test_parses_current_ds1_structured_payload(self):
        search = self._make_search(travellers=2)
        segment = [None] * 22
        segment[3], segment[6] = "LHR", "MCT"
        flight = [None] * 10
        flight[1], flight[2], flight[3], flight[4], flight[5] = ["Sample Air"], [segment], "LHR", [2030, 9, 1], [8, 15]
        flight[6], flight[7], flight[8], flight[9] = "MCT", [2030, 9, 1], [12, 45], 270
        payload = [None] * 4
        payload[3] = [[[flight, [[None, 246]]]]]
        html = '<script class="ds:1">AF_initDataCallback({data:' + json.dumps(payload) + ',sideChannel:{}});</script>'
        offers = _parse_flight_cards(html, search=search, origin="LHR", destination="MCT", day="2030-09-01", booking_url="https://www.google.com/travel/flights/search?tfs=x")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].review_status, "results_page_structured")
        self.assertEqual(offers[0].price_per_traveller, 123)

    def test_parses_nonstop_flight_card(self):
        html = (
            'aria-label="From 150 British pounds. '
            'Non-stop flight with Oman Air. '
            'Leaves London Heathrow at 08:15, '
            'arrives at Muscat at 16:45. '
            'Total duration 7 hrs 30 mins."'
        )
        search = self._make_search()
        offers = _parse_flight_cards(
            html, search=search, origin="LHR", destination="MCT",
            day="2030-09-01", booking_url="https://example.com",
        )
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer.price, 150)
        self.assertIsNone(offer.price_per_traveller)
        self.assertEqual(offer.stops, 0)
        self.assertEqual(offer.airline, "Oman Air")
        self.assertEqual(offer.origin, "LHR")
        self.assertEqual(offer.destination, "MCT")
        self.assertEqual(offer.review_status, "results_page_only")

    def test_one_traveller_marks_displayed_fare_as_per_traveller(self):
        html = (
            'aria-label="From 150 British pounds. '
            'Non-stop flight with Oman Air. '
            'Leaves London Heathrow at 08:15, '
            'arrives at Muscat at 16:45. '
            'Total duration 7 hrs 30 mins."'
        )
        offers = _parse_flight_cards(
            html,
            search=self._make_search(travellers=1),
            origin="LHR",
            destination="MCT",
            day="2030-09-01",
            booking_url="https://example.com",
        )
        self.assertEqual(offers[0].price, 150)
        self.assertEqual(offers[0].price_per_traveller, 150)

    def test_parses_comma_price_plural_stops_and_hour_only_duration(self):
        html = (
            'aria-label="From 1,234 British pounds. '
            '2 stops flight with Sample Airways. '
            'Leaves London Heathrow at 09:15, '
            'arrives at Muscat at 17:15. '
            'Total duration 8 hrs."'
        )
        offers = _parse_flight_cards(
            html,
            search=self._make_search(max_stops=2),
            origin="LHR",
            destination="MCT",
            day="2030-09-01",
            booking_url="https://example.com",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 1234)
        self.assertEqual(offers[0].stops, 2)
        self.assertEqual(offers[0].duration_minutes, 480)

    def test_overnight_arrival_uses_following_date(self):
        html = (
            'aria-label="From 150 British pounds. '
            'Non-stop flight with Oman Air. '
            'Leaves London Heathrow at 23:30, '
            'arrives at Muscat at 07:00. '
            'Total duration 7 hrs 30 mins."'
        )
        offers = _parse_flight_cards(
            html,
            search=self._make_search(),
            origin="LHR",
            destination="MCT",
            day="2030-09-01",
            booking_url="https://example.com",
        )
        self.assertEqual(offers[0].arrival, "2030-09-02T07:00:00")

    def test_parses_one_stop_flight_card(self):
        html = (
            'aria-label="From 95 British pounds. '
            '1 stop flight with Emirates. '
            'Leaves London Heathrow at 10:30, '
            'arrives at Muscat at 21:00. '
            'Total duration 9 hrs 30 mins."'
        )
        search = self._make_search()
        offers = _parse_flight_cards(
            html, search=search, origin="LHR", destination="MCT",
            day="2030-09-01", booking_url="https://example.com",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].stops, 1)
        self.assertEqual(offers[0].airline, "Emirates")

    def test_filters_by_departure_window(self):
        html = (
            'aria-label="From 100 British pounds. '
            'Non-stop flight with Airline. '
            'Leaves Airport at 06:00, '
            'arrives at Dest at 10:00. '
            'Total duration 4 hrs 0 mins."'
        )
        search = self._make_search(departure_window=("08:00", "20:00"))
        offers = _parse_flight_cards(
            html, search=search, origin="LHR", destination="MCT",
            day="2030-09-01", booking_url="https://example.com",
        )
        self.assertEqual(len(offers), 0)

    def test_filters_by_max_price(self):
        html = (
            'aria-label="From 500 British pounds. '
            'Non-stop flight with Airline. '
            'Leaves Airport at 12:00, '
            'arrives at Dest at 16:00. '
            'Total duration 4 hrs 0 mins."'
        )
        search = self._make_search(
            travellers=1, max_price_per_traveller_gbp=200
        )
        offers = _parse_flight_cards(
            html, search=search, origin="LHR", destination="MCT",
            day="2030-09-01", booking_url="https://example.com",
        )
        self.assertEqual(len(offers), 0)

    def test_filters_by_max_stops(self):
        html = (
            'aria-label="From 80 British pounds. '
            '2 stop flight with Airline. '
            'Leaves Airport at 12:00, '
            'arrives at Dest at 20:00. '
            'Total duration 8 hrs 0 mins."'
        )
        search = self._make_search(max_stops=1)
        offers = _parse_flight_cards(
            html, search=search, origin="LHR", destination="MCT",
            day="2030-09-01", booking_url="https://example.com",
        )
        self.assertEqual(len(offers), 0)

    def test_skips_unreasonably_low_price(self):
        html = (
            'aria-label="From 5 British pounds. '
            'Non-stop flight with Airline. '
            'Leaves Airport at 12:00, '
            'arrives at Dest at 16:00. '
            'Total duration 4 hrs 0 mins."'
        )
        search = self._make_search()
        offers = _parse_flight_cards(
            html, search=search, origin="LHR", destination="MCT",
            day="2030-09-01", booking_url="https://example.com",
        )
        self.assertEqual(len(offers), 0)

    def test_no_aria_labels_returns_empty(self):
        search = self._make_search()
        offers = _parse_flight_cards(
            "<html><body>No flight data</body></html>",
            search=search, origin="LHR", destination="MCT",
            day="2030-09-01", booking_url="https://example.com",
        )
        self.assertEqual(len(offers), 0)


class SearchGoogleFlightsTests(unittest.TestCase):
    @staticmethod
    def _search() -> FlightSearch:
        return FlightSearch(
            key="sample",
            label="Sample",
            origins=("LHR",),
            destinations=("MCT",),
            dates=("2030-09-01", "2030-09-02"),
            travellers=1,
            cabin_class="ECONOMY",
            departure_window=("00:00", "23:59"),
            max_stops=1,
            max_duration_minutes=1440,
            max_price_per_traveller_gbp=None,
        )

    @staticmethod
    def _card() -> str:
        return (
            'aria-label="From 150 British pounds. '
            'Non-stop flight with Oman Air. '
            'Leaves London Heathrow at 08:15, '
            'arrives at Muscat at 16:45. '
            'Total duration 7 hrs 30 mins."'
        )

    def test_normal_page_with_captcha_script_is_not_a_waf_page(self):
        html = '<script src="/recaptcha/api.js"></script><main>Flights</main>'
        self.assertFalse(_is_waf_response(html))

    def test_explicit_challenge_is_a_waf_page(self):
        self.assertTrue(_is_waf_response("Our systems have detected unusual traffic"))

    def test_same_time_on_different_dates_is_not_deduplicated(self):
        environment = {
            "GOOGLE_FLIGHTS_DELAY_SECONDS": "0",
            "GOOGLE_FLIGHTS_MAX_SEARCHES": "10",
            "GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS": "30",
            "FLIGHT_CAPTURE_HTML": "",
        }
        with patch.dict(os.environ, environment), patch(
            "public_flight_search.google_flights._fetch_page_html",
            return_value=self._card(),
        ):
            result = asyncio.run(search_google_flights((self._search(),)))
        self.assertEqual(
            [offer.departure[:10] for offer in result["sample"]],
            ["2030-09-01", "2030-09-02"],
        )

    def test_raw_provider_html_is_not_captured_by_default(self):
        search = self._search()
        environment = {
            "SCREENSHOTS_DIR": "unused",
            "GOOGLE_FLIGHTS_DELAY_SECONDS": "0",
            "GOOGLE_FLIGHTS_MAX_SEARCHES": "1",
            "GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS": "30",
            "FLIGHT_CAPTURE_HTML": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            environment["SCREENSHOTS_DIR"] = directory
            with patch.dict(os.environ, environment), patch(
                "public_flight_search.google_flights._fetch_page_html",
                return_value=self._card(),
            ):
                asyncio.run(search_google_flights((search,)))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
