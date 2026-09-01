import unittest
import re

from public_flight_search.config import FlightConfig, FlightSearch
from public_flight_search.engine import FlightOffer
from public_flight_search.report import render_flight_report


class ReportTests(unittest.TestCase):
    def test_escapes_labels_and_renders_truthful_link_status(self):
        search = FlightSearch(
            key="sample",
            label="A < B",
            origins=("AAA",),
            destinations=("BBB",),
            dates=("2030-09-01",),
            travellers=1,
            cabin_class="ECONOMY",
            departure_window=("08:00", "18:00"),
            max_stops=1,
            max_duration_minutes=1440,
            max_price_per_traveller_gbp=None,
        )
        offer = FlightOffer(
            origin="AAA",
            destination="BBB",
            departure="2030-09-01T09:00:00",
            price=123,
            currency="GBP",
            stops=0,
            duration_minutes=240,
            provider="Google Flights",
            booking_url="https://www.google.com/travel/flights?q=sample",
            airline="Sample Air",
            review_status="results_page_only",
        )
        html = render_flight_report(
            FlightConfig(report_title="Digest <private>", searches=(search,)),
            {"sample": (offer,)},
            generated_at="2030-08-01T10:00:00+00:00",
        )
        self.assertIn("Digest &lt;private&gt;", html)
        self.assertIn("A &lt; B", html)
        self.assertIn("⚠ Disclaimer:", html)
        self.assertIn("Displayed fare", html)
        self.assertNotIn("£123 whole party", html.lower())
        self.assertNotIn("checkout verified", html.lower())
        self.assertTrue(all(url.startswith("https://") for url in re.findall(r'href="([^"]+)"', html)))

    def test_fallback_links_are_scoped_to_each_search(self):
        first = FlightSearch(
            key="first", label="First", origins=("AAA",), destinations=("BBB",),
            dates=("2030-09-01",), travellers=1, cabin_class="ECONOMY",
            departure_window=("00:00", "23:59"), max_stops=1,
            max_duration_minutes=1440, max_price_per_traveller_gbp=None,
        )
        second = FlightSearch(
            key="second", label="Second", origins=("CCC",), destinations=("DDD",),
            dates=("2030-09-02",), travellers=1, cabin_class="ECONOMY",
            departure_window=("00:00", "23:59"), max_stops=1,
            max_duration_minutes=1440, max_price_per_traveller_gbp=None,
        )
        html = render_flight_report(
            FlightConfig(report_title="Fallbacks", searches=(first, second)),
            {"first": (), "second": ()},
            google_links={
                "AAA_BBB_2030-09-01": {"url": "https://example.test/a", "label": "ONLY-A"},
                "CCC_DDD_2030-09-02": {"url": "https://example.test/b", "label": "ONLY-B"},
            },
            generated_at="2030-08-01T10:00:00+00:00",
        )
        self.assertEqual(html.count("ONLY-A"), 1)
        self.assertEqual(html.count("ONLY-B"), 1)


if __name__ == "__main__":
    unittest.main()
