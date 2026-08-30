import json
import unittest

from public_flight_search.engine import SearchCriteria, search_offers


class SearchOffersTests(unittest.TestCase):
    def test_filters_invalid_and_out_of_policy_offers_then_sorts(self):
        offers = [
            {
                "origin": "AAA",
                "destination": "BBB",
                "departure": "2030-01-02T08:00:00Z",
                "price": 220,
                "currency": "GBP",
                "stops": 1,
                "duration_minutes": 300,
                "provider": "public-feed",
                "booking_url": "https://example.test/book?id=2",
            },
            {
                "origin": "AAA",
                "destination": "BBB",
                "departure": "2030-01-02T09:00:00Z",
                "price": 180,
                "currency": "GBP",
                "stops": 0,
                "duration_minutes": 240,
                "provider": "public-feed",
                "booking_url": "https://example.test/book?id=1",
            },
            {
                "origin": "AAA",
                "destination": "BBB",
                "departure": "2030-01-02T10:00:00Z",
                "price": 99,
                "currency": "GBP",
                "stops": 3,
                "duration_minutes": 600,
                "provider": "public-feed",
            },
            {"origin": "not-an-airport", "price": 1},
        ]

        results = search_offers(
            offers,
            SearchCriteria(
                origins=frozenset({"AAA"}),
                destinations=frozenset({"BBB"}),
                max_stops=1,
                max_duration_minutes=360,
                max_price=250,
                currency="GBP",
            ),
        )

        self.assertEqual([item.price for item in results], [180.0, 220.0])
        self.assertEqual(results[0].origin, "AAA")

    def test_never_claims_an_offer_is_verified(self):
        result = search_offers(
            [
                {
                    "origin": "AAA",
                    "destination": "BBB",
                    "departure": "2030-01-02T09:00:00Z",
                    "price": 180,
                    "currency": "GBP",
                    "stops": 0,
                    "duration_minutes": 240,
                    "provider": "sample",
                }
            ],
            SearchCriteria(),
        )[0]

        payload = result.to_public_dict()
        self.assertEqual(payload["review_status"], "unverified_provider_result")
        self.assertNotIn("verified", json.dumps(payload).lower().replace("unverified", ""))

    def test_rejects_non_https_booking_urls(self):
        results = search_offers(
            [
                {
                    "origin": "AAA",
                    "destination": "BBB",
                    "departure": "2030-01-02T09:00:00Z",
                    "price": 180,
                    "currency": "GBP",
                    "stops": 0,
                    "duration_minutes": 240,
                    "provider": "sample",
                    "booking_url": "file:///private/path",
                }
            ],
            SearchCriteria(),
        )

        self.assertEqual(results[0].booking_url, "")


if __name__ == "__main__":
    unittest.main()
