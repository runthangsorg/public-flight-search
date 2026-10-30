"""The July mail's last trip pages may ride the attachment, and the owner may set a total ceiling (30 Oct 2026).

Owner decision, 30 Oct 2026: show the best trips in the body, and filter out any holiday above a total ceiling.
Two rules are pinned here,
from SYNTHETIC fares, trips and deals only (no real figure and no private config enters this repository):

* when even the short trip pages and the minimum resort cards will not fit Gmail's byte budget, the LAST trips'
  pages move to the attached full-detail file — never the first in the owner's order — and their rows stay in the
  at-a-glance table, with one line saying how many pages moved and where they went;
* an optional ``max_total_gbp`` leaves any holiday whose priced total for the party is above it out of the body,
  the attachment AND the over-budget list, and one note line says how many were left out. An unpriced item has no
  total and is never filtered.

Each test here fails against the source before the change (the config field does not exist; the body never moves a
page) and passes after it.
"""

from __future__ import annotations

import dataclasses
import json
import re
import unittest
from unittest.mock import patch

from public_flight_search import holiday_email, holidays as hol
from public_flight_search.config import ConfigError
from public_flight_search.holiday_email import (
    multi_centre_wanted,
    render_holiday_report_compact,
    render_holiday_report_full,
)
from public_flight_search.holidays import load_holiday_config
from public_flight_search.multi_centre import load_multi_centre

from test_holiday_email_compact import _config, _deal, visible_text
from test_multi_centre_reads import _multi_centre_read

NOW = "2026-10-30T09:00:00+00:00"
ATTACHMENT = "july-trips-full-2026-10-30.html"
#: Forced so the "still too big" case is deterministic; thirty trips cannot fit this.
BODY_BUDGET = 60_000
#: SYNTHETIC. The owner's real ceiling lives in the private config, never here.
CEILING = 10_000.0


def _ke_one(config) -> object:
    """The shipped Kenya trip, cloned rather than rewritten: a real shape under synthetic ids."""
    return next(trip for trip in load_multi_centre(config) if trip.id == "KE-01")


def _fares(wanted, totals):
    """One SYNTHETIC whole-trip read per trip that has an entry in ``totals``."""
    out = {}
    for want in wanted:
        total = totals.get(want["trip"])
        if total is None:
            continue
        out[hol.multi_centre_fare_key(want["trip"], want["legs"])] = _multi_centre_read(want, total=total)
    return out


def _render_body(config, *, fares, deals=(), attachment_name=ATTACHMENT) -> str:
    return render_holiday_report_compact(
        config, generated_at=NOW, deals=deals, multi_centre_fares=fares,
        attachment_name=attachment_name)


def _render_attachment(config, *, fares, deals=()) -> str:
    return render_holiday_report_full(
        config, generated_at=NOW, deals=deals, multi_centre_fares=fares)


def _table_ids(html: str) -> list[str]:
    """The trips the at-a-glance table links to, in its order."""
    table = html[html.index("Every option at a glance"):html.index('id="trips"')]
    return re.findall(r'href="#trip-([A-Z]{2}-\d+)"', table)


class LastTripPagesMoveToTheAttachmentTests(unittest.TestCase):
    def test_thirty_priced_trips_keep_the_body_inside_the_budget_and_all_thirty_in_the_attachment(self):
        config = _config()
        template = _ke_one(config)
        clones = [
            dataclasses.replace(template, id=f"ZZ-{index:02d}", title=f"Synthetic Kenya trip {index:02d}")
            for index in range(1, 31)
        ]
        with patch.object(holiday_email, "load_multi_centre", return_value=clones), \
                patch.object(hol, "LAST_OVER_BUDGET", ()), \
                patch.object(hol, "LAST_FILTERED_OUT", ()), \
                patch.object(hol, "LAST_CLIMATE_EXCLUDED", ()):
            fares = _fares(multi_centre_wanted(config),
                           {f"ZZ-{index:02d}": 9_000.0 for index in range(1, 31)})
            with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", BODY_BUDGET):
                body = _render_body(config, fares=fares, deals=())
            attachment = _render_attachment(config, fares=fares, deals=())

        self.assertLessEqual(len(body.encode("utf-8")), BODY_BUDGET,
                             "the body is over the byte budget the renderer was given")
        self.assertEqual(_table_ids(body), [f"ZZ-{index:02d}" for index in range(1, 31)],
                         "a trip left the table when its page moved")
        body_pages = re.findall(r'id="trip-(ZZ-\d+)"', body)
        moved = 30 - len(body_pages)
        self.assertGreater(moved, 0, "all thirty pages fitted a budget they cannot fit")
        self.assertIn("ZZ-01", body_pages, "the first trip in the owner's order lost its page")
        self.assertEqual(body_pages, [f"ZZ-{index:02d}" for index in range(1, len(body_pages) + 1)],
                         "pages moved from somewhere other than the end of the owner's order")
        self.assertIn(
            f"{moved} more trip page(s) are in the attached file, {ATTACHMENT}: "
            "every trip is still in the table above.",
            visible_text(body),
        )
        attachment_pages = re.findall(r'id="trip-(ZZ-\d+)"', attachment)
        self.assertEqual(sorted(attachment_pages), [f"ZZ-{index:02d}" for index in range(1, 31)],
                         "the attachment must keep every page")


class TotalCeilingTests(unittest.TestCase):
    """A holiday priced above the owner's optional ceiling is not shown at all."""

    def setUp(self):
        # Pre-change this line is the failure: the config has no such field.
        self.config = dataclasses.replace(_config(), max_total_gbp=CEILING)
        template = _ke_one(self.config)
        self.above = dataclasses.replace(
            template, id="ZZ-91", title="Synthetic over-ceiling trip",
            cost_low_gbp=30_000.0, cost_high_gbp=35_000.0)
        self.below = dataclasses.replace(
            template, id="ZZ-92", title="Synthetic within-ceiling trip",
            cost_low_gbp=5_000.0, cost_high_gbp=7_000.0)
        self.unpriced = dataclasses.replace(
            template, id="ZZ-93", title="Synthetic unpriced trip",
            cost_low_gbp=0.0, cost_high_gbp=0.0)
        self.deals = [
            _deal(0, resort_name="Synthetic over-ceiling resort",
                  flight_price_total_gbp=12_000.0, hotel_price_total_gbp=17_900.0,
                  uk_ground_gbp=50.0, transfer_gbp=50.0,
                  true_d2d_gbp=30_000.0, total_package_price_gbp=30_000.0),
            _deal(1, resort_name="Synthetic within-ceiling resort",
                  flight_price_total_gbp=2_000.0, hotel_price_total_gbp=2_960.0,
                  uk_ground_gbp=15.0, transfer_gbp=25.0,
                  true_d2d_gbp=5_000.0, total_package_price_gbp=5_000.0),
        ]

    def _both(self, *, trips, deals, read_totals, over_budget=(), config=None):
        config = config or self.config
        with patch.object(holiday_email, "load_multi_centre", return_value=list(trips)), \
                patch.object(hol, "LAST_OVER_BUDGET", tuple(over_budget)), \
                patch.object(hol, "LAST_FILTERED_OUT", ()), \
                patch.object(hol, "LAST_CLIMATE_EXCLUDED", ()):
            fares = _fares(multi_centre_wanted(config), read_totals)
            return (_render_body(config, fares=fares, deals=deals),
                    _render_attachment(config, fares=fares, deals=deals))

    def test_a_priced_card_and_trip_above_the_ceiling_are_left_out_while_the_below_and_unpriced_ones_stay(self):
        body, attachment = self._both(
            trips=[self.above, self.below, self.unpriced],
            deals=self.deals,
            read_totals={"ZZ-91": 29_000.0, "ZZ-92": 4_000.0},
        )
        for html, where in ((body, "body"), (attachment, "attachment")):
            text = visible_text(html)
            self.assertNotIn("Synthetic over-ceiling resort", text, where)
            self.assertNotIn("Synthetic over-ceiling trip", text, where)
            self.assertNotIn("ZZ-91", _table_ids(html), where)
            self.assertIn("Synthetic within-ceiling resort", text, where)
            self.assertIn("Synthetic within-ceiling trip", text, where)
            self.assertIn("Synthetic unpriced trip", text, where)
        self.assertIn("2 holiday(s) over £10,000 left out", visible_text(body))
        self.assertIn("2 holiday(s) over £10,000 left out", visible_text(attachment))

    def test_a_resort_over_the_ceiling_is_not_offered_in_the_over_budget_list_either(self):
        over = {"destination_key": "lombok", "destination_label": "Kuta Mandalika, Lombok",
                "resort_name": "Synthetic over-ceiling over-budget resort",
                "true_d2d": 30_000.0, "max_budget_gbp": 12_000.0}
        within = {"destination_key": "lombok", "destination_label": "Kuta Mandalika, Lombok",
                  "resort_name": "Synthetic within-ceiling over-budget resort",
                  "true_d2d": 14_000.0, "max_budget_gbp": 12_000.0}
        # The ceiling must sit ABOVE the budget here, or every over-budget row
        # is also over the ceiling and the surviving row below proves nothing.
        config = dataclasses.replace(_config(), max_total_gbp=15_000.0)
        body, attachment = self._both(
            trips=[self.below, self.unpriced], deals=(), read_totals={},
            over_budget=(over, within), config=config,
        )
        for html, where in ((body, "body"), (attachment, "attachment")):
            text = visible_text(html)
            self.assertNotIn("Synthetic over-ceiling over-budget resort", text, where)
            self.assertIn("Synthetic within-ceiling over-budget resort", text, where)
        self.assertIn("1 holiday(s) over £15,000 left out", visible_text(body))


class CeilingConfigTests(unittest.TestCase):
    def _payload(self, **extra) -> str:
        payload = {
            "report_title": "Test",
            "party": {"travellers": 2, "rooms": [2]},
            "departure_window": ["06:00", "21:00"],
            "origins": ["LHR"],
            "outbound_dates": ["2026-12-20"],
            "return_dates": ["2026-12-28"],
            "destinations": [{"key": "antalya", "label": "Antalya", "airports": ["AYT"]}],
        }
        payload.update(extra)
        return json.dumps(payload)

    def test_a_positive_ceiling_loads_and_an_absent_one_means_no_ceiling(self):
        self.assertIsNone(load_holiday_config(self._payload()).max_total_gbp)
        self.assertIsNone(load_holiday_config(self._payload(max_total_gbp=None)).max_total_gbp)
        self.assertEqual(load_holiday_config(self._payload(max_total_gbp=15_000)).max_total_gbp, 15_000.0)
        self.assertEqual(load_holiday_config(self._payload(max_total_gbp=10_000.5)).max_total_gbp, 10_000.5)

    def test_the_ceiling_is_refused_unless_it_is_a_positive_number(self):
        # The control matters: before this field existed, every value below was
        # refused as an unknown key, so the refusals would pass vacuously.
        self.assertEqual(load_holiday_config(self._payload(max_total_gbp=15_000)).max_total_gbp, 15_000.0)
        for bad in (0, -1, -0.5, "15000", [15000], {"amount": 15000}, True):
            with self.subTest(max_total_gbp=bad):
                with self.assertRaises(ConfigError):
                    load_holiday_config(self._payload(max_total_gbp=bad))
