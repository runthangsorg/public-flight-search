import unittest

from public_flight_search.google_flights import (
    build_google_flights_url,
    check_waf,
    parse_google_flight_text,
)


class GoogleFlightsTests(unittest.TestCase):
    def test_normal_flights_document_with_captcha_script_is_not_waf(self):
        class Page:
            async def content(self):
                return '<script src="/recaptcha/api.js"></script><div role="main">Flights</div>'

        import asyncio
        self.assertFalse(asyncio.run(check_waf(Page())))

    def test_explicit_google_challenge_is_waf(self):
        class Page:
            async def content(self):
                return "Our systems have detected unusual traffic from your computer"

        import asyncio
        self.assertTrue(asyncio.run(check_waf(Page())))

    def test_builds_https_booking_entry_url(self):
        url = build_google_flights_url(
            origins=("AAA",),
            destinations=("BBB",),
            date="2030-09-01",
            travellers=2,
            cabin_class="ECONOMY",
        )
        self.assertTrue(url.startswith("https://www.google.com/travel/flights?"))
        self.assertNotIn(" ", url)

    def test_parses_a_result_card_without_claiming_checkout_verification(self):
        offer = parse_google_flight_text(
            "AAA to BBB 08:15 12:45 non-stop 4 hr 30 min Sample Air £123",
            origins=("AAA",),
            destinations=("BBB",),
            date="2030-09-01",
            travellers=2,
            booking_url="https://www.google.com/travel/flights?q=sample",
        )
        self.assertIsNotNone(offer)
        self.assertEqual(offer.price, 246)
        self.assertEqual(offer.stops, 0)
        self.assertEqual(offer.review_status, "results_page_only")


if __name__ == "__main__":
    unittest.main()
