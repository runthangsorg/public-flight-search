"""Tests for curl_cffi stealth HTTP client."""

import unittest
from unittest.mock import MagicMock, patch

from public_flight_search.stealth import stealth_get, stealth_post


class StealthGetTests(unittest.TestCase):
    @patch("public_flight_search.stealth._HAS_CURL_CFFI", True)
    @patch("public_flight_search.stealth._session")
    def test_uses_impersonate_chrome(self, mock_session):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response

        result = stealth_get("https://example.test/data")

        mock_session.get.assert_called_once()
        call_kwargs = mock_session.get.call_args
        self.assertEqual(call_kwargs[0][0], "https://example.test/data")
        self.assertEqual(call_kwargs[1].get("impersonate"), "chrome")
        self.assertEqual(result.status_code, 200)

    @patch("public_flight_search.stealth._session")
    def test_passes_custom_timeout(self, mock_session):
        mock_response = MagicMock()
        mock_session.get.return_value = mock_response

        stealth_get("https://example.test/data", timeout=30)

        call_kwargs = mock_session.get.call_args[1]
        self.assertEqual(call_kwargs.get("timeout", 15), 30)

    @patch("public_flight_search.stealth._session")
    def test_passes_custom_headers(self, mock_session):
        mock_response = MagicMock()
        mock_session.get.return_value = mock_response

        stealth_get(
            "https://example.test/data",
            headers={"Accept-Language": "en-GB"},
        )

        call_kwargs = mock_session.get.call_args[1]
        self.assertIn("Accept-Language", call_kwargs.get("headers", {}))

    @patch("public_flight_search.stealth._session")
    def test_returns_none_on_network_error(self, mock_session):
        mock_session.get.side_effect = ConnectionError("timeout")

        result = stealth_get("https://example.test/data")
        self.assertIsNone(result)


class StealthPostTests(unittest.TestCase):
    @patch("public_flight_search.stealth._HAS_CURL_CFFI", True)
    @patch("public_flight_search.stealth._session")
    def test_uses_impersonate_chrome(self, mock_session):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.post.return_value = mock_response

        result = stealth_post(
            "https://example.test/api",
            json={"key": "value"},
        )

        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args[1]
        self.assertEqual(call_kwargs.get("impersonate"), "chrome")
        self.assertEqual(result.status_code, 200)

    @patch("public_flight_search.stealth._session")
    def test_returns_none_on_network_error(self, mock_session):
        mock_session.post.side_effect = OSError("connection refused")

        result = stealth_post("https://example.test/api", data=b"body")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
