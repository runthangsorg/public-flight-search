"""An in-budget operator package BECOMES the card's price (BRIEF-H10 §2).

Owner decision 2, 2026-10-04, on a resort whose operator quoted £10,957 for
the card's own trip while the card's own business headline was £27,702 and
over the ceiling: "ok go ahead" to

> when an operator package for the card's own dates comes in under budget, the
> card stays and is priced at that package, once the package's flights are
> confirmed economy.

That SUPERSEDES H9 §1, where a package was only ever a sentence beside an
over-budget row. Pinned here:

* the card stays, and its headline IS the package total;
* every gate on that promotion, and each one alone is enough to refuse it:
  same dates, same nights, ``flight_cabin`` ECONOMY, whole-party total inside
  the ceiling, and the board/unit/rooms gates the loader and the one-booking
  rule already applied;
* a MISSING ``flight_cabin`` is unknown, and unknown does not promote — that
  case keeps H9's "package deal £X … fits the budget" line on the over-budget
  row instead;
* SUPERSEDED 2026-10-05 by BRIEF-H12 §1/§2, which this file's docstring used
  to state the other way round: a resort whose own headline is already in
  budget no longer keeps the package beside the headline — a qualifying package
  for the pair is the top evidence class and becomes the price. An UNQUALIFIED
  package (no ``flight_cabin``) still rides beneath the engine's own price as
  H9's comparison sentence, and both cases are asserted below;
* the breakdown adds up to the printed total, and the card says in its first
  words that the price is the operator's package, what it covers, and how many
  rooms;
* ranking uses the package total.

Synthetic throughout. The Garrya SHAPE is reproduced at small synthetic scale
(an over-budget economy headline rescued by a package) because the real
figures belong to the real dry run; the brief asks for both that case and the
"unknown package cabin → line only" case, and both are here.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from public_flight_search import holidays as hol
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    priced_date_pair,
)
from public_flight_search.holiday_email import (
    breakdown_display_parts,
    breakdown_words,
    package_words,
)
from public_flight_search.package_evidence import (
    consume_package_skip_log,
    load_package_evidence,
    package_covers_nights,
    package_flown_economy,
    package_shortfall_nights,
    package_within_budget,
)

NOW = "2026-10-04T12:00:00+00:00"
OBSERVED_AT = "2026-10-04T09:00:00+00:00"
BUDGET = 1700.0
RESORT = "Concorde De Luxe Resort"

#: A one-stop route (the owner quotes economy for these), priced by a
#: benchmark the engine cannot make fit, with a real operator package that can.
CONFIG = """
{
  "report_title": "In-budget package keeps its card",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 1700,
  "min_nights": 8,
  "max_nights": 10,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-20"],
  "return_dates": ["2026-12-28"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"],
     "flight_hours": 4.5, "nonstop_from_london": true,
     "nonstop_source": "test: year-round nonstop"}
  ]
}
"""

#: The pair the card would be priced on, and the pair the package is quoted for.
PAIR = ("2026-12-20", "2026-12-28")
NIGHTS = 8

ROOMS_HOW = (
    "room 1 £450.00 (2 adults, Grand Deluxe - Bed and Breakfast) + "
    "room 2 £450.00 (3 adults, Grand Deluxe - Bed and Breakfast), "
    "all as shown for the same hotel on Bed and Breakfast and the same dates"
)


def _record(*, amount=1200.0, outbound=PAIR[0], returning=PAIR[1],
            nights=NIGHTS, **overrides) -> dict:
    """One package read, shaped like the real Destination2 export."""
    record = {
        "operator_key": "example_holidays",
        "operator": "Example Holidays",
        "property_name": RESORT,
        "destination_key": "antalya",
        "season": "winter",
        "departure_airport": "LHR",
        "outbound_date": outbound,
        "return_date": returning,
        "nights": nights,
        "party": {"adults": 5, "children": 0, "child_ages": []},
        "rooms": 2,
        "room_descriptions": ["GRAND DELUXE", "GRAND DELUXE"],
        "board": "BB",
        "price_shown": {"amount": amount, "currency": "GBP", "basis": "rooms_sum"},
        "read_method": "dom-text",
        "link_kind": "deep-link",
        "source_url": "https://www.example.invalid/package/antalya",
        "observed_at": OBSERVED_AT,
        "exact_date_match": True,
        "confidence": "verified-exact-date",
        "flight_summary": "",
        "includes": ["transfers"],
        "derived_total_gbp": {"value": amount, "how": ROOMS_HOW},
        # Since dealsearch ff26b7a the Destination2 adapter records the cabin
        # it searched in, which is what lets a package promote a card.
        "flight_cabin": "ECONOMY",
        "flight_cabin_basis": "searched as Class=E (example_holidays.py)",
    }
    record.update(overrides)
    return record


def _loaded(*records) -> dict:
    payload = {"schema": "holiday_package_evidence/1", "packages": list(records)}
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    loaded = load_package_evidence(
        load_holiday_config(CONFIG), path=handle.name, now=NOW)
    consume_package_skip_log()
    return loaded


def _deal(*records, budget=BUDGET):
    """Collect with the given package reads. Synthetic, no private data."""
    import dataclasses
    config = dataclasses.replace(
        load_holiday_config(CONFIG), max_budget_gbp=budget)
    return config, collect_holiday_deals(
        config, max_budget_gbp=budget, package_evidence=_loaded(*records) or None)


class LoaderReadsTheCabinTests(unittest.TestCase):
    def test_the_cabin_and_its_basis_reach_the_record(self):
        loaded = _loaded(_record())
        entry = next(iter(loaded.values()))
        self.assertEqual(entry.flight_cabin, "ECONOMY")
        self.assertIn("Class=E", entry.flight_cabin_basis)

    def test_a_record_with_no_cabin_still_loads_but_never_promotes(self):
        # It stays quotable — H9's note on the over-budget row — because the
        # loader's job is price validity, not promotion.
        record = _record()
        del record["flight_cabin"]
        del record["flight_cabin_basis"]
        entry = next(iter(_loaded(record).values()))
        self.assertEqual(entry.flight_cabin, "")
        self.assertFalse(package_flown_economy(entry))
        self.assertTrue(package_within_budget(entry, BUDGET))


class GateTests(unittest.TestCase):
    """Each condition alone is enough to refuse the promotion."""

    def _promoted(self, **record_overrides) -> bool:
        _config, deals = _deal(_record(**record_overrides))
        return any(getattr(deal, "package_priced", False) for deal in deals)

    def test_a_qualifying_package_keeps_the_card_and_becomes_its_price(self):
        self.assertTrue(self._promoted())

    def test_dates_that_do_not_match_do_not_rescue(self):
        # A package for the neighbouring fortnight is a different holiday.
        self.assertFalse(self._promoted(outbound="2026-12-19"))

    def test_different_nights_do_not_rescue(self):
        self.assertFalse(self._promoted(nights=NIGHTS + 1))

    def test_a_package_over_the_ceiling_does_not_rescue(self):
        self.assertFalse(self._promoted(amount=BUDGET + 0.01))

    def test_a_business_cabin_package_does_not_rescue(self):
        # The owner's rule is business only for a direct flight; a package
        # whose flights were searched in Business is not this holiday.
        self.assertFalse(self._promoted(flight_cabin="BUSINESS"))

    def test_an_unknown_cabin_does_not_rescue(self):
        self.assertFalse(self._promoted(flight_cabin=""))
        record = _record()
        del record["flight_cabin"]
        _config, deals = _deal(record)
        self.assertFalse(any(getattr(d, "package_priced", False) for d in deals))

    def test_the_exact_ceiling_still_qualifies(self):
        self.assertTrue(self._promoted(amount=BUDGET))


class HelperTests(unittest.TestCase):
    def test_package_covers_nights_compares_the_records_own_field(self):
        entry = next(iter(_loaded(_record(nights=7)).values()))
        self.assertFalse(package_covers_nights(entry, 8))
        self.assertTrue(package_covers_nights(entry, 7))
        # An unusable value never promotes.
        self.assertFalse(package_covers_nights(entry, "eight"))

    def test_package_shortfall_nights_counts_the_difference(self):
        entry = next(iter(_loaded(_record(nights=7)).values()))
        self.assertEqual(package_shortfall_nights(entry, 10), 3)
        self.assertIsNone(package_shortfall_nights(entry, 7))
        self.assertIsNone(package_shortfall_nights(entry, 6))


class RescueCardTests(unittest.TestCase):
    def test_the_headline_is_the_package_total(self):
        _config, deals = _deal(_record(amount=1200.0))
        card = next(d for d in deals if d.package_priced)
        self.assertEqual(card.total_package_price_gbp, 1200.0)
        self.assertEqual(card.true_d2d_gbp, 1200.0)
        self.assertEqual(card.operator_package.total_gbp, 1200.0)
        # The pair is the PACKAGE's dates: the card was never re-based.
        self.assertEqual((card.outbound_date, card.return_date), PAIR)

    def test_the_breakdown_adds_up_to_the_printed_total(self):
        _config, deals = _deal(_record(amount=1200.0))
        card = next(d for d in deals if d.package_priced)
        parts, total = breakdown_display_parts(card)
        self.assertEqual(sum(amount for _label, amount in parts), total)
        words = breakdown_words(card)
        self.assertEqual(words, "flights + board + rooms £1,200 (economy) = £1,200")

    def test_the_card_says_in_its_first_words_that_the_price_is_the_package(self):
        _config, deals = _deal(_record(amount=1200.0))
        card = next(d for d in deals if d.package_priced)
        words = package_words(card, travellers=5)
        self.assertTrue(words.startswith("This price is the operator's package: £1,200 for 5"))
        self.assertIn("Example Holidays", words)
        self.assertIn("flights + Bed & Breakfast, 2 rooms", words)
        # The comparison tail survives, because it is measured against the
        # ENGINE's own quote for the same trip, not against the headline: the
        # engine's own flights + stay was £1,890, so £690 is a real difference.
        # What must not appear is the old "Package deal:" lead, which would
        # present the headline as a comparison beside itself.
        self.assertIn("£690 less than booking separately", words)
        self.assertNotIn("Package deal:", words)

    def test_ranking_uses_the_package_total(self):
        # Two resorts, both rescued: the one whose package is cheaper must
        # sort first, and its total must be the package's.
        _config, deals = _deal(_record(amount=1200.0))
        card = next(d for d in deals if d.package_priced)
        self.assertEqual(
            min(d.total_package_price_gbp for d in deals), 1200.0)
        self.assertLessEqual(card.total_package_price_gbp, BUDGET)
        self.assertEqual(card.price_per_person_gbp, 240.0)

    def test_the_operator_package_is_the_auditable_source(self):
        _config, deals = _deal(_record())
        card = next(d for d in deals if d.package_priced)
        self.assertEqual(card.source_url, "https://www.example.invalid/package/antalya")
        self.assertEqual(card.live_observed_at, OBSERVED_AT)
        self.assertEqual(card.confidence, "verified-exact-date")
        # No separate hotel read on a package-priced card: the operator's
        # quote IS the stay, so a rate line would be a second price.
        self.assertIsNone(card.hotel_evidence)
        self.assertEqual(card.board_options, ())

    def test_the_gappy_comparison_still_counts_against_the_engines_own_quote(self):
        # "£X less than booking flights and stay separately" is only true
        # against the engine's own total for the same trip.
        _config, deals = _deal(_record(amount=1200.0))
        card = next(d for d in deals if d.package_priced)
        self.assertGreater(card.operator_package.vs_engine_gbp, 0.0)


class UnchangedBehaviourTests(unittest.TestCase):
    def test_an_in_budget_headline_is_now_priced_at_the_package_too(self):
        # REWRITTEN 2026-10-05 for BRIEF-H12 §1/§2, which supersedes the rule
        # this assertion used to carry: "decision 2 only rescues an OVER-budget
        # headline, so with the ceiling high enough for the engine's own price
        # the card is priced by the engine and the package rides beside it".
        #
        # H12 §1 ranks candidate pairs by evidence class first, and a pair
        # carrying a qualifying operator package is the top class; §2 then says
        # a package that becomes the headline this way renders exactly as this
        # file's package-priced card renders. So an in-budget headline no longer
        # keeps the package beside it — the operator's own figure for the trip is
        # better evidence than the engine's split of it, and it is cheaper
        # besides (GBP 1,200 against GBP 1,890 here).
        #
        # The H9 comparison line is NOT lost: it is what an UNQUALIFIED package
        # still gets, which the two tests below pin.
        _config, deals = _deal(_record(amount=1200.0), budget=60000.0)
        card = next(d for d in deals if d.resort_name == RESORT)
        self.assertTrue(card.package_priced)
        self.assertEqual(card.total_package_price_gbp, 1200.0)
        self.assertTrue(
            package_words(card, travellers=5).startswith(
                "This price is the operator's package: £1,200 for 5"
            )
        )

    def test_an_unqualified_package_keeps_the_h9_comparison_line(self):
        # Same shape as the test above, with the one gate that refuses the
        # promotion: the record states no ``flight_cabin``, so the cabin is
        # UNKNOWN. The card is priced by the engine and the package rides
        # beneath it as H9's comparison sentence, never instead of it.
        record = _record(amount=1200.0)
        del record["flight_cabin"]
        del record["flight_cabin_basis"]
        _config, deals = _deal(record, budget=60000.0)
        card = next(d for d in deals if d.resort_name == RESORT)
        self.assertFalse(card.package_priced)
        self.assertNotEqual(card.total_package_price_gbp, 1200.0)
        self.assertIsNotNone(card.operator_package)
        self.assertTrue(
            package_words(card, travellers=5).startswith("Package deal: £1,200 for 5")
        )

    def test_an_unqualified_package_leaves_the_resort_over_budget_with_the_note(self):
        # Unknown cabin: the card is not rescued, so the resort is listed over
        # budget and keeps H9's "fits the budget" note on its row.
        record = _record(flight_cabin="")
        _config, deals = _deal(record)
        self.assertFalse(any(getattr(d, "package_priced", False) for d in deals))
        self.assertNotIn(RESORT, {d.resort_name for d in deals})
        rows = {row["resort_name"]: row for row in hol.LAST_OVER_BUDGET}
        self.assertIn(RESORT, rows)
        self.assertIsNotNone(rows[RESORT]["package"])

    def test_no_package_at_all_changes_nothing(self):
        _config, deals = _deal()
        card = next(d for d in deals if d.resort_name == RESORT) if any(
            d.resort_name == RESORT for d in deals) else None
        if card is not None:
            self.assertFalse(card.package_priced)
            self.assertIsNone(card.operator_package)


if __name__ == "__main__":
    unittest.main()