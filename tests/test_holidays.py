import json
from pathlib import Path
import unittest

from public_flight_search.holidays import load_holiday_config, render_holiday_report
from public_flight_search.config import ConfigError


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
        self.assertIn(">2</strong> room(s)", html)
        self.assertIn("Room occupancy:", html)
        self.assertIn("2 + 1", html)
        self.assertIn("08:00–18:00", html)
        self.assertIn("Package Deal Search Links", html)
        self.assertIn("No live prices collected", html)
        self.assertIn("2030-12-18", html)
        self.assertIn("2030-12-20", html)
        self.assertIn("2031-01-01", html)
        self.assertIn("2031-01-03", html)
        # New format: Top Picks (3 of 4 valid pairs × 6 providers) + Full Matrix (4 valid pairs × 6 providers) = 42
        self.assertEqual(html.count('href="'), 42)

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

    def test_public_december_example_matches_family_requirements(self):
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config.travellers, 5)
        self.assertEqual(config.rooms, (2, 2, 1))
        self.assertEqual(config.departure_window, ("08:00", "18:00"))
        self.assertEqual({item.key for item in config.destinations}, {"antalya", "malta", "cairo"})

    def test_rejects_ai_content_in_holiday_report_title(self):
        for title in [
            "AI Engineering Brief",
            "ai news digest",
            "The Engineering Brief",
            "News Roundup",
        ]:
            with self.assertRaises(ConfigError):
                load_holiday_config(
                    json.dumps(
                        {
                            "report_title": title,
                            "party": {"travellers": 2, "rooms": [2]},
                            "departure_window": ["08:00", "18:00"],
                            "origins": ["AAA"],
                            "outbound_dates": ["2030-12-18"],
                            "return_dates": ["2030-12-28"],
                            "destinations": [
                                {"key": "test", "label": "Test", "airports": ["BBB"]}
                            ],
                        }
                    )
                )

    def test_accepts_valid_holiday_report_title(self):
        config = load_holiday_config(
            json.dumps(
                {
                    "report_title": "Holiday package watch",
                    "party": {"travellers": 2, "rooms": [2]},
                    "departure_window": ["08:00", "18:00"],
                    "origins": ["AAA"],
                    "outbound_dates": ["2030-12-18"],
                    "return_dates": ["2030-12-28"],
                    "destinations": [
                        {"key": "test", "label": "Test", "airports": ["BBB"]}
                    ],
                }
            )
        )
        self.assertEqual(config.report_title, "Holiday package watch")


if __name__ == "__main__":
    unittest.main()
