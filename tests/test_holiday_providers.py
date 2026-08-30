"""Tests for parametric holiday provider search URLs."""

import unittest

from public_flight_search.holidays import (
    build_loveholidays_url,
    build_on_the_beach_url,
    build_jet2_url,
    build_tui_url,
    build_easyjet_url,
    build_ba_holidays_url,
    build_provider_urls,
)


class LoveHolidaysTests(unittest.TestCase):
    def test_builds_parametric_search_url(self):
        url = build_loveholidays_url(
            destination="sharm-el-sheikh",
            airports=["LGW", "MAN"],
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
            airports=["LGW", "MAN", "BHX"],
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
            airports=["LGW"],
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
            airports=["MAN"],
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
            airports=["LGW"],
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
            airports=["LGW"],
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
            airports=["LHR"],
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
            airports=["LGW", "MAN"],
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


if __name__ == "__main__":
    unittest.main()
