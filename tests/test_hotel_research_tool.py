"""The pure rules of ``tools/hotel_research.py``, tested with no network (23 Oct 2026).

The tool is run by hand on a laptop and is never run in CI or at send time; what it WRITES is public data the e-mail
hot-links. These tests pin the rules that decide what it may write: a rating needs a count and a sane score, a photo
must be an image of a sensible size, a page must name the property, a stored URL carries no tracking, and a figure that
was not read is never invented.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))

import hotel_research as hr  # noqa: E402


def _jsonld(payload: str) -> str:
    return f'<html><head><script type="application/ld+json">{payload}</script></head></html>'


class RatingsAreOnlyWhatAPageStatesTests(unittest.TestCase):
    def test_a_jsonld_rating_with_a_count_is_read_on_its_own_scale(self):
        html = _jsonld('{"@type":"Hotel","aggregateRating":{"ratingValue":"8.9","reviewCount":640,"bestRating":"10"}}')
        self.assertEqual(hr.aggregate_rating(html), {"score": 8.9, "best": 10.0, "count": 640})

    def test_a_rating_nested_in_a_graph_is_found(self):
        html = _jsonld('{"@graph":[{"@type":"WebSite"},{"@type":"Hotel","aggregateRating":{"ratingValue":4.6,"ratingCount":"2,310"}}]}')
        self.assertEqual(hr.aggregate_rating(html), {"score": 4.6, "best": 5.0, "count": 2310})

    def test_a_rating_with_no_count_is_not_a_rating(self):
        self.assertIsNone(hr.aggregate_rating(_jsonld('{"aggregateRating":{"ratingValue":"4"}}')))

    def test_a_zero_count_or_a_score_off_its_scale_is_refused_not_repaired(self):
        self.assertIsNone(hr.aggregate_rating(_jsonld('{"aggregateRating":{"ratingValue":4.5,"reviewCount":0}}')))
        self.assertIsNone(hr.aggregate_rating(_jsonld('{"aggregateRating":{"ratingValue":9.5,"reviewCount":10,"bestRating":5}}')))
        self.assertIsNone(hr.aggregate_rating(_jsonld('{"aggregateRating":{"ratingValue":"great","reviewCount":10}}')))

    def test_a_small_review_count_is_kept_with_its_count(self):
        found = hr.aggregate_rating(_jsonld('{"aggregateRating":{"ratingValue":5,"reviewCount":3}}'))
        self.assertEqual(found["count"], 3)

    def test_a_page_with_no_rating_gives_none(self):
        self.assertIsNone(hr.aggregate_rating("<html><title>x</title></html>"))
        self.assertIsNone(hr.aggregate_rating(_jsonld("not json {")))


class APageMustNameTheProperty(unittest.TestCase):
    def test_the_title_or_the_url_naming_the_property_passes(self):
        self.assertTrue(hr.title_names_property("Novotel Lombok Resort & Villas", "Novotel Lombok Resort & Villas - Lombok"))
        self.assertTrue(hr.title_names_property("Kirurumu Tarangire Lodge", "", "https://www.kirurumu.net/tarangire"))

    def test_another_hotel_that_came_back_from_the_same_search_fails(self):
        self.assertFalse(hr.title_names_property("Ocean Paradise Resort", "Zanzibar Bay Resort | Official site"))
        self.assertFalse(hr.title_names_property("Giraffe Manor", "Hotels in Nairobi"))

    def test_a_name_with_only_generic_words_never_passes_on_nothing(self):
        self.assertFalse(hr.title_names_property("The Resort", "Some other place"))


class APhotoMustBeAPhotoTests(unittest.TestCase):
    def _head(self, status=200, ctype="image/jpeg", length=90_000, body=b""):
        return lambda url: {"status": status, "content_type": ctype, "length": length, "body": body}

    def test_http_200_an_image_and_a_sensible_size_passes(self):
        ok, _why = hr.verify_image("https://example.org/a.jpg", self._head())
        self.assertTrue(ok)

    def test_a_missing_picture_a_page_and_an_svg_all_fail(self):
        self.assertFalse(hr.verify_image("https://example.org/a.jpg", self._head(status=404))[0])
        self.assertFalse(hr.verify_image("https://example.org/a.jpg", self._head(ctype="text/html"))[0])
        self.assertFalse(hr.verify_image("https://example.org/a.svg", self._head(ctype="image/svg+xml"))[0])

    def test_an_icon_sized_picture_fails(self):
        self.assertFalse(hr.verify_image("https://example.org/a.jpg", self._head(length=3_000))[0])

    def test_logos_and_icons_are_not_candidates(self):
        self.assertFalse(hr.looks_like_a_photo_url("https://example.org/img/logo.png"))
        self.assertFalse(hr.looks_like_a_photo_url("http://example.org/room.jpg"))
        self.assertTrue(hr.looks_like_a_photo_url("https://example.org/img/pool.jpg"))

    def test_candidates_come_best_first_and_only_as_absolute_https(self):
        html = ('<meta property="og:image" content="https://cdn.example.org/hero.jpg">'
                '<img src="/rooms/one.jpg"><img data-src="//cdn.example.org/two.jpg"><img src="data:image/gif;base64,AA">'
                '<img src="/logo.png">')
        got = hr.image_candidates(html, "https://www.example.org/stay")
        self.assertEqual(got[0], "https://cdn.example.org/hero.jpg")
        self.assertEqual(got[1:], ["https://www.example.org/rooms/one.jpg", "https://cdn.example.org/two.jpg"])


class APhotosSourceIsNamedHonestlyTests(unittest.TestCase):
    def test_a_domain_that_carries_the_properties_name_is_official(self):
        self.assertEqual(hr.source_label("https://www.novotellombok.com/", "Novotel Lombok Resort & Villas"), "official")
        self.assertEqual(hr.source_label("https://www.kirurumu.net/tarangire", "Kirurumu Tarangire Lodge"), "official")

    def test_somebody_elses_site_that_merely_names_the_hotel_is_not_official(self):
        self.assertEqual(hr.source_label("https://kalandara-resort.hotels-in-lombok.com/en/", "Kalandara Resort Lombok"), "other")
        self.assertEqual(hr.registrable_domain("a.b.example.co.uk"), "example.co.uk")

    def test_the_big_travel_sites_and_operators_are_labelled_as_what_they_are(self):
        self.assertEqual(hr.source_label("https://www.booking.com/hotel/id/x.html", "X"), "booking")
        self.assertEqual(hr.source_label("https://www.tripadvisor.com/Hotel_Review-x.html", "X"), "tripadvisor")
        self.assertEqual(hr.source_label("https://www.kuoni.co.uk/destinations/x", "Giraffe Manor"), "operator")


class UrlsCarryNoTrackingTests(unittest.TestCase):
    def test_tracking_parameters_and_fragments_are_stripped(self):
        self.assertEqual(hr.clean_url("https://example.org/p?utm_source=x&fbclid=1&q=a#top"), "https://example.org/p?q=a")

    def test_only_https_pages_are_kept(self):
        self.assertEqual(hr.clean_url("http://example.org/p"), "")
        self.assertEqual(hr.clean_url("javascript:alert(1)"), "")

    def test_a_stored_google_page_names_the_property_and_nothing_about_a_visitor(self):
        url = hr.google_page("Novotel Lombok Resort & Villas", "Lombok")
        self.assertEqual(hr.clean_url(url), url)
        self.assertNotIn("ts=", url)


class SearchResultsAreSortedIntoSitesTests(unittest.TestCase):
    def test_pages_are_classified_by_what_they_are(self):
        self.assertEqual(hr.classify_page("https://www.booking.com/hotel/id/novotellombok.html"), "booking")
        self.assertEqual(hr.classify_page("https://www.booking.com/searchresults.html?ss=x"), "skip")
        self.assertEqual(hr.classify_page("https://www.tripadvisor.co.uk/Hotel_Review-g1-d2-Reviews-X.html"), "tripadvisor")
        self.assertEqual(hr.classify_page("https://www.tripadvisor.co.uk/Restaurant_Review-g1.html"), "skip")
        self.assertEqual(hr.classify_page("https://www.agoda.com/x/hotel/lombok-id.html"), "agoda")
        self.assertEqual(hr.classify_page("https://www.novotellombok.com/"), "other")
        self.assertEqual(hr.classify_page("https://www.facebook.com/novotellombok"), "skip")

    def test_search_results_unwrap_the_redirects(self):
        html = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.org%2Fa&rut=1">x</a>'
                '<a class="result__a" href="https://www.example.org/b">y</a>')
        self.assertEqual(hr.search_results(html), ["https://www.example.org/a", "https://www.example.org/b"])


class TheFilesAreBuiltFromWhatWasReadTests(unittest.TestCase):
    PROPS = {"novotellombokresortvillas": {"name": "Novotel Lombok Resort & Villas", "area": "Lombok"},
             "giraffemanor": {"name": "Giraffe Manor", "area": "Nairobi"}}

    def _build(self, researched, google=None, ta=None):
        return hr.build_files(researched, self.PROPS, google or {}, ta or {}, today="2026-10-23")

    def test_a_property_without_a_verified_photo_gets_no_image_entry(self):
        images, _reviews = self._build({"giraffemanor": {"image": None, "ratings": [], "not_read": {}}})
        self.assertEqual(images["properties"], {})

    def test_a_verified_photo_is_recorded_with_its_page_and_source(self):
        live = {"novotellombokresortvillas": {"image": {"image_url": "https://cdn.example.org/a.jpg",
                                                         "page_url": "https://www.novotellombok.com/", "source": "official"},
                                               "ratings": [], "not_read": {}}}
        images, _ = self._build(live)
        self.assertEqual(images["properties"]["novotellombokresortvillas"]["source"], "official")

    def test_each_sites_figure_stays_on_its_own_scale_and_is_never_averaged(self):
        live = {"novotellombokresortvillas": {"image": None, "not_read": {}, "ratings": [
            {"source": "Booking", "score": 8.9, "scale": 10.0, "count": "640", "observed_at": "2026-10-23T09:00:00+00:00",
             "source_url": "https://www.booking.com/hotel/id/x.html"}]}}
        google = {"novotellombokresortvillas": [{"source": "Google", "score": 4.5, "scale": 5.0, "count": "3.9k",
                                                  "observed_at": "2026-10-02T15:20:00+00:00", "name": "Novotel"}]}
        _images, reviews = self._build(live, google)
        rows = {r["source"]: r for r in reviews["properties"]["novotellombokresortvillas"]["ratings"]}
        self.assertEqual((rows["Booking"]["score"], rows["Booking"]["scale"]), (8.9, 10.0))
        self.assertEqual((rows["Google"]["score"], rows["Google"]["scale"], rows["Google"]["count"]), (4.5, 5.0, "3.9k"))
        self.assertEqual(len(rows), 2, "no combined figure appears")

    def test_a_site_that_gave_nothing_is_recorded_as_not_read_with_its_reason(self):
        live = {"giraffemanor": {"image": None, "ratings": [], "not_read": {"tripadvisor": "wall: datadome-challenge"}}}
        _images, reviews = self._build(live)
        self.assertEqual(reviews["properties"]["giraffemanor"]["ratings"], [])
        self.assertEqual(reviews["properties"]["giraffemanor"]["not_read"]["tripadvisor"], "wall: datadome-challenge")
        self.assertEqual(reviews["properties"]["giraffemanor"]["not_read"]["google"], "no read")

    def test_an_accor_figure_is_added_only_where_none_of_the_three_sites_has_one(self):
        accor = {"source": "Accor", "score": 4.4, "scale": 5.0, "count": "497", "observed_at": "2026-10-02T15:14:24+00:00", "name": "N"}
        google = {"source": "Google", "score": 4.4, "scale": 5.0, "count": "789", "observed_at": "2026-10-02T15:21:26+00:00", "name": "N"}
        _i, with_google = self._build({}, {"novotellombokresortvillas": [accor, google]})
        self.assertEqual([r["source"] for r in with_google["properties"]["novotellombokresortvillas"]["ratings"]], ["Google"])


if __name__ == "__main__":
    unittest.main()
