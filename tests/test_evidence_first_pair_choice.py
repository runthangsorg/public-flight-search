"""A card's dates come from a trip with real fares when one exists.

WHY this file exists
--------------------
``collect_holiday_deals`` priced every in-band pair and showed the cheapest.
Because the flight benchmark does not move with the date, "cheapest" was
always the SHORTEST stay — and in July that was 1 Jul -> 13 Jul, a pair no
fare and no stopover read was ever collected for. The 33 live flight fares
and 17 stopover fares the private engine had actually read were for
26 Jun -> 10 Jul, 1 Jul -> 15 Jul and 3 Jul -> 24 Jul, and none of them
reached a card. So the report the reader paid for was, on every July card,
an estimate for dates nobody priced, beside a folder full of real numbers.

The fix is to rank candidates by evidence first and price second: a pair some-
body priced for this exact holiday beats a cheaper pair that is only modelled,
and within one evidence class the cheapest still wins. It is exactly that
ranking, on exactly the pair a card is built on.

What these tests pin:

* a read fare on a longer pair beats a cheaper modelled short one;
* with no evidence anywhere the choice is EXACTLY what it was before - the
  cheapest pair, with the shipped December config still on its headline pair;
* two read fares are still ranked by price between them;
* an AGED read still counts as read: the age is the freshness chip's business,
  and it is not a reason to prefer a modelled number for the same holiday;
* hotel evidence counts the same way as flight evidence - a rate read for these
  dates beats the catalogue stay, and two read halves outrank one;
* nothing else moves: the budget still rejects an evidenced pair over the
  ceiling, a resort that made a card still makes one, and a tie still resolves
  to the headline pair.

Synthetic throughout: a two-pair Antalya window, invented fares and an invented
rate file. No figure here came from an evidence export or a private read.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    option_evidence_class,
    priceable_date_pairs,
    priced_date_pair,
    pricing_order,
)
from public_flight_search.hotel_evidence import (
    consume_hotel_skip_log,
    load_hotel_evidence,
)
from public_flight_search.live_verify import LiveFareEvidence

ROOT = Path(__file__).parents[1]
DEC_CONFIG = ROOT / "examples" / "dec_holiday_config.json"

RESORT = "Concorde De Luxe Resort"
AIRPORT = "AYT"

#: A 12-21 band is not what these tests are about. 12-14 gives three priced
#: pairs out of four, so "the short one" and "the long one" are both real
#: candidates and the band is not doing the choosing:
#:
#:     17 Dec -> 29 Dec   12 nights   (cheapest when everything is modelled)
#:     17 Dec -> 31 Dec   14 nights   the HEADLINE pair - middle of the
#:                                     shortlist, so ties resolve to it
#:     19 Dec -> 31 Dec   12 nights
#:
#: 19 Dec -> 29 Dec is ten nights and out of band on purpose: a pair the run
#: does not price must stay out of the answer.
BAND_CONFIG = """
{
  "report_title": "Evidence first",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 12,
  "max_nights": 14,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-17", "2026-12-19"],
  "return_dates": ["2026-12-29", "2026-12-31"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"], "flight_hours": 4.5}
  ]
}
"""

#: The same window pinned to twelve nights only: two priced pairs that cost
#: exactly the same, so the only thing that can choose between them is the
#: order they are evaluated in.
TIE_CONFIG = BAND_CONFIG.replace('"max_nights": 14,', '"max_nights": 12,')

SHORT_PAIR = ("2026-12-17", "2026-12-29")
LONG_PAIR = ("2026-12-17", "2026-12-31")
OTHER_SHORT_PAIR = ("2026-12-19", "2026-12-31")

#: Antalya's whole-party economy benchmark, and the suite's nightly rate, as
#: the catalogue states them. A modelled twelve-night stay is therefore
#: 648 + (12 x 150) = 2,448 and the fourteen-night one 648 + (14 x 150) = 2,748.
BENCHMARK_FLIGHTS = 648.0
SUITE_NIGHTLY = 150.0

OBSERVED_AT = "2026-10-04T09:00:00+00:00"
STALE_AT = "2026-06-01T09:00:00+00:00"
NOW = "2026-10-04T12:00:00+00:00"


def _fare(pair, total: float, *, stale: bool = False,
          observed_at: str = OBSERVED_AT) -> LiveFareEvidence:
    """One whole-party, exact-date economy fare, as the loader would return it.

    ``stale`` is the loader's own age verdict, set here rather than derived:
    the dataclass trusts whoever built it, and ``promotable`` reads the flag.
    """
    return LiveFareEvidence(
        airport=AIRPORT,
        total_gbp=total,
        basis="whole_party_return_total",
        source_url="https://example.invalid/hunt",
        observed_at=observed_at,
        cabin_class="ECONOMY",
        stale=stale,
    )


def _offers(*pairs_and_totals: tuple[tuple, float], **fare_kwargs) -> dict:
    return {
        (AIRPORT, "ECONOMY", pair[0], pair[1], "LHR"): _fare(pair, total, **fare_kwargs)
        for pair, total in pairs_and_totals
    }


def _rate(pair, price_gbp: float, **overrides) -> dict:
    """One qualifying exact-date hotel rate for ``pair``, as the file states it."""
    base = {
        "property_name": RESORT,
        "destination_key": "antalya",
        "season": "winter",
        "vendor": "Example brand booking engine",
        "check_in": pair[0],
        "check_out": pair[1],
        "nights": 14,
        "party": {"adults": 5, "children": 0},
        "booking_shape": "single_unit",
        "board": "AI",
        "rate_name": "SAVER NON-REFUNDABLE",
        "prices_shown": [
            {"unit": "DUPLEX FAMILY SUITE", "public": price_gbp}
        ],
        "price_basis": "total_stay_rate",
        "currency": "GBP",
        "taxes_included": True,
        "source_url": "https://example.invalid/booking",
        "observed_at": "2026-10-03T15:02:10+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    base.update(overrides)
    return base


def _hotel_evidence(*rates: dict) -> dict:
    """``load_hotel_evidence``'s output for a synthetic file. Nothing persists."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"schema": "holiday_hotel_evidence/1", "rates": list(rates)}, handle)
    handle.close()
    config = load_holiday_config(BAND_CONFIG)
    loaded = load_hotel_evidence(config, path=handle.name, now=NOW)
    consume_hotel_skip_log()
    return loaded


def _deals(config_json: str = BAND_CONFIG, *, offers=None, hotel=None,
           max_budget_gbp: float = 10 ** 9):
    config = load_holiday_config(config_json)
    deals = collect_holiday_deals(
        config,
        max_budget_gbp=max_budget_gbp,
        live_flight_offers=offers or None,
        hotel_evidence=hotel or None,
    )
    consume_hotel_skip_log()
    return deals


def _card(deals, name: str = RESORT):
    for deal in deals:
        if deal.resort_name == name:
            return deal
    raise AssertionError(f"no card for {name}: {[d.resort_name for d in deals]}")


class TestTheWindowIsWhatTheTestsThinkItIs(unittest.TestCase):
    def test_three_pairs_are_priced_and_the_tenth_night_one_is_not(self):
        config = load_holiday_config(BAND_CONFIG)
        self.assertEqual(
            priceable_date_pairs(config),
            (SHORT_PAIR, LONG_PAIR, OTHER_SHORT_PAIR),
        )

    def test_the_headline_pair_is_the_long_one(self):
        # The headline leads ``pricing_order``, so it is what a tie resolves
        # to - which is what "behaviour exactly as before" means here.
        config = load_holiday_config(BAND_CONFIG)
        self.assertEqual(priced_date_pair(config), LONG_PAIR)
        self.assertEqual(pricing_order(config)[0], LONG_PAIR)


class TestAReadFareBeatsAModelledPair(unittest.TestCase):
    def test_a_live_fare_on_the_fourteen_night_pair_beats_the_cheaper_twelve(self):
        # GBP 5,000 for five is dearer than the modelled 2,448, and it is for
        # fourteen nights rather than twelve. The reader asked for a real price:
        # the real price wins.
        deal = _card(_deals(offers=_offers((LONG_PAIR, 5000.0))))
        self.assertEqual((deal.outbound_date, deal.return_date), LONG_PAIR)
        self.assertEqual(deal.nights, 14)
        self.assertEqual(deal.flight_price_total_gbp, 5000.0)
        self.assertEqual(deal.confidence, "verified-exact-date")

    def test_with_no_evidence_the_cheapest_pair_is_still_the_card(self):
        # The whole change is inert without evidence: the shortest stay is
        # the cheapest when every figure is modelled, exactly as before.
        deal = _card(_deals())
        self.assertEqual((deal.outbound_date, deal.return_date), SHORT_PAIR)
        self.assertEqual(deal.nights, 12)
        self.assertAlmostEqual(
            deal.total_package_price_gbp, BENCHMARK_FLIGHTS + 12 * SUITE_NIGHTLY,
            places=2,
        )
        self.assertEqual(deal.confidence, "market-supported")

    def test_the_cheaper_of_two_read_fares_wins(self):
        # Evidence equalises the field; it does not replace the price. Both
        # pairs have a whole-party exact-date fare, so the dearer one loses.
        deal = _card(
            _deals(offers=_offers((LONG_PAIR, 5000.0), (SHORT_PAIR, 3000.0)))
        )
        self.assertEqual((deal.outbound_date, deal.return_date), SHORT_PAIR)
        self.assertEqual(deal.flight_price_total_gbp, 3000.0)

    def test_an_aged_read_still_beats_a_modelled_pair(self):
        # `evidence_used` is the collector's "may this price a card" test and
        # an observation too old to be called LIVE is still an observation.
        # The card says how old; the ranking must not quietly prefer a
        # benchmark for the same holiday because the read has grey hair.
        deal = _card(
            _deals(
                offers=_offers((LONG_PAIR, 5000.0), stale=True, observed_at=STALE_AT)
            )
        )
        self.assertEqual((deal.outbound_date, deal.return_date), LONG_PAIR)
        self.assertEqual(deal.confidence, "stale-cache")

    def test_a_fare_for_a_pair_outside_the_band_still_prices_nothing(self):
        # Ten nights is not priced by this run, so a read for those dates
        # cannot pull the card off the pairs the band admits.
        offers = _offers((("2026-12-19", "2026-12-29"), 1.0))
        deal = _card(_deals(offers=offers))
        self.assertNotEqual(
            (deal.outbound_date, deal.return_date), ("2026-12-19", "2026-12-29")
        )
        self.assertEqual(deal.flight_price_total_gbp, BENCHMARK_FLIGHTS)


class TestHotelEvidenceCountsTheSameWay(unittest.TestCase):
    def test_a_rate_read_for_the_longer_stay_beats_a_cheaper_catalogue_stay(self):
        # GBP 2,600 for fourteen nights is dearer than the modelled 2,100 the
        # catalogue would charge, and it is what the hotel quoted.
        hotel = _hotel_evidence(_rate(LONG_PAIR, 2600.0, nights=14))
        deal = _card(_deals(hotel=hotel))
        self.assertEqual((deal.outbound_date, deal.return_date), LONG_PAIR)
        self.assertEqual(deal.hotel_rate_basis, "exact-date-rate")
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 2600.0)

    def test_both_halves_read_outrank_one_half_read(self):
        # A read fare on the short pair beats a modelled fare on the long one
        # (both class 1: read flights, catalogue stay). Give the long pair a
        # read RATE as well and it is class 2 - two figures somebody can go
        # and check - so it wins.
        hotel = _hotel_evidence(_rate(LONG_PAIR, 2600.0, nights=14))
        deal = _card(
            _deals(offers=_offers((SHORT_PAIR, 3000.0)), hotel=hotel)
        )
        self.assertEqual((deal.outbound_date, deal.return_date), LONG_PAIR)
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 2600.0)

    def test_a_rate_for_a_board_the_property_does_not_sell_is_not_evidence(self):
        # The catalogue says this property is Ultra All Inclusive. A
        # breakfast-only rate cannot be booked here, so it is not a read
        # stay and must not buy the card either.
        hotel = _hotel_evidence(_rate(LONG_PAIR, 2600.0, nights=14, board="BB"))
        deal = _card(_deals(hotel=hotel))
        self.assertEqual((deal.outbound_date, deal.return_date), SHORT_PAIR)
        self.assertNotEqual(deal.hotel_rate_basis, "exact-date-rate")


class TestNothingElseMoves(unittest.TestCase):
    def test_an_evidenced_pair_over_the_ceiling_is_still_rejected(self):
        # Preferring a real price must not become a way to buy a holiday over
        # budget. With a ceiling that only the modelled short stay clears, the
        # card is that stay - evidence does not buy its way past the ceiling.
        deal = _card(
            _deals(
                offers=_offers((LONG_PAIR, 5000.0)),
                max_budget_gbp=BENCHMARK_FLIGHTS + 12 * SUITE_NIGHTLY + 100.0,
            )
        )
        self.assertEqual((deal.outbound_date, deal.return_date), SHORT_PAIR)
        self.assertTrue(deal.is_under_budget)

    def test_a_resort_with_nothing_that_fits_makes_no_card(self):
        # The set of resorts that appear is decided by the budget test alone,
        # before any ranking: preferring evidence adds no resort and drops
        # none.
        self.assertEqual(
            _deals(offers=_offers((LONG_PAIR, 5000.0)), max_budget_gbp=1.0), ()
        )

    def test_a_tie_keeps_the_headline_pair(self):
        # Two priced pairs, twelve nights each, the same modelled cost: the
        # first one evaluated wins, and ``pricing_order`` leads with the
        # headline. This is the "ties keep today's headline-first order" rule,
        # and it is why the evidence change cannot quietly move every
        # benchmark-only card onto the earliest date in the window.
        #
        # With only two pairs the shortlist is both of them and its middle is
        # the second, so the headline here is 19 Dec -> 31 Dec.
        config = load_holiday_config(TIE_CONFIG)
        self.assertEqual(priceable_date_pairs(config), (SHORT_PAIR, OTHER_SHORT_PAIR))
        self.assertEqual(pricing_order(config)[0], OTHER_SHORT_PAIR)
        self.assertEqual(priced_date_pair(config), OTHER_SHORT_PAIR)
        deal = _card(_deals(TIE_CONFIG))
        self.assertEqual((deal.outbound_date, deal.return_date), OTHER_SHORT_PAIR)

    def test_the_shipped_december_config_with_no_evidence_is_unchanged(self):
        # December pins min = max = 8 and ships with no evidence file: the
        # whole run is modelled, so every card must still be the 20 Dec
        # headline pair the evidence contract states.
        config = load_holiday_config(DEC_CONFIG.read_text(encoding="utf-8"))
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertEqual(
                    (deal.outbound_date, deal.return_date, deal.nights),
                    ("2026-12-20", "2026-12-28", 8),
                )


class TestTheEvidenceClassItself(unittest.TestCase):
    """The rank key, stated on its own so it cannot drift silently."""

    def test_two_modelled_halves_is_class_zero(self):
        self.assertEqual(
            option_evidence_class({"evidence_used": False, "hotel_rate": None}), 0
        )

    def test_a_read_fare_alone_is_class_one(self):
        self.assertEqual(
            option_evidence_class({"evidence_used": True, "hotel_rate": None}), 1
        )

    def test_a_read_rate_alone_is_class_one(self):
        self.assertEqual(
            option_evidence_class({"evidence_used": False, "hotel_rate": object()}), 1
        )

    def test_two_read_halves_is_class_two(self):
        self.assertEqual(
            option_evidence_class({"evidence_used": True, "hotel_rate": object()}), 2
        )

    def test_a_missing_field_is_not_a_read(self):
        # The key reads what the option carries and treats an absent field as
        # the modelled answer, so a caller that forgets one cannot be handed a
        # free upgrade.
        self.assertEqual(option_evidence_class({}), 0)

    def test_higher_is_better_so_it_can_be_negated_for_a_sort_key(self):
        # The collector sorts on ``-class``: an ascending sort must put the
        # best-evidenced option first, which is only true while this
        # direction is the one being relied on. Note that a read fare and a
        # read rate TIE at class 1 - they are the same kind of claim, which is
        # exactly what makes "the cheaper of two read fares wins" true.
        modelled = {"evidence_used": False, "hotel_rate": None}
        read_rate = {"evidence_used": False, "hotel_rate": object()}
        read_fare = {"evidence_used": True, "hotel_rate": None}
        both_read = {"evidence_used": True, "hotel_rate": object()}
        self.assertEqual(option_evidence_class(read_fare), option_evidence_class(read_rate))
        self.assertLess(
            -option_evidence_class(both_read), -option_evidence_class(read_fare)
        )
        self.assertLess(
            -option_evidence_class(read_fare), -option_evidence_class(modelled)
        )