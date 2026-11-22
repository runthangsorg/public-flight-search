"""A trip card shows a trip total only when its flights AND every planned night's stay were read (owner, 14 Nov 2026:
"massively improve it ... itineraries"). Before this the July body said "flights only, stays not priced" on every
trip, because a two-centre trip's hotels were never looked up in the hotel evidence.

Synthetic reads and synthetic rates throughout.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from public_flight_search import holiday_digest as hd
from public_flight_search import hotel_evidence as he
from public_flight_search import trip_totals as tt
from public_flight_search.holiday_email import _multi_centre_rows
from public_flight_search.multi_centre import trip_stays_for_dates

from test_holiday_email_compact import _config as _layout_config, visible_text
from test_price_says_what_it_covers import BUILD, deal_read, load


def _config(**overrides):
    """The layout helper next door, with the £25,000 ceiling brief M shipped in the example config.

    The compact tests clear it because they want a page for every trip; these two files are where the ceiling's
    own wording is pinned, so it is put back unless a test asks otherwise (``max_total_gbp=None``).
    """
    overrides.setdefault("max_total_gbp", 25_000.0)
    return _layout_config(**overrides)

NOW = "2026-11-14T12:00:00+00:00"


def _rows(reads):
    return [r for r in _multi_centre_rows(_config(), fares=load(list(reads))) if r["trip"].id == BUILD]


def _rate(name, check_in, check_out, nightly, *, board="BB", adults=5, observed="2026-11-14T09:00:00+00:00",
          two_rooms=False):
    nights = (__import__("datetime").date.fromisoformat(check_out) - __import__("datetime").date.fromisoformat(check_in)).days
    units = ([{"name": "SYNTHETIC room A", "adults": 3}, {"name": "SYNTHETIC room B", "adults": 2}] if two_rooms
             else [{"name": "SYNTHETIC family villa", "adults": adults, "guests_stated": f"{adults} guests"}])
    return {
        "property_name": name, "destination_key": "synthetic", "season": "summer",
        "vendor": "SYNTHETIC Seller as listed on Google Hotels", "check_in": check_in, "check_out": check_out,
        "nights": nights, "party": {"adults": adults, "children": 0},
        "booking_shape": "two_rooms_one_booking" if two_rooms else "single_unit", "units": units,
        "rate_name": "SYNTHETIC rate", "board": board, "price_basis": "nightly_room_rate", "currency": "GBP",
        "taxes_included": None, "prices_shown": [{"unit": u["name"], "nightly": nightly / len(units),
                                                  "provider": "SYNTHETIC Seller"} for u in units],
        "terms": [], "source_url": f"https://example.org/SYNTHETIC-rate-{name.replace(' ', '-')}",
        "observed_at": observed, "exact_date_match": True, "confidence": "verified-exact-date",
        "derived_stay_total": {"value": nightly * nights, "currency": "GBP", "how": "nightly price shown x nights"},
    }


def _hotel_rates(rates):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hotel.json"
        path.write_text(json.dumps({"schema": "holiday_hotel_evidence/1", "travellers": 5, "rates": list(rates),
                                    "unit_checks": [], "ratings": [], "facts": [], "blocked": []}), encoding="utf-8")
        loaded = dict(he.load_hotel_evidence(_config(), path=str(path), now=NOW))
    he.consume_hotel_skip_log()
    return loaded


def _plan_lodges(row):
    plan = trip_stays_for_dates(row["trip"], row["outbound"], row["return"])
    return [(ls.lodge.name, ls.check_in, ls.check_out) for stay in plan.stays for ls in stay.lodges]


def _build(rows, hotel_rates):
    return hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW, hotel_rates=hotel_rates)


class TripTotalTests(unittest.TestCase):
    def setUp(self):
        self.rows = _rows([deal_read(BUILD, "MIXED", 8_000)])
        self.lodges = _plan_lodges(self.rows[0])
        self.assertEqual(len(self.lodges), 2, "the synthetic trip has one named property per stop")

    def test_flights_plus_every_stay_read_is_a_trip_total(self):
        rates = _hotel_rates([_rate(name, ci, co, 200.0) for name, ci, co in self.lodges])
        card = _build(self.rows, rates).cards[0]
        nights = card.nights
        self.assertEqual(card.kind, "trip")
        self.assertEqual(card.total_gbp, 8_000.0 + 200.0 * nights)
        self.assertEqual(card.flights_gbp, 8_000.0)
        self.assertEqual(card.stays_gbp, 200.0 * nights)
        self.assertIn("trip total", card.covers)
        self.assertNotIn("flights only", card.covers)
        self.assertTrue(all(s.priced for s in card.stays))

    def test_one_stay_unread_is_partly_priced_and_never_called_a_trip_total(self):
        name, ci, co = self.lodges[0]
        card = _build(self.rows, _hotel_rates([_rate(name, ci, co, 200.0)])).cards[0]
        self.assertEqual(card.kind, "part")
        self.assertNotIn("trip total", card.covers)
        self.assertIn("not priced", card.covers)
        self.assertIsNone(card.fits, "a part-priced figure is never measured against the budget")
        self.assertEqual([s.priced for s in card.stays], [True, False])
        self.assertEqual(card.stays[1].reason, "no dated rate read")

    def test_a_rate_for_other_nights_prices_nothing(self):
        name, ci, co = self.lodges[0]
        shifted = _rate(name, "2027-07-20", "2027-07-24", 200.0)
        card = _build(self.rows, _hotel_rates([shifted])).cards[0]
        self.assertEqual(card.kind, "flights")
        self.assertIn("flights only", card.covers)

    def test_a_room_only_or_stale_or_wrong_party_rate_prices_nothing(self):
        name, ci, co = self.lodges[0]
        for bad in (_rate(name, ci, co, 200.0, board="RO"), _rate(name, ci, co, 200.0, adults=2),
                    _rate(name, ci, co, 200.0, observed="2026-10-01T09:00:00+00:00")):
            card = _build(self.rows, _hotel_rates([bad])).cards[0]
            self.assertEqual(card.kind, "flights", bad)

    def test_the_cheapest_qualifying_read_is_the_one_used_and_two_rooms_are_named(self):
        name, ci, co = self.lodges[0]
        rates = _hotel_rates([_rate(name, ci, co, 300.0), _rate(name, ci, co, 250.0, two_rooms=True)])
        stay = _build(self.rows, rates).cards[0].stays[0]
        nights = stay.nights
        self.assertEqual(stay.total_gbp, 250.0 * nights)
        self.assertTrue(stay.two_rooms)

    def test_without_a_flight_read_a_trip_with_stays_read_is_a_partly_priced_card(self):
        """14 Nov 2026: the stays are real and dated, so they belong on a card even with no accepted fare."""
        rows = _rows([])
        lodges = _plan_lodges(rows[0])
        digest = _build(rows, _hotel_rates([_rate(n, ci, co, 200.0) for n, ci, co in lodges]))
        (card,) = digest.cards
        self.assertEqual(card.kind, "part")
        self.assertIsNone(card.flights_gbp)
        self.assertEqual(card.total_gbp, card.stays_gbp)
        self.assertIn("flights not priced yet", card.covers)
        self.assertTrue(card.flights.startswith("not priced"))
        self.assertNotIn(rows[0]["trip"].title, digest.not_priced)
        self.assertFalse([p for p in digest.pending if p.name == rows[0]["trip"].title])

    def test_without_a_flight_read_and_no_stays_read_there_is_no_card(self):
        rows = _rows([])
        digest = _build(rows, None)
        self.assertEqual(digest.cards, ())
        self.assertIn(rows[0]["trip"].title, digest.not_priced)


class TripTotalRenderingTests(unittest.TestCase):
    def setUp(self):
        self.rows = _rows([deal_read(BUILD, "MIXED", 8_000)])
        lodges = _plan_lodges(self.rows[0])
        self.full = _build(self.rows, _hotel_rates([_rate(n, ci, co, 200.0) for n, ci, co in lodges]))
        self.part = _build(self.rows, _hotel_rates([_rate(*lodges[0], 200.0)]))

    def _html(self, digest):
        return hd.render_digest_html(_config(), digest, generated_at=NOW)

    def test_the_card_shows_the_total_what_it_is_made_of_and_each_stay_with_its_seller_and_link(self):
        html = self._html(self.full)
        text = visible_text(html)
        card = self.full.cards[0]
        self.assertIn(f"£{card.total_gbp:,.0f}", text)
        self.assertIn(f"flights £8,000 + stays £{card.stays_gbp:,.0f}", text)
        self.assertRegex(text, r"Africa · 1 holiday · from £")
        for stay in card.stays:
            self.assertIn(stay.property_name, text)
            self.assertIn(f"£{stay.total_gbp:,.0f}", text)
            self.assertIn(f'href="{stay.source_url}"', html)
        self.assertIn("SYNTHETIC Seller", text)
        self.assertIn("Not in the figure", text)

    def test_the_summary_leads_with_whole_trips_and_the_budget(self):
        text = visible_text(self._html(self.full))
        self.assertLess(text.index("priced in full at or under £25,000"), text.index("Africa · 1 holiday"))
        self.assertIn("cheapest £", text)
        self.assertIn("By region: Africa 1", text)

    def test_a_part_priced_trip_is_a_note_line_with_no_figure_and_no_budget_verdict(self):
        """22 Nov 2026: a partly priced result renders as a badged card in its region."""
        html = self._html(self.part)
        text = visible_text(html)
        self.assertIn("No holiday is priced in full at or under £25,000 this week · 1 partly priced across 1 region", text)
        self.assertIn("Partly priced · 4 of 12 nights priced", text)
        self.assertIn("Africa · 1 holiday", text)
        self.assertNotIn("fits the", text)

    def test_the_text_part_carries_the_same_figures(self):
        text = hd.render_digest_text(_config(), self.full, generated_at=NOW)
        card = self.full.cards[0]
        self.assertIn(f"£{card.total_gbp:,.0f}", text)
        self.assertIn("Made of: flights £8,000", text)
        for stay in card.stays:
            self.assertIn(stay.source_url, text)

    def test_a_flights_only_read_is_a_note_line_not_a_row(self):
        digest = _build(self.rows, None)
        text = visible_text(self._html(digest))
        self.assertNotIn("Flight searches, flights only", text)
        self.assertIn("Not priced in full (1):", text)
        self.assertRegex(text, r" — (fare|[0-9]+ of [0-9]+ nights|fare \+ )")


class StayWantedTests(unittest.TestCase):
    def test_every_dated_property_of_every_trip_is_listed_once_in_the_readers_shape(self):
        rows = _multi_centre_rows(_config(), fares=load([]))
        doc = tt.stay_wanted(_config(), rows)
        self.assertEqual(doc["schema"], "stay_wanted/1")
        self.assertEqual(doc["travellers"], 5)
        keys = [(s["property_name"], s["check_in"], s["check_out"]) for s in doc["stays"]]
        self.assertEqual(len(keys), len(set(keys)))
        for row in rows:
            for name, ci, co in _plan_lodges(row):
                if ci and co:
                    self.assertIn((name, ci, co), keys)
        for stay in doc["stays"]:
            self.assertLess(stay["check_in"], stay["check_out"])
            self.assertTrue(stay["query"].startswith(stay["property_name"]))
            self.assertEqual(stay["season"], "summer")

    def test_a_search_area_keeps_place_names_and_drops_descriptions(self):
        self.assertEqual(tt._search_area("Lucerne, lakefront"), "Lucerne")
        self.assertEqual(tt._search_area("Bwejuu, Zanzibar (east coast)"), "Bwejuu, Zanzibar")
        self.assertEqual(tt._search_area("Zermatt, 2222 m, Matterhorn view"), "Zermatt, Matterhorn view")

    def test_watch_list_properties_are_wanted_on_the_reference_pair(self):
        class Entry:
            name, area, url = "SYNTHETIC Island Villa", "Gili Meno", ""
        doc = tt.stay_wanted(_config(), [], watch=[Entry()], reference_pair=("2027-06-27", "2027-07-09"))
        self.assertEqual([(s["property_name"], s["check_in"], s["check_out"]) for s in doc["stays"]],
                         [("SYNTHETIC Island Villa", "2027-06-27", "2027-07-09")])


if __name__ == "__main__":
    unittest.main()


class LeadTripTests(unittest.TestCase):
    """A lead is a trip with no figure at all: only the digest and the wanted lists may see it."""

    LEAD = {"id": "LD-01", "lead": True, "season": "summer", "title": "SYNTHETIC Island 6 nights + SYNTHETIC City 6 nights",
            "stops": [{"place": "SYNTHETIC Island", "nights": 6, "airport": "ZNZ", "hotel": "",
                       "lodges": [{"name": "SYNTHETIC Reef Lodge", "nights": 6, "area": "SYNTHETIC Island",
                                   "url": "https://example.org/SYNTHETIC-reef"}]},
                      {"place": "SYNTHETIC City", "nights": 6, "airport": "MCT", "hotel": "",
                       "lodges": [{"name": "SYNTHETIC Fort Hotel", "nights": 6, "area": "SYNTHETIC City"}]}],
            "legs": [["LHR", "ZNZ"], ["ZNZ", "MCT"], ["MCT", "LHR"]], "why": "a reef lodge at a third of the usual price",
            "catch": "small planes", "source_urls": ["https://example.org/SYNTHETIC-reef"]}

    def _file(self, tmp):
        path = Path(tmp) / "mc.json"
        path.write_text(json.dumps({"schema": "multi_centre/1", "itineraries": [self.LEAD]}), encoding="utf-8")
        return str(path)

    def test_a_lead_loads_without_a_cost_range_only_when_asked_for(self):
        from public_flight_search.multi_centre import load_multi_centre
        with tempfile.TemporaryDirectory() as tmp:
            path = self._file(tmp)
            self.assertEqual(load_multi_centre(path=path, season="summer"), [])
            trips = load_multi_centre(path=path, season="summer", include_leads=True)
        self.assertEqual([t.id for t in trips], ["LD-01"])
        self.assertEqual((trips[0].cost_low_gbp, trips[0].cost_high_gbp, trips[0].confidence), (0.0, 0.0, "lead"))

    def test_the_shipped_leads_reach_the_wanted_lists_and_the_digest_but_no_range_renderer(self):
        from public_flight_search.multi_centre import load_multi_centre
        from public_flight_search.holiday_email import multi_centre_wanted, render_holiday_report_compact_text
        leads = [t for t in load_multi_centre(_config(), include_leads=True) if t.confidence == "lead"]
        plain = {t.id for t in load_multi_centre(_config())}
        self.assertFalse(plain & {t.id for t in leads})
        wanted = {w["trip"] for w in multi_centre_wanted(_config(), include_leads=True)}
        self.assertFalse({t.id for t in leads} & {w["trip"] for w in multi_centre_wanted(_config())})
        self.assertGreaterEqual(len(leads), 10)
        rows = _multi_centre_rows(_config(), fares=load([]), include_leads=True)
        digest = hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW)
        html = hd.render_digest_html(_config(), digest, generated_at=NOW)
        for trip in leads:
            self.assertIn(trip.id, wanted)
            self.assertIn(trip.title, digest.not_priced)
            self.assertTrue(trip.why, f"{trip.id}: a lead says why it is worth reading")
            for stop in trip.stops:
                for lodge in stop.lodges:
                    self.assertTrue(lodge.url.startswith("https://"), f"{trip.id}: {lodge.name} has no page")
        if leads:
            notes = visible_text(html)[visible_text(html).index("Not priced in full"):]
            for trip in leads:
                self.assertIn(trip.title, notes, trip.id)
        self.assertNotIn("£0", visible_text(html))


class NewestReadWinsTests(unittest.TestCase):
    """A fare read two weeks ago is not this week's fare, however much cheaper it was (14 Nov 2026: a 1 Nov read
    hid the read made that morning because the index kept the cheaper of two same-cabin reads whatever their age)."""

    def _read_for(self, reads):
        fares = load(reads)
        row = [r for r in _multi_centre_rows(_config(), fares=fares) if r["trip"].id == BUILD][0]
        return row["reads"]["business"]

    def test_a_later_days_read_replaces_an_earlier_cheaper_one(self):
        old = deal_read(BUILD, "MIXED", 7_000, observed="2026-11-01T09:00:00+00:00")
        new = deal_read(BUILD, "MIXED", 8_200, observed="2026-11-14T09:00:00+00:00")
        for order in ([old, new], [new, old]):
            read = self._read_for(order)
            self.assertEqual(float(read["total_gbp"]), 8_200.0, "the newest day's read, in either file order")

    def test_two_reads_on_the_same_day_keep_the_cheaper(self):
        a = deal_read(BUILD, "MIXED", 8_200, observed="2026-11-14T09:00:00+00:00")
        b = deal_read(BUILD, "MIXED", 7_900, observed="2026-11-14T15:00:00+00:00")
        for order in ([a, b], [b, a]):
            self.assertEqual(float(self._read_for(order)["total_gbp"]), 7_900.0)


class StayLineTests(unittest.TestCase):
    """14 Nov 2026, reading the rendered body: a two-room stay printed the exporter's own unit strings
    ("room only, 2 rooms, Booking.com — 3 guests — 3; Booking.com — 2 guests — 2 · Booking.com · read 14 Nov")."""

    def setUp(self):
        self.rows = _rows([deal_read(BUILD, "MIXED", 8_000)])
        self.lodges = _plan_lodges(self.rows[0])

    def _html(self, digest):
        return hd.render_digest_html(_config(), digest, generated_at=NOW)

    def test_a_two_room_stay_line_is_board_rooms_seller_read_html_and_text_alike(self):
        digest = _build(self.rows, _hotel_rates([_rate(n, ci, co, 200.0, two_rooms=True) for n, ci, co in self.lodges]))
        html, text = self._html(digest), hd.render_digest_text(_config(), digest, generated_at=NOW)
        # Brief I (14 Nov 2026): the HTML keeps "read 14 Nov" and the room counts on one line with
        # non-breaking spaces, so the visible text is compared with them as ordinary spaces.
        for part in (visible_text(html).replace("\xa0", " "), text):
            self.assertIn("2 rooms (3 + 2 guests)", part)
            self.assertIn("read 14 Nov", part)
            self.assertNotIn("SYNTHETIC room A", part)
            self.assertNotIn("guests — 3", part)
            self.assertEqual(part.count("SYNTHETIC Seller"), len(digest.cards[0].stays), "the seller is named once a stay")

    def test_one_unit_says_one_unit_for_the_party(self):
        digest = _build(self.rows, _hotel_rates([_rate(n, ci, co, 200.0) for n, ci, co in self.lodges]))
        text = hd.render_digest_text(_config(), digest, generated_at=NOW)
        self.assertIn("breakfast · one unit for 5 · nightly price × 4 nights · SYNTHETIC Seller · read 14 Nov", text)

    def test_two_rooms_with_no_stated_counts_say_only_two_rooms(self):
        rates = []
        for name, check_in, check_out in self.lodges:
            record = _rate(name, check_in, check_out, 200.0, two_rooms=True)
            record["units"] = [{"name": "SYNTHETIC room A"}, {"name": "SYNTHETIC room B"}]
            rates.append(record)
        digest = _build(self.rows, _hotel_rates(rates))
        text = hd.render_digest_text(_config(), digest, generated_at=NOW)
        self.assertIn("2 rooms", text)
        self.assertNotIn("2 rooms (", text)

    def test_a_nightly_derived_total_says_so_on_the_stay_line(self):
        digest = _build(self.rows, _hotel_rates([_rate(n, ci, co, 200.0) for n, ci, co in self.lodges]))
        card = digest.cards[0]
        self.assertTrue(all(stay.derived_total for stay in card.stays))
        html = self._html(digest)
        text = hd.render_digest_text(_config(), digest, generated_at=NOW)
        for part in (visible_text(html), text):
            self.assertIn(f"nightly price × {card.stays[0].nights} nights", part)
            self.assertEqual(part.count(hd.DERIVED_TOTAL_NOTE), 1,
                             "once per region section, which is where the card is")


class StaysWithoutAFareTests(unittest.TestCase):
    """A trip whose flights have no accepted read but whose stays were read is a partly priced card, not a name
    under "Not yet priced": the stays are the one thing a reader can act on."""

    def setUp(self):
        self.rows = _rows([deal_read(BUILD, "ECONOMY", 4_000)])
        self.lodges = _plan_lodges(self.rows[0])

    def test_the_card_counts_the_nights_and_names_why_the_flights_are_missing(self):
        digest = _build(self.rows, _hotel_rates([_rate(*self.lodges[0], 200.0)]))
        (card,) = digest.cards
        self.assertEqual(card.kind, "part")
        self.assertIsNone(card.flights_gbp)
        self.assertEqual(card.total_gbp, card.stays_gbp)
        self.assertIn("nights' stay, 5 people; flights not priced yet", card.covers)
        self.assertEqual(card.flights,
                         "not priced; the economy fare read has a leg over 8 hours; a business fare is still to be read")
        rendered = visible_text(hd.render_digest_html(_config(), digest, generated_at=NOW))
        assert "Stays read, fares still to come" not in rendered
        # 22 Nov 2026: partly priced trips render as cards in their region.
        self.assertIn("Partly priced · flights still to price", rendered)
        self.assertIn("the economy fare read has a leg over 8 hours", rendered)
        self.assertNotIn("Not priced in full", rendered)
        text = hd.render_digest_text(_config(), digest, generated_at=NOW)
        self.assertIn("Partly priced · 4 of 12 nights priced", text)
        self.assertIn("the economy fare read has a leg over 8 hours", text)

    def test_every_night_priced_without_a_fare_is_still_partly_priced(self):
        digest = _build(self.rows, _hotel_rates([_rate(n, ci, co, 200.0) for n, ci, co in self.lodges]))
        (card,) = digest.cards
        self.assertEqual(card.kind, "part")
        self.assertNotIn("Whole trips, fully priced", hd.render_digest_html(_config(), digest, generated_at=NOW))

    def test_a_lead_with_a_stay_priced_becomes_a_partly_priced_card_that_keeps_its_why(self):
        from public_flight_search.holiday_email import _multi_centre_rows
        rows = [r for r in _multi_centre_rows(_config(), fares=load([]), include_leads=True)
                if r["trip"].id == "LD-01"]
        lodges = _plan_lodges(rows[0])
        digest = _build(rows, _hotel_rates([_rate(n, ci, co, 200.0) for n, ci, co in lodges]))
        (card,) = digest.cards
        self.assertEqual(card.kind, "part")
        self.assertEqual(card.why, rows[0]["trip"].why)
        # 15 Nov 2026: the why line belongs to a whole holiday's card; a not-fully-priced trip is a name
        # in the notes, but the digest still carries its why for the trip pages.
        html = hd.render_digest_html(_config(), digest, generated_at=NOW)
        self.assertIn(hd._e(card.title), html)
        self.assertIn(hd._e(card.why), html)
        self.assertFalse([p for p in digest.pending if p.name == card.title])


class PartlyPricedOrderAndSummaryTests(unittest.TestCase):
    def setUp(self):
        self.rows = _rows([deal_read(BUILD, "MIXED", 8_000)])
        self.lodges = _plan_lodges(self.rows[0])

    def test_a_partly_priced_card_with_a_flight_read_sorts_before_a_stays_only_one(self):
        # The same synthetic trip twice: one row with a fare read, one with none. Both price the same stays.
        fare = self.rows[0]
        no_fare = dict(_rows([])[0])
        digest = _build([no_fare, fare], _hotel_rates([_rate(*self.lodges[0], 200.0)]))
        parts = [c for c in digest.cards if c.kind == "part"]
        self.assertEqual(len(parts), 2)
        self.assertIsNotNone(parts[0].flights_gbp, "the card with a fare comes first")
        self.assertIsNone(parts[1].flights_gbp)

    def test_the_summary_counts_what_is_shown(self):
        fare = self.rows[0]
        no_fare = dict(_rows([])[0])
        digest = _build([fare, no_fare], _hotel_rates([_rate(*self.lodges[0], 200.0)]))
        text = visible_text(hd.render_digest_html(_config(), digest, generated_at=NOW))
        self.assertIn("No holiday is priced in full at or under £25,000 this week · 2 partly priced across 1 region", text)
        self.assertIn("By region: Africa 2", text)
        self.assertNotIn("Not priced in full", text)

    def test_a_flights_only_week_says_nothing_is_whole_and_omits_the_zero_clauses(self):
        digest = _build(self.rows, None)
        text = visible_text(hd.render_digest_html(_config(), digest, generated_at=NOW))
        self.assertIn("No holiday is priced in full at or under £25,000 this week.", text)
        self.assertNotIn("stays only", text)
        self.assertNotIn("0 have", text)
        self.assertNotIn("flights only", text)


def _not_priced_names(html):
    """The names in the footnote only: the body's one line about everything it does not show."""
    start = html.find(">Not shown</div>")
    return html[start:] if start >= 0 else ""


def test_a_three_room_stay_takes_the_breakfast_rate_over_a_cheaper_room_only_one():
    """14 Nov 2026: one entry held both boards and only its cheapest (room only) was looked at."""
    from types import SimpleNamespace as NS
    from unittest import mock
    from public_flight_search import trip_totals as tt

    ro = NS(price_gbp=900.0, board="RO")
    bb = NS(price_gbp=1100.0, board="BB")
    entry = NS(cheapest=ro, rates=(ro, bb))
    with mock.patch.object(tt.hotel_evidence_module, "_pair_entries", return_value=(entry,)):
        assert tt._three_room_read({"k": entry}, "Palm Cove Resort", "2027-07-05", "2027-07-10") is bb


def test_a_stop_naming_several_properties_without_nights_is_never_priced_from_one_of_them():
    """14 Nov 2026: six safari nights were priced from the city hotel the stop also named."""
    from types import SimpleNamespace as NS
    from unittest import mock
    from public_flight_search import trip_totals as tt

    lodges = [NS(lodge=NS(name="Palm City Hotel", url="", area=""), check_in="", check_out="", nights=0),
              NS(lodge=NS(name="Palm Bush Camp", url="", area=""), check_in="", check_out="", nights=0)]
    stay = NS(stop=NS(place="City and bush"), lodges=lodges, check_in="2027-06-27", check_out="2027-07-03", nights=6)
    rate = NS(price_gbp=600.0, board="BB")
    with mock.patch.object(tt, "_rate_for", return_value=rate):
        (only,) = tt._stop_stays(stay, {"k": 1})
    assert not only.priced and only.nights == 6 and "not itemised" in only.reason


def _multi_property_stay(*, lodging="", nights=6):
    """A stop naming two properties with no nights against each, as `lodging` says it shares them."""
    from types import SimpleNamespace as NS
    lodges = [NS(lodge=NS(name=name, url="", area=""), check_in="", check_out="", nights=0)
              for name in ("SYNTHETIC City Hotel", "SYNTHETIC Bush Camp")]
    return NS(stop=NS(place="SYNTHETIC Park (city and bush)", lodging=lodging), lodges=lodges,
              check_in="2027-06-27", check_out="2027-07-03", nights=nights)


def _fake_rate(price):
    from types import SimpleNamespace as NS
    return NS(price_gbp=price, units=(), board="BB", source_url="https://example.org/SYNTHETIC-rate",
              observed_at="2026-11-14T09:00:00+00:00", booking_shape="single_unit", unit_guests=(5,),
              derived_total=False)


class SeveralPropertiesTests(unittest.TestCase):
    """Brief K (14 Nov 2026): a stop naming several properties says which case it is, and only
    ALTERNATIVES are priced for the whole stop. Nothing is read from the wording."""

    def _priced_by(self, prices):
        from unittest import mock
        return mock.patch.object(tt, "_rate_for",
                                 side_effect=lambda *args, **kwargs: (_fake_rate(prices[args[1]])
                                                                     if args[1] in prices else None))

    def test_alternatives_price_the_whole_stop_from_the_cheapest_read(self):
        stay = _multi_property_stay(lodging="alternatives")
        with self._priced_by({"SYNTHETIC City Hotel": 900.0, "SYNTHETIC Bush Camp": 1_400.0}):
            (only,) = tt._stop_stays(stay, {"k": 1})
        self.assertTrue(only.priced)
        self.assertEqual(only.total_gbp, 900.0)
        self.assertEqual(only.nights, 6, "each alternative holds the WHOLE stop")
        self.assertEqual((only.check_in, only.check_out), ("2027-06-27", "2027-07-03"))
        self.assertEqual(only.property_name, "SYNTHETIC City Hotel")
        self.assertEqual(only.one_of, ("SYNTHETIC City Hotel", "SYNTHETIC Bush Camp"))
        self.assertEqual(hd._stay_name(only),
                         "SYNTHETIC City Hotel (one of: SYNTHETIC City Hotel or SYNTHETIC Bush Camp)")

    def test_alternatives_with_no_read_are_unpriced_and_name_both(self):
        stay = _multi_property_stay(lodging="alternatives")
        with self._priced_by({}):
            (only,) = tt._stop_stays(stay, {"k": 1})
        self.assertFalse(only.priced)
        self.assertEqual(only.reason, "no dated rate read")
        self.assertEqual(only.property_name, "SYNTHETIC City Hotel or SYNTHETIC Bush Camp")
        self.assertEqual(only.nights, 6)

    def test_a_sequence_is_unpriced_whatever_was_read(self):
        from unittest import mock
        stay = _multi_property_stay(lodging="sequence")
        with mock.patch.object(tt, "_rate_for", side_effect=AssertionError("a sequence is never priced")):
            (only,) = tt._stop_stays(stay, {"k": 1})
        self.assertFalse(only.priced)
        self.assertEqual(only.reason, "the nights at each property are not itemised")
        self.assertEqual(only.property_name, "SYNTHETIC City Hotel, then SYNTHETIC Bush Camp")

    def test_an_unflagged_stop_keeps_todays_wording_and_is_never_priced(self):
        from unittest import mock
        stay = _multi_property_stay()
        with mock.patch.object(tt, "_rate_for", side_effect=AssertionError("an unstated stop is never priced")):
            (only,) = tt._stop_stays(stay, {"k": 1})
        self.assertFalse(only.priced)
        self.assertEqual(only.reason, "nights not itemised between these properties")
        self.assertEqual(only.property_name, "SYNTHETIC City Hotel or SYNTHETIC Bush Camp")

    def test_a_sequence_says_so_in_the_still_to_price_clause(self):
        from types import SimpleNamespace as NS
        stay = tt.StayPrice(place="SYNTHETIC Park", property_name="SYNTHETIC City Hotel, then SYNTHETIC Bush Camp",
                            check_in="2027-06-27", check_out="2027-07-03", nights=6,
                            reason="the nights at each property are not itemised", lodging="sequence")
        card = NS(stays=(stay,), areas={})
        self.assertEqual(hd._open_nights_words(card),
                         "SYNTHETIC Park 6n (SYNTHETIC City Hotel, then SYNTHETIC Bush Camp; "
                         "nights at each not itemised)")

    def test_stay_wanted_asks_for_alternatives_and_single_properties_only(self):
        from public_flight_search.multi_centre import load_multi_centre
        stops = [
            {"place": "SYNTHETIC Alt Park", "nights": 4, "airport": "NBO", "hotel": "SYNTHETIC A or SYNTHETIC B",
             "lodging": "alternatives",
             "lodges": [{"name": "SYNTHETIC Alt Lodge", "area": "SYNTHETIC Alt Park"},
                        {"name": "SYNTHETIC Alt Villa", "area": "SYNTHETIC Alt Park"}]},
            {"place": "SYNTHETIC Seq Park", "nights": 6, "airport": "MBA", "hotel": "SYNTHETIC C then SYNTHETIC D",
             "lodging": "sequence",
             "lodges": [{"name": "SYNTHETIC Seq Lodge", "area": "SYNTHETIC Seq Park"},
                        {"name": "SYNTHETIC Seq Camp", "area": "SYNTHETIC Seq Park"}]},
            {"place": "SYNTHETIC Quiet Park", "nights": 3, "airport": "ZNZ", "hotel": "SYNTHETIC E, SYNTHETIC F",
             "lodges": [{"name": "SYNTHETIC Quiet Lodge", "area": "SYNTHETIC Quiet Park"},
                        {"name": "SYNTHETIC Quiet Camp", "area": "SYNTHETIC Quiet Park"}]},
            {"place": "SYNTHETIC Solo Park", "nights": 2, "airport": "MCT", "hotel": "SYNTHETIC Solo Hotel",
             "lodges": [{"name": "SYNTHETIC Solo Hotel", "area": "SYNTHETIC Solo Park"}]},
        ]
        trip = {"id": "SYN-1", "season": "summer", "title": "SYNTHETIC parks", "stops": stops,
                "legs": [["LHR", "NBO"], ["NBO", "MBA"], ["MBA", "ZNZ"], ["ZNZ", "MCT"], ["MCT", "LHR"]],
                "cost_low_gbp": 1000, "cost_high_gbp": 2000, "cost_basis": "estimate"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mc.json"
            path.write_text(json.dumps({"schema": "multi_centre/1", "itineraries": [trip]}), encoding="utf-8")
            (loaded,) = load_multi_centre(path=path, season="summer")
        doc = tt.stay_wanted(_config(), [{"trip": loaded, "outbound": "2027-06-27", "return": "2027-07-20"}])
        listed = [(s["property_name"], s["check_in"], s["check_out"]) for s in doc["stays"]]
        self.assertIn(("SYNTHETIC Alt Lodge", "2027-06-27", "2027-07-01"), listed)
        self.assertIn(("SYNTHETIC Alt Villa", "2027-06-27", "2027-07-01"), listed)
        names = {name for name, _, _ in listed}
        self.assertEqual(names & {"SYNTHETIC Seq Lodge", "SYNTHETIC Seq Camp", "SYNTHETIC Quiet Lodge",
                                  "SYNTHETIC Quiet Camp"}, set(),
                         "a sequence or an unstated stop is not asked for: a whole-stop read at one of them is "
                         "a read nobody can use")
        self.assertIn("SYNTHETIC Solo Hotel", names, "a single property is still asked for the whole stop")
