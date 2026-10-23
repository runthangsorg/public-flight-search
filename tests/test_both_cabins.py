"""Business and Economy flight prices, both shown for a trip (owner decision, 23 Oct 2026: "i want both business and economy").

Until now a two-centre read was indexed by (trip, legs) alone, and since d69d7a1 a MIXED/BUSINESS read hid an Economy read of the
same legs, so the cheap figure vanished. Reads now come in two products per trip: ``ECONOMY`` (Economy on every flight) and
``MIXED`` (Business on every leg over eight hours, Economy hops, separate tickets; ``cabin_mix`` says which) or ``BUSINESS``.
These tests pin that:

* the index keeps one read PER CABIN per (trip, legs), the cheaper winning only within a cabin, and the old single-read
  question still gets the rule-following read when both exist;
* a trip whose price itemises its flights (``cost_lines``) shows its total under BOTH reads, each with its own over/fits verdict,
  and says the cabin not read "has not been read for these dates yet" instead of estimating it; a trip whose figure bundles its own
  flights (an operator package, an estimate) keeps that figure and shows both flight reads beside it;
* the overview row, the quick answer, the trip page, the plain text and the full-detail attachment all carry it;
* the page says in one line what each product is made of, and never calls a mixed read Economy.

Synthetic reads throughout; the trips are the shipped ``multi_centre.json``.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search import trip_dossier as td
from public_flight_search.holiday_email import (
    multi_centre_wanted,
    render_holiday_report_compact_text,
    render_holiday_report_full,
)

from test_holiday_email_compact import _config, _deals, visible_text
from test_multi_centre_reads import _multi_centre_read
from test_trip_dossiers import NOW, STAMPS, UNLIMITED, _html, _ids, _rows, _slice, _table_ids

BUDGET = 12_000.0
MIX = "Business LHR-JRO, ZNZ-LHR + Economy JRO-ZNZ"
WANTED = {w["trip"]: w for w in multi_centre_wanted(_config())}


def _row(trip, cabin, total, *, observed="2026-10-22T09:00:00+00:00", **extra):
    row = _multi_centre_read(WANTED[trip], observed_at=observed, total=float(total))
    row["cabin"] = cabin
    row["source_url"] = f"https://example.org/SYNTHETIC-{trip}-{cabin}-{int(total)}"
    if cabin == "MIXED":
        row["cabin_mix"] = MIX
    row["vendor"] = "kayak" if cabin != "ECONOMY" else "google"
    row.update(extra)
    return row


def _load(rows):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "stopover_reads_synthetic.json"
        path.write_text(json.dumps({"schema": hol.STOPOVER_READS_SCHEMA, "rows": list(rows)}), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            _stops, fares = hol.load_batch_reads(str(path))
    hol.consume_stopover_skip_log()
    return fares


def _legs(trip):
    return [tuple(leg) for leg in WANTED[trip]["legs"]]


def _both(trip="AF-10", eco=5_000, biz=20_000):
    return _load([_row(trip, "ECONOMY", eco, observed="2026-10-20T10:00:00+00:00"), _row(trip, "MIXED", biz)])


def _page(fares, trip="AF-10", **kw):
    return _slice(_html(fares=fares, **kw), f"trip-{trip}")


class TheIndexKeepsOneReadPerCabinTests(unittest.TestCase):
    def test_both_cabins_of_one_journey_are_kept(self):
        got = hol.multi_centre_fares_for("AF-10", _legs("AF-10"), fares=_both())
        self.assertEqual(sorted(got), ["ECONOMY", "MIXED"])
        self.assertEqual(got["ECONOMY"]["total_gbp"], 5_000.0)
        self.assertEqual(got["MIXED"]["total_gbp"], 20_000.0)

    def test_the_cheaper_read_wins_only_within_its_own_cabin(self):
        fares = _load([_row("AF-10", "ECONOMY", 5_400), _row("AF-10", "ECONOMY", 5_000),
                       _row("AF-10", "MIXED", 21_000), _row("AF-10", "MIXED", 20_000), _row("AF-10", "MIXED", 22_000)])
        got = hol.multi_centre_fares_for("AF-10", _legs("AF-10"), fares=fares)
        self.assertEqual((got["ECONOMY"]["total_gbp"], got["MIXED"]["total_gbp"]), (5_000.0, 20_000.0))

    def test_business_and_mixed_are_both_kept_when_both_were_read(self):
        got = hol.multi_centre_fares_for("AF-10", _legs("AF-10"),
                                         fares=_load([_row("AF-10", "BUSINESS", 26_000), _row("AF-10", "MIXED", 20_000)]))
        self.assertEqual(sorted(got), ["BUSINESS", "MIXED"])

    def test_the_old_single_read_question_gets_the_rule_following_read_when_both_exist(self):
        fares = _both()
        self.assertEqual(hol.multi_centre_fare_for("AF-10", _legs("AF-10"), fares=fares)["cabin"], "MIXED")
        economy_only = _load([_row("AF-10", "ECONOMY", 5_000)])
        self.assertEqual(hol.multi_centre_fare_for("AF-10", _legs("AF-10"), fares=economy_only)["cabin"], "ECONOMY")
        self.assertIsNone(hol.multi_centre_fare_for("AF-10", _legs("AF-10"), fares={}))

    def test_a_registry_without_cabin_entries_still_answers_both_questions(self):
        """A hand-built registry (``{key: read}``) is what older callers and tests pass."""
        read = _row("AF-10", "ECONOMY", 5_000)
        flat = {hol.multi_centre_fare_key("AF-10", _legs("AF-10")): read}
        self.assertEqual(hol.multi_centre_fare_for("AF-10", _legs("AF-10"), fares=flat), read)
        self.assertEqual(hol.multi_centre_fares_for("AF-10", _legs("AF-10"), fares=flat), {"ECONOMY": read})

    def test_a_read_for_other_dates_answers_neither(self):
        shifted = [list(leg) for leg in _legs("AF-10")]
        shifted[0][2] = "2027-06-28"
        self.assertEqual(hol.multi_centre_fares_for("AF-10", shifted, fares=_both()), {})

    def test_the_registry_function_keeps_every_cabin_entry(self):
        registry = hol.multi_centre_fares_registry(_both())
        self.assertEqual(sorted(hol.multi_centre_fares_for("AF-10", _legs("AF-10"), fares=registry)), ["ECONOMY", "MIXED"])


class TheTripTotalIsShownUnderBothReadsTests(unittest.TestCase):
    NON_FLIGHT = 9_287 - 5_123  # AF-10's own figure less its flights line

    def _dossier(self, fares, trip="AF-10"):
        return next(d for d in td.build_trip_dossiers(_config(), _rows(fares), generated_at=NOW) if d["id"] == trip)

    def test_the_total_is_the_rest_of_the_trip_plus_each_read(self):
        totals = {t["key"]: t for t in self._dossier(_both())["cabin_totals"]}
        self.assertEqual(totals["business"]["total"], self.NON_FLIGHT + 20_000)
        self.assertEqual(totals["economy"]["total"], self.NON_FLIGHT + 5_000)

    def test_each_total_has_its_own_verdict_against_the_budget(self):
        totals = {t["key"]: t for t in self._dossier(_both())["cabin_totals"]}
        self.assertTrue(totals["economy"]["fits"])
        self.assertFalse(totals["business"]["fits"])
        self.assertEqual(totals["business"]["gap"], self.NON_FLIGHT + 20_000 - BUDGET)
        text = visible_text(_page(_both()))
        self.assertIn(f"£{self.NON_FLIGHT + 20_000:,.0f}", text)
        self.assertIn(f"£{self.NON_FLIGHT + 5_000:,.0f}", text)
        self.assertIn(f"£{self.NON_FLIGHT + 20_000 - BUDGET:,.0f} over the £12,000 budget", text)
        self.assertRegex(text, r"all economy[^.]*fits the £12,000 budget")

    def test_the_labels_say_what_each_total_is(self):
        text = visible_text(_page(_both()))
        self.assertIn("with Business long-haul", text)
        self.assertIn("all economy", text)
        self.assertNotIn("with Business long-haul: all economy", text)

    def test_a_business_read_that_is_pure_business_is_labelled_so(self):
        fares = _load([_row("AF-10", "BUSINESS", 26_000), _row("AF-10", "ECONOMY", 5_000)])
        text = visible_text(_page(fares))
        self.assertIn("with Business on every flight", text)
        self.assertNotIn("with Business long-haul", text)

    def test_only_economy_read_says_the_business_one_has_not_been_read_and_prints_no_number_for_it(self):
        fares = _load([_row("AF-10", "ECONOMY", 5_000)])
        text = visible_text(_page(fares))
        self.assertIn("with Business long-haul has not been read for these dates yet", text)
        self.assertIn(f"£{self.NON_FLIGHT + 5_000:,.0f}", text)
        self.assertEqual([t["key"] for t in self._dossier(fares)["cabin_totals"]], ["economy"])

    def test_only_a_business_read_says_the_economy_one_has_not_been_read(self):
        fares = _load([_row("AF-10", "MIXED", 20_000)])
        text = visible_text(_page(fares))
        self.assertIn("all economy has not been read for these dates yet", text)
        self.assertIn(f"£{self.NON_FLIGHT + 20_000:,.0f}", text)

    def test_with_neither_read_the_trip_keeps_its_stated_figure_and_claims_no_cabin_totals(self):
        text = visible_text(_page(None))
        self.assertIn("from £9,287", text)
        self.assertNotIn("all economy", text)
        self.assertEqual(self._dossier(None)["cabin_totals"], [])

    def test_a_trip_whose_figure_bundles_its_own_flights_keeps_it_and_shows_both_reads_beside_it(self):
        fares = _both("AF-01")
        d = self._dossier(fares, "AF-01")
        self.assertEqual(d["cabin_totals"], [], "the package price cannot be recomputed per cabin")
        text = visible_text(_page(fares, "AF-01"))
        self.assertIn("£21,385–£25,235", text)
        self.assertIn("price includes its own flights", text)
        self.assertIn("£20,000", text)
        self.assertIn("£5,000", text)


class TheFlightsSectionPrintsBothReadsTests(unittest.TestCase):
    def test_each_read_has_its_price_date_vendor_cabin_words_and_link(self):
        fares = _both("AF-10")
        part = _page(fares)
        text = visible_text(part)
        self.assertIn("£20,000 for 5", text)
        self.assertIn(MIX, text)
        self.assertIn("£5,000 for 5", text)
        self.assertIn("20 Oct", text)
        self.assertIn("22 Oct", text)
        self.assertIn("Read through kayak", text)
        self.assertIn("Read through google", text)
        self.assertIn("https://example.org/SYNTHETIC-AF-10-MIXED-20000", part)
        self.assertIn("https://example.org/SYNTHETIC-AF-10-ECONOMY-5000", part)

    def test_the_mixed_read_is_never_called_economy(self):
        text = visible_text(_page(_both("AF-10")))
        line = re.search(r"£20,000 for 5[^.]*\.", text).group(0)
        self.assertIn("Business", line)
        self.assertNotRegex(line, r"Economy\.|, Economy,")

    def test_one_line_says_what_each_product_is_made_of(self):
        text = visible_text(_page(_both("AF-10")))
        self.assertIn("Business long-haul is Business on every flight over 8 hours and Economy on the shorter ones", text)
        self.assertIn("different products", text)
        self.assertEqual(text.count("different products"), 1)

    def test_the_per_leg_times_of_both_reads_are_printed(self):
        legs = _legs("AF-10")

        def flights(carrier, cabin):
            return [{"origin": o, "destination": d, "departure_local": f"{day}T08:15:00", "arrival_local": f"{day}T19:40:00",
                     "carrier": carrier, "stops": 0, "duration": "11h 25m", "layover": "", "cabin": cabin, "vendor": "kayak"}
                    for o, d, day in legs]

        fares = _load([_row("AF-10", "ECONOMY", 5_000, flights=flights("Economy Air", "ECONOMY")),
                       _row("AF-10", "MIXED", 20_000, flights=flights("Business Air", "BUSINESS"))])
        text = visible_text(_page(fares))
        self.assertEqual(text.count("departs 08:15"), 6, "three legs for each of the two options")
        self.assertIn("Business Air", text)
        self.assertIn("Economy Air", text)
        self.assertNotIn("not captured", text)


class TheOverviewAndQuickAnswersCarryItTests(unittest.TestCase):
    def _table(self, fares):
        html = _html(fares=fares)
        return html[html.index("Every option at a glance"):html.index('id="trips"')]

    def test_a_row_shows_both_totals_each_with_its_verdict(self):
        text = visible_text(self._table(_both()))
        row = text[text.index("Self-build: Kruger self-drive"):]
        row = row[:row.index("Kruger + Cape Town")]
        self.assertIn("Business £24,164", row)
        self.assertIn("Economy £9,164", row)
        self.assertIn("£12,164 over", row)
        self.assertIn("fits", row)

    def test_a_row_with_only_one_read_names_it_and_says_nothing_of_the_other(self):
        row = visible_text(self._table(_load([_row("AF-10", "ECONOMY", 5_000)])))
        row = row[row.index("Self-build: Kruger self-drive"):]
        row = row[:row.index("Kruger + Cape Town")]
        self.assertIn("Economy £9,164", row)
        self.assertNotIn("Business £", row)

    def test_a_row_names_the_cabin_not_read_yet_without_a_figure_for_it(self):
        row = visible_text(self._table(_load([_row("AF-10", "ECONOMY", 5_000)])))
        row = row[row.index("Self-build: Kruger self-drive"):]
        row = row[:row.index("Kruger + Cape Town")]
        self.assertIn("Business not read yet", row)
        both = visible_text(self._table(_both()))
        both = both[both.index("Self-build: Kruger self-drive"):]
        self.assertNotIn("not read yet", both[:both.index("Kruger + Cape Town")])
        self.assertIn("£12,164 over", visible_text(self._table(_both())))

    def test_the_order_of_the_rows_is_what_it_was_without_reads(self):
        self.assertEqual(_table_ids(_html(fares=_both())), _table_ids(_html(fares=None)))

    def test_every_trip_is_still_in_the_table(self):
        fares = _load([_row(t, "ECONOMY", 5_000) for t in WANTED] + [_row(t, "MIXED", 20_000) for t in WANTED])
        self.assertEqual(sorted(_table_ids(_html(fares=fares))), sorted(r["trip"].id for r in _rows(fares)))

    def test_the_quick_answer_uses_the_cabin_that_fits_and_says_which(self):
        text = visible_text(_html(fares=_both(), deals=[]))
        box = text[text.index("Start here"):text.index("How current this is")]
        self.assertIn("Self-build: Kruger self-drive", box)
        self.assertIn("£9,164", box)
        self.assertIn("all economy", box)

    def test_when_only_the_business_total_fits_it_is_named_as_that(self):
        fares = _load([_row("AF-10", "MIXED", 7_000)])
        text = visible_text(_html(fares=fares, deals=[]))
        box = text[text.index("Start here"):text.index("How current this is")]
        self.assertIn("£11,164", box)
        self.assertIn("with Business long-haul", box)


class TheTextAndTheAttachmentAndTheBudgetTests(unittest.TestCase):
    def test_the_plain_text_carries_both_totals_both_reads_and_the_note(self):
        text = render_holiday_report_compact_text(_config(), generated_at=NOW, deals=_deals(2), evidence_stamps=STAMPS,
                                                  multi_centre_fares=_both())
        for word in ("with Business long-haul", "£24,164", "all economy", "£9,164", "£20,000 for 5", "£5,000 for 5",
                     "different products"):
            self.assertIn(word, text, word)
        self.assertNotIn("all economy has not been read", text.split("Self-build: Kruger self-drive 4 nights + Cape Town 8 nights\n")[1][:1500])

    def test_the_full_detail_attachment_has_both_at_full_detail_whatever_the_body_shed(self):
        with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", 20_000):
            html = render_holiday_report_full(_config(), generated_at=NOW, deals=_deals(2), evidence_stamps=STAMPS,
                                              multi_centre_fares=_both())
        part = visible_text(_slice(html, "trip-AF-10"))
        self.assertNotIn("Shortened to fit", part)
        for word in ("£24,164", "£9,164", "£20,000 for 5", "£5,000 for 5", "different products"):
            self.assertIn(word, part, word)

    def test_every_trip_read_in_both_cabins_still_fits_the_body_budget_and_loses_least_important_detail_first(self):
        fares = _load([_row(t, "ECONOMY", 5_000) for t in WANTED] + [_row(t, "MIXED", 20_000) for t in WANTED])
        html = _html(fares=fares, deals=_deals(2), budget=hol.EMAIL_HTML_BUDGET_BYTES)
        self.assertLessEqual(len(html.encode("utf-8")), hol.EMAIL_HTML_BUDGET_BYTES)
        self.assertEqual(sorted(_ids(html)), sorted(WANTED))
        for ident in _ids(html):
            text = visible_text(_slice(html, f"trip-{ident}"))
            self.assertIn("£20,000 for 5", text, ident)
            self.assertIn("£5,000 for 5", text, ident)

    def test_the_html_stays_well_formed_with_both_cabins_at_every_budget(self):
        from test_trip_dossiers import WellFormedTests

        fares = _load([_row(t, "ECONOMY", 5_000) for t in WANTED] + [_row(t, "MIXED", 20_000) for t in WANTED])
        checker = WellFormedTests()
        for budget in (UNLIMITED, 90_000, 20_000):
            self.assertEqual(checker._unbalanced(_html(fares=fares, deals=_deals(3), budget=budget)), [], budget)


if __name__ == "__main__":
    unittest.main()
