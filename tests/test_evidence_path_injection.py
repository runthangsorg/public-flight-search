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