"""An in-budget operator package on an over-budget row (BRIEF-H9 §1, 2026-10-04).

The over-budget list is the only place in the report that says "priced, no
option fits". H9 asks that when an operator's OWN package for that property
fits the ceiling, the row says so — and only then. Pinned here:

* the sentence is the owner's own wording: price, party, operator, board,
  rooms, the package's dates when they are not the row's dates, and
  "fits the budget";
* it is a NOTE on the row. The row's headline, the ordering of the list and
  the card list do not move — a package never prices, ranks or admits
  anything (the same rule the cards follow);
* a package that is itself over the ceiling says nothing: it would assert the
  opposite of the row above it;
* only a link that carries the quote is a link (the H8 rule), so an operator
  without a quotable URL is named and told the dates are theirs to enter.

The helpers are tested on a hand-built row; the collector is tested with a
synthetic Antalya window and a temp evidence file, the way
``tests/test_package_price_on_cards.py`` does it. No figure here is read from
``data/`` — the real reads belong to the season's own dry run (§4).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    _over_budget_html,
    over_package_words,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import (
    OperatorPackage,
    collect_holiday_deals,
    load_holiday_config,
    render_over_budget,
)
from public_flight_search.holiday_email import _package_is_comparable as hol_package_is_comparable
from public_flight_search.package_evidence import (
    cheapest_package_for_property,
    consume_package_skip_log,
    load_package_evidence,
)

NOW = "2026-10-04T12:00:00+00:00"
OBSERVED_AT = "2026-10-03T09:00:00+00:00"
BUDGET = 1500.0
RESORT = "Concorde De Luxe Resort"

#: An Antalya window with two priceable pairs, so a package read can be for a
#: pair the row does not own — the case the note's date tail exists for.
CONFIG = """
{
  "report_title": "In-budget package on an over-budget row",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 1500,
  "min_nights": 6,
  "max_nights": 10,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-19", "2026-12-20"],
  "return_dates": ["2026-12-28"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"], "flight_hours": 4.5}
  ]
}
"""

#: The row's own pair; the package below is quoted for the OTHER pair.
ROW_DATES = ("2026-12-20", "2026-12-28")
PACKAGE_DATES = ("2026-12-19", "2026-12-28")

#: The exporter's own words for a two-room sum, in the shape the real export
#: uses — the ``rooms_sum`` basis that made the feature possible on cards.
ROOMS_HOW = (
    "room 1 £450.00 (2 adults, Grand Deluxe - Bed and Breakfast) + "
    "room 2 £450.00 (3 adults, Grand Deluxe - Bed and Breakfast), "
    "all as shown for the same hotel on Bed and Breakfast and the same dates"
)


def _record(*, amount=900.0, outbound=PACKAGE_DATES[0],
            returning=PACKAGE_DATES[1], **overrides) -> dict:
    """One qualifying package read, shaped like the real export."""
    record = {
        "operator_key": "example_holidays",
        "operator": "Example Holidays",
        "property_name": RESORT,
        "destination_key": "antalya",
        "season": "winter",
        "departure_airport": "LHR",
        "outbound_date": outbound,
        "return_date": returning,
        "nights": 9 if outbound == PACKAGE_DATES[0] else 8,
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
    }
    record.update(overrides)
    return record


def _loaded(*records) -> dict:
    payload = {"schema": "holiday_package_evidence/1", "packages": list(records)}
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    return load_package_evidence(
        load_holiday_config(CONFIG), path=handle.name, now=NOW)


def _package(**overrides) -> OperatorPackage:
    base = dict(
        operator="Example Holidays",
        operator_key="example_holidays",
        total_gbp=900.0,
        board="BB",
        rooms=2,
        link_kind="deep-link",
        source_url="https://www.example.invalid/package/antalya",
        observed_at=OBSERVED_AT,
        provenance="package read 3 Oct 2026 from Example Holidays, BB, 2 rooms",
        how=ROOMS_HOW,
        vs_engine_gbp=5141.5,
        outbound_date=PACKAGE_DATES[0],
        return_date=PACKAGE_DATES[1],
    )
    base.update(overrides)
    return OperatorPackage(**base)


def _row(**overrides) -> dict:
    """An over-budget row: £6,041.50 door to door against a £1,500 ceiling."""
    row = {
        "resort_name": RESORT,
        "destination_label": "Antalya, Türkiye",
        "destination_key": "antalya",
        "airport": "AYT",
        "cabin": "ECONOMY",
        "outbound": ROW_DATES[0],
        "return": ROW_DATES[1],
        "nights": 8,
        "origin": "LHR",
        "flight_cost": 2400.0,
        "hotel_cost": 3600.0,
        "total_pkg": 6000.0,
        "true_d2d": 6041.5,
        "flight_confidence": "benchmark",
        "hotel_confidence": "market-supported",
        "unit": "Grand Deluxe room",
        "board": "BB",
        "board_options": (),
        "flight_options": (),
        "max_budget_gbp": BUDGET,
        "package": _package(),
    }
    row.update(overrides)
    return row


class SentenceTests(unittest.TestCase):
    def test_the_sentence_is_the_owners_sentence(self):
        words = over_package_words(_row(), travellers=5)
        self.assertEqual(
            words,
            "— package deal £900 for 5 (Example Holidays, flights + B&B, "
            "2 rooms) for 19–28 Dec, 9 nights against this row's 8 "
            "fits the budget",
        )

    def test_the_nights_are_named_when_they_differ_from_the_row(self):
        """A date range cannot say how long a trip is on its own.

        Two calendars can share an end date and still be a fortnight apart, and
        the H9 note printed only the dates — so a reader comparing it with the
        row's own price had to work the length out by hand (REVIEW-H9 P2-7).
        Here the row is 8 nights and the package 9, and the sentence says both.
        """
        words = over_package_words(_row(), travellers=5)
        self.assertIn("9 nights against this row's 8", words)

    def test_matching_nights_are_not_restated(self):
        row = _row(package=_package(outbound_date=ROW_DATES[0],
                                    return_date=ROW_DATES[1]))
        words = over_package_words(row, travellers=5)
        self.assertIn("2 rooms) fits the budget", words)
        self.assertNotIn(" for 19–28 Dec", words)
        self.assertNotIn("nights against this row", words)

    def test_a_package_two_nights_shorter_is_still_the_same_trip(self):
        # The tolerance is two nights, so a read a day or two out is a
        # schedule difference rather than a different holiday, and the verdict
        # stands. An ``OperatorPackage`` carries dates rather than a nights
        # field, so the length is taken from those: 20 Dec -> 3 Jan is 14.
        fourteen = _package(outbound_date="2026-12-20", return_date="2027-01-03")
        self.assertTrue(hol_package_is_comparable(fourteen, 16))
        self.assertTrue(hol_package_is_comparable(fourteen, 14))
        self.assertFalse(hol_package_is_comparable(fourteen, 17))

    def test_a_package_more_than_two_nights_shorter_says_nothing(self):
        """Three weeks of holiday must not be compared with a fortnight's price.

        The note would otherwise say "fits the budget" beside a row priced for
        a different number of nights, and the reader would be reading about a
        trip they are not being offered (REVIEW-H9 P2-7).
        """
        self.assertFalse(hol_package_is_comparable(_package(), 14))
        self.assertTrue(hol_package_is_comparable(_package(), 10))
        # And the note itself is withheld rather than printed with a caveat.
        long_row = _row(nights=17, package=_package())
        row = dict(long_row)
        row["package"] = _package(outbound_date=ROW_DATES[0],
                                  return_date="2026-12-22")
        self.assertEqual(over_package_words(row, travellers=5), "")

    def test_the_dates_are_dropped_when_the_package_quoted_the_rows_own(self):
        row = _row(package=_package(outbound_date=ROW_DATES[0],
                                    return_date=ROW_DATES[1]))
        words = over_package_words(row, travellers=5)
        self.assertIn("2 rooms) fits the budget", words)
        self.assertNotIn(" for 19–28 Dec", words)

    def test_a_row_without_a_package_says_nothing(self):
        self.assertEqual(over_package_words(_row(package=None), travellers=5), "")

    def test_a_package_that_is_itself_over_the_ceiling_says_nothing(self):
        # £2,400 is itself over £1,500: printing it beside "fits the budget"
        # would assert the opposite of the row it is attached to.
        row = _row(package=_package(total_gbp=2400.0))
        self.assertEqual(over_package_words(row, travellers=5), "")

    def test_the_board_is_spelled_the_way_the_sentence_spells_it(self):
        for code, words in (("AI", "All Inclusive"), ("HB", "Half Board")):
            row = _row(package=_package(board=code))
            self.assertIn(f"flights + {words}", over_package_words(row, travellers=5))


class NoteRenderingTests(unittest.TestCase):
    def test_the_compact_line_carries_the_note_and_links_the_operator(self):
        with patch.object(hol, "LAST_OVER_BUDGET", (_row(),)):
            html = _over_budget_html(load_holiday_config(CONFIG))
        text = unescape(html)
        self.assertIn("£6,042 for 5", text)
        self.assertIn("£4,542 over", text)
        self.assertIn("package deal £900 for 5 (", html)
        self.assertIn(">Example Holidays ↗</a>", html)
        self.assertIn("flights + B&amp;B, 2 rooms", html)
        self.assertIn(" for 19–28 Dec, 9 nights against this row's 8 fits the budget", text)

    def test_the_text_twin_prints_the_same_words(self):
        config = load_holiday_config(CONFIG)
        with patch.object(hol, "LAST_OVER_BUDGET", (_row(),)):
            text = render_holiday_report_compact_text(config, generated_at=NOW)
        self.assertIn("Over the £1,500 budget", text)
        self.assertIn(
            "— package deal £900 for 5 (Example Holidays, flights + B&B, "
            "2 rooms) for 19–28 Dec, 9 nights against this row's 8 "
            "fits the budget",
            text,
        )

    def test_the_detailed_renderer_carries_the_note_too(self):
        html = render_over_budget([_row()], travellers=5)
        self.assertIn("package deal £900 for 5 (", html)
        self.assertIn("flights + B&amp;B, 2 rooms", html)
        self.assertIn(">Example Holidays ↗</a>", html)
        # The row's own price stays the row's price.
        self.assertIn("<strong style=\"color:#0f172a;\">£6,000</strong> package", html)
        self.assertIn("package · £6,042 door to door", html)

    def test_the_operator_is_only_a_link_that_keeps_the_quote(self):
        row = _row(package=_package(link_kind="search-page"))
        with patch.object(hol, "LAST_OVER_BUDGET", (row,)):
            html = _over_budget_html(load_holiday_config(CONFIG))
        self.assertNotIn("<a href=", html)
        self.assertIn("Example Holidays", unescape(html))
        self.assertIn("(dates to enter on their site)", unescape(html))

    def test_a_row_with_no_package_is_printed_without_a_note(self):
        row = _row(package=None)
        with patch.object(hol, "LAST_OVER_BUDGET", (row,)):
            html = _over_budget_html(load_holiday_config(CONFIG))
        self.assertIn("over", unescape(html))
        self.assertNotIn("package deal", unescape(html))
        detailed = render_over_budget([row], travellers=5)
        self.assertNotIn("package deal", detailed)
        self.assertNotIn("Example Holidays", detailed)


class CollectorTests(unittest.TestCase):
    """The note reaches the reader through the collector, and nothing moves."""

    def setUp(self):
        self.config = load_holiday_config(CONFIG)
        self.saved_over = hol.LAST_OVER_BUDGET
        self.saved_filtered = hol.LAST_FILTERED_OUT

    def tearDown(self):
        hol.LAST_OVER_BUDGET = self.saved_over
        hol.LAST_FILTERED_OUT = self.saved_filtered
        consume_package_skip_log()

    def _collect(self, loaded):
        return collect_holiday_deals(
            self.config,
            max_budget_gbp=self.config.max_budget_gbp,
            package_evidence=loaded or None,
        )

    def _row_for(self, name=RESORT):
        for row in hol.LAST_OVER_BUDGET:
            if row.get("resort_name") == name:
                return row
        raise AssertionError(
            f"no over-budget row for {name}: "
            f"{[r.get('resort_name') for r in hol.LAST_OVER_BUDGET]}")

    def test_the_collector_attaches_the_cheapest_in_budget_package(self):
        loaded = _loaded(_record(amount=900.0), _record(amount=2400.0))
        deals = self._collect(loaded)
        self.assertEqual(deals, (), "at £1,500 nothing may become a card")
        package = self._row_for()["package"]
        self.assertIsNotNone(package)
        self.assertEqual(package.total_gbp, 900.0)
        self.assertEqual((package.outbound_date, package.return_date),
                         PACKAGE_DATES)
        self.assertLessEqual(package.total_gbp, self.config.max_budget_gbp)

    def test_a_package_that_is_itself_over_the_ceiling_is_not_attached(self):
        deals = self._collect(_loaded(_record(amount=2400.0)))
        self.assertEqual(deals, ())
        self.assertIsNone(self._row_for()["package"])

    def test_no_evidence_leaves_the_row_exactly_as_it_was(self):
        deals = self._collect({})
        self.assertEqual(deals, ())
        self.assertIsNone(self._row_for()["package"])


class CheapestAcrossPairsTests(unittest.TestCase):
    def test_the_cheapest_read_on_any_priced_pair_is_the_one_quoted(self):
        loaded = _loaded(_record(amount=2400.0), _record(amount=900.0))
        price = cheapest_package_for_property(loaded, RESORT)
        self.assertIsNotNone(price)
        self.assertEqual(price.total_gbp, 900.0)

    def test_a_read_for_a_pair_this_run_does_not_price_is_not_quoted(self):
        loaded = _loaded(_record(amount=900.0))
        config = load_holiday_config(CONFIG)
        priced = hol.priceable_date_pairs(config)
        self.assertIn(PACKAGE_DATES, priced)
        self.assertIsNone(
            cheapest_package_for_property(
                loaded, RESORT, date_pairs=[ROW_DATES]))

    def test_punctuation_is_ignored_when_the_property_is_matched(self):
        # The exporter wrote the "&"; the catalogue would write "and" — the
        # two must still be the same hotel (hotel_evidence._normalise_property).
        loaded = _loaded(_record(amount=900.0,
                                 property_name="Concorde De Luxe Resort & Spa"))
        price = cheapest_package_for_property(
            loaded, "Concorde De Luxe Resort and Spa")
        self.assertIsNotNone(price)
        self.assertEqual(price.total_gbp, 900.0)


if __name__ == "__main__":
    unittest.main()
