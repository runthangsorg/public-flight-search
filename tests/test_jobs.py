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
        self.assertEqual(result["destination_count"], 3)
        self.assertEqual(result["date_combination_count"], 9)
        self.assertEqual(result["provider_entry_count"], 162)
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


if __name__ == "__main__":
    unittest.main()
