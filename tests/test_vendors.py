import re
import unittest
from urllib.parse import parse_qs, urlparse

from public_flight_search import vendors as V


def fixture_trip(**overrides) -> V.TripQuery:
    base = dict(
        destination_key="tenerife",
        destination_airport="TFS",
        origin_airports=("LGW", "LTN"),
        outbound_date="2026-12-22",
        return_date="2026-12-30",
        nights=8,
        adults=5,
        rooms=(2, 2, 1),
        resort_name="Sample Bay Resort",
    )
    base.update(overrides)
    return V.TripQuery(**base)


class VendorLinkGrammarTests(unittest.TestCase):
    def test_loveholidays_link_carries_dates_party_and_airports(self):
        # The complaint was that every card ended in the same generic hotel
        # search. A vendor link that does not carry the actual search is the
        # same failure wearing a different brand name.
        link = V.build_loveholidays_link(fixture_trip())
        query = parse_qs(urlparse(link.url).query)
        self.assertEqual(query["date"], ["2026-12-22"])
        self.assertEqual(query["nights"], ["8"])
        self.assertEqual(query["rooms"], ["2,2,1"])
        self.assertEqual(query["departureAirports"], ["LGW,LTN"])
        self.assertEqual(query["dateType"], ["absolute"])
        self.assertIn("loveholidays.com", urlparse(link.url).hostname or "")

    def test_loveholidays_uses_the_destination_id_it_publishes(self):
        # The slug alone landed the reader on a country landing page that did not
        # run the search (owner, 2026-09-24: the operator links "are broken").
        # Each destination page publishes its own destinationIds in the search
        # link it renders, so the link is built from that, not from the slug.
        link = V.build_loveholidays_link(fixture_trip())  # tenerife → spain
        query = parse_qs(urlparse(link.url).query)
        self.assertEqual(query["destinationIds"], ["987,391,474"])
        self.assertEqual(urlparse(link.url).path, "/holidays/")
        self.assertIn("destination", link.carried)

    def test_every_published_slug_has_its_observed_destination_id(self):
        # A slug without an id would silently fall back to the country page that
        # does not search. Pin the ids read on 2026-09-24 so one cannot slip in.
        for slug in V.LOVEHOLIDAYS_DESTINATION_SLUGS.values():
            self.assertIn(slug, V.LOVEHOLIDAYS_DESTINATION_IDS, slug)
        self.assertEqual(V.LOVEHOLIDAYS_DESTINATION_IDS["cyprus-holidays.html"], "526")
        self.assertEqual(V.LOVEHOLIDAYS_DESTINATION_IDS["turkey-holidays.html"], "1036")

    def test_a_destination_with_no_published_id_still_says_so(self):
        link = V.build_loveholidays_link(fixture_trip(destination_key="muscat"))
        self.assertNotIn("destinationIds", link.url)
        self.assertNotIn("destination", link.carried)
        self.assertIn("destination", link.note)

    def test_loveholidays_without_a_published_slug_says_so(self):
        # Oman has no loveholidays destination page we observed. Guessing a
        # slug produces a 404; the honest link is the dated search without a
        # destination, and the note must say the destination is still to pick.
        link = V.build_loveholidays_link(fixture_trip(destination_key="muscat"))
        self.assertNotIn("destination", link.carried)
        self.assertIn("destination", link.note)
        query = parse_qs(urlparse(link.url).query)
        self.assertEqual(query["date"], ["2026-12-22"])

    def test_loveholidays_is_labelled_a_prefilled_search_not_a_deep_link(self):
        # Its results page is bot-protected, so the parameters could not be
        # watched being honoured. Calling that a deep link would be a claim
        # the evidence does not support.
        link = V.build_loveholidays_link(fixture_trip())
        self.assertEqual(link.kind, V.PREFILLED_SEARCH)
        self.assertFalse(link.is_deep_link)
        self.assertIn("prefilled search", link.kind_label)

    def test_destination2_is_a_destination_page_never_a_homepage(self):
        link = V.build_destination2_link(fixture_trip())
        self.assertIsNotNone(link)
        self.assertEqual(link.kind, V.DESTINATION_PAGE)
        self.assertEqual(
            link.url, "https://www.destination2.co.uk/destinations/europe/spain/canaries"
        )
        self.assertNotEqual(urlparse(link.url).path, "/")
        self.assertIn("POST", link.note)

    def test_destination2_omitted_where_it_has_no_destination_page(self):
        self.assertIsNone(V.build_destination2_link(fixture_trip(destination_key="narnia")))

    def test_every_vendor_link_disclaims_price(self):
        for link in V.build_vendor_links(fixture_trip()):
            self.assertEqual(link.price_label, "search link, price not verified")
            self.assertTrue(link.observed_on)

    def test_no_vendor_link_is_a_bare_homepage(self):
        # The old behaviour linked homepages and hubs. A homepage carries no
        # search at all, which is what made the e-mail useless.
        for key in V.DESTINATION2_DESTINATION_PATHS:
            for link in V.build_vendor_links(fixture_trip(destination_key=key)):
                path = urlparse(link.url).path
                self.assertNotEqual(path, "/", link.url)
                self.assertTrue(len(path) > 1, link.url)

    def test_vendor_templates_contain_no_personal_identifiers(self):
        # This repository is public: a vendor template must never carry a
        # recipient, a postcode or any personal identifier.
        blob = "\n".join(
            link.url + " " + link.note + " " + link.example_url
            for key in V.DESTINATION2_DESTINATION_PATHS
            for link in V.build_vendor_links(fixture_trip(destination_key=key))
        )
        self.assertIsNone(re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", blob, re.I))
        self.assertIsNone(re.search(r"\b[a-z]{1,2}\d[a-z\d]?\s*\d[a-z]{2}\b", blob, re.I))


if __name__ == "__main__":
    unittest.main()
