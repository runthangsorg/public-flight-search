"""Holiday planner Business LINKS open at one traveller and say the fare is scaled.

Google Flights answers a BUSINESS search for a party over four with a
near-empty page — no Best block, one to three rows, often mixed-cabin — so a
planner link that asks for the whole party prices nothing at all. Every
Business link therefore opens at ONE traveller, and the row says so beside the
link: "per person, scaled to the party". Economy links are untouched, because
the page prices a whole Economy party normally.

What this file holds:

* the stopover link helper asks for one seat in Business, the party in the
  other cabins, including the link built for a read that carried no URL;
* the unpriced Business row on a long-haul card links one seat and carries the
  scaled note in its basis text, and the rendered row prints it beside the link;
* a card's own flight link follows its cabin: one seat on a Business card, the
  party on an Economy one;
* the far-east table's Flights link follows its cabin the same way.

Fixtures are synthetic throughout: this repository is public, so no real page,
fare or captured content appears here.
"""

from __future__ import annotations

import base64
import dataclasses
import re
import unittest
from pathlib import Path
from urllib.parse import unquote

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    build_google_flights_holiday_url,
    collect_holiday_deals,
    load_holiday_config,
    render_flight_options,
    stopover_search_url,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
DEC = ROOT / "examples" / "dec_holiday_config.json"
#: A synthetic ceiling, not the owner's budget.
UNCAPPED = 60_000.0
PAIR = ("2030-07-10", "2030-07-24")


def _varint(raw: bytes, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = raw[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7


def _seats(url: str) -> int:
    """The traveller count the URL's ``tfs`` payload asks Google for.

    ``tfs`` field 8 is a length-delimited run of one byte per passenger, so its
    length IS the seat count — the same field ``build_google_flights_url``
    writes.
    """
    raw = base64.b64decode(unquote(url.split("tfs=", 1)[1].split("&", 1)[0]))
    index = 0
    while index < len(raw):
        key, index = _varint(raw, index)
        number, wire_type = key >> 3, key & 7
        if wire_type == 2:
            length, index = _varint(raw, index)
            if number == 8:
                return length
            index += length
        elif wire_type == 0:
            _value, index = _varint(raw, index)
    raise AssertionError("no passenger field in the tfs payload")


def _config(path: Path = JULY):
    return dataclasses.replace(
        load_holiday_config(path.read_text(encoding="utf-8")), max_budget_gbp=UNCAPPED
    )


def _deal(config, destination_key: str | None = None, *, cabin: str | None = None):
    for deal in collect_holiday_deals(config, max_budget_gbp=UNCAPPED):
        if destination_key is not None and deal.destination_key != destination_key:
            continue
        if cabin is not None and str(deal.cabin_class).upper() != cabin:
            continue
        return deal
    raise AssertionError(f"no card for {destination_key!r} in cabin {cabin!r}")


def _stopover_read(*, cabin: str, total: float = 4100.0) -> dict:
    """One synthetic multi-city read, in the stopover registry's own shape."""
    return {
        "status": "priced",
        "cabin": cabin,
        "pair": list(PAIR),
        "hub": "DOH",
        "airport": "HKT",
        "origin": "LHR",
        "total_gbp": total,
        "observed_at": "2026-10-15T09:00:00+00:00",
    }


class StopoverBusinessLinksAskForOneSeatTests(unittest.TestCase):
    def test_a_business_stopover_link_asks_for_one_traveller(self):
        url = stopover_search_url(
            "DOH", "HKT", PAIR[0], PAIR[1], travellers=5, cabin_class="BUSINESS"
        )
        self.assertEqual(_seats(url), 1)

    def test_an_economy_stopover_link_keeps_the_party(self):
        url = stopover_search_url(
            "DOH", "HKT", PAIR[0], PAIR[1], travellers=5, cabin_class="ECONOMY"
        )
        self.assertEqual(_seats(url), 5, "an Economy party page prices normally")

    def test_a_premium_economy_stopover_link_keeps_the_party(self):
        url = stopover_search_url(
            "DOH", "HKT", PAIR[0], PAIR[1], travellers=5, cabin_class="PREMIUM_ECONOMY"
        )
        self.assertEqual(_seats(url), 5)

    def test_the_default_economy_link_is_unchanged(self):
        self.assertEqual(
            _seats(stopover_search_url("DOH", "HKT", PAIR[0], PAIR[1])),
            5,
            "the default party size stays 5 for Economy",
        )


class AReadWithoutItsOwnLinkGetsTheCabinSeatCountTests(unittest.TestCase):
    def _fallback_url(self, cabin: str) -> str:
        fares = hol._stopover_fares(reads=[_stopover_read(cabin=cabin)])
        row = fares[((PAIR[0], PAIR[1]), "DOH", "HKT")][0]
        self.assertTrue(row["source_url"], "a read with no link still gets one")
        return row["source_url"]

    def test_an_unread_business_link_asks_for_one_traveller(self):
        self.assertEqual(_seats(self._fallback_url("BUSINESS")), 1)

    def test_an_unread_economy_link_still_asks_for_the_party(self):
        self.assertEqual(_seats(self._fallback_url("ECONOMY")), 5)


class TheUnpricedBusinessRowLinksOneSeatAndSaysSoTests(unittest.TestCase):
    def setUp(self):
        self.deal = _deal(_config())
        self.row = next(o for o in self.deal.flight_options if o["kind"] == "business")

    def test_the_row_links_the_business_search_for_one_traveller(self):
        self.assertTrue(self.row["not_priced"], "no Business fare was read")
        self.assertEqual(_seats(self.row["source_url"]), 1)
        self.assertEqual(
            self.row["source_url"],
            hol.build_google_flights_roundtrip_url(
                origin=self.deal.origin,
                destination=self.deal.destination_airport,
                outbound_date=self.deal.outbound_date,
                return_date=self.deal.return_date,
                travellers=1,
                cabin_class="BUSINESS",
            ),
            "the unpriced row still links ITS OWN dates and departure airport",
        )

    def test_the_row_basis_names_the_basis(self):
        self.assertIn("no Business fare read", self.row["flight_basis"])
        self.assertIn(hol.SEARCHED_TRAVELLERS_NOTE, self.row["flight_basis"])
        self.assertIn("per person, scaled to the party", self.row["flight_basis"])

    def test_the_rendered_row_prints_the_note_beside_the_link(self):
        html = render_flight_options(
            self.deal.flight_options,
            travellers=5,
            dates=(self.deal.outbound_date, self.deal.return_date),
            airport=self.deal.destination_airport,
            origin=self.deal.origin,
        )
        self.assertIn(hol.SEARCHED_TRAVELLERS_NOTE, html)
        href = re.search(r'href="([^"]*)"[^>]*>price it in Business', html)
        self.assertIsNotNone(href, "the unpriced Business row still offers the link")
        self.assertEqual(_seats(href.group(1)), 1)


class ACardLinkFollowsItsCabinTests(unittest.TestCase):
    def test_a_business_card_links_one_traveller(self):
        deal = _deal(_config(DEC), "riviera_maya", cabin="BUSINESS")
        self.assertEqual(_seats(deal.flight_booking_url), 1)

    def test_an_economy_card_links_the_party(self):
        deal = _deal(_config(DEC), "tenerife", cabin="ECONOMY")
        self.assertEqual(_seats(deal.flight_booking_url), 5)


class TheFarEastFlightsLinkFollowsItsCabinTests(unittest.TestCase):
    URL = dict(
        destination="okinawa",
        origin_airports=("LHR",),
        departure_date=PAIR[0],
        return_date=PAIR[1],
        adults=5,
    )

    def test_a_business_row_links_one_traveller(self):
        self.assertEqual(_seats(build_google_flights_holiday_url(
            **self.URL, cabin_class="BUSINESS")), 1)

    def test_an_economy_row_links_the_party(self):
        self.assertEqual(_seats(build_google_flights_holiday_url(
            **self.URL, cabin_class="ECONOMY")), 5)


if __name__ == "__main__":
    unittest.main()
