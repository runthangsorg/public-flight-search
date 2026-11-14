"""The July e-mail body is a short list of confirmed prices and searches, each with where it was found (owner, 8 Nov
2026): "too dense and hard to read and repetitive. i only want confirmed prices and searches with links and details of
where you found what. confirmed package holidays can be included from real priced sites like tui, expedia, etc."

Synthetic reads throughout.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from public_flight_search import holiday_digest as hd
from public_flight_search.holiday_email import _multi_centre_rows
from public_flight_search.package_evidence import PackagePrice

from public_flight_search import holidays as hol
from public_flight_search.jobs import run_holiday_planner

from test_full_detail_attachment import SMTP_ENV, _sent_message
from test_holiday_email_compact import JULY, _config, visible_text
from test_price_says_what_it_covers import BUILD, PACKAGE, deal_read, load

NOW = "2026-11-08T20:00:00+00:00"


def _package(name="Paradise Resort", key="antalya", total=6_400.0, cabin="ECONOMY", operator="TUI", **kw):
    fields = dict(
        operator_key=operator.lower(), operator=operator, property_name=name, destination_key=key, season="summer",
        departure_airport="LHR", outbound_date="2027-06-27", return_date="2027-07-11", nights=14, adults=5, children=0,
        rooms=2, board="BB", total_gbp=total, price_basis="whole_party_total", price_how="",
        read_method="dom-text", link_kind="deep-link", source_url=f"https://example.org/SYNTHETIC-{name.replace(' ', '-')}",
        observed_at="2026-11-08T18:00:00+00:00", flight_summary="", includes=(), flight_cabin=cabin)
    fields.update(kw)
    return PackagePrice(**fields)


def _build(packages=(), reads=(), watch=None):
    rows = _multi_centre_rows(_config(), fares=load(list(reads)))
    return hd.build_digest(_config(), rows=rows, package_prices={i: p for i, p in enumerate(packages)}, watch=watch,
                           generated_at=NOW)


def _text(digest):
    return hd.render_digest_text(_config(), digest, generated_at=NOW)


def _html(digest):
    return hd.render_digest_html(_config(), digest, generated_at=NOW)


class ConfirmedPackageCardTests(unittest.TestCase):
    def test_a_confirmed_package_is_one_card_with_where_it_was_found(self):
        digest = _build(packages=[_package()])
        self.assertEqual([c.title for c in digest.cards], ["Paradise Resort"])
        html, text = _html(digest), _text(digest)
        for part in (html, text):
            self.assertIn("£6,400", part)
            self.assertIn("14 nights", part)
            self.assertIn("27 Jun", part)
            self.assertIn("TUI", part)
            self.assertIn("8 Nov", part)
        self.assertIn('href="https://example.org/SYNTHETIC-Paradise-Resort"', html)

    def test_an_economy_package_whose_flight_has_a_leg_over_eight_hours_is_not_offered(self):
        digest = _build(packages=[_package(name="Far Beach", key="koh_samui", total=9_000.0)])
        self.assertEqual(digest.cards, ())
        self.assertIn("Far Beach", digest.not_priced)
        self.assertNotIn("£9,000", _html(digest))

    def test_a_business_package_to_a_far_place_is_offered(self):
        digest = _build(packages=[_package(name="Far Beach", key="koh_samui", total=19_000.0, cabin="BUSINESS")])
        self.assertEqual([c.title for c in digest.cards], ["Far Beach"])

    def test_halal_first_among_equals_and_only_when_sourced(self):
        a = _package(name="Alpha Resort", total=6_400.0)
        b = _package(name="Vila Ombak", total=6_700.0)
        digest = _build(packages=[a, b])
        self.assertEqual([c.title for c in digest.cards], ["Vila Ombak", "Alpha Resort"], "same £1,000 band: halal first")
        self.assertIn("halal food on site", _html(digest))
        self.assertEqual([c.halal for c in digest.cards], ["halal food on site", ""])
        far = _build(packages=[_package(name="Alpha Resort", total=3_000.0), b])
        self.assertEqual([c.title for c in far.cards], ["Alpha Resort", "Vila Ombak"], "a cheaper band still comes first")


class FlightSearchCardTests(unittest.TestCase):
    def test_a_trip_with_a_business_read_is_a_flights_only_card_with_its_search_link(self):
        digest = _build(reads=[deal_read(BUILD, "MIXED", 8_000)])
        card = next(c for c in digest.cards if c.kind == "flights")
        self.assertIn("flights only", card.covers.lower())
        self.assertEqual(card.total_gbp, 8_000.0)
        self.assertTrue(card.url.startswith("https://"))
        self.assertIn("Self-build", card.title)

    def test_the_nights_are_the_nights_between_the_dates_shown(self):
        # A read for later dates than the plan prices the trip (no_unplanned_nights): the card counts the dates it prints.
        rows = [dict(r, **{"return": "2027-07-14", "nights": 10})
                for r in _multi_centre_rows(_config(), fares=load([deal_read(BUILD, "MIXED", 8_000)])) if r["trip"].id == BUILD]
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW)
        card = digest.cards[0]
        self.assertEqual(card.dates, "27 Jun – 14 Jul")
        self.assertEqual(card.nights, 17)
        self.assertIn("stays are planned for 10 of the 17 nights", card.facts[0])

    def test_an_economy_read_with_a_long_leg_is_not_a_card(self):
        digest = _build(reads=[deal_read(BUILD, "ECONOMY", 4_000)])
        self.assertFalse([c for c in digest.cards if "Kruger" in c.title])

    def test_an_unread_trip_is_only_a_name_in_the_not_yet_priced_list(self):
        digest = _build()
        self.assertEqual(digest.cards, ())
        self.assertTrue(any("Kruger" in n for n in digest.not_priced))


class NothingEstimatedTests(unittest.TestCase):
    def test_the_body_has_no_catalogue_estimate_range_or_no_reads_boilerplate(self):
        digest = _build(packages=[_package()], reads=[deal_read(BUILD, "MIXED", 8_000)])
        for part in (_html(digest), _text(digest)):
            for banned in ("estimate", "from £", "no reads loaded", "range", "Winelands", "catalogue", "–£"):
                self.assertNotIn(banned, part, banned)

    def test_the_watchlist_is_names_only_and_ends_the_email(self):
        digest = _build()
        for name in ("Vila Ombak", "Angsana Velavaru"):
            self.assertIn(name, digest.not_priced)
        html = _html(digest)
        self.assertEqual(html.count("Not yet priced"), 1)
        self.assertLess(html.index("Vila Ombak"), len(html))
        self.assertIn("seaplane", html)

    def test_the_body_stays_under_ninety_kilobytes_and_dark_text_on_light(self):
        digest = _build(packages=[_package(name=f"Resort {i}", total=5_000.0 + i) for i in range(40)])
        html = _html(digest)
        self.assertLess(len(html.encode("utf-8")), 90_000)
        self.assertNotRegex(html, r"background:\s*#(0|1|2)[0-9a-f]{5}")


def _hidden_rows(carriers):
    """The rows of one trip whose business read was set aside, with its carriers recorded."""
    rows = [r for r in _multi_centre_rows(_config(), fares=load([deal_read(BUILD, "ECONOMY", 4_000)]))
            if r["trip"].id == BUILD]
    return [dict(r, business_hidden={"saving": None, "travellers": 5,
                                     "reason": "no long flight on a quality carrier",
                                     "carriers": list(carriers)}) for r in rows]


class BusinessHiddenReasonTests(unittest.TestCase):
    """A business fare WAS read, on an airline the rule does not accept: say so (owner, 14 Nov 2026)."""

    def _reason(self, carriers):
        digest = hd.build_digest(_config(), rows=_hidden_rows(carriers), package_prices={}, watch=(),
                                 generated_at=NOW)
        self.assertEqual(digest.cards, ())
        return [p.reason for p in digest.pending if not p.group][0]

    def test_the_reason_names_the_airline_the_fare_was_read_on(self):
        self.assertEqual(self._reason(["SYNTHETIC Air"]),
                         "a business fare was read on SYNTHETIC Air, which is not on the accepted airline list; "
                         "a fare on an accepted airline is still to be read")

    def test_it_names_every_carrier_of_the_read(self):
        self.assertIn("SYNTHETIC Air, Second SYNTHETIC Air", self._reason(["SYNTHETIC Air", "Second SYNTHETIC Air"]))

    def test_with_no_carrier_recorded_it_still_says_a_fare_was_read(self):
        self.assertEqual(self._reason([]),
                         "a business fare was read, but not on an accepted airline; "
                         "a fare on an accepted airline is still to be read")

    def test_no_price_is_printed_for_it(self):
        html = hd.render_digest_html(_config(), hd.build_digest(
            _config(), rows=_hidden_rows(["SYNTHETIC Air"]), package_prices={}, watch=(), generated_at=NOW),
            generated_at=NOW)
        self.assertNotIn("£4,000", html)


class NotYetPricedRenderingTests(unittest.TestCase):
    """The reason once, then one line per trip: thirteen links in one paragraph was unreadable."""

    def setUp(self):
        self.digest = _build()
        self.trips = [p for p in self.digest.pending if not p.group]

    def test_the_html_keeps_its_section_marker(self):
        self.assertIn(">Not yet priced</div>", _html(self.digest))

    def test_the_reason_is_one_bold_line_and_each_trip_has_its_own_line(self):
        html = _html(self.digest)
        self.assertGreater(len(self.trips), 6, "the July run has many unread trips")
        reason = self.trips[0].reason
        self.assertEqual(html.count(f"<b style=\"color:#334155;\">{reason}</b>"), 1,
                         "the shared reason is stated once, not once per trip")
        lines = re.findall(r'<div style="margin:3px 0 0;">.*?</div>', html)
        for p in self.trips:
            self.assertEqual(sum(1 for line in lines if hd._e(p.name) in line), 1, p.name)

    def test_the_text_part_is_a_reason_line_then_two_space_indented_trips(self):
        text = _text(self.digest)
        self.assertIn("\nNot yet priced\n", text)
        self.assertIn(f"\n{self.trips[0].reason}\n", text)
        for p in self.trips:
            self.assertIn(f"\n  {p.name}\n", text)
        self.assertNotIn("Not yet priced: " + self.trips[0].name, text)


class TheJobSendsTheDigestTests(unittest.TestCase):
    def setUp(self):
        self.saved = (hol.LAST_FILTERED_OUT, hol.LAST_OVER_BUDGET, hol.LAST_CLIMATE_EXCLUDED)

    def tearDown(self):
        hol.LAST_FILTERED_OUT, hol.LAST_OVER_BUDGET, hol.LAST_CLIMATE_EXCLUDED = self.saved

    def test_the_july_body_is_the_digest_and_names_its_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"HOLIDAY_SEARCH_CONFIG_JSON": JULY.read_text(encoding="utf-8"),
                   "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"), **SMTP_ENV}
            with patch.dict(os.environ, env), patch("public_flight_search.mailer.smtplib.SMTP") as smtp:
                result = run_holiday_planner(
                    dry_run=False, force_send=True, hotel_evidence_path=str(Path(tmp) / "a.json"),
                    live_evidence_path=str(Path(tmp) / "b.json"), package_evidence_path=str(Path(tmp) / "c.json"),
                    stopover_reads_path=str(Path(tmp) / "d.json"))
            message = _sent_message(smtp)
        self.assertTrue(result["email_sent"])
        body = next(p for p in message.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
        text = visible_text(body)
        self.assertIn("confirmed prices only", text)
        self.assertNotIn("Every option at a glance", text)
        self.assertNotIn("Winelands", text)
        self.assertIn(result["full_detail_attachment"], text)
        self.assertLess(len(body.encode("utf-8")), 90_000)


if __name__ == "__main__":
    unittest.main()
