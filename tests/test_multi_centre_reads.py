"""Two-centre trips, priced from the private reader's dated whole-trip fares.

Owner brief 2026-10-15. The July e-mail's "Two-centre trips" block showed a cost
RANGE per trip — Bali 7 nights + Lombok 7 nights, Khao Lak 7 + Koh Phangan 7 —
because no dated multi-city fare had ever been read for one, and the block said so
on every run. The private reader (`dealserach`'s `stopover_reads`) now writes a row
for a trip's own legs, with ``kind`` ``multi_centre`` and a ``trip`` id, into the
SAME ``stopover_reads/1`` batches the stopover fares ride.

These tests pin the four ways that seam can lie:

* a two-centre row polluting ``STOPOVER_FARES`` (it is a whole multi-city trip, not
  a two-night stopover, and its figure must not move a pair's median either);
* a fare borrowed from other dates — a read answers a trip only on the exact legs
  it was read for, the same rule a stopover fare answers only its own pair;
* a range silently becoming a quote, or a priced row losing the range it sits in;
* a header claiming no fare was readable after one was, or still saying so when one
  was not.

Everything here is SYNTHETIC and stamped so: fictional carriers, fares and URLs, and
no private evidence file is read. Both example configs are exercised because both
seasons render this block.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    MULTI_CENTRE_HEAD_NO_READ,
    MULTI_CENTRE_HEAD_PRICE_READ,
    _multi_centre_lines,
    _multi_centre_rows,
    multi_centre_wanted,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_batch_reads,
    load_holiday_config,
    multi_centre_fare_for,
    multi_centre_fares_registry,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
DECEMBER = ROOT / "examples" / "dec_holiday_config.json"
GENERATED_AT = "2026-10-15T00:00:00+00:00"

#: SYNTHETIC. A real-looking fare and read stamp, both invented, so a figure below
#: can never be mistaken for a read. The URL is ``example.invalid``: unresolvable
#: by design.
SYNTHETIC_TOTAL = 4182.0
SYNTHETIC_FIRST_READ_AT = "2026-10-15T09:30:00+00:00"
SYNTHETIC_SECOND_READ_AT = "2026-09-30T07:05:00+00:00"
SYNTHETIC_SOURCE = "https://example.invalid/SYNTHETIC-multi-city-read"
#: The day the read above was taken, as the row's own line prints it.
SYNTHETIC_READ_DAY = "15 Oct"
#: A ceiling that cards some resorts whatever the catalogue's own figure is.
SYNTHETIC_CEILING_GBP = 60000.0

#: The three shortlist winter pairs, for the stopover-side tests.
DECEMBER_PAIRS = (
    ("2026-12-17", "2026-12-25"),
    ("2026-12-20", "2026-12-28"),
    ("2026-12-23", "2026-12-31"),
)
KEPT_TOTALS = (4000.0, 4500.0, 5000.0)
KEPT_HUBS = ("AUH", "DOH", "DXB")
STOPOVER_OUTLIER_HUB = "MCT"
STOPOVER_OUTLIER_TOTAL = 28000.0


def _config(path=JULY, *, budget=SYNTHETIC_CEILING_GBP):
    config = load_holiday_config(path.read_text(encoding="utf-8"))
    return dataclasses.replace(config, max_budget_gbp=budget)


def _declared(config):
    """The trips the report asks to be read, in the private reader's own format."""
    return multi_centre_wanted(config)


def _trip(config):
    """One trip this config renders, as the ``--wanted`` row describes it."""
    declared = _declared(config)
    if not declared:  # pragma: no cover - both example configs render the block
        raise AssertionError("this config renders no two-centre trip at all")
    return declared[0]


def _multi_centre_read(want, *, total=SYNTHETIC_TOTAL, status="priced",
                       observed_at=SYNTHETIC_FIRST_READ_AT, source=SYNTHETIC_SOURCE,
                       travellers=5, season=None) -> dict:
    """One SYNTHETIC two-centre read, in the shape Part A writes it.

    The key order and the full key set (``kind``/``trip``/``legs`` on top of the
    stopover row's own) are the private reader's contract, so they are reproduced
    here rather than trimmed to what this test happens to need.
    """
    legs = [list(leg) for leg in want["legs"]]
    return {
        "pair": [legs[0][2], legs[-1][2]],
        "hub": "",
        "airport": "",
        "origin": "LHR",
        "legs": legs,
        "travellers": travellers,
        "cabin": "ECONOMY",
        "season": season or want["season"],
        "source_url": source,
        "observed_at": observed_at,
        "status": status,
        "total_gbp": total if status == "priced" else None,
        "price_basis_text": "entire trip",
        "carrier": "SYNTHETIC carrier",
        "stops": 1,
        "layovers": "",
        "duration": "16 hrs 40 min",
        "tab": "best",
        "note": "SYNTHETIC read",
        "kind": "multi_centre",
        "trip": want["trip"],
    }


def _stopover_read(pair, hub, airport, *, total, season="summer") -> dict:
    """One SYNTHETIC stopover read, in the shape the private export carries."""
    return {
        "pair": list(pair),
        "hub": hub,
        "airport": airport,
        "legs": [list(leg) for leg in hol.stopover_legs(hub, airport, pair[0], pair[1])],
        "origin": "LHR",
        "travellers": 5,
        "cabin": "ECONOMY",
        "season": season,
        "source_url": "https://example.invalid/SYNTHETIC-stopover",
        "observed_at": SYNTHETIC_FIRST_READ_AT,
        "status": "priced",
        "total_gbp": total,
        "price_basis_text": "entire trip",
        "carrier": "SYNTHETIC carrier",
    }


class _BatchCase(unittest.TestCase):
    """A temporary home for a ``stopover_reads/1`` batch, and the loader under test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

    def _write(self, rows, name="stopover_reads_synthetic.json") -> str:
        path = self.directory / name
        path.write_text(
            json.dumps({"schema": hol.STOPOVER_READS_SCHEMA, "rows": list(rows)}),
            encoding="utf-8",
        )
        return str(path)


class StopoverTableIsNeverPollutedTests(_BatchCase):
    """A two-centre row shares the file and shares nothing else."""

    def setUp(self):
        super().setUp()
        self.want = _trip(_config())
        self.pair = DECEMBER_PAIRS[0]
        self.stopover = _stopover_read(self.pair, "DOH", "ZNZ", total=4200.0)

    def test_the_stopover_loader_drops_multi_centre_rows(self):
        """The required half: one file, two kinds of row, one of them not a stopover."""
        path = self._write([self.stopover, _multi_centre_read(self.want)])

        loaded = hol.load_stopover_reads(path)
        self.assertEqual(loaded, (self.stopover,),
                         "a two-centre row reached the stopover rows")
        # ... while the same file still answers the two-centre question, so the
        # loader drops them rather than losing them.
        _stops, fares = load_batch_reads(path)
        self.assertEqual(multi_centre_fare_for(self.want["trip"], self.want["legs"],
                                               fares=fares)["total_gbp"], SYNTHETIC_TOTAL)

    def test_a_multi_centre_row_alone_produces_no_stopover_fare(self):
        """A whole-trip multi-city figure is not a two-night stopover's."""
        path = self._write([_multi_centre_read(self.want)])
        rows, _fares = load_batch_reads(path)
        self.assertEqual(rows, ())
        self.assertEqual(hol.consume_stopover_skip_log(), [],
                         "a well-formed two-centre row is not a skip")
        self.assertEqual(hol._stopover_fares(rows), {})

    def test_a_multi_centre_figure_cannot_move_a_stopover_pairs_median(self):
        """The real hazard: the median is per pair, so a whole-trip figure could hide a mis-read.

        Four stopover reads on one pair, the last a genuine mis-read at seven times
        the median of the other three; beside them a SYNTHETIC two-centre read on
        the SAME pair, whose figure is ten times bigger. If that figure entered the
        population the median would become the outlier's own value, nothing would
        look out of range, and the mis-read card would be quoted. So it is dropped
        BEFORE the median is taken, and the exclusion still names the MCT read.
        """
        rows = tuple(
            _stopover_read(self.pair, hub, "ZNZ", total=total, season="winter")
            for hub, total in zip(KEPT_HUBS, KEPT_TOTALS)
        ) + (
            _stopover_read(self.pair, STOPOVER_OUTLIER_HUB, "ZNZ",
                           total=STOPOVER_OUTLIER_TOTAL, season="winter"),
            _multi_centre_read(self.want, total=100_000.0, season="winter"),
        )
        hol.consume_stopover_skip_log()
        fares = hol._stopover_fares(rows)

        skipped = hol.consume_stopover_skip_log()
        self.assertEqual(len(skipped), 1, f"expected one exclusion, got {skipped}")
        self.assertIn(STOPOVER_OUTLIER_HUB, skipped[0])
        self.assertIn("median", skipped[0])
        self.assertEqual(
            sorted(float(fares[key][0]["total_gbp"]) for key in fares),
            sorted(KEPT_TOTALS),
            "the mis-read stopover card is still refused",
        )
        for key in fares:
            self.assertTrue(str(key[1]).strip() and str(key[2]).strip(),
                            f"a fare with no hub or airport reached the table: {key}")


class MultiCentreFareIndexTests(_BatchCase):
    """A fare answers the exact journey it was read for, and nothing else."""

    def setUp(self):
        super().setUp()
        self.config = _config()
        self.want = _trip(self.config)

    def _registry(self, rows):
        _stops, fares = load_batch_reads(self._write(rows))
        self.assertEqual(hol.consume_stopover_skip_log(), [])
        return fares

    def test_a_priced_read_answers_its_own_trip_and_its_own_legs(self):
        fares = self._registry([_multi_centre_read(self.want)])
        self.assertEqual(len(fares), 1)
        self.assertEqual(
            multi_centre_fare_for(self.want["trip"], self.want["legs"], fares=fares)["total_gbp"],
            SYNTHETIC_TOTAL,
        )
        self.assertEqual(multi_centre_fares_registry(fares), fares)

    def test_a_read_for_other_dates_is_never_borrowed(self):
        """The same rule a stopover fare answers only its own pair by."""
        fares = self._registry([_multi_centre_read(self.want)])
        shifted = [list(leg) for leg in self.want["legs"]]
        shifted[0][2] = "2027-06-28"          # one neighbouring pair, same airports
        self.assertIsNone(multi_centre_fare_for(self.want["trip"], shifted, fares=fares))
        self.assertIsNone(multi_centre_fare_for("another-trip", self.want["legs"], fares=fares))
        self.assertEqual(multi_centre_fare_for(self.want["trip"], self.want["legs"],
                                               fares=fares)["total_gbp"], SYNTHETIC_TOTAL)

    def test_the_cheapest_of_two_reads_for_one_journey_is_the_one_kept(self):
        """One journey is quoted once, at its cheapest look — the stopover rule."""
        dearer = _multi_centre_read(self.want, total=9000.0,
                                    observed_at=SYNTHETIC_SECOND_READ_AT)
        fares = self._registry([dearer, _multi_centre_read(self.want)])
        (fare,) = fares.values()
        self.assertEqual(float(fare["total_gbp"]), SYNTHETIC_TOTAL)
        self.assertEqual(fare["observed_at"], SYNTHETIC_FIRST_READ_AT)

    def test_an_unpriced_read_is_a_gap_and_not_a_fare(self):
        fares = self._registry([_multi_centre_read(self.want, status="no_priced_economy_card")])
        self.assertEqual(fares, {})
        self.assertIsNone(multi_centre_fare_for(self.want["trip"], self.want["legs"], fares=fares))

    def test_a_row_with_no_trip_or_broken_legs_is_named_rather_than_guessed(self):
        broken = _multi_centre_read(self.want)
        broken["trip"] = ""
        no_legs = _multi_centre_read(self.want)
        no_legs["legs"] = [["LHR", "DPS"]]
        _stops, fares = load_batch_reads(self._write([broken, no_legs]))
        skipped = hol.consume_stopover_skip_log()
        self.assertEqual(fares, {})
        self.assertEqual(len(skipped), 2, skipped)
        for message in skipped:
            self.assertIn("multi_centre", message)


class MultiCentreWantedTests(unittest.TestCase):
    """What the run asks to be read, in the reader's own input format."""

    def test_the_list_is_the_private_readers_wanted_input_format(self):
        for path in (JULY, DECEMBER):
            with self.subTest(config=path.name):
                wanted = _declared(_config(path))
                self.assertTrue(wanted)
                for row in wanted:
                    self.assertEqual(set(row), {"kind", "trip", "legs", "season"})
                    self.assertEqual(row["kind"], "multi_centre")
                    self.assertTrue(str(row["trip"]).strip())
                    self.assertIn(row["season"], ("summer", "winter"))
                    self.assertGreaterEqual(len(row["legs"]), 2)
                    self.assertLessEqual(len(row["legs"]), 6)
                    for origin, destination, day in row["legs"]:
                        self.assertRegex(origin, r"^[A-Z]{3}$")
                        self.assertRegex(destination, r"^[A-Z]{3}$")
                        self.assertRegex(day, r"^\d{4}-\d{2}-\d{2}$")

    def test_every_rendered_trip_is_listed_once_with_the_legs_its_row_shows(self):
        """The list is derived from the same rows the block renders, not guessed."""
        for path in (JULY, DECEMBER):
            with self.subTest(config=path.name):
                config = _config(path)
                rendered = _multi_centre_rows(config)
                wanted = _declared(config)
                self.assertEqual(len(wanted), len(rendered))
                self.assertEqual([row["trip"] for row in wanted],
                                 [row["trip"].id for row in rendered])
                self.assertEqual(
                    {tuple(tuple(leg) for leg in row["legs"]) for row in wanted},
                    {tuple(legs) for legs in (row["legs"] for row in rendered)},
                )
                # Each trip's legs are the trip's own airports on THIS run's pair.
                for row, source in zip(wanted, rendered):
                    self.assertEqual(row["legs"][0][2], source["outbound"])
                    self.assertEqual(row["legs"][-1][2], source["return"])

    def test_the_list_carries_no_fare_a_url_or_a_name(self):
        """This repository is PUBLIC: a trip id and its airports are all that may go in."""
        raw = json.dumps(_declared(_config()), sort_keys=True)
        for leaked in (SYNTHETIC_SOURCE, "http", "£", "GBP", "total", "observed_at"):
            self.assertNotIn(leaked, raw)
        self.assertNotIn("/home/", raw)

    def test_a_config_with_no_trip_in_season_is_asked_about_nothing(self):
        no_trips = _config(JULY)
        with patch("public_flight_search.holiday_email.load_multi_centre", return_value=[]):
            self.assertEqual(_declared(no_trips), [])


class MultiCentreRenderTests(unittest.TestCase):
    """The block: a range plus, where one was read, the dated fare."""

    def _render(self, config, fares):
        deals = collect_holiday_deals(config)
        return render_holiday_report_compact(
            config, generated_at=GENERATED_AT, deals=deals, multi_centre_fares=fares
        )

    def _text(self, config, fares):
        deals = collect_holiday_deals(config)
        return render_holiday_report_compact_text(
            config, generated_at=GENERATED_AT, deals=deals, multi_centre_fares=fares
        )

    def _fares(self, want):
        return {hol.multi_centre_fare_key(want["trip"], want["legs"]): _multi_centre_read(want)}

    def test_a_read_trip_shows_the_dated_fare_with_its_link(self):
        config = _config()
        want = _trip(config)
        html = self._render(config, self._fares(want))
        text = self._text(config, self._fares(want))
        line = f"flights £{SYNTHETIC_TOTAL:,.0f} for 5 (read {SYNTHETIC_READ_DAY})"
        self.assertIn(line, html)
        self.assertIn(line, text)
        # Linked to the page the fare was read from, not to the search link.
        self.assertIn(f'href="{SYNTHETIC_SOURCE}"', html)
        self.assertIn(SYNTHETIC_SOURCE, text)

    def test_the_range_beside_a_fare_is_unchanged_and_still_a_range(self):
        """A flight fare does not turn a whole-trip estimate into a quote."""
        config = _config()
        want = _trip(config)
        row = _multi_centre_rows(config, fares=self._fares(want))[0]
        html = self._render(config, self._fares(want))
        self.assertEqual(row["low"], row["trip"].cost_low_gbp)
        self.assertEqual(row["high"], row["trip"].cost_high_gbp)
        self.assertIn(f"£{row['low']:,.0f}–£{row['high']:,.0f}", html)
        self.assertIn(row["trip"].price_label(), html)
        self.assertNotIn("price:", html.lower())
        self.assertNotIn("quoted", html.lower())

    def test_only_the_trip_the_read_names_gains_a_fare(self):
        """One read prices one row, however many rows the block renders."""
        config = _config()
        wanted = _declared(config)
        self.assertGreater(len(wanted), 1, "this test needs more than one rendered trip")
        fares = self._fares(wanted[0])
        rows = _multi_centre_rows(config, fares=fares)
        self.assertEqual([bool(row["read"]) for row in rows],
                         [True] + [False] * (len(rows) - 1))
        html = self._render(config, fares)
        text = self._text(config, fares)
        self.assertEqual(html.count(f"flights £{SYNTHETIC_TOTAL:,.0f} for 5 (read "), 1)
        self.assertEqual(text.count(f"flights £{SYNTHETIC_TOTAL:,.0f} for 5 (read "), 1)
        # The unread trips still show their range and their own verdict.
        other = rows[1]
        self.assertIn(f"£{other['low']:,.0f}–£{other['high']:,.0f}", html)
        self.assertIn(other["trip"].why, html)

    def test_the_header_says_priced_where_shown_only_when_a_read_is_shown(self):
        config = _config()
        want = _trip(config)
        unpriced_html = self._render(config, {})
        unpriced_text = self._text(config, {})
        self.assertIn(MULTI_CENTRE_HEAD_NO_READ, unpriced_html)
        self.assertIn(MULTI_CENTRE_HEAD_NO_READ, unpriced_text)
        self.assertNotIn(MULTI_CENTRE_HEAD_PRICE_READ, unpriced_html)
        # The old claim is gone, and it is not left behind anywhere in the report.
        self.assertNotIn("no dated multi-city fare was readable", unpriced_html)
        self.assertNotIn("no dated multi-city fare was readable", unpriced_text)

        priced_html = self._render(config, self._fares(want))
        priced_text = self._text(config, self._fares(want))
        self.assertIn(MULTI_CENTRE_HEAD_PRICE_READ, priced_html)
        self.assertIn(MULTI_CENTRE_HEAD_PRICE_READ, priced_text)
        self.assertNotIn(MULTI_CENTRE_HEAD_NO_READ, priced_html)
        self.assertNotIn(MULTI_CENTRE_HEAD_NO_READ, priced_text)

    def test_a_read_for_another_pair_leaves_the_header_alone(self):
        """Never borrowed: the block must not claim a price it is not showing."""
        config = _config()
        want = _trip(config)
        shifted = [list(leg) for leg in want["legs"]]
        shifted[0][2] = "2027-06-28"
        elsewhere = {hol.multi_centre_fare_key(want["trip"], shifted):
                     _multi_centre_read(want)}
        html = self._render(config, elsewhere)
        self.assertIn(MULTI_CENTRE_HEAD_NO_READ, html)
        self.assertNotIn(MULTI_CENTRE_HEAD_PRICE_READ, html)
        self.assertNotIn(f"flights £{SYNTHETIC_TOTAL:,.0f} for 5", html)

    def test_the_priced_block_stays_inside_the_mail_byte_budget(self):
        """A read adds a line to every priced row, and the report must still fit.

        This is the Gmail clip guard applied to the new content: the block is
        rendered as part of the e-mail, so a fare line that pushed the report over
        ``EMAIL_HTML_BUDGET_BYTES`` would have cards dropped to make room for it.
        """
        for path in (JULY, DECEMBER):
            with self.subTest(config=path.name):
                config = _config(path)
                fares = {hol.multi_centre_fare_key(row["trip"], row["legs"]):
                         _multi_centre_read(row)
                         for row in _declared(config)}
                html = self._render(config, fares)
                size = len(html.encode("utf-8"))
                self.assertLessEqual(size, hol.EMAIL_HTML_BUDGET_BYTES)
                self.assertNotIn(
                    "not shown", html,
                    "the byte budget dropped a card to make room for a fare line",
                )

    def test_the_block_prices_from_the_registry_the_run_was_handed_and_no_other(self):
        """No module state, no file, no fallback: a render prices only what it was given."""
        config = _config()
        want = _trip(config)
        self.assertIsNone(multi_centre_fare_for(want["trip"], want["legs"]))
        self.assertEqual(multi_centre_fares_registry(), {})
        html = self._render(config, {})
        self.assertNotIn(f"flights £{SYNTHETIC_TOTAL:,.0f} for 5", html)
        lines = _multi_centre_lines(config)
        self.assertTrue(lines)
        self.assertNotIn("read ", " ".join(lines))


class RunWiringTests(unittest.TestCase):
    """The job hands the renderer the run's reads, and reports what to read next."""

    #: Absent evidence paths, so a checkout with private data on it is a different
    #: machine from this test (the same rule ``test_jobs`` uses).
    def _paths(self, batch):
        return {
            "hotel_evidence_path": str(self.directory / "absent-hotel.json"),
            "live_evidence_path": str(self.directory / "absent-live.json"),
            "package_evidence_path": str(self.directory / "absent-package.json"),
            "stopover_reads_path": batch,
        }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        (self.directory / "no-batch.json").write_text(
            json.dumps({"schema": hol.STOPOVER_READS_SCHEMA, "rows": []}), encoding="utf-8"
        )
        self.payload = DECEMBER.read_text(encoding="utf-8")

    def _run(self, batch):
        from public_flight_search.jobs import run_holiday_planner

        stdout = io.StringIO()
        with patch.dict(os.environ, {"HOLIDAY_SEARCH_CONFIG_JSON": self.payload}, clear=True):
            with contextlib.redirect_stdout(stdout):
                result = run_holiday_planner(dry_run=True, **self._paths(batch))
        return result, stdout.getvalue()

    def test_the_run_prints_and_reports_what_to_read_next(self):
        result, printed = self._run(str(self.directory / "no-batch.json"))
        config = load_holiday_config(self.payload)
        wanted = multi_centre_wanted(config)
        self.assertTrue(wanted)
        self.assertEqual(result["multi_centre_wanted"], wanted)
        self.assertIn(f"multi_centre_wanted: {len(wanted)}", printed)
        # Nothing was read, so nothing is priced.
        self.assertEqual(result["multi_centre_reads_loaded"], 0)

    def test_a_priced_batch_reaches_the_run_that_loaded_it(self):
        config = load_holiday_config(self.payload)
        want = multi_centre_wanted(config)[0]
        batch = self.directory / "stopover_reads_synthetic.json"
        batch.write_text(
            json.dumps({"schema": hol.STOPOVER_READS_SCHEMA,
                        "rows": [_multi_centre_read(want)]}),
            encoding="utf-8",
        )
        result, printed = self._run(str(batch))
        self.assertEqual(result["multi_centre_reads_loaded"], 1)
        self.assertEqual(result["stopover_reads_loaded"], 0,
                         "a two-centre row counted as a stopover read")
        self.assertIn(f"multi_centre_wanted: {len(multi_centre_wanted(config))}", printed)


if __name__ == "__main__":
    unittest.main()
