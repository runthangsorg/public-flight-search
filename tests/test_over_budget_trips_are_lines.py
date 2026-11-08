"""Over-budget trips stop taking full pages in the body (owner, 8 Nov 2026).

A trip whose low end (the cheapest total the table prints for it) is more than 20% over the budget gets ONE line in an
"Over budget" list in the e-mail body: its title, its nights, its low end, how much over, and where its page is (the
full-detail attachment). It keeps its full page in the attachment and in the plain-text part. Synthetic reads.
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from public_flight_search import holiday_email as he
from public_flight_search import holidays as hol
from public_flight_search.holiday_email import _multi_centre_rows, multi_centre_wanted

from test_holiday_email_compact import _config, _deals, visible_text
from test_price_says_what_it_covers import deal_read, load
from test_trip_dossiers import NOW, STAMPS, _ids

ATTACHMENT = "july-trips-full-2026-11-08.html"
BUDGET = 12_000.0


def _fares():
    return load([deal_read(w["trip"], "ECONOMY", 5_000) for w in multi_centre_wanted(_config())])


def _render(fares, *, budget=hol.EMAIL_HTML_BUDGET_BYTES):
    config = _config(over_budget_lines=True)
    kw = dict(generated_at=NOW, deals=_deals(2), evidence_stamps=STAMPS, multi_centre_fares=fares)
    with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", budget):
        body = he.render_holiday_report_compact(config, attachment_name=ATTACHMENT, **kw)
    return body, he.render_holiday_report_compact_text(config, **kw), he.render_holiday_report_full(config, **kw)


class TheThresholdTests(unittest.TestCase):
    def test_more_than_twenty_percent_over_is_a_line_and_twenty_percent_is_not(self):
        self.assertEqual(he.OVER_BUDGET_LINE_FACTOR, 1.2)
        self.assertFalse(he.over_budget_line(14_400.0, BUDGET))
        self.assertTrue(he.over_budget_line(14_401.0, BUDGET))
        self.assertFalse(he.over_budget_line(9_000.0, BUDGET))
        self.assertFalse(he.over_budget_line(50_000.0, 0.0), "no budget, no verdict, no line")
        self.assertFalse(he.over_budget_line(None, BUDGET), "an unpriced trip is never a line")


class TheBodyListsThemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fares = _fares()
        cls.rows = {r["trip"].id: r for r in _multi_centre_rows(_config(), fares=cls.fares)}
        cls.over = {i for i, r in cls.rows.items() if he.over_budget_line(he.trip_low_end(r), BUDGET)}
        cls.within = set(cls.rows) - cls.over
        cls.body, cls.text, cls.full = _render(cls.fares, budget=10 ** 9)

    def test_the_fixture_has_both_kinds(self):
        self.assertIn("AF-04", self.over)          # from £19,945
        self.assertIn("AF-10", self.within)        # £9,164 all economy
        self.assertIn("MC-01", self.within)        # from £13,032, under £14,400

    def test_an_over_budget_trip_has_no_page_in_the_body_but_one_line(self):
        pages = set(_ids(self.body))
        self.assertFalse(pages & self.over, "no full page in the body for a trip more than 20% over")
        self.assertEqual(pages, self.within, "every other trip keeps its page")
        text = visible_text(self.body)
        self.assertEqual(text.count("Over budget"), 1)
        block = text[text.index("Over budget"):]
        for ident in self.over:
            row = self.rows[ident]
            low = he.trip_low_end(row)
            self.assertRegex(block, re.escape(row["trip"].title) + r"\s*·\s*" + str(row["trip"].total_nights)
                             + r" nights · " + re.escape(he._gbp(low)) + r"[^·]*· " + re.escape(he._gbp(low - BUDGET))
                             + " over", ident)
        self.assertIn(ATTACHMENT, block)

    def test_the_low_end_is_the_figure_the_table_prints(self):
        # An itemised trip's table figure is its cheapest cabin total, not the catalogue's low end (EU-02: the table
        # prints "Economy £X" and the line must say the same £X).
        row = self.rows["EU-02"]
        cheapest = min(item["total"] for item in row["cabin_totals"])
        self.assertNotEqual(round(cheapest), round(row["low"]), "the fixture needs the two figures to differ")
        self.assertEqual(he.trip_low_end(row), cheapest)
        self.assertEqual(he.trip_low_end(self.rows["AF-04"]), self.rows["AF-04"]["low"])
        block = visible_text(self.body)[visible_text(self.body).index("Over budget"):]
        self.assertIn(f"{he._gbp(cheapest)} low end", block)
        self.assertNotIn(f"{he._gbp(row['low'])} low end", block)

    def test_the_tables_name_links_to_the_line_when_the_trip_has_no_page(self):
        table = self.body[self.body.index("Every option at a glance"):self.body.index('id="trips"')]
        for ident in self.over:
            self.assertNotIn(f'href="#trip-{ident}"', table, ident)
        self.assertEqual(table.count('href="#over-budget"'), len(self.over))
        for ident in self.within:
            self.assertIn(f'href="#trip-{ident}"', table, ident)

    def test_each_line_is_a_link_to_the_attachment_page(self):
        start = self.body.index('id="over-budget"')
        block = self.body[start:self.body.index("</div></div>", start)]
        for ident in self.over:
            self.assertIn(f'href="{ATTACHMENT}#trip-{ident}"', block, ident)

    def test_the_attachment_and_the_text_keep_every_full_page(self):
        self.assertEqual(set(_ids(self.full)), set(self.rows))
        for ident in self.over:
            self.assertIn(f"{self.rows[ident]['trip'].title}\n", self.text)
        self.assertNotIn('id="over-budget"', self.full)

    def test_no_link_in_the_start_box_points_at_a_page_the_body_does_not_have(self):
        box = self.body[self.body.index('id="start"'):self.body.index("How current this is")]
        ids = set(re.findall(r'id="([^"]+)"', self.body))
        for anchor in re.findall(r'href="#([^"]+)"', box):
            self.assertIn(anchor, ids, anchor)

    def test_the_real_budget_still_fits(self):
        body, _text, _full = _render(self.fares)
        self.assertLessEqual(len(body.encode("utf-8")), hol.EMAIL_HTML_BUDGET_BYTES)
        self.assertFalse(set(_ids(body)) & self.over)

# Rule 4 (8 Nov 2026) is tested in test_business_over_eight_hours; these tests lay out pages from one-journey reads.
from leg_rule_off import lift_leg_rule as _lift_leg_rule  # noqa: E402

_LEG_RULE = _lift_leg_rule()


def setUpModule():
    _LEG_RULE.start()


def tearDownModule():
    _LEG_RULE.stop()


if __name__ == "__main__":
    unittest.main()
