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

from test_holiday_email_compact import _config, visible_text
from test_price_says_what_it_covers import BUILD, deal_read, load

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

    def test_without_a_flight_read_there_is_no_card_whatever_the_hotels_say(self):
        rows = _rows([])
        lodges = _plan_lodges(rows[0])
        digest = _build(rows, _hotel_rates([_rate(n, ci, co, 200.0) for n, ci, co in lodges]))
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
        self.assertIn("Whole trips, fully priced", text)
        for stay in card.stays:
            self.assertIn(stay.property_name, text)
            self.assertIn(f"£{stay.total_gbp:,.0f}", text)
            self.assertIn(f'href="{stay.source_url}"', html)
        self.assertIn("SYNTHETIC Seller", text)
        self.assertIn("Not in the figure", text)

    def test_the_summary_leads_with_whole_trips_and_the_budget(self):
        text = visible_text(self._html(self.full))
        self.assertLess(text.index("1 whole trip priced"), text.index("Whole trips, fully priced"))

    def test_a_part_priced_trip_says_which_nights_are_open_and_carries_no_budget_verdict(self):
        html = self._html(self.part)
        text = visible_text(html)
        self.assertIn("Partly priced", text)
        self.assertIn("nights still to price", text)
        self.assertIn("no dated rate read", text)
        self.assertNotIn("fits the", text)
        self.assertIn("No whole trip is priced yet this week", text)

    def test_the_text_part_carries_the_same_figures(self):
        text = hd.render_digest_text(_config(), self.full, generated_at=NOW)
        card = self.full.cards[0]
        self.assertIn(f"£{card.total_gbp:,.0f}", text)
        self.assertIn("Made of: flights £8,000", text)
        for stay in card.stays:
            self.assertIn(stay.source_url, text)

    def test_a_flights_only_read_is_a_row_not_a_card_and_names_the_stays_to_price(self):
        digest = _build(self.rows, None)
        text = visible_text(self._html(digest))
        self.assertIn("Flight searches, flights only", text)
        self.assertIn("flights only", text)


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
            self.assertIn("New ideas, fares and stays being read", visible_text(html))
        self.assertNotIn("£0", visible_text(html))
