"""Real operator package prices on the planner cards (WP4d, owner brief
2026-10-04; extended by H8 for the ``rooms_sum`` basis).

The private engine now reads an operator's own package price — flights and
hotel, one booking — for the exact dates and party. These tests pin what the
public side does with one, and the two things it must never do:

* **it never becomes the price.** The card's headline stays the engine's own
  flights + stay, and the operator's figure rides beside it as information.
  The total, the budget test, the discount, the value score and the ORDER of the
  report are asserted byte-equal against a run with no package evidence at all;
* **it is never shown for the wrong trip.** A package read for other dates is
  another package, and a party that is not the report's party is another
  booking.

The basis that matters for this report's party is ``rooms_sum``: five
travellers cannot be one room, so the operator displays a price per room and the
engine adds them. That arrived as the ONLY basis in the real export on
2026-10-04 (7 of 7 records), which is why accepting it is the difference
between the feature working and not existing.

Synthetic throughout: an invented Antalya window, invented operators, invented
prices, and an evidence file written to a temp path. Nothing here is read from
an export, a captured page or ``data/``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)
from public_flight_search.hotel_evidence import _normalise_property
from public_flight_search.package_evidence import (
    consume_package_skip_log,
    load_package_evidence,
    package_price_for,
    package_provenance,
)

ROOT = Path(__file__).parents[1]
NOW = "2026-10-04T12:00:00+00:00"
OBSERVED_AT = "2026-10-03T09:00:00+00:00"

RESORT = "Concorde De Luxe Resort"

#: A narrow Antalya window so every test knows exactly which pair the card is
#: built on. Same shape as ``tests/test_multi_pair_pricing.py``'s BAND_JSON, so
#: the nights band, the origin rule and the headline pair behave as they do
#: there.
CONFIG = """
{
  "report_title": "Operator package on the card",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
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

#: The pair a benchmark-only run prices for this window. Pinned by a test so a
#: config change cannot quietly move every expectation with it.
CARD_PAIR = ("2026-12-20", "2026-12-28")

#: The exporter's own words for a two-room sum, in the shape the real export
#: uses (2026-10-04): one clause per room, each naming the room and the adults
#: in it, then a closing clause.
ROOMS_HOW = (
    "room 1 £4,112.80 (2 adults, Grand Deluxe - Bed and Breakfast) + "
    "room 2 £5,847.90 (3 adults, Grand Deluxe - Bed and Breakfast), "
    "all as shown for the same hotel on Bed and Breakfast and the same dates"
)


def _record(*, basis="rooms_sum", amount=4112.80, derived_value=9960.70,
            how=ROOMS_HOW, name=RESORT, outbound=CARD_PAIR[0],
            returning=CARD_PAIR[1], **overrides) -> dict:
    record = {
        "operator_key": "example_holidays",
        "operator": "Example Holidays",
        "property_name": name,
        "destination_key": "antalya",
        "season": "winter",
        "departure_airport": "LHR",
        "outbound_date": outbound,
        "return_date": returning,
        "nights": 8,
        "party": {"adults": 5, "children": 0, "child_ages": []},
        "rooms": 2,
        "room_descriptions": ["GRAND DELUXE", "GRAND DELUXE"],
        "board": "BB",
        "price_shown": {"amount": amount, "currency": "GBP", "basis": basis},
        "read_method": "dom-text",
        "link_kind": "deep-link",
        "source_url": "https://www.example.invalid/package/antalya",
        "observed_at": OBSERVED_AT,
        "exact_date_match": True,
        "confidence": "verified-exact-date",
        "flight_summary": "",
        "includes": ["transfers"],
    }
    if derived_value is not None:
        record["derived_total_gbp"] = {"value": derived_value, "how": how}
    record.update(overrides)
    return record


def _evidence_file(records, **extra) -> str:
    payload = {"schema": "holiday_package_evidence/1", "packages": list(records)}
    payload.update(extra)
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    return handle.name


def _loaded(records, *, config=None, path=None):
    config = config or load_holiday_config(CONFIG)
    if path is None:
        path = _evidence_file(records)
    return load_package_evidence(config, path=path, now=NOW)


def _deals(*records, config=None, with_packages: bool = True, **kwargs):
    config = config or load_holiday_config(CONFIG)
    loaded = _loaded(records, config=config) if with_packages else {}
    deals = collect_holiday_deals(
        config,
        max_budget_gbp=config.max_budget_gbp,
        package_evidence=loaded or None,
        **kwargs,
    )
    consume_package_skip_log()
    return deals


def _deal(deals, name: str = RESORT):
    for deal in deals:
        if deal.resort_name == name:
            return deal
    raise AssertionError(f"no card for {name}: {[d.resort_name for d in deals]}")


def _visible(html: str) -> str:
    from html import unescape
    import re

    return unescape(re.sub(r"<[^>]+>", " ", html))


def _render(deals, *, generated_at=NOW):
    return render_holiday_report_compact(
        load_holiday_config(CONFIG), generated_at=generated_at, deals=deals,
    )


def _render_text(deals, *, generated_at=NOW):
    return render_holiday_report_compact_text(
        load_holiday_config(CONFIG), generated_at=generated_at, deals=deals,
    )


class TestTheWindowIsPinned(unittest.TestCase):
    def test_the_card_is_built_on_the_pinned_pair(self):
        deal = _deal(_deals(with_packages=False))
        self.assertEqual(
            (deal.outbound_date, deal.return_date, deal.nights), (*CARD_PAIR, 8)
        )


class TestTheLoaderAcceptsARoomSum(unittest.TestCase):
    """A five-traveller booking is two rooms, so this is the normal shape."""

    def test_a_rooms_sum_prices_the_card_from_the_derived_total(self):
        loaded = _loaded([_record()])
        price = package_price_for(loaded, RESORT, *CARD_PAIR)
        self.assertIsNotNone(price)
        self.assertEqual(price.total_gbp, 9960.70)
        self.assertEqual(price.price_basis, "rooms_sum")

    def test_the_exporter_arithmetic_is_kept_verbatim(self):
        loaded = _loaded([_record()])
        price = package_price_for(loaded, RESORT, *CARD_PAIR)
        self.assertEqual(price.price_how, ROOMS_HOW)

    def test_the_provenance_says_the_total_is_a_sum_and_not_a_displayed_total(self):
        # The failure this seam exists to prevent: a figure that reads like one
        # the operator printed for the party when it is the engine's addition.
        loaded = _loaded([_record()])
        sentence = package_provenance(package_price_for(loaded, RESORT, *CARD_PAIR))
        self.assertIn("2 room prices added, as shown", sentence)
        self.assertNotIn("whole-party total as shown", sentence)

    def test_a_rooms_sum_with_no_derived_value_is_refused_with_a_stated_reason(self):
        loaded = _loaded([_record(derived_value=None)])
        self.assertEqual(loaded, {})
        self.assertTrue(
            any("derived_total_gbp" in reason for reason in consume_package_skip_log())
        )

    def test_a_rooms_sum_whose_how_is_empty_is_refused(self):
        # A total with no arithmetic on its face is a figure nobody can check.
        _loaded([_record(how="")])
        self.assertTrue(
            any("derived_total_gbp" in reason for reason in consume_package_skip_log())
        )

    def test_a_rooms_sum_whose_total_is_not_positive_is_refused(self):
        _loaded([_record(derived_value=0.0)])
        self.assertTrue(
            any("derived_total_gbp" in reason for reason in consume_package_skip_log())
        )

    def test_a_rooms_sum_for_another_party_is_refused(self):
        _loaded([_record(party={"adults": 4, "children": 0})])
        self.assertTrue(
            any("report party" in reason for reason in consume_package_skip_log())
        )

    def test_a_rooms_sum_in_another_currency_is_refused(self):
        _loaded([_record(price_shown={
            "amount": 4112.80, "currency": "EUR", "basis": "rooms_sum"})])
        self.assertTrue(
            any("GBP" in reason for reason in consume_package_skip_log())
        )

    def test_a_whole_party_total_still_prices_the_card(self):
        loaded = _loaded([_record(basis="whole_party_total", amount=5100.0,
                                  derived_value=None)])
        price = package_price_for(loaded, RESORT, *CARD_PAIR)
        self.assertEqual((price.total_gbp, price.price_basis), (5100.0, "whole_party_total"))
        self.assertEqual(price.price_how, "")

    def test_a_per_person_price_still_prices_the_card(self):
        loaded = _loaded([_record(basis="per_person", amount=1020.0,
                                  derived_value=5100.0,
                                  how="1020 per person x 5 travellers as shown")])
        price = package_price_for(loaded, RESORT, *CARD_PAIR)
        self.assertEqual((price.total_gbp, price.price_basis), (5100.0, "per_person"))

    def test_an_unknown_basis_is_refused_by_name(self):
        _loaded([_record(basis="mystery")])
        self.assertTrue(
            any("'mystery'" in reason for reason in consume_package_skip_log())
        )

    def test_two_qualifying_records_for_one_key_keep_the_cheaper(self):
        loaded = _loaded([
            _record(derived_value=9960.70),
            _record(derived_value=8800.00),
        ])
        self.assertEqual(
            package_price_for(loaded, RESORT, *CARD_PAIR).total_gbp, 8800.00
        )


class TestThePropertyNameMatchesTheExportsSpelling(unittest.TestCase):
    """The exporter writes ``and`` where the catalogue writes ``&``."""

    def test_the_briefs_own_pair_normalises_to_the_same_name(self):
        self.assertEqual(
            _normalise_property("Melati Beach Resort and Spa"),
            _normalise_property("Melati Beach Resort & Spa"),
        )

    def test_a_spelled_out_conjunction_still_finds_the_record(self):
        # The exact lookup the collector makes, both ways round.
        loaded = _loaded([_record(name="Melati Beach Resort and Spa")])
        self.assertIsNotNone(
            package_price_for(loaded, "Melati Beach Resort & Spa", *CARD_PAIR)
        )
        self.assertIsNotNone(
            package_price_for(loaded, "Melati Beach Resort and Spa", *CARD_PAIR)
        )

    def test_a_word_that_merely_contains_and_is_not_a_conjunction(self):
        # "Banyan" and "Anderson" keep every letter: only a standalone word is
        # the conjunction, or two genuinely different hotels would collide.
        self.assertEqual(_normalise_property("Banyan Tree Samui"), "banyantreesamui")
        self.assertEqual(
            _normalise_property("Anderson Resort"), "andersonresort"
        )
        self.assertNotEqual(
            _normalise_property("Anderson Resort"), _normalise_property("Resort")
        )

    def test_a_comma_still_does_not_hide_a_price(self):
        loaded = _loaded([_record(name="Concorde, De Luxe Resort")])
        self.assertIsNotNone(package_price_for(loaded, RESORT, *CARD_PAIR))


class TestTheDealCarriesItWithoutBeingPricedByIt(unittest.TestCase):
    def test_the_card_carries_the_operators_price(self):
        deal = _deal(_deals(_record()))
        package = deal.operator_package
        self.assertIsNotNone(package)
        self.assertEqual(package.total_gbp, 9960.70)
        self.assertEqual(package.operator, "Example Holidays")
        self.assertEqual(package.board, "BB")
        self.assertEqual(package.rooms, 2)
        self.assertEqual(package.link_kind, "deep-link")
        self.assertEqual(package.provenance, package_provenance(
            package_price_for(_loaded([_record()]), RESORT, *CARD_PAIR)
        ))

    def test_the_gap_to_the_engines_own_total_is_carried(self):
        deal = _deal(_deals(_record()))
        self.assertAlmostEqual(
            deal.operator_package.vs_engine_gbp,
            round(deal.total_package_price_gbp - 9960.70, 2),
            places=2,
        )

    def test_nothing_about_the_ranking_moves(self):
        # The whole point: an operator's price is information, not a re-ranking.
        # Every field that decides what the report shows must be identical.
        with_package = _deals(_record())
        without = _deals(with_packages=False)
        self.assertEqual(
            [d.resort_name for d in with_package], [d.resort_name for d in without]
        )
        fields = (
            "resort_name", "outbound_date", "return_date", "nights", "cabin_class",
            "flight_price_total_gbp", "hotel_price_total_gbp",
            "total_package_price_gbp", "true_d2d_gbp", "price_per_person_gbp",
            "is_under_budget", "confidence", "value_score", "deal_class",
            "peak_summer_total_gbp",
        )
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual(
                    [getattr(d, field) for d in with_package],
                    [getattr(d, field) for d in without],
                )

    def test_a_deal_with_no_match_carries_nothing(self):
        deals = _deals(_record(name="Some Other Property"))
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertIsNone(deal.operator_package)

    def test_a_package_read_for_other_dates_does_not_ride_the_card(self):
        deals = _deals(_record(outbound="2026-12-19", returning="2026-12-28"))
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                self.assertIsNone(deal.operator_package)

    def test_no_package_evidence_at_all_changes_nothing(self):
        deals = _deals(_record(), with_packages=False)
        self.assertTrue(deals)
        for deal in deals:
            self.assertIsNone(deal.operator_package)


class TestTheCompactCardShowsIt(unittest.TestCase):
    def test_the_line_carries_the_price_the_party_and_the_operator(self):
        text = _visible(_render(_deals(_record())))
        self.assertIn("Package deal: £9,961 for 5", text)
        self.assertIn("Example Holidays", text)

    def test_the_board_is_words_and_the_room_count_is_spelled(self):
        text = _visible(_render(_deals(_record())))
        self.assertIn("Bed & Breakfast", text)
        self.assertIn("2 rooms", text)
        self.assertNotIn(" BB,", text)

    def test_the_line_states_when_it_was_checked(self):
        text = _visible(_render(_deals(_record())))
        self.assertIn("checked 3 Oct", text)

    def test_a_cheaper_package_says_how_much_less(self):
        text = _visible(_render(_deals(_record(derived_value=100.0))))
        self.assertRegex(text, r"£[\d,]+ less than booking separately")

    def test_a_dearer_package_says_how_much_more(self):
        text = _visible(_render(_deals(_record(derived_value=99999.0))))
        self.assertRegex(text, r"£[\d,]+ more than booking separately")

    def test_an_equal_package_says_so_rather_than_printing_a_zero(self):
        deal = _deal(_deals(with_packages=False))
        exact = round(deal.total_package_price_gbp, 2)
        text = _visible(_render(_deals(_record(derived_value=exact))))
        self.assertIn("the same as booking separately", text)
        self.assertNotIn("£0 less", text)

    def test_the_two_room_arithmetic_is_shown_beneath_in_small_words(self):
        text = _visible(_render(_deals(_record())))
        self.assertIn("2 rooms added:", text)
        self.assertIn("room 1 £4,113 (2 adults)", text)
        self.assertIn("room 2 £5,848 (3 adults)", text)
        # The exporter's full sentence is 200-odd characters and does not belong
        # on a card; the two figures it exists to show do.
        self.assertNotIn("Grand Deluxe - Bed and Breakfast)", text)

    def test_a_deep_link_makes_the_operators_name_a_link(self):
        html = _render(_deals(_record()))
        self.assertIn("https://www.example.invalid/package/antalya", html)

    def test_a_search_page_link_is_words_not_a_link_that_loses_the_dates(self):
        html = _render(_deals(_record(link_kind="search-page")))
        self.assertIn("(dates to enter on their site)", _visible(html))
        self.assertNotIn("https://www.example.invalid/package/antalya", html)

    def test_a_prefilled_search_link_is_a_link(self):
        html = _render(_deals(_record(link_kind="prefilled-search")))
        self.assertIn("https://www.example.invalid/package/antalya", html)
        self.assertNotIn("(dates to enter on their site)", _visible(html))

    def test_a_card_with_no_package_prints_no_line(self):
        text = _visible(_render(_deals(with_packages=False)))
        self.assertNotIn("Package deal", text)
        self.assertNotIn("rooms added", text)

    def test_the_plain_text_part_mirrors_the_line(self):
        text = _render_text(_deals(_record()))
        self.assertIn("Package deal: £9,961 for 5", text)
        self.assertIn("Example Holidays", text)
        # This fixture's package is dearer than the engine's total; the text
        # says so in the same words the HTML does.
        self.assertIn("more than booking separately", text)
        self.assertIn("2 rooms added:", text)
        self.assertIn("room 1 £4,113 (2 adults)", text)

    def test_the_text_part_says_less_when_the_package_really_is_cheaper(self):
        text = _render_text(_deals(_record(derived_value=100.0)))
        self.assertRegex(text, r"£[\d,]+ less than booking separately")

    def test_the_line_is_beside_the_headline_and_never_replaces_it(self):
        text = _visible(_render(_deals(_record())))
        self.assertIn("total for 5, door to door", text)
        self.assertIn("Package deal", text)
        # Exactly one headline price: the engine's own.
        # Once per card, plus the at-a-glance key line, which says the same
        # words once for the whole table.
        self.assertEqual(
            text.count("total for 5, door to door"),
            len(_deals(_record())) + 1,
        )


class TestTheDetailedStyleShowsItToo(unittest.TestCase):
    """WP4d D3: choosing a style must not change what the report claims."""

    def _html(self, deals):
        return render_holiday_report(
            load_holiday_config(CONFIG), generated_at=NOW, deals=deals,
        )

    def test_the_detailed_card_carries_the_same_line(self):
        html = self._html(_deals(_record()))
        self.assertIn("Operator package:", html)
        self.assertIn("Example Holidays", html)
        # This fixture's package is dearer than the engine's own Antalya total,
        # and the line says so rather than implying a saving.
        self.assertIn("MORE than booking flights and hotel separately", html)

    def test_the_detailed_card_says_less_when_the_package_really_is_cheaper(self):
        html = self._html(_deals(_record(derived_value=100.0)))
        self.assertRegex(html, r"£[\d,]+ LESS than booking flights and hotel separately")

    def test_the_detailed_self_create_note_no_longer_says_the_price_is_unverified(self):
        # The old text claimed no package price existed while the card above it
        # carried one. With a read price the comparison is a real verdict. The
        # card is rendered ALONE, because the other two resorts in this window
        # have no package and must keep the old sentence.
        without = _visible(self._html(_deals(with_packages=False)))
        self.assertIn("package price not verified", without)

        con_only = _deal(_deals(_record(derived_value=99999.0)))
        html = _visible(self._html([con_only]))
        self.assertNotIn("package price not verified", html)
        self.assertIn("self-create is", html)

    def test_the_detailed_card_names_the_board_and_the_rooms(self):
        text = _visible(self._html(_deals(_record())))
        self.assertIn("Bed & Breakfast", text)
        self.assertIn("2 rooms", text)

    def test_the_detailed_card_shows_the_two_room_arithmetic(self):
        text = _visible(self._html(_deals(_record())))
        self.assertIn("2 rooms added:", text)
        self.assertIn("room 1 £4,113 (2 adults)", text)

    def test_a_search_page_link_is_words_in_the_detailed_style_too(self):
        html = self._html(_deals(_record(link_kind="search-page")))
        self.assertIn("(dates to enter on their site)", _visible(html))
        self.assertNotIn("https://www.example.invalid/package/antalya", html)

    def test_a_card_with_no_package_prints_no_line(self):
        # The detailed report already has a "Package operators" LINK block and a
        # "package price not verified" note; neither is this line, and both are
        # why the assertion names our own marker.
        html = self._html(_deals(with_packages=False))
        self.assertNotIn("Operator package:", html)
        self.assertNotIn("rooms added:", html)


class TestTheRunSummary(unittest.TestCase):
    """WP4d D1: the five fields, so an operator can see what was collected."""

    def _run(self, **kwargs):
        from public_flight_search import jobs

        return jobs.run_holiday_planner(dry_run=True, **kwargs)

    def _fields(self, result):
        return {
            "package_evidence_file_found": result["package_evidence_file_found"],
            "package_evidence_newest_observed_at":
                result["package_evidence_newest_observed_at"],
            "package_prices_on_cards": result["package_prices_on_cards"],
            "package_evidence_skipped": result["package_evidence_skipped"],
            "package_evidence_load_error": result["package_evidence_load_error"],
        }

    def test_a_missing_file_is_reported_and_changes_nothing_else(self):
        result = self._run(
            config_path=str(ROOT / "examples" / "dec_holiday_config.json"),
            package_evidence_path="/nonexistent/holiday_package_evidence.json",
            hotel_evidence_path="/nonexistent/hotel.json",
            live_evidence_path="/nonexistent/live.json",
        )
        fields = self._fields(result)
        self.assertFalse(fields["package_evidence_file_found"])
        self.assertEqual(fields["package_prices_on_cards"], 0)
        self.assertIsNone(fields["package_evidence_load_error"])
        self.assertIsNone(fields["package_evidence_newest_observed_at"])
        # A missing package file must not stop the report being built.
        self.assertGreater(result["deal_count"], 0)

    def test_an_unreadable_file_is_reported_as_an_error_not_swallowed(self):
        bad = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        bad.write("{not json at all")
        bad.close()
        result = self._run(
            config_path=str(ROOT / "examples" / "dec_holiday_config.json"),
            package_evidence_path=bad.name,
            hotel_evidence_path="/nonexistent/hotel.json",
            live_evidence_path="/nonexistent/live.json",
        )
        self.assertTrue(result["package_evidence_file_found"])
        self.assertIsNone(result["package_evidence_load_error"])
        self.assertTrue(result["package_evidence_skipped"])
        self.assertGreater(result["deal_count"], 0)