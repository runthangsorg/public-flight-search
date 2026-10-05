"""A booking link says what it books (BRIEF-H16 §3, 2026-10-06).

The compact e-mail's first link read "Book this package" on every card. On
Pullman Lombok Merujani Mandalika that card is priced from a rate read on
Accor plus an economy flight estimate — two halves the engine priced itself —
so "this package" described nothing the reader could buy at the card's price.

Pinned here:

* the label follows the price: "Book this package" only when an operator's own
  package priced the card, "Book the hotel" when the engine did;
* the URL follows the label. A package search is NOT relabelled "the hotel":
  every vendor in ``build_vendor_links`` sells flights plus a hotel, so the old
  link was a package search whatever it was called, and on a card priced by the
  engine it is a different holiday at a different price. The hotel's own site
  is the one link that can promise the stay;
* nothing is dropped either way: the card still has a compare link and a hotel
  page, and the hotel page is still a different place from the hotel's own site;
* both renderings (the e-mail and its plain-text twin) print the label.

The card is built from a synthetic deal shaped like Pullman Lombok's, not read
from ``data/`` — the real card is verified by the July dry run.
"""

from __future__ import annotations

import unittest
from html import unescape
from pathlib import Path

from public_flight_search.holiday_email import (
    link_row,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import (
    PackageDeal,
    load_holiday_config,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-06T12:00:00+00:00"
HOTEL_SITE = "https://pullman.accor.com/en/hotels/central-lombok/A1K2.html"


def _config():
    return load_holiday_config(
        (ROOT / "examples" / "july_holiday_config.json").read_text(encoding="utf-8"))


def _deal(**overrides) -> PackageDeal:
    """Pullman Lombok Merujani Mandalika's card, as the engine priced it:
    a hotel rate read plus an economy fare, so nothing here is a package."""
    base = dict(
        resort_name="Pullman Lombok Merujani Mandalika Beach Resort",
        destination_label="Kuta Mandalika, Lombok, Indonesia",
        destination_key="lombok",
        star_rating=5,
        board_basis="Bed & Breakfast",
        outbound_date="2027-06-27",
        return_date="2027-07-09",
        nights=12,
        airline="Singapore Airlines",
        origin="LHR",
        origin_airports=("LHR", "LGW", "LTN", "STN"),
        destination_airport="LOP",
        flight_price_total_gbp=4990.0,
        hotel_price_total_gbp=8755.0,
        total_package_price_gbp=13745.0,
        price_per_person_gbp=2749.0,
        uk_ground_gbp=16.5,
        transfer_gbp=25.0,
        true_d2d_gbp=13787.0,
        hotel_booking_url=HOTEL_SITE,
        flight_booking_url="https://www.google.com/travel/flights/search?tfs=abc",
        booking_deep_url="https://www.booking.com/searchresults.html?ss=Pullman",
        compare_url="https://www.google.com/travel/hotels?q=Pullman+Lombok",
        is_under_budget=False,
        unit_architecture="Two-Bedroom Garden Villa, private pool (6 guests max)",
        rooms_in_unit=1,
    )
    base.update(overrides)
    return PackageDeal(**base)


class LabelTests(unittest.TestCase):
    def test_a_card_the_engine_priced_does_not_say_book_this_package(self):
        links = link_row(_deal(), _config())
        labels = [label for label, _ in links]
        self.assertNotIn("Book this package", labels)
        self.assertEqual(labels[0], "Book the hotel")

    def test_book_the_hotel_goes_to_the_hotels_own_site(self):
        links = dict((label, url) for label, url in link_row(_deal(), _config()))
        self.assertEqual(links["Book the hotel"], HOTEL_SITE)
        self.assertTrue(links["Book the hotel"].startswith("https://"))

    def test_an_operator_package_priced_card_keeps_the_operator_search(self):
        links = link_row(_deal(package_priced=True), _config())
        labels = [label for label, _ in links]
        self.assertEqual(labels[0], "Book this package")
        self.assertNotIn("Book the hotel", labels)

    def test_the_two_branches_link_to_different_places(self):
        package_url = dict(link_row(_deal(package_priced=True), _config()))[
            "Book this package"]
        hotel_url = dict(link_row(_deal(), _config()))["Book the hotel"]
        self.assertNotEqual(package_url, hotel_url)
        self.assertIn("loveholidays", package_url)

    def test_the_hotel_page_is_still_a_different_place_from_the_hotels_site(self):
        links = dict((label, url) for label, url in link_row(_deal(), _config()))
        self.assertEqual(links["Hotel page"], _deal().booking_deep_url)
        self.assertNotEqual(links["Hotel page"], links["Book the hotel"])
        self.assertEqual(links["Compare prices"], _deal().compare_url)

    def test_a_card_with_no_hotel_site_keeps_the_other_two_links(self):
        deal = _deal(hotel_booking_url="")
        links = link_row(deal, _config())
        self.assertEqual([label for label, _ in links],
                         ["Compare prices", "Hotel page"])

    def test_a_hotel_site_that_is_not_a_url_is_not_a_link(self):
        deal = _deal(hotel_booking_url="barutlara.com")
        labels = [label for label, _ in link_row(deal, _config())]
        self.assertNotIn("Book the hotel", labels)

    def test_a_package_priced_card_never_gets_the_hotels_own_site(self):
        labels = [label for label, _ in link_row(_deal(package_priced=True), _config())]
        self.assertNotIn("Book the hotel", labels)


class RenderingTests(unittest.TestCase):
    def test_the_email_prints_the_hotels_own_site_as_book_the_hotel(self):
        html = render_holiday_report_compact(
            _config(), generated_at=NOW, deals=[_deal()])
        self.assertIn(f'href="{HOTEL_SITE}"', html)
        self.assertIn("Book the hotel", unescape(html))
        self.assertNotIn("Book this package", unescape(html))

    def test_the_plain_text_email_prints_the_same_labels(self):
        text = render_holiday_report_compact_text(
            _config(), generated_at=NOW, deals=[_deal()])
        line = next(line for line in text.splitlines() if "Book" in line)
        self.assertIn("Book the hotel", line)
        self.assertNotIn("Book this package", text)

    def test_a_package_priced_card_still_prints_book_this_package(self):
        text = render_holiday_report_compact_text(
            _config(), generated_at=NOW, deals=[_deal(package_priced=True)])
        self.assertIn("Book this package", text)
        self.assertNotIn("Book the hotel", text)


if __name__ == "__main__":
    unittest.main()