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

from public_flight_search import holidays
from public_flight_search.holidays import (
    collect_holiday_deals,
    destination_cabins,
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
from public_flight_search.live_verify import LiveFareEvidence, evidence_for

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
        #
        # NOTE this config is SHORT haul (4.5 hours), so it exercises the
        # economy branch, where the budget test has always run before the
        # ranking. The long-haul branch is a different path with a different
        # bug; see TestALongHaulCardChoosesAmongTheOptionsThatFit.
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

# ---------------------------------------------------------------------------
# The long-haul branch, which is a DIFFERENT path with a DIFFERENT bug
# ---------------------------------------------------------------------------

#: Zanzibar at 11.67 hours: a long-haul ROUTE, so the card goes down the
#: long-haul branch rather than the short-haul one the tests above exercise.
#: Two priced pairs:
#:
#:     19 Dec -> 31 Dec   12 nights   the HEADLINE pair
#:     17 Dec -> 31 Dec   14 nights
#:
#: Since 2026-10-04 this route is quoted ECONOMY, not Business: it has no London
#: nonstop (Ethiopian via Addis Ababa), and the owner's rule is business class
#: for a direct flight only. That does not weaken what these tests check.
#: "Long haul" is now a statement about the ROUTE, so the branch under repair
#: is still the one exercised — and it is the branch every July card now takes.
#: The modelled fare is the GBP 5,954 economy benchmark used as-is and the
#: suite is GBP 1,120.04 a night, so an economy option lands at 28,341.98 for
#: twelve nights and 30,582.06 for fourteen. A GBP 35,000 ceiling admits both;
#: GBP 20,000 admits neither.
LONG_HAUL_CONFIG = """
{
  "report_title": "Long haul budget first",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 35000,
  "min_nights": 12,
  "max_nights": 14,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-17", "2026-12-19"],
  "return_dates": ["2026-12-31"],
  "destinations": [
    {"key": "zanzibar", "label": "Zanzibar", "airports": ["ZNZ"],
     "flight_hours": 11.67, "nonstop_from_london": false,
     "nonstop_source": "synthetic fixture: no London nonstop, Ethiopian via ADD"}
  ]
}
"""

LONG_PAIR_14N = ("2026-12-17", "2026-12-31")
SHORT_PAIR_12N = ("2026-12-19", "2026-12-31")

#: The review's case (REVIEW-H5 P1): a whole-party fare read for the
#: fourteen-night pair that no budget could ever absorb. It was a Business fare
#: in 2026-10-03 and is an Economy fare now, because that is the cabin this
#: route is quoted in; the failure it guards is the same either way.
READ_FARE = 99_000.0


def _economy_fares(*pairs_and_totals: tuple[tuple, float]) -> dict:
    """Whole-party ECONOMY fares for one route and its pairs."""
    return {
        ("ZNZ", "ECONOMY", pair[0], pair[1], "LHR"): LiveFareEvidence(
            airport="ZNZ",
            total_gbp=total,
            basis="whole_party_return_total",
            source_url="https://example.invalid/hunt",
            observed_at=OBSERVED_AT,
            cabin_class="ECONOMY",
        )
        for pair, total in pairs_and_totals
    }


#: The one Zanzibar property in the catalogue this config reaches. Its modelled
#: fare is derived from the catalogue rather than pasted, so a rate change
#: cannot make these tests lie.
LONG_HAUL_AIRPORT = "ZNZ"
LONG_HAUL_RESORT = "Nungwi Dreams by Mantis"


def _modelled_fare() -> float:
    """The card's flight figure with no read fare: the economy benchmark."""
    resort = next(
        r for rs in holidays.resort_catalog().values() for r in rs
        if r["name"] == LONG_HAUL_RESORT
    )
    return round(resort["flight_benchmark_5pax_gbp"], 2)


#: The ceiling this file reasons about. ``_deals`` defaults to a billion so the
#: short-haul fixtures are never budget-limited; here the ceiling is the point,
#: so it is the config's own unless a test names another.
LONG_HAUL_BUDGET = 35_000.0


def _long_haul_deals(*pairs_and_totals: tuple[tuple, float], **kwargs):
    kwargs.setdefault("max_budget_gbp", LONG_HAUL_BUDGET)
    return _deals(LONG_HAUL_CONFIG, offers=_economy_fares(*pairs_and_totals), **kwargs)


def _zcard(deals):
    """The long-haul card, or a failure that names what was actually built."""
    return _card(deals, LONG_HAUL_RESORT)


class TestALongHaulCardChoosesAmongTheOptionsThatFit(unittest.TestCase):
    """The card is built on an option that clears the budget, or on nothing.

    The long-haul path used to choose its pair with ``enforce_budget=False``
    and consult the budget afterwards, as "admit the resort when ANY option row
    fits, then show ``cheapest``". When the evidence-first pick was the pair
    that busted the ceiling but a cheaper row fitted, the resort was admitted
    AND the card advertised the far dearer option - a read GBP 99,000
    fare produced a GBP 114,697 card against a GBP 35,000 ceiling, because the
    economy row fitted. The card was not lying (``is_under_budget`` was False
    and the amber chip rendered); the SELECTION was wrong, and the reason it
    was admitted was invisible on the card.

    The short-haul tests above cannot catch this: that branch has always run
    the budget test before the ranking. These use a destination over eight
    flight hours so the branch under repair is the one exercised.
    """

    def test_the_window_really_is_long_haul(self):
        # If this config ever stopped deriving BUSINESS the tests below would
        # pass for the wrong reason, so the premise is asserted, not assumed.
        config = load_holiday_config(LONG_HAUL_CONFIG)
        # A long-haul ROUTE, quoted Economy because there is no London nonstop:
        # since 2026-10-04 the branch is chosen on hours and the cabin on
        # nonstopness, and these tests need the branch, not the cabin.
        self.assertGreater(config.destinations[0].flight_hours, 8.0)
        self.assertEqual(destination_cabins(config, config.destinations[0]), ("ECONOMY",))
        self.assertEqual(
            priceable_date_pairs(config), (LONG_PAIR_14N, SHORT_PAIR_12N)
        )

    def test_a_read_fare_the_budget_cannot_absorb_never_becomes_the_card(self):
        deal = _zcard(_long_haul_deals((LONG_PAIR_14N, READ_FARE)))
        self.assertEqual((deal.outbound_date, deal.return_date), SHORT_PAIR_12N)
        self.assertEqual(deal.nights, 12)
        self.assertTrue(deal.is_under_budget)
        self.assertLessEqual(deal.true_d2d_gbp, LONG_HAUL_BUDGET)

    def test_the_rejected_read_is_still_read_it_was_the_budget_that_refused_it(self):
        # The test above must pass because the budget excluded the pair, not
        # because the fare went missing: without this, a loader that silently
        # dropped the record would make the same assertion true for a
        # different and wrong reason.
        config = load_holiday_config(LONG_HAUL_CONFIG)
        loaded = _economy_fares((LONG_PAIR_14N, READ_FARE))
        self.assertIsNotNone(
            evidence_for(loaded, LONG_HAUL_AIRPORT, "ECONOMY", *LONG_PAIR_14N, "LHR")
        )
        deal = _zcard(_long_haul_deals((LONG_PAIR_14N, READ_FARE)))
        # The flight half of the card is modelled, not read: ``confidence``
        # names the weaker leg for the freshness tag and falls back to the
        # hotel's own basis on an ECONOMY card, so the flight's own basis is
        # what this asserts.
        self.assertEqual(deal.flight_price_basis, "benchmark_supplied")
        self.assertNotIn(deal.confidence, ("verified-exact-date", "stale-cache"))
        self.assertEqual(deal.cabin_class, "ECONOMY")
        self.assertEqual(deal.destination_airport, LONG_HAUL_AIRPORT)

    def test_the_card_is_no_longer_a_five_figure_price_under_a_ceiling(self):
        # The headline number the review objected to, asserted directly: the
        # card's door-to-door total is nowhere near the read fare.
        deal = _zcard(_long_haul_deals((LONG_PAIR_14N, READ_FARE)))
        self.assertLess(deal.true_d2d_gbp, READ_FARE / 2)
        # The modelled Business fare, derived from the catalogue rather than
        # pasted: this number is the complaint in REVIEW-H5 P1 made concrete.
        self.assertAlmostEqual(
            deal.flight_price_total_gbp, _modelled_fare(), places=2
        )

    def test_an_in_budget_read_is_still_preferred_over_a_cheaper_modelled_pair(self):
        # The fix filters candidates; it must not demote a read that FITS. A
        # GBP 19,000 read on the fourteen-night pair costs 34,696.06 door to
        # door, which clears the ceiling, and it beats the cheaper modelled
        # twelve-night option at 28,341.98 - so evidence still wins.
        deal = _zcard(_long_haul_deals((LONG_PAIR_14N, 19_000.0)))
        self.assertEqual((deal.outbound_date, deal.return_date), LONG_PAIR_14N)
        self.assertEqual(deal.nights, 14)
        self.assertEqual(deal.confidence, "verified-exact-date")
        self.assertTrue(deal.is_under_budget)
        self.assertGreater(deal.true_d2d_gbp, 28_341.98)

    def test_the_cheaper_of_two_fitting_reads_still_wins(self):
        # Evidence equalises the field, it does not replace the price: inside
        # the budget the ranking is unchanged.
        deal = _zcard(
            _long_haul_deals((LONG_PAIR_14N, 24_000.0), (SHORT_PAIR_12N, 21_000.0))
        )
        self.assertEqual((deal.outbound_date, deal.return_date), SHORT_PAIR_12N)
        self.assertEqual(deal.flight_price_total_gbp, 21_000.0)

    def test_when_no_headline_option_fits_todays_behaviour_still_stands(self):
        # The fallback, and it is deliberately the OLD behaviour. A
        # GBP 20,000 ceiling clears the read Economy fare on the TWELVE-night
        # pair but not the modelled fourteen-night option, so the card is built
        # on the pair whose option fits rather than on the pair the evidence
        # pointed at. Nothing is invented and nothing is hidden: the brief
        # sanctions this rather than dropping a destination the owner asked for.
        deal = _zcard(
            _long_haul_deals((LONG_PAIR_14N, READ_FARE),
                             max_budget_gbp=20_000.0)
        )
        self.assertEqual((deal.outbound_date, deal.return_date), SHORT_PAIR_12N)
        self.assertEqual(deal.cabin_class, "ECONOMY")
        self.assertTrue(deal.is_under_budget)
        self.assertLessEqual(deal.true_d2d_gbp, 20_000.0)
        self.assertTrue(
            any(row.get("within_budget") for row in deal.flight_options),
            "the resort is admitted on a row that fits, which is the point",
        )

    def test_when_not_even_an_economy_row_fits_there_is_no_card_at_all(self):
        # Below every option the resort is not priced into the report as a
        # deal; it is stated in the over-budget list instead of vanishing.
        deals = _long_haul_deals((LONG_PAIR_14N, READ_FARE),
                                 max_budget_gbp=10_000.0)
        self.assertEqual(deals, ())
        self.assertEqual(
            [row["resort_name"] for row in holidays.LAST_OVER_BUDGET],
            [LONG_HAUL_RESORT],
        )
        self.assertGreater(
            float(holidays.LAST_OVER_BUDGET[0]["true_d2d"]), 10_000.0
        )

    def test_the_card_keeps_its_option_rows(self):
        # The repair is about WHICH option leads, not about stripping the
        # comparison: the card still carries its option rows, and on this
        # one-stop route the Economy row leads because that is the cabin the
        # owner is quoted (2026-10-04). There is no Business row, and a Business
        # row here would be the exact bug the rule fixes.
        deal = _zcard(_long_haul_deals((LONG_PAIR_14N, READ_FARE)))
        self.assertEqual(deal.cabin_class, "ECONOMY")
        kinds = [str(row.get("kind")) for row in deal.flight_options]
        self.assertNotIn("business", kinds)
        self.assertEqual(kinds[0], "economy")
        self.assertIn("premium_economy", kinds)
        # The headline IS the Economy option, priced as one. Before 2026-10-04
        # the Economy row was re-derived without the budget test, so on an
        # economy card it could be a DIFFERENT option from the card and read
        # "over budget" on a card the report calls affordable.
        self.assertEqual(deal.total_package_price_gbp, deal.flight_options[0]["total_pkg"])
        self.assertEqual(
            (deal.flight_options[0]["outbound"], deal.flight_options[0]["return"]),
            (deal.outbound_date, deal.return_date),
        )
