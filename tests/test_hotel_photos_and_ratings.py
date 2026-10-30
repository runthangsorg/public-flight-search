"""A photo and each site's own rating beside every property (owner, 23 Oct 2026).

"i want images in the july holiday mail of the hotel, like you did for the dec mail", then: "check google reviews,
tripadvisor, booking.com etc. reviews and ratings alongside it so you can get pics from those".

What these tests pin, from SYNTHETIC media (no network, no data file):

* the loader keeps only entries that obey the rules (https, no tracking, key = normalised name) and tolerates a missing file;
* a resort card with a photo shows it across the top, linked to the link the card already has, with the property name as
  ``alt``, fixed width attributes and no ``data:`` URI; a card without one shows no image tag at all;
* a trip page shows one thumbnail beside each named property in the Itinerary, linked to that property's booking search with
  its own dates; a property without a photo shows no tag; the overview and the plain text carry no image;
* each site's figure is printed on its own scale (Booking /10, Google and TripAdvisor /5) with its count and read date, linking
  to the page it came from, in the order Google, TripAdvisor, Booking, with NO combined figure; a site that gave nothing is
  named as not read with the reason's gist; a property with no read at all keeps the old wording;
* the plain text carries the ratings too, the attachment carries the photos, the body stays inside its byte budget, and the
  markup stays well formed.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search import trip_dossier as td
from public_flight_search.holiday_email import (
    render_holiday_report_compact,
    render_holiday_report_compact_text,
    render_holiday_report_full,
)
from public_flight_search.hotel_evidence import HotelRating, normalise_property_name as norm
from public_flight_search.hotel_media import HotelMedia, load_hotel_media, merge_ratings

from test_holiday_email_compact import _config, _deal, _deals, visible_text
from test_trip_dossiers import NOW, STAMPS, UNLIMITED, WellFormedTests, _html, _ids, _reads, _slice, _table_ids, _text

IMG = "https://cdn.example.org/photos/{}.jpg"


def _image(name, source="official"):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return {"name": name, "image_url": IMG.format(slug), "page_url": f"https://www.example.org/{slug}", "source": source}


def _rating(name, source, score, scale, count, observed="2026-10-23T09:00:00+00:00", url=None):
    return HotelRating(property_name=name, source=source, score=score, scale=scale, review_count=count,
                       where="researched page", source_url=url or f"https://www.example.org/{source.lower()}/{norm(name)}",
                       observed_at=observed)


def _media(images=(), ratings=(), not_read=None):
    by_name: dict[str, list] = {}
    for rating in ratings:
        by_name.setdefault(norm(rating.property_name), []).append(rating)
    return HotelMedia(images={norm(n): _image(n) for n in images},
                      ratings={k: merge_ratings(v) for k, v in by_name.items()},
                      not_read={norm(k): v for k, v in (not_read or {}).items()})


def _flat(html):
    """Visible text with every run of whitespace (the tags' own gaps) collapsed to one space."""
    return " ".join(visible_text(html).split())


def _img_tags(html):
    return re.findall(r"<img\b[^>]*>", html)


class TheLoaderKeepsOnlyWhatObeysTheRulesTests(unittest.TestCase):
    def _write(self, directory, images=None, reviews=None):
        import json

        ip, rp = Path(directory) / "images.json", Path(directory) / "reviews.json"
        if images is not None:
            ip.write_text(json.dumps({"schema": "hotel_images/1", "properties": images}), encoding="utf-8")
        if reviews is not None:
            rp.write_text(json.dumps({"schema": "hotel_reviews/1", "properties": reviews}), encoding="utf-8")
        return str(ip), str(rp)

    def test_valid_entries_are_kept_and_found_by_any_spelling_of_the_name(self):
        with tempfile.TemporaryDirectory() as d:
            ip, rp = self._write(d, {norm("Giraffe Manor"): _image("Giraffe Manor")},
                                 {norm("Giraffe Manor"): {"name": "Giraffe Manor", "ratings": [
                                     {"source": "Booking", "score": 9.1, "scale": 10, "count": "640",
                                      "observed_at": "2026-10-23T09:00:00+00:00", "source_url": "https://www.booking.com/hotel/ke/giraffe.html"}],
                                  "not_read": {"tripadvisor": "wall: datadome-challenge"}}})
            media = load_hotel_media(ip, rp)
        self.assertEqual(media.image_for("GIRAFFE  manor")["image_url"], IMG.format("giraffe-manor"))
        self.assertEqual([(r.source, r.score, r.scale, r.review_count) for r in media.ratings_for("Giraffe Manor")],
                         [("Booking", 9.1, 10.0, "640")])
        self.assertEqual(media.not_read_for("Giraffe Manor"), {"tripadvisor": "wall: datadome-challenge"})

    def test_an_entry_that_breaks_a_rule_is_dropped_not_repaired(self):
        bad = {
            norm("Http One"): {**_image("Http One"), "image_url": "http://cdn.example.org/a.jpg"},
            norm("Tracked Two"): {**_image("Tracked Two"), "page_url": "https://www.example.org/x?utm_source=mail"},
            "wrongkey": _image("Three Hotel"),
            norm("Fragment Four"): {**_image("Fragment Four"), "image_url": "https://cdn.example.org/a.jpg#x"},
        }
        with tempfile.TemporaryDirectory() as d:
            ip, rp = self._write(d, bad, {norm("Five Hotel"): {"name": "Five Hotel", "ratings": [
                {"source": "Google", "score": 6, "scale": 5, "count": "9", "source_url": "https://g.example.org/x"},
                {"source": "Google", "score": 4, "scale": 5, "count": "9", "source_url": "http://g.example.org/x"}]}})
            media = load_hotel_media(ip, rp)
        self.assertEqual(dict(media.images), {})
        self.assertEqual(dict(media.ratings), {})

    def test_missing_unreadable_or_wrongly_shaped_files_give_an_empty_media(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dict(load_hotel_media(str(Path(d) / "a"), str(Path(d) / "b")).images), {})
            (Path(d) / "c.json").write_text("not json", encoding="utf-8")
            (Path(d) / "d.json").write_text('{"schema": "other/1", "properties": {"x": {}}}', encoding="utf-8")
            self.assertEqual(dict(load_hotel_media(str(Path(d) / "c.json"), str(Path(d) / "d.json")).images), {})

    def test_the_newest_read_of_a_site_wins_and_nothing_is_averaged(self):
        old = _rating("X Hotel", "Google", 4.0, 5, "100", observed="2026-10-02T00:00:00+00:00")
        new = _rating("X Hotel", "Google", 4.4, 5, "120", observed="2026-10-23T00:00:00+00:00")
        booking = _rating("X Hotel", "Booking", 8.5, 10, "50")
        ta = _rating("X Hotel", "TripAdvisor", 4.5, 5, "70")
        merged = merge_ratings((old, booking), (new, ta))
        self.assertEqual([(r.source, r.score) for r in merged], [("Google", 4.4), ("TripAdvisor", 4.5), ("Booking", 8.5)])


class AResortCardShowsItsPhotoTests(unittest.TestCase):
    def _html(self, media, deals=None, **kw):
        return render_holiday_report_compact(_config(), generated_at=NOW, deals=deals or [_deal(0)], evidence_stamps=STAMPS,
                                             hotel_media=media, **kw)

    def _card(self, html):
        return html[html.index('id="deal-1"'):]

    def test_the_photo_is_at_the_top_of_the_card_linked_to_the_cards_own_booking_link(self):
        html = self._html(_media(images=["Test Resort 0"]))
        card = self._card(html)
        tag = _img_tags(card)[0]
        self.assertIn('src="https://cdn.example.org/photos/test-resort-0.jpg"', tag)
        self.assertIn('alt="Test Resort 0"', tag)
        self.assertRegex(tag, r'width="\d+"')
        self.assertIn("max-width:100%", tag)
        self.assertNotIn("data:", tag)
        self.assertLess(card.index("<img"), card.index("Test Resort 0 "), "the photo comes before the name")
        # the link the card already has first: "Book the hotel"
        self.assertRegex(card[card.rindex("<a ", 0, card.index("<img")):card.index("<img")], r'href="https://example\.invalid/hotel"')

    def test_a_card_without_a_photo_shows_no_image_tag_and_no_empty_box(self):
        html = self._html(_media(images=["Some Other Hotel"]))
        self.assertEqual(_img_tags(html), [])

    def test_with_no_media_at_all_the_report_has_no_image(self):
        self.assertEqual(_img_tags(self._html(None)), [])

    def test_each_card_gets_only_its_own_photo(self):
        html = self._html(_media(images=["Test Resort 1"]), deals=_deals(3))
        self.assertEqual(len(_img_tags(html)), 1)
        self.assertIn("test-resort-1.jpg", _img_tags(html)[0])

    def test_the_plain_text_carries_no_image(self):
        text = render_holiday_report_compact_text(_config(), generated_at=NOW, deals=[_deal(0)], evidence_stamps=STAMPS,
                                                  hotel_media=_media(images=["Test Resort 0"]))
        self.assertNotIn("cdn.example.org", text)
        self.assertNotIn("<img", text)


class ATripPageShowsAThumbnailBesideEachNamedPropertyTests(unittest.TestCase):
    NAMES = ["Mount Meru Hotel", "Kirurumu Tarangire Lodge", "Breezes Beach Club & Spa"]

    def _page(self, media, level=None):
        html = _html(fares=_reads(["AF-01"]), hotel_media=media, budget=UNLIMITED)
        return _slice(html, "trip-AF-01")

    def test_a_property_with_a_photo_gets_a_thumbnail_linked_to_its_booking_search_with_its_own_dates(self):
        part = self._page(_media(images=["Kirurumu Tarangire Lodge"]))
        tags = _img_tags(part)
        self.assertEqual(len(tags), 1)
        self.assertIn('alt="Kirurumu Tarangire Lodge"', tags[0])
        self.assertIn('width="120"', tags[0])
        before = part[:part.index(tags[0])]
        href = re.findall(r'href="([^"]+)"', before)[-1].replace("&amp;", "&")
        self.assertIn("booking.com", href)
        self.assertIn("checkin=2027-06-28", href)
        self.assertIn("checkout=2027-07-01", href)

    def test_properties_without_a_photo_get_no_tag(self):
        part = self._page(_media(images=["Mount Meru Hotel"]))
        self.assertEqual(len(_img_tags(part)), 1)
        self.assertNotIn("kirurumu-tarangire-lodge.jpg", part)

    def test_every_named_property_can_have_one(self):
        part = self._page(_media(images=self.NAMES))
        self.assertEqual(len(_img_tags(part)), 3)

    def test_the_short_form_has_no_thumbnails_and_the_overview_has_none(self):
        media = _media(images=self.NAMES)
        short = _html(fares=_reads(["AF-01"]), hotel_media=media, budget=20_000, deals=_deals(2))
        attachment = render_holiday_report_full(_config(), generated_at=NOW, deals=_deals(2), evidence_stamps=STAMPS,
                                                multi_centre_fares=_reads(["AF-01"]), hotel_media=media)
        self.assertIn("AF-01", _table_ids(short), "the table lists the trip whether its page fits or not")
        if 'id="trip-AF-01"' in short:
            self.assertEqual(_img_tags(_slice(short, "trip-AF-01")), [],
                             "a page still in the tiny body is the short form, which carries no thumbnail")
        else:
            self.assertIn('id="trip-AF-01"', attachment,
                          "a page the tiny body could not hold is in the attachment, not gone")
        table = short[short.index("Every option at a glance"):short.index('id="trips"')]
        self.assertEqual(_img_tags(table), [])

    def test_no_image_has_a_data_uri_or_misses_its_alt_and_width(self):
        html = _html(fares=_reads(), hotel_media=_media(images=self.NAMES), budget=UNLIMITED)
        for tag in _img_tags(html):
            self.assertNotIn("data:", tag)
            self.assertRegex(tag, r'alt="[^"]+"')
            self.assertRegex(tag, r'width="\d+"')
            self.assertRegex(tag, r'src="https://')

    def test_the_attachment_carries_the_photos_at_every_level(self):
        media = _media(images=self.NAMES)
        with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", 20_000):
            html = render_holiday_report_full(_config(), generated_at=NOW, deals=_deals(2), evidence_stamps=STAMPS,
                                              multi_centre_fares=_reads(["AF-01"]), hotel_media=media)
        self.assertEqual(len(_img_tags(_slice(html, "trip-AF-01"))), 3)

    def test_the_plain_text_carries_no_image_for_a_trip_either(self):
        text = _text(fares=_reads(["AF-01"]), hotel_media=_media(images=self.NAMES))
        self.assertNotIn("<img", text)
        self.assertNotIn("cdn.example.org", text)


class EachSitesRatingIsShownOnItsOwnScaleTests(unittest.TestCase):
    LODGE = "Kirurumu Tarangire Lodge"

    def _text_of_page(self, media, **kw):
        html = _html(fares=_reads(["AF-01"]), hotel_media=media, budget=UNLIMITED, **kw)
        return _slice(html, "trip-AF-01")

    def _three(self):
        return [_rating(self.LODGE, "Google", 4.6, 5, "2,310", observed="2026-10-02T15:00:00+00:00"),
                _rating(self.LODGE, "TripAdvisor", 4.5, 5, "1,870", observed="2026-10-15T19:45:00+00:00"),
                _rating(self.LODGE, "Booking", 8.9, 10, "640", observed="2026-10-23T09:00:00+00:00")]

    def test_each_figure_has_its_scale_count_and_read_date_in_google_tripadvisor_booking_order(self):
        text = _flat(self._text_of_page(_media(ratings=self._three())))
        line = text[text.index("Google 4.6/5"):]
        line = line[:line.index("Breezes")]
        self.assertRegex(line, r"Google 4\.6/5 \(2,310 reviews, read 2 Oct\) · TripAdvisor 4\.5/5 \(1,870 reviews, read 15 Oct\) · "
                               r"Booking 8\.9/10 \(640 reviews, read 23 Oct\)")

    def test_each_figure_links_to_the_page_it_came_from(self):
        part = self._text_of_page(_media(ratings=self._three()))
        for site in ("google", "tripadvisor", "booking"):
            self.assertIn(f'href="https://www.example.org/{site}/{norm(self.LODGE)}"', part)

    def test_no_combined_figure_appears(self):
        text = visible_text(self._text_of_page(_media(ratings=self._three())))
        for invented in ("4.5 average", "average", "overall", "6.0", "4.7/5", "8.9/10 and"):
            self.assertNotIn(invented, text)

    def test_only_the_sites_with_a_read_are_shown_and_the_others_are_named_as_not_read(self):
        media = _media(ratings=[self._three()[0]], not_read={self.LODGE: {"tripadvisor": "wall: datadome-challenge",
                                                                          "booking": "no page found"}})
        text = visible_text(self._text_of_page(media))
        self.assertIn("Google 4.6/5", text)
        self.assertNotIn("TripAdvisor 4.", text)
        self.assertNotIn("Booking 8", text)
        self.assertIn("not read: TripAdvisor (walled), Booking (no page found)", text)

    def test_a_property_with_a_read_stops_the_trip_saying_no_rating_was_collected_for_any_property(self):
        text = visible_text(self._text_of_page(_media(ratings=self._three())))
        self.assertNotIn("not collected for any property on this trip", text)
        self.assertEqual(text.count("guest rating not collected"), 2, "the other two lodges say so for themselves")

    def test_with_no_read_for_any_property_the_old_wording_stands(self):
        text = visible_text(self._text_of_page(_media()))
        self.assertIn("guest rating not collected for any property on this trip", text)

    def test_a_rating_from_a_handful_of_reviews_is_shown_with_its_count_not_hidden(self):
        text = visible_text(self._text_of_page(_media(ratings=[_rating(self.LODGE, "Booking", 9.6, 10, "3")])))
        self.assertIn("Booking 9.6/10 (3 reviews", text)

    def test_the_researched_read_and_the_evidence_read_of_one_site_keep_the_newer(self):
        evidence = {norm(self.LODGE): (_rating(self.LODGE, "Google", 4.1, 5, "900", observed="2026-10-02T00:00:00+00:00"),)}
        media = _media(ratings=[_rating(self.LODGE, "Google", 4.6, 5, "2,310", observed="2026-10-23T00:00:00+00:00")])
        text = visible_text(self._text_of_page(media, ratings=evidence))
        self.assertIn("Google 4.6/5", text)
        self.assertNotIn("Google 4.1/5", text)

    def test_a_resort_card_shows_the_same_line_and_merges_with_the_rating_its_deal_holds(self):
        held = _rating("Test Resort 0", "Accor", 4.4, 5, "497", observed="2026-10-02T00:00:00+00:00")
        media = _media(ratings=[_rating("Test Resort 0", "Google", 4.6, 5, "2,310"),
                                _rating("Test Resort 0", "Booking", 8.9, 10, "640")])
        html = render_holiday_report_compact(_config(), generated_at=NOW, deals=[_deal(0, hotel_ratings=(held,))],
                                             evidence_stamps=STAMPS, hotel_media=media)
        card = _flat(html[html.index('id="deal-1"'):])
        self.assertRegex(card, r"Google 4\.6/5 \(2,310 reviews, read 23 Oct\) · Booking 8\.9/10 \(640 reviews, read 23 Oct\)")
        self.assertIn("Accor 4.4/5", card)
        self.assertNotIn("guest rating not collected", card)

    def test_the_plain_text_carries_the_ratings_for_trips_and_cards(self):
        media = _media(ratings=self._three() + [_rating("Test Resort 0", "Google", 4.6, 5, "2,310")])
        text = render_holiday_report_compact_text(_config(), generated_at=NOW, deals=[_deal(0)], evidence_stamps=STAMPS,
                                                  multi_centre_fares=_reads(["AF-01"]), hotel_media=media)
        self.assertIn("Google 4.6/5 (2,310 reviews, read 2 Oct)", text)
        self.assertIn("Booking 8.9/10 (640 reviews, read 23 Oct)", text)
        self.assertGreaterEqual(text.count("Google 4.6/5"), 2)


class TheBudgetAndTheMarkupSurviveTests(unittest.TestCase):
    def _media_for_everyone(self):
        names = {l.name for t in hol.load_multi_centre(season="summer") for s in t.stops for l in s.lodges} if hasattr(hol, "load_multi_centre") else set()
        from public_flight_search.multi_centre import load_multi_centre

        names = {l.name for season in ("summer", "winter") for t in load_multi_centre(season=season)
                 for s in t.stops for l in s.lodges}
        images = sorted(names) + [f"Test Resort {i}" for i in range(12)]
        ratings = [_rating(n, "Google", 4.5, 5, "1,000") for n in sorted(names)[:10]]
        return _media(images=images, ratings=ratings)

    def test_every_trip_and_card_with_a_photo_still_fits_the_body_budget_and_is_balanced(self):
        media = self._media_for_everyone()
        for budget in (hol.EMAIL_HTML_BUDGET_BYTES, 20_000):
            html = _html(fares=_reads(), hotel_media=media, deals=_deals(4), budget=budget)
            self.assertLessEqual(len(html.encode("utf-8")), max(budget, 0) if budget == hol.EMAIL_HTML_BUDGET_BYTES else 10 ** 9)
            self.assertEqual(WellFormedTests()._unbalanced(html), [], budget)
        body = _html(fares=_reads(), hotel_media=media, deals=_deals(4), budget=hol.EMAIL_HTML_BUDGET_BYTES)
        self.assertEqual(sorted(_ids(body)), sorted(_ids(_html(fares=_reads(), deals=_deals(4), budget=UNLIMITED))),
                         "no trip leaves the page for a photo")

    def test_the_full_attachment_is_balanced_and_has_a_photo_for_every_named_property(self):
        media = self._media_for_everyone()
        html = render_holiday_report_full(_config(), generated_at=NOW, deals=_deals(4), evidence_stamps=STAMPS,
                                          multi_centre_fares=_reads(), hotel_media=media)
        self.assertEqual(WellFormedTests()._unbalanced(html), [])
        self.assertGreaterEqual(len(_img_tags(html)), 28)


if __name__ == "__main__":
    unittest.main()
