"""A card's dates follow the evidence, and an operator's package is evidence.

WHY this file exists
--------------------
BRIEF-H12 (2026-10-05), from what REPLY-H10 found in the dry runs: almost no
read evidence reached a card, because every card took the dates of its cheapest
viable flight pair while the hotel rates, operator packages and stopover fares
had all been read for OTHER pairs. The brief's own worked case is quoted above
in two figures (GBP 5,618 against GBP 5,364) purely to say what was ignored —
both are already written down in the brief and in REPLY-H10. No fixture here
uses either of them, or any other figure from an evidence export.

H5 (2026-10-04) already ranks candidates by evidence class first and price
second, and its class counts two read halves: a read fare, a read hotel rate.
What was missing is the one piece of evidence that beats both — an operator's
own package for the very trip being offered, which is a single figure somebody
published for flights + board + rooms, in one booking, on those dates.

The rule this file pins:

* a pair carrying a qualifying operator package outranks a pair priced from
  catalogue nightly + benchmark, and within one evidence class the lower total
  still wins;
* a package that becomes the card's price this way renders EXACTLY as BRIEF-H10
  §2's package-priced card renders — operator, what it includes, rooms, the
  operator link, and a breakdown that adds up to the headline;
* a package that does NOT qualify under H10 §2's gates (economy ``flight_cabin``
  read from the record, the same dates and the same nights, party and rooms fit,
  the whole-party total inside the ceiling) changes nothing: the card stays on
  the pair its own evidence chose, and the package rides beside the headline as
  the comparison line it always was;
* an exact-date hotel-rate read still outranks a catalogue estimate on another
  pair — the half of the rule H5 already had, pinned here beside the package
  half so the two cannot drift apart;
* the ceiling is never moved: a package over it promotes nothing, and a card
  priced by a package is inside it.

Every FIXTURE in this file is synthetic and derived: an invented Lanzarote
window and an invented Zanzibar one, invented package reads for an invented
operator, invented rates, and catalogue figures read out of
``resort_catalog`` rather than pasted so a rate change cannot make the tests
describe a different holiday. No fixture figure came from an evidence export, a
private read or a real holiday — the two real figures in this docstring are the
brief's, quoted to name the case and used by nothing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from public_flight_search import holidays as hol
from public_flight_search.holidays import (
    candidate_price,
    collect_holiday_deals,
    destination_cabins,
    load_holiday_config,
    package_evidence_class,
    priceable_date_pairs,
    priced_date_pair,
    render_holiday_report,
)
from public_flight_search.holiday_email import (
    breakdown_display_parts,
    breakdown_words,
    package_words,
)
from public_flight_search.hotel_evidence import (
    consume_hotel_skip_log,
    load_hotel_evidence,
)
from public_flight_search.package_evidence import (
    consume_package_skip_log,
    load_package_evidence,
)

ROOT = Path(__file__).parents[1]

#: The one Lanzarote property the catalogue prices this window for. Its figures
#: are DERIVED from the catalogue below rather than pasted, so a rate change in
#: the catalogue cannot make these tests quietly describe a different holiday.
RESORT = "Princesa Yaiza Suite Hotel Resort"
AIRPORT = "ACE"

#: A twelve-to-fourteen night band over four configured pairs:
#:
#:     17 Dec -> 29 Dec   12 nights   the CHEAPEST when everything is modelled
#:     17 Dec -> 31 Dec   14 nights   the HEADLINE pair (shortlist middle)
#:     19 Dec -> 31 Dec   12 nights
#:     19 Dec -> 29 Dec   10 nights   OUT of band, on purpose
#:
#: Lanzarote is a London nonstop of about four hours, so the card is priced
#: ECONOMY under the 2026-10-04 cabin rule and goes down the short-haul branch.
CONFIG = """
{
  "report_title": "Evidence-first dates",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 6000,
  "min_nights": 12,
  "max_nights": 14,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-17", "2026-12-19"],
  "return_dates": ["2026-12-29", "2026-12-31"],
  "destinations": [
    {"key": "lanzarote", "label": "Lanzarote", "airports": ["ACE"],
     "flight_hours": 4.0, "nonstop_from_london": true,
     "nonstop_source": "synthetic fixture: year-round nonstop"}
  ]
}
"""

SHORT_PAIR = ("2026-12-17", "2026-12-29")   # 12 nights, the modelled cheapest
LONG_PAIR = ("2026-12-17", "2026-12-31")    # 14 nights, the headline pair
OTHER_SHORT_PAIR = ("2026-12-19", "2026-12-31")
OUT_OF_BAND_PAIR = ("2026-12-19", "2026-12-29")   # 10 nights

#: The ceiling the config states. Named rather than pasted into assertions so a
#: test that says "inside the ceiling" says it about the same number the run
#: used.
BUDGET = 6000.0

NOW = "2026-10-05T09:00:00+00:00"
OBSERVED_AT = "2026-10-05T07:30:00+00:00"

OPERATOR = "Example Package Holidays"
OPERATOR_URL = "https://www.example.invalid/package/lanzarote"


def _catalogue_row(name: str = RESORT) -> dict:
    return next(
        resort
        for resorts in hol.resort_catalog().values()
        for resort in resorts
        if resort["name"] == name
    )


def _benchmark_flights() -> float:
    """The whole-party economy benchmark this property is priced from."""
    return round(float(_catalogue_row()["flight_benchmark_5pax_gbp"]), 2)


def _nightly() -> float:
    """The suite's nightly rate, as the catalogue states it."""
    return round(float(hol._suite_for(_catalogue_row())["suite_nightly_gbp"]), 2)


def _modelled_total(nights: int) -> float:
    """What the engine's own flights + stay cost for ``nights`` nights."""
    return round(_benchmark_flights() + _nightly() * nights, 2)


#: UK ground for LHR plus this property's transfer: the two halves of true D2D
#: that are NOT the package. Derived, so "the package total is the whole
#: headline" is an assertion about the card rather than about this file.
UK_GROUND = 16.50


def _record(*, amount: float = 4000.0, outbound: str = LONG_PAIR[0],
            returning: str = LONG_PAIR[1], nights: int = 14,
            **overrides) -> dict:
    """One operator package read, shaped like the real Destination2 export.

    ``flight_cabin`` is what lets a package price a card at all (BRIEF-H10 §2):
    the Destination2 adapter records the cabin it searched in, and a record
    without the field is UNKNOWN, which never promotes.
    """
    record = {
        "operator_key": "example_package_holidays",
        "operator": OPERATOR,
        "property_name": RESORT,
        "destination_key": "lanzarote",
        "season": "winter",
        "departure_airport": "LHR",
        "outbound_date": outbound,
        "return_date": returning,
        "nights": nights,
        "party": {"adults": 5, "children": 0, "child_ages": []},
        "rooms": 2,
        "room_descriptions": ["SUITE", "SUITE"],
        "board": "BB",
        "price_shown": {"amount": amount, "currency": "GBP", "basis": "rooms_sum"},
        "read_method": "dom-text",
        "link_kind": "deep-link",
        "source_url": OPERATOR_URL,
        "observed_at": OBSERVED_AT,
        "exact_date_match": True,
        "confidence": "verified-exact-date",
        "flight_summary": "",
        "includes": ["flights", "transfers"],
        "derived_total_gbp": {
            "value": amount,
            "how": (
                "room 1 GBP {0:.2f} + room 2 GBP {0:.2f}, as shown for the "
                "same hotel on the same dates"
            ).format(amount / 2),
        },
        "flight_cabin": "ECONOMY",
        "flight_cabin_basis": "searched as Class=E (example_package_holidays.py)",
    }
    record.update(overrides)
    return record


def _packages(*records) -> dict:
    """``load_package_evidence``'s output for a synthetic file. Nothing persists."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"schema": "holiday_package_evidence/1", "packages": list(records)},
              handle)
    handle.close()
    loaded = load_package_evidence(
        load_holiday_config(CONFIG), path=handle.name, now=NOW
    )
    consume_package_skip_log()
    return loaded


def _rate(pair, price_gbp: float, **overrides) -> dict:
    """One qualifying exact-date hotel rate for ``pair``, as the file states it.

    The board is the one this property is catalogued as selling: a rate read in
    a board the hotel does not sell is a rate that cannot be booked, so it is
    refused before it can price anything (and these tests are not about that
    refusal).
    """
    nights = (
        datetime.strptime(pair[1], "%Y-%m-%d")
        - datetime.strptime(pair[0], "%Y-%m-%d")
    ).days
    base = {
        "property_name": RESORT,
        "destination_key": "lanzarote",
        "season": "winter",
        "vendor": "Example brand booking engine",
        "check_in": pair[0],
        "check_out": pair[1],
        "nights": nights,
        "party": {"adults": 5, "children": 0},
        "booking_shape": "two_rooms_one_booking",
        "board": "HB",
        "rate_name": "SAVER NON-REFUNDABLE",
        "prices_shown": [{"unit": "SUITE", "public": price_gbp}],
        "price_basis": "total_stay_rate",
        "currency": "GBP",
        "taxes_included": True,
        "source_url": "https://example.invalid/booking",
        "observed_at": "2026-10-04T15:02:10+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    base.update(overrides)
    return base


def _rates(*records) -> dict:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"schema": "holiday_hotel_evidence/1", "rates": list(records)}, handle)
    handle.close()
    loaded = load_hotel_evidence(
        load_holiday_config(CONFIG), path=handle.name, now=NOW
    )
    consume_hotel_skip_log()
    return loaded


def _deals(*, packages=None, rates=None, offers=None,
           max_budget_gbp: float = BUDGET):
    import dataclasses

    config = dataclasses.replace(
        load_holiday_config(CONFIG), max_budget_gbp=max_budget_gbp
    )
    deals = collect_holiday_deals(
        config,
        max_budget_gbp=max_budget_gbp,
        live_flight_offers=offers or None,
        hotel_evidence=rates or None,
        package_evidence=packages or None,
    )
    consume_package_skip_log()
    consume_hotel_skip_log()
    return config, deals


def _card(deals, name: str = RESORT):
    for deal in deals:
        if deal.resort_name == name:
            return deal
    raise AssertionError(
        f"no card for {name}: {[d.resort_name for d in deals]}"
    )


class _StubPackage:
    """The one field ``candidate_price`` reads, so a test can pin the fallback."""

    def __init__(self, total_gbp):
        self.total_gbp = total_gbp


class TestTheWindowIsWhatTheTestsThinkItIs(unittest.TestCase):
    """The premise, asserted rather than assumed."""

    def test_the_three_priced_pairs_and_the_one_out_of_band(self):
        config = load_holiday_config(CONFIG)
        self.assertEqual(
            priceable_date_pairs(config),
            (SHORT_PAIR, LONG_PAIR, OTHER_SHORT_PAIR),
        )
        self.assertNotIn(OUT_OF_BAND_PAIR, priceable_date_pairs(config))

    def test_the_headline_pair_is_the_fourteen_night_one(self):
        config = load_holiday_config(CONFIG)
        self.assertEqual(priced_date_pair(config), LONG_PAIR)

    def test_with_nothing_read_the_card_is_still_the_cheapest_modelled_pair(self):
        # The whole change is inert without evidence: this is the pair the
        # collector chose before H12, so every other assertion here is about a
        # DIFFERENCE from it rather than about the fixture.
        _config, deals = _deals()
        card = _card(deals)
        self.assertEqual((card.outbound_date, card.return_date), SHORT_PAIR)
        self.assertEqual(card.total_package_price_gbp, _modelled_total(12))
        self.assertFalse(card.package_priced)
        self.assertIsNone(card.operator_package)


class TestAPackagePairOutranksAModelledPair(unittest.TestCase):
    """BRIEF-H12 §1: evidence class first, then the total."""

    def test_a_cheaper_package_on_another_pair_moves_the_card_and_prices_it(self):
        # The card would be 17 Dec -> 29 Dec at the modelled 5,140 for twelve
        # nights. The operator quoted 4,000 for fourteen nights ON THE OTHER
        # PAIR: better evidence and a lower total, so it is the card.
        _config, deals = _deals(packages=_packages(_record(amount=4000.0)))
        card = _card(deals)
        self.assertEqual((card.outbound_date, card.return_date), LONG_PAIR)
        self.assertEqual(card.nights, 14)
        self.assertTrue(card.package_priced)
        self.assertEqual(card.total_package_price_gbp, 4000.0)
        self.assertEqual(card.true_d2d_gbp, 4000.0)
        self.assertLess(card.total_package_price_gbp, _modelled_total(12))

    def test_the_package_card_is_rendered_exactly_as_H10_section_2_renders_it(self):
        # Same rendering, so every part of it is asserted rather than assumed:
        # the operator and what it includes, the room count, the operator link,
        # and a breakdown whose parts sum to the printed total.
        _config, deals = _deals(packages=_packages(_record(amount=4000.0)))
        card = _card(deals)
        parts, total = breakdown_display_parts(card)
        self.assertEqual(sum(amount for _label, amount in parts), total)
        self.assertEqual(
            breakdown_words(card), "flights + board + rooms £4,000 (economy) = £4,000"
        )
        words = package_words(card, travellers=5)
        self.assertTrue(words.startswith("This price is the operator's package: £4,000 for 5"))
        self.assertIn(OPERATOR, words)
        self.assertIn("flights + Bed & Breakfast, 2 rooms", words)
        self.assertEqual(card.source_url, OPERATOR_URL)
        self.assertEqual(card.live_observed_at, OBSERVED_AT)
        self.assertEqual(card.confidence, "verified-exact-date")
        self.assertIsNone(card.hotel_evidence)
        self.assertEqual(card.board_options, ())
        self.assertEqual(card.hotel_rate_basis, "operator package")
        # The gap is measured against the ENGINE's own quote for this trip, so
        # "less than booking separately" is a true sentence.
        self.assertAlmostEqual(
            card.operator_package.vs_engine_gbp,
            round(_modelled_total(14) + UK_GROUND
                  + float(_catalogue_row().get("transfer_gbp", 30.0))
                  - 4000.0, 2),
            places=2,
        )

    def test_a_dearer_package_still_outranks_a_cheaper_modelled_pair(self):
        # Class first, then price — the same order the read-fare rule has had
        # since H5. GBP 5,600 for fourteen nights is dearer than the modelled
        # 5,140 for twelve, and it is the price an operator displayed for a
        # real booking, so it is the one the card is built on.
        self.assertGreater(5600.0, _modelled_total(12))
        _config, deals = _deals(packages=_packages(_record(amount=5600.0)))
        card = _card(deals)
        self.assertEqual((card.outbound_date, card.return_date), LONG_PAIR)
        self.assertEqual(card.total_package_price_gbp, 5600.0)
        self.assertTrue(card.package_priced)

    def test_within_one_class_the_lower_total_wins(self):
        # Two pairs, two qualifying packages, both the same class: the cheaper
        # one is the card, exactly as two read fares are ranked by price.
        records = (
            _record(amount=5600.0, outbound=LONG_PAIR[0], returning=LONG_PAIR[1], nights=14),
            _record(amount=4000.0, outbound=SHORT_PAIR[0], returning=SHORT_PAIR[1], nights=12),
        )
        _config, deals = _deals(packages=_packages(*records))
        card = _card(deals)
        self.assertEqual((card.outbound_date, card.return_date), SHORT_PAIR)
        self.assertEqual(card.total_package_price_gbp, 4000.0)
        self.assertEqual(card.nights, 12)

    def test_a_package_wins_over_a_read_fare_on_the_other_pair(self):
        # The strongest claim the rule makes: a figure an operator displayed
        # beats a figure this engine read, because the operator's figure covers
        # flights + board + rooms in the one booking the owner would make.
        from public_flight_search.live_verify import LiveFareEvidence

        offers = {
            (AIRPORT, "ECONOMY", SHORT_PAIR[0], SHORT_PAIR[1], "LHR"): LiveFareEvidence(
                airport=AIRPORT,
                total_gbp=2000.0,
                basis="whole_party_return_total",
                source_url="https://example.invalid/hunt",
                observed_at=OBSERVED_AT,
                cabin_class="ECONOMY",
            )
        }
        _config, deals = _deals(
            packages=_packages(_record(amount=5600.0)), offers=offers
        )
        card = _card(deals)
        self.assertEqual((card.outbound_date, card.return_date), LONG_PAIR)
        self.assertEqual(card.total_package_price_gbp, 5600.0)


class TestAnUnqualifiedPackageChangesNothing(unittest.TestCase):
    """H10 §2's gates, unchanged: an unknown cabin is unknown, and a package
    that fails a gate is information, not a price."""

    def test_a_qualifying_package_on_the_chosen_pair_still_becomes_the_price(self):
        # H10 §2 rescued a card whose own flights + stay could not fit. H12 §1
        # widens the same rule to a pair that DOES fit: once the pair is chosen
        # on evidence, the operator's figure for it is better evidence than the
        # engine's own split of it, so it is the price either way. The pair
        # does not move here (the engine would have chosen it anyway), which is
        # exactly why this case needed its own assertion.
        record = _record(
            amount=4000.0,
            outbound=SHORT_PAIR[0],
            returning=SHORT_PAIR[1],
            nights=12,
        )
        _config, deals = _deals(packages=_packages(record))
        card = _card(deals)
        self.assertEqual((card.outbound_date, card.return_date), SHORT_PAIR)
        self.assertTrue(card.package_priced)
        self.assertEqual(card.total_package_price_gbp, 4000.0)

    def test_a_package_without_flight_cabin_leaves_the_card_on_its_fare_pair(self):
        # The package IS for the card's own dates here, so the only thing that
        # can stop it being the price is the gate: a record with no
        # ``flight_cabin`` is UNKNOWN, and unknown does not promote (H10 §2).
        # The card keeps the engine's own price and keeps the package as the
        # comparison line beneath it.
        record = _record(
            amount=4000.0,
            outbound=SHORT_PAIR[0],
            returning=SHORT_PAIR[1],
            nights=12,
        )
        del record["flight_cabin"]
        del record["flight_cabin_basis"]
        _config, deals = _deals(packages=_packages(record))
        card = _card(deals)
        self.assertFalse(card.package_priced)
        self.assertEqual((card.outbound_date, card.return_date), SHORT_PAIR)
        self.assertEqual(card.total_package_price_gbp, _modelled_total(12))
        # ...and it keeps riding the card as the comparison line it always was.
        self.assertIsNotNone(card.operator_package)
        self.assertEqual(card.operator_package.total_gbp, 4000.0)
        self.assertTrue(
            package_words(card, travellers=5).startswith("Package deal: £4,000 for 5")
        )

    def test_a_business_cabin_package_does_not_move_the_card(self):
        _config, deals = _deals(packages=_packages(_record(flight_cabin="BUSINESS")))
        card = _card(deals)
        self.assertFalse(card.package_priced)
        self.assertEqual((card.outbound_date, card.return_date), SHORT_PAIR)

    def test_a_package_over_the_ceiling_does_not_move_the_card(self):
        # The ceiling is never moved. A package above it cannot price anything,
        # so the card stays on the pair its own evidence chose and the ceiling
        # is exactly what it was.
        _config, deals = _deals(packages=_packages(_record(amount=BUDGET + 0.01)))
        card = _card(deals)
        self.assertFalse(card.package_priced)
        self.assertEqual((card.outbound_date, card.return_date), SHORT_PAIR)
        self.assertLessEqual(card.true_d2d_gbp, BUDGET)

    def test_a_package_for_another_number_of_nights_does_not_move_the_card(self):
        # "Same dates and nights", H10 §2: a package quoted for a different
        # length of stay is a different holiday.
        _config, deals = _deals(packages=_packages(_record(nights=13)))
        card = _card(deals)
        self.assertFalse(card.package_priced)
        self.assertEqual((card.outbound_date, card.return_date), SHORT_PAIR)

    def test_a_package_for_a_pair_outside_the_band_does_not_move_the_card(self):
        # Ten nights is not priced by this run, so a read for those dates can
        # neither promote a card nor draw it off the pairs the band admits.
        _config, deals = _deals(
            packages=_packages(
                _record(
                    amount=4000.0,
                    outbound=OUT_OF_BAND_PAIR[0],
                    returning=OUT_OF_BAND_PAIR[1],
                    nights=10,
                )
            )
        )
        card = _card(deals)
        self.assertFalse(card.package_priced)
        self.assertNotEqual(
            (card.outbound_date, card.return_date), OUT_OF_BAND_PAIR
        )

    def test_a_package_never_adds_a_resort_the_budget_test_refuses(self):
        # The set of carded resorts is still decided by the budget, not by the
        # evidence: with a ceiling below every figure the resort makes no card,
        # package included.
        _config, deals = _deals(
            packages=_packages(_record(amount=4000.0)), max_budget_gbp=1.0
        )
        self.assertEqual(deals, ())

    def test_a_package_card_is_never_reported_over_budget(self):
        _config, deals = _deals(packages=_packages(_record(amount=4000.0)))
        card = _card(deals)
        self.assertTrue(card.is_under_budget)
        self.assertLessEqual(card.total_package_price_gbp, BUDGET)


class TestTheHotelRateHalfOfTheRule(unittest.TestCase):
    """The other half of §1, which H5 had and H12 must not break."""

    def test_a_rate_read_for_the_longer_stay_beats_a_catalogue_estimate(self):
        rates = _rates(_rate(LONG_PAIR, 4600.0))
        _config, deals = _deals(rates=rates)
        card = _card(deals)
        self.assertEqual((card.outbound_date, card.return_date), LONG_PAIR)
        self.assertEqual(card.hotel_rate_basis, "exact-date-rate")
        self.assertAlmostEqual(card.hotel_price_total_gbp, 4600.0)

    def test_a_rate_read_does_not_out_rank_a_package_on_another_pair(self):
        # A read rate is class 1 and a package is the top class, so the package
        # takes the pair even though the rate is much cheaper. That is the rule
        # doing what it says; a rate may still win on a pair of its OWN (no
        # package read for it), which the test above is.
        rates = _rates(_rate(SHORT_PAIR, 3000.0))
        _config, deals = _deals(
            packages=_packages(_record(amount=5600.0)), rates=rates
        )
        card = _card(deals)
        self.assertEqual((card.outbound_date, card.return_date), LONG_PAIR)
        self.assertEqual(card.total_package_price_gbp, 5600.0)


class TestThePairEvidenceClassItself(unittest.TestCase):
    """The ranking key, stated on its own so it cannot drift silently."""

    def test_a_package_pair_is_the_top_class(self):
        self.assertGreater(package_evidence_class({"package": object()}), 2)

    def test_a_pair_with_no_package_keeps_the_two_read_figure_ranks(self):
        self.assertEqual(package_evidence_class({}), 0)
        self.assertEqual(
            package_evidence_class({"evidence_used": True, "hotel_rate": None}), 1
        )
        self.assertEqual(
            package_evidence_class({"evidence_used": True, "hotel_rate": object()}), 2
        )

    def test_a_package_key_of_none_is_not_a_class_of_its_own(self):
        # The key reads the option it is handed, and an absent field is the
        # modelled answer: a caller that sets ``package`` to None gets the
        # read-half ranks it had before, never a free upgrade.
        self.assertEqual(package_evidence_class({"package": None}), 0)
        self.assertEqual(package_evidence_class({}), 0)


class TestThePriceTheClassIsComparedOn(unittest.TestCase):
    """``candidate_price``: the figure the reader is shown, not another one."""

    def test_an_option_with_a_package_is_worth_the_package_total(self):
        self.assertEqual(
            candidate_price({"total_pkg": 999.0, "package": _StubPackage(4000.0)}),
            4000.0,
        )

    def test_an_option_without_a_package_is_worth_the_engines_own_total(self):
        self.assertEqual(candidate_price({"total_pkg": 999.0}), 999.0)

    def test_a_package_with_no_readable_price_falls_back_to_the_engines_total(self):
        # The loader guarantees a float total, so this cannot happen through the
        # collector — but the ranking key must not raise if a caller hands it
        # something else, and it must fall back to a figure the card can print
        # rather than to a package total it cannot read.
        self.assertEqual(
            candidate_price({"total_pkg": 999.0, "package": _StubPackage(None)}),
            999.0,
        )


# ---------------------------------------------------------------------------
# The long-haul branch, where the card's own rows exist to contradict it
# ---------------------------------------------------------------------------

#: Zanzibar at 11h40: a long-haul ROUTE, quoted ECONOMY since 2026-10-04 (no
#: London nonstop), so the card goes down the branch that builds the comparison
#: rows. The Lanzarote fixture above is short haul and has no rows at all, which
#: is why the contradiction this file guards cannot be shown there.
LONG_HAUL_CONFIG = """
{
  "report_title": "Evidence-first dates, long haul",
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
     "nonstop_source": "synthetic fixture: no London nonstop"}
  ]
}
"""

LH_SHORT_PAIR = ("2026-12-19", "2026-12-31")   # 12 nights
LH_LONG_PAIR = ("2026-12-17", "2026-12-31")    # 14 nights
LH_RESORT = "Nungwi Dreams by Mantis"


def _lh_record(*, amount: float = 9000.0, **overrides) -> dict:
    """One operator package for the long-haul fixture's property."""
    record = _record(
        amount=amount,
        outbound=LH_LONG_PAIR[0],
        returning=LH_LONG_PAIR[1],
        nights=14,
        property_name=LH_RESORT,
        destination_key="zanzibar",
        flight_summary="",
    )
    del record["room_descriptions"]
    record.update(overrides)
    return record


def _lh_deals(*records, max_budget_gbp: float = 35_000.0):
    config = load_holiday_config(LONG_HAUL_CONFIG)
    deals = collect_holiday_deals(
        config,
        max_budget_gbp=max_budget_gbp,
        package_evidence=_packages_for(config, *records) or None,
    )
    consume_package_skip_log()
    return config, deals


def _packages_for(config, *records) -> dict:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"schema": "holiday_package_evidence/1", "packages": list(records)},
              handle)
    handle.close()
    loaded = load_package_evidence(config, path=handle.name, now=NOW)
    consume_package_skip_log()
    return loaded


class TestThePairTheEngineCannotAfford(unittest.TestCase):
    """The one way a resort now enters the report for a reason other than the
    budget test — and what the card may then say about itself.

    H10 §2 rescued a card whose own flights + stay busted the ceiling, but only
    for the pair the engine happened to land on. §1 asks every priceable pair, so
    a package read for any pair this run prices can now admit one. The ceiling is
    untouched and the package still has to clear every gate; what must not happen
    is the card contradicting itself — a headline that fits, beside rows marked
    "over budget" and a line saying every option is over the budget.
    """

    #: A ceiling BELOW what this property costs on either pair on the engine's
    #: own figures — 5,954 + (1,120.04 x 12) + 16.50 = 19,410.98 for twelve
    #: nights and 21,651.06 for fourteen — while a package for the fourteen-night
    #: pair is well inside it. Without that package the resort makes no card at
    #: all; with it, the card exists at the package price.
    TIGHT_CEILING = 19_000.0
    PACKAGE_TOTAL = 9_000.0

    def test_the_window_really_is_long_haul(self):
        config = load_holiday_config(LONG_HAUL_CONFIG)
        self.assertGreater(config.destinations[0].flight_hours, 8.0)
        self.assertEqual(destination_cabins(config, config.destinations[0]), ("ECONOMY",))

    def test_the_card_exists_because_its_package_fits(self):
        config, deals = _lh_deals(
            _lh_record(amount=self.PACKAGE_TOTAL), max_budget_gbp=self.TIGHT_CEILING
        )
        card = _card(deals, LH_RESORT)
        self.assertTrue(card.package_priced)
        self.assertEqual((card.outbound_date, card.return_date), LH_LONG_PAIR)
        self.assertEqual(card.total_package_price_gbp, self.PACKAGE_TOTAL)
        self.assertTrue(card.is_under_budget)
        self.assertLessEqual(card.true_d2d_gbp, self.TIGHT_CEILING)
        # It is not on the over-budget list any more: the package IS its price.
        self.assertNotIn(LH_RESORT, {row["resort_name"] for row in hol.LAST_OVER_BUDGET})
        self.assertTrue(deals, "the resort makes a card at all")

    def test_without_that_package_the_same_ceiling_makes_no_card(self):
        # The control, and the point of the whole thing: the ceiling is not
        # moved. Only a qualifying package under it admits the pair.
        config, deals = _lh_deals(max_budget_gbp=self.TIGHT_CEILING)
        self.assertEqual(deals, ())
        self.assertIn(LH_RESORT, {row["resort_name"] for row in hol.LAST_OVER_BUDGET})

    def test_the_detailed_card_never_contradicts_its_own_package_headline(self):
        config, deals = _lh_deals(
            _lh_record(amount=self.PACKAGE_TOTAL), max_budget_gbp=self.TIGHT_CEILING
        )
        card = _card(deals, LH_RESORT)
        # The rows beside it are the engine's own split of the same trip and the
        # package line measures the gap against them, so their totals are still
        # printed — but they must not carry a budget verdict about a card whose
        # price is the package and fits.
        self.assertGreater(card.operator_package.vs_engine_gbp, 0.0)
        self.assertTrue(
            any(not row.get("within_budget") for row in card.flight_options),
            "the engine's own row really is over the ceiling, which is why the"
            " card can only exist through its package",
        )
        html = render_holiday_report(
            config, generated_at=NOW, deals=deals, history_chips=(),
        )
        self.assertNotIn("over budget", html)
        self.assertNotIn("every option is over", html)
        self.assertIn("LESS than booking flights and hotel separately", html)

    def test_an_engine_priced_card_keeps_its_budget_verdicts(self):
        # The guard is on the package-priced card only. With no package the rows
        # ARE the card, so their marks stand — asserted here against the same
        # renderer so the guard cannot be "fixed" by deleting the marks.
        config, deals = _lh_deals()
        card = _card(deals, LH_RESORT)
        self.assertFalse(card.package_priced)
        self.assertTrue(any(row.get("within_budget") for row in card.flight_options))
        html = render_holiday_report(
            config, generated_at=NOW, deals=deals, history_chips=(),
        )
        self.assertIn("within budget", html)


class TestTheShippedReportIsUntouchedWithoutEvidence(unittest.TestCase):
    def test_the_committed_december_config_still_prices_every_card_on_its_headline(self):
        config_path = ROOT / "examples" / "dec_holiday_config.json"
        config = load_holiday_config(config_path.read_text(encoding="utf-8"))
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
        self.assertTrue(deals)
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertEqual(
                    (deal.outbound_date, deal.return_date, deal.nights),
                    ("2026-12-20", "2026-12-28", 8),
                )
                self.assertFalse(deal.package_priced)


if __name__ == "__main__":
    unittest.main()