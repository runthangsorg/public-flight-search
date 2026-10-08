import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from public_flight_search.jobs import (
    config_season,
    run_holiday_planner,
)

#: One empty scratch directory for the whole module, so the paths below never
#: exist. See ``_no_evidence``.
_NO_EVIDENCE_DIR = ""


def _no_evidence() -> dict:
    """Explicit paths to evidence files that do not exist.

    EVERY planner test in this module passes these. Both evidence defaults are
    CWD-relative (``data/holiday_...json``), so a checkout the workflow has
    seeded is a different machine from CI: a test that names no path reads
    whatever that operator's checkout happens to hold, and reports on prices
    the test author never chose. Naming an absent path is the cheapest way to
    say "this test is about the job, not about somebody's evidence file" — and
    it makes the omission visible at the call site instead of resolving it from
    the working directory.
    """
    global _NO_EVIDENCE_DIR
    if not _NO_EVIDENCE_DIR:
        import atexit
        import shutil

        _NO_EVIDENCE_DIR = tempfile.mkdtemp(prefix="holiday-no-evidence-")
        atexit.register(shutil.rmtree, _NO_EVIDENCE_DIR, True)
    return {
        "hotel_evidence_path": os.path.join(_NO_EVIDENCE_DIR, "absent-hotel.json"),
        "live_evidence_path": os.path.join(_NO_EVIDENCE_DIR, "absent-live.json"),
    }


class HolidayJobTests(unittest.TestCase):
    def test_provider_count_includes_every_destination_and_date_pair(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text(
            encoding="utf-8"
        )
        with patch.dict(os.environ, {"HOLIDAY_SEARCH_CONFIG_JSON": payload}):
            result = run_holiday_planner(dry_run=True, **_no_evidence())
        self.assertEqual(result["destination_count"], 21)
        self.assertEqual(result["date_combination_count"], 49)
        # 10 destinations x 49 pairs x 10 providers (6 package + 4 dynamic)
        # + 4 destinations (cairo/muscat/doha/cape_verde, no Jet2 product)
        # x 49 pairs x 9
        # + 3 Far East destinations (no Jet2 product; Langkawi/Penang/Singapore
        # removed 2026-10-02) x 49 pairs x 9
        # + 4 Africa/Mexico/Japan destinations (2026-09-30; okinawa added
        # 2026-10-04, no Jet2 product) x 49 x 9.
        self.assertEqual(
            result["provider_entry_count"],
            10 * 49 * 10 + 4 * 49 * 9 + 3 * 49 * 9 + 4 * 49 * 9,
        )
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
                result = run_holiday_planner(dry_run=False, **_no_evidence())
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
                first = run_holiday_planner(dry_run=False, **_no_evidence())
                self.assertTrue(first["email_sent"])
                second = run_holiday_planner(dry_run=False, **_no_evidence())
        self.assertFalse(second["email_sent"])
        self.assertTrue(second["send_skipped_no_change"])
        # Same-day re-run: day-level dedupe means no double-counted rows —
        # a manual re-dispatch neither re-sends nor inflates the series.
        self.assertEqual(second["history_observations_appended"], 0)
        send.assert_called_once()  # only the first run emailed

    def test_send_every_run_switch_sends_an_unchanged_run(self):
        """HOLIDAY_SEND_EVERY_RUN=1: the 3x-week schedule mails even when flat."""
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text()
        send = self._patch_smtp()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": payload,
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
                "HOLIDAY_SEND_EVERY_RUN": "1",
                "HOLIDAY_EMAIL_COOLDOWN_MINUTES": "0",
            }
            with patch.dict(os.environ, env):
                first = run_holiday_planner(dry_run=False)
                second = run_holiday_planner(dry_run=False)
        self.assertTrue(first["email_sent"])
        self.assertTrue(second["email_sent"])
        self.assertFalse(second["send_skipped_no_change"])
        self.assertEqual(send.call_count, 2)

    def test_send_every_run_switch_never_overrides_dry_run(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "dec_holiday_config.json").read_text()
        send = self._patch_smtp()
        env = {"HOLIDAY_SEARCH_CONFIG_JSON": payload, "HOLIDAY_SEND_EVERY_RUN": "true"}
        with patch.dict(os.environ, env):
            result = run_holiday_planner(dry_run=True)
        self.assertFalse(result["email_sent"])
        send.assert_not_called()

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
                first = run_holiday_planner(dry_run=False, **_no_evidence())
                self.assertTrue(first["email_sent"])
                # Simulate a resort repricing £200 cheaper since run 1.
                history_file = Path(env["HOLIDAY_HISTORY_PATH"])
                rows = [json.loads(l) for l in history_file.read_text().splitlines() if l.strip()]
                target = rows[-1]
                target["total_package_price_gbp"] -= 200.0
                target["observed_at"] = "2026-09-12T08:00:00+00:00"
                rows.append(target)
                history_file.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
                third = run_holiday_planner(dry_run=False, **_no_evidence())
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
                first = run_holiday_planner(dry_run=False, **_no_evidence())
                self.assertTrue(first["email_sent"])
                history_file = Path(env["HOLIDAY_HISTORY_PATH"])
                rows = [json.loads(l) for l in history_file.read_text().splitlines() if l.strip()]
                target = rows[-1]
                target["total_package_price_gbp"] -= 200.0
                rows.append(target)
                history_file.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
                rapid = run_holiday_planner(dry_run=False, **_no_evidence())
                self.assertFalse(rapid["email_sent"])
                self.assertIn("cooldown", rapid["email_cooldown_reason"])
                # force_send still overrides the cooldown.
                forced = run_holiday_planner(
                    dry_run=False, force_send=True, **_no_evidence()
                )
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
            return run_holiday_planner(dry_run=True, **_no_evidence())

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
            result = run_holiday_planner(
                dry_run=True, config_path=str(explicit), **_no_evidence()
            )
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
                    dry_run=True,
                    config_path="examples/july_holday_config.json",
                    **_no_evidence(),
                )
        self.assertIn("july_holday_config.json", str(ctx.exception))


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
                                             expect_season=expect, **_no_evidence())
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
        # Refused, not quiet: "no change" would send an operator the wrong way.
        self.assertFalse(result["send_skipped_no_change"])
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
                result = run_holiday_planner(dry_run=False, force_send=True,
                                             expect_season="july", **_no_evidence())
        self.assertEqual(result["config_season"], "unknown")
        self.assertFalse(result["config_season_mismatch"])
        self.assertTrue(result["email_sent"])


class HolidayStepSummaryTests(unittest.TestCase):
    """`config_source` lives in the log. The run page is where a wrong config gets noticed."""

    def _run(self, env):
        with patch.dict(os.environ, env, clear=True):
            return run_holiday_planner(dry_run=True, **_no_evidence())

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


class SkipReasonTallyTests(unittest.TestCase):
    """Each refusal reason is listed once in the run result, with its count.

    The loaders log one line per rejected row, so one summer read refused by a
    December run appeared once per room row: the 7 Oct December result carried
    64 hotel skip lines of which 23 were distinct, and a 12 KB JSON line that
    an operator has to read to see why a card fell back to a catalogue rate.
    """

    def test_a_repeated_reason_is_listed_once_with_its_count(self):
        from public_flight_search.jobs import _tally

        self.assertEqual(_tally(["a", "b", "a", "a"]), ["a (x3)", "b"])
        self.assertEqual(_tally(["only"]), ["only"])
        self.assertEqual(_tally([]), [])

    def test_the_run_result_lists_each_skip_reason_once(self):
        root = Path(__file__).parents[1]
        fixtures = root / "tests" / "fixtures"
        with patch("builtins.print"):
            result = run_holiday_planner(
                dry_run=True,
                config_path=str(root / "examples" / "dec_holiday_config.json"),
                hotel_evidence_path=str(fixtures / "hotel_evidence_sample.json"),
                package_evidence_path=str(fixtures / "package_evidence_sample.json"),
                live_evidence_path=_no_evidence()["live_evidence_path"],
            )
        tallied = False
        for key in ("hotel_evidence_skipped", "package_evidence_skipped",
                    "live_skipped", "stopover_evidence_skipped"):
            entries = result[key]
            self.assertEqual(len(entries), len(set(entries)), key)
            tallied = tallied or any(entry.endswith(")") and " (x" in entry for entry in entries)
        # The fixtures repeat at least one reason, so the count is exercised.
        self.assertTrue(tallied)
