"""Tests for flight number to airport mapping."""

import unittest

from public_flight_search.flight_numbers import (
    FLIGHT_NUMBER_AIRPORT_MAP,
    map_flight_numbers_to_airports,
    resolve_flight_airports,
)


class FlightNumberMapTests(unittest.TestCase):
    def test_all_entries_valid(self):
        for flt, (orig, dest) in FLIGHT_NUMBER_AIRPORT_MAP.items():
            self.assertGreaterEqual(len(flt), 4, f"Flight number {flt} should be 4-6 chars")
            self.assertEqual(len(orig), 3, f"Origin {orig} should be 3-letter code")
            self.assertEqual(len(dest), 3, f"Destination {dest} should be 3-letter code")

    def test_etihad_e68(self):
        orig, dest = FLIGHT_NUMBER_AIRPORT_MAP["EY68"]
        self.assertEqual(orig, "LHR")
        self.assertEqual(dest, "AUH")

    def test_oman_air_wy102(self):
        orig, dest = FLIGHT_NUMBER_AIRPORT_MAP["WY102"]
        self.assertEqual(orig, "LHR")
        self.assertEqual(dest, "MCT")


class MapFlightNumbersTests(unittest.TestCase):
    def test_known_flight(self):
        orig, dest = map_flight_numbers_to_airports(["EY68"], "LHR", "MCT")
        self.assertEqual(orig, "LHR")
        self.assertEqual(dest, "AUH")

    def test_unknown_flight_falls_back(self):
        orig, dest = map_flight_numbers_to_airports(["XX999"], "LHR", "MCT")
        self.assertEqual(orig, "LHR")
        self.assertEqual(dest, "MCT")

    def test_empty_list(self):
        orig, dest = map_flight_numbers_to_airports([], "LHR", "MCT")
        self.assertEqual(orig, "LHR")
        self.assertEqual(dest, "MCT")


class ResolveFlightAirportsTests(unittest.TestCase):
    def test_no_flight_numbers(self):
        orig, dest = resolve_flight_airports("LHR", "MCT")
        self.assertEqual(orig, "LHR")
        self.assertEqual(dest, "MCT")

    def test_with_flight_numbers(self):
        orig, dest = resolve_flight_airports("LHR", "MCT", ["WY102"])
        self.assertEqual(orig, "LHR")
        self.assertEqual(dest, "MCT")


if __name__ == "__main__":
    unittest.main()
