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
        self.assertIn("2 + 1", html)
        self.assertIn("Official search entry points", html)
        self.assertIn("No live package price was collected", html)


if __name__ == "__main__":
    unittest.main()
