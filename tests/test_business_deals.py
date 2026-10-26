"""Business-class deals job: history, deal rules, silence, dedupe, walls, malformed fares."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from public_flight_search import business_deals as bd
from public_flight_search.engine import FlightOffer

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "business_deals_config.json"
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
DEP = "2027-03-01"


def raw_config(**over):
    base = {
        "report_title": "Business-class deals",
        "origins": [
            {"code": "LHR", "label": "London Heathrow", "positioning_gbp": 0, "home": True},
            {"code": "OSL", "label": "Oslo", "positioning_gbp": 150, "home": False},
        ],
        "destinations": [
            {"code": "BKK", "label": "Bangkok", "region": "asia", "hours_from_london": 11.5},
        ],
        "dates": [DEP],
        "min_observations": 5,
        "median_drop_pct": 30,
        "away_min_saving_pct": 20,
        "dedupe_days": 7,
        "redrop_pct": 2,
        "max_searches_per_run": 40,
        "stop_after_blocked": 3,
        "absolute_caps_gbp": {"asia": 1000},
    }
    base.update(over)
    return base


def offer(origin, price, *, dest="BKK", dep=DEP, duration=700, stops=0, currency="GBP"):
    return FlightOffer.from_mapping({
        "origin": origin, "destination": dest, "departure": f"{dep}T10:00:00", "price": price,
        "currency": currency, "stops": stops, "duration_minutes": duration, "provider": "Google Flights",
        "booking_url": f"https://example.test/{origin}-{dest}", "airline": "Test Air",
    })


def hist_row(origin, total, *, days_ago, dest="BKK", dep=DEP, positioning=0, home=None):
    when = (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "key": f"{origin}|{dest}|{dep}|BUSINESS", "origin": origin, "destination": dest, "region": "asia",
        "departure": dep, "cabin_class": "BUSINESS", "fare_gbp": total - positioning,
        "positioning_gbp": positioning, "total_gbp": total, "stops": 0, "duration_minutes": 700,
        "airline": "Test Air", "booking_url": "", "observed_at": when,
        "origin_is_home": (origin == "LHR") if home is None else home,
    }


def write_history(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def median_history(origin, level, n=6, **kw):
    return [hist_row(origin, level + i, days_ago=3 + i, **kw) for i in range(n)]


class Sink:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, subject, html, *, text=""):
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append((subject, html, text))


def fetch_with(prices_by_origin, *, calls=None):
    def fetch(spec):
        if calls is not None:
            calls.append(spec)
        price = prices_by_origin.get(spec.origin)
        offers = [] if price is None else [offer(spec.origin, price, dest=spec.destination, dep=spec.date)]
        return bd.FetchOutcome("ok", offers)
    return fetch


class JobCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.history = self.dir / "history.jsonl"
        self.alerts = self.dir / "alerts.jsonl"

    def run_job(self, prices, *, config=None, now=NOW, send=None, dry_run=False, fetch=None):
        cfg = bd.load_config(config or raw_config(), today=now.date())
        sink = send if send is not None else Sink()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = bd.run_job(
                cfg, history_path=self.history, alerts_path=self.alerts, now=now,
                fetch=fetch or fetch_with(prices), send=sink, dry_run=dry_run,
            )
        return result, sink, out.getvalue()


class DealRuleTests(JobCase):
    def test_cold_start_only_absolute_cap_can_fire(self):
        result, sink, _ = self.run_job({"LHR": 900})
        self.assertEqual(len(result.deals), 1)
        deal = result.deals[0]
        self.assertEqual(deal.trigger, "cap")
        self.assertTrue(deal.cold_start)
        self.assertEqual(len(sink.sent), 1)

    def test_cold_start_without_a_cap_is_silent_even_when_cheap(self):
        cfg = raw_config(absolute_caps_gbp={})
        result, sink, _ = self.run_job({"LHR": 300}, config=cfg)
        self.assertEqual(result.deals, [])
        self.assertEqual(sink.sent, [])

    def test_median_trigger_needs_thirty_percent_below(self):
        cfg = raw_config(absolute_caps_gbp={})
        write_history(self.history, median_history("LHR", 2000))
        result, _, _ = self.run_job({"LHR": 1300}, config=cfg)  # ~35% under ~2002 median
        self.assertEqual([d.trigger for d in result.deals], ["median"])
        self.assertAlmostEqual(result.deals[0].pct_below_median, 35.0, delta=1.5)

    def test_median_trigger_does_not_fire_at_twenty_five_percent(self):
        cfg = raw_config(absolute_caps_gbp={})
        write_history(self.history, median_history("LHR", 2000))
        result, sink, _ = self.run_job({"LHR": 1500}, config=cfg)
        self.assertEqual(result.deals, [])
        self.assertEqual(sink.sent, [])

    def test_median_needs_the_minimum_number_of_observations(self):
        cfg = raw_config(absolute_caps_gbp={})
        write_history(self.history, median_history("LHR", 2000, n=4))
        result, _, _ = self.run_job({"LHR": 900}, config=cfg)
        self.assertEqual(result.deals, [])

    def test_cap_fires_even_when_history_median_is_low(self):
        write_history(self.history, median_history("LHR", 1100))
        result, _, _ = self.run_job({"LHR": 990})
        self.assertEqual([d.trigger for d in result.deals], ["cap"])

    def test_positioning_cost_is_added_and_can_flip_the_winner(self):
        cfg = raw_config(absolute_caps_gbp={})
        write_history(self.history, median_history("LHR", 2200) + median_history("OSL", 2200, positioning=150))
        # Oslo fare 1300 + 150 positioning = 1450 total: 34% under its own median, but not 20% under London 1400.
        result, _, _ = self.run_job({"LHR": 1400, "OSL": 1300}, config=cfg)
        self.assertEqual([d.origin for d in result.deals], ["LHR"])
        obs_total = {o["origin"]: o["total_gbp"] for o in map(json.loads, self.history.read_text().splitlines())
                     if o["observed_at"].startswith(NOW.date().isoformat())}
        self.assertEqual(obs_total["OSL"], 1450)

    def test_away_origin_wins_when_total_beats_home_by_the_margin(self):
        cfg = raw_config(absolute_caps_gbp={})
        write_history(self.history, median_history("LHR", 2200) + median_history("OSL", 2200, positioning=150))
        result, _, _ = self.run_job({"LHR": 1400, "OSL": 900}, config=cfg)  # 1050 total <= 1120
        self.assertEqual(sorted(d.origin for d in result.deals), ["LHR", "OSL"])
        osl = [d for d in result.deals if d.origin == "OSL"][0]
        self.assertAlmostEqual(osl.saving_vs_home_pct, 25.0, delta=0.5)

    def test_away_origin_without_a_home_price_cannot_fire_on_median(self):
        cfg = raw_config(absolute_caps_gbp={})
        write_history(self.history, median_history("OSL", 2200, positioning=150))
        result, _, _ = self.run_job({"OSL": 900}, config=cfg)
        self.assertEqual(result.deals, [])


class SilenceAndDedupeTests(JobCase):
    def test_no_deal_means_no_email_and_a_one_line_log(self):
        result, sink, out = self.run_job({"LHR": 2500, "OSL": 2400})
        self.assertEqual(sink.sent, [])
        self.assertFalse(result.mailed)
        lines = [ln for ln in out.splitlines() if ln.startswith("business-deals")]
        self.assertEqual(len(lines), 1)
        self.assertIn("deals 0", lines[0])
        self.assertIn("mail not sent", lines[0])
        self.assertTrue(self.history.exists())

    def test_same_deal_is_not_mailed_twice_within_seven_days(self):
        _, first, _ = self.run_job({"LHR": 900})
        self.assertEqual(len(first.sent), 1)
        _, second, _ = self.run_job({"LHR": 900}, now=NOW + timedelta(days=2))
        self.assertEqual(second.sent, [])

    def test_a_further_drop_inside_the_window_is_mailed(self):
        self.run_job({"LHR": 900})
        _, second, _ = self.run_job({"LHR": 820}, now=NOW + timedelta(days=2))
        self.assertEqual(len(second.sent), 1)

    def test_a_tiny_drop_is_not_a_new_deal(self):
        self.run_job({"LHR": 900})
        _, second, _ = self.run_job({"LHR": 895}, now=NOW + timedelta(days=2))
        self.assertEqual(second.sent, [])

    def test_the_same_deal_is_mailed_again_after_the_window(self):
        self.run_job({"LHR": 900})
        _, later, _ = self.run_job({"LHR": 900}, now=NOW + timedelta(days=8))
        self.assertEqual(len(later.sent), 1)

    def test_a_failed_send_does_not_record_the_alert_so_the_next_run_retries(self):
        result, _, _ = self.run_job({"LHR": 900}, send=Sink(fail=True))
        self.assertFalse(result.mailed)
        self.assertFalse(self.alerts.exists())
        _, retry, _ = self.run_job({"LHR": 900}, now=NOW + timedelta(days=1))
        self.assertEqual(len(retry.sent), 1)

    def test_dry_run_prints_the_email_and_writes_and_sends_nothing(self):
        result, sink, out = self.run_job({"LHR": 900}, dry_run=True)
        self.assertEqual(sink.sent, [])
        self.assertFalse(self.history.exists())
        self.assertFalse(self.alerts.exists())
        self.assertEqual(len(result.deals), 1)
        self.assertIn("<html", out)
        self.assertIn("dry run", out.lower())


class PublicLogTests(JobCase):
    """This repository's Actions logs are world-readable. With the owner's real config (a secret), a dispatched dry
    run must not print routes, dates or fares: they are his travel plans (review 26 Oct 2026)."""

    def test_a_withheld_dry_run_prints_only_the_count(self):
        cfg = bd.load_config(raw_config(), today=NOW.date())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = bd.run_job(cfg, history_path=self.history, alerts_path=self.alerts, now=NOW,
                                fetch=fetch_with({"LHR": 900}), send=Sink(), dry_run=True, print_details=False)
        self.assertEqual(len(result.deals), 1)
        text = out.getvalue()
        self.assertIn("would mail 1 deal", text)
        for leak in ("BKK", "LHR", DEP, "900", "<html", "example.test"):
            self.assertNotIn(leak, text, leak)

    def _main(self, env):
        offers = self.dir / "offers.json"
        offers.write_text(json.dumps([{
            "origin": "LHR", "destination": "BKK", "departure": f"{DEP}T10:00:00", "price": 900, "currency": "GBP",
            "stops": 0, "duration_minutes": 700, "provider": "Google Flights",
            "booking_url": "https://example.test/LHR-BKK", "airline": "Test Air"}]), encoding="utf-8")
        keep = {k: os.environ.get(k) for k in ("GITHUB_ACTIONS", "BUSINESS_DEALS_CONFIG_JSON")}
        try:
            for k in keep:
                os.environ.pop(k, None)
            os.environ.update(env)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = bd.main(["--dry-run", "--offers", str(offers), "--history", str(self.history)])
        finally:
            for k, v in keep.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return code, out.getvalue()

    def test_actions_with_the_secret_config_withholds_the_details(self):
        code, text = self._main({"GITHUB_ACTIONS": "true", "BUSINESS_DEALS_CONFIG_JSON": json.dumps(raw_config())})
        self.assertEqual(code, 0)
        self.assertIn("would mail 1 deal", text)
        self.assertNotIn("BKK", text)

    def test_actions_with_a_config_file_also_withholds_the_details(self):
        cfg = self.dir / "cfg.json"
        cfg.write_text(json.dumps(raw_config()), encoding="utf-8")
        offers = self.dir / "offers.json"
        offers.write_text(json.dumps([{
            "origin": "LHR", "destination": "BKK", "departure": f"{DEP}T10:00:00", "price": 900, "currency": "GBP",
            "stops": 0, "duration_minutes": 700, "provider": "Google Flights",
            "booking_url": "https://example.test/LHR-BKK", "airline": "Test Air"}]), encoding="utf-8")
        keep = os.environ.get("GITHUB_ACTIONS")
        os.environ["GITHUB_ACTIONS"] = "true"
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                bd.main(["--dry-run", "--config", str(cfg), "--offers", str(offers), "--history", str(self.history)])
        finally:
            if keep is None:
                os.environ.pop("GITHUB_ACTIONS", None)
            else:
                os.environ["GITHUB_ACTIONS"] = keep
        self.assertIn("would mail 1 deal", out.getvalue())
        self.assertNotIn("BKK", out.getvalue())

    def test_a_local_dry_run_still_shows_the_email(self):
        code, text = self._main({"BUSINESS_DEALS_CONFIG_JSON": json.dumps(raw_config())})
        self.assertEqual(code, 0)
        self.assertIn("LHR-BKK", text)
        self.assertIn("<html", text)


class WallAndMalformedTests(JobCase):
    def test_walls_are_recorded_and_the_run_stops_instead_of_pushing_on(self):
        cfg = raw_config(dates=[DEP, "2027-03-08", "2027-03-15", "2027-03-22"])
        calls = []

        def walled(spec):
            calls.append(spec)
            return bd.FetchOutcome("wall", [])

        result, sink, out = self.run_job({}, config=cfg, fetch=walled)
        self.assertEqual(len(calls), 3)  # stop_after_blocked, never all 8 searches
        self.assertEqual(result.walled, 3)
        self.assertTrue(result.stopped_early)
        self.assertEqual(sink.sent, [])
        self.assertFalse(self.history.exists())
        self.assertIn("walled 3", out)

    def test_malformed_and_out_of_policy_fares_are_rejected(self):
        cfg = bd.load_config(raw_config(), today=NOW.date())
        spec = bd.SearchSpec("LHR", "BKK", DEP)
        good = offer("LHR", 1500)
        bad = [
            offer("LHR", 1500, duration=300),          # under 8 hours: not a long-haul business fare
            offer("LHR", 40),                          # business under the sanity floor: a mis-parse
            offer("LHR", 1500, currency="EUR"),        # not GBP
            offer("LHR", 1500, stops=3),               # more stops than the config allows
            offer("LHR", 1500, dep="2027-03-02"),      # wrong date for this search
            offer("OSL", 1500),                        # wrong origin for this search
            offer("LHR", 1500, dest="SIN"),            # wrong destination
        ]
        observation, rejected = bd.cheapest_observation([*bad, good], spec, cfg, NOW)
        self.assertEqual(rejected, len(bad))
        self.assertEqual(observation["total_gbp"], 1500)
        none, rejected_all = bd.cheapest_observation(bad, spec, cfg, NOW)
        self.assertIsNone(none)
        self.assertEqual(rejected_all, len(bad))

    def test_non_finite_price_never_becomes_an_observation(self):
        cfg = bd.load_config(raw_config(), today=NOW.date())
        spec = bd.SearchSpec("LHR", "BKK", DEP)
        nan_offer = offer("LHR", 1500)
        object.__setattr__(nan_offer, "price", float("nan"))
        observation, rejected = bd.cheapest_observation([nan_offer], spec, cfg, NOW)
        self.assertIsNone(observation)
        self.assertEqual(rejected, 1)

    def test_corrupt_history_lines_are_skipped_not_fatal(self):
        self.history.write_text("not json\n" + json.dumps(hist_row("LHR", 2000, days_ago=3)) + "\n[]\n")
        result, _, _ = self.run_job({"LHR": 2500})
        self.assertEqual(result.history_rows_added, 1)


class ConfigAndPlanTests(unittest.TestCase):
    def test_short_haul_destination_is_rejected_by_the_cabin_rule(self):
        raw = raw_config(absolute_caps_gbp={}, destinations=[{"code": "DXB", "label": "Dubai", "region": "middle_east",
                                                              "hours_from_london": 7.0}])
        with self.assertRaises(bd.BusinessDealsConfigError):
            bd.load_config(raw, today=NOW.date())

    def test_exactly_eight_hours_is_not_over_eight(self):
        def cfg(hours):
            return raw_config(absolute_caps_gbp={}, destinations=[
                {"code": "JFK", "label": "New York", "region": "north_america", "hours_from_london": hours}])

        with self.assertRaises(bd.BusinessDealsConfigError):
            bd.load_config(cfg(8.0), today=NOW.date())
        self.assertEqual(bd.load_config(cfg(8.1), today=NOW.date()).destinations[0].code, "JFK")

    def test_a_cap_for_a_region_nobody_flies_to_is_a_typo_and_is_rejected(self):
        with self.assertRaises(bd.BusinessDealsConfigError):
            bd.load_config(raw_config(absolute_caps_gbp={"asai": 1000}), today=NOW.date())

    def test_unknown_fields_and_bad_airport_codes_are_rejected(self):
        with self.assertRaises(bd.BusinessDealsConfigError):
            bd.load_config(raw_config(surprise=1), today=NOW.date())
        bad = raw_config(origins=[{"code": "LONDON", "label": "x", "positioning_gbp": 0, "home": True}])
        with self.assertRaises(bd.BusinessDealsConfigError):
            bd.load_config(bad, today=NOW.date())

    def test_at_least_one_home_origin_is_required(self):
        bad = raw_config(origins=[{"code": "OSL", "label": "Oslo", "positioning_gbp": 150, "home": False}])
        with self.assertRaises(bd.BusinessDealsConfigError):
            bd.load_config(bad, today=NOW.date())

    def test_date_windows_expand_and_past_dates_are_dropped(self):
        raw = raw_config(dates=[], date_windows=[{"start": "2026-10-01", "end": "2026-12-31", "every_days": 30}])
        cfg = bd.load_config(raw, today=date(2026, 11, 2))
        self.assertTrue(cfg.dates)
        self.assertTrue(all(d >= "2026-11-09" for d in cfg.dates))  # min_days_ahead default 7

    def test_plan_rotates_through_every_combination_and_respects_the_cap(self):
        raw = raw_config(
            origins=[{"code": "LHR", "label": "L", "positioning_gbp": 0, "home": True},
                     {"code": "OSL", "label": "O", "positioning_gbp": 100, "home": False}],
            destinations=[{"code": c, "label": c, "region": "asia", "hours_from_london": 11}
                          for c in ("BKK", "SIN", "HKG")],
            dates=["2027-03-01", "2027-03-08"], max_searches_per_run=5)
        cfg = bd.load_config(raw, today=date(2026, 11, 2))
        seen = set()
        for offset in range(3):  # 12 combinations / 5 per run => 3 runs cover all
            plan = bd.plan_searches(cfg, date(2026, 11, 2) + timedelta(days=offset))
            self.assertLessEqual(len(plan), 5)
            seen.update((s.origin, s.destination, s.date) for s in plan)
        self.assertEqual(len(seen), 12)
        again = bd.plan_searches(cfg, date(2026, 11, 2))
        self.assertEqual(again, bd.plan_searches(cfg, date(2026, 11, 2)))

    def test_shipped_example_config_loads_and_is_all_long_haul(self):
        cfg = bd.load_config(EXAMPLE.read_text(encoding="utf-8"), today=date(2026, 11, 2))
        self.assertGreaterEqual(len(cfg.origins), 4)
        self.assertTrue(any(not o.home for o in cfg.origins))
        self.assertTrue(all(d.hours_from_london > 8.0 for d in cfg.destinations))
        self.assertTrue(bd.plan_searches(cfg, date(2026, 11, 2)))


class EmailTests(JobCase):
    def test_email_has_clickable_links_dates_total_median_and_last_seen(self):
        cfg = raw_config(absolute_caps_gbp={})
        write_history(self.history, median_history("LHR", 2000))
        _, sink, _ = self.run_job({"LHR": 1300}, config=cfg)
        subject, html, text = sink.sent[0]
        self.assertIn("Business-class deal", subject)
        self.assertIn('<a href="https://example.test/LHR-BKK">', html)
        self.assertIn("2027-03-01", html)
        self.assertIn("£1,300", html)
        self.assertIn("below median", html)
        self.assertIn(NOW.date().isoformat(), html)
        self.assertIn("https://example.test/LHR-BKK", text)

    def test_email_escapes_text_and_has_no_personal_defaults(self):
        raw = raw_config()
        raw["destinations"][0]["label"] = "Bang<script>kok"
        _, sink, _ = self.run_job({"LHR": 900}, config=raw)
        html = sink.sent[0][1]
        self.assertNotIn("<script>", html)
        self.assertNotIn("@", html)

    def test_cold_start_is_said_plainly_in_the_email(self):
        _, sink, _ = self.run_job({"LHR": 900})
        self.assertIn("not enough history", sink.sent[0][1].lower())

    def test_a_cap_deal_above_a_warm_median_says_cap_not_a_negative_drop(self):
        write_history(self.history, median_history("LHR", 900))
        result, sink, _ = self.run_job({"LHR": 990})
        self.assertEqual([d.trigger for d in result.deals], ["cap"])
        html = sink.sent[0][1]
        self.assertIn("under the asia cap £1,000", html)
        self.assertNotIn("% below median", html)
        self.assertNotIn("not enough history", html.lower())


if __name__ == "__main__":
    unittest.main()
