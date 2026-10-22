"""The Economy row says what the fare that PRICED the card is, not the catalogue's usual routing (22 Oct 2026).

The 22 Oct preview put two answers on one resort card: the Economy row read "1-Stop via Addis Ababa" (the catalogue's
routing note) while the fare that priced the headline was a read of two stops, 17 hours. The Business row has taken the
read's own stops since 15 Oct (``fare_route_words``); the Economy row did not. These tests pin that it does, wherever the
Economy option is priced from a live fare, and that the catalogue's words stay where no fare was read.

Fixtures are synthetic: this repository is public.
"""

from __future__ import annotations

import dataclasses
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import flight_rows, render_holiday_report_compact

from test_business_row import UNCAPPED, _base_card, _config, _fare, _load


def _economy_deal(stops, *, layover="", carrier="SYNTHETIC carrier", total=3_200.0):
    """The July example's first card, priced from one ECONOMY read of its own pair, origin and airport."""
    config, base = _base_card()
    pair = (base.outbound_date, base.return_date)
    records = _load(config, [_fare(
        base.destination_airport, cabin="ECONOMY", total=total, stops=stops, carrier=carrier,
        layover=layover, pair=pair, origin=base.origin,
    )])
    deals = collect_holiday_deals(config, records)
    return config, base, next(d for d in deals if d.resort_name == base.resort_name)


def collect_holiday_deals(config, records):
    return hol.collect_holiday_deals(config, max_budget_gbp=UNCAPPED, live_flight_offers=records)


def _economy_option(deal):
    return next(o for o in deal.flight_options if o["kind"] == "economy")


class TheEconomyRowSaysWhatTheFareIsTests(unittest.TestCase):
    def test_a_nonstop_read_says_nonstop(self):
        _config_, _base, deal = _economy_deal(0)
        self.assertEqual(_economy_option(deal)["route"], "Nonstop")

    def test_a_one_stop_read_names_the_hub_it_states(self):
        _config_, _base, deal = _economy_deal(1, layover="Doha")
        self.assertEqual(_economy_option(deal)["route"], "1-Stop via Doha")

    def test_a_two_stop_read_says_two_stops_and_names_the_carriers_when_it_names_no_hub(self):
        _config_, _base, deal = _economy_deal(2, carrier="A Air, B Air")
        self.assertEqual(_economy_option(deal)["route"], "2-Stop (A Air · B Air)")

    def test_a_read_that_says_nothing_about_stops_states_no_route_and_the_card_keeps_its_own_words(self):
        _config_, base, deal = _economy_deal(None)
        self.assertEqual(_economy_option(deal)["route"], "", "a read that states no stops may not name any")
        economy = next(r for r in flight_rows(deal, travellers=5) if r[0] == "Economy" and "2 nights" not in r[1])
        self.assertEqual(economy[1], hol.route_words(str(base.routing or ""), origin=str(base.origin or ""),
                                                      airport=str(base.destination_airport or "")))

    def test_with_no_read_at_all_the_row_keeps_the_catalogue_words_and_no_route_of_its_own(self):
        config, base = _base_card()
        self.assertEqual(_economy_option(base)["route"], "", "no fare was read, so the option states no route")
        rows = flight_rows(base, travellers=5)
        economy = next(r for r in rows if r[0] == "Economy")
        self.assertEqual(economy[1], hol.route_words(str(base.routing or ""), origin=str(base.origin or ""),
                                                      airport=str(base.destination_airport or "")))

    def test_the_card_prints_the_fares_route_on_its_economy_row_and_no_other_economy_routing(self):
        for stops, layover, words in ((0, "", "Nonstop"), (1, "Doha", "1-Stop via Doha"),
                                      (2, "", "2-Stop (SYNTHETIC carrier)")):
            with self.subTest(stops=stops):
                config, base, deal = _economy_deal(stops, layover=layover)
                economy = next(r for r in flight_rows(deal, travellers=5) if r[0] == "Economy" and "2 nights" not in r[1])
                self.assertEqual(economy[1], words)
                html = render_holiday_report_compact(config, generated_at="2026-10-15T12:00:00+00:00", deals=[deal])
                self.assertIn(words, html)

    def test_the_headline_and_the_business_row_are_untouched_by_the_change(self):
        config, base, deal = _economy_deal(2, carrier="A Air")
        self.assertEqual(deal.cabin_class, "ECONOMY")
        business = next(o for o in deal.flight_options if o["kind"] == "business")
        self.assertTrue(business["not_priced"], "no Business fare was read, so the row still states the gap")
        before = next(o for o in base.flight_options if o["kind"] == "business")
        self.assertEqual(business["route"], before["route"],
                         "the Business gap row keeps the card's own route words, untouched by an Economy read")

    def test_the_card_no_longer_prints_a_stops_note_that_disagrees_with_its_own_row(self):
        config, base, deal = _economy_deal(2, carrier="A Air")
        html = render_holiday_report_compact(config, generated_at="2026-10-15T12:00:00+00:00", deals=[deal])
        self.assertNotIn("names the usual routing", html)


if __name__ == "__main__":
    unittest.main()
