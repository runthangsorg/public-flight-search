"""The 3x-median rule runs on the loaded exports too, not just the committed tuple.

Owner brief 2026-10-05 (H13). `_STOPOVER_READS` has always been curated by hand
against one rule — a read more than three times its own pair's median is a
mis-read card, not an option worth showing — and H11's test holds the committed
tuple to it. The runtime loader took every priced row it found, so seeding the
private exports into a live run (H13 §1) would have let exactly the reads the
committed tuple refuses back in.

The rule therefore lives in one function, called by the one place that turns
reads into fares, so the committed tuple and the loaded exports cannot diverge,
and each excluded read is recorded in the same skip list the loader's other
refusals go to — which is what the run summary reports.

Every figure here is synthetic and stamped SYNTHETIC, so it can never be
mistaken for a read; nothing in this file reads a private evidence file.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

import public_flight_search.holidays as hol
from public_flight_search.holidays import collect_holiday_deals, load_holiday_config

ROOT = Path(__file__).parents[1]
DECEMBER = ROOT / "examples" / "dec_holiday_config.json"

#: The three shortlist winter pairs, as the December config prices them.
DECEMBER_PAIRS = (
    ("2026-12-17", "2026-12-25"),
    ("2026-12-20", "2026-12-28"),
    ("2026-12-23", "2026-12-31"),
)
#: Synthetic fares on one pair, shaped so the outlier is unmistakable: three
#: reads around GBP 4,000-5,000 and one at more than six times the median.
KEPT_TOTALS = (4000.0, 4500.0, 5000.0)
OUTLIER_TOTAL = 28000.0
KEPT_HUBS = ("AUH", "DOH", "DXB")
OUTLIER_HUB = "MCT"
ZANZIBAR = "ZNZ"
#: The fixture's own ceiling, so a card is built whatever the catalogue says.
SYNTHETIC_CEILING_GBP = 90000.0


def _read(pair, hub, airport, *, total=5000.0, status="priced", season="winter",
          carrier="SYNTHETIC carrier", observed_at="synthetic") -> dict:
    """One stopover read row, in the shape the private export carries."""
    return {
        "pair": list(pair),
        "hub": hub,
        "airport": airport,
        "total_gbp": total,
        "carrier": carrier,
        "status": status,
        "observed_at": observed_at,
        "season": season,
        "source_url": "",
    }


def _winter_reads(pair, *, extra: tuple = ()) -> tuple:
    """Three priced winter reads for `pair`, plus any extra rows."""
    rows = [
        _read(pair, hub, ZANZIBAR, total=total)
        for hub, total in zip(KEPT_HUBS, KEPT_TOTALS)
    ]
    return tuple(rows) + tuple(extra)


def _export(rows, directory: Path, name: str = "stopover_reads_synthetic.json") -> str:
    """Write a `stopover_reads/1` document and return its path."""
    path = directory / name
    path.write_text(
        json.dumps({"schema": hol.STOPOVER_READS_SCHEMA, "rows": list(rows)}),
        encoding="utf-8",
    )
    return str(path)


def _fares(reads) -> dict:
    """The fares those reads produce, with the skip log drained first."""
    hol.consume_stopover_skip_log()
    return hol._stopover_fares(tuple(reads))


class LoadedExportOutlierTests(unittest.TestCase):
    """A loaded export is filtered by the same rule as the committed tuple."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.pair = DECEMBER_PAIRS[0]
        self.rows = _winter_reads(
            self.pair,
            extra=(_read(self.pair, OUTLIER_HUB, ZANZIBAR, total=OUTLIER_TOTAL),),
        )

    def test_a_loaded_export_drops_only_its_outlier(self):
        path = _export(self.rows, self.directory)

        # The LOADER keeps every priced row: refusing a read is the fare
        # table's decision, not the file reader's, so the skip is recorded once
        # and in one place.
        loaded = hol.load_stopover_reads(path)
        self.assertEqual(len(loaded), len(self.rows))

        fares = _fares(loaded)
        self.assertEqual(
            sorted(float(fares[key][0]["total_gbp"]) for key in fares),
            sorted(KEPT_TOTALS),
            "a loaded export must keep every read that is not an outlier",
        )
        self.assertNotIn((self.pair, OUTLIER_HUB, ZANZIBAR), fares)

    def test_an_excluded_read_is_named_in_the_runs_skip_list(self):
        hol.load_stopover_reads(_export(self.rows, self.directory))
        hol.consume_stopover_skip_log()
        _fares(self.rows)

        skipped = hol.consume_stopover_skip_log()
        self.assertEqual(len(skipped), 1, f"expected one exclusion, got {skipped}")
        message = skipped[0]
        self.assertIn(OUTLIER_HUB, message)
        self.assertIn(ZANZIBAR, message)
        self.assertIn(self.pair[0], message)
        # The reason quotes the rule that excluded it, so an operator reading
        # the summary can tell a mis-read card from an unreadable file.
        self.assertIn("median", message)

    def test_a_pair_with_one_read_is_never_its_own_outlier(self):
        # One read is its pair's median, so the rule cannot refuse it. A short
        # pair (one hub answered, or an export of one row) must still price.
        fares = _fares([_read(self.pair, "DOH", ZANZIBAR, total=9999.0)])
        self.assertEqual(len(fares), 1)
        self.assertEqual(hol.consume_stopover_skip_log(), [])

    def test_a_read_that_came_back_without_a_fare_is_a_gap_not_an_outlier(self):
        # Only priced rows with a total take part in the median, and an
        # unanswered read is refused as a fare either way.
        rows = (
            _read(self.pair, "AUH", ZANZIBAR, total=4000.0,
                  status="no_priced_economy_card"),
            _read(self.pair, "DOH", ZANZIBAR, total=4500.0),
            _read(self.pair, "DXB", ZANZIBAR, total=5000.0),
            _read(self.pair, OUTLIER_HUB, ZANZIBAR, total=OUTLIER_TOTAL),
        )
        fares = _fares(rows)
        self.assertEqual(
            sorted(float(fares[key][0]["total_gbp"]) for key in fares),
            [4500.0, 5000.0],
        )
        self.assertEqual(len(hol.consume_stopover_skip_log()), 1)


class CommittedTupleGoesThroughTheSameRuleTests(unittest.TestCase):
    """The committed table is the other caller of the one filter."""

    def test_the_committed_reads_survive_the_rule_the_exports_are_held_to(self):
        kept, excluded = hol._without_stopover_outliers(hol._STOPOVER_READS)
        self.assertEqual(
            excluded, [],
            "the committed tuple is no longer inside the rule that filters exports",
        )
        self.assertEqual(len(kept), len(hol._STOPOVER_READS))
        # ...and the module's own table is what the same function produced, so
        # H11's assertion is belt to these braces rather than the only gate.
        self.assertEqual(len(hol._stopover_fares(hol._STOPOVER_READS)), len(hol.STOPOVER_FARES))

    def test_an_outlier_in_the_committed_tuple_is_refused_too(self):
        rows = tuple(
            dict(row, season="summer") for row in _winter_reads(
                DECEMBER_PAIRS[0],
                extra=(_read(DECEMBER_PAIRS[0], OUTLIER_HUB, ZANZIBAR,
                             total=OUTLIER_TOTAL),),
            )
        )
        hol.consume_stopover_skip_log()
        saved = hol._STOPOVER_READS
        hol._STOPOVER_READS = rows
        try:
            fares = hol._stopover_fares()
        finally:
            hol._STOPOVER_READS = saved
        self.assertNotIn((DECEMBER_PAIRS[0], OUTLIER_HUB, ZANZIBAR), fares)
        self.assertEqual(len(fares), 3)
        self.assertEqual(len(hol.consume_stopover_skip_log()), 1)


class DecemberSeasonReadTests(unittest.TestCase):
    """A winter read prices a December card, and prices nothing else."""

    def setUp(self):
        self.config = load_holiday_config(DECEMBER.read_text(encoding="utf-8"))
        self.config = dataclasses.replace(
            self.config, max_budget_gbp=SYNTHETIC_CEILING_GBP
        )
        self.deals = collect_holiday_deals(self.config)
        self.zanzibar = [
            deal for deal in self.deals if deal.destination_airport == ZANZIBAR
        ]
        self.assertTrue(self.zanzibar, "no December card for a Zanzibar resort")
        self.pair = (self.zanzibar[0].outbound_date, self.zanzibar[0].return_date)
        self.assertIn(self.pair, DECEMBER_PAIRS)

    def test_a_winter_read_prices_the_december_card_it_was_read_for(self):
        deals = collect_holiday_deals(
            self.config, stopover_reads=_winter_reads(self.pair)
        )
        # The read economy multi-city fare is the priced row; the Premium
        # Economy row beside it is that read x1.6, an estimate, and is checked
        # as such so neither is mistaken for the other.
        priced = [
            option for deal in deals for option in deal.flight_options
            if str(option.get("kind", "")) == "stopover"
        ]
        self.assertTrue(priced, "a winter read for a card's own pair priced nothing")
        for option in priced:
            self.assertEqual((option["outbound"], option["return"]), self.pair)
            self.assertEqual(option["cabin"], "ECONOMY")
            self.assertIn(float(option["flight_cost"]), KEPT_TOTALS)
        estimated = [
            option for deal in deals for option in deal.flight_options
            if str(option.get("kind", "")) == "stopover_premium_economy"
        ]
        for option in estimated:
            self.assertIn(
                round(float(option["flight_cost"]) / 1.6, 2), KEPT_TOTALS,
                "the Premium Economy row must be that read x1.6, never a read of its own",
            )
            self.assertEqual((option["outbound"], option["return"]), self.pair)

    def test_a_summer_read_never_prices_a_december_card(self):
        deals = collect_holiday_deals(self.config, stopover_reads=tuple(
            dict(row, season="summer") for row in _winter_reads(self.pair)
        ))
        self.assertTrue(deals, "the December config produced no cards at all")
        self.assertEqual(
            [
                option for deal in deals for option in deal.flight_options
                if str(option.get("kind", "")).startswith("stopover")
            ],
            [],
            "a summer read reached a December card",
        )

    def test_an_outlier_never_prices_a_card_either(self):
        deals = collect_holiday_deals(self.config, stopover_reads=_winter_reads(
            self.pair,
            extra=(_read(self.pair, OUTLIER_HUB, ZANZIBAR, total=OUTLIER_TOTAL),),
        ))
        priced = [
            option for deal in deals for option in deal.flight_options
            if str(option.get("kind", "")).startswith("stopover")
        ]
        self.assertTrue(priced)
        for option in priced:
            self.assertNotEqual(float(option["flight_cost"]), OUTLIER_TOTAL)


if __name__ == "__main__":
    unittest.main()
