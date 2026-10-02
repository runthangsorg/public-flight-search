"""T8: the July planner must not log a line per December record.

The July run loads an evidence file that also holds December observations. Every
one of them failed the "dates do not match a priced pair" check and printed a
line, so a July run produced ~300 of them. Records for another season are
skipped before the per-record loop and reported as ONE summary count.

A record for THIS season whose dates are genuinely wrong is a real signal and
must still be logged individually.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr

from public_flight_search.holidays import load_holiday_config
from public_flight_search.live_verify import (
    consume_skip_log,
    load_live_flight_evidence,
)

JULY_CONFIG = """
{
  "report_title": "July Summer Holiday Packages",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "khao_lak", "label": "Khao Lak", "airports": ["HKT"], "flight_hours": 11.0}
  ]
}
"""

DEC_CONFIG = """
{
  "report_title": "December Winter Holiday Packages",
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


def _rec(airport: str, outbound: str, returning: str) -> dict:
    return {
        "airport": airport,
        "total_gbp": 2000.0,
        "basis": "whole_party_return_total",
        "source_url": "https://example.invalid/search",
        "observed_at": "2026-09-21T00:00:00+00:00",
        "exact_dates": {"outbound": outbound, "return": returning},
        "travellers": 5,
    }


class OtherSeasonNoiseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        consume_skip_log()

    def tearDown(self):
        self._tmp.cleanup()
        consume_skip_log()

    def _write(self, records) -> str:
        path = os.path.join(self._tmp.name, "evidence.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"travellers": 5, "evidence": records}, handle)
        return path

    def test_a_july_run_does_not_log_a_line_per_december_record(self):
        config = load_holiday_config(JULY_CONFIG)
        # Many December records — the July run must not print one line each.
        records = [
            _rec("ACE", f"2026-12-{day:02d}", f"2026-12-{day + 7:02d}")
            for day in (2, 9, 16, 23)
        ]
        path = self._write(records)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            load_live_flight_evidence(config, path=path)
        skips = consume_skip_log()
        # No per-record "dates do not match" noise for the other season.
        self.assertEqual([s for s in skips if "do not match" in s], [])
        # And it is reported as one summary, not silence.
        self.assertIn("other season", stderr.getvalue())
        self.assertIn("4", stderr.getvalue())

    def test_a_same_season_wrong_date_is_still_logged_individually(self):
        # A real signal: this season, wrong dates. It must still surface.
        config = load_holiday_config(JULY_CONFIG)
        path = self._write([_rec("HKT", "2027-07-21", "2027-07-28")])
        with redirect_stderr(io.StringIO()):
            load_live_flight_evidence(config, path=path)
        skips = consume_skip_log()
        self.assertTrue(
            any("do not match" in s for s in skips),
            f"a same-season date mismatch must still be logged, got {skips}",
        )

    def test_a_december_run_still_consumes_a_december_record(self):
        config = load_holiday_config(DEC_CONFIG)
        path = self._write([_rec("AYT", "2026-12-22", "2026-12-30")])
        with redirect_stderr(io.StringIO()):
            offers = load_live_flight_evidence(config, path=path)
        self.assertIn(("AYT", "ECONOMY"), {tuple(k[:2]) for k in offers})
        self.assertEqual([s for s in consume_skip_log() if "do not match" in s], [])


if __name__ == "__main__":
    unittest.main()
