"""The committed photo and rating data files obey their rules (23 Oct 2026).

``hotel_images.json`` and ``hotel_reviews.json`` are public data the e-mail hot-links; ``tools/hotel_research.py`` writes
them by hand. Whatever it wrote, these rules hold, and no test here touches the network.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

from public_flight_search.hotel_evidence import normalise_property_name
from public_flight_search.hotel_media import (
    DEFAULT_IMAGES_PATH,
    DEFAULT_REVIEWS_PATH,
    load_hotel_media,
    url_is_clean,
)

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import hotel_research as hr  # noqa: E402

IMAGE_SOURCES = {"booking", "official", "operator", "tripadvisor", "agoda", "other"}


def _strict_load(path):
    """The file as a dict, refusing a duplicate key (``json.load`` would silently keep the last)."""
    def hook(pairs):
        keys = [k for k, _v in pairs]
        dup = {k for k in keys if keys.count(k) > 1}
        if dup:
            raise AssertionError(f"duplicate keys in {path}: {sorted(dup)}")
        return dict(pairs)

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=hook)


class TheImagesFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = _strict_load(DEFAULT_IMAGES_PATH)

    def test_it_is_the_declared_schema_with_a_research_date(self):
        self.assertEqual(self.doc["schema"], "hotel_images/1")
        datetime.strptime(self.doc["researched_on"], "%Y-%m-%d")

    def test_every_entry_has_https_urls_without_tracking_and_a_name_that_normalises_to_its_key(self):
        self.assertTrue(self.doc["properties"], "an empty file would make the feature a no-op")
        for key, item in self.doc["properties"].items():
            with self.subTest(property=key):
                self.assertEqual(normalise_property_name(item["name"]), key)
                self.assertTrue(url_is_clean(item["image_url"]), item["image_url"])
                self.assertTrue(url_is_clean(item["page_url"]), item["page_url"])
                self.assertIn(item["source"], IMAGE_SOURCES)

    def test_no_entry_is_a_data_uri_a_logo_or_an_icon(self):
        for key, item in self.doc["properties"].items():
            with self.subTest(property=key):
                self.assertTrue(hr.looks_like_a_photo_url(item["image_url"]), item["image_url"])

    def test_every_entry_is_a_property_the_reports_can_show(self):
        shown = hr.properties_to_cover()
        self.assertEqual(sorted(set(self.doc["properties"]) - set(shown)), [])

    def test_the_loader_keeps_every_entry_the_file_holds(self):
        media = load_hotel_media()
        self.assertEqual(sorted(media.images), sorted(self.doc["properties"]))


class TheReviewsFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = _strict_load(DEFAULT_REVIEWS_PATH)

    def test_it_is_the_declared_schema_with_a_research_date(self):
        self.assertEqual(self.doc["schema"], "hotel_reviews/1")
        datetime.strptime(self.doc["researched_on"], "%Y-%m-%d")

    def test_each_rating_is_one_sites_own_figure_on_its_own_scale_with_its_count_date_and_page(self):
        for key, item in self.doc["properties"].items():
            self.assertEqual(normalise_property_name(item["name"]), key)
            seen = set()
            for rating in item["ratings"]:
                with self.subTest(property=key, site=rating["source"]):
                    self.assertNotIn(rating["source"].casefold(), seen, "one figure per site")
                    seen.add(rating["source"].casefold())
                    self.assertIn(rating["scale"], (5, 5.0, 10, 10.0))
                    self.assertTrue(0 < rating["score"] <= rating["scale"])
                    self.assertTrue(str(rating["count"]).strip(), "a rating without its review count says nothing")
                    datetime.fromisoformat(rating["observed_at"])
                    self.assertTrue(url_is_clean(rating["source_url"]), rating["source_url"])
                    self.assertNotRegex(rating["source"].lower(), r"average|overall|combined|mean")

    def test_booking_is_out_of_ten_and_google_and_tripadvisor_out_of_five(self):
        for key, item in self.doc["properties"].items():
            for rating in item["ratings"]:
                if rating["source"] == "Booking":
                    self.assertEqual(rating["scale"], 10, key)
                if rating["source"] in ("Google", "TripAdvisor"):
                    self.assertEqual(rating["scale"], 5, key)

    def test_a_site_that_gave_nothing_has_a_reason_and_is_not_also_given_a_figure(self):
        for key, item in self.doc["properties"].items():
            have = {r["source"].casefold() for r in item["ratings"]}
            for site, why in item["not_read"].items():
                with self.subTest(property=key, site=site):
                    self.assertEqual(site, site.lower())
                    self.assertTrue(why.strip())
                    self.assertNotIn(site, have)

    def test_every_entry_is_a_property_the_reports_can_show(self):
        self.assertEqual(sorted(set(self.doc["properties"]) - set(hr.properties_to_cover())), [])

    def test_the_loader_keeps_every_rating_the_file_holds(self):
        media = load_hotel_media()
        held = {k: len(v["ratings"]) for k, v in self.doc["properties"].items() if v["ratings"]}
        self.assertEqual({k: len(v) for k, v in media.ratings.items()}, held)


if __name__ == "__main__":
    unittest.main()


class OnlyAllowedSitesAndNoRefusedPhotosTests(unittest.TestCase):
    ALLOWED = {"Google", "TripAdvisor", "Booking", "Accor"} | set(hr.OPERATOR_RATING_SITES.values())

    def test_every_rating_names_one_of_the_allowed_sites(self):
        for key, item in _strict_load(DEFAULT_REVIEWS_PATH)["properties"].items():
            for rating in item["ratings"]:
                with self.subTest(property=key, source=rating["source"]):
                    self.assertIn(rating["source"], self.ALLOWED)

    def test_no_photo_a_person_refused_is_committed(self):
        refused = set(hr.load_rejects())
        for key, item in _strict_load(DEFAULT_IMAGES_PATH)["properties"].items():
            with self.subTest(property=key):
                self.assertNotIn(item["image_url"], refused)
