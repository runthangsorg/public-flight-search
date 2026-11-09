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
