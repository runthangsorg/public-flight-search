"""The June shortlist's stopover reads are committed, and the silly ones are not.

The July planner's shortlist is three trips (25Jun-9Jul, 27Jun-14Jul,
30Jun-20Jul). The travel session read the stopover fares for all three; these
tests hold the committed reads to that promise, and hold them to the rule that
excludes a fare more than three times its own pair's median — one read, a Muscat
stopover into Zanzibar at GBP 32,858 against a pair median of GBP 5,135, is
six times the median and would be quoted as if it were a real option.

Nothing here reads the private evidence files: the committed tuple is the
deliverable, and a test that needed the JSON would fail on a fresh checkout.
"""

import dataclasses
import statistics
import unittest
from collections import defaultdict
from html import escape
from pathlib import Path

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    STOPOVER_HUBS,
    STOPOVER_LINK_HUBS,
    collect_holiday_deals,
    load_holiday_config,
    render_flight_options,
    shortlist_date_pairs,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
UNCAPPED_GBP = 60000.0

#: The three June shortlist trips, and the date span the resort stay covers.
JUNE_PAIRS = (
    ("2027-06-25", "2027-07-09"),
    ("2027-06-27", "2027-07-14"),
    ("2027-06-30", "2027-07-20"),
)
#: The read the June session must NOT offer: over 3x its pair's median.
OUTLIER_PAIR = ("2027-06-27", "2027-07-14")
OUTLIER_HUB = "MCT"
OUTLIER_AIRPORT = "ZNZ"
OUTLIER_TOTAL = 32858.0


def _july_uncapped():
    config = load_holiday_config(JULY.read_text(encoding="utf-8"))
    return dataclasses.replace(config, max_budget_gbp=UNCAPPED_GBP)


def _priced_by_pair(rows=None):
    """Committed priced reads grouped by pair: {pair: [(hub, airport, total)]}."""
    source = hol._STOPOVER_READS if rows is None else rows
    grouped = defaultdict(list)
    for row in source:
        if str(row.get("status", "")).strip().lower() != "priced":
            continue
        if row.get("total_gbp") in (None, ""):
            continue
        grouped[tuple(row["pair"])].append(
            (str(row["hub"]).upper(), str(row["airport"]).upper(), float(row["total_gbp"]))
        )
    return grouped


class JuneShortlistPairTests(unittest.TestCase):
    """The shortlist these reads answer for is the shortlist the config draws."""

    def test_the_july_shortlist_is_the_three_june_pairs(self):
        # If the config's shortlist ever moves again, the reads are for the wrong
        # trips and this fails before a card quietly loses its stopover price.
        self.assertEqual(tuple(shortlist_date_pairs(_july_uncapped())), JUNE_PAIRS)


class JuneStopoverReadTests(unittest.TestCase):
    """Every June shortlist trip has a real fare, and no silly one."""

    def test_every_june_shortlist_pair_has_a_priced_stopover_to_phuket(self):
        grouped = _priced_by_pair()
        for pair in JUNE_PAIRS:
            with self.subTest(pair=pair):
                priced_to_phuket = [
                    (hub, total)
                    for hub, airport, total in grouped.get(pair, [])
                    if airport == "HKT"
                ]
                self.assertTrue(
                    priced_to_phuket,
                    f"no priced Phuket stopover committed for {pair}",
                )

    def test_every_june_shortlist_pair_prices_through_at_least_one_hub(self):
        grouped = _priced_by_pair()
        for pair in JUNE_PAIRS:
            with self.subTest(pair=pair):
                hubs = {hub for hub, _, _ in grouped.get(pair, [])}
                self.assertTrue(
                    hubs & set(STOPOVER_HUBS),
                    f"no committed read for {pair} uses a configured hub",
                )

    def test_the_outlier_muscat_zanzibar_read_is_not_committed(self):
        offenders = [
            (row["hub"], row["airport"], row["total_gbp"])
            for row in hol._STOPOVER_READS
            if tuple(row["pair"]) == OUTLIER_PAIR
            and str(row["hub"]).upper() == OUTLIER_HUB
            and str(row["airport"]).upper() == OUTLIER_AIRPORT
        ]
        self.assertEqual(
            offenders, [], "the six-times-median Muscat-Zanzibar read is still committed"
        )
        self.assertNotIn(OUTLIER_TOTAL, {
            float(row["total_gbp"]) for row in hol._STOPOVER_READS
        })

    def test_no_committed_read_is_more_than_three_times_its_own_pairs_median(self):
        # The rule, enforced over the whole tuple rather than one named read, so
        # the next import cannot smuggle in a different silly fare.
        for pair, reads in _priced_by_pair().items():
            median = statistics.median([total for _, _, total in reads])
            for hub, airport, total in reads:
                with self.subTest(pair=pair, hub=hub, airport=airport):
                    self.assertLessEqual(
                        total, 3 * median,
                        f"{hub}-{airport} on {pair} is more than 3x the pair median",
                    )

    def test_no_committed_read_is_for_a_pair_the_config_cannot_price(self):
        # December keeps its own; the July reads must all be July-priceable.
        config = _july_uncapped()
        priceable = {tuple(pair) for pair in hol.priceable_date_pairs(config)}
        stale = {
            tuple(row["pair"]) for row in hol._STOPOVER_READS
            if tuple(row["pair"]) not in priceable
        }
        self.assertEqual(stale, set(), "a committed read prices a pair nothing asks for")

    def test_the_cheapest_committed_stopover_is_the_read_one(self):
        # The file's own headline: Abu Dhabi into Phuket at GBP 3,218 Etihad.
        cheapest = min(
            (float(row["total_gbp"]), tuple(row["pair"]), row["hub"], row["airport"])
            for row in hol._STOPOVER_READS
        )
        self.assertEqual(cheapest[0], 3218.0)
        self.assertEqual(cheapest[2:], ("AUH", "HKT"))


def _synth_read(pair, hub, airport, *, total=4800.0, status="priced", season="summer") -> dict:
    """One SYNTHETIC stopover read, in the shape the private export carries."""
    return {
        "pair": list(pair),
        "hub": hub,
        "airport": airport,
        "origin": "LHR",
        "legs": [list(leg) for leg in hol.stopover_legs(hub, airport, pair[0], pair[1])],
        "travellers": 5,
        "cabin": "ECONOMY",
        "season": season,
        "source_url": "https://example.invalid/SYNTHETIC",
        "observed_at": "2026-10-15T00:00:00+00:00",
        "status": status,
        "total_gbp": total,
        "price_basis_text": "entire trip",
        "carrier": "SYNTHETIC carrier",
    }


class StopoverWantedTests(unittest.TestCase):
    """What this report asks to be read next (owner brief 2026-10-15).

    A long-haul card whose own (pair, hub, airport) has no priced read says "not
    priced yet". ``stopover_wanted`` is the other half of that: the same gap,
    listed in the private reader's ``--wanted`` input format, so the next read is
    one command rather than a hand-written list. The join between the two
    repositories is therefore this list's SHAPE, and nothing in it may carry a
    fare, a URL or a name — this repository is public.
    """

    def _wanted(self, *, config=None, fares=None, season="summer"):
        deals = collect_holiday_deals(config or _july_uncapped())
        source = hol.STOPOVER_FARES if fares is None else fares
        return deals, hol.stopover_wanted(deals, source, season=season)

    def test_the_list_is_the_private_readers_wanted_input_format(self):
        _deals, wanted = self._wanted()
        self.assertTrue(wanted)
        for row in wanted:
            with self.subTest(row=row):
                self.assertEqual(set(row), {"pair", "hub", "airport", "season"})
                self.assertEqual(len(row["pair"]), 2)
                self.assertIn(row["hub"], STOPOVER_LINK_HUBS)
                self.assertEqual(row["season"], "summer")
                self.assertRegex(row["airport"], r"^[A-Z]{3}$")

    def test_every_row_is_a_rendered_cards_own_pair_hub_and_airport_with_no_read(self):
        """The list is derived, not guessed: one row per (card, hub) with no fare."""
        deals, wanted = self._wanted()
        listed = {(tuple(row["pair"]), row["hub"], row["airport"]) for row in wanted}
        expected = {
            ((deal.outbound_date, deal.return_date), hub, deal.destination_airport)
            for deal in deals if deal.flight_options
            for hub in STOPOVER_LINK_HUBS
            if not hol.stopover_fares_for(
                hub, deal.destination_airport, "summer",
                pair=(deal.outbound_date, deal.return_date),
            )
        }
        self.assertTrue(expected, "every card is already priced — this test proves nothing today")
        self.assertEqual(listed, expected)
        self.assertEqual(len(wanted), len(listed), "a row is listed once, however many cards need it")

    def test_the_list_names_the_private_readers_stopover_hubs_only(self):
        # Singapore is a plane change, not a hub to stay in (owner, 2026-10-15).
        _deals, wanted = self._wanted()
        self.assertNotIn("SIN", STOPOVER_LINK_HUBS)
        self.assertNotIn("SIN", {row["hub"] for row in wanted})

    def test_a_priced_read_removes_only_its_own_row(self):
        """One fare answers one (pair, hub, airport): the other hub stays listed."""
        deals, _ = self._wanted()
        deal = deals[0]
        pair = (deal.outbound_date, deal.return_date)
        fares = hol._stopover_fares((_synth_read(pair, "DOH", deal.destination_airport),))
        self.assertTrue(hol.stopover_fares_for("DOH", deal.destination_airport, "summer",
                                               pair=pair, fares=fares))
        _deals, wanted = self._wanted(fares=fares)
        listed = {(tuple(row["pair"]), row["hub"], row["airport"]) for row in wanted}
        self.assertNotIn((pair, "DOH", deal.destination_airport), listed)
        self.assertIn((pair, "MCT", deal.destination_airport), listed)

    def test_an_unpriced_read_does_not_answer_the_row(self):
        # ``no_priced_economy_card`` is recorded so the gap is visible; it is not
        # a price, so the row is still wanted.
        deals, _ = self._wanted()
        deal = deals[0]
        pair = (deal.outbound_date, deal.return_date)
        fares = hol._stopover_fares((_synth_read(pair, "DOH", deal.destination_airport,
                                                 total=None,
                                                 status="no_priced_economy_card"),))
        _deals, wanted = self._wanted(fares=fares)
        self.assertIn((pair, "DOH", deal.destination_airport),
                      {(tuple(row["pair"]), row["hub"], row["airport"]) for row in wanted})

    def test_a_short_haul_card_is_not_asked_about(self):
        # No flight options means no stopover row at all, so there is nothing to
        # price for that card.
        deals, _ = self._wanted()
        short_haul = dataclasses.replace(deals[0], flight_options=())
        self.assertEqual(hol.stopover_wanted([short_haul], {}, season="summer"), [])

    def test_a_row_with_no_airport_or_dates_is_skipped_rather_than_listed(self):
        deals, _ = self._wanted()
        broken = dataclasses.replace(deals[0], destination_airport="", outbound_date="")
        self.assertEqual(hol.stopover_wanted([broken], {}, season="summer"), [])

    def test_the_season_asked_for_is_the_one_the_trip_prices(self):
        _deals, summer = self._wanted(season="summer")
        _deals, winter = self._wanted(season="winter")
        self.assertTrue(all(row["season"] == "winter" for row in winter))
        # The same gaps either way: what changes is the season a read must be made
        # in, so a summer card is never answered by a December read.
        self.assertEqual({tuple(row["pair"]) for row in summer},
                         {tuple(row["pair"]) for row in winter})

    def test_the_registry_the_run_priced_from_is_the_one_it_measures_the_gap_against(self):
        """A private export must satisfy the same rows the cards were priced from."""
        deals, _ = self._wanted()
        deal = deals[0]
        pair = (deal.outbound_date, deal.return_date)
        export = (_synth_read(pair, "DOH", deal.destination_airport),)
        registry = hol.stopover_fares_registry(export)
        self.assertEqual(hol.stopover_fares_registry(), hol.STOPOVER_FARES)
        wanted = hol.stopover_wanted(deals, registry, season="summer")
        self.assertNotIn((pair, "DOH", deal.destination_airport),
                         {(tuple(row["pair"]), row["hub"], row["airport"]) for row in wanted})


class UnreadPairStillOffersTheLinkTests(unittest.TestCase):
    """A trip nobody read a fare for is offered the itinerary, not a guess."""

    def test_a_pair_with_no_committed_read_renders_price_on_request(self):
        config = _july_uncapped()
        # A pair the July config prices, with no read committed for it.
        priceable = [
            tuple(pair) for pair in hol.priceable_date_pairs(config)
            if tuple(pair) not in _priced_by_pair()
        ]
        self.assertTrue(priceable, "every priceable pair already has a read")
        pair = priceable[len(priceable) // 2]

        # No committed read answers that pair, through any hub: so a card for it
        # has no number to print and must offer the itinerary instead.
        for hub in STOPOVER_HUBS:
            with self.subTest(pair=pair, hub=hub):
                self.assertEqual(hol.stopover_fares_for(hub, "HKT", "summer", pair=pair), ())

        # And the render for that pair says so, offering the multi-city link.
        deals = collect_holiday_deals(config)
        options = [
            option for deal in deals for option in deal.flight_options
            if option["kind"] in ("business", "economy", "premium_economy")
        ]
        self.assertTrue(options, "no card offered a flight option at all")
        html = render_flight_options(
            options, travellers=5, dates=pair, airport="HKT", origin="LHR"
        )
        self.assertIn("not priced yet", html)
        self.assertNotIn("price on request", html)
        self.assertIn("price this multi-city itinerary", html)
        self.assertIn(
            escape(hol.stopover_search_url("DOH", "HKT", pair[0], pair[1]), quote=True),
            html,
        )

    def test_a_shortlist_pair_with_its_read_answers_with_that_number(self):
        # The other side of the same contract: a June pair that WAS read gets its
        # own fare back, with its provenance, rather than a blank.
        for pair in JUNE_PAIRS:
            answered = {
                hub: fares
                for hub in STOPOVER_HUBS
                if (fares := hol.stopover_fares_for(hub, "HKT", "summer", pair=pair))
            }
            with self.subTest(pair=pair):
                self.assertTrue(answered, f"no hub answered for {pair}")
                for hub, fares in answered.items():
                    fare = fares[0]
                    self.assertEqual(tuple(fare["pair"]), pair)
                    self.assertGreater(float(fare["total_gbp"]), 0.0)
                    self.assertTrue(fare["source_url"].startswith("https://"))
                    self.assertTrue(str(fare["observed_at"]))
                    self.assertEqual(
                        tuple(fare["legs"]),
                        hol.stopover_legs(hub, "HKT", pair[0], pair[1],
                                          origin=fare["origin"]),
                    )


if __name__ == "__main__":
    unittest.main()
