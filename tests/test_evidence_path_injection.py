"""The suite must give the same answer with or without ``data/`` present.

CI has no ``data/holiday_live_evidence.json``; an operator's checkout does,
because the workflow seeds the private engine's export there. Two tests read
the DEFAULT evidence path, so on such a checkout they consumed real evidence
and failed while CI stayed green:

* ``test_http_path_returns_no_evidence_rather_than_a_derived_figure`` — called
  ``try_live_flight_offers(config)`` with no ``path``, so the decoy's records
  were loaded and the honest "no evidence" answer became a priced deal;
* ``test_an_ancient_observation_is_dropped_outright`` — asserted on the
  MODULE-GLOBAL ``_SKIP_LOG``, which the default-path call above had already
  filled, so ``skip_log()[0]`` was the decoy's reason, not its own.

The fix is two-fold and both halves are pinned here: every test passes an
explicit path, and a skip log belongs to ONE load rather than accumulating
across the process.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from public_flight_search import live_verify
from public_flight_search.live_verify import (
    consume_skip_log,
    try_live_flight_offers,
)

CONFIG_JSON = """
{
  "report_title": "Path injection test",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2026-12-22"],
  "return_dates": ["2026-12-30"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"], "flight_hours": 4.5}
  ]
}
"""

#: A record shaped so it WOULD be accepted for the config above: right
#: airport, right priced pair, right origin, right party, whole-party basis.
#: Its whole purpose is to be accepted, so that any test reading the default
#: path has something to trip over.
DECOY_RECORD = {
    "airport": "AYT",
    "cabin": "ECONOMY",
    "total_gbp": 1234.5,
    "basis": "whole_party_return_total",
    "source_url": "https://example.invalid/decoy",
    "observed_at": "2026-10-03T00:00:00+00:00",
    "exact_dates": {"outbound": "2026-12-22", "return": "2026-12-30"},
    "origin": "LHR",
    "travellers": 5,
}

#: A second decoy record that is NOT acceptable — its dates are not a priced
#: pair. It exists to leave a skip reason behind, because the defect is not
#: only that the decoy prices a deal: a rejected decoy record still writes to
#: the module-global skip log, and that is what corrupted the dated-pair test.
DECOY_REJECTED_RECORD = {
    **DECOY_RECORD,
    "source_url": "https://example.invalid/decoy-rejected",
    "exact_dates": {"outbound": "2030-01-01", "return": "2030-01-08"},
}


#: The committed December example, used when a test needs a run rather than a
#: bare loader.
CONFIG_PATH = str(Path(__file__).parents[1] / "examples" / "dec_holiday_config.json")


@contextmanager
def decoy_data_file():
    """Write ``data/holiday_live_evidence.json`` in a scratch cwd.

    Returns the path. The caller must not care whether it exists: that is the
    property under test.
    """
    original = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            path = data_dir / "holiday_live_evidence.json"
            path.write_text(
                json.dumps(
                    {"evidence": [DECOY_RECORD, DECOY_REJECTED_RECORD]}
                ),
                encoding="utf-8",
            )
            yield str(path)
        finally:
            os.chdir(original)


#: A decoy hotel rate, shaped so the loader WOULD accept it: right property,
#: right exact dates, right party, one booking. Its purpose is to be accepted,
#: so that any run reading the default path has something real to pick up.
DECOY_HOTEL_RATE = {
    "property": "Concorde De Luxe Resort",
    "check_in": "2026-12-20",
    "check_out": "2026-12-28",
    "cheapest": {
        "nightly_gbp": 1.0,
        "basis": "two_rooms_one_booking",
        "rooms": 2,
        "party": 5,
        "source_url": "https://example.invalid/decoy-hotel",
    },
}


@contextmanager
def decoy_data_dir():
    """A scratch cwd holding BOTH decoy evidence files.

    The job's default paths are CWD-relative, so a checkout with ``data/``
    seeded by the workflow is a different machine from CI. This puts the two
    files exactly where an operator's would be.
    """
    original = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "holiday_live_evidence.json").write_text(
                json.dumps({"evidence": [DECOY_RECORD]}), encoding="utf-8"
            )
            (data_dir / "holiday_hotel_evidence.json").write_text(
                json.dumps({"schema": "hotel_evidence/v1", "travellers": 5,
                            "rates": [DECOY_HOTEL_RATE]}),
                encoding="utf-8",
            )
            yield str(data_dir)
        finally:
            os.chdir(original)


class TestNoDefaultPathInTests(unittest.TestCase):
    """The default path must be used only by the job, never by a test."""

    def test_a_load_is_satisfied_by_an_explicit_path_only(self):
        """The decoy on disk must not reach a load that named its own path.

        This is the property that keeps CI and an operator's checkout
        reporting the same thing: the outcome is a function of the path the
        caller passed, not of whatever happens to sit in ``data/``.
        """
        from public_flight_search.holidays import load_holiday_config

        config = load_holiday_config(CONFIG_JSON)
        with decoy_data_file():
            with tempfile.TemporaryDirectory() as tmp:
                empty = os.path.join(tmp, "absent.json")
                offers = try_live_flight_offers(
                    config,
                    path=empty,
                    now=datetime.fromisoformat("2026-10-03T06:00:00+00:00"),
                )
        self.assertEqual(
            dict(offers),
            {},
            "an explicit absent path must yield no evidence even when "
            "data/holiday_live_evidence.json holds an acceptable record",
        )

    def test_the_default_path_still_works_for_the_job(self):
        """Injection must not have been 'delete the default'.

        The workflow seeds the export at this exact path and passes nothing,
        so the default has to keep working for a real run.
        """
        from public_flight_search.holidays import load_holiday_config

        config = load_holiday_config(CONFIG_JSON)
        with decoy_data_file():
            offers = try_live_flight_offers(
                config, now=datetime.fromisoformat("2026-10-03T06:00:00+00:00")
            )
        self.assertEqual(
            sorted(tuple(key[:2]) for key in offers),
            [("AYT", "ECONOMY")],
            "the seeded default path must still be honoured on a real run",
        )


class TestHotelEvidencePathIsInjectedToo(unittest.TestCase):
    """R5: the HOTEL evidence path must be injectable the same way.

    The live half was fixed above and the hotel half was not, so every
    planner test that did not name a path silently read whatever an operator's
    checkout happened to seed into ``data/``. Both paths are the same seam and
    must be pinnable independently.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _absent(self, name: str) -> str:
        return os.path.join(self._tmp.name, name)

    def test_the_default_path_is_still_reachable(self):
        """The hazard must be real, or the tests below prove nothing.

        A test that cannot fail is not evidence. If the decoy were never read,
        "the suite ignores it" would be vacuous.
        """
        from public_flight_search.jobs import run_holiday_planner

        with decoy_data_dir():
            result = run_holiday_planner(
                dry_run=True, config_path=CONFIG_PATH
            )
        self.assertTrue(result["hotel_evidence_file_found"])
        self.assertTrue(result["live_evidence_file_found"])

    def test_named_paths_win_over_the_decoy_data_dir(self):
        """What every test must do: name where the evidence is.

        Passes now because both loaders and the job's env seam already accept a
        path. What it pins is that naming one is enough — the CWD-relative
        default is not consulted as a fallback once a path is given.
        """
        from public_flight_search.jobs import run_holiday_planner

        with decoy_data_dir():
            result = run_holiday_planner(
                dry_run=True,
                config_path=CONFIG_PATH,
                hotel_evidence_path=self._absent("no-hotel.json"),
                live_evidence_path=self._absent("no-live.json"),
            )
        self.assertFalse(result["hotel_evidence_file_found"])
        self.assertFalse(result["live_evidence_file_found"])
        self.assertIsNone(result["hotel_evidence_load_error"])
        self.assertIsNone(result["live_evidence_load_error"])

    def test_the_run_is_identical_with_and_without_the_decoys(self):
        """Same result with or without data/: the property in one comparison."""
        from public_flight_search.jobs import run_holiday_planner

        def _run() -> dict:
            return run_holiday_planner(
                dry_run=True,
                config_path=CONFIG_PATH,
                hotel_evidence_path=self._absent("no-hotel.json"),
                live_evidence_path=self._absent("no-live.json"),
            )

        clean = _run()
        with decoy_data_dir():
            decoyed = _run()
        for key in (
            "deal_count",
            "destination_count",
            "date_combination_count",
            "provider_entry_count",
            "hotel_rate_properties",
            "hotel_rates_priced_cards",
            "live_evidence_record_count",
            "live_evidence_missing_keys",
        ):
            with self.subTest(key=key):
                self.assertEqual(clean[key], decoyed[key])

    def test_a_planner_test_can_name_its_paths_as_arguments(self):
        """Parameters, not only environment variables.

        ``patch.dict(os.environ, ..., clear=True)`` is how these tests pin
        every other input, and it is silent about a path nobody thought to
        set. Naming the two evidence paths in the call is the only way the
        omission becomes visible at the call site.
        """
        import inspect

        from public_flight_search.jobs import run_holiday_planner

        parameters = inspect.signature(run_holiday_planner).parameters
        for name in ("hotel_evidence_path", "live_evidence_path"):
            with self.subTest(parameter=name):
                self.assertIn(name, parameters)


class TestSkipLogIsScopedToOneLoad(unittest.TestCase):
    """``_SKIP_LOG`` is module-global; it must not accumulate across loads."""

    def setUp(self):
        from public_flight_search.holidays import load_holiday_config

        self.config = load_holiday_config(CONFIG_JSON)
        self.now = datetime.fromisoformat("2026-10-03T06:00:00+00:00")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Never inherit another test's log state.
        consume_skip_log()
        self.addCleanup(consume_skip_log)

    def _write(self, records):
        path = os.path.join(self._tmp.name, "evidence.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"evidence": records}, handle)
        return path

    def _expired_record(self):
        return {
            "airport": "AYT",
            "total_gbp": 2000.0,
            "basis": "whole_party_return_total",
            "source_url": "https://example.invalid/search",
            # Well past EVIDENCE_STALE_CACHE_MAX_AGE_HOURS (720h).
            "observed_at": "2026-08-01T12:00:00+00:00",
            "exact_dates": {"outbound": "2026-12-22", "return": "2026-12-30"},
            "travellers": 5,
        }

    def test_skip_log_holds_only_the_most_recent_load(self):
        """Two loads, two reasons — the second must not see the first.

        A load that appends to a log the caller has to drain afterwards is
        only safe if it clears it first. Otherwise a report runs the loader
        for a December season after a July one and an operator reads the
        previous season's skip reasons as this run's.
        """
        self.assertEqual(consume_skip_log(), [], "log must start empty")

        first = self._write([self._expired_record()])
        try_live_flight_offers(self.config, path=first, now=self.now)

        # NOTE: deliberately NOT draining here. The second load must clear the
        # log itself; draining by hand is exactly what the test suite was
        # doing to paper over the defect, and it is why the leak survived.
        accepted = self._write(
            [
                {
                    **self._expired_record(),
                    "observed_at": "2026-10-03T00:00:00+00:00",
                }
            ]
        )
        offers = try_live_flight_offers(self.config, path=accepted, now=self.now)
        self.assertEqual(len(offers), 1, "sanity: the fresh record is accepted")
        self.assertEqual(
            consume_skip_log(),
            [],
            "a load that skipped nothing must report no skips, whatever ran "
            "before it in this process",
        )

    def test_the_decoy_cannot_reach_a_test_that_named_its_own_path(self):
        """The exact two-test interaction that made CI green and local red.

        ``test_http_path_returns_no_evidence_rather_than_a_derived_figure``
        used to call the loader with no path, loading the decoy. That call
        also left the decoy's skip reason at the head of the global log,
        which the dated-pair test then read as its own reason.
        """
        with decoy_data_file():
            # The decoy load, with no path passed — the historical defect.
            try_live_flight_offers(
                self.config, now=datetime.fromisoformat("2026-10-03T06:00:00+00:00")
            )

            # The dated-pair test's own load, with its own explicit path.
            expired = self._write([self._expired_record()])
            self.assertEqual(
                dict(try_live_flight_offers(self.config, path=expired, now=self.now)),
                {},
            )
            self.assertIn(
                "expired",
                consume_skip_log()[0],
                "the reason at the head of the log must be this load's, not a "
                "rejected record left behind by an earlier default-path load",
            )


class TestDefaultPathConstantIsUnchanged(unittest.TestCase):
    def test_the_documented_default_is_the_seeded_workflow_path(self):
        # Changed carelessly, the workflow seeds a file nothing reads.
        self.assertEqual(
            live_verify.DEFAULT_EVIDENCE_PATH, "data/holiday_live_evidence.json"
        )


if __name__ == "__main__":
    unittest.main()