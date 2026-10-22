"""The e-mail carries ONE self-contained HTML file with every trip and every resort in full (22 Oct 2026).

Gmail clips an HTML part near 102 KB, so the body sheds the last trips' detail (see test_trip_dossiers.py) and says so.
The owner asked for "full verbose details", so the planner also attaches ``july-trips-full-<date>.html``: the same
dossiers and cards built from the same structures, with no byte budget, with inline CSS only and nothing fetched.
What these tests pin:

* the mailer attaches it (multipart/mixed around the usual text + html alternative) and, with no attachment, the message
  is exactly what it was;
* a send carries it and a dry run neither sends nor writes anywhere;
* it holds every trip id and every dossier section at full detail, and every resort card, whatever the body shed;
* it is self-contained: no script, link, image or frame, no ``src`` at all, no ``url(`` or ``@import``, and every
  ``href`` is a link on an ``<a>`` (a booking page or an in-page anchor);
* the body names the attachment in one line near the top, the plain-text part is as it was, and the file stays far
  below any sensible size bound.

Everything here is SYNTHETIC; the SMTP object is a mock.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from email import message_from_bytes
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    full_detail_filename,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
    render_holiday_report_full,
)
from public_flight_search.jobs import run_holiday_planner
from public_flight_search.mailer import send_html

from test_holiday_email_compact import DEC, JULY, _config, _deals, visible_text
from test_trip_dossiers import NOW, STAMPS, _ids, _reads, _rows

SECTIONS = ("Package vs our build", "Itinerary", "Flights", "What the price covers", "Links")
BOUND_BYTES = 600_000
SMTP_ENV = {"SMTP_USER": "sender@example.invalid", "SMTP_PASSWORD": "x", "REPORT_RECIPIENT": "owner@example.invalid"}


def _full(deals=None, **kw):
    return render_holiday_report_full(
        _config(), generated_at=NOW, deals=_deals(12) if deals is None else deals,
        evidence_stamps=STAMPS, multi_centre_fares=_reads(), **kw)


def _sent_message(smtp):
    sent = smtp.return_value.__enter__.return_value.sendmail.call_args[0][2]
    return message_from_bytes(sent.encode("utf-8") if isinstance(sent, str) else sent)


class MailerTests(unittest.TestCase):
    def _send(self, **kw):
        with patch.dict(os.environ, SMTP_ENV), patch("public_flight_search.mailer.smtplib.SMTP") as smtp:
            send_html("subject", "<p>html</p>", text="plain twin", **kw)
        return _sent_message(smtp)

    def test_an_attachment_rides_beside_the_text_and_html_alternative(self):
        message = self._send(attachments=[("july-trips-full-2026-10-22.html", "<p>full</p>".encode("utf-8"), "text/html")])
        self.assertEqual(message.get_content_type(), "multipart/mixed")
        body, attachment = message.get_payload()
        self.assertEqual(body.get_content_type(), "multipart/alternative")
        self.assertEqual([p.get_content_type() for p in body.get_payload()], ["text/plain", "text/html"])
        self.assertEqual(attachment.get_content_type(), "text/html")
        self.assertEqual(attachment.get_filename(), "july-trips-full-2026-10-22.html")
        self.assertEqual(attachment.get_content_disposition(), "attachment")
        self.assertEqual(attachment.get_payload(decode=True), b"<p>full</p>")

    def test_with_no_attachment_the_message_is_exactly_what_it_was(self):
        message = self._send()
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        self.assertEqual([p.get_content_type() for p in message.get_payload()], ["text/plain", "text/html"])


class TheJobAttachesItOnASendAndNeverOnADryRunTests(unittest.TestCase):
    def _run(self, tmp, *, dry_run, force_send=False):
        env = {
            "HOLIDAY_SEARCH_CONFIG_JSON": JULY.read_text(encoding="utf-8"),
            "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "history.jsonl"),
            **SMTP_ENV,
        }
        with patch.dict(os.environ, env), patch("public_flight_search.mailer.smtplib.SMTP") as smtp:
            result = run_holiday_planner(
                dry_run=dry_run, force_send=force_send,
                hotel_evidence_path=str(Path(tmp) / "absent-hotel.json"),
                live_evidence_path=str(Path(tmp) / "absent-live.json"),
                package_evidence_path=str(Path(tmp) / "absent-package.json"),
                stopover_reads_path=str(Path(tmp) / "absent-reads.json"),
            )
        return result, smtp

    def test_a_send_carries_exactly_one_full_detail_file_named_for_the_season_and_the_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, smtp = self._run(tmp, dry_run=False, force_send=True)
            message = _sent_message(smtp)
        self.assertTrue(result["email_sent"])
        attachments = [p for p in message.walk() if p.get_content_disposition() == "attachment"]
        self.assertEqual(len(attachments), 1)
        name = attachments[0].get_filename()
        self.assertRegex(name, r"^july-trips-full-\d{4}-\d{2}-\d{2}\.html$")
        self.assertEqual(result["full_detail_attachment"], name)
        html = attachments[0].get_payload(decode=True).decode("utf-8")
        self.assertEqual(result["full_detail_attachment_bytes"], len(html.encode("utf-8")))
        self.assertLess(len(html.encode("utf-8")), BOUND_BYTES)
        body = next(p for p in message.walk() if p.get_content_type() == "text/html")
        self.assertIn(name, visible_text(body.get_payload(decode=True).decode("utf-8")), "the body names its attachment")

    def test_a_dry_run_sends_nothing_and_writes_nothing_outside_its_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = sorted(os.listdir(tmp))
            result, smtp = self._run(tmp, dry_run=True, force_send=True)
            after = sorted(os.listdir(tmp))
        self.assertFalse(result["email_sent"])
        smtp.assert_not_called()
        self.assertEqual(before, after, "a dry run wrote a file")

    def test_the_december_planner_attaches_its_own_named_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"HOLIDAY_SEARCH_CONFIG_JSON": DEC.read_text(encoding="utf-8"),
                   "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "history.jsonl"), **SMTP_ENV}
            with patch.dict(os.environ, env), patch("public_flight_search.mailer.smtplib.SMTP") as smtp:
                run_holiday_planner(dry_run=False, force_send=True,
                                    hotel_evidence_path=str(Path(tmp) / "a.json"),
                                    live_evidence_path=str(Path(tmp) / "b.json"))
            message = _sent_message(smtp)
        names = [p.get_filename() for p in message.walk() if p.get_content_disposition() == "attachment"]
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], r"^december-trips-full-\d{4}-\d{2}-\d{2}\.html$")

    def test_the_file_name_sorts_by_date(self):
        self.assertEqual(full_detail_filename(_config(), "2026-10-22T13:25:00+00:00"), "july-trips-full-2026-10-22.html")
        self.assertLess(full_detail_filename(_config(), "2026-10-22T13:25:00+00:00"),
                        full_detail_filename(_config(), "2026-10-25T06:00:00+00:00"))


class TheFileHoldsEverythingInFullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _full()
        cls.trip_ids = [r["trip"].id for r in _rows(_reads())]

    def test_every_trip_has_its_page_with_every_section(self):
        self.assertEqual(sorted(_ids(self.html)), sorted(self.trip_ids))
        for ident in self.trip_ids:
            start = self.html.index(f'id="trip-{ident}"')
            ends = [self.html.find(m, start + 1) for m in ('id="trip-', 'id="resorts"')]
            part = visible_text(self.html[start:min(e for e in ends if e > 0)])
            for section in SECTIONS:
                self.assertIn(section, part, (ident, section))

    def test_every_page_is_at_full_detail_whatever_the_body_budget_was(self):
        with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", 20_000):
            html = _full()
        self.assertNotIn("Shortened to fit", visible_text(html))
        self.assertGreaterEqual(html.count("google.com/travel/hotels"), 20, "the second-choice links are all there")
        text = visible_text(html)
        for marker in ("Why it is here", "The catch", "is made of", "Basis:"):
            self.assertIn(marker, text)

    def test_every_resort_card_is_there_not_only_the_first_five_or_eight(self):
        for index in range(1, 13):
            self.assertIn(f'id="deal-{index}"', self.html)
        self.assertNotIn("further deal(s) not shown", self.html)

    def test_it_is_a_whole_document_that_reads_on_a_phone(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertIn('<meta name="viewport"', self.html)
        self.assertIn("<title>", self.html)

    def test_it_says_it_is_the_full_copy_and_does_not_point_at_an_attachment_of_its_own(self):
        text = visible_text(self.html)
        self.assertIn("full-detail copy", text)
        self.assertNotIn("attached file", text)

    def test_it_stays_far_below_a_sensible_size_bound(self):
        self.assertLess(len(self.html.encode("utf-8")), BOUND_BYTES)


class TheFileIsSelfContainedTests(unittest.TestCase):
    FORBIDDEN_TAGS = {"script", "link", "img", "iframe", "object", "embed", "source", "video", "audio", "base", "form"}

    def test_nothing_is_fetched_and_every_href_is_a_link_on_an_anchor(self):
        problems = []
        anchors = 0

        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                nonlocal anchors
                if tag in TheFileIsSelfContainedTests.FORBIDDEN_TAGS:
                    problems.append(f"<{tag}>")
                for name, value in attrs:
                    if name == "src":
                        problems.append(f"{tag} src={value}")
                    if name == "href":
                        if tag != "a":
                            problems.append(f"{tag} href={value}")
                        else:
                            anchors += 1
                            if not (value.startswith("#") or value.startswith("https://")):
                                problems.append(f"a href={value}")

        html = _full()
        Parser().feed(html)
        self.assertEqual(problems, [])
        self.assertGreater(anchors, 100)
        self.assertNotIn("url(", html)
        self.assertNotIn("@import", html)
        self.assertNotIn("http://", html)


class TheBodyNamesItAndTheTextIsAsItWasTests(unittest.TestCase):
    def _body(self, **kw):
        return render_holiday_report_compact(
            _config(), generated_at=NOW, deals=_deals(2), evidence_stamps=STAMPS, multi_centre_fares=_reads(), **kw)

    def test_the_body_says_in_one_line_near_the_top_that_the_full_detail_is_attached(self):
        html = self._body(attachment_name="july-trips-full-2026-10-22.html")
        text = visible_text(html)
        line = "The full detail of every trip and every resort is in the attached file, july-trips-full-2026-10-22.html."
        self.assertIn(line, text)
        self.assertLess(text.index(line), text.index("Every option at a glance"))
        self.assertEqual(text.count("attached file"), 1)

    def test_without_an_attachment_the_body_claims_none(self):
        self.assertNotIn("attached", visible_text(self._body()))

    def test_the_plain_text_part_is_as_it_was(self):
        a = render_holiday_report_compact_text(_config(), generated_at=NOW, deals=_deals(2), evidence_stamps=STAMPS,
                                               multi_centre_fares=_reads())
        self.assertNotIn("attached", a)
        self.assertEqual(a.count("Itinerary"), len(_rows(_reads())), "the text part is still every dossier in full")


if __name__ == "__main__":
    unittest.main()
