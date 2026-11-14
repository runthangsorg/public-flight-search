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


class CarrierNamedOnceTests(unittest.TestCase):
    """14 Nov 2026, reading the rendered body: "a business fare was read on RwandAir, RwandAir, which is not ..." and
    "Air Algerie, Emirates, Air Algerie, Emirates"."""

    def test_the_digest_names_a_carrier_once_however_often_the_read_repeats_it(self):
        rows = _hidden_rows(["RwandAir", "RwandAir"])
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW)
        (reason,) = [p.reason for p in digest.pending if not p.group]
        self.assertEqual(reason,
                         "a business fare was read on RwandAir, which is not on the accepted airline list; "
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
            self.assertIn(hd._e(card.title), row)
            self.assertIn(f"{card.nights_priced} of {card.nights} nights", row)
            self.assertIn(f"{card.nights} nights · {hd._e(card.dates)}", row)
            self.assertIn("fare: " + hd._e(hd._fare_reason(card)), row)
            for stay in card.stays:
                if not stay.priced:
                    continue
                self.assertIn(hd._e(stay.property_name), row)
                self.assertIn(f"{stay.nights} nights", row)
                self.assertIn(f"{hd._gbp(stay.total_gbp)} ({hd._gbp(stay.total_gbp / stay.nights)} a night)", row)
            open_nights = [s for s in card.stays if not s.priced]
            if open_nights:
                self.assertIn("still to price: " + hd._e(open_nights[0].place), row)

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
        right = row[row.index('align="right"'):]
        self.assertIn(f"<b>{hd._gbp(watch.total_gbp)}</b>", right)
        self.assertIn(f"{watch.nights} nights", right)
        self.assertIn(f"£{watch.total_gbp / watch.nights:,.0f} a night", row)

    def test_a_full_card_shows_the_per_night_figure_in_its_stay_line(self):
        (trip,) = self._cards("trip")
        self.assertEqual({s.total_gbp / s.nights for s in trip.stays}, {200.0})
        self.assertEqual(self.html.count("(£200 a night)"), len(trip.stays), "one per priced stay, in its detail line")
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
        self.assertIn("£2,450 so far · 7 of 12 nights", self.text)
        self.assertIn("  Why it is special: ", self.text)
