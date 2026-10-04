"""The stopover option's shape: which legs, how many nights, whose fare.

Owner brief 2026-10-04 (H4). The stopover option leaves London on the pair's own
outbound date, reaches the resort two days later, comes back through the hub on
the return date and lands two days after that — so the resort stay is the
pair's nights less two, and the whole thing is priced as one package.

Three things have to hold together, and each is a way this could quietly lie:

* the **legs**. A link and a fare must describe the same journey, so both come
  from `holidays.stopover_legs`. The old shape (hub on outbound-2) still produced
  a valid-looking multi-city URL, for the wrong dates.
* the **nights**. A stopover option that prices the full stay is not a cheaper
  option, it is a different holiday quoted at the wrong price.
* the **fare's own pair**. A read is for the dates it was read for; every other
  pair, and every read that did not come back priced, is "price on request".

The figures here are synthetic and stamped SYNTHETIC, so they can never be
mistaken for a read.
"""

from __future__ import annotations

import base64
import dataclasses
import unittest
from html import escape
from pathlib import Path
from urllib.parse import unquote

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    priceable_date_pairs,
    render_flight_options,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
UNCAPPED_GBP = 60000.0

# The pair from the brief: "leave from 26 June onwards".
PAIR = ("2027-06-26", "2027-07-10")
EXPECTED_LEGS = (
    ("LHR", "DOH", "2027-06-26"),
    ("DOH", "HKT", "2027-06-28"),
    ("HKT", "DOH", "2027-07-10"),
    ("DOH", "LHR", "2027-07-12"),
)


def _payload(url: str) -> bytes:
    return base64.b64decode(unquote(url.split("tfs=", 1)[1].split("&", 1)[0]))


def _july_uncapped():
    config = load_holiday_config(JULY.read_text(encoding="utf-8"))
    return dataclasses.replace(config, max_budget_gbp=UNCAPPED_GBP)


def _read(pair, hub, airport, *, total=5000.0, status="priced",
          carrier="SYNTHETIC carrier", observed_at="synthetic", source_url="",
          season="summer") -> dict:
    """One stopover read row, in the shape ``_STOPOVER_READS`` holds."""
    return {
        "pair": tuple(pair),
        "hub": hub,
        "airport": airport,
        "total_gbp": total,
        "carrier": carrier,
        "status": status,
        "observed_at": observed_at,
        "season": season,
        "source_url": source_url,
    }


def _registry_from(rows) -> dict:
    """The fare registry those reads produce, without leaving the module changed."""
    saved = hol._STOPOVER_READS
    hol._STOPOVER_READS = tuple(rows)
    try:
        return hol._stopover_fares()
    finally:
        hol._STOPOVER_READS = saved


def _synthetic_fares(config, *, airports=("HKT",), hubs=("DOH", "MCT", "AUH", "DXB")):
    """Read fares for every pair this config prices, keyed as the code keys them."""
    rows = []
    for pair in priceable_date_pairs(config):
        for index, hub in enumerate(hubs):
            for airport in airports:
                rows.append(_read(pair, hub, airport, total=5000.0 + 100.0 * index))
    return _registry_from(rows)


def _with_fares(registry):
    """Collect the deals against `registry`, then put the real one back."""
    def collect(config):
        saved = hol.STOPOVER_FARES
        hol.STOPOVER_FARES = registry
        try:
            return collect_holiday_deals(config)
        finally:
            hol.STOPOVER_FARES = saved
    return collect


class StopoverLegShapeTests(unittest.TestCase):
    """The four legs, and the URL that offers them for pricing."""

    def test_the_legs_of_a_stopover_itinerary_for_a_june_pair(self):
        self.assertEqual(hol.stopover_legs("DOH", "HKT", PAIR[0], PAIR[1]), EXPECTED_LEGS)

    def test_the_price_it_yourself_link_carries_exactly_those_legs(self):
        # Bit-for-bit equality with a URL built from the legs above: the link a
        # card offers and the itinerary it describes cannot drift apart.
        self.assertEqual(
            hol.stopover_search_url("DOH", "HKT", PAIR[0], PAIR[1]),
            hol.build_google_flights_legs_url(
                EXPECTED_LEGS, travellers=5, cabin_class="ECONOMY"
            ),
        )

    def test_the_link_names_the_four_flights_and_their_dates(self):
        payload = _payload(hol.stopover_search_url("DOH", "HKT", PAIR[0], PAIR[1]))
        for _origin, airport, day in EXPECTED_LEGS:
            self.assertIn(airport.encode(), payload)
            self.assertIn(day.encode(), payload)
        # The old shape flew to the hub two days BEFORE the pair's outbound date.
        self.assertNotIn(b"2027-06-24", payload)

    def test_a_committed_read_is_priced_on_the_same_legs_as_its_link(self):
        fare = _registry_from([_read(PAIR, "DOH", "HKT")])[(PAIR, "DOH", "HKT")][0]
        self.assertEqual(tuple(fare["legs"]), EXPECTED_LEGS)
        self.assertEqual(
            fare["source_url"], hol.stopover_search_url("DOH", "HKT", PAIR[0], PAIR[1])
        )


class StopoverResortNightsTests(unittest.TestCase):
    """The resort stay is the pair's nights less the two days spent flying."""

    def _first_stopover_card(self):
        config = _july_uncapped()
        deals = _with_fares(_synthetic_fares(config))(config)
        cards = [deal for deal in deals
                 if any(option["kind"] == "stopover" for option in deal.flight_options)]
        self.assertTrue(cards, "no card carried a stopover option")
        return cards[0]

    def test_the_stopover_stay_is_two_nights_shorter_than_the_economy_stay(self):
        deal = self._first_stopover_card()
        economy = next(o for o in deal.flight_options if o["kind"] == "economy")
        nightly = economy["hotel_cost"] / economy["nights"]
        stopovers = [o for o in deal.flight_options if o["kind"] == "stopover"]
        self.assertTrue(stopovers)
        for stopover in stopovers:
            with self.subTest(hub=stopover["hub"]):
                nights = stopover["nights"]
                self.assertGreaterEqual(nights, 3, "the pair is too short to fly two days")
                self.assertEqual(stopover["resort_nights"], nights - 2)
                # Same hotel and board, so the only difference is how many
                # nights of it: the same nightly rate, two nights fewer.
                self.assertAlmostEqual(
                    nightly * (nights - 2), stopover["hotel_cost"], places=2
                )
                self.assertLess(stopover["hotel_cost"], nightly * nights)
                self.assertGreater(stopover["hotel_cost"], 0)

    def test_a_stopover_row_is_only_offered_for_the_cards_own_dates(self):
        config = _july_uncapped()
        deals = _with_fares(_synthetic_fares(config))(config)
        checked = 0
        wrong_dates = []
        for deal in deals:
            for option in deal.flight_options:
                if not option["kind"].startswith("stopover"):
                    continue
                checked += 1
                if (option["outbound"], option["return"]) != (deal.outbound_date,
                                                               deal.return_date):
                    wrong_dates.append(
                        f'{deal.resort_name} {option["hub"]} priced for '
                        f'{option["outbound"]}→{option["return"]} on a card for '
                        f'{deal.outbound_date}→{deal.return_date}'
                    )
        self.assertGreater(checked, 0, "no card was priced a stopover")
        self.assertEqual(wrong_dates, [])

    def test_the_option_states_the_split_of_nights(self):
        deal = self._first_stopover_card()
        # Only the cheapest stopover is rendered in full; that is the one whose
        # numbers the reader is reading.
        stopover = hol._cheapest_stopover(
            [o for o in deal.flight_options if o["kind"] == "stopover"]
        )
        html = render_flight_options(
            deal.flight_options, travellers=5,
            dates=(stopover["outbound"], stopover["return"]),
            airport="HKT", origin="LHR",
        )
        self.assertIn(
            f'{stopover["resort_nights"]} nights at the resort + '
            f'{stopover["hub_nights_each_way"]} in {stopover["hub_label"]} each way',
            html,
        )
        # The two nights in the hub are still priced as their own hotel.
        self.assertEqual(stopover["stopover_nights"], 4)
        self.assertGreater(stopover["stopover_hotel_cost"], 0)

    def test_the_other_options_keep_the_full_stay(self):
        deal = self._first_stopover_card()
        full_stay = next(o for o in deal.flight_options if o["kind"] == "economy")["hotel_cost"]
        for option in deal.flight_options:
            if option["kind"].startswith("stopover"):
                continue
            with self.subTest(kind=option["kind"]):
                self.assertNotIn("resort_nights", option)
                self.assertEqual(option["hotel_cost"], full_stay)


class StopoverFarePairTests(unittest.TestCase):
    """A read answers one pair, one hub, one airport — and only when priced."""

    def test_a_read_for_one_pair_is_never_used_for_another(self):
        saved = hol.STOPOVER_FARES
        hol.STOPOVER_FARES = _registry_from([_read(PAIR, "DOH", "HKT")])
        other_pair = ("2027-07-12", "2027-07-26")
        try:
            self.assertTrue(hol.stopover_fares_for("DOH", "HKT", "summer", pair=PAIR))
            self.assertEqual(
                hol.stopover_fares_for("DOH", "HKT", "summer", pair=other_pair), ()
            )
            # Nor for another airport on the same pair.
            self.assertEqual(hol.stopover_fares_for("DOH", "USM", "summer", pair=PAIR), ())
            # And asking for every pair at once still only finds this one.
            self.assertEqual(len(hol.stopover_fares_for("DOH", "HKT", "summer")), 1)
        finally:
            hol.STOPOVER_FARES = saved

    def test_a_card_priced_for_another_pair_gets_no_stopover_number(self):
        config = _july_uncapped()
        # A read for a pair the config does not price.
        unpriceable = ("2027-06-20", "2027-07-04")
        deals = _with_fares(_registry_from([_read(unpriceable, "DOH", "HKT")]))(config)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertNotIn("stopover", [o["kind"] for o in deal.flight_options])

    def test_a_non_priced_read_never_yields_a_number(self):
        for status in ("no_priced_economy_card", "blocked", "error"):
            with self.subTest(status=status):
                registry = _registry_from([_read(PAIR, "DOH", "HKT", status=status)])
                self.assertEqual(registry, {})
                saved = hol.STOPOVER_FARES
                hol.STOPOVER_FARES = registry
                try:
                    self.assertEqual(
                        hol.stopover_fares_for("DOH", "HKT", "summer", pair=PAIR), ()
                    )
                finally:
                    hol.STOPOVER_FARES = saved

    def test_a_priced_read_without_a_total_never_yields_a_number(self):
        self.assertEqual(_registry_from([_read(PAIR, "DOH", "HKT", total=None)]), {})
        self.assertEqual(_registry_from([_read(PAIR, "DOH", "HKT", total="")]), {})

    def test_a_card_with_no_row_says_price_on_request_and_offers_the_legs(self):
        config = _july_uncapped()
        deals = _with_fares({})(config)
        options = [o for deal in deals for o in deal.flight_options
                   if o["kind"] in ("business", "economy")]
        self.assertTrue(options)
        html = render_flight_options(
            options, travellers=5, dates=PAIR, airport="HKT", origin="LHR"
        )
        self.assertIn("price on request", html)
        self.assertIn("price this multi-city itinerary", html)
        # The link it offers is the new-shape itinerary for this pair (escaped
        # for the href, as every URL in the report is).
        self.assertIn(
            escape(hol.stopover_search_url("DOH", "HKT", PAIR[0], PAIR[1]), quote=True),
            html,
        )

    def test_a_priced_read_keeps_its_provenance(self):
        read = _read(
            PAIR, "DOH", "HKT",
            observed_at="2026-10-04T09:00:00Z",
            source_url="https://www.google.com/travel/flights/search?tfs=synthetic",
        )
        fare = _registry_from([read])[(PAIR, "DOH", "HKT")][0]
        self.assertEqual(fare["observed_at"], "2026-10-04T09:00:00Z")
        self.assertEqual(fare["source_url"], read["source_url"])

    def test_a_read_renders_its_observation_date_on_the_card(self):
        config = _july_uncapped()
        registry = _registry_from([
            _read(pair, "DOH", "HKT", observed_at="2026-10-04T09:00:00Z")
            for pair in priceable_date_pairs(config)
        ])
        deals = _with_fares(registry)(config)
        options = [o for deal in deals for o in deal.flight_options
                   if o["kind"] == "stopover"]
        self.assertTrue(options)
        self.assertTrue(all("read 2026-10-04" in o["flight_basis"] for o in options))

    def test_carrier_names_run_together_are_split_for_display(self):
        fare = _registry_from([
            _read(PAIR, "DOH", "HKT", carrier="Qatar AirwaysBritish Airways")
        ])[(PAIR, "DOH", "HKT")][0]
        self.assertEqual(fare["carrier"], "Qatar Airways / British Airways")

    def test_carrier_text_that_already_separates_its_names_is_left_alone(self):
        for raw in ("Qatar Airways / British Airways",
                    "Emirates, then flydubai / Emirates",
                    "Qatar Airways via Doha to Muscat, then Oman Air",
                    "SYNTHETIC carrier"):
            with self.subTest(raw=raw):
                self.assertEqual(hol._display_carrier(raw), raw)


class StopoverHubOrderTests(unittest.TestCase):
    """DOH and MCT come before the UAE hubs, whatever the prices say."""

    def test_the_hub_order_is_the_owners(self):
        order = list(hol.STOPOVER_HUBS)
        self.assertEqual(order[:2], ["DOH", "MCT"])
        self.assertEqual([hub for hub in order if hub in ("AUH", "DXB")], ["AUH", "DXB"])
        # The unpriced link list is drawn from the same order.
        self.assertEqual(
            list(hol.STOPOVER_LINK_HUBS),
            [hub for hub in order if hub in hol.STOPOVER_LINK_HUBS],
        )

    def test_a_cards_stopover_options_follow_the_hub_order(self):
        config = _july_uncapped()
        deals = _with_fares(_synthetic_fares(config))(config)
        expected = list(hol.STOPOVER_HUBS)
        checked = 0
        for deal in deals:
            hubs = [o["hub"] for o in deal.flight_options if o["kind"] == "stopover"]
            if not hubs:
                continue
            checked += 1
            with self.subTest(resort=deal.resort_name):
                self.assertEqual(hubs, sorted(hubs, key=expected.index))
        self.assertGreater(checked, 0, "no card was priced a stopover")


class StopoverRegistryTests(unittest.TestCase):
    """Whatever reads are committed, the registry keeps its promises."""

    def test_every_committed_read_is_a_priced_row_with_a_total(self):
        for row in hol._STOPOVER_READS:
            with self.subTest(pair=row.get("pair"), hub=row.get("hub")):
                self.assertEqual(str(row.get("status", "")).lower(), "priced")
                self.assertIsNotNone(row.get("total_gbp"))
                self.assertTrue(str(row.get("observed_at", "")))
                self.assertIn(str(row.get("hub", "")).upper(), hol.STOPOVER_HUBS)
                self.assertIn(str(row.get("season", "summer")).strip().lower(),
                              {"summer", "winter"})

    def test_every_fare_is_keyed_by_its_own_pair_and_carries_provenance(self):
        for (pair, hub, airport), fares in hol.STOPOVER_FARES.items():
            for fare in fares:
                with self.subTest(pair=pair, hub=hub, airport=airport):
                    self.assertEqual(tuple(fare["pair"]), tuple(pair))
                    self.assertTrue(str(fare.get("observed_at", "")))
                    self.assertTrue(fare["source_url"].startswith("https://"))
                    self.assertTrue(str(fare.get("carrier", "")))
                    self.assertEqual(
                        tuple(fare["legs"]),
                        hol.stopover_legs(hub, airport, pair[0], pair[1],
                                          origin=fare["origin"]),
                    )

    def test_a_stored_source_url_matches_the_legs_it_was_read_for(self):
        # A hand-copied URL can outlive the leg shape it was built for. Every
        # committed read's stored URL must be the URL this code builds for its
        # own legs, or the fare would point somewhere the report does not
        # describe.
        for row in hol._STOPOVER_READS:
            legs = hol.stopover_legs(row["hub"], row["airport"], row["pair"][0], row["pair"][1])
            with self.subTest(pair=row["pair"], hub=row["hub"], airport=row["airport"]):
                self.assertEqual(
                    row["source_url"],
                    hol.build_google_flights_legs_url(
                        legs, travellers=5, cabin_class="ECONOMY"
                    ),
                )

    def test_a_winter_read_never_answers_a_summer_question(self):
        rows = [
            _read(PAIR, "DOH", "HKT", season="summer"),
            _read(PAIR, "DOH", "USM", season="winter"),
        ]
        saved = hol.STOPOVER_FARES
        hol.STOPOVER_FARES = _registry_from(rows)
        try:
            self.assertEqual(len(hol.stopover_fares_for("DOH", "HKT", "winter", pair=PAIR)), 0)
            self.assertEqual(len(hol.stopover_fares_for("DOH", "USM", "summer", pair=PAIR)), 0)
            self.assertEqual(len(hol.stopover_fares_for("DOH", "USM", "winter", pair=PAIR)), 1)
        finally:
            hol.STOPOVER_FARES = saved


if __name__ == "__main__":
    unittest.main()