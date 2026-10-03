"""ATOL package-operator links on long-haul cards.

Owner brief 2026-10-03 (F1). A card used to link one package operator (Love
Holidays) plus room-only sites. For long-haul, an ATOL-protected package can
beat a self-built trip and protects the money, so the card must carry the six
named operators: British Airways Holidays, Qatar Airways Holidays, Emirates
Holidays, Etihad Holidays, Kuoni and Trailfinders.

Every URL was checked against the operator's own live site on 2026-10-03 with
plain fetches only (no CAPTCHA solving, no bot-wall evasion, no logins):

- Kuoni: real pages, live (HTTP 200). Its search widget is JavaScript-only
  and its enquiry forms are POST, so no dates/party can be prefilled; its own
  sitemap publishes destination pages, which are linked instead, per key.
- British Airways: ba.com served an Akamai "Information Page" interstitial to
  plain fetchers — no URL grammar observable. Search page, no prefill.
- Emirates Holidays: emiratesholidays.com served a DataDome CAPTCHA wall
  (403 to both fetchers). Search page, no prefill.
- Etihad Holidays: etihadholidays.com and holidays.etihad.com both 301 to
  etihad.com/holidays (Location header from the operator's own server); the
  page body itself times out from this network. Search page, no prefill.
- Qatar Airways Holidays: 403 / connection timeout on every fetch path.
  Search page, no prefill.
- Trailfinders: every path serves an Incapsula interstitial. Search page,
  no prefill.

Where dates/party cannot be prefilled, the card's "Package operators" header
carries them ("5 travellers · out→ret · origins") and the reader enters them
on the operator's site; the note on each link says so.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import re
import unittest
from urllib.parse import urlparse

from public_flight_search import vendors as V
from public_flight_search.holidays import (
    VERIFIED_LINK_BASES,
    PackageDeal,
    _is_verified_link,
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
    render_vendor_block,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"

#: The six operators the brief names, in brief order.
ATOL_OPERATORS = (
    "British Airways Holidays",
    "Qatar Airways Holidays",
    "Emirates Holidays",
    "Etihad Holidays",
    "Kuoni",
    "Trailfinders",
)


def lombok_trip(**overrides) -> V.TripQuery:
    """A July long-haul card's search: Lombok, party of 5, from London."""
    base = dict(
        destination_key="lombok",
        destination_airport="LOP",
        origin_airports=("LHR", "LGW"),
        outbound_date="2027-07-10",
        return_date="2027-07-20",
        nights=10,
        adults=5,
        rooms=(2, 3),
        resort_name="Test Resort Lombok",
    )
    base.update(overrides)
    return V.TripQuery(**base)


def _base_deal(**overrides) -> PackageDeal:
    base = dict(
        resort_name="Test Resort",
        destination_label="Kuta Mandalika, Lombok",
        destination_key="lombok",
        star_rating=5,
        board_basis="Bed & Breakfast",
        outbound_date="2027-07-10",
        return_date="2027-07-20",
        nights=10,
        airline="Test Air",
        origin_airports=("LHR",),
        destination_airport="LOP",
        flight_price_total_gbp=5000.0,
        hotel_price_total_gbp=2000.0,
        total_package_price_gbp=7000.0,
        price_per_person_gbp=1400.0,
        flight_booking_url="https://example.invalid/flight",
        hotel_booking_url="https://example.invalid/hotel",
        is_under_budget=True,
        value_score_verified=True,
        # Non-empty flight_options is what marks a card long-haul.
        flight_options=({"kind": "economy"},),
    )
    base.update(overrides)
    return PackageDeal(**base)


class AtolOperatorLinkTests(unittest.TestCase):
    def test_long_haul_cards_carry_all_six_operators_in_brief_order(self):
        links = V.build_atol_operator_links(lombok_trip())
        self.assertEqual([link.vendor for link in links], list(ATOL_OPERATORS))
        for link in links:
            with self.subTest(operator=link.vendor):
                self.assertTrue(link.url.startswith("https://"))
                self.assertTrue(link.observed_on)
                self.assertTrue(link.note)

    def test_kuoni_links_the_destination_page_its_own_sitemap_publishes(self):
        # Kuoni's search widget is JS-only and its forms are POST, so no
        # dates/party can be prefilled. Its destination pages are the deepest
        # pages its own sitemap publishes for these keys (verified live
        # 2026-10-03, HTTP 200).
        expected = {
            "lombok": "https://www.kuoni.co.uk/destinations/south-east-asia/"
                      "indonesia/lombok-and-gili-islands/",
            "koh_samui": "https://www.kuoni.co.uk/destinations/south-east-asia/"
                         "thailand/koh-samui/",
            "koh_phangan": "https://www.kuoni.co.uk/destinations/south-east-asia/"
                           "thailand/koh-phangan/",
            "khao_lak": "https://www.kuoni.co.uk/destinations/south-east-asia/"
                        "thailand/khao-lak/",
            "riviera_maya": "https://www.kuoni.co.uk/destinations/caribbean/"
                            "mexico/cancun/",
        }
        for key, url in expected.items():
            with self.subTest(destination=key):
                link = V.build_kuoni_link(lombok_trip(destination_key=key))
                self.assertEqual(link.url, url)
                self.assertEqual(link.kind, V.DESTINATION_PAGE)
                self.assertIn("dates", link.note.lower())
                self.assertIn("party", link.note.lower())

    def test_kuoni_without_a_published_page_falls_back_to_its_destinations_index(self):
        link = V.build_kuoni_link(lombok_trip(destination_key="narnia"))
        self.assertEqual(link.url, "https://www.kuoni.co.uk/destinations/")
        self.assertEqual(link.kind, V.DESTINATION_PAGE)
        self.assertIn("dates", link.note.lower())

    def test_bot_walled_operators_link_their_search_pages_without_prefill(self):
        expected = {
            "British Airways Holidays": (
                "https://www.britishairways.com/en-gb/flights-and-holidays/holidays"
            ),
            "Qatar Airways Holidays": "https://www.qatarairways.com/en/holidays.html",
            "Emirates Holidays": "https://www.emiratesholidays.com/",
            "Etihad Holidays": "https://www.etihad.com/holidays",
            "Trailfinders": "https://www.trailfinders.com/",
        }
        links = {link.vendor: link for link in V.build_atol_operator_links(lombok_trip())}
        for vendor, url in expected.items():
            with self.subTest(operator=vendor):
                link = links[vendor]
                self.assertEqual(link.url, url)
                # An unconfirmable format must NOT be dressed up as a search:
                # no invented parameters, no fabricated prefill kind.
                self.assertEqual(urlparse(link.url).query, "")
                self.assertNotEqual(link.kind, V.PREFILLED_SEARCH)
                self.assertNotEqual(link.kind, V.DEEP_LINK)
                # "…and say so": the note names the operator's site as the
                # place the dates and party are entered.
                self.assertIn("dates", link.note.lower())
                self.assertIn("party", link.note.lower())

    def test_no_prefill_means_no_dates_party_or_origin_in_the_url(self):
        # URL-building honesty: only a confirmed grammar may carry a date, a
        # party size or an origin. None of the six is confirmed today, so no
        # built URL carries any of them, and nothing guesses.
        for link in V.build_atol_operator_links(lombok_trip()):
            with self.subTest(operator=link.vendor):
                self.assertNotIn("2027-07-10", link.url)
                self.assertNotIn("2027-07-20", link.url)
                self.assertNotIn("LHR", link.url)
                self.assertNotIn("LGW", link.url)
                self.assertNotIn("adults", link.url)
                self.assertNotIn("rooms", link.url)

    def test_operator_urls_never_carry_a_budget_or_personal_detail(self):
        blob = " ".join(
            link.url + " " + link.note
            for link in V.build_atol_operator_links(lombok_trip())
        )
        for token in ("budget", "£", "@", "name="):
            with self.subTest(token=token):
                self.assertNotIn(token, blob)
        self.assertIsNone(re.search(
            r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", blob, re.I))
        self.assertIsNone(re.search(
            r"\b[a-z]{1,2}\d[a-z\d]?\s*\d[a-z]{2}\b", blob, re.I))

    def test_every_operator_url_is_in_the_verified_allowlist(self):
        for link in V.build_atol_operator_links(lombok_trip()):
            with self.subTest(operator=link.vendor):
                self.assertTrue(
                    _is_verified_link(link.url),
                    f"{link.vendor} URL has unverified base: {link.url}",
                )
        # And the constants feed the allowlist, so a future operator cannot
        # bypass it.
        for base in V.ATOL_OPERATOR_LINK_BASES:
            self.assertIn(base, VERIFIED_LINK_BASES)


class AtolOperatorRenderTests(unittest.TestCase):
    def test_long_haul_vendor_block_shows_the_operators_the_search_and_the_label(self):
        html = render_vendor_block(_base_deal(), adults=5, rooms=(2, 3))
        for vendor in ATOL_OPERATORS:
            with self.subTest(operator=vendor):
                self.assertIn(vendor, html)
        # The search the links are for: the card's dates, party of 5, origin.
        self.assertIn("5 travellers", html)
        self.assertIn("2027-07-10", html)
        self.assertIn("2027-07-20", html)
        self.assertIn("LHR", html)
        # "…and say so": no-prefill links are tagged as search pages.
        self.assertIn("search page", html)
        # The label every link carries.
        self.assertIn("price not verified", html)
        self.assertIn("a link is not a quote", html)

    def test_short_haul_cards_do_not_carry_the_six_operators(self):
        html = render_vendor_block(
            _base_deal(flight_options=()), adults=5, rooms=(2, 3))
        self.assertIn("Love Holidays", html)
        for vendor in ("Qatar Airways Holidays", "Trailfinders", "Etihad Holidays"):
            with self.subTest(operator=vendor):
                self.assertNotIn(vendor, html)

    def test_footer_label_names_prefilled_links_as_prefilled(self):
        # The brief's exact label applies when a link is actually prefilled;
        # a link with no prefill must never wear that word.
        prefilled = V.VendorLink(
            vendor="Prefilled Co", url="https://prefilled.example/?date=2027-07-10",
            kind=V.PREFILLED_SEARCH, carried=("date",), note="",
        )
        self.assertIn(
            "prefilled search link, price not verified — a link is not a quote",
            V.price_label_line([prefilled]),
        )
        walled = V.VendorLink(
            vendor="Walled Co", url="https://walled.example/",
            kind=V.SEARCH_PAGE, carried=(), note="",
        )
        self.assertIn(
            "search link, price not verified — a link is not a quote",
            V.price_label_line([walled]),
        )
        self.assertNotIn(
            "prefilled search link", V.price_label_line([walled]))

    def test_every_long_haul_card_in_the_report_carries_the_operators(self):
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        deals = collect_holiday_deals(config)
        long_haul = [d for d in deals if d.flight_options]
        self.assertTrue(long_haul)
        html = render_holiday_report(
            config, generated_at="2026-10-03T00:00:00+00:00", deals=deals,
        )
        for vendor in ("Qatar Airways Holidays", "Emirates Holidays", "Kuoni",
                       "Trailfinders"):
            with self.subTest(operator=vendor):
                self.assertIn(vendor, html)
        self.assertGreaterEqual(html.count("a link is not a quote"), len(long_haul))


if __name__ == "__main__":
    unittest.main()
