"""One weekly holiday e-mail (owner, 9 Nov 2026): rare instant business alerts, live fares in the Sunday body,
and no dispatch that e-mails the owner unless it is asked to."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import re

from public_flight_search import business_deals as bd
from public_flight_search import weekly_fares as wf
from public_flight_search.engine import FlightOffer
from public_flight_search.holidays import load_holiday_config

ROOT = Path(__file__).resolve().parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
WORKFLOW = ROOT / ".github" / "workflows" / "july-holiday-planner.yml"
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
DEP = "2027-03-01"


def raw_config(**over):
    base = {
        "origins": [{"code": "LHR", "label": "London Heathrow", "positioning_gbp": 0, "home": True}],
        "destinations": [{"code": "BKK", "label": "Bangkok", "region": "asia", "hours_from_london": 11.5}],
        "dates": [DEP], "min_observations": 5, "absolute_caps_gbp": {"asia": 1000},
    }
    base.update(over)
    return base


def history(level, n=6):
    rows = []
    for i in range(n):
        when = (NOW - timedelta(days=3 + i)).isoformat(timespec="seconds")
        total = level + i
        rows.append({"key": f"LHR|BKK|{DEP}|BUSINESS", "origin": "LHR", "destination": "BKK", "region": "asia",
                     "departure": DEP, "cabin_class": "BUSINESS", "fare_gbp": total, "positioning_gbp": 0,
                     "total_gbp": total, "stops": 0, "duration_minutes": 700, "airline": "Test Air",
                     "booking_url": "", "observed_at": when, "origin_is_home": True})
    return rows


class Sink:
    def __init__(self):
        self.sent = []

    def __call__(self, subject, html, *, text=""):
        self.sent.append(subject)


class InstantBusinessAlertTests(unittest.TestCase):
    def run_job(self, price, raw, rows=()):
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / "h.jsonl"
            hist.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            cfg = bd.load_config(raw, today=NOW.date())

            def fetch(spec):
                return bd.FetchOutcome("ok", [FlightOffer.from_mapping({
                    "origin": spec.origin, "destination": spec.destination, "departure": f"{spec.date}T10:00:00",
                    "price": price, "currency": "GBP", "stops": 0, "duration_minutes": 700,
                    "provider": "Google Flights", "booking_url": "https://example.test/x", "airline": "Test Air"})])

            sink = Sink()
            with contextlib.redirect_stdout(io.StringIO()):
                result = bd.run_job(cfg, history_path=hist, alerts_path=Path(tmp) / "a.jsonl", now=NOW,
                                    fetch=fetch, send=sink, dry_run=False)
            return result, sink

    def test_the_default_drop_is_forty_percent(self):
        self.assertEqual(bd.INSTANT_ALERT_DROP_PCT, 40.0)
        self.assertEqual(bd.load_config(raw_config(), today=NOW.date()).median_drop_pct, 40.0)

    def test_the_live_example_config_asks_for_forty_percent(self):
        cfg = bd.load_config(EXAMPLE_TEXT(), today=NOW.date())
        self.assertGreaterEqual(cfg.median_drop_pct, 40.0)
        self.assertFalse(cfg.cap_alerts)

    def test_thirty_five_percent_under_the_median_sends_nothing(self):
        result, sink = self.run_job(1300, raw_config(absolute_caps_gbp={}), history(2000))
        self.assertEqual(result.deals, [])
        self.assertEqual(sink.sent, [])

    def test_forty_one_percent_under_the_median_sends_one_instant_email(self):
        result, sink = self.run_job(1180, raw_config(absolute_caps_gbp={}), history(2000))
        self.assertEqual([d.trigger for d in result.deals], ["median"])
        self.assertEqual(len(sink.sent), 1)

    def test_a_fare_under_its_cap_alone_no_longer_emails(self):
        result, sink = self.run_job(900, raw_config())
        self.assertEqual(result.deals, [])
        self.assertEqual(sink.sent, [])

    def test_cap_alerts_can_still_be_switched_on(self):
        result, sink = self.run_job(900, raw_config(cap_alerts=True))
        self.assertEqual([d.trigger for d in result.deals], ["cap"])


def EXAMPLE_TEXT():
    return (ROOT / "examples" / "business_deals_config.json").read_text(encoding="utf-8")


class WeeklyFaresTests(unittest.TestCase):
    def setUp(self):
        self.config = load_holiday_config(JULY.read_text(encoding="utf-8"))

    def test_the_plan_covers_every_config_airport_and_the_maldives_in_both_cabins(self):
        searches = wf.plan(self.config)
        airports = {s.airport for s in searches}
        for code in ("LOP", "DPS", "DAD", "OKA", "CTS", "NBO", "MBA", "JNB", "CPT", "MRU", "ZNZ", "JRO", "MLE", "HND"):
            self.assertIn(code, airports)
        for code in airports:
            self.assertEqual({s.cabin for s in searches if s.airport == code}, {"ECONOMY", "BUSINESS"})

    def test_the_reference_dates_are_a_priced_pair_near_seventeen_nights(self):
        out, back = wf.reference_dates(self.config)
        nights = (datetime.fromisoformat(back) - datetime.fromisoformat(out)).days
        self.assertLessEqual(abs(nights - wf.REFERENCE_NIGHTS), 2)

    def fetch(self, prices):
        def fetch(search):
            price = prices.get((search.airport, search.cabin))
            if price == "wall":
                return "wall", ()
            if price is None:
                return "ok", ()
            return "ok", [{"origin": "LHR", "destination": search.airport, "departure": f"{search.outbound}T09:00:00",
                           "price": price, "currency": "GBP", "stops": 1, "duration_minutes": 900,
                           "provider": "Google Flights", "booking_url": "https://example.test/f",
                           "airline": "Qatar Airways"}]
        return fetch

    def test_a_read_records_per_person_and_the_scaled_party_figure(self):
        payload = wf.read_weekly_fares(self.config, self.fetch({("MLE", "ECONOMY"): 812.0, ("MLE", "BUSINESS"): "wall"}),
                                       now=NOW)
        rows = {(r["airport"], r["cabin"]): r for r in payload["rows"]}
        econ = rows[("MLE", "ECONOMY")]
        self.assertEqual(econ["status"], "priced")
        self.assertEqual(econ["per_person_gbp"], 812.0)
        self.assertEqual(econ["party_estimate_gbp"], 812.0 * self.config.travellers)
        self.assertEqual(rows[("MLE", "BUSINESS")]["status"], "wall")
        self.assertEqual(rows[("DPS", "ECONOMY")]["status"], "no fares")

    def test_the_section_says_when_it_was_read_and_that_the_party_figure_is_scaled(self):
        payload = wf.read_weekly_fares(self.config, self.fetch({("MLE", "ECONOMY"): 812.0}), now=NOW)
        html = wf.render_section_html(payload, [])
        self.assertIn("Live fares this week", html)
        self.assertIn("read 2 Nov", html)
        self.assertIn("not a quote", html)
        self.assertIn("Maldives", html)
        self.assertIn("£812", html)
        self.assertIn("https://example.test/f", html)

    def test_best_business_this_week_takes_the_cheapest_recent_read_per_destination(self):
        rows = [
            {"origin": "LHR", "destination": "BKK", "departure": DEP, "per_person_gbp": 2100,
             "observed_at": (NOW - timedelta(days=2)).isoformat(), "airline": "A"},
            {"origin": "LHR", "destination": "BKK", "departure": DEP, "per_person_gbp": 1900,
             "observed_at": (NOW - timedelta(days=1)).isoformat(), "airline": "B"},
            {"origin": "LHR", "destination": "BKK", "departure": DEP, "per_person_gbp": 900,
             "observed_at": (NOW - timedelta(days=20)).isoformat(), "airline": "old"},
            {"origin": "LHR", "destination": "DPS", "departure": DEP, "per_person_gbp": 2500,
             "observed_at": (NOW - timedelta(days=3)).isoformat(), "airline": "C"},
        ]
        best = wf.best_business_this_week(rows, NOW)
        self.assertEqual([(r["destination"], r["airline"]) for r in best], [("BKK", "B"), ("DPS", "C")])
        html = wf.render_section_html(None, best)
        self.assertIn("Best business fares this week", html)
        self.assertIn("40%", html)

    def test_the_sections_go_before_not_yet_priced(self):
        body = '<div>cards</div><div style="x">Not yet priced</div><div>list</div></div>'
        out = wf.insert_section(body, "<p>WEEKLY</p>")
        self.assertLess(out.index("WEEKLY"), out.index("Not yet priced"))
        self.assertEqual(wf.insert_section(body, ""), body)


class DispatchNeverEmailsUnlessAskedTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def step_if(self, name):
        match = re.search(r"- name: " + re.escape(name) + r"[^\n]*\n\s+if: ([^\n]+)", self.text)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_dispatch_has_a_send_to_owner_input_that_defaults_off(self):
        block = re.search(r"\n      send_to_owner:\n((?:        [^\n]*\n)+)", self.text)
        self.assertIsNotNone(block)
        self.assertIn("default: false", block.group(1))
        self.assertIn("type: boolean", block.group(1))

    def test_a_dispatch_runs_dry_unless_send_to_owner_is_true(self):
        self.assertIn('"${DISPATCH_SEND_TO_OWNER:-false}" != "true"', self.text)
        self.assertIn("DISPATCH_SEND_TO_OWNER: ${{ inputs.send_to_owner }}", self.text)

    def test_history_is_only_persisted_by_a_real_send(self):
        for name in ("Seed price history from private data repo", "Persist price history to private data repo"):
            self.assertIn("inputs.send_to_owner == true", self.step_if(name))

    def test_the_sunday_run_reads_live_fares_and_always_sends(self):
        read = self.text.index("- name: Read this week's live fares")
        build = self.text.index("- name: Build and optionally deliver")
        self.assertLess(read, build)
        self.assertIn('"${GITHUB_EVENT_NAME}" == "schedule"', self.text)

    def test_agents_md_forbids_live_test_dispatches(self):
        rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("never dispatch a live send", rules)


if __name__ == "__main__":
    unittest.main()


def _clean_env(**extra):
    keep = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "PYTHONPATH")}
    keep.update(extra)
    return keep


class ClampedThresholdTests(unittest.TestCase):
    def test_a_stored_config_asking_for_less_than_forty_percent_is_clamped_to_forty(self):
        for asked in (5, 30, 39.9):
            cfg = bd.load_config(raw_config(median_drop_pct=asked), today=NOW.date())
            self.assertEqual(cfg.median_drop_pct, 40.0, asked)
        self.assertEqual(bd.load_config(raw_config(median_drop_pct=55), today=NOW.date()).median_drop_pct, 55.0)

    def test_a_fare_thirty_five_percent_under_sends_nothing_even_when_the_secret_says_thirty(self):
        run = InstantBusinessAlertTests("run_job")
        result, sink = run.run_job(1300, raw_config(absolute_caps_gbp={}, median_drop_pct=30), history(2000))
        self.assertEqual(result.deals, [])
        self.assertEqual(sink.sent, [])


def _route_rows(level, n, *, nights=17, cabin="BUSINESS", origin="LHR", dest="BKK", dep="2027-07-02", days_ago=10):
    ret = (datetime.fromisoformat(dep) + timedelta(days=nights)).date().isoformat()
    return [{"origin": origin, "destination": dest, "cabin_class": cabin, "departure": dep, "return_date": ret,
             "per_person_gbp": level + i, "total_gbp": level + i,
             "observed_at": (NOW - timedelta(days=days_ago + i)).isoformat(), "airline": "Test Air"}
            for i in range(n)]


class SectionUsesTheAlertBaselineTests(unittest.TestCase):
    def best(self, rows):
        return wf.best_business_this_week(rows, NOW)

    def this_week(self, price, **kw):
        row = _route_rows(price, 1, days_ago=1, **kw)[0]
        row["per_person_gbp"] = price
        return row

    def test_the_median_is_the_alerts_route_median(self):
        # Same route, month and trip length: median of 6 readings (2000..2005) is 2002.5.
        rows = _route_rows(2000, 6) + [self.this_week(1500)]
        # A 10-night trip and a different origin must not leak into the baseline.
        rows += _route_rows(500, 8, nights=10) + _route_rows(500, 8, origin="OSL")
        out = self.best(rows)[0]
        self.assertEqual(out["median_gbp"], bd.route_median(rows, out, NOW)[0])
        self.assertAlmostEqual(out["median_gbp"], 2002.0, delta=1.5)
        self.assertGreater(out["pct_below_median"], 20)

    def test_fewer_than_five_readings_shows_the_fare_with_no_percentage(self):
        rows = _route_rows(2000, 3) + [self.this_week(1500)]
        out = self.best(rows)[0]
        self.assertIsNone(out["pct_below_median"])
        self.assertIsNone(out["median_gbp"])
        html = wf.render_section_html(None, [out])
        self.assertIn("£1,500", html)
        self.assertNotIn("under", html.split("vs usual")[1])

    def test_four_readings_is_not_enough_and_five_is(self):
        four = self.best(_route_rows(2000, 3) + [self.this_week(1500)])[0]
        self.assertIsNone(four["median_gbp"])
        # the best fare of the week counts as one of its own route's readings, as it does for the alerts' history
        five = self.best(_route_rows(2000, 5) + [self.this_week(1500)])[0]
        self.assertIsNotNone(five["median_gbp"])

    def test_readings_older_than_ninety_days_do_not_count(self):
        rows = _route_rows(2000, 6, days_ago=100) + [self.this_week(1500)]
        self.assertIsNone(self.best(rows)[0]["median_gbp"])

    def test_the_multi_vendor_history_is_read_too_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.jsonl", Path(tmp) / "b.jsonl"
            base = self.this_week(1500)
            base["fingerprint"] = "f1"
            other = self.this_week(1700, dest="DPS")
            other["fingerprint"] = "f2"
            a.write_text(json.dumps(base) + "\n", encoding="utf-8")
            b.write_text(json.dumps(base) + "\n" + json.dumps(other) + "\n", encoding="utf-8")
            env = {"BUSINESS_DEALS_HISTORY": str(a), "BUSINESS_DEALS_MULTIVENDOR_HISTORY": str(b),
                   "JULY_WEEKLY_FARES_PATH": str(Path(tmp) / "none.json")}
            with patch.dict(os.environ, env):
                html, text = wf.weekly_sections(NOW)
        self.assertIn("BKK", html)
        self.assertIn("DPS", html)
        self.assertEqual(html.count("LHR→BKK"), 1)
        self.assertIn("LHR→DPS", text)


class IncrementalAndBudgetedReadTests(unittest.TestCase):
    def setUp(self):
        self.config = load_holiday_config(JULY.read_text(encoding="utf-8"))

    def test_every_search_checkpoints_the_rows_so_far(self):
        sizes = []
        wf.read_weekly_fares(self.config, lambda s: ("ok", ()), now=NOW, max_searches=3,
                             checkpoint=lambda p: sizes.append(len(p["rows"])))
        self.assertEqual(sizes[:3], [1, 2, 3])

    def test_a_killed_run_keeps_what_it_read_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "d" / "fares.json")
            calls = []

            def fetch(search):
                if len(calls) == 2:
                    raise KeyboardInterrupt  # stands in for the step being killed
                calls.append(search)
                return "ok", ()

            with self.assertRaises(KeyboardInterrupt):
                wf.read_weekly_fares(self.config, fetch, now=NOW, checkpoint=lambda p: wf.write_atomic(out, p))
            saved = wf.load_weekly_fares(out)
            self.assertEqual(len(saved["rows"]), 2)
            self.assertFalse(Path(out + ".tmp").exists())

    def test_no_new_search_starts_after_the_wall_clock_budget(self):
        ticks = iter(range(0, 10_000, 100))  # each clock() call is 100 s later
        started = []

        def fetch(search):
            started.append(search)
            return "ok", ()

        payload = wf.read_weekly_fares(self.config, fetch, now=NOW, budget_seconds=350, clock=lambda: next(ticks))
        self.assertLess(len(started), len(wf.plan(self.config)))
        self.assertEqual(len(payload["rows"]), len(wf.plan(self.config)))
        statuses = [r["status"] for r in payload["rows"]]
        self.assertEqual(statuses.count("skipped"), len(wf.plan(self.config)) - len(started))
        self.assertEqual(statuses[len(started):], ["skipped"] * statuses.count("skipped"))

    def test_the_budget_is_inside_the_step_timeout(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        step = re.search(r"timeout (\d+)m python -m public_flight_search july-weekly-fares[^\n]*--budget-seconds (\d+)", text)
        self.assertIsNotNone(step)
        self.assertLess(int(step.group(2)), int(step.group(1)) * 60 - 120)
        self.assertLess(wf.DEFAULT_BUDGET_SECONDS, 20 * 60 - 120)


class JulyDryRunRendersTheWeeklySectionTests(unittest.TestCase):
    def test_a_dry_run_with_a_weekly_fares_file_renders_the_section(self):
        from public_flight_search.jobs import run_holiday_planner

        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        prices = {("MLE", "ECONOMY"): 812.0}

        def fake(search):
            price = prices.get((search.airport, search.cabin))
            if price is None:
                return "ok", ()
            return "ok", [{"origin": "LHR", "destination": search.airport, "departure": f"{search.outbound}T09:00:00",
                           "price": price, "currency": "GBP", "stops": 1, "duration_minutes": 900,
                           "provider": "Google Flights", "booking_url": "https://example.test/f",
                           "airline": "Test Air"}]

        payload = wf.read_weekly_fares(config, fake, now=NOW)
        captured = []
        real = wf.insert_section

        def spy(html, section):
            out = real(html, section)
            captured.append(out)
            return out

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weekly.json"
            wf.write_atomic(str(path), payload)
            env = _clean_env(JULY_WEEKLY_FARES_PATH=str(path), HOLIDAY_HISTORY_PATH=str(Path(tmp) / "h.jsonl"),
                             BUSINESS_DEALS_HISTORY=str(Path(tmp) / "none.jsonl"),
                             BUSINESS_DEALS_MULTIVENDOR_HISTORY=str(Path(tmp) / "none2.jsonl"))
            with patch.dict(os.environ, env, clear=True), patch.object(wf, "insert_section", spy), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = run_holiday_planner(dry_run=True, config_path=str(JULY), expect_season="july")
        self.assertFalse(result["email_sent"])
        self.assertEqual(len(captured), 1)
        self.assertIn("Live fares this week", captured[0])
        self.assertIn("Maldives", captured[0])
        self.assertIn("£812", captured[0])
