import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from public_flight_search.jobs import FlightCollectionError, run_flight_digest, run_holiday_planner


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


class FlightJobTests(unittest.TestCase):
    def test_empty_provider_scan_fails_closed_without_email(self):
        root = Path(__file__).parents[1]
        payload = (root / "examples" / "sept_config.json").read_text(
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
        payload = (root / "examples" / "sept_config.json").read_text(
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
