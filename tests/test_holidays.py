import json
import unittest

from public_flight_search.holidays import load_holiday_config, render_holiday_report


class HolidayPlannerTests(unittest.TestCase):
    def test_private_constraints_are_runtime_data_and_party_is_dynamic(self):
        config = load_holiday_config(
            json.dumps(
                {
                    "report_title": "Package watch",
                    "party": {"travellers": 3, "rooms": [2, 1]},
                    "departure_window": ["08:00", "18:00"],
                    "origins": ["AAA"],
                    "outbound_dates": ["2030-12-18", "2030-12-20"],
                    "return_dates": ["2031-01-01", "2031-01-03"],
                    "destinations": [
                        {"key": "sample", "label": "Sample coast", "airports": ["BBB"]}
                    ],
                }
            )
        )
        html = render_holiday_report(config, generated_at="2030-08-01T10:00:00+00:00")
        self.assertIn("3 travellers", html)
        self.assertIn("2 room(s)", html)
        self.assertIn("Package Deal Search Links", html)
        self.assertIn("No live prices collected", html)

    def test_origin_airports_shown_not_destination_airports(self):
        config = load_holiday_config(
            json.dumps(
                {
                    "report_title": "Test",
                    "party": {"travellers": 2, "rooms": [2]},
                    "departure_window": ["06:00", "21:00"],
                    "origins": ["LHR", "LGW"],
                    "outbound_dates": ["2026-12-20"],
                    "return_dates": ["2026-12-28"],
                    "destinations": [
                        {"key": "antalya", "label": "Antalya", "airports": ["AYT"]}
                    ],
                }
            )
        )
        html = render_holiday_report(config, generated_at="2026-08-31T10:00:00+00:00")
        self.assertIn("From: LHR, LGW", html)
        self.assertNotIn("Airports: AYT", html)


if __name__ == "__main__":
    unittest.main()
