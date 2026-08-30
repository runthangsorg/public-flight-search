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
        self.assertIn("Results-page evidence — recheck at checkout", html)
        self.assertNotIn("checkout verified", html.lower())
        self.assertTrue(all(url.startswith("https://") for url in re.findall(r'href="([^"]+)"', html)))


if __name__ == "__main__":
    unittest.main()
