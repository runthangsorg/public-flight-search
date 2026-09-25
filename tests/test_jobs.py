import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from public_flight_search.jobs import (
    FlightCollectionError,
    config_season,
    run_flight_digest,
    run_holiday_planner,
)


class HolidayJobTests(unittest.TestCase):
    def test_provider_count_includes_every_destination_and_date_pair(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text(
            encoding="utf-8"
        )
        with patch.dict(os.environ, {"HOLIDAY_SEARCH_CONFIG_JSON": payload}):
            result = run_holiday_planner(dry_run=True)
        self.assertEqual(result["destination_count"], 14)
        self.assertEqual(result["date_combination_count"], 9)
        # 10 destinations x 9 pairs x 10 providers (6 package + 4 dynamic)
        # + 4 destinations (cairo/muscat/doha/cape_verde, no Jet2 product)
        # x 9 pairs x 9.
        self.assertEqual(result["provider_entry_count"], 1224)
        self.assertFalse(result["email_sent"])

    def _patch_smtp(self):
        sender = patch("public_flight_search.jobs.send_html")
        mock_send = sender.start()
        self.addCleanup(sender.stop)
        return mock_send

    def test_first_run_sends_and_reports_no_prior(self):
        """First-ever run has no history: email goes out, digest empty."""
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text()
        send = self._patch_smtp()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": payload,
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
            }
            with patch.dict(os.environ, env):
                result = run_holiday_planner(dry_run=False)
        self.assertTrue(result["email_sent"])
        self.assertFalse(result["send_skipped_no_change"])
        self.assertEqual(result["last_prior_observation"], "")
        send.assert_called_once()

    def test_unchanged_rerun_is_suppressed(self):
        """Same prices as last run -> tracked but NOT emailed (anti-spam)."""
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text()
        send = self._patch_smtp()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": payload,
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
            }
            with patch.dict(os.environ, env):
                first = run_holiday_planner(dry_run=False)
                self.assertTrue(first["email_sent"])
                second = run_holiday_planner(dry_run=False)
        self.assertFalse(second["email_sent"])
        self.assertTrue(second["send_skipped_no_change"])
        # Same-day re-run: day-level dedupe means no double-counted rows —
        # a manual re-dispatch neither re-sends nor inflates the series.
        self.assertEqual(second["history_observations_appended"], 0)
        send.assert_called_once()  # only the first run emailed

    def test_price_drop_re_sends(self):
        """A drop vs last report re-sends once the cooldown has passed
        (cooldown explicitly disabled here to isolate the drop rule)."""
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text()
        send = self._patch_smtp()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": payload,
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
                "HOLIDAY_EMAIL_COOLDOWN_MINUTES": "0",
            }
            with patch.dict(os.environ, env):
                first = run_holiday_planner(dry_run=False)
                self.assertTrue(first["email_sent"])
                # Simulate a resort repricing £200 cheaper since run 1.
                history_file = Path(env["HOLIDAY_HISTORY_PATH"])
                rows = [json.loads(l) for l in history_file.read_text().splitlines() if l.strip()]
                target = rows[-1]
                target["total_package_price_gbp"] -= 200.0
                target["observed_at"] = "2026-09-12T08:00:00+00:00"
                rows.append(target)
                history_file.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
                third = run_holiday_planner(dry_run=False)
        self.assertTrue(third["email_sent"])
        self.assertFalse(third["send_skipped_no_change"])
        self.assertEqual(send.call_count, 2)

    def test_cooldown_suppresses_rapid_refire_even_on_drop(self):
        """2026-09-22: 3 emails landed in 35 minutes while hunt batches
        landed (each batch produced benchmark→live drops). A reader-worthy
        change no longer re-sends within the cooldown window; the next
        scheduled run carries it."""
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text()
        send = self._patch_smtp()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": payload,
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
            }
            with patch.dict(os.environ, env):
                first = run_holiday_planner(dry_run=False)
                self.assertTrue(first["email_sent"])
                history_file = Path(env["HOLIDAY_HISTORY_PATH"])
                rows = [json.loads(l) for l in history_file.read_text().splitlines() if l.strip()]
                target = rows[-1]
                target["total_package_price_gbp"] -= 200.0
                rows.append(target)
                history_file.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
                rapid = run_holiday_planner(dry_run=False)
                self.assertFalse(rapid["email_sent"])
                self.assertIn("cooldown", rapid["email_cooldown_reason"])
                # force_send still overrides the cooldown.
                forced = run_holiday_planner(dry_run=False, force_send=True)
                self.assertTrue(forced["email_sent"])
        self.assertEqual(send.call_count, 2)  # first + forced; rapid suppressed


class HolidayConfigSourceTests(unittest.TestCase):
    """Which config a run used must be readable from its result.

    Three shapes reach run_holiday_planner — an explicit --config path, one
    of two env secrets, then a committed fallback file — and they price
    different holidays. On 2026-09-24 the July workflow bound an empty env
    var of the wrong name over the real secret, so the scheduled run priced
    the committed fallback: a valid report about the right dates, sent with
    `email_sent: true`, and nothing in the summary said which config made it.
    """

    def setUp(self):
        self.root = Path(__file__).parents[1]
        self.payload = (self.root / "examples" / "dec_holiday_config.json").read_text(
            encoding="utf-8"
        )

    def _run(self, env):
        with patch.dict(os.environ, env, clear=True):
            return run_holiday_planner(dry_run=True)

    def test_names_the_env_secret_that_was_used(self):
        result = self._run({"HOLIDAY_SEARCH_CONFIG_JSON": self.payload})
        self.assertEqual(result["config_source"], "env:HOLIDAY_SEARCH_CONFIG_JSON")

    def test_names_the_legacy_env_secret_that_was_used(self):
        result = self._run({"JULY_HOLIDAY_SEARCH_CONFIG_JSON": self.payload})
        self.assertEqual(
            result["config_source"], "env:JULY_HOLIDAY_SEARCH_CONFIG_JSON"
        )

    def test_the_preferred_secret_wins_over_the_legacy_one(self):
        result = self._run(
            {
                "HOLIDAY_SEARCH_CONFIG_JSON": self.payload,
                "JULY_HOLIDAY_SEARCH_CONFIG_JSON": "not-json-and-not-used",
            }
        )
        self.assertEqual(result["config_source"], "env:HOLIDAY_SEARCH_CONFIG_JSON")

    def test_names_an_explicit_config_path(self):
        explicit = self.root / "examples" / "dec_holiday_config.json"
        with patch.dict(os.environ, {}, clear=True):
            result = run_holiday_planner(dry_run=True, config_path=str(explicit))
        self.assertTrue(result["config_source"].startswith("config-path:"))
        self.assertTrue(
            result["config_source"].endswith("examples/dec_holiday_config.json")
        )

    def test_names_the_committed_fallback_file(self):
        result = self._run({})
        self.assertEqual(
            result["config_source"], "fallback-file:dec_holiday_config.json"
        )

    def test_explicit_config_path_that_does_not_exist_fails_loudly(self):
        """A typo'd --config must never fall through to a different holiday.

        `evidence-contract` already fails fast on this exact mistake (a
        misspelt July path printed a valid December contract and exited 0).
        The job had the same hole, one layer down.
        """
        with patch.dict(os.environ, {"HOLIDAY_SEARCH_CONFIG_JSON": self.payload}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                run_holiday_planner(
                    dry_run=True, config_path="examples/july_holday_config.json"
                )
        self.assertIn("july_holday_config.json", str(ctx.exception))


class FlightJobTests(unittest.TestCase):
    def test_empty_provider_scan_fails_closed_without_email(self):
        root = Path(__file__).parents[1]
        # Any real flight-digest payload will do; the December example is the one that is
        # still a supported trip (the September Muscat/UAE configs were deleted with the
        # job on 2026-09-25).
        payload = (root / "examples" / "dec_config.json").read_text(
            encoding="utf-8"
        )

        async def empty_scan(_searches):
            return {}

        with patch.dict(os.environ, {"FLIGHT_SEARCH_CONFIG_JSON": payload}), patch(
            "public_flight_search.jobs.search_google_flights", empty_scan
        ):
            with self.assertRaises(FlightCollectionError):
                run_flight_digest(dry_run=False)

    def test_paired_flight_digest_generates_itineraries(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_config.json").read_text(
            encoding="utf-8"
        )
        from public_flight_search.engine import FlightOffer
        from public_flight_search.config import build_search_plan
        from public_flight_search.trip_config import DEFAULT_TRIP_DEFINITIONS

        plan = build_search_plan(DEFAULT_TRIP_DEFINITIONS)
        outbound_key = [p.key for p in plan if "_OUTBOUND_" in p.key][0]
        return_key = [p.key for p in plan if "_RETURN_" in p.key][0]

        async def paired_scan(_searches):
            return {
                outbound_key: [
                    FlightOffer(
                        origin="LHR", destination="MCT", departure="2026-09-15T09:00:00",
                        arrival="2026-09-15T19:00:00", price=350, currency="GBP",
                        stops=0, duration_minutes=420, provider="Google Flights",
                        airline="Oman Air", booking_url="https://google.com/test1",
                        price_per_traveller=350, review_status="results_page_only"
                    )
                ],
                return_key: [
                    FlightOffer(
                        origin="MCT", destination="LHR", departure="2026-09-22T10:00:00",
                        arrival="2026-09-22T18:00:00", price=320, currency="GBP",
                        stops=0, duration_minutes=420, provider="Google Flights",
                        airline="Oman Air", booking_url="https://google.com/test2",
                        price_per_traveller=320, review_status="results_page_only"
                    )
                ]
            }

        with patch.dict(os.environ, {"FLIGHT_SEARCH_CONFIG_JSON": payload}), patch(
            "public_flight_search.jobs.search_google_flights", paired_scan
        ):
            result = run_flight_digest(dry_run=True)
            self.assertEqual(result["itinerary_count"], 1)
            self.assertEqual(result["search_count"], 6)
            self.assertFalse(result["email_sent"])


if __name__ == "__main__":
    unittest.main()


class HolidaySeasonGuardTests(unittest.TestCase):
    """A July run must never email the December holiday, however it got the config.

    The two planners are separate schedules with separate secrets, and the engine reads the
    GENERIC `HOLIDAY_SEARCH_CONFIG_JSON` before `JULY_HOLIDAY_SEARCH_CONFIG_JSON`. Nothing in a
    July run knew it was a July run, so one env binding was all that stood between the owner
    and a December report on the July schedule - a valid report about the right dates and the
    wrong trip, with only `config_source` in a log line to say so.
    """

    def setUp(self):
        self.root = Path(__file__).parents[1]
        self.dec = (self.root / "examples" / "dec_holiday_config.json").read_text(encoding="utf-8")
        self.july = (self.root / "examples" / "july_holiday_config.json").read_text(encoding="utf-8")

    def test_the_season_is_derived_from_the_title_and_the_departure_dates(self):
        from public_flight_search.holidays import load_holiday_config

        self.assertEqual(config_season(load_holiday_config(self.dec)), "december")
        self.assertEqual(config_season(load_holiday_config(self.july)), "july")

    def test_a_conflicting_title_and_dates_is_not_a_season_we_vouch_for(self):
        from public_flight_search.holidays import load_holiday_config

        payload = json.loads(self.dec)
        payload["report_title"] = "July Summer Holiday Packages"
        payload["outbound_dates"] = ["2026-12-20"]     # says July, prices December
        self.assertEqual(config_season(load_holiday_config(json.dumps(payload))), "unknown")

    def _run(self, payload, *, expect, force_send):
        send = self._patch_smtp()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": payload,
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
            }
            with patch.dict(os.environ, env, clear=True):
                result = run_holiday_planner(dry_run=False, force_send=force_send,
                                             expect_season=expect)
        return result, send

    def _patch_smtp(self):
        sender = patch("public_flight_search.jobs.send_html")
        mock_send = sender.start()
        self.addCleanup(sender.stop)
        return mock_send

    def test_the_december_secret_on_the_july_schedule_sends_nothing(self):
        result, send = self._run(self.dec, expect="july", force_send=False)
        self.assertEqual(result["config_season"], "december")
        self.assertTrue(result["config_season_mismatch"])
        self.assertFalse(result["email_sent"])
        self.assertIn("july planner", result["email_skipped_reason"])
        send.assert_not_called()

    def test_even_a_forced_send_cannot_push_the_wrong_holiday_out(self):
        """`force_send` overrides the anti-spam cooldown, never the season check: the report is
        not stale, it is a different trip."""
        result, send = self._run(self.dec, expect="july", force_send=True)
        self.assertFalse(result["email_sent"])
        send.assert_not_called()

    def test_the_july_secret_on_the_december_schedule_sends_nothing(self):
        result, send = self._run(self.july, expect="december", force_send=True)
        self.assertEqual(result["config_season"], "july")
        self.assertTrue(result["config_season_mismatch"])
        self.assertFalse(result["email_sent"])
        send.assert_not_called()

    def test_the_matching_season_still_sends(self):
        result, send = self._run(self.july, expect="july", force_send=True)
        self.assertEqual(result["config_season"], "july")
        self.assertFalse(result["config_season_mismatch"])
        self.assertEqual(result["email_skipped_reason"], "")
        self.assertTrue(result["email_sent"])
        send.assert_called_once()

    def test_an_unknown_season_is_reported_rather_than_assumed(self):
        """A config naming one season and pricing another must not be silently pushed out as
        either; it is not a season we can vouch for, so it is named as unknown."""
        payload = json.loads(self.dec)
        payload["report_title"] = "July Summer Holiday Packages"
        send = self._patch_smtp()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": json.dumps(payload),
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
            }
            with patch.dict(os.environ, env, clear=True):
                result = run_holiday_planner(dry_run=False, force_send=True, expect_season="july")
        self.assertEqual(result["config_season"], "unknown")
        self.assertFalse(result["config_season_mismatch"])
        self.assertTrue(result["email_sent"])


class HolidayStepSummaryTests(unittest.TestCase):
    """`config_source` lives in the log. The run page is where a wrong config gets noticed."""

    def _run(self, env):
        with patch.dict(os.environ, env, clear=True):
            return run_holiday_planner(dry_run=True)

    def test_the_summary_names_the_config_season_and_live_coverage(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "july_holiday_config.json").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            self._run({
                "JULY_HOLIDAY_SEARCH_CONFIG_JSON": payload,
                "GITHUB_STEP_SUMMARY": str(summary),
            })
            text = summary.read_text(encoding="utf-8")
        self.assertIn("### Holiday planner run", text)
        self.assertIn("env:JULY_HOLIDAY_SEARCH_CONFIG_JSON", text)
        self.assertIn("| Season this config prices | july |", text)

    def test_no_step_summary_file_is_not_an_error(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "july_holiday_config.json").read_text(encoding="utf-8")
        result = self._run({"JULY_HOLIDAY_SEARCH_CONFIG_JSON": payload})
        self.assertEqual(result["config_season"], "july")
