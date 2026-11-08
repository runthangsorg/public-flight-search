"""The repeated small print is printed once, in a "How to read this" footer (owner, 8 Nov 2026).

Five sentences repeated on every trip page pushed the 8 Nov July body past Gmail's ~102 KB clip, which then cut the
booking links off the last pages:

* "Business long-haul is Business on every flight over 8 hours ..." (``CABIN_NOTE``)
* "All clock times are local to each airport."
* "This trip's price includes its own flights, so it does not change with these reads ..."
* "The flights search link opens Economy, not the cabin this price was read in."
* "Shortened to fit Gmail's size limit: the booking links and the rest are in the plain-text version."

Each now appears once, in the footer (a trip-specific exception stays inline in a few words), and with the example
config and a read for every trip the body stays under the byte budget with every trip page in it keeping its booking
links. Synthetic reads throughout.
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from public_flight_search import holiday_email as he
from public_flight_search import holidays as hol
from public_flight_search.holiday_email import multi_centre_wanted

from test_holiday_email_compact import _config, _deals, visible_text
from test_price_says_what_it_covers import deal_read, load
from test_trip_dossiers import NOW, STAMPS, _ids, _slice

REPEATED = (
    "Business long-haul is Business on every flight over 8 hours",
    "All clock times are local to each airport",
    "does not change with these reads",
    "The flights search link opens Economy, not the cabin this price was read in",
    "the booking links and the rest are in the plain-text version",
    "the longest notes are in the plain-text version",
)
FOOTER = "How to read this"


def _every_trip_read(*, business=True):
    """An Economy read for every trip, and a Business one that is a deal (so its small print is relevant)."""
    rows = []
    for want in multi_centre_wanted(_config()):
        rows.append(deal_read(want["trip"], "ECONOMY", 5_000))
        if business:
            rows.append(deal_read(want["trip"], "MIXED", 9_000))
    return load(rows)


def _renders(fares, *, config=None, deals=None):
    config = config or _config()
    deals = _deals(3) if deals is None else deals
    kw = dict(generated_at=NOW, deals=deals, evidence_stamps=STAMPS, multi_centre_fares=fares)
    return (he.render_holiday_report_compact(config, attachment_name="july-trips-full.html", **kw),
            he.render_holiday_report_compact_text(config, **kw),
            he.render_holiday_report_full(config, **kw))


class EachSentenceIsPrintedOnceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", 10 ** 9):
            cls.html, cls.text, cls.full = _renders(_every_trip_read())

    def test_the_footer_is_there_once_in_every_part(self):
        for name, part in (("body", visible_text(self.html)), ("text", self.text), ("attachment", visible_text(self.full))):
            self.assertEqual(part.count(FOOTER), 1, name)

    def test_no_sentence_repeats_on_the_trip_pages(self):
        for name, part in (("body", visible_text(self.html)), ("text", self.text), ("attachment", visible_text(self.full))):
            for sentence in REPEATED:
                self.assertLessEqual(part.count(sentence), 1, f"{name}: {sentence}")
            for ident in _ids(self.html):
                page = visible_text(_slice(self.html, f"trip-{ident}"))
                for sentence in REPEATED:
                    self.assertNotIn(sentence, page, f"{ident}: {sentence}")

    def test_the_footer_carries_each_explanation(self):
        footer = visible_text(self.html)[visible_text(self.html).index(FOOTER):]
        for words in ("Business long-haul is Business on every flight over 8 hours", "local to each airport",
                      "includes them, so it does not change with the flight reads", "opens Economy"):
            self.assertIn(words, footer, words)

    def test_a_trip_specific_exception_stays_inline_in_a_few_words(self):
        page = visible_text(_slice(self.html, "trip-AF-06"))
        self.assertIn("Search link opens Economy.", page)
        self.assertIn("Reads for comparison only.", page)


class TheBodyKeepsItsBookingLinksTests(unittest.TestCase):
    """The example config, a read for every trip, the real byte budget."""

    @classmethod
    def setUpClass(cls):
        config = _config(complete_price_only=True)
        cls.html, _text, cls.full = _renders(_every_trip_read(business=False), config=config, deals=_deals(3))

    def test_the_body_fits_the_budget(self):
        self.assertLessEqual(len(self.html.encode("utf-8")), hol.EMAIL_HTML_BUDGET_BYTES)

    def test_every_trip_page_in_the_body_keeps_its_booking_and_search_links(self):
        ids = _ids(self.html)
        self.assertTrue(ids)
        for ident in ids:
            with self.subTest(trip=ident):
                page = _slice(self.html, f"trip-{ident}")
                self.assertIn(">Flights search ↗<", page)
                full_page = _slice(self.full, f"trip-{ident}")
                self.assertEqual(len(re.findall(r'href="https://www\.booking\.com/', page)),
                                 len(re.findall(r'href="https://www\.booking\.com/', full_page)),
                                 "every Booking.com link of the full page is in the body")

    def test_every_trip_is_in_the_body_or_the_attachment(self):
        wanted = {w["trip"] for w in multi_centre_wanted(_config())}
        self.assertEqual(set(_ids(self.html)) | set(_ids(self.full)), wanted)


if __name__ == "__main__":
    unittest.main()


class TheFooterSaysOnlyWhatIsTrueTests(unittest.TestCase):
    def test_with_nothing_shortened_the_footer_does_not_say_a_page_is_shorter(self):
        with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", 10 ** 9):
            html, _text, _full = _renders(_every_trip_read())
        footer = visible_text(html)[visible_text(html).index(FOOTER):]
        self.assertNotIn("page here is shorter", footer)

    def test_with_pages_shortened_it_says_where_the_full_pages_are(self):
        html, _text, _full = _renders(_every_trip_read())
        self.assertIn('data-level="', html, "the fixture needs a shortened page")
        footer = visible_text(html)[visible_text(html).index(FOOTER):]
        self.assertIn("july-trips-full.html and the plain-text version have it in full", footer)

    def test_the_bundled_flights_sentence_covers_an_estimate_as_well_as_a_package(self):
        self.assertIn("a package or an estimate", he.HOW_TO_READ_PACKAGE)
