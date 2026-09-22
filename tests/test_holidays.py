import json
from pathlib import Path
import unittest

import public_flight_search.holidays as hol
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
                "fuerteventura",
                "gran_canaria",
                "paphos",
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
        self.assertIn("ONE booking", html)
        # Vidamar (2× connecting-rooms fallback, no sand beach) is dropped by
        # the walkable-beach non-negotiable and shown in the transparency list.
        self.assertIn("Vidamar Resort Madeira", html)
        self.assertIn("no genuine walkable private beach", html)
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
        self.assertEqual(set(buckets), {"discounts", "luxury", "winter", "value"})
        # Discounts: WEATHER-WEIGHTED discount lens (2026-09-22 mandate) —
        # below the 20°C December floor the discount de-weights to half, so
        # warm Red Sea/Canary destinations outrank a colder resort's bigger
        # raw discount; ties break on value score, then cheapest total.
        from public_flight_search.holidays import weather_weighted_discount_pct
        keys = [(weather_weighted_discount_pct(d), -d.value_score, d.total_package_price_gbp) for d in buckets["discounts"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(buckets["discounts"]), len(deals))
        # Value lens: composite winter-first score, highest first.
        values = [d.value_score for d in buckets["value"]]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(len(buckets["value"]), len(deals))
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

    def test_discount_ties_break_on_value_score(self):
        """Equal-% discount: the miserable-winter property must not outrank
        a genuine-winter-sun property just because it was listed first."""
        from public_flight_search.holidays import bucket_deals
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = list(collect_holiday_deals(config, max_budget_gbp=5000.0))
        if len(deals) < 2:
            self.skipTest("need at least two deals")
        a, b = deals[0], deals[1]
        # Force an equal discount % with different value scores.
        object.__setattr__(a, "peak_summer_total_gbp", a.total_package_price_gbp / 0.8)
        object.__setattr__(b, "peak_summer_total_gbp", b.total_package_price_gbp / 0.8)
        high, low = (a, b) if a.value_score >= b.value_score else (b, a)
        buckets = bucket_deals([a, b])
        self.assertIs(buckets["discounts"][0], high)

    def test_collect_stamps_value_rank(self):
        """rank_value is 1..N over the value score with no ties."""
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        self.assertTrue(deals)
        ranks = sorted(d.rank_value for d in deals)
        self.assertEqual(ranks, list(range(1, len(deals) + 1)))
        best = max(deals, key=lambda d: d.value_score)
        self.assertEqual(best.rank_value, 1)

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

    def test_cabin_class_and_budget_support(self):
        root = Path(__file__).parents[1]
        july_path = root / "examples" / "july_holiday_config.json"
        self.assertTrue(july_path.exists())
        config = load_holiday_config(july_path.read_text(encoding="utf-8"))
        self.assertEqual(config.cabin_class, "BUSINESS")
        self.assertEqual(config.max_budget_gbp, 12000.0)
        self.assertEqual(config.travellers, 5)

        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        for deal in deals:
            self.assertIn(deal.cabin_class, {"BUSINESS", "PREMIUM_ECONOMY"})
            self.assertLessEqual(deal.total_package_price_gbp, 12000.0)

        html = render_holiday_report(config, generated_at="2026-07-01T10:00:00+00:00", deals=deals)
        self.assertIn("Business Class", html)

    def test_invalid_cabin_class_rejected(self):
        payload = {
            "report_title": "Test",
            "party": {"travellers": 2, "rooms": [2]},
            "departure_window": ["06:00", "21:00"],
            "origins": ["LHR"],
            "outbound_dates": ["2026-12-20"],
            "return_dates": ["2026-12-28"],
            "cabin_class": "INVALID_CABIN",
            "destinations": [{"key": "antalya", "label": "Antalya", "airports": ["AYT"]}],
        }
        with self.assertRaises(ConfigError):
            load_holiday_config(json.dumps(payload))

    def test_business_cabin_never_names_lcc_carriers(self):
        """Luxury regression: a BUSINESS card must name a carrier that sells
        business — never SunExpress/Ryanair/easyJet/Jet2 (economy-only)."""
        from public_flight_search import holidays as hol

        root = Path(__file__).parents[1]
        july_path = root / "examples" / "july_holiday_config.json"
        config = load_holiday_config(july_path.read_text(encoding="utf-8"))
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        lcc_markers = ("sunexpress", "pegasus", "ryanair", "easyjet", "jet2", "wizz")
        for deal in deals:
            if deal.cabin_class in ("BUSINESS", "FIRST", "PREMIUM_ECONOMY"):
                lowered = deal.airline.lower()
                for marker in lcc_markers:
                    self.assertNotIn(
                        marker, lowered,
                        f"{deal.resort_name} {deal.cabin_class} names LCC: {deal.airline}",
                    )
                # Same-cabin peak: business Dec total compares to business peak.
                self.assertGreater(
                    deal.peak_summer_total_gbp, deal.total_package_price_gbp,
                    f"{deal.resort_name} peak should exceed December in the same cabin",
                )
        # Spot-check the cabin_carrier helper directly.
        self.assertIn("Turkish", hol.cabin_carrier(airport="AYT", cabin="BUSINESS", economy_carrier="SunExpress / Pegasus"))
        self.assertIn("Club Europe", hol.cabin_carrier(airport="PFO", cabin="BUSINESS", economy_carrier="Ryanair / Jet2 / BA"))
        self.assertEqual(
            hol.cabin_carrier(airport="AYT", cabin="ECONOMY", economy_carrier="SunExpress / Pegasus"),
            "SunExpress / Pegasus",
        )


class EmailPresentationTests(unittest.TestCase):
    """The reader-facing fixes of 2026-09-22: distinct real images, no dead
    resort links, and a change digest that stays a strip instead of a wall."""

    def test_every_catalog_destination_has_distinct_image(self):
        from public_flight_search.holidays import DEST_IMAGES

        dest_keys = set(hol.WINTER_RESORT_CATALOG)
        missing = dest_keys - set(DEST_IMAGES)
        self.assertEqual(missing, set(), f"DEST_IMAGES missing: {sorted(missing)}")
        # Distinctness is the point: the old fallback served one beach photo
        # for 8 of 14 destinations.
        self.assertEqual(len(set(DEST_IMAGES.values())), len(DEST_IMAGES))
        for url in DEST_IMAGES.values():
            self.assertTrue(url.startswith("https://thumb.wikimedia.org/"), url)

    def test_resort_hotel_urls_are_canonical(self):
        for resorts in hol.WINTER_RESORT_CATALOG.values():
            for resort in resorts:
                url = resort.get("hotel_url", "")
                self.assertTrue(url.startswith("https://"), url)
                # Both dead hosts removed after the 2026-09-22 link audit.
                self.assertNotIn("baruthotels.com", url, resort["name"])
                self.assertNotIn("/brands/sheraton-hotels/", url, resort["name"])

    def test_change_digest_pills_are_capped(self):
        from public_flight_search.holiday_history import render_change_digest_html

        digest = {
            "has_prior": True,
            "drops": [
                {"name": f"Drop {i}", "current": 100.0, "prev": 200.0, "delta": -100.0}
                for i in range(9)
            ],
            "rises": [],
            "new": [f"New {i}" for i in range(9)],
            "value_changes": [],
            "unchanged": 0,
        }
        html = render_change_digest_html(digest)
        # 4 drop pills + 4 new pills + collapse line + timestamp.
        self.assertEqual(html.count("cheaper</span>"), 4)
        self.assertEqual(html.count("now under budget</span>"), 4)
        # 9 drops - 4 shown + 9 new - 4 shown = 10 collapsed.
        self.assertIn("+10 more moved", html)

    def test_change_digest_dedupes_resorts_across_cabins(self):
        from public_flight_search.holiday_history import build_change_digest

        trends = [
            {"resort_name": "Concorde", "prior_observations": 1, "prior_last": None, "rank_delta": 2, "current_rank": 1, "prior_rank": 3},
            {"resort_name": "Concorde", "prior_observations": 1, "prior_last": None, "rank_delta": 2, "current_rank": 2, "prior_rank": 4},
            {"resort_name": "Lara", "prior_observations": 3, "prior_last": 2100.0, "current": 1900.0},
            {"resort_name": "Lara", "prior_observations": 3, "prior_last": 2600.0, "current": 2400.0},
        ]
        digest = build_change_digest(trends)
        self.assertEqual(digest["new"], ["Concorde"])
        self.assertEqual(len(digest["drops"]), 1)
        self.assertEqual(digest["drops"][0]["name"], "Lara")
        self.assertEqual(digest["drops"][0]["delta"], -200.0)

    def test_render_history_html_suppresses_first_run_chip(self):
        from public_flight_search.holiday_history import render_history_html

        snippets = render_history_html([{"prior_observations": 0}])
        self.assertEqual(snippets, [""])

    def test_one_card_per_hotel_with_upgrade_addons(self):
        """2026-09-22 mandate: never list the same hotel twice. The cheapest
        cabin is the baseline card; premium cabins appear once inside it as
        optional add-ons with the exact delta."""
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        html = render_holiday_report(config, generated_at="2026-09-22T10:00:00+00:00", deals=deals)
        names = [d.resort_name for d in deals]
        dupes = {n for n in names if names.count(n) > 1}
        self.assertTrue(dupes, "test premise: at least one hotel priced in multiple cabins")
        from html import escape
        for name in dupes:
            # & in names is entity-escaped in HTML. A hotel may be absent
            # from the rendered top-10 (count 0) but must NEVER render twice.
            self.assertLessEqual(html.count(">" + escape(name) + "<"), 1, f"{name} rendered more than once")
        self.assertIn("Optional flight upgrades", html)
        self.assertIn("+£", html)  # exact delta per upgrade
        # Card count == unique hotels rendered (≤10).
        self.assertLessEqual(html.count("Compare all vendors"), 10)

    def test_cards_are_text_only_images_suspended(self):
        """2026-09-22 mandate: image rendering is suspended — no <img> tags
        in deal cards until a per-hotel image source exists."""
        root = Path(__file__).parents[1]
        config = load_holiday_config(
            (root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        )
        deals = collect_holiday_deals(config, max_budget_gbp=5000.0)
        html = render_holiday_report(config, generated_at="2026-09-22T10:00:00+00:00", deals=deals)
        self.assertNotIn("<img", html)

    def test_weather_floor_penalises_cold_beach_destinations(self):
        """2026-09-22 mandate: a 50%% discount is invalid if the weather makes
        a beach holiday impossible. Below 20°C December average the value
        score takes a hard penalty and the discount lens de-weights it."""
        from public_flight_search.holidays import compute_value_score, weather_weighted_discount_pct

        warm = compute_value_score(
            true_pp=500.0, luxury=8, food=8, winter=7, mosque=8, activities=7,
            flight_quality=8, indoor_activity_count=2, heated_indoor_pool=True,
            dec_avg_temp_c=24.0,
        )
        cold = compute_value_score(
            true_pp=500.0, luxury=8, food=8, winter=7, mosque=8, activities=7,
            flight_quality=8, indoor_activity_count=2, heated_indoor_pool=True,
            dec_avg_temp_c=15.0,
        )
        self.assertGreater(warm, cold)
        self.assertGreaterEqual(warm - cold, 7.0)  # 5°C under floor × 1.5
        # At/above the floor: no penalty.
        floor = compute_value_score(
            true_pp=500.0, luxury=8, food=8, winter=7, mosque=8, activities=7,
            flight_quality=8, indoor_activity_count=2, heated_indoor_pool=True,
            dec_avg_temp_c=20.0,
        )
        self.assertEqual(floor, warm)

        class _FakeDeal:
            vs_peak_pct = 52
            dec_ambient_c = (15, 17)
            outbound_date = "2026-12-22"  # winter trip → floor applies

        class _WarmDeal:
            vs_peak_pct = 40
            dec_ambient_c = (24, 26)
            outbound_date = "2026-12-22"

        # Ascending-sort key: the MORE NEGATIVE value ranks first. Cold 52%
        # de-weights to 26 → key −26; warm 40% keeps −40. Warm sorts first.
        self.assertLess(
            weather_weighted_discount_pct(_WarmDeal()),
            weather_weighted_discount_pct(_FakeDeal()),
        )

    def test_weather_floor_skips_summer_trips(self):
        """The December-temperature floor is a WINTER-search rule: a July
        trip to a resort that is 15°C in December is 30°C+ in July and must
        not be penalised."""
        from public_flight_search.holidays import compute_value_score

        july_cold_resort = compute_value_score(
            true_pp=500.0, luxury=8, food=8, winter=7, mosque=8, activities=7,
            flight_quality=8, indoor_activity_count=2, heated_indoor_pool=True,
            dec_avg_temp_c=15.0,
        )
        dec_trip = compute_value_score(
            true_pp=500.0, luxury=8, food=8, winter=7, mosque=8, activities=7,
            flight_quality=8, indoor_activity_count=2, heated_indoor_pool=True,
            dec_avg_temp_c=15.0,
        )
        # Same inputs — but the JULY config's cards are priced on a July
        # departure, so collect() must pass dec_avg_temp_c=None for them.
        root = Path(__file__).parents[1]
        july_config = load_holiday_config(
            (root / "examples" / "july_holiday_config.json").read_text(encoding="utf-8")
        )
        july_deals = collect_holiday_deals(july_config)
        self.assertTrue(july_deals)
        self.assertTrue(all(d.outbound_date[5:7] == "07" for d in july_deals))
        # July deals score as if dec_avg_temp_c=None: an Antalya resort's
        # July value score must equal the unpenalised computation.
        from public_flight_search.holidays import _dec_temp_for_floor
        self.assertIsNone(_dec_temp_for_floor("2027-07-05", 15.0))
        self.assertIsNone(_dec_temp_for_floor("2027-04-10", 15.0))  # summer boundary
        self.assertEqual(_dec_temp_for_floor("2026-12-22", 15.0), 15.0)
        self.assertEqual(_dec_temp_for_floor("2026-11-15", 15.0), 15.0)
        self.assertEqual(_dec_temp_for_floor("2027-03-01", 15.0), 15.0)  # Mar = winter trip


if __name__ == "__main__":
    unittest.main()
