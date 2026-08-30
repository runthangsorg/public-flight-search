"""Tests for Amadeus Flight Offers Search API integration."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from public_flight_search.amadeus import (
    AmadeusClient,
    _parse_iso_duration,
    _extract_baggage,
    _build_airline_name,
    build_google_flights_link,
)


class IsoDurationTests(unittest.TestCase):
    def test_parses_hours_and_minutes(self):
        self.assertEqual(_parse_iso_duration("PT10H30M"), 630)

    def test_parses_hours_only(self):
        self.assertEqual(_parse_iso_duration("PT5H"), 300)

    def test_parses_minutes_only(self):
        self.assertEqual(_parse_iso_duration("PT45M"), 45)

    def test_returns_zero_for_unparseable(self):
        self.assertEqual(_parse_iso_duration(""), 0)
        self.assertEqual(_parse_iso_duration("garbage"), 0)


class BaggageExtractionTests(unittest.TestCase):
    def test_extracts_weight_baggage(self):
        pricing = {
            "fareDetailsBySegment": [
                {"includedCheckedBags": {"weight": 23, "weightUnit": "KG"}}
            ]
        }
        included, weight = _extract_baggage(pricing)
        self.assertTrue(included)
        self.assertEqual(weight, "23kg")

    def test_extracts_quantity_baggage(self):
        pricing = {
            "fareDetailsBySegment": [
                {"includedCheckedBags": {"quantity": 2}}
            ]
        }
        included, weight = _extract_baggage(pricing)
        self.assertTrue(included)
        self.assertEqual(weight, "2 bag(s)")

    def test_returns_hand_only_when_no_bags(self):
        pricing = {"fareDetailsBySegment": [{"includedCheckedBags": {}}]}
        included, weight = _extract_baggage(pricing)
        self.assertFalse(included)
        self.assertEqual(weight, "Hand only")

    def test_handles_empty_pricing_gracefully(self):
        included, weight = _extract_baggage({})
        self.assertFalse(included)
        self.assertIn("Unknown", weight)


class AirlineNameTests(unittest.TestCase):
    def test_known_airline_code(self):
        self.assertEqual(_build_airline_name("BA"), "British Airways")
        self.assertEqual(_build_airline_name("EK"), "Emirates")
        self.assertEqual(_build_airline_name("QR"), "Qatar Airways")

    def test_unknown_code_returns_code(self):
        self.assertEqual(_build_airline_name("XX"), "XX")


class GoogleFlightsLinkTests(unittest.TestCase):
    def test_builds_valid_https_link(self):
        url = build_google_flights_link(
            origin="LHR",
            destination="DXB",
            date="2030-12-15",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.google.com/travel/flights?"))
        self.assertIn("LHR", url)
        self.assertIn("DXB", url)
        self.assertIn("2030-12-15", url)

    def test_encodes_cabin_class(self):
        url = build_google_flights_link(
            origin="LHR",
            destination="DXB",
            date="2030-12-15",
            adults=1,
            cabin="business",
        )
        self.assertIn("business", url.lower())


def _make_token_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"access_token": "fake_token", "expires_in": 3000}
    return mock


class AmadeusClientTests(unittest.TestCase):
    def test_requires_client_id_and_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            client = AmadeusClient()
            self.assertFalse(client.is_configured)

    @patch("public_flight_search.amadeus.stealth_get")
    @patch("public_flight_search.amadeus.stealth_post")
    def test_search_returns_flight_offers(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "1",
                    "price": {"grandTotal": "450.00", "currency": "GBP"},
                    "itineraries": [
                        {
                            "duration": "PT5H30M",
                            "segments": [
                                {
                                    "carrierCode": "BA",
                                    "number": "115",
                                    "departure": {
                                        "iataCode": "LHR",
                                        "at": "2030-12-15T09:00:00",
                                    },
                                    "arrival": {
                                        "iataCode": "DXB",
                                        "at": "2030-12-15T19:30:00",
                                    },
                                }
                            ],
                        }
                    ],
                    "travelerPricings": [
                        {
                            "fareDetailsBySegment": [
                                {
                                    "cabin": "ECONOMY",
                                    "includedCheckedBags": {"weight": 23, "weightUnit": "KG"},
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"AMADEUS_CLIENT_ID": "test_id", "AMADEUS_CLIENT_SECRET": "test_secret"}):
            client = AmadeusClient()
            offers = client.search_flights(
                origin="LHR",
                destination="DXB",
                departure_date="2030-12-15",
                adults=2,
            )

        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer["origin"], "LHR")
        self.assertEqual(offer["destination"], "DXB")
        self.assertEqual(offer["airline"], "British Airways")
        self.assertEqual(offer["airline_code"], "BA")
        self.assertEqual(offer["price"], 450.0)
        self.assertEqual(offer["currency"], "GBP")
        self.assertEqual(offer["stops"], 0)
        self.assertEqual(offer["duration_minutes"], 330)
        self.assertTrue(offer["baggage_included"])
        self.assertEqual(offer["baggage_weight"], "23kg")
        self.assertIn("google.com/travel/flights", offer["booking_url"])
        self.assertEqual(offer["source"], "amadeus")
        self.assertEqual(offer["review_status"], "amadeus_api_result")

    @patch("public_flight_search.amadeus.stealth_get")
    @patch("public_flight_search.amadeus.stealth_post")
    def test_search_handles_api_error(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"AMADEUS_CLIENT_ID": "test_id", "AMADEUS_CLIENT_SECRET": "test_secret"}):
            client = AmadeusClient()
            offers = client.search_flights(
                origin="LHR",
                destination="DXB",
                departure_date="2030-12-15",
                adults=2,
            )

        self.assertEqual(offers, [])

    @patch("public_flight_search.amadeus.stealth_get")
    @patch("public_flight_search.amadeus.stealth_post")
    def test_search_handles_no_results(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"AMADEUS_CLIENT_ID": "test_id", "AMADEUS_CLIENT_SECRET": "test_secret"}):
            client = AmadeusClient()
            offers = client.search_flights(
                origin="LHR",
                destination="DXB",
                departure_date="2030-12-15",
                adults=2,
            )

        self.assertEqual(offers, [])

    @patch("public_flight_search.amadeus.stealth_get")
    @patch("public_flight_search.amadeus.stealth_post")
    def test_search_handles_network_error(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        mock_get.return_value = None

        with patch.dict(os.environ, {"AMADEUS_CLIENT_ID": "test_id", "AMADEUS_CLIENT_SECRET": "test_secret"}):
            client = AmadeusClient()
            offers = client.search_flights(
                origin="LHR",
                destination="DXB",
                departure_date="2030-12-15",
                adults=2,
            )

        self.assertEqual(offers, [])

    def test_search_rejected_without_config(self):
        with patch.dict(os.environ, {}, clear=True):
            client = AmadeusClient()
            offers = client.search_flights(
                origin="LHR",
                destination="DXB",
                departure_date="2030-12-15",
                adults=2,
            )
        self.assertEqual(offers, [])

    @patch("public_flight_search.amadeus.stealth_get")
    @patch("public_flight_search.amadeus.stealth_post")
    def test_multi_stop_offer_parsed(self, mock_post, mock_get):
        mock_post.return_value = _make_token_response()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "2",
                    "price": {"grandTotal": "320.00", "currency": "GBP"},
                    "itineraries": [
                        {
                            "duration": "PT9H15M",
                            "segments": [
                                {
                                    "carrierCode": "TK",
                                    "number": "1972",
                                    "departure": {
                                        "iataCode": "LHR",
                                        "at": "2030-12-15T07:00:00",
                                    },
                                    "arrival": {
                                        "iataCode": "IST",
                                        "at": "2030-12-15T13:00:00",
                                    },
                                },
                                {
                                    "carrierCode": "TK",
                                    "number": "700",
                                    "departure": {
                                        "iataCode": "IST",
                                        "at": "2030-12-15T14:30:00",
                                    },
                                    "arrival": {
                                        "iataCode": "DXB",
                                        "at": "2030-12-15T19:15:00",
                                    },
                                },
                            ],
                        }
                    ],
                    "travelerPricings": [
                        {
                            "fareDetailsBySegment": [
                                {"cabin": "ECONOMY", "includedCheckedBags": {}},
                                {"cabin": "ECONOMY", "includedCheckedBags": {}},
                            ]
                        }
                    ],
                }
            ]
        }
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {"AMADEUS_CLIENT_ID": "test_id", "AMADEUS_CLIENT_SECRET": "test_secret"}):
            client = AmadeusClient()
            offers = client.search_flights(
                origin="LHR",
                destination="DXB",
                departure_date="2030-12-15",
                adults=1,
            )

        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer["stops"], 1)
        self.assertEqual(offer["stop_airports"], ["IST"])
        self.assertEqual(offer["airline"], "Turkish Airlines")

    @patch("public_flight_search.amadeus.stealth_post")
    def test_search_handles_token_failure(self, mock_post):
        mock_post.return_value = None

        with patch.dict(os.environ, {"AMADEUS_CLIENT_ID": "test_id", "AMADEUS_CLIENT_SECRET": "test_secret"}):
            client = AmadeusClient()
            offers = client.search_flights(
                origin="LHR",
                destination="DXB",
                departure_date="2030-12-15",
                adults=2,
            )

        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()
