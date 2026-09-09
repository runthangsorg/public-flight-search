"""Tests for verified holiday provider entry-point URLs.

Every link this module emits was verified live on 2026-09-07 with a headless
Camoufox browser. The old parametric search-result patterns 404'd
(Jet2/TUI/BA/easyJet canaries) or serve bot-wall stubs (loveholidays,
On the Beach), so these tests pin the verified entry points and forbid
reintroducing unverified deep-link shapes.
"""

import unittest
import json

from public_flight_search.holidays import (
    BA_HOLIDAYS_HUB,
    EASYJET_HOLIDAYS_HUB,
    JET2_HOME,
    LOVEHOLIDAYS_HOME,
    ON_THE_BEACH_HOME,
    TUI_HOLIDAYS_HUB,
    VERIFIED_LINK_BASES,
    _is_verified_link,
    build_booking_com_url,
    build_expedia_url,
    build_google_flights_holiday_url,
    build_google_hotels_url,
    build_loveholidays_url,
    build_on_the_beach_url,
    build_jet2_url,
    build_tui_url,
    build_easyjet_url,
    build_ba_holidays_url,
    build_provider_urls,
    load_holiday_config,
    render_holiday_report,
)


def _kwargs(**overrides):
    base = {
        "destination": "lanzarote",
        "origin_airports": ("LHR",),
        "departure_date": "2026-12-22",
        "return_date": "2026-12-30",
        "adults": 5,
    }
    base.update(overrides)
    return base


class LoveHolidaysTests(unittest.TestCase):
    def test_links_verified_homepage_entry_point(self):
        url = build_loveholidays_url(**_kwargs(), rooms=3)
        self.assertEqual(url, "https://www.loveholidays.com/")


class OnTheBeachTests(unittest.TestCase):
    def test_links_verified_homepage_entry_point(self):
        url = build_on_the_beach_url(**_kwargs())
        self.assertEqual(url, "https://www.onthebeach.co.uk/")


class Jet2Tests(unittest.TestCase):
    def test_links_verified_destination_guides(self):
        cases = {
            "malta": "https://www.jet2holidays.com/destinations/malta",
            "lanzarote": "https://www.jet2holidays.com/destinations/canary-islands/lanzarote",
            "tenerife": "https://www.jet2holidays.com/destinations/canary-islands/tenerife",
            "madeira": "https://www.jet2holidays.com/destinations/portugal/madeira",
            "hurghada": "https://www.jet2holidays.com/destinations/egypt/hurghada",
            "antalya": "https://www.jet2holidays.com/destinations/turkey",
            "taghazout": "https://www.jet2holidays.com/destinations/morocco",
        }
        for dest, expected in cases.items():
            with self.subTest(destination=dest):
                self.assertEqual(build_jet2_url(**_kwargs(destination=dest), rooms=3), expected)

    def test_raises_where_jet2_has_no_product(self):
        # Long-haul (muscat/doha), city-break (cairo) and cape_verde have no
        # Jet2 product: callers must omit the link, never emit a 404.
        for dest in ("cairo", "muscat", "doha", "cape_verde"):
            with self.subTest(destination=dest):
                with self.assertRaises(KeyError):
                    build_jet2_url(**_kwargs(destination=dest), rooms=3)


class TUITests(unittest.TestCase):
    def test_links_verified_holidays_hub(self):
        url = build_tui_url(**_kwargs())
        self.assertEqual(url, "https://www.tui.co.uk/holidays/")


class EasyJetTests(unittest.TestCase):
    def test_links_verified_destination_guides(self):
        cases = {
            "malta": "https://www.easyjet.com/en/holidays/malta",
            "antalya": "https://www.easyjet.com/en/holidays/turkey/antalya",
            "cairo": "https://www.easyjet.com/en/holidays/egypt/cairo",
            "taghazout": "https://www.easyjet.com/en/holidays/morocco/agadir",
            "hurghada": "https://www.easyjet.com/en/holidays/egypt/hurghada",
            "tenerife": "https://www.easyjet.com/en/holidays/spain/tenerife",
            "madeira": "https://www.easyjet.com/en/holidays/portugal/madeira",
            "lanzarote": "https://www.easyjet.com/en/holidays/spain/lanzarote",
            "cape_verde": "https://www.easyjet.com/en/holidays/cape-verde",
        }
        for dest, expected in cases.items():
            with self.subTest(destination=dest):
                self.assertEqual(build_easyjet_url(**_kwargs(destination=dest)), expected)

    def test_canary_paths_have_no_canary_islands_segment(self):
        # Regression: /spain/canary-islands/... 404s ("404 Page" verified live).
        for dest in ("tenerife", "lanzarote"):
            url = build_easyjet_url(**_kwargs(destination=dest))
            self.assertNotIn("canary-islands", url)

    def test_unserved_destinations_fall_back_to_hub(self):
        # easyJet holidays serves neither Oman nor Qatar: hub, never a 404.
        for dest in ("muscat", "doha"):
            self.assertEqual(
                build_easyjet_url(**_kwargs(destination=dest)),
                "https://www.easyjet.com/en/holidays/",
            )


class BAHolidaysTests(unittest.TestCase):
    def test_links_verified_holidays_hub(self):
        url = build_ba_holidays_url(**_kwargs())
        self.assertEqual(
            url, "https://www.britishairways.com/en-gb/flights-and-holidays/holidays"
        )


class BuildProviderUrlsTests(unittest.TestCase):
    def test_returns_only_known_providers(self):
        urls = build_provider_urls(
            destination_key="lanzarote",
            destination_label="Lanzarote",
            origin_airports=("LHR", "LGW"),
            departure_date="2026-12-22",
            return_date="2026-12-30",
            adults=5,
            rooms=3,
        )
        self.assertLessEqual(
            set(urls),
            {"loveholidays", "on_the_beach", "jet2", "tui", "easyjet",
             "ba_holidays", "booking_com", "expedia", "google_hotels",
             "google_flights"},
        )
        self.assertIn("jet2", urls)  # Lanzarote has Jet2 product
        # Dynamic links encode the exact dates + party.
        self.assertIn("2026-12-22", urls["booking_com"])
        self.assertIn("2026-12-30", urls["expedia"])
        self.assertIn("Lanzarote", urls["google_hotels"].replace("+", " ").replace("%2C", ","))
        self.assertTrue(urls["google_flights"].startswith(
            "https://www.google.com/travel/flights/search?tfs="))
        self.assertNotIn("#flt=", urls["google_flights"])
        self.assertNotIn("?q=", urls["google_flights"])

    def test_omits_jet2_where_it_has_no_product(self):
        for dest in ("cairo", "muscat", "doha", "cape_verde"):
            with self.subTest(destination=dest):
                urls = build_provider_urls(
                    destination_key=dest,
                    destination_label=dest.title(),
                    origin_airports=("LHR",),
                    departure_date="2026-12-22",
                    return_date="2026-12-30",
                    adults=5,
                    rooms=3,
                )
                self.assertNotIn("jet2", urls)
                self.assertIn("easyjet", urls)

    def test_unknown_destination_falls_back_to_all_hubs(self):
        urls = build_provider_urls(
            destination_key="somewhere-new",
            destination_label="Somewhere New",
            origin_airports=("LHR",),
            departure_date="2026-12-22",
            return_date="2026-12-30",
            adults=2,
            rooms=1,
        )
        self.assertEqual(
            set(urls),
            {"loveholidays", "on_the_beach", "jet2", "tui", "easyjet",
             "ba_holidays", "booking_com", "expedia", "google_hotels",
             "google_flights"},
        )


class DynamicSearchLinkTests(unittest.TestCase):
    """Parametric hotel/flight links must encode real dates + party."""

    def test_booking_com_encodes_dates_and_party(self):
        url = build_booking_com_url(
            destination="lanzarote", departure_date="2026-12-22",
            return_date="2026-12-30", adults=5, rooms=3,
        )
        self.assertTrue(url.startswith("https://www.booking.com/searchresults.html?"))
        self.assertIn("checkin=2026-12-22", url)
        self.assertIn("checkout=2026-12-30", url)
        self.assertIn("group_adults=5", url)
        self.assertIn("no_rooms=3", url)
        for token in ("None", "null", "{}"):
            self.assertNotIn(token, url)

    def test_expedia_encodes_dates_and_party(self):
        url = build_expedia_url(
            destination="hurghada", departure_date="2026-12-22",
            return_date="2026-12-29", adults=5, rooms=3,
        )
        self.assertTrue(url.startswith("https://www.expedia.co.uk/Hotel-Search?"))
        self.assertIn("startDate=2026-12-22", url)
        self.assertIn("endDate=2026-12-29", url)

    def test_google_hotels_encodes_dates_and_party(self):
        url = build_google_hotels_url(
            destination="malta", departure_date="2026-12-20",
            return_date="2026-12-28", adults=5, rooms=3,
        )
        self.assertTrue(url.startswith("https://www.google.com/travel/hotels?"))
        self.assertIn("2026-12-20", url)
        self.assertIn("2026-12-28", url)

    def test_google_flights_holiday_uses_tfs_format(self):
        url = build_google_flights_holiday_url(
            destination="lanzarote", origin_airports=("LHR", "LGW"),
            departure_date="2026-12-22", return_date="2026-12-30",
            adults=5,
        )
        self.assertTrue(url.startswith(
            "https://www.google.com/travel/flights/search?tfs="))
        self.assertNotIn("#flt=", url)
        self.assertNotIn("?q=", url)


class VerifiedLinkTests(unittest.TestCase):
    """Every emitted link must resolve to a live-verified provider page."""

    def test_all_links_are_in_verified_allowlist(self):
        destinations = [
            "antalya", "malta", "taghazout", "hurghada", "cairo",
            "muscat", "doha", "tenerife", "madeira", "lanzarote", "cape_verde",
        ]
        for dest in destinations:
            urls = build_provider_urls(
                destination_key=dest,
                destination_label=dest.title(),
                origin_airports=("LHR", "LGW", "LTN", "STN"),
                departure_date="2026-12-22",
                return_date="2026-12-29",
                adults=5,
                rooms=3,
            )
            for provider, url in urls.items():
                with self.subTest(destination=dest, provider=provider):
                    self.assertTrue(url.startswith("https://"))
                    # Prefix match: parametric Booking/Expedia/Google URLs
                    # encode dates + party after a verified base.
                    self.assertTrue(
                        _is_verified_link(url),
                        f"{provider} URL has unverified base: {url}",
                    )
                    for token in ("None", "null", "{}", "AYT", "MLA", "CAI"):
                        # Airport codes must never leak into hotel-search URLs
                        # (they belong in Google Flights tfs payloads only).
                        if provider in ("booking_com", "expedia", "google_hotels"):
                            self.assertNotIn(token, url)
                    self.assertNotIn("#flt=", url)
                    if provider == "google_flights":
                        self.assertNotIn("?q=", url)

    def test_allowlist_contains_only_https_bases(self):
        for base in VERIFIED_LINK_BASES:
            self.assertTrue(base.startswith("https://"))


class HolidayReportDateConsistencyTests(unittest.TestCase):
    """Test that the holiday report uses consistent dates."""

    def test_report_preserves_every_return_date_option(self):
        config = load_holiday_config(json.dumps({
            "report_title": "Test",
            "party": {"travellers": 2, "rooms": [2]},
            "departure_window": ["06:00", "21:00"],
            "origins": ["LHR"],
            "outbound_dates": ["2026-12-20"],
            "return_dates": ["2026-12-28", "2026-12-30", "2026-12-31"],
            "destinations": [{"key": "test", "label": "Test", "airports": ["BBB"]}],
        }))
        html = render_holiday_report(config, generated_at="2026-08-31T10:00:00+00:00")
        self.assertIn("2026-12-28", html)
        self.assertIn("2026-12-30", html)
        self.assertIn("2026-12-31", html)

    def test_provider_urls_preserve_every_return_date(self):
        config = load_holiday_config(json.dumps({
            "report_title": "Test",
            "party": {"travellers": 2, "rooms": [2]},
            "departure_window": ["06:00", "21:00"],
            "origins": ["LHR"],
            "outbound_dates": ["2026-12-20"],
            "return_dates": ["2026-12-28", "2026-12-30", "2026-12-31"],
            "destinations": [{"key": "test", "label": "Test", "airports": ["BBB"]}],
        }))
        html = render_holiday_report(config, generated_at="2026-08-31T10:00:00+00:00")
        self.assertIn("2026-12-28", html)
        self.assertIn("2026-12-30", html)
        self.assertIn("2026-12-31", html)
        # Top Picks (3 dates × 4 dynamic date-encoded links) + one package-hub
        # row (6 hubs) = 18 links. Hubs render once to stay under Gmail clips.
        self.assertEqual(html.count('href="'), 18)


if __name__ == "__main__":
    unittest.main()
