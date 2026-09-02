import unittest
from datetime import datetime

from public_flight_search.cost_ledger import (
    ItineraryCostLedger,
    AncillaryQuote,
    build_cost_ledger,
    parse_fare_family_baggage,
)


class CostLedgerTests(unittest.TestCase):
    def test_itinerary_cost_ledger_default_initialization(self):
        ledger = ItineraryCostLedger()
        self.assertEqual(ledger.base_airfare, 0.0)
        self.assertEqual(ledger.normalized_flight_cost, 0.0)
        self.assertEqual(ledger.total_ground_cost, 10.0)
        self.assertEqual(ledger.total_all_in_door_to_door, 10.0)
        self.assertTrue(len(ledger.computed_at) > 0)
        # Verify computed_at is valid ISO timestamp
        datetime.fromisoformat(ledger.computed_at)

    def test_itinerary_cost_ledger_to_dict(self):
        ledger = ItineraryCostLedger(
            base_airfare=250.0,
            checked_baggage_cost=40.0,
            seat_selection_cost=15.0,
            payment_fee=5.0,
            london_ground_out_cost=30.0,
            london_ground_in_cost=30.0,
            uae_ground_transfer_cost=20.0,
        )
        d = ledger.to_dict()
        self.assertEqual(d["base_airfare"], 250.0)
        self.assertEqual(d["normalized_flight_cost"], 310.0)
        self.assertEqual(d["total_ground_cost"], 90.0)
        self.assertEqual(d["total_all_in_door_to_door"], 400.0)
        self.assertIn("computed_at", d)

    def test_parse_fare_family_baggage_airlines(self):
        self.assertEqual(parse_fare_family_baggage("Etihad", "Basic"), (0, 45.0, False))
        self.assertEqual(parse_fare_family_baggage("Etihad", "Value"), (25, 0.0, True))
        self.assertEqual(parse_fare_family_baggage("Oman Air", "Super Saver"), (0, 40.0, False))
        self.assertEqual(parse_fare_family_baggage("Air Arabia", "Basic"), (0, 27.0, False))
        self.assertEqual(parse_fare_family_baggage("Pegasus", "Basic"), (0, 35.0, False))
        self.assertEqual(parse_fare_family_baggage("Wizz Air", "Basic"), (0, 45.0, False))
        self.assertEqual(parse_fare_family_baggage("Emirates", "Saver"), (25, 0.0, True))

    def test_build_cost_ledger_calculation(self):
        ledger = build_cost_ledger(
            airfare=300.0,
            fare_family="Basic",
            airline="Etihad",
            traveller_count=2,
            checked_bag_count=1,
            checked_bag_target_kg=20,
            london_ground_out=25.0,
            london_ground_in=25.0,
        )
        self.assertEqual(ledger.checked_baggage_cost, 90.0)
        self.assertEqual(ledger.normalized_flight_cost, 390.0)
        self.assertEqual(ledger.total_ground_cost, 60.0)
        self.assertEqual(ledger.total_all_in_door_to_door, 450.0)


if __name__ == "__main__":
    unittest.main()
