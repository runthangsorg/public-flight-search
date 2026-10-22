"""The July report leads with what the owner asked for, and says how old its evidence is (22 Oct 2026).

Owner, 22 Oct: "why aren't the new safari holidays making it into these emails ... you should have rewritten it from
scratch already". The 22 Oct e-mail did carry eleven Africa trips, but below four Asian resort cards, every row an
estimate, with hotel reads 17 days old and nothing saying so at the top. These tests pin the new first screen:

* a freshness strip (how old each kind of evidence is, and a plain warning past a week);
* one at-a-glance table of EVERY option in the owner's order: Tanzania safari + Zanzibar first, other Africa, the
  Asian two-centre trips, then the single resorts;
* the Africa block ahead of the resort cards, in the HTML and in the plain text.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    _multi_centre_rows,
    multi_centre_wanted,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)

from test_holiday_email_compact import GENERATED_AT, _config, _deals, visible_text
from test_multi_centre_reads import _multi_centre_read

#: A run on 22 Oct 2026 with the evidence the 22 Oct e-mail actually had.
NOW = "2026-10-22T13:25:00+00:00"
STAMPS_AS_ON_22_OCT = {
    "resort_flights": "2026-10-15T13:25:00+00:00",     # exactly 7 days: not stale yet
    "safari_flights": "2026-10-20T13:25:00+00:00",     # 2 days
    "hotel_rates": "2026-10-05T13:25:00+00:00",        # 17 days (the 22 Oct e-mail's "Seen 17 days ago")
    "operator_packages": "2026-10-05T13:25:00+00:00",  # 17 days
}
STAMPS_ALL_FRESH = {k: "2026-10-22T03:40:00+00:00" for k in STAMPS_AS_ON_22_OCT}

OVERVIEW = "Every option at a glance"
STRIP = "How current this is"
AFRICA = "Africa safari + beach"


def _fares_with_one_africa_read():
    """A registry holding one SYNTHETIC dated flight read (20 Oct) for the first Africa trip the report asks about."""
    config = _config()
    africa_ids = {r["trip"].id for r in _rows() if getattr(r["trip"], "region", "") == "africa"}
    want = next(w for w in multi_centre_wanted(config) if w["trip"] in africa_ids)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "stopover_reads_synthetic.json"
        path.write_text(json.dumps({
            "schema": hol.STOPOVER_READS_SCHEMA,
            "rows": [_multi_centre_read(want, observed_at="2026-10-20T10:00:00+00:00")],
        }), encoding="utf-8")
        _stops, fares = hol.load_batch_reads(str(path))
    hol.consume_stopover_skip_log()
    return fares


def _html(stamps=None, **kw):
    return render_holiday_report_compact(
        _config(), generated_at=NOW, deals=_deals(4), evidence_stamps=stamps, **kw)


def _text(stamps=None, **kw):
    return render_holiday_report_compact_text(
        _config(), generated_at=NOW, deals=_deals(4), evidence_stamps=stamps, **kw)


def _overview_region(html: str) -> str:
    start = html.index(OVERVIEW)
    end = html.index(AFRICA)
    return html[start:end]


def _rows():
    return _multi_centre_rows(_config())


def _africa_titles():
    return [r["trip"].title for r in _rows() if getattr(r["trip"], "region", "") == "africa"]


def _asia_titles():
    return [r["trip"].title for r in _rows() if getattr(r["trip"], "region", "") != "africa"]


class FirstScreenOrderTests(unittest.TestCase):
    def test_the_strip_then_the_overview_then_africa_then_the_resort_cards(self):
        html = _html(STAMPS_AS_ON_22_OCT)
        order = [html.index(STRIP), html.index(OVERVIEW), html.index(AFRICA), html.index('id="deal-1"')]
        self.assertEqual(order, sorted(order), "freshness, overview, Africa block, then the resort cards")

    def test_the_two_centre_block_and_the_rest_still_follow_the_cards(self):
        html = _html(STAMPS_AS_ON_22_OCT)
        self.assertGreater(html.index("Two-centre trips"), html.index('id="deal-4"'))
        self.assertGreater(html.index("Over the"), html.index("Two-centre trips")) if "Over the" in html else None

    def test_the_plain_text_twin_has_the_same_order(self):
        text = _text(STAMPS_AS_ON_22_OCT)
        order = [text.index(STRIP), text.index(OVERVIEW), text.index(AFRICA), text.index("Test Resort 0")]
        # the resort name appears in the overview too, so the card is the LAST occurrence before the two-centre block
        self.assertEqual(order[:3], sorted(order[:3]))
        self.assertGreater(text.rindex("Test Resort 0", 0, text.index("Two-centre trips")), text.index(AFRICA))


class OverviewCoversEveryOptionTests(unittest.TestCase):
    def test_every_africa_trip_and_every_asian_trip_and_every_resort_is_in_the_table(self):
        region = visible_text(_overview_region(_html(STAMPS_AS_ON_22_OCT)))
        for title in _africa_titles() + _asia_titles():
            self.assertIn(title, region, f"missing from the at-a-glance table: {title}")
        for index in range(4):
            self.assertIn(f"Test Resort {index}", region)

    def test_the_owners_order_tanzania_safari_plus_zanzibar_first(self):
        region = visible_text(_overview_region(_html(STAMPS_AS_ON_22_OCT)))
        positions = {t: region.index(t) for t in _africa_titles() + _asia_titles()}
        tz = [t for t in _africa_titles()
              if "Zanzibar" in t and re.search(r"Serengeti|Tanzania|Ngorongoro|Nyerere|Sayari", t)]
        other_africa = [t for t in _africa_titles() if t not in tz]
        self.assertTrue(tz, "the fixture must have Tanzania + Zanzibar trips")
        self.assertLess(max(positions[t] for t in tz), min(positions[t] for t in other_africa),
                        "every Tanzania safari + Zanzibar trip comes before the other Africa trips")
        self.assertLess(max(positions[t] for t in _africa_titles()), min(positions[t] for t in _asia_titles()),
                        "Africa before the Asian two-centre trips")
        self.assertLess(max(positions[t] for t in _asia_titles()), region.index("Test Resort 0"),
                        "the single resorts come last")

    def test_every_row_says_what_it_is_made_of_and_whether_it_fits(self):
        region = visible_text(_overview_region(_html(STAMPS_AS_ON_22_OCT, multi_centre_fares=_fares_with_one_africa_read())))
        for word in ("estimate", "operator package", "self-build", "over", "fits"):
            self.assertIn(word, region)
        self.assertRegex(region, r"flights read 20 Oct", "a trip with a read flight fare says when it was read")

    def test_the_overview_is_part_of_the_plain_text_too(self):
        text = _text(STAMPS_AS_ON_22_OCT)
        start, end = text.index(OVERVIEW), text.index(AFRICA)
        for title in _africa_titles() + _asia_titles():
            self.assertIn(title, text[start:end])


class FreshnessStripTests(unittest.TestCase):
    def test_it_names_each_kind_of_evidence_with_its_age_in_days(self):
        strip = visible_text(_html(STAMPS_AS_ON_22_OCT))
        strip = strip[strip.index(STRIP):strip.index(OVERVIEW)]
        for label, days in (("flights", "7 days"), ("Safari", "2 days"), ("Hotel", "17 days"), ("package", "17 days")):
            self.assertIn(label.lower(), strip.lower())
            self.assertIn(days, strip)

    def test_anything_older_than_a_week_is_called_stale_in_plain_words(self):
        strip = visible_text(_html(STAMPS_AS_ON_22_OCT))
        strip = strip[strip.index(STRIP):strip.index(OVERVIEW)]
        self.assertIn("older than a week", strip)
        self.assertIn("stale", strip.lower())

    def test_a_week_exactly_is_not_stale_but_eight_days_is(self):
        seven = dict(STAMPS_ALL_FRESH, resort_flights="2026-10-15T13:25:00+00:00")
        eight = dict(STAMPS_ALL_FRESH, resort_flights="2026-10-14T13:25:00+00:00")
        self.assertNotIn("older than a week", visible_text(_html(seven)))
        self.assertIn("older than a week", visible_text(_html(eight)))

    def test_all_fresh_evidence_prints_no_warning(self):
        text = visible_text(_html(STAMPS_ALL_FRESH))
        self.assertNotIn("older than a week", text)
        self.assertNotIn("stale", text.lower().replace("stale-cache", ""))
        self.assertIn("today", text[text.index(STRIP):text.index(OVERVIEW)])

    def test_missing_stamps_say_so_instead_of_pretending(self):
        for stamps in (None, {}, {"resort_flights": "", "hotel_rates": None}):
            text = visible_text(_html(stamps))
            strip = text[text.index(STRIP):text.index(OVERVIEW)]
            self.assertIn("no reads loaded", strip, stamps)

    def test_the_plain_text_carries_the_strip_and_the_warning(self):
        text = _text(STAMPS_AS_ON_22_OCT)
        strip = text[text.index(STRIP):text.index(OVERVIEW)]
        self.assertIn("17 days", strip)
        self.assertIn("older than a week", strip)


class JobPassesTheStampsTests(unittest.TestCase):
    def test_the_newest_read_of_each_kind_is_picked_from_objects_dicts_and_lists(self):
        from public_flight_search.jobs import _newest_stamp

        class Entry:
            def __init__(self, stamp):
                self.observed_at = stamp

        self.assertEqual(_newest_stamp([Entry("2026-10-05T01:00:00+00:00"), Entry("2026-10-07T01:00:00+00:00")]),
                         "2026-10-07T01:00:00+00:00")
        self.assertEqual(_newest_stamp([{"observed_at": "2026-10-20T10:00:00+00:00"}, {"observed_at": ""}]),
                         "2026-10-20T10:00:00+00:00")
        self.assertEqual(_newest_stamp([[Entry("2026-10-01T00:00:00+00:00"), {"observed_at": "2026-10-09T00:00:00+00:00"}]]),
                         "2026-10-09T00:00:00+00:00")
        self.assertEqual(_newest_stamp([]), "")
        self.assertEqual(_newest_stamp(None), "")

    def test_a_planner_run_with_no_evidence_reports_empty_stamps_not_a_crash(self):
        import os
        import tempfile
        from public_flight_search.jobs import run_holiday_planner

        with tempfile.TemporaryDirectory() as directory:
            absent = lambda name: os.path.join(directory, name)  # noqa: E731
            result = run_holiday_planner(
                dry_run=True,
                config_path=str(Path(__file__).parents[1] / "examples" / "july_holiday_config.json"),
                hotel_evidence_path=absent("hotel.json"), live_evidence_path=absent("live.json"),
                package_evidence_path=absent("package.json"), stopover_reads_path=absent("reads.json"),
            )
        self.assertEqual(set(result["evidence_stamps"]),
                         {"safari_flights", "resort_flights", "hotel_rates", "operator_packages"})
        self.assertEqual({v for v in result["evidence_stamps"].values()}, {""})


class SizeTests(unittest.TestCase):
    def test_the_report_with_the_overview_stays_inside_the_gmail_budget(self):
        html = _html(STAMPS_AS_ON_22_OCT)
        self.assertLessEqual(len(html.encode("utf-8")), hol.EMAIL_HTML_BUDGET_BYTES)
        full = render_holiday_report_compact(
            _config(), generated_at=NOW, deals=_deals(12), evidence_stamps=STAMPS_AS_ON_22_OCT)
        self.assertLessEqual(len(full.encode("utf-8")), hol.EMAIL_HTML_BUDGET_BYTES)
        self.assertIn(AFRICA, full)
        self.assertIn(OVERVIEW, full, "the overview is reserved room first, so the cards are what gets cut")


if __name__ == "__main__":
    unittest.main()
