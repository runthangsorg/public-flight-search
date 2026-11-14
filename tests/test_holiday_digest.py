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

from dataclasses import replace

from public_flight_search import holidays as hol
from public_flight_search.jobs import run_holiday_planner

from test_full_detail_attachment import SMTP_ENV, _sent_message
from test_holiday_email_compact import JULY, _config, visible_text
from test_price_says_what_it_covers import BUILD, PACKAGE, deal_read, load
from test_trip_totals import _hotel_rates, _plan_lodges, _rate

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


def _flat(fragment):
    """A piece of the body as a reader sees it: no tags, and a non-breaking space is a space."""
    return hd._visible(fragment).replace("\xa0", " ")


class ConfirmedPackageCardTests(unittest.TestCase):
    def test_a_confirmed_package_is_one_card_with_where_it_was_found(self):
        digest = _build(packages=[_package()])
        self.assertEqual([c.title for c in digest.cards], ["Paradise Resort"])
        html, text = _html(digest), _text(digest)
        for part in (html, text):
            flat = _flat(part) if "<" in part else part
            for needle in ("£6,400", "14 nights", "27 Jun", "TUI", "8 Nov"):
                self.assertIn(needle, flat)
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
                         "a business fare was read on SYNTHETIC Air, not on the accepted airline list; "
                         "a fare on an accepted airline is still to be read")

    def test_it_names_every_carrier_of_the_read(self):
        self.assertIn("SYNTHETIC Air and Second SYNTHETIC Air",
                      self._reason(["SYNTHETIC Air", "Second SYNTHETIC Air"]))
        self.assertIn("A, B and C", self._reason(["A", "B", "C"]))

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
        lines = re.findall(r'<div style="margin:3px 0 0; font-size:13px;">.*?</div>', html)
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


class CarrierNamedOnceTests(unittest.TestCase):
    """14 Nov 2026, reading the rendered body: "a business fare was read on RwandAir, RwandAir, which is not ..." and
    "Air Algerie, Emirates, Air Algerie, Emirates"."""

    def test_the_digest_names_a_carrier_once_however_often_the_read_repeats_it(self):
        rows = _hidden_rows(["RwandAir", "RwandAir"])
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW)
        (reason,) = [p.reason for p in digest.pending if not p.group]
        self.assertEqual(reason,
                         "a business fare was read on RwandAir, not on the accepted airline list; "
                         "a fare on an accepted airline is still to be read")
        self.assertEqual(reason.count("RwandAir"), 1)

    def test_the_same_airline_makes_one_heading_for_every_trip_it_set_aside(self):
        rows = _hidden_rows(["Egyptair", "Egyptair"]) + _hidden_rows(["Egyptair"])
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW)
        html = hd.render_digest_html(_config(), digest, generated_at=NOW)
        self.assertEqual(html.count("a business fare was read on Egyptair"), 1)

    def test_cabin_options_records_the_carriers_once_each(self):
        from public_flight_search.holiday_email import cabin_options

        trip = type("Trip", (), {"cost_lines": (), "cost_low_gbp": 0.0, "legs": ()})()
        read = {"total_gbp": 20_000.0,
                "flights": [{"carrier": "RwandAir", "cabin": "BUSINESS", "duration": "13h 10m"},
                            {"carrier": "RwandAir", "cabin": "BUSINESS", "duration": "12h 30m"}]}
        options = cabin_options(trip, {"MIXED": read}, 12_000.0, travellers=5)
        self.assertEqual(options["business_hidden"]["carriers"], ["RwandAir"])


class CompactRowsTests(unittest.TestCase):
    """14 Nov 2026: the body was 9,000 px tall — twelve stays-only trips and the watch list were full cards.

    Only whole trips, packages and part-priced trips whose FLIGHTS are read stay full-size; a trip with stays
    read but no fare, and each watch-list stay, is one compact row, and the derived-total sentence is printed
    once per section instead of inside every card.
    """

    @classmethod
    def setUpClass(cls):
        cls.rows = _multi_centre_rows(_config(), fares=load([deal_read(BUILD, "MIXED", 8_000),
                                                              deal_read(PACKAGE, "MIXED", 9_000)]))
        by_id = {r["trip"].id: r for r in cls.rows}
        cls.build_lodges = _plan_lodges(by_id[BUILD])
        cls.package_lodges = _plan_lodges(by_id[PACKAGE])
        cls.mc01_lodge = _plan_lodges(by_id["MC-01"])[0]
        cls.mc07_lodge = _plan_lodges(by_id["MC-07"])[0]
        cls.watch_pair = hd._reference_pair(_config())
        cls.entry = type("Entry", (), {"name": "SYNTHETIC Island Villa", "area": "Gili Meno",
                                       "url": "https://example.org/SYNTHETIC-villa", "halal": None})()
        rates = [_rate(name, ci, co, 200.0) for name, ci, co in cls.build_lodges]
        rates.append(_rate(*cls.package_lodges[0], 300.0))
        rates.append(_rate(*cls.mc01_lodge, 400.0))
        rates.append(_rate(*cls.mc07_lodge, 350.0))
        rates.append(_rate(cls.entry.name, *cls.watch_pair, 250.0))
        cls.digest = hd.build_digest(_config(), rows=cls.rows, package_prices={}, watch=(cls.entry,),
                                     generated_at=NOW, hotel_rates=_hotel_rates(rates))
        cls.html = _html(cls.digest)
        cls.text = _text(cls.digest)

    def _cards(self, kind):
        return [c for c in self.digest.cards if c.kind == kind]

    def test_only_a_whole_trip_a_package_and_a_part_with_its_fare_are_full_cards(self):
        self.assertEqual(len(self._cards("trip")), 1)
        self.assertEqual(len([c for c in self._cards("part") if c.flights_gbp is not None]), 1)
        self.assertEqual(len([c for c in self._cards("part") if c.flights_gbp is None]), 3)
        self.assertEqual(len(self._cards("stay")), 1)
        self.assertEqual(self.html.count('data-kind="card-trip"'), 1)
        self.assertEqual(self.html.count('data-kind="card-part"'), 1, "the stays-only trips are not cards")
        self.assertEqual(self.html.count('data-kind="row-stays-only"'), 3)
        self.assertEqual(self.html.count('data-kind="row-stay"'), 1)
        self.assertNotIn('data-kind="card-flights"', self.html, "no fare-only trip is a card")

    def test_the_new_section_sits_between_partly_priced_and_the_watch_list(self):
        for part in (self.html, self.text):
            partly = part.index("Partly priced")
            stays = part.index("Stays read, fares still to come")
            watch = part.index("Stays priced, flights separate")
            self.assertLess(partly, stays)
            self.assertLess(stays, watch)
        self.assertIn("These nights are priced; the trip joins the cards above when its fare is read.", self.html)
        self.assertIn("These nights are priced; the trip joins the cards above when its fare is read.", self.text)

    def test_a_stays_only_row_carries_the_trip_the_stays_and_the_open_nights(self):
        stays_only = sorted((c for c in self._cards("part") if c.flights_gbp is None),
                            key=lambda c: (-(c.nights_priced / c.nights_planned), c.stays_gbp))
        rows = re.findall(r'<tr data-kind="row-stays-only">.*?</tr>', self.html)
        self.assertEqual(len(rows), 3)
        for row, card in zip(rows, stays_only):
            flat = _flat(row)
            self.assertIn(hd._e(card.title), row)
            self.assertIn(f"{card.nights_priced} of {card.nights} nights", flat)
            self.assertIn(f"{card.nights} nights · {card.dates}", flat)
            self.assertIn("fare: " + hd._fare_reason(card), flat)
            for stay in card.stays:
                if not stay.priced:
                    continue
                self.assertIn(hd._e(stay.property_name), row)
                self.assertIn(f"{stay.nights} nights", flat)
                self.assertIn(f"{hd._gbp(stay.total_gbp)} ({hd._gbp(stay.total_gbp / stay.nights)} a night)", flat)
            if hd._open_nights_words(card):
                self.assertIn("Still to price:</b> " + hd._e(hd._open_nights_words(card)), row)

    def test_the_rows_are_ordered_by_the_share_of_nights_priced_then_by_figure(self):
        # Two trips price 7 of 12 nights; MC-01 prices 7 of 14, so it comes last.
        rows = re.findall(r'<tr data-kind="row-stays-only">.*?</tr>', self.html)
        self.assertIn("Halekulani Okinawa", rows[0])
        self.assertIn("Halekulani Okinawa", rows[1], "the tied 7-of-12 rows stay together")
        self.assertIn("Kalandara Resort Lombok", rows[-1])
        shares = [c.nights_priced / c.nights_planned
                  for c in hd._sorted_stays_rows([c for c in self._cards("part") if c.flights_gbp is None])]
        self.assertEqual(shares, sorted(shares, reverse=True))
        tie = [c for c in self._cards("part") if c.flights_gbp is None][0]
        dear = replace(tie, title="Synthetic dear", nights_priced=7, nights_planned=14, stays_gbp=3_000.0)
        cheap = replace(tie, title="Synthetic cheap", nights_priced=7, nights_planned=14, stays_gbp=2_000.0)
        self.assertEqual([c.title for c in hd._sorted_stays_rows([dear, cheap])],
                         ["Synthetic cheap", "Synthetic dear"])

    def test_a_watch_stay_is_one_compact_row_with_its_night_rate(self):
        (watch,) = self._cards("stay")
        (row,) = re.findall(r'<tr data-kind="row-stay">.*?</tr>', self.html)
        self.assertIn(hd._e(watch.title), row)
        self.assertIn(hd._e(watch.place), row)
        self.assertNotIn("<br><br>", row)
        right = row[row.index("width:120px"):]
        self.assertIn(f"<b>{hd._gbp(watch.total_gbp)}</b>", right)
        self.assertIn("for 5 · stay only", _flat(right), "who the figure is for, on its own line")
        self.assertIn(f"{watch.nights} nights", _flat(right), "the nights it covers, on the next line")
        self.assertIn(f"£{watch.total_gbp / watch.nights:,.0f} a night", _flat(row))

    def test_a_full_card_shows_the_per_night_figure_in_its_stay_line(self):
        (trip,) = self._cards("trip")
        self.assertEqual({s.total_gbp / s.nights for s in trip.stays}, {200.0})
        self.assertEqual(_flat(self.html).count("(£200 a night)"), len(trip.stays),
                         "one per priced stay, in its detail line")
        self.assertIn(f"{hd._gbp(trip.stays[0].total_gbp)} (£200 a night) · breakfast", self.text)

    def test_the_derived_total_sentence_is_once_per_section_not_once_per_card(self):
        groups = [[c for c in self.digest.cards if c.kind == "trip"],
                  [c for c in self.digest.cards if c.kind == "package"],
                  [c for c in self.digest.cards if c.kind == "part" and c.flights_gbp is not None],
                  [c for c in self.digest.cards if c.kind == "part" and c.flights_gbp is None],
                  [c for c in self.digest.cards if c.kind == "stay"]]
        expected = sum(1 for g in groups if any(s.derived_total for c in g for s in c.stays))
        self.assertGreater(expected, 1, "more than one section derives a stay total")
        self.assertEqual(self.html.count(hd.DERIVED_TOTAL_NOTE), expected)
        self.assertEqual(self.text.count(hd.DERIVED_TOTAL_NOTE), expected)
        self.assertEqual(len(self.digest.cards), 6)

    def test_the_text_part_has_the_same_rows_in_the_same_order(self):
        self.assertIn("\nStays read, fares still to come\n", self.text)
        self.assertIn("\nStays priced, flights separate\n", self.text)
        first = self.text.index("Halekulani Okinawa")
        second = self.text.index("Kalandara Resort Lombok")
        self.assertLess(first, second)
        self.assertIn("£2,450 (£350 a night)", self.text, "the per-night figure follows the stay total")
        self.assertIn("£2,450 so far · for 5 · stays only, 7 of 12 nights", self.text)
        self.assertIn("    the strongest July weather case", self.text, "the why line is the trip's own words")

class RenderedBodyDefectsTests(unittest.TestCase):
    """The defects a visual check of the rendered body found at 640 px and 390 px (14 Nov 2026).

    One test per numbered item of brief H: the double-escaped seller link and the overflow, the figure
    labels, the per-night wording, seller and source, the short fare reasons, the labelled row lines,
    and the small things.
    """

    @classmethod
    def setUpClass(cls):
        cls.pair = hd._reference_pair(_config())
        cls.entry = type("Entry", (), {"name": "SYNTHETIC Island Villa", "area": "Gili Meno",
                                       "url": "https://example.org/SYNTHETIC-villa", "halal": None})()
        #: No fare read at all: every trip is stays-only (or a name in "Not yet priced").
        cls.unpriced = _multi_centre_rows(_config(), fares=load([]))
        cls.lodges = {r["trip"].id: _plan_lodges(r) for r in cls.unpriced}

    def _stay(self, **overrides):
        """A watch-list stay card, priced from one synthetic rate."""
        rate = _rate(self.entry.name, self.pair[0], self.pair[1], 250.0, two_rooms=True)
        rate.update(overrides)
        digest = hd.build_digest(_config(), rows=[], package_prices={}, watch=(self.entry,),
                                 generated_at=NOW, hotel_rates=_hotel_rates([rate]))
        self.assertTrue([c for c in digest.cards if c.kind == "stay"])
        return (digest, hd.render_digest_html(_config(), digest, generated_at=NOW),
                hd.render_digest_text(_config(), digest, generated_at=NOW))

    def _rows_digest(self, rows=None, rates=(), **row_patch):
        rows = [dict(r, **row_patch) for r in (rows if rows is not None else self.unpriced)]
        return hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW,
                               hotel_rates=_hotel_rates(list(rates)))

    # 1. Raw HTML printed and the row overflowing
    def test_a_long_seller_url_with_an_ampersand_is_escaped_once_and_cannot_overflow(self):
        url = "https://example.org/SYNTHETIC-" + "a" * 250 + "?x=1&y=2&z=3"
        _digest, html, _text = self._stay(source_url=url)
        self.assertNotIn("&lt;a", html, "the anchor tag was escaped a second time")
        self.assertNotIn("&amp;amp;", html)
        self.assertNotIn("&y=2", html.replace("&amp;y=2", ""))
        self.assertEqual(html.count('href="' + hd._e(url) + '"'), 2, "the title link and the seller link")
        self.assertIn("table-layout:fixed", html)
        self.assertIn("overflow-wrap:break-word", html)  # breaks a long URL, never an ordinary word
        self.assertIn("width:120px", html, "wide enough at 390 px for the two-line figure label")

    # 2. Every right-hand figure says who and what it covers
    def test_every_compact_figure_says_who_it_is_for_and_what_it_covers(self):
        _digest, html, text = self._stay()
        self.assertIn("for 5 · stay only", _flat(html))
        self.assertIn("for 5 · stay only,", text)
        self.assertIn("for 5 · stays only",
                      _flat(hd.render_digest_html(_config(), self._rows_digest(
                          rates=[_rate(*self.lodges[BUILD][0], 200.0)]), generated_at=NOW)))
        fare_only = hd.build_digest(_config(), rows=_multi_centre_rows(
            _config(), fares=load([deal_read("AF-02", "MIXED", 9_000)])), package_prices={},
            watch=(), generated_at=NOW)
        for part in (hd.render_digest_html(_config(), fare_only, generated_at=NOW),
                     hd.render_digest_text(_config(), fare_only, generated_at=NOW)):
            self.assertIn("for 5 · flights only", _flat(part) if "<" in part else part)

    # 3. The per-night figure says whether it is per room
    def test_the_per_night_figure_says_what_it_covers(self):
        from public_flight_search.trip_totals import StayPrice

        def stay(**kw):
            base = dict(place="Gili Meno", property_name="SYNTHETIC", check_in="2027-06-27",
                        check_out="2027-07-01", nights=4, total_gbp=2_800.0)
            return StayPrice(**dict(base, **kw))

        self.assertEqual(hd._per_night_phrase(stay(unit_guests=(3, 2), two_rooms=True)),
                         "(£700 a night for both rooms)")
        self.assertEqual(hd._per_night_phrase(stay(unit_guests=(2, 2, 1), three_rooms=True)),
                         "(£700 a night for all three rooms)")
        self.assertEqual(hd._per_night_phrase(stay(unit_guests=(5,))), "(£700 a night)")
        rates = [_rate(name, ci, co, 200.0, two_rooms=True) for name, ci, co in self.lodges[BUILD]]
        digest = self._rows_digest(rates=rates)
        for part in (hd.render_digest_html(_config(), digest, generated_at=NOW),
                     hd.render_digest_text(_config(), digest, generated_at=NOW)):
            self.assertIn("a night for both rooms", _flat(part) if "<" in part else part)

    # 4. Seller and source
    def test_a_seller_that_is_the_property_says_the_hotels_own_rate_and_keeps_its_link(self):
        rate = _rate(self.entry.name, self.pair[0], self.pair[1], 250.0, two_rooms=True)
        own_name = "SYNTHETIC Island Villa Resort & Spa"
        rate["prices_shown"] = [dict(shown, provider=own_name) for shown in rate["prices_shown"]]
        digest = hd.build_digest(_config(), rows=[], package_prices={}, watch=(self.entry,),
                                 generated_at=NOW, hotel_rates=_hotel_rates([rate]))
        html = hd.render_digest_html(_config(), digest, generated_at=NOW)
        text = hd.render_digest_text(_config(), digest, generated_at=NOW)
        self.assertIn(f">{hd._e("the hotel's own rate")}</a>", html)
        self.assertNotIn(f">{hd._e(own_name)}</a>", html)
        self.assertIn("the hotel's own rate", text)
        self.assertNotIn(f"{own_name} · read", text)
        self.assertIn("href=", html)

    def test_every_priced_stay_line_ends_with_a_source_link_and_the_day_it_was_read(self):
        _digest, html, text = self._stay()
        self.assertIn("read&nbsp;14&nbsp;Nov", html, "the day is one token, so it cannot split")
        self.assertTrue(re.search(r" · read 14 Nov$", text, re.M), "the line ends with the day it was read")
        line = next(line for line in text.splitlines() if "read 14 Nov" in line)
        self.assertIn("SYNTHETIC Seller", line, "the seller is named, never dropped")

    # 5. Fare reasons are short and say the same thing as the group heading
    def test_the_short_fare_reasons_and_the_group_heading_wording(self):
        for carriers, short, heading in (
            (["RwandAir", "RwandAir"],
             "business found only on RwandAir (not on the accepted airline list)",
             "a business fare was read on RwandAir, not on the accepted airline list"),
            (["Air A", "Air B", "Air C"],
             "business found only on Air A, Air B and Air C (not all on the accepted airline list)",
             "a business fare was read on Air A, Air B and Air C, not all on the accepted airline list"),
            (["Multiple airlines", "Multiple airlines"],
             "business found only on a mix of airlines (not on the accepted airline list)",
             "a business fare was read on a mix of airlines, not on the accepted airline list"),
        ):
            hidden = {"saving": None, "travellers": 5, "reason": "", "carriers": carriers}
            self.assertEqual(hd._business_hidden_short(hidden), short)
            self.assertTrue(hd._business_hidden_reason(hidden).startswith(heading))
        hidden_row = dict(self.unpriced[0], business_hidden={"saving": None, "travellers": 5, "reason": "",
                                                             "carriers": ["RwandAir", "RwandAir"]}) \
            if False else None
        rows = [dict(r, business_hidden={"saving": None, "travellers": 5, "reason": "",
                                         "carriers": ["RwandAir", "RwandAir"]})
                for r in self.unpriced if r["trip"].id == BUILD]
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW,
                                 hotel_rates=_hotel_rates([_rate(*self.lodges[BUILD][0], 200.0)]))
        for part in (hd.render_digest_html(_config(), digest, generated_at=NOW),
                     hd.render_digest_text(_config(), digest, generated_at=NOW)):
            self.assertIn("fare: business found only on RwandAir "
                          "(not on the accepted airline list)", part)
        economy = self._rows_digest(rows=[r for r in self.unpriced if r["trip"].id == BUILD],
                                    rates=[_rate(*self.lodges[BUILD][0], 200.0)], economy_refused=True)
        for part in (hd.render_digest_html(_config(), economy, generated_at=NOW),
                     hd.render_digest_text(_config(), economy, generated_at=NOW)):
            self.assertIn("fare: economy has a leg over 8 hours; business not read yet", part)
        nothing = self._rows_digest(rows=[r for r in self.unpriced if r["trip"].id == BUILD],
                                    rates=[_rate(*self.lodges[BUILD][0], 200.0)])
        self.assertIn("fare: not read yet", hd.render_digest_html(_config(), nothing, generated_at=NOW))

    # 6. Compact trip rows are labelled lines, not a wall of text
    def test_a_compact_trip_row_labels_its_lines_and_keeps_the_why_italic_and_unlabelled(self):
        digest = self._rows_digest(rows=[r for r in self.unpriced if r["trip"].id == BUILD],
                                   rates=[_rate(*self.lodges[BUILD][0], 200.0)])
        (row,) = re.findall(r'<tr data-kind="row-stays-only">.*?</tr>',
                            hd.render_digest_html(_config(), digest, generated_at=NOW))
        self.assertIn(">Priced:</div>", row)
        self.assertIn("<b>Still to price:</b>", row)
        self.assertIn("color:#92400E", row, "the open nights keep their amber colour")
        self.assertIn("font-style:italic;", row)
        self.assertNotIn("Why it is special", row)
        self.assertIn("line-height:1.45", row)
        self.assertIn("padding-left:10px", row, "the priced lines are indented under the label")

    # 7. The small things
    def test_no_stay_line_ends_with_a_dangling_separator(self):
        _digest, html, text = self._stay()
        self.assertNotIn(" ·<", html)
        self.assertNotIn(" ·\n", text)

    def test_the_section_caption_sentence_starts_with_a_capital_and_ends_with_a_full_stop(self):
        self.assertEqual(hd.DERIVED_TOTAL_NOTE,
                         "Stay totals are the nightly price shown times the nights; "
                         "taxes and resort fees may be added at booking.")
        caption = hd._section_caption("These nights are priced; the trip joins the cards above when its fare is read.",
                                      [c for c in self._rows_digest(
                                          rates=[_rate(*self.lodges[BUILD][0], 200.0)]).cards])
        self.assertTrue(caption.endswith(" " + hd.DERIVED_TOTAL_NOTE))

    def test_the_summary_counts_equal_the_rows_each_section_renders(self):
        fares = load([deal_read(BUILD, "MIXED", 8_000), deal_read(PACKAGE, "MIXED", 9_000),
                      deal_read("AF-02", "MIXED", 9_000)])
        rows = _multi_centre_rows(_config(), fares=fares)
        lodges = {r["trip"].id: _plan_lodges(r) for r in rows}
        rates = [_rate(*lodges[BUILD][0], 300.0), _rate(*lodges[PACKAGE][0], 300.0)]
        # Three stays-only trips whose first properties are distinct, so none shares a rate.
        rates += [_rate(*lodges[trip][0], 400.0) for trip in ("MC-01", "AF-01", "AF-04")]
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(),
                                 generated_at=NOW, hotel_rates=_hotel_rates(rates))
        html = hd.render_digest_html(_config(), digest, generated_at=NOW)
        text = hd.render_digest_text(_config(), digest, generated_at=NOW)
        self.assertEqual(html.count('data-kind="card-part"'), 2)
        self.assertEqual(html.count('data-kind="row-stays-only"'), 3)
        self.assertEqual(html.count('data-kind="row-flights"'), 1)
        self.assertIn("2 trips have flights and some stays priced, 3 trips have stays priced and await a fare, "
                      "and 1 trip has a fare only (all below).", html)
        # The summary box is HTML-only; the plain text's sections carry the same rows.
        self.assertEqual(text.count("    Priced:"), 3)
        self.assertEqual(text.count("\nFlight searches, flights only\n"), 1)

    def test_a_stop_split_around_another_stop_names_the_hotel_once(self):
        rows = [r for r in self.unpriced if r["trip"].id == PACKAGE]
        digest = self._rows_digest(rows=rows, rates=[_rate(*self.lodges[PACKAGE][1], 300.0)])
        card = next(c for c in digest.cards if c.title.startswith("Zanzibar 8 nights"))
        # The lodge's own area (Marumbi), not the stop's place: brief I, item 7.
        self.assertEqual(hd._open_nights_words(card), "Marumbi 3n + 5n (Paradise Beach Resort)")
        self.assertNotIn("Paradise Beach Resort) (Paradise Beach Resort", hd._open_nights_words(card))


def test_a_watch_row_escapes_its_place_once():
    """Review, 14 Nov 2026: the area and dates went into the row unescaped."""
    from public_flight_search import holiday_digest as hd
    from public_flight_search.trip_totals import StayPrice

    stay = StayPrice(place="Palm <Atoll> & Cove", property_name="Palm Cove Resort", check_in="2027-06-27",
                     check_out="2027-07-04", nights=7, total_gbp=700.0, board="BB", seller="Example Stays",
                     source_url="https://example.com/r?a=1&b=2", observed_at="2026-11-14T10:00:00+00:00")
    card = hd.Card(kind="stay", title="Palm Cove Resort", place="Palm <Atoll> & Cove", nights=7,
                   dates="27 Jun – 4 Jul", total_gbp=700.0, covers="stay only", shop="Example Stays",
                   url=stay.source_url, read_on="14 Nov", flights="", hotel="", facts=(), halal="",
                   stays=(stay,), stays_gbp=700.0, nights_priced=7, nights_planned=7, travellers=5)
    html = hd._watch_rows_html([card])
    assert "Palm &lt;Atoll&gt; &amp; Cove" in html and "<Atoll>" not in html and "&amp;amp;" not in html


class SecondVisualCheckTests(unittest.TestCase):
    """The defects a second read of the rendered body found (14 Nov 2026, brief I).

    One test per numbered item: the plain summary sentence, the one-versus-several carrier wording, the
    colon after a card's bold labels, the tokens that must not split across lines, the separator that
    must never start a line, the labelled flight duration, each lodge under its own area, and the one
    font size on the "Not yet priced" list.
    """

    @classmethod
    def setUpClass(cls):
        cls.pair = hd._reference_pair(_config())
        cls.entry = type("Entry", (), {"name": "SYNTHETIC Island Villa", "area": "Gili Meno",
                                       "url": "https://example.org/SYNTHETIC-villa", "halal": None})()
        cls.unpriced = _multi_centre_rows(_config(), fares=load([]))
        cls.lodges = {r["trip"].id: _plan_lodges(r) for r in cls.unpriced}

    def _stay(self):
        rate = _rate(self.entry.name, self.pair[0], self.pair[1], 250.0, two_rooms=True)
        digest = hd.build_digest(_config(), rows=[], package_prices={}, watch=(self.entry,),
                                 generated_at=NOW, hotel_rates=_hotel_rates([rate]))
        return digest, hd.render_digest_html(_config(), digest, generated_at=NOW), \
            hd.render_digest_text(_config(), digest, generated_at=NOW)

    def _trip(self):
        """One whole-trip card: the synthetic fare read and every one of its nights' stays."""
        rows = [r for r in _multi_centre_rows(_config(), fares=load([deal_read(BUILD, "MIXED", 8_000)]))
                if r["trip"].id == BUILD]
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW,
                                 hotel_rates=_hotel_rates([_rate(*lodge, 200.0)
                                                           for lodge in self.lodges[BUILD]]))
        self.assertEqual(digest.cards[0].kind, "trip")
        return digest, hd.render_digest_html(_config(), digest, generated_at=NOW), \
            hd.render_digest_text(_config(), digest, generated_at=NOW)

    # 1. The summary box reads as one sentence, not four categories
    def test_the_summary_is_one_sentence_with_a_clause_per_kind_and_none_for_a_zero(self):
        fares = load([deal_read(BUILD, "MIXED", 8_000), deal_read(PACKAGE, "MIXED", 9_000),
                      deal_read("AF-02", "MIXED", 9_000)])
        rows = [r for r in _multi_centre_rows(_config(), fares=fares)
                if r["trip"].id in (BUILD, PACKAGE, "AF-02", "MC-01", "AF-01", "AF-04")]
        lodges = {r["trip"].id: _plan_lodges(r) for r in rows}
        rates = [_rate(*lodges[BUILD][0], 300.0), _rate(*lodges[PACKAGE][0], 300.0)]
        rates += [_rate(*lodges[trip][0], 400.0) for trip in ("MC-01", "AF-01", "AF-04")]
        rates.append(_rate(self.entry.name, *self.pair, 250.0))
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(self.entry,),
                                 generated_at=NOW, hotel_rates=_hotel_rates(rates))
        sentence = _flat(hd.render_digest_html(_config(), digest, generated_at=NOW))
        self.assertIn("No whole trip is priced yet this week. 2 trips have flights and some stays priced, "
                      "3 trips have stays priced and await a fare, 1 trip has a fare only, and "
                      "1 watch-list stay is priced (all below).", sentence)

    def test_a_clause_with_a_count_of_zero_is_left_out_and_a_count_of_one_is_singular(self):
        only_fare = hd.build_digest(_config(), rows=_multi_centre_rows(
            _config(), fares=load([deal_read("AF-02", "MIXED", 9_000)])), package_prices={},
            watch=(), generated_at=NOW)
        sentence = _flat(hd.render_digest_html(_config(), only_fare, generated_at=NOW))
        self.assertIn("No whole trip is priced yet this week. 1 trip has a fare only (all below).", sentence)
        self.assertNotIn("stays priced and await", sentence)
        self.assertNotIn("0 trip", sentence)

    # 2. One airline is not on the list; two or more are not ALL on it
    def test_one_unaccepted_carrier_is_not_on_the_list_and_several_are_not_all_on_it(self):
        one = {"saving": None, "travellers": 5, "reason": "", "carriers": ["RwandAir", "RwandAir"]}
        several = {"saving": None, "travellers": 5, "reason": "", "carriers": ["Air A", "Air B"]}
        self.assertEqual(hd._business_hidden_short(one),
                         "business found only on RwandAir (not on the accepted airline list)")
        self.assertEqual(hd._business_hidden_short(several),
                         "business found only on Air A and Air B (not all on the accepted airline list)")
        self.assertTrue(hd._business_hidden_reason(one).startswith(
            "a business fare was read on RwandAir, not on the accepted airline list"))
        self.assertTrue(hd._business_hidden_reason(several).startswith(
            "a business fare was read on Air A and Air B, not all on the accepted airline list"))

    # 3. A card's bold labels end with a colon
    def test_every_bold_label_on_a_full_card_is_followed_by_a_colon_and_a_space(self):
        _digest, html, _text = self._trip()
        for label in ("Why it is special", "Watch out", "Not in the figure"):
            self.assertIn(f"<b>{label}:</b> ", html)

    # 4. The tokens that must not split, and the two-line figure label
    def test_the_named_tokens_never_split_and_the_figure_cell_holds_two_lines(self):
        _digest, html, _text = self._trip()
        for token in ("12&nbsp;nights", "4&nbsp;nights", "read&nbsp;14&nbsp;Nov",
                      "(£200&nbsp;a&nbsp;night)"):
            self.assertIn(token, html, token)
        rows = [r for r in self.unpriced if r["trip"].id == BUILD]
        part = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW,
                               hotel_rates=_hotel_rates([_rate(*self.lodges[BUILD][0], 200.0)]))
        part_html = hd.render_digest_html(_config(), part, generated_at=NOW)
        self.assertIn("4&nbsp;of&nbsp;12&nbsp;nights", part_html)
        self.assertIn(f"{hd._gbp(800)}&nbsp;(£200&nbsp;a&nbsp;night)", part_html,
                      "the stay figure and its bracketed per-night phrase never split")
        _digest, watch_html, _text = self._stay()
        self.assertIn("for&nbsp;5&nbsp;·&nbsp;stay&nbsp;only", watch_html)
        self.assertRegex(watch_html,
                         r'<div style="[^"]*white-space:nowrap;">for&nbsp;5&nbsp;·&nbsp;stay&nbsp;only</div>'
                         r'<div style="[^"]*white-space:nowrap;">17&nbsp;nights</div>')
        self.assertIn("width:120px", watch_html)

    # 5. A wrapped line never starts with the separator
    def test_a_separator_is_glued_to_the_part_before_it_so_no_line_can_start_with_it(self):
        joined = hd._dot_join(["Gili Meno", "x" * 45, "read 14 Nov"])
        self.assertTrue(joined.startswith('<span style="white-space:nowrap">Gili Meno&nbsp;·</span> '),
                        "a short part is whole and carries its own separator")
        self.assertIn("x" * 45 + "&nbsp;· ", joined, "a part over 40 characters stays breakable")
        self.assertNotIn(" · ", joined, "no separator keeps a break opportunity before it")
        self.assertTrue(joined.endswith(">read 14 Nov</span>"), "the last part carries no separator")
        self.assertNotIn(" · ", self._trip()[1])

    # 6. A flight duration says what it is, and the fare says who it is for
    def test_a_flight_duration_is_labelled_and_the_fare_says_for_5(self):
        self.assertEqual(hd._duration_words({"duration": "12h 10m"}), "outbound 12h 10m")
        self.assertEqual(hd._duration_words({"duration": "12h 10m",
                                             "flights": [{"duration": "12h 10m"}]}),
                         "longest leg 12h 10m")
        _digest, html, text = self._trip()
        (flights_row,) = re.findall(r"<tr><td[^>]*><b>Flights</b>.*?</tr>", html)
        self.assertIn("longest leg 12h 10m", _flat(flights_row))
        self.assertIn(f"{hd._gbp(8_000)} for 5", _flat(flights_row))
        self.assertIn("Flights: Business on the long legs: Qatar Airways, longest leg 12h 10m", text)
        fare_only = hd.build_digest(_config(), rows=_multi_centre_rows(
            _config(), fares=load([deal_read("AF-02", "MIXED", 9_000)])), package_prices={},
            watch=(), generated_at=NOW)
        (row,) = re.findall(r'<tr data-kind="row-flights">.*?</tr>',
                            hd.render_digest_html(_config(), fare_only, generated_at=NOW))
        self.assertIn("longest leg 12h 10m", _flat(row))

    # 7. Each lodge is named under its own area, not the stop's
    def test_each_open_lodge_is_named_under_its_own_area_and_falls_back_to_the_stop(self):
        lodge = lambda name, area: type("Lodge", (), {"name": name, "area": area})()  # noqa: E731
        stop = type("Stop", (), {"place": "Nairobi + central Serengeti", "nights": 5,
                                 "lodges": (lodge("Melia Serengeti Lodge", "Serengeti, Tanzania"),
                                            lodge("Nairobi Hotel", ""))})()
        trip = type("Trip", (), {"stops": (stop,)})()
        self.assertEqual(hd._lodge_areas(trip), (("Melia Serengeti Lodge", "Serengeti"),),
                         "the first comma-separated part of the area, and no area invented")
        open_stays = (
            hd.StayPrice(place="Nairobi + central Serengeti", property_name="Melia Serengeti Lodge",
                         check_in="2027-06-27", check_out="2027-07-01", nights=4, reason="no dated rate read"),
            hd.StayPrice(place="Nairobi + central Serengeti", property_name="Nairobi Hotel",
                         check_in="2027-07-02", check_out="2027-07-03", nights=1, reason="no dated rate read"),
        )
        card = hd.Card(kind="part", title="Synthetic shape", place="Nairobi + central Serengeti", nights=5,
                       dates="27 Jun – 2 Jul", total_gbp=0.0, covers="", shop="", url="", read_on="",
                       flights="", hotel="", facts=(), stays=open_stays, areas=hd._lodge_areas(trip))
        self.assertEqual(hd._open_nights_words(card),
                         "Serengeti 4n (Melia Serengeti Lodge); Nairobi + central Serengeti 1n (Nairobi Hotel)")
        self.assertIn("<b>Still to price:</b> " + hd._e(hd._open_nights_words(card)),
                      hd._still_to_price_html(card))

    def test_a_real_trip_carries_its_lodges_own_areas(self):
        rows = [r for r in self.unpriced if r["trip"].id == BUILD]
        areas = dict(hd._lodge_areas(rows[0]["trip"]))
        self.assertEqual(areas, {"Satara Rest Camp": "Kruger National Park", "Commodore Hotel": "Cape Town"})

    # 8. One font size on the "Not yet priced" list, and no phone-side scaling
    def test_the_not_yet_priced_list_has_one_explicit_size_and_the_wrapper_does_not_scale(self):
        rows = _multi_centre_rows(_config(), fares=load([]), include_leads=True)
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW)
        html = hd.render_digest_html(_config(), digest, generated_at=NOW)
        self.assertIn("-webkit-text-size-adjust:100%; text-size-adjust:100%;", html)
        self.assertIn('<ul style="padding-left:16px; margin:4px 0; font-size:13px;', html)
        self.assertRegex(html, r'<li style="margin:0 0 4px; font-size:13px;">')
        self.assertRegex(html, r'<div style="margin:3px 0 0; font-size:13px;">',
                         "the trip lines and the new ideas sub-items each state their size")
        self.assertIn("New ideas, fares and stays being read", html)
        self.assertNotIn("font-size:12px", html[html.index(">Not yet priced<"):])
