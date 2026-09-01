"""Tests for parametric holiday provider search URLs."""

import unittest
import json
from urllib.parse import urlparse, parse_qs

from public_flight_search.holidays import (
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


class LoveHolidaysTests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_loveholidays_url(
            destination="sharm-el-sheikh",
            origin_airports=("LGW", "MAN"),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
            rooms=1,
        )
        self.assertTrue(url.startswith("https://www.loveholidays.com/holidays/"))
        self.assertIn("sharm-el-sheikh", url)
        self.assertIn("2030-12-15", url)
        self.assertIn("nights=7", url)  # return - departure = 7 nights
        self.assertIn("rooms=2", url)  # 2 adults in 1 room = "2"
        self.assertTrue(url.startswith("https://"))

    def test_encodes_multiple_airports(self):
        url = build_loveholidays_url(
            destination="malta",
            origin_airports=("LGW", "MAN", "BHX"),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=5,
            rooms=2,
        )
        self.assertIn("LGW", url)
        self.assertIn("MAN", url)
        self.assertIn("BHX", url)
        self.assertIn("rooms=2%2C3", url)  # 5 adults, 2 rooms = "2,3"


class OnTheBeachTests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_on_the_beach_url(
            destination="malta",
            origin_airports=("LGW",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.onthebeach.co.uk/holidays/Malta/"))
        self.assertIn("departure_date=2030-12-15", url)
        self.assertIn("duration=7", url)
        self.assertTrue(url.startswith("https://"))


class Jet2Tests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_jet2_url(
            destination="malta",
            origin_airports=("MAN",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
            rooms=1,
        )
        self.assertTrue(url.startswith("https://www.jet2holidays.com/search-results"))
        self.assertIn("destinations=Malta", url)
        self.assertIn("departureDate=2030-12-15", url)
        self.assertIn("duration=7", url)
        self.assertTrue(url.startswith("https://"))


class TUITests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_tui_url(
            destination="malta",
            origin_airports=("LGW",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.tui.co.uk/holidays/search"))
        self.assertIn("dest=MALTA", url)
        self.assertIn("when=2030-12-15", url)
        self.assertIn("nights=7", url)
        self.assertTrue(url.startswith("https://"))


class EasyJetTests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_easyjet_url(
            destination="malta",
            origin_airports=("LGW",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.easyjet.com/en/holidays/malta"))
        self.assertIn("flightDate=2030-12-15", url)
        self.assertIn("duration=7", url)
        self.assertTrue(url.startswith("https://"))


class BAHolidaysTests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_ba_holidays_url(
            destination="malta",
            origin_airports=("LHR",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.britishairways.com/holidays/malta/search"))
        self.assertIn("departureDate=2030-12-15", url)
        self.assertIn("duration=7", url)
        self.assertTrue(url.startswith("https://"))


class BuildProviderUrlsTests(unittest.TestCase):
    def test_returns_dict_with_all_providers(self):
        urls = build_provider_urls(
            destination_key="sharm-el-sheikh",
            destination_label="Sharm El Sheikh",
            origin_airports=("LGW", "MAN"),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=5,
            rooms=2,
        )
        self.assertIsInstance(urls, dict)
        expected_providers = {
            "loveholidays",
            "on_the_beach",
            "jet2",
            "tui",
            "easyjet",
            "ba_holidays",
        }
        self.assertEqual(set(urls.keys()), expected_providers)
        for provider, url in urls.items():
            self.assertTrue(url.startswith("https://"), f"{provider} URL must be HTTPS: {url}")
            self.assertIn("2030-12-15", url, f"{provider} URL must contain departure date")


class SemanticDeepLinkTests(unittest.TestCase):
    """Layer A + B tests: structural and semantic validation of provider URLs."""

    def _parse_url(self, url: str) -> dict[str, list[str]]:
        """Parse URL query parameters."""
        parsed = urlparse(url)
        return parse_qs(parsed.query)

    def _assert_url_is_structural(self, url: str, provider: str):
        """Layer A: structural validation."""
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https", f"{provider}: must be HTTPS")
        self.assertTrue(parsed.netloc, f"{provider}: must have hostname")
        self.assertFalse(parsed.query == "" or parsed.path == "/", f"{provider}: must have query params or path")
        self.assertNotIn("None", url, f"{provider}: URL must not contain None")
        self.assertNotIn("null", url, f"{provider}: URL must not contain null")
        self.assertNotIn("{}", url, f"{provider}: URL must not contain {{}}")
        params = self._parse_url(url)
        for key, values in params.items():
            for v in values:
                self.assertNotIn("None", v, f"{provider}: param {key} must not be None")

    def _get_departure_param(self, params: dict) -> str | None:
        """Find departure airport param (varies by provider)."""
        for key in ("departureAirports", "departureAirport", "airports", "gateway", "origin"):
            if key in params:
                return params[key][0]
        # OnTheBeach and easyJet don't include departure airport in query
        # They use path-based or handle it differently
        return None

    def _get_departure_date(self, params: dict, provider: str) -> str | None:
        """Find departure date param (varies by provider)."""
        for key in ("departureDate", "departure_date", "when", "flightDate"):
            if key in params:
                return params[key][0]
        return None

    def _get_return_info(self, params: dict, provider: str) -> str | None:
        """Find return date/nights/duration param (varies by provider)."""
        for key in ("returnDate", "nights", "duration", "until"):
            if key in params:
                return params[key][0]
        return None

    def _get_destination(self, params: dict, url: str) -> str | None:
        """Find destination in query params or URL path."""
        if "destination" in params:
            return params["destination"][0]
        if "destinations" in params:
            return params["destinations"][0]
        if "dest" in params:
            return params["dest"][0]
        # Check path for destination
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        for part in path_parts:
            if part.lower() in ("antalya", "malta", "cairo", "turkey", "egypt", "spain"):
                return part
        # OnTheBeach uses "Turkey" for Antalya region
        for part in path_parts:
            if part.lower() in ("turkey", "egypt"):
                return part
        return None

    def test_antalya_ayt_not_used_as_departure(self):
        """AYT is a destination airport, must never appear as departureAirport."""
        origins = ("LHR", "LGW", "LTN", "STN")
        urls = build_provider_urls(
            destination_key="antalya",
            destination_label="Antalya",
            origin_airports=origins,
            departure_date="2026-12-20",
            return_date="2026-12-28",
            adults=2,
            rooms=1,
        )
        for provider, url in urls.items():
            params = self._parse_url(url)
            dep = self._get_departure_param(params)
            if dep is None:
                # Some providers (OnTheBeach, easyJet) don't include departure airport in query
                continue
            dep_airports = dep.split(",") if "," in dep else [dep]
            self.assertNotIn("AYT", dep_airports, f"{provider}: AYT must NOT be departure airport")
            for airport in dep_airports:
                self.assertIn(airport, origins,
                              f"{provider}: departure must be UK origin, got {airport}")

    def test_malta_mla_not_used_as_departure(self):
        """MLA is a destination airport, must never appear as departureAirport."""
        urls = build_provider_urls(
            destination_key="malta",
            destination_label="Malta",
            origin_airports=("LHR", "LGW", "LTN", "STN"),
            departure_date="2026-12-20",
            return_date="2026-12-28",
            adults=2,
            rooms=1,
        )
        for provider, url in urls.items():
            params = self._parse_url(url)
            dep = self._get_departure_param(params)
            if dep is None:
                continue
            self.assertNotEqual(dep, "MLA", f"{provider}: MLA must NOT be departure airport")

    def test_cairo_cai_not_used_as_departure(self):
        """CAI is a destination airport, must never appear as departureAirport."""
        urls = build_provider_urls(
            destination_key="cairo",
            destination_label="Cairo",
            origin_airports=("LHR", "LGW", "LTN", "STN"),
            departure_date="2026-12-20",
            return_date="2026-12-28",
            adults=2,
            rooms=1,
        )
        for provider, url in urls.items():
            params = self._parse_url(url)
            dep = self._get_departure_param(params)
            if dep is None:
                continue
            self.assertNotEqual(dep, "CAI", f"{provider}: CAI must NOT be departure airport")

    def test_dates_match_intent(self):
        """Departure and return dates must match the intent, not be swapped."""
        urls = build_provider_urls(
            destination_key="antalya",
            destination_label="Antalya",
            origin_airports=("LHR",),
            departure_date="2026-12-20",
            return_date="2026-12-28",
            adults=2,
            rooms=1,
        )
        for provider, url in urls.items():
            params = self._parse_url(url)
            dep = self._get_departure_date(params, provider)
            ret = self._get_return_info(params, provider)
            self.assertIsNotNone(dep, f"{provider}: missing departure date")
            self.assertIsNotNone(ret, f"{provider}: missing return info (nights/duration/returnDate)")
            self.assertEqual(dep, "2026-12-20", f"{provider}: wrong departure date")
            # Return info should indicate 8 nights
            self.assertIn("8", ret, f"{provider}: return info should indicate 8 nights")
            # Ensure departure is before return conceptually
            self.assertLess(dep, "2026-12-28", f"{provider}: departure must be before return")

    def test_adults_not_swapped_with_rooms(self):
        """Adults and rooms must not be silently swapped."""
        urls = build_provider_urls(
            destination_key="antalya",
            destination_label="Antalya",
            origin_airports=("LHR",),
            departure_date="2026-12-20",
            return_date="2026-12-28",
            adults=3,
            rooms=2,
        )
        for provider, url in urls.items():
            params = self._parse_url(url)
            if provider == "loveholidays":
                # loveholidays encodes adults in rooms parameter (e.g., rooms=2,1 for 3 adults in 2 rooms)
                self.assertIn("rooms", params, f"{provider}: missing rooms")
                self.assertEqual(params["rooms"][0], "2,1", f"{provider}: rooms should encode 3 adults in 2 rooms")
            else:
                self.assertIn("adults", params, f"{provider}: missing adults")
                self.assertEqual(params["adults"][0], "3", f"{provider}: adults should be 3")
                if "rooms" in params:
                    self.assertEqual(params["rooms"][0], "2", f"{provider}: rooms should be 2")

    def test_destination_matches_intent(self):
        """Destination in URL must match the intended destination."""
        urls = build_provider_urls(
            destination_key="antalya",
            destination_label="Antalya",
            origin_airports=("LHR",),
            departure_date="2026-12-20",
            return_date="2026-12-28",
            adults=2,
            rooms=1,
        )
        for provider, url in urls.items():
            params = self._parse_url(url)
            dest = self._get_destination(params, url)
            self.assertIsNotNone(dest, f"{provider}: missing destination in query or path")
            # OnTheBeach uses "Turkey" for Antalya region; others use "antalya"
            dest_lower = dest.lower()
            self.assertTrue("antalya" in dest_lower or "turkey" in dest_lower,
                           f"{provider}: destination should be antalya/turkey, got {dest}")

    def test_all_urls_structural(self):
        """All generated URLs must pass structural checks."""
        urls = build_provider_urls(
            destination_key="malta",
            destination_label="Malta",
            origin_airports=("LHR", "LGW"),
            departure_date="2026-12-20",
            return_date="2026-12-28",
            adults=2,
            rooms=1,
        )
        for provider, url in urls.items():
            self._assert_url_is_structural(url, provider)


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
        # New format: Top Picks (3 dates × 6 providers) + Full Matrix (3 dates × 6 providers) = 36 links
        self.assertEqual(html.count('href="'), 36)


if __name__ == "__main__":
    unittest.main()
