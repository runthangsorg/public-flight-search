"""A Business price on every long-haul card (owner direction, 2026-10-15).

Verbatim: "i want to know direct business class prices for each hotel option
too". Every long-haul card therefore carries a Business row beside its Economy
one. The rules this file holds:

* the row is priced from a BUSINESS fare read for THIS card's own pair, origin
  and airport — a fare read for another pair, origin or airport is never borrowed
  to fill it — and where no such fare exists the row says so and links the
  Business search for those dates;
* the route text says what the FARE is: ``Nonstop``, or the stop(s) it makes,
  from the record's own fields;
* the row never becomes the card: the headline total, the at-a-glance table and
  the budget verdict stay Economy-based;
* where several Business reads answer, the MOST DIRECT one prices the row
  (fewest stops, then shortest, then cheapest) and a cheaper read that stops more
  is named on one muted line beneath it;
* a read answers for one CABIN, so a Business multi-city fare never prices an
  Economy stopover row nor the other way round.

Fixtures are synthetic throughout: this repository is public, so no real fare,
carrier booking URL or captured page appears here.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import public_flight_search.holidays as hol
from public_flight_search.holiday_email import (
    flight_rows,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_flight_options,
)
from public_flight_search.live_verify import LiveFareEvidence, load_live_flight_evidence

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
#: A synthetic ceiling, not the owner's budget.
UNCAPPED = 60_000.0
OBSERVED_AT = "2026-10-15T09:00:00+00:00"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def _config():
    return dataclasses.replace(
        load_holiday_config(JULY.read_text(encoding="utf-8")), max_budget_gbp=UNCAPPED
    )


def _base_card(config=None):
    """The card this file prices, from the shipped July config and no evidence."""
    config = config or _config()
    deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
    return config, deals[0]


def _fare(airport, *, cabin, total, stops, carrier, duration_minutes=None,
          layover="", observed_at=OBSERVED_AT, pair=None, origin=None,
          travellers=5):
    """One synthetic live-fare record in the loader's own shape."""
    return {
        "airport": airport,
        "origin": origin,
        "total_gbp": float(total),
        "basis": "whole_party_return_total",
        "cabin_class": cabin,
        "carrier": carrier,
        "source_url": "https://example.invalid/SYNTHETIC",
        "observed_at": observed_at,
        "exact_dates": {"outbound": pair[0], "return": pair[1]},
        "travellers": travellers,
        "stops": stops,
        "layover": layover,
        "duration_minutes": duration_minutes,
    }


def _load(config, records):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump({"schema": "holiday_live_evidence/1", "evidence": records}, handle)
        path = handle.name
    return load_live_flight_evidence(config, path=path, now=NOW)


def _business_option(deal):
    return next(o for o in deal.flight_options if o["kind"] == "business")


class TheBusinessRowIsOnEveryLongHaulCardTests(unittest.TestCase):
    def test_every_long_haul_card_shows_a_business_row_before_its_economy_one(self):
        deals = collect_holiday_deals(_config(), max_budget_gbp=UNCAPPED)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(card=deal.resort_name):
                self.assertEqual(deal.flight_options[0]["kind"], "business")
                self.assertEqual(deal.flight_options[0]["cabin"], "BUSINESS")
                self.assertIn(
                    "economy", [o["kind"] for o in deal.flight_options]
                )

    def test_with_no_business_read_the_row_states_the_gap_and_links_this_pair(self):
        _config_, deal = _base_card()
        row = _business_option(deal)
        self.assertTrue(row["not_priced"])
        self.assertEqual(row["total_pkg"], 0.0)
        self.assertEqual(
            row["source_url"],
            hol.build_google_flights_roundtrip_url(
                origin=deal.origin,
                destination=deal.destination_airport,
                outbound_date=deal.outbound_date,
                return_date=deal.return_date,
                travellers=5,
                cabin_class="BUSINESS",
            ),
            "the unpriced Business row must link the Business search for ITS OWN "
            "dates and departure airport",
        )
        self.assertIn("no Business fare read", row["flight_basis"])

    def test_a_short_haul_card_shows_no_business_row_at_all(self):
        # The other half of the rule: a short-haul card is unchanged.
        config = dataclasses.replace(
            load_holiday_config((ROOT / "examples" / "dec_holiday_config.json")
                                .read_text(encoding="utf-8")),
            max_budget_gbp=UNCAPPED,
        )
        for deal in collect_holiday_deals(config, max_budget_gbp=UNCAPPED):
            if deal.destination_key not in ("riviera_maya", "zanzibar"):
                with self.subTest(card=deal.resort_name):
                    self.assertNotIn(
                        "business", [o["kind"] for o in deal.flight_options]
                    )


class ABusinessReadPricesTheRowTests(unittest.TestCase):
    def test_a_business_read_for_the_cards_own_pair_prices_the_row(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        records = _load(config, [_fare(
            base.destination_airport, cabin="BUSINESS", total=26_000.0, stops=1,
            carrier="SYNTHETIC carrier", pair=pair, origin=base.origin,
        )])
        deal = collect_holiday_deals(
            config, max_budget_gbp=UNCAPPED, live_flight_offers=records,
        )[0]
        row = _business_option(deal)
        self.assertFalse(row["not_priced"])
        self.assertEqual(row["flight_cost"], 26_000.0)
        # The row is a door-to-door total for the SAME holiday: the read prices
        # the flight, the card's own figures price the stay and the ground.
        economy = next(o for o in deal.flight_options if o["kind"] == "economy")
        self.assertEqual(row["hotel_cost"], economy["hotel_cost"])
        self.assertEqual(row["uk_ground"], economy["uk_ground"])
        self.assertEqual(row["transfer"], economy["transfer"])
        self.assertEqual(
            row["total_pkg"], round(26_000.0 + row["hotel_cost"], 2)
        )
        self.assertIn("fare read", row["flight_basis"])
        # ...and the card itself is untouched: still Economy, still its own price.
        self.assertEqual(deal.cabin_class, "ECONOMY")
        self.assertEqual(deal.total_package_price_gbp, base.total_package_price_gbp)

    def test_a_business_read_for_another_pair_is_never_borrowed(self):
        config, base = _base_card()
        other_pair = next(
            tuple(pair) for pair in hol.priceable_date_pairs(config)
            if tuple(pair) != (base.outbound_date, base.return_date)
        )
        records = _load(config, [_fare(
            base.destination_airport, cabin="BUSINESS", total=18_000.0, stops=1,
            carrier="SYNTHETIC carrier", pair=other_pair, origin=base.origin,
        )])
        deal = collect_holiday_deals(
            config, max_budget_gbp=UNCAPPED, live_flight_offers=records,
        )[0]
        self.assertTrue(
            _business_option(deal)["not_priced"],
            "a fare read for another fortnight must never price this card's "
            "Business row",
        )

    def test_a_business_read_for_another_airport_is_never_borrowed(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        records = {
            ("ZZZ", "BUSINESS", pair[0], pair[1], base.origin): LiveFareEvidence(
                airport="ZZZ", total_gbp=18_000.0, basis="whole_party_return_total",
                source_url="https://example.invalid/SYNTHETIC", observed_at=OBSERVED_AT,
                cabin_class="BUSINESS", carrier="SYNTHETIC carrier", stops=1,
            )
        }
        deal = collect_holiday_deals(
            config, max_budget_gbp=UNCAPPED, live_flight_offers=records,
        )[0]
        self.assertTrue(_business_option(deal)["not_priced"])


class TheRouteTextSaysWhatTheFareIsTests(unittest.TestCase):
    #: The card's own route words, which are what a read that says nothing falls
    #: back to (the July example's Lombok routing is a via-SIN connection).
    CARD_ROUTE = "1-Stop via Bangkok"

    def _route(self, stops, *, layover="", carrier="SYNTHETIC carrier", fallback=None):
        return hol.fare_route_words(
            LiveFareEvidence(
                airport="HKT", total_gbp=1.0, basis="whole_party_return_total",
                source_url="https://example.invalid/SYNTHETIC", observed_at=OBSERVED_AT,
                cabin_class="BUSINESS", carrier=carrier, stops=stops, layover=layover,
            ),
            self.CARD_ROUTE if fallback is None else fallback,
        )

    def test_a_nonstop_read_says_nonstop(self):
        self.assertEqual(self._route(0), "Nonstop")

    def test_a_one_stop_read_names_the_hub_when_the_read_names_one(self):
        self.assertEqual(self._route(1, layover="Doha"), "1-Stop via Doha")

    def test_a_read_without_a_hub_names_the_carriers_it_flies(self):
        # A stop count plus the airline flying it is the whole of what such a
        # record states; deriving a hub from it would be a guess.
        self.assertEqual(self._route(2, carrier="A Air, B Air"),
                         "2-Stop (A Air · B Air)")

    def test_a_singapore_connection_says_it_is_a_change_of_plane(self):
        self.assertEqual(
            self._route(1, layover="SIN"),
            "1-Stop via SIN (change of plane, no stay)",
        )

    def test_a_read_that_says_nothing_keeps_the_cards_own_route_words(self):
        self.assertEqual(self._route(None), "1-Stop via Bangkok")

    def test_the_card_prints_the_fares_own_route_on_the_business_row(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        records = _load(config, [_fare(
            base.destination_airport, cabin="BUSINESS", total=26_000.0, stops=0,
            carrier="SYNTHETIC carrier", pair=pair, origin=base.origin,
        )])
        deal = collect_holiday_deals(
            config, max_budget_gbp=UNCAPPED, live_flight_offers=records,
        )[0]
        self.assertEqual(_business_option(deal)["route"], "Nonstop")
        html = render_flight_options(
            deal.flight_options, travellers=5,
            dates=(deal.outbound_date, deal.return_date),
            airport=deal.destination_airport, origin=deal.origin,
        )
        self.assertIn("(a) Business, Nonstop", html)
        rows = flight_rows(deal, travellers=5)
        self.assertEqual(rows[0][0], "Business")
        self.assertEqual(rows[0][1], "Nonstop")


class TheBusinessRowIsNeverTheCardTests(unittest.TestCase):
    """Item 4 of the brief: the headline, the at-a-glance table and the budget
    verdict stay Economy-based, with a Business row present."""

    def _render(self, *, with_read: bool):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        records = None
        if with_read:
            records = _load(config, [_fare(
                base.destination_airport, cabin="BUSINESS", total=26_000.0, stops=1,
                carrier="SYNTHETIC carrier", pair=pair, origin=base.origin,
            )])
        deals = collect_holiday_deals(
            config, max_budget_gbp=UNCAPPED, live_flight_offers=records,
        )
        html = render_holiday_report_compact(
            config, generated_at="2026-10-15T12:00:00+00:00", deals=deals,
        )
        text = render_holiday_report_compact_text(
            config, generated_at="2026-10-15T12:00:00+00:00", deals=deals,
        )
        return _glance_rows(html), deals, html, text

    def test_the_headline_and_the_glance_row_are_identical_with_or_without_a_read(self):
        without_glance, without_deals, _html, _text = self._render(with_read=False)
        with_glance, with_deals, html, text = self._render(with_read=True)
        self.assertEqual(without_glance, with_glance, "the glance table moved")
        self.assertEqual(
            [(d.resort_name, d.total_package_price_gbp, d.is_under_budget)
             for d in without_deals],
            [(d.resort_name, d.total_package_price_gbp, d.is_under_budget)
             for d in with_deals],
            "a Business row changed a card's price or its budget verdict",
        )
        # The Business row's own total is on the card, in both parts of the
        # mail, and in no glance row: the table is the Economy headline.
        # Both parts of the mail show a door-to-door figure per row, so that is
        # the Business figure to look for (the same basis as the Economy row
        # beside it, and the same as the card's headline).
        business = _business_option(with_deals[0])
        business_total = f"£{business['true_d2d']:,.0f}"
        self.assertIn(business_total, html)
        self.assertIn(business_total, text)
        self.assertNotIn(business_total, "".join(with_glance))

    def test_the_budget_line_ignores_an_unpriced_business_row(self):
        # A row with no price has no verdict: a zero total must never read as
        # the cheapest thing on the card.
        config = dataclasses.replace(_config(), max_budget_gbp=7_000.0)
        deals = collect_holiday_deals(config, max_budget_gbp=7_000.0)
        self.assertTrue(deals, "no card fits, so this test proves nothing")
        html = render_holiday_report_compact(
            config, generated_at="2026-10-15T12:00:00+00:00", deals=deals,
        )
        self.assertNotIn("Business £0", html)
        for deal in deals:
            row = _business_option(deal)
            if row["not_priced"]:
                self.assertEqual(row["total_pkg"], 0.0)
                self.assertFalse(row["within_budget"])


def _glance_rows(html: str) -> list[str]:
    """The at-a-glance rows of a compact report, as text.

    Read out of the finished e-mail rather than rebuilt, so the comparison is
    between what the reader is sent with a read and without one.
    """
    start = html.find("Total for 5</td>")
    end = html.find("</table>", start)
    block = html[start:end]
    return [
        row for row in block.replace("</tr>", "\n").splitlines()
        if "deal-" in row
    ]


class TheMostDirectFareWinsTests(unittest.TestCase):
    """Owner steer 2026-10-15: fewest stops, then shortest, then cheapest."""

    def _deal_with(self, records):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        loaded = _load(config, [
            _fare(base.destination_airport, cabin="BUSINESS", total=total, stops=stops,
                  carrier=carrier, duration_minutes=duration, observed_at=observed,
                  pair=pair, origin=base.origin)
            for total, stops, carrier, duration, observed in records
        ])
        deal = collect_holiday_deals(
            config, max_budget_gbp=UNCAPPED, live_flight_offers=loaded,
        )[0]
        return deal, _business_option(deal)

    def test_the_fewest_stops_wins_even_when_a_cheaper_read_exists(self):
        _deal, row = self._deal_with([
            # Dear and fresh, but a nonstop — and a fresher still record is the
            # one the loader keeps as the slot's own read.
            (41_000.0, 0, "SYNTHETIC nonstop", 780, "2026-10-15T09:00:00+00:00"),
            (18_500.0, 2, "SYNTHETIC two-stop", 970, "2026-10-15T11:00:00+00:00"),
        ])
        self.assertEqual(row["flight_cost"], 41_000.0)
        self.assertEqual(row["route"], "Nonstop")

    def test_the_cheaper_read_that_stops_more_is_named_on_one_muted_line(self):
        _deal, row = self._deal_with([
            (41_000.0, 0, "SYNTHETIC nonstop", 780, "2026-10-15T09:00:00+00:00"),
            (18_500.0, 2, "SYNTHETIC two-stop", 970, "2026-10-15T11:00:00+00:00"),
        ])
        self.assertEqual(row["cheaper_alternative"], {
            "stops": 2, "total_gbp": 18_500.0, "carrier": "SYNTHETIC two-stop",
        })
        self.assertEqual(
            hol.cheaper_alternative_note(row["cheaper_alternative"]),
            "cheaper with 2 stops: £18,500 (SYNTHETIC two-stop)",
        )

    def test_the_note_reads_as_the_next_best_fare_not_the_absolute_cheapest(self):
        # Both cheaper reads stop more: the one nearer in directness is named, so
        # the line never skips over a nearer alternative.
        _deal, row = self._deal_with([
            (41_000.0, 0, "SYNTHETIC nonstop", 780, "2026-10-15T09:00:00+00:00"),
            (26_000.0, 1, "SYNTHETIC one-stop", 900, "2026-10-15T10:00:00+00:00"),
            (18_500.0, 2, "SYNTHETIC two-stop", 970, "2026-10-15T11:00:00+00:00"),
        ])
        self.assertEqual(row["cheaper_alternative"]["stops"], 1)
        self.assertEqual(row["cheaper_alternative"]["total_gbp"], 26_000.0)

    def test_the_shorter_journey_breaks_a_tie_on_stops(self):
        _deal, row = self._deal_with([
            (30_000.0, 1, "SYNTHETIC slow", 1_200, "2026-10-15T09:00:00+00:00"),
            (33_000.0, 1, "SYNTHETIC quick", 900, "2026-10-15T11:00:00+00:00"),
        ])
        self.assertEqual(row["route"], "1-Stop (SYNTHETIC quick)")
        self.assertEqual(row["flight_cost"], 33_000.0)

    def test_nothing_cheaper_is_named_when_the_cheaper_read_stops_no_more(self):
        _deal, row = self._deal_with([
            (41_000.0, 1, "SYNTHETIC direct-ish", 900, "2026-10-15T09:00:00+00:00"),
            (20_000.0, 1, "SYNTHETIC same-stops", 1_100, "2026-10-15T11:00:00+00:00"),
        ])
        # A cheaper fare with as few stops is the fare the choice above would
        # already have taken; the line has nothing to say.
        self.assertIsNone(row["cheaper_alternative"])

    def test_the_loader_keeps_the_reads_it_did_not_choose(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        loaded = _load(config, [
            _fare(base.destination_airport, cabin="BUSINESS", total=18_500.0, stops=2,
                  carrier="SYNTHETIC two-stop", pair=pair, origin=base.origin,
                  observed_at="2026-10-15T11:00:00+00:00"),
            _fare(base.destination_airport, cabin="BUSINESS", total=41_000.0, stops=0,
                  carrier="SYNTHETIC nonstop", pair=pair, origin=base.origin,
                  observed_at="2026-10-15T09:00:00+00:00"),
        ])
        key = (base.destination_airport, "BUSINESS", pair[0], pair[1], base.origin)
        slot = loaded[key]
        # The slot still holds ONE fare (the freshest, as before)...
        self.assertEqual(slot.total_gbp, 18_500.0)
        # ...and the read it beat rides along, so the row can choose on
        # directness without a second look at the file.
        self.assertEqual(
            [(alt.stops, alt.total_gbp) for alt in slot.alternates],
            [(0, 41_000.0)],
        )

    def test_re_reading_the_same_fare_does_not_pile_up_alternatives(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        same = _fare(base.destination_airport, cabin="BUSINESS", total=18_500.0,
                     stops=2, carrier="SYNTHETIC two-stop", pair=pair,
                     origin=base.origin)
        loaded = _load(config, [dict(same), dict(same)])
        key = (base.destination_airport, "BUSINESS", pair[0], pair[1], base.origin)
        self.assertEqual(loaded[key].alternates, ())


class AReadAnswersOneCabinTests(unittest.TestCase):
    """Item 5: cabin is part of what a stopover read answers for."""

    def _registry(self, rows):
        return hol._stopover_fares(tuple(rows))

    def _row(self, cabin, pair, hub="DOH", total=5_000.0):
        return {
            "pair": list(pair), "hub": hub, "airport": "HKT", "origin": "LHR",
            "legs": [list(leg) for leg in hol.stopover_legs(hub, "HKT", pair[0], pair[1])],
            "travellers": 5, "cabin": cabin, "season": "summer",
            "source_url": "https://example.invalid/SYNTHETIC",
            "observed_at": OBSERVED_AT, "status": "priced", "total_gbp": total,
            "carrier": "SYNTHETIC carrier",
        }

    def test_a_business_read_never_prices_the_economy_row(self):
        pair = ("2027-06-27", "2027-07-14")
        registry = self._registry([self._row("BUSINESS", pair)])
        self.assertEqual(
            hol.stopover_fares_for("DOH", "HKT", "summer", pair=pair,
                                   cabin="ECONOMY", fares=registry),
            (),
        )
        self.assertTrue(
            hol.stopover_fares_for("DOH", "HKT", "summer", pair=pair,
                                   cabin="BUSINESS", fares=registry)
        )

    def test_an_economy_read_never_prices_the_business_row(self):
        pair = ("2027-06-27", "2027-07-14")
        registry = self._registry([self._row("ECONOMY", pair)])
        self.assertEqual(
            hol.stopover_fares_for("DOH", "HKT", "summer", pair=pair,
                                   cabin="BUSINESS", fares=registry),
            (),
        )
        self.assertTrue(
            hol.stopover_fares_for("DOH", "HKT", "summer", pair=pair,
                                   cabin="ECONOMY", fares=registry)
        )

    def test_a_read_with_no_cabin_field_counts_as_economy(self):
        pair = ("2027-06-27", "2027-07-14")
        row = self._row("ECONOMY", pair)
        del row["cabin"]
        registry = self._registry([row])
        self.assertTrue(
            hol.stopover_fares_for("DOH", "HKT", "summer", pair=pair,
                                   cabin="ECONOMY", fares=registry)
        )
        self.assertEqual(
            hol.stopover_fares_for("DOH", "HKT", "summer", pair=pair,
                                   cabin="BUSINESS", fares=registry),
            (),
        )

    def test_both_cabins_survive_the_cheapest_read_rule(self):
        # Two reads for one itinerary are not competing: they are two products,
        # so the Business one is not deleted by a cheaper Economy read.
        pair = ("2027-06-27", "2027-07-14")
        registry = self._registry([
            self._row("ECONOMY", pair, total=5_000.0),
            self._row("BUSINESS", pair, total=31_000.0),
        ])
        self.assertEqual(
            hol.stopover_fares_for("DOH", "HKT", "summer", pair=pair,
                                   cabin="BUSINESS", fares=registry)[0]["total_gbp"],
            31_000.0,
        )

    def test_the_median_the_misread_rule_uses_is_per_cabin(self):
        # A Business fare is a different product at a different price; sharing
        # one median would read every good Business fare as a mis-read.
        pair = ("2027-06-27", "2027-07-14")
        economy = self._row("ECONOMY", pair, total=5_000.0)
        business = self._row("BUSINESS", pair, total=31_000.0)
        kept, excluded = hol._without_stopover_outliers((economy, business))
        self.assertEqual([row["cabin"] for row in kept], ["ECONOMY", "BUSINESS"])
        self.assertEqual(excluded, [])

    def test_a_business_stopover_read_puts_a_business_stopover_row_on_the_card(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        saved = hol.STOPOVER_FARES
        hol.STOPOVER_FARES = self._registry([
            {**self._row("BUSINESS", pair, total=21_000.0),
             "airport": base.destination_airport},
        ])
        try:
            deal = collect_holiday_deals(config, max_budget_gbp=UNCAPPED)[0]
        finally:
            hol.STOPOVER_FARES = saved
        kinds = [o["kind"] for o in deal.flight_options]
        self.assertIn("stopover_business", kinds)
        self.assertNotIn("stopover", kinds, "no Economy read prices the Economy row")
        business_stopover = next(
            o for o in deal.flight_options if o["kind"] == "stopover_business"
        )
        self.assertEqual(business_stopover["cabin"], "BUSINESS")
        self.assertEqual(business_stopover["flight_cost"], 21_000.0)
        self.assertIn("business fare read", business_stopover["flight_basis"])
        rows = flight_rows(deal, travellers=5)
        self.assertIn(
            ("Business", "1-Stop via Doha, 2 nights each way",
             f"£{business_stopover['true_d2d']:,.0f}"),
            rows,
        )
        html = render_flight_options(
            deal.flight_options, travellers=5,
            dates=(deal.outbound_date, deal.return_date),
            airport=deal.destination_airport, origin=deal.origin,
        )
        self.assertIn("Business + 2 nights Doha each way", html)


class BusinessAcrossAllOriginsTests(unittest.TestCase):
    """Rank BUSINESS candidates across every config origin; name airport when it differs."""

    def test_business_chosen_from_different_origin_when_more_direct(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        # Economy fare comes from base.origin (e.g. LHR); Business fare from different origin
        # is more direct (fewer stops) and should be chosen.
        other_origin = "LGW" if str(base.origin).upper() != "LGW" else "MAN"
        records = _load(config, [
            # Cheaper but more stops from the economy's origin - should not be chosen
            _fare(base.destination_airport, cabin="BUSINESS", total=18_500.0, stops=2,
                  carrier="SYNTHETIC two-stop", pair=pair, origin=base.origin,
                  duration_minutes=970),
            # More direct (nonstop) from different origin - should be chosen
            _fare(base.destination_airport, cabin="BUSINESS", total=41_000.0, stops=0,
                  carrier="SYNTHETIC nonstop", pair=pair, origin=other_origin,
                  duration_minutes=780),
        ])
        deal = collect_holiday_deals(
            config, max_budget_gbp=UNCAPPED, live_flight_offers=records,
        )[0]
        row = _business_option(deal)
        self.assertFalse(row["not_priced"])
        self.assertEqual(row["flight_cost"], 41_000.0)
        self.assertEqual(row["route"], "Nonstop")
        # Airport differs from economy's origin - should be named/reflected
        self.assertEqual(str(row["origin"]).upper(), other_origin)


if __name__ == "__main__":
    unittest.main()
