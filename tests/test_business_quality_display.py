"""Business class: the quality-carrier list and the display rule that replaced "only when it is a deal".

The 8 Nov 2026 morning rule ("prefer economy ... unless the business class is a really good deal and good airline and
long") hid a Business figure unless it fit the budget or cost at most £1,200 a head more than Economy. The evening rule
4 ("reject economy where a leg is more than 8hrs, has to be business") replaced the price test for legs over 8 hours:
a Business read is shown whatever it costs, an Economy read with a leg over 8 hours is not (see
``test_business_over_eight_hours``), and what stays is the quality-carrier list, which now includes Kenya Airways and
Ethiopian. This file holds the list, the duration parser, and how the trip pages and resort cards show the result.
Synthetic reads throughout.
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search import holiday_email as he
from public_flight_search.business_airlines import BUSINESS_QUALITY_CARRIERS, quality_business_carrier
from public_flight_search.holidays import load_holiday_config

from test_holiday_email_compact import JULY, _config, _deals, visible_text
from test_price_says_what_it_covers import BUILD, PACKAGE, deal_read, load
from test_trip_dossiers import NOW, STAMPS, UNLIMITED, _attachment, _html, _slice, _text


def _overview_line(text: str, start: str) -> str:
    return next(line for line in text.splitlines() if line.strip().startswith(f"· {start}"))


class TheQualityListTests(unittest.TestCase):
    def test_the_list_holds_the_major_full_service_carriers(self):
        codes = {code for code, _name in BUSINESS_QUALITY_CARRIERS}
        self.assertEqual(codes, {"QR", "EK", "EY", "SQ", "CX", "JL", "NH", "TK", "BA", "VS", "LX", "LH", "KL", "AF",
                                 "WY", "QF", "KQ", "ET"})

    def test_names_codes_and_the_pages_own_spellings_are_matched(self):
        for name in ("Qatar Airways", "Emirates", "Etihad Airways", "Singapore Airlines", "Cathay Pacific", "JAL",
                     "Japan Airlines", "ANA", "Turkish Airlines", "British Airways", "Virgin Atlantic", "SWISS",
                     "Lufthansa", "KLM", "Air France", "Oman Air", "Qantas", "QR", "Qatar Airways, British Airways",
                     # Owner, 8 Nov 2026: Kenya Airways and Ethiopian count as good airlines for business.
                     "Kenya Airways", "Ethiopian Airlines", "Ethiopian Air", "KQ", "ET", "Kenya Airways, Qatar Airways"):
            self.assertTrue(quality_business_carrier(name), name)

    def test_anything_else_or_a_mixture_or_an_unnamed_carrier_is_not(self):
        for name in ("Egyptair, Emirates", "Emirates, Airlink", "Multiple airlines",
                     "British AirwaysIberia", "", "RwandAir", "Air India"):
            self.assertFalse(quality_business_carrier(name), name)


class DurationWordsTests(unittest.TestCase):
    def test_both_formats_the_reads_use(self):
        self.assertAlmostEqual(he.duration_hours("12h 50m"), 12 + 50 / 60)
        self.assertAlmostEqual(he.duration_hours("12 hrs 55 min"), 12 + 55 / 60)
        self.assertAlmostEqual(he.duration_hours("8h"), 8.0)
        self.assertAlmostEqual(he.duration_hours("45m"), 0.75)
        self.assertIsNone(he.duration_hours(""))
        self.assertIsNone(he.duration_hours("soon"))


class TheTripPagesTests(unittest.TestCase):
    def _render(self, rows, config=None):
        fares = load(rows)
        config = config or _config()
        with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", UNLIMITED):
            html = he.render_holiday_report_compact(config, generated_at=NOW, deals=_deals(1),
                                                    evidence_stamps=STAMPS, multi_centre_fares=fares)
        text = he.render_holiday_report_compact_text(config, generated_at=NOW, deals=_deals(1),
                                                     evidence_stamps=STAMPS, multi_centre_fares=fares)
        full = he.render_holiday_report_full(config, generated_at=NOW, deals=_deals(1),
                                             evidence_stamps=STAMPS, multi_centre_fares=fares)
        return html, text, full

    def test_a_good_airline_on_a_long_leg_is_shown_whatever_it_costs(self):
        # £15,000 more than Economy for 5 is £3,000 a head: the old premium cap hid it, rule 4 shows it, because the
        # Economy read has a leg over 8 hours and so is not offered at all.
        html, text, _full = self._render([deal_read(PACKAGE, "ECONOMY", 5_000), deal_read(PACKAGE, "MIXED", 20_000)])
        self.assertIn("business long-haul £20,000", _overview_line(text, "Zanzibar 8 nights"))
        self.assertIn("£20,000", visible_text(_slice(html, f"trip-{PACKAGE}")))
        self.assertNotIn("£5,000", visible_text(_slice(html, f"trip-{PACKAGE}")))
        self.assertNotIn("Business not shown", visible_text(_slice(html, f"trip-{PACKAGE}")))

    def _assert_hidden(self, html, text, full):
        line = "Business not shown: its long flight is not on a quality carrier"
        for where, part in (("body", visible_text(_slice(html, f"trip-{PACKAGE}"))),
                            ("attachment", visible_text(_slice(full, f"trip-{PACKAGE}")))):
            self.assertIn(line, part, where)
            self.assertNotRegex(part, r"(?i)with business long-haul", where)
        self.assertNotIn("business long-haul £", _overview_line(text, "Zanzibar 8 nights"))

    def test_a_carrier_off_the_quality_list_is_not_shown(self):
        html, text, full = self._render([deal_read(PACKAGE, "ECONOMY", 5_000),
                                         deal_read(PACKAGE, "MIXED", 9_000, carrier="RwandAir")])
        self._assert_hidden(html, text, full)
        self.assertNotIn("£9,000", visible_text(_slice(html, f"trip-{PACKAGE}")))

    def test_no_long_flight_in_business_is_not_shown_and_short_economy_is(self):
        html, text, full = self._render([deal_read(PACKAGE, "ECONOMY", 5_000, long_hours=7),
                                         deal_read(PACKAGE, "MIXED", 9_000, long_hours=7)])
        self._assert_hidden(html, text, full)
        self.assertIn("economy £5,000", _overview_line(text, "Zanzibar 8 nights"))

    def test_the_retired_premium_cap_still_loads_and_changes_nothing(self):
        raw = json.loads(JULY.read_text(encoding="utf-8"))
        raw["business_max_premium_pp_gbp"] = 500
        config = load_holiday_config(json.dumps(raw))
        object.__setattr__(config, "complete_price_only", False)
        object.__setattr__(config, "over_budget_lines", False)
        html, text, _full = self._render([deal_read(PACKAGE, "MIXED", 9_000)], config=config)
        self.assertIn("business long-haul £9,000", _overview_line(text, "Zanzibar 8 nights"))

    def test_an_itemised_trip_shows_its_business_total_over_the_budget_without_a_verdict_of_hidden(self):
        html, text, _full = self._render([deal_read(BUILD, "ECONOMY", 4_000), deal_read(BUILD, "MIXED", 20_000)])
        page = visible_text(_slice(html, f"trip-{BUILD}"))
        self.assertNotIn("Business not shown", page)
        self.assertRegex(page, r"(?i)with business long-haul")
        self.assertNotIn("£4,000", page, "Economy's read is not shown: its leg is over 8 hours")


class TheResortCardsTests(unittest.TestCase):
    """A card's Business row obeys the same rule."""

    def _card_rows(self, carrier, total, budget):
        from test_business_row import _base_card, _fare, _load

        config, base = _base_card()
        config = dataclasses.replace(config, max_budget_gbp=budget)
        pair = (base.outbound_date, base.return_date)
        records = _load(config, [_fare(base.destination_airport, cabin="BUSINESS", total=total, stops=1,
                                       carrier=carrier, pair=pair, origin=base.origin, duration_minutes=14 * 60)])
        deal = hol.collect_holiday_deals(config, max_budget_gbp=budget, live_flight_offers=records)[0]
        return deal, he.flight_rows(deal)

    def test_a_good_airline_keeps_its_row_whatever_the_budget(self):
        deal, rows = self._card_rows("Qatar Airways", 26_000.0, 60_000.0)
        self.assertIn("Business", [cabin for cabin, _route, _total in rows])
        self.assertEqual(he.business_note_words(deal), "")

    def test_a_carrier_off_the_list_loses_its_row_and_says_why(self):
        deal, rows = self._card_rows("SYNTHETIC carrier", 26_000.0, 60_000.0)
        priced = [total for cabin, _route, total in rows if cabin == "Business" and str(total).startswith("£")]
        self.assertEqual(priced, [])
        self.assertEqual(he.business_note_words(deal), "Business not shown: its long flight is not on a quality carrier")


if __name__ == "__main__":
    unittest.main()
