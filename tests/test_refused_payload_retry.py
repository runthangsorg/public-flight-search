"""Google's error notice in place of results is read once more (21 Nov 2026).

The daily business watcher counted 26 to 46 of its 72 searches a day as "no itinerary" because Google answered
with its error notice, and nothing read them again; the same search read half a minute later priced. A refused
search now gets one more read, for a bounded number of searches a run, and the summary says how many were
refused, read again and recovered. Pages and fares here are synthetic."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from public_flight_search import business_deals as bd
from public_flight_search import weekly_fares as wf
from public_flight_search.holidays import load_holiday_config

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
DEP = "2027-03-01"
REFUSED = ('<html><head><title>A to B | Google Flights</title></head><body><script class="ds:1">'
           'AF_initDataCallback({data:' + json.dumps([None, None, [["no flights found"]]])
           + ',errorHasStatus: true});</script></body></html>')
RESULTS = "<html><body>results</body></html>"
OFFER = {"origin": "LHR", "destination": "BKK", "departure": f"{DEP}T09:00:00", "price": 1500.0, "currency": "GBP",
         "stops": 0, "duration_minutes": 700, "provider": "Google Flights", "booking_url": "https://example.test/f",
         "airline": "Test Air"}


def config():
    return bd.load_config({
        "origins": [{"code": "LHR", "label": "London Heathrow", "positioning_gbp": 0, "home": True}],
        "destinations": [{"code": "BKK", "label": "Bangkok", "region": "asia", "hours_from_london": 11.5}],
        "dates": [DEP, "2027-03-08"], "min_observations": 5, "absolute_caps_gbp": {"asia": 1000},
    }, today=NOW.date())


def parse_by_page(page, *, tally=None, **_):
    """Stand in for the card parser: a refused page marks the tally, a results page gives one offer."""
    if page == REFUSED:
        tally["payload_refused_error"] = 1
        return []
    return [OFFER]


class BusinessWatcherRetryTests(unittest.TestCase):
    SPEC = bd.SearchSpec("LHR", "BKK", DEP, "2027-03-15")

    def fetch(self, pages, **env):
        with patch("public_flight_search.google_flights._fetch_page_html", side_effect=list(pages)) as read, \
                patch("public_flight_search.google_flights._parse_flight_cards", side_effect=parse_by_page), \
                patch("public_flight_search.business_deals.time.sleep") as waited, \
                patch.dict(os.environ, env):
            outcome = bd.make_google_fetch(config())(self.SPEC)
        return outcome, read.call_count, [call.args[0] for call in waited.call_args_list]

    def test_a_refused_search_that_prices_on_the_second_read_is_recovered(self):
        outcome, reads, waits = self.fetch([REFUSED, RESULTS])
        self.assertEqual((outcome.status, len(outcome.offers), reads), ("ok", 1, 2))
        self.assertEqual((outcome.tally[bd.REFUSED_RETRIED], outcome.tally[bd.REFUSED_RECOVERED]), (1, 1))
        self.assertEqual(len(waits), 1)
        self.assertTrue(bd.REFUSED_RETRY_WAIT_SECONDS[0] <= waits[0] <= bd.REFUSED_RETRY_WAIT_SECONDS[1])

    def test_a_search_refused_twice_is_read_no_third_time(self):
        outcome, reads, _ = self.fetch([REFUSED, REFUSED, RESULTS])
        self.assertEqual((list(outcome.offers), reads), ([], 2))
        tally = outcome.page_note["tally"]
        self.assertEqual((tally.get("payload_refused_error"), tally.get(bd.REFUSED_RETRIED)), (1, 1))
        self.assertNotIn(bd.REFUSED_RECOVERED, tally)

    def test_a_priced_search_is_read_once(self):
        outcome, reads, waits = self.fetch([RESULTS])
        self.assertEqual((len(outcome.offers), reads, waits), (1, 1, []))
        self.assertNotIn(bd.REFUSED_RETRIED, outcome.tally)

    def test_the_run_stops_reading_again_once_its_allowance_is_spent(self):
        outcome, reads, waits = self.fetch([REFUSED, RESULTS], GOOGLE_FLIGHTS_REFUSED_RETRIES="0")
        self.assertEqual((list(outcome.offers), reads, waits), ([], 1, []))

    def test_a_wall_on_the_second_read_is_a_wall_and_is_left_alone(self):
        with patch("public_flight_search.google_flights._is_waf_response", side_effect=[False, True]):
            outcome, reads, _ = self.fetch([REFUSED, "challenge"])
        self.assertEqual((outcome.status, reads), ("wall", 2))
        self.assertEqual(outcome.tally, {bd.REFUSED_RETRIED: 1})

    def test_the_allowance_keeps_the_daily_job_inside_its_time_limit(self):
        workflow = (ROOT / ".github" / "workflows" / "business-deals.yml").read_text(encoding="utf-8")
        self.assertIn("timeout-minutes: 35", workflow)
        worst_extra_minutes = bd.REFUSED_RETRIES_PER_RUN * (bd.REFUSED_RETRY_WAIT_SECONDS[1] + 5) / 60
        self.assertLess(17 + worst_extra_minutes, 35 - 4)

    def test_the_summary_line_counts_refused_read_again_and_recovered(self):
        refused = bd.FetchOutcome("ok", [], page_note={"tally": {"payload_refused_error": 1, bd.REFUSED_RETRIED: 1}})
        recovered = bd.FetchOutcome("ok", [], page_note={"ds1_payload": True, "best_rows": 0, "other_rows": 0,
                                                         "tally": {bd.REFUSED_RETRIED: 1, bd.REFUSED_RECOVERED: 1}})
        outcomes = iter([refused, recovered])
        self.assertEqual(len(bd.plan_searches(config(), NOW.date())), 2)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            result = bd.run_job(config(), history_path=Path(tmp) / "h.jsonl", alerts_path=Path(tmp) / "a.jsonl",
                                now=NOW, fetch=lambda spec: next(outcomes, recovered), send=lambda *a, **k: None,
                                dry_run=True, print_details=False)
        self.assertEqual((result.refused, result.refused_retried, result.refused_recovered), (1, 2, 1))
        self.assertIn("refused by Google 1 (read again 2, recovered 1)", result.log_line)
        self.assertIn("no itinerary 2", result.log_line)


class WeeklyFaresRetryTests(unittest.TestCase):
    SEARCH = wf.FareSearch("BKK", "Bangkok", "ECONOMY", "2027-06-25", "2027-07-12")

    def fetch(self, pages, calls=1):
        with patch("public_flight_search.google_flights._fetch_page_html", side_effect=list(pages)) as read, \
                patch("public_flight_search.google_flights._parse_flight_cards", side_effect=parse_by_page), \
                patch("public_flight_search.weekly_fares.time.sleep"):
            fetch = wf.make_google_fetch()
            results = [fetch(self.SEARCH) for _ in range(calls)]
        return results, read.call_count

    def test_a_refused_search_is_read_once_more_and_priced(self):
        results, reads = self.fetch([REFUSED, RESULTS])
        self.assertEqual((results[0][0], len(results[0][1]), reads), ("ok", 1, 2))

    def test_refused_twice_is_its_own_status_not_no_fares(self):
        results, reads = self.fetch([REFUSED, REFUSED])
        self.assertEqual((results[0], reads), (("refused", ()), 2))
        config = load_holiday_config((ROOT / "examples" / "july_holiday_config.json").read_text(encoding="utf-8"))
        payload = wf.read_weekly_fares(config, lambda search: ("refused", ()), now=NOW, max_searches=2)
        self.assertEqual([row["status"] for row in payload["rows"]], ["refused", "refused"])
        self.assertIn("refused", wf.render_section_html(payload, []))

    def test_no_second_read_starts_after_the_retry_deadline(self):
        with patch("public_flight_search.google_flights._fetch_page_html", side_effect=[REFUSED, RESULTS]) as read, \
                patch("public_flight_search.google_flights._parse_flight_cards", side_effect=parse_by_page), \
                patch("public_flight_search.weekly_fares.time.sleep") as waited:
            result = wf.make_google_fetch(retry_until=0.0)(self.SEARCH)
        self.assertEqual((result, read.call_count, waited.call_count), (("refused", ()), 1, 0))

    def test_only_a_few_searches_a_run_are_read_again(self):
        calls = wf.REFUSED_RETRIES_PER_RUN + 3
        _, reads = self.fetch([REFUSED] * (2 * calls), calls=calls)
        self.assertEqual(reads, calls + wf.REFUSED_RETRIES_PER_RUN)
        worst_extra_seconds = wf.REFUSED_RETRIES_PER_RUN * (wf.REFUSED_RETRY_WAIT_SECONDS[1] + 5)
        self.assertLess(9 * 60 + worst_extra_seconds, wf.DEFAULT_BUDGET_SECONDS)


if __name__ == "__main__":
    unittest.main()
