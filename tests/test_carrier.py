"""Tests for carrier canonicalization."""

import unittest

from public_flight_search.carrier import (
    canonicalize_carrier,
    canonicalize_carrier_string,
    CARRIER_CANONICAL_NAMES,
)


class CanonicalizeCarrierTests(unittest.TestCase):
    def test_known_code(self):
        self.assertEqual(canonicalize_carrier("ey"), "Etihad Airways")

    def test_known_name(self):
        self.assertEqual(canonicalize_carrier("emirates"), "Emirates")

    def test_unknown_passthrough(self):
        result = canonicalize_carrier("RandomAir")
        self.assertEqual(result, "Randomair")

    def test_empty_string(self):
        self.assertEqual(canonicalize_carrier(""), "Unknown airline")

    def test_case_insensitive(self):
        self.assertEqual(canonicalize_carrier("EK"), "Emirates")


class CanonicalizeCarrierStringTests(unittest.TestCase):
    def test_single_carrier(self):
        self.assertEqual(canonicalize_carrier_string("ey"), "Etihad Airways")

    def test_multi_carrier(self):
        result = canonicalize_carrier_string("g9 + w9")
        self.assertIn("Air Arabia", result)
        self.assertIn("Wizz Air UK", result)

    def test_empty(self):
        self.assertEqual(canonicalize_carrier_string(""), "Unknown airline")


class CarrierMapTests(unittest.TestCase):
    def test_all_entries_have_values(self):
        for key, value in CARRIER_CANONICAL_NAMES.items():
            self.assertIsInstance(value, str)
            self.assertTrue(len(value) > 0)


if __name__ == "__main__":
    unittest.main()
