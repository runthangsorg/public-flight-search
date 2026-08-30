import json
import unittest

from public_flight_search.config import ConfigError, load_flight_config


class FlightConfigTests(unittest.TestCase):
    def test_loads_multiple_generic_searches(self):
        config = load_flight_config(
            json.dumps(
                {
                    "report_title": "Private flight watch",
                    "searches": [
                        {
                            "key": "outbound",
                            "label": "Outbound options",
                            "origins": ["AAA", "AAC"],
                            "destinations": ["BBB"],
                            "dates": ["2030-09-01", "2030-09-02"],
                            "travellers": 1,
                            "departure_window": ["08:00", "18:00"],
                            "max_stops": 1,
                        }
                    ],
                }
            )
        )

        self.assertEqual(config.searches[0].origins, ("AAA", "AAC"))
        self.assertEqual(config.searches[0].departure_window, ("08:00", "18:00"))

    def test_rejects_embedded_email_and_unknown_fields(self):
        with self.assertRaises(ConfigError):
            load_flight_config(
                json.dumps(
                    {
                        "recipient_email": "person@example.test",
                        "searches": [],
                    }
                )
            )

    def test_rejects_invalid_airports_dates_and_oversized_jobs(self):
        bad = {
            "searches": [
                {
                    "key": "bad",
                    "label": "Bad",
                    "origins": ["NOT-AIRPORT"],
                    "destinations": ["BBB"],
                    "dates": ["tomorrow"],
                }
            ]
        }
        with self.assertRaises(ConfigError):
            load_flight_config(json.dumps(bad))


if __name__ == "__main__":
    unittest.main()
