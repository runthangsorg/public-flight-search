import unittest

from public_flight_search.config import FlightSearch
from public_flight_search.google_flights import (
    build_google_flights_url,
    _parse_flight_cards,
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
        self.assertTrue(url.startswith("https://www.google.com/travel/flights?"))
        self.assertIn("q=", url)
        self.assertIn("curr=GBP", url)
        self.assertNotIn(" ", url)

    def test_url_contains_origin_and_destination(self):
        url = build_google_flights_url(
            origin="LGW",
            destination="DXB",
            date="2030-12-25",
            travellers=1,
            cabin_class="ECONOMY",
        )
        self.assertIn("LGW", url)
        self.assertIn("DXB", url)
        self.assertIn("2030-12-25", url)

    def test_one_way_in_query(self):
        url = build_google_flights_url(
            origin="LHR",
            destination="MCT",
            date="2030-09-01",
            travellers=1,
            cabin_class="ECONOMY",
        )
        self.assertIn("one", url)
        self.assertIn("way", url)


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
        self.assertEqual(offer.price, 300)
        self.assertEqual(offer.price_per_traveller, 150)
        self.assertEqual(offer.stops, 0)
        self.assertEqual(offer.airline, "Oman Air")
        self.assertEqual(offer.origin, "LHR")
        self.assertEqual(offer.destination, "MCT")
        self.assertEqual(offer.review_status, "results_page_only")

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
        search = self._make_search(max_price_per_traveller_gbp=200)
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


if __name__ == "__main__":
    unittest.main()
