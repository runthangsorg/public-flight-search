"""A held-back resort is named, with its price and the reason (BRIEF-H16 §1).

The short-haul rule keeps an over-ceiling resort to itself when its
destination has other cards, and Lara Barut Collection was December item 2
until that rule hid it completely: a live £8,994 door to door for a December
fortnight that the report never mentioned. The rule stays — one card per
destination is the point of the report, and a held-back resort is still not a
card. What H16 changes is that the silence ends.

Pinned here:

* the resort is on the over-budget list, marked ``held_back``, with its own
  pair, its D2D total and what priced it — every field a fact the collector
  already holds, so nothing new is claimed;
* the reason is the owner's own sentence: the destination that has cards
  within budget;
* ONE sentence, built once, printed by the compact e-mail, its plain-text
  twin and the audit page, so the three cannot word it differently;
* a resort whose destination produced NO card at all is untouched: its row
  was already there and it still says only what it always said.
"""

from __future__ import annotations

import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    _over_budget_html,
    held_back_sentence,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_over_budget,
)

NOW = "2026-10-06T12:00:00+00:00"
BUDGET = 2200.0
RESORT = "Titanic Mardan Palace"
CARDED = "Concorde De Luxe Resort"

#: Antalya at a ceiling where two of its three resorts fit and the third does
#: not — the shape the owner read in the December report.
CONFIG = """
{
  "report_title": "Antalya: two resorts fit, one does not",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 2200,
  "min_nights": 8,
  "max_nights": 8,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-17", "2026-12-20"],
  "return_dates": ["2026-12-25", "2026-12-28"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"], "flight_hours": 4.5}
  ]
}
"""


def _row(**overrides) -> dict:
    """A held-back over-budget row, shaped as the collector builds one."""
    row = {
        "resort_name": RESORT,
        "destination_label": "Antalya Riviera, Turkey",
        "destination_key": "antalya",
        "airport": "AYT",
        "cabin": "ECONOMY",
        "outbound": "2026-12-20",
        "return": "2026-12-28",
        "nights": 8,
        "origin": "LHR",
        "flight_cost": 1530.0,
        "hotel_cost": 1200.0,
        "total_pkg": 2730.0,
        "true_d2d": 2770.0,
        "flight_confidence": "benchmark",
        "hotel_confidence": "market-supported",
        "hotel_rate_basis": "market-supported",
        "hotel_rate_read_dates": (),
        "unit": "2-Bedroom Family Suite",
        "board": "Ultra All Inclusive",
        "board_options": (),
        "flight_options": (),
        "max_budget_gbp": BUDGET,
        "package": None,
        "held_back": True,
    }
    row.update(overrides)
    return row


class SentenceTests(unittest.TestCase):
    def test_it_names_the_resort_the_pair_the_price_and_the_reason(self):
        sentence = held_back_sentence(_row(), travellers=5)
        self.assertEqual(
            sentence,
            f"{RESORT} · 20–28 Dec · £2,770 for 5, door to door · priced by "
            "a benchmark fare and a rate read for these dates · held back: "
            "Antalya Riviera, Turkey has cards within budget")

    def test_the_pair_is_spelled_in_words_not_as_iso_dates(self):
        sentence = held_back_sentence(_row(), travellers=5)
        self.assertIn("20–28 Dec", sentence)
        self.assertNotIn("2026-12-20", sentence)

    def test_a_stay_carried_from_another_pair_names_that_pair(self):
        # A nightly derived from a read for a neighbouring fortnight is an
        # estimate, and the read's own dates must not be mistakable for this
        # row's — which is why "another pair" comes before them.
        sentence = held_back_sentence(
            _row(hotel_rate_basis="read-rate-estimate",
                 hotel_rate_read_dates=("2026-12-17", "2026-12-25")),
            travellers=5,
        )
        self.assertIn("a rate read for another pair, 17–25 Dec", sentence)
        self.assertNotIn("a rate read for these dates", sentence)

    def test_a_live_fare_is_named_as_the_flight_basis(self):
        sentence = held_back_sentence(
            _row(flight_confidence="verified-exact-date"), travellers=5)
        self.assertIn("priced by a live fare read and", sentence)

    def test_a_row_that_is_not_held_back_has_no_sentence(self):
        # Every other row on the list is there because its destination produced
        # nothing; it keeps the line it has always had.
        self.assertEqual(held_back_sentence(_row(held_back=False), travellers=5), "")
        self.assertEqual(held_back_sentence(_row(held_back=None), travellers=5), "")

    def test_the_reason_survives_a_destination_with_no_label(self):
        sentence = held_back_sentence(_row(destination_label=""), travellers=5)
        self.assertTrue(
            sentence.endswith("held back: this destination has cards within budget"),
            sentence)


class SurfaceTests(unittest.TestCase):
    """One sentence, three renderers: the e-mail, its twin and the page."""

    def setUp(self):
        self.config = load_holiday_config(CONFIG)
        self.sentence = held_back_sentence(_row(), travellers=5)

    def test_the_compact_email_prints_it(self):
        with patch.object(hol, "LAST_OVER_BUDGET", (_row(),)):
            html = _over_budget_html(self.config)
        self.assertIn(self.sentence, unescape(html))

    def test_the_plain_text_email_prints_the_same_words(self):
        with patch.object(hol, "LAST_OVER_BUDGET", (_row(),)):
            text = render_holiday_report_compact_text(
                self.config, generated_at=NOW)
        self.assertIn(self.sentence, text)

    def test_the_audit_page_prints_the_same_words(self):
        html = render_over_budget([_row()], travellers=5)
        self.assertIn(self.sentence, unescape(html))

    def test_the_held_back_line_replaces_the_gap_line_not_sits_beside_it(self):
        # The two lines state different things — this one has no pair, no unit
        # and no gap, that one has no reason — so a reader is never asked to
        # reconcile two figures for one resort.
        with patch.object(hol, "LAST_OVER_BUDGET", (_row(),)):
            text = render_holiday_report_compact_text(
                self.config, generated_at=NOW)
        line = next(line for line in text.splitlines() if RESORT in line)
        self.assertIn("held back:", line)
        self.assertNotIn("over", line.split("held back:")[0])

    def test_an_ordinary_row_keeps_the_line_it_always_had(self):
        with patch.object(hol, "LAST_OVER_BUDGET", (_row(held_back=False),)):
            text = render_holiday_report_compact_text(
                self.config, generated_at=NOW)
        line = next(line for line in text.splitlines() if RESORT in line)
        self.assertIn("£570 over", line)
        self.assertNotIn("held back", line)


class CollectorTests(unittest.TestCase):
    """The rule itself is unchanged; only the silence is broken."""

    def setUp(self):
        self.config = load_holiday_config(CONFIG)
        self.saved_over = hol.LAST_OVER_BUDGET
        self.saved_filtered = hol.LAST_FILTERED_OUT

    def tearDown(self):
        hol.LAST_OVER_BUDGET = self.saved_over
        hol.LAST_FILTERED_OUT = self.saved_filtered

    def _row_for(self, name):
        for row in hol.LAST_OVER_BUDGET:
            if row.get("resort_name") == name:
                return row
        raise AssertionError(
            f"no over-budget row for {name}: "
            f"{[r.get('resort_name') for r in hol.LAST_OVER_BUDGET]}")

    def test_the_held_back_resort_is_listed_with_its_price_and_reason(self):
        deals = collect_holiday_deals(self.config, max_budget_gbp=BUDGET)
        self.assertIn(CARDED, [d.resort_name for d in deals])
        row = self._row_for(RESORT)
        self.assertTrue(row["held_back"])
        self.assertGreater(row["true_d2d"], BUDGET)
        sentence = held_back_sentence(row, travellers=5)
        self.assertIn(RESORT, sentence)
        self.assertIn(f"£{row['true_d2d']:,.0f} for 5, door to door", sentence)
        self.assertIn(
            "held back: Antalya Riviera, Turkey has cards within budget", sentence)

    def test_the_destination_still_gets_exactly_its_own_cards(self):
        # The rule is untouched: the held-back resort is priced, not offered,
        # and the destination's cards are the same ones it had before.
        deals = collect_holiday_deals(self.config, max_budget_gbp=BUDGET)
        self.assertNotIn(RESORT, [d.resort_name for d in deals])
        carded = {d.destination_key for d in deals}
        self.assertEqual(carded, {"antalya"})

    def test_a_resort_whose_destination_produced_no_card_is_unchanged(self):
        # Nothing fits anywhere: every row is listed for the reason it always
        # was — its own destination produced nothing — and carries no second
        # reason and no held-back line.
        collect_holiday_deals(self.config, max_budget_gbp=100.0)
        listed = {row["destination_key"] for row in hol.LAST_OVER_BUDGET}
        self.assertEqual(listed, {"antalya"})
        for row in hol.LAST_OVER_BUDGET:
            with self.subTest(resort=row["resort_name"]):
                self.assertFalse(row["held_back"])
                self.assertEqual(held_back_sentence(row, travellers=5), "")

    def test_an_uncarded_destination_row_is_still_printed_the_old_way(self):
        collect_holiday_deals(self.config, max_budget_gbp=100.0)
        with patch.object(
            hol, "LAST_OVER_BUDGET", tuple(hol.LAST_OVER_BUDGET)
        ):
            text = render_holiday_report_compact_text(
                self.config, generated_at=NOW)
        self.assertIn("£", text)
        self.assertNotIn("held back", text)

    def test_no_resort_is_priced_twice_on_the_list(self):
        collect_holiday_deals(self.config, max_budget_gbp=BUDGET)
        names = [row["resort_name"] for row in hol.LAST_OVER_BUDGET]
        self.assertEqual(len(names), len(set(names)))

    def test_the_whole_report_says_the_held_back_resort_only_once(self):
        deals = collect_holiday_deals(self.config, max_budget_gbp=BUDGET)
        with patch.object(hol, "LAST_OVER_BUDGET", hol.LAST_OVER_BUDGET):
            html = render_holiday_report_compact(
                self.config, generated_at=NOW, deals=deals)
        self.assertEqual(unescape(html).count(f"held back: Antalya Riviera"), 1)


class RealDecemberCaseTests(unittest.TestCase):
    """The shape the owner actually read, on the committed December config.

    Lara Barut Collection reaches the held-back list in the real run because its
    OWN live read lifts it over the ceiling, and that read lives in the private
    evidence file this repository never commits — so no figure from it can be
    pinned here. What is pinned is the destination rule on the committed
    config: Antalya cards only from the resorts that fit, and a resort that
    does not fit is either listed for its own destination or marked. The real
    line is verified by the December dry run (REPLY-H16), not by this test.
    """

    def setUp(self):
        self.config = load_holiday_config(
            (Path(__file__).resolve().parents[1] / "examples"
             / "dec_holiday_config.json").read_text(encoding="utf-8"))
        self.saved_over = hol.LAST_OVER_BUDGET

    def tearDown(self):
        hol.LAST_OVER_BUDGET = self.saved_over

    def test_every_antalya_resort_is_either_a_card_or_a_listed_row(self):
        deals = collect_holiday_deals(
            self.config, max_budget_gbp=self.config.max_budget_gbp)
        self.assertIn("Lara Barut Collection", [d.resort_name for d in deals])
        self.assertEqual(
            [row["resort_name"] for row in hol.LAST_OVER_BUDGET
             if row["destination_key"] == "antalya"],
            [],
            "Antalya carded, so with no evidence there is nothing held back")

    def test_a_resort_that_cannot_fit_is_still_listed_when_its_destination_cannot(self):
        # Nothing fits in Antalya at £100: every resort is on the list, and
        # every row is there for the reason it always was.
        collect_holiday_deals(self.config, max_budget_gbp=100.0)
        antalya = [row for row in hol.LAST_OVER_BUDGET
                   if row["destination_key"] == "antalya"]
        self.assertIn(
            "Lara Barut Collection", [row["resort_name"] for row in antalya])
        for row in antalya:
            with self.subTest(resort=row["resort_name"]):
                self.assertFalse(row["held_back"])


if __name__ == "__main__":
    unittest.main()