import json
from pathlib import Path
import unittest

from public_flight_search.holidays import collect_holiday_deals, load_holiday_config, render_holiday_report
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
        # Top Picks (3 pairs × 4 dynamic date-encoded links) + one package-hub
        # row (6 hubs) = 18. Hubs render once to stay under Gmail clip limits.
        self.assertEqual(html.count('href="'), 18)

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
        self.assertEqual(
            {item.key for item in config.destinations},
            {
                "antalya",
                "malta",
                "taghazout",
                "hurghada",
                "cairo",
                "muscat",
                "doha",
                "tenerife",
                "madeira",
                "lanzarote",
                "cape_verde",
            },
        )

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
    def test_collect_holiday_deals_filters_under_5k(self):
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        self.assertGreaterEqual(len(deals), 4)
        for deal in deals:
            self.assertLessEqual(deal.total_package_price_gbp, 5000.0)
            self.assertTrue(deal.is_under_budget)
            self.assertGreater(deal.price_per_person_gbp, 100.0)
            self.assertTrue(deal.flight_booking_url.startswith("https://www.google.com/travel/flights/search?tfs="))
            self.assertNotIn("#flt=", deal.flight_booking_url)
            self.assertTrue(deal.hotel_booking_url.startswith("https://"))

    def test_render_holiday_report_with_deals(self):
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        html = render_holiday_report(config, generated_at="2026-09-06T12:00:00+00:00", deals=deals)
        self.assertIn("December Deals — One Family Unit, Real Discounts vs Summer Peak", html)
        self.assertIn("vs summer peak", html)
        self.assertIn("save £", html)
        self.assertIn("Lara Barut Collection", html)
        self.assertIn("Biggest Discount vs Summer Peak", html)
        self.assertIn("Top Luxury Within", html)
        self.assertIn("Best Winter Facilities", html)
        # Property-targeted deep links with exact dates + party, ONE unit.
        self.assertIn("Book this hotel, your dates", html)
        self.assertIn("Compare all vendors", html)
        self.assertIn("ss=Lara+Barut+Collection+Antalya", html)
        self.assertIn("no_rooms=1", html)
        # Strict-mode transparency: removed resorts are listed with reasons.
        self.assertIn("Strict filters applied", html)
        self.assertIn("Jaz Aquaviva", html)
        self.assertIn("ONE family unit", html)
        # Verify compact size: guaranteed < 70 KB so Gmail (102 KB clip limit)
        # will never clip it. Budget raised from 45 KB to cover date-encoded
        # Booking.com / Expedia / Google Hotels buttons on every deal.
        self.assertLess(len(html.encode("utf-8")), 70_000)

    def test_bucket_deals_assigns_three_ranked_buckets(self):
        from public_flight_search.holidays import bucket_deals
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        buckets = bucket_deals(deals)
        self.assertEqual(set(buckets), {"discounts", "luxury", "winter"})
        # Discounts: REAL discount lens — biggest % below the same resort's
        # summer-peak price first (ties broken by cheapest absolute total).
        keys = [(-d.vs_peak_pct, d.total_package_price_gbp) for d in buckets["discounts"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(buckets["discounts"]), len(deals))
        # Every deal carries a real discount baseline + property deep links.
        for deal in deals:
            self.assertGreater(deal.peak_summer_total_gbp, deal.total_package_price_gbp)
            self.assertGreater(deal.vs_peak_pct, 0)
            self.assertIn("q=", deal.compare_url)
            self.assertIn("ss=", deal.booking_deep_url)
        # Luxury: 5-star only.
        self.assertTrue(all(d.star_rating >= 5 for d in buckets["luxury"]))
        self.assertGreaterEqual(len(buckets["luxury"]), 4)
        # Winter: warmest ambient air first; cold heated-pool traps sink.
        ambients = [d.dec_ambient_c[0] for d in buckets["winter"]]
        self.assertEqual(ambients, sorted(ambients, reverse=True))
        self.assertGreaterEqual(buckets["winter"][0].dec_ambient_c[0], 20)
        # Every bucket entry clears the budget on both measures.
        for bucket in buckets.values():
            for deal in bucket:
                self.assertLessEqual(deal.total_package_price_gbp, 5000.0)
                self.assertLessEqual(deal.true_d2d_gbp, 5000.0)

    def test_strict_filters_drop_non_conforming_resorts(self):
        """User strict mandate: city stays and resorts without a verified
        one-unit room sleeping 5, walkable beach, heated ≥28°C pools and
        TripAdvisor ≥4.5 are filtered out with an explicit reason."""
        from public_flight_search.holidays import collect_holiday_deals
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        names = {d.resort_name for d in deals}
        # Cairo trio is a city break — no walkable private beach → excluded.
        self.assertNotIn("Kempinski Nile Hotel Cairo", names)
        self.assertNotIn("Marriott Mena House", names)
        self.assertNotIn("JW Marriott Hotel Cairo", names)
        # User exclusions honoured.
        self.assertNotIn("Jaz Aquaviva", names)
        self.assertNotIn("Jungle Aqua Park", names)
        # Every survivor has verified one-unit architecture facts.
        from public_flight_search import holidays as hol
        for deal in deals:
            self.assertIn(deal.resort_name, hol.SUITE_ARCHITECTURE)
            arch = hol.SUITE_ARCHITECTURE[deal.resort_name]
            self.assertTrue(arch["beach_walkable"])
            self.assertGreaterEqual(arch["pool_heated_c"], 28)
            self.assertGreaterEqual(arch["tripadvisor"], 4.5)
            self.assertLessEqual(deal.total_package_price_gbp, 5000.0)


if __name__ == "__main__":
    unittest.main()
