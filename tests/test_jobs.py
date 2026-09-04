import os
from pathlib import Path
import unittest
from unittest.mock import patch

from public_flight_search.jobs import FlightCollectionError, run_flight_digest, run_holiday_planner


class HolidayJobTests(unittest.TestCase):
    def test_provider_count_includes_every_destination_and_date_pair(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text(
            encoding="utf-8"
        )
        with patch.dict(os.environ, {"HOLIDAY_SEARCH_CONFIG_JSON": payload}):
            result = run_holiday_planner(dry_run=True)
        self.assertEqual(result["destination_count"], 11)
        self.assertEqual(result["date_combination_count"], 9)
        self.assertEqual(result["provider_entry_count"], 594)
        self.assertFalse(result["email_sent"])


class FlightJobTests(unittest.TestCase):
    def test_empty_provider_scan_fails_closed_without_email(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "sept_config.json").read_text(
            encoding="utf-8"
        )

        async def empty_scan(_searches):
            return {}

        with patch.dict(os.environ, {"FLIGHT_SEARCH_CONFIG_JSON": payload}), patch(
            "public_flight_search.jobs.search_google_flights", empty_scan
        ):
            with self.assertRaises(FlightCollectionError):
                run_flight_digest(dry_run=False)

    def test_paired_flight_digest_generates_itineraries(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "sept_config.json").read_text(
            encoding="utf-8"
        )
        from public_flight_search.engine import FlightOffer
        from public_flight_search.config import build_search_plan
        from public_flight_search.trip_config import DEFAULT_TRIP_DEFINITIONS

        plan = build_search_plan(DEFAULT_TRIP_DEFINITIONS)
        outbound_key = [p.key for p in plan if "_OUTBOUND_" in p.key][0]
        return_key = [p.key for p in plan if "_RETURN_" in p.key][0]

        async def paired_scan(_searches):
            return {
                outbound_key: [
                    FlightOffer(
                        origin="LHR", destination="MCT", departure="2026-09-15T09:00:00",
                        arrival="2026-09-15T19:00:00", price=350, currency="GBP",
                        stops=0, duration_minutes=420, provider="Google Flights",
                        airline="Oman Air", booking_url="https://google.com/test1",
                        price_per_traveller=350, review_status="results_page_only"
                    )
                ],
                return_key: [
                    FlightOffer(
                        origin="MCT", destination="LHR", departure="2026-09-22T10:00:00",
                        arrival="2026-09-22T18:00:00", price=320, currency="GBP",
                        stops=0, duration_minutes=420, provider="Google Flights",
                        airline="Oman Air", booking_url="https://google.com/test2",
                        price_per_traveller=320, review_status="results_page_only"
                    )
                ]
            }

        with patch.dict(os.environ, {"FLIGHT_SEARCH_CONFIG_JSON": payload}), patch(
            "public_flight_search.jobs.search_google_flights", paired_scan
        ):
            result = run_flight_digest(dry_run=True)
            self.assertEqual(result["itinerary_count"], 1)
            self.assertEqual(result["search_count"], 6)
            self.assertFalse(result["email_sent"])


if __name__ == "__main__":
    unittest.main()
