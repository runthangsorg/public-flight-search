"""Tests for parametric holiday provider search URLs."""

import unittest
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
        self.assertTrue(url.startswith("https://www.loveholidays.com/search/"))
        self.assertIn("sharm-el-sheikh", url)
        self.assertIn("2030-12-15", url)
        self.assertIn("2030-12-22", url)
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


class OnTheBeachTests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_on_the_beach_url(
            destination="sharm-el-sheikh",
            origin_airports=("LGW",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.onthebeach.co.uk/"))
        self.assertIn("sharm", url.lower())
        self.assertTrue(url.startswith("https://"))


class Jet2Tests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_jet2_url(
            destination="sharm-el-sheikh",
            origin_airports=("MAN",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
            rooms=1,
        )
        self.assertTrue(url.startswith("https://www.jet2holidays.com/"))
        self.assertIn("sharm", url.lower())
        self.assertTrue(url.startswith("https://"))


class TUITests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_tui_url(
            destination="sharm-el-sheikh",
            origin_airports=("LGW",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.tui.co.uk/"))
        self.assertIn("sharm", url.lower())
        self.assertTrue(url.startswith("https://"))


class EasyJetTests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_easyjet_url(
            destination="sharm-el-sheikh",
            origin_airports=("LGW",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.easyjet.com/"))
        self.assertIn("sharm", url.lower())
        self.assertTrue(url.startswith("https://"))


class BAHolidaysTests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_ba_holidays_url(
            destination="sharm-el-sheikh",
            origin_airports=("LHR",),
            departure_date="2030-12-15",
            return_date="2030-12-22",
            adults=2,
        )
        self.assertTrue(url.startswith("https://www.britishairways.com/"))
        self.assertIn("sharm", url.lower())
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
        self.assertFalse(parsed.query == "", f"{provider}: must have query params")
        self.assertNotIn("None", url, f"{provider}: URL must not contain None")
        self.assertNotIn("null", url, f"{provider}: URL must not contain null")
        self.assertNotIn("{}", url, f"{provider}: URL must not contain {{}}")
        params = self._parse_url(url)
        for key, values in params.items():
            for v in values:
                self.assertNotIn("None", v, f"{provider}: param {key} must not be None")

    def test_antalya_ayt_not_used_as_departure(self):
        """AYT is a destination airport, must never appear as departureAirport."""
        urls = build_provider_urls(
            destination_key="antalya",
            destination_label="Antalya",
            origin_airports=("LHR", "LGW", "LTN", "STN"),
            departure_date="2026-12-20",
            return_date="2026-12-28",
            adults=2,
            rooms=1,
        )
        for provider, url in urls.items():
            params = self._parse_url(url)
            dep_key = "departureAirports" if "departureAirports" in params else "departureAirport"
            self.assertIn(dep_key, params, f"{provider}: missing departureAirport param")
            dep_value = params[dep_key][0]
            self.assertNotEqual(dep_value, "AYT", f"{provider}: AYT must NOT be departure airport")
            self.assertIn(dep_value, ["LHR", "LGW", "LTN", "STN"],
                          f"{provider}: departure must be UK origin, got {dep_value}")

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
            dep_key = "departureAirports" if "departureAirports" in params else "departureAirport"
            dep_value = params[dep_key][0]
            self.assertNotEqual(dep_value, "MLA", f"{provider}: MLA must NOT be departure airport")

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
            dep_key = "departureAirports" if "departureAirports" in params else "departureAirport"
            dep_value = params[dep_key][0]
            self.assertNotEqual(dep_value, "CAI", f"{provider}: CAI must NOT be departure airport")

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
            self.assertIn("departureDate", params, f"{provider}: missing departureDate")
            self.assertIn("returnDate", params, f"{provider}: missing returnDate")
            dep = params["departureDate"][0]
            ret = params["returnDate"][0]
            self.assertEqual(dep, "2026-12-20", f"{provider}: wrong departure date")
            self.assertEqual(ret, "2026-12-28", f"{provider}: wrong return date")
            self.assertLess(dep, ret, f"{provider}: departure must be before return")

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
            self.assertIn("destination", params, f"{provider}: missing destination")
            self.assertEqual(params["destination"][0], "antalya",
                           f"{provider}: destination should be antalya")

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

    def test_header_uses_first_return_date_not_last(self):
        """The report header must show return_dates[0], not return_dates[-1]."""
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
        self.assertNotIn("2026-12-31", html)

    def test_provider_urls_use_first_return_date(self):
        """Provider URLs must use return_dates[0], consistent with header."""
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
        self.assertNotIn("2026-12-31", html)


if __name__ == "__main__":
    unittest.main()
