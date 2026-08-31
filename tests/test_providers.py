"""Tests for provider URL builders."""

import unittest

from public_flight_search.providers import (
    build_all_provider_urls,
    _build_kayak_url,
    _build_skyscanner_url,
    _build_trip_com_url,
    _build_momondo_url,
    _build_gotogate_url,
    _build_airline_direct_url,
    ACTIVE_PROVIDER_COVERAGE,
    render_provider_coverage_notice,
)


class KayakURLTests(unittest.TestCase):
    def test_roundtrip(self):
        url = _build_kayak_url(
            out_orig="LHR", out_dest="MCT", out_date="2026-09-16",
            ret_orig="DXB", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertIn("kayak.co.uk", url)
        self.assertIn("LHR-MCT", url)
        self.assertIn("2026-09-16", url)

    def test_open_jaw(self):
        url = _build_kayak_url(
            out_orig="LHR", out_dest="MCT", out_date="2026-09-16",
            ret_orig="AUH", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertIn("AUH-LHR", url)


class SkyscannerURLTests(unittest.TestCase):
    def test_date_format(self):
        url = _build_skyscanner_url(
            out_orig="LHR", out_dest="MCT", out_date="2026-09-16",
            ret_orig="DXB", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertIn("skyscanner.net", url)
        self.assertIn("260916", url)
        self.assertIn("260927", url)


class TripComURLTests(unittest.TestCase):
    def test_roundtrip(self):
        url = _build_trip_com_url(
            out_orig="LHR", out_dest="DXB", out_date="2026-09-16",
            ret_orig="DXB", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertIn("trip.com", url)
        self.assertIn("flighttype=rt", url)

    def test_open_jaw(self):
        url = _build_trip_com_url(
            out_orig="LHR", out_dest="MCT", out_date="2026-09-16",
            ret_orig="AUH", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertIn("flighttype=mt", url)


class MomondoURLTests(unittest.TestCase):
    def test_roundtrip(self):
        url = _build_momondo_url(
            out_orig="LHR", out_dest="MCT", out_date="2026-09-16",
            ret_orig="DXB", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertIn("momondo.co.uk", url)


class GoToGateURLTests(unittest.TestCase):
    def test_url_structure(self):
        url = _build_gotogate_url(
            out_orig="lhr", out_dest="mct", out_date="2026-09-16",
            ret_orig="dxb", ret_dest="lhr", ret_date="2026-09-27",
        )
        self.assertIn("gotogate.co.uk", url)
        self.assertIn("LHR-MCT", url.upper())


class AirlineDirectTests(unittest.TestCase):
    def test_etihad(self):
        url, name = _build_airline_direct_url(
            "Etihad", orig="LHR", dest="MCT", dep_date="2026-09-16",
        )
        self.assertIn("etihad.com", url)
        self.assertEqual(name, "Etihad Airways")

    def test_emirates(self):
        url, name = _build_airline_direct_url(
            "EK", orig="LHR", dest="DXB", dep_date="2026-09-16",
        )
        self.assertIn("emirates.com", url)
        self.assertEqual(name, "Emirates")

    def test_unknown_carrier_fallback(self):
        url, name = _build_airline_direct_url(
            "UnknownAirline", orig="LHR", dest="MCT", dep_date="2026-09-16",
        )
        self.assertIn("google.com", url)


class BuildAllProviderURLsTests(unittest.TestCase):
    def test_returns_all_providers(self):
        urls = build_all_provider_urls(
            out_orig="LHR", out_dest="MCT", out_date="2026-09-16",
            ret_orig="DXB", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertIn("google", urls.google)
        self.assertIn("kayak", urls.kayak)
        self.assertIn("skyscanner", urls.skyscanner)
        self.assertIn("trip.com", urls.trip_com)
        self.assertIn("momondo", urls.momondo)
        self.assertIn("gotogate", urls.gotogate)

    def test_roundtrip_detection(self):
        urls = build_all_provider_urls(
            out_orig="LHR", out_dest="DXB", out_date="2026-09-16",
            ret_orig="DXB", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertTrue(urls.is_roundtrip)

    def test_open_jaw_detection(self):
        urls = build_all_provider_urls(
            out_orig="LHR", out_dest="MCT", out_date="2026-09-16",
            ret_orig="AUH", ret_dest="LHR", ret_date="2026-09-27",
        )
        self.assertFalse(urls.is_roundtrip)


class ProviderCoverageTests(unittest.TestCase):
    def test_coverage_has_all_categories(self):
        self.assertIn("live_priced_results", ACTIVE_PROVIDER_COVERAGE)
        self.assertIn("manual_discovery_links", ACTIVE_PROVIDER_COVERAGE)
        self.assertIn("not_live", ACTIVE_PROVIDER_COVERAGE)

    def test_notice_renders(self):
        notice = render_provider_coverage_notice()
        self.assertIn("Provider coverage", notice)
        self.assertIn("Google Flights", notice)
        self.assertIn("Kayak", notice)


if __name__ == "__main__":
    unittest.main()
