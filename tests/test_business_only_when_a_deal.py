"""Business class only when it is a real deal (owner, 8 Nov 2026).

Verbatim: "prefer economy flights ... rather than wasting money on business class unless the business class is a really
good deal and good airline and long". A business figure is shown only when ALL of these hold:

* a long-haul flight over 8 hours is flown in Business;
* every carrier on those Business flights is on the quality list (``business_airlines.BUSINESS_QUALITY_CARRIERS``);
* the business whole-trip total keeps the trip inside the budget, OR the business premium over economy is at most
  ``BUSINESS_DEAL_MAX_PREMIUM_PP_GBP`` per person (default £1,200, a config may set ``business_max_premium_pp_gbp``).

Otherwise the page says one short line, "Business not shown: not a deal for these dates (economy is £X less for 5)",
and Economy is the headline everywhere. Synthetic reads throughout.
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
                                 "WY", "QF"})

    def test_names_codes_and_the_pages_own_spellings_are_matched(self):
        for name in ("Qatar Airways", "Emirates", "Etihad Airways", "Singapore Airlines", "Cathay Pacific", "JAL",
                     "Japan Airlines", "ANA", "Turkish Airlines", "British Airways", "Virgin Atlantic", "SWISS",
                     "Lufthansa", "KLM", "Air France", "Oman Air", "Qantas", "QR", "Qatar Airways, British Airways"):
            self.assertTrue(quality_business_carrier(name), name)

    def test_anything_else_or_a_mixture_or_an_unnamed_carrier_is_not(self):
        for name in ("Kenya Airways", "Egyptair, Emirates", "Emirates, Airlink", "Multiple airlines",
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

    def test_a_good_airline_long_and_cheap_enough_is_shown(self):
        html, text, _full = self._render([deal_read(PACKAGE, "ECONOMY", 5_000), deal_read(PACKAGE, "MIXED", 9_000)])
        self.assertIn("business long-haul £9,000", _overview_line(text, "Zanzibar 8 nights"))
        self.assertIn("£9,000", visible_text(_slice(html, f"trip-{PACKAGE}")))
        self.assertNotIn("Business not shown", visible_text(_slice(html, f"trip-{PACKAGE}")))

    def _assert_hidden(self, html, text, full, saving):
        line = f"Business not shown: not a deal for these dates (economy is {saving} less for 5)"
        for where, part in (("body", visible_text(_slice(html, f"trip-{PACKAGE}"))),
                            ("attachment", visible_text(_slice(full, f"trip-{PACKAGE}")))):
            self.assertIn(line, part, where)
            self.assertNotRegex(part, r"(?i)with business long-haul", where)
        self.assertIn(line, text)
        overview = _overview_line(text, "Zanzibar 8 nights")
        self.assertIn("economy £5,000", overview)
        self.assertNotIn("business long-haul £", overview)

    def test_a_carrier_off_the_quality_list_is_not_a_deal(self):
        html, text, full = self._render([deal_read(PACKAGE, "ECONOMY", 5_000),
                                         deal_read(PACKAGE, "MIXED", 9_000, carrier="Kenya Airways")])
        self._assert_hidden(html, text, full, "£4,000")
        self.assertNotIn("£9,000", visible_text(_slice(html, f"trip-{PACKAGE}")))

    def test_a_premium_over_the_per_person_cap_is_not_a_deal(self):
        # £15,000 more for 5 is £3,000 a head, over the £1,200 cap, and a package total cannot be re-priced in Business.
        html, text, full = self._render([deal_read(PACKAGE, "ECONOMY", 5_000), deal_read(PACKAGE, "MIXED", 20_000)])
        self._assert_hidden(html, text, full, "£15,000")

    def test_no_long_flight_in_business_is_not_a_deal(self):
        html, text, full = self._render([deal_read(PACKAGE, "ECONOMY", 5_000),
                                         deal_read(PACKAGE, "MIXED", 9_000, long_hours=7)])
        self._assert_hidden(html, text, full, "£4,000")

    def test_the_cap_is_configurable(self):
        self.assertEqual(he.BUSINESS_DEAL_MAX_PREMIUM_PP_GBP, 1_200)
        raw = json.loads(JULY.read_text(encoding="utf-8"))
        raw["business_max_premium_pp_gbp"] = 500
        config = load_holiday_config(json.dumps(raw))
        self.assertEqual(config.business_max_premium_pp_gbp, 500)
        object.__setattr__(config, "complete_price_only", False)
        html, text, full = self._render([deal_read(PACKAGE, "ECONOMY", 5_000), deal_read(PACKAGE, "MIXED", 9_000)],
                                        config=config)
        self._assert_hidden(html, text, full, "£4,000")

    def test_a_business_total_inside_the_budget_is_shown_whatever_the_premium(self):
        # £20,000 against £4,000 is £3,200 a head, but on a £60,000 budget the itemised trip still fits in Business.
        config = _config(max_budget_gbp=60_000.0)
        html, text, _full = self._render([deal_read(BUILD, "ECONOMY", 4_000), deal_read(BUILD, "MIXED", 20_000)],
                                         config=config)
        page = visible_text(_slice(html, f"trip-{BUILD}"))
        self.assertNotIn("Business not shown", page)
        self.assertRegex(page, r"(?i)with business long-haul")

    def test_an_itemised_trip_over_budget_and_over_the_cap_shows_economy_only(self):
        html, text, _full = self._render([deal_read(BUILD, "ECONOMY", 4_000), deal_read(BUILD, "MIXED", 20_000)])
        page = visible_text(_slice(html, f"trip-{BUILD}"))
        self.assertIn("Business not shown: not a deal for these dates (economy is £16,000 less for 5)", page)
        overview = _overview_line(text, "Self-build: Kruger")
        self.assertNotIn("Business", overview)
        self.assertNotIn("not read yet", overview, "a business read that is not a deal is not 'not read'")

    def test_economy_is_listed_first_when_both_are_shown(self):
        html, text, _full = self._render([deal_read(BUILD, "ECONOMY", 4_000), deal_read(BUILD, "MIXED", 7_000)])
        overview = _overview_line(text, "Self-build: Kruger")
        self.assertLess(overview.index("Economy"), overview.index("Business"))
        page = visible_text(_slice(html, f"trip-{BUILD}"))
        self.assertLess(page.index("All economy"), page.index("With Business long-haul"))


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
        economy = next(o for o in deal.flight_options if o["kind"] == "economy")
        return deal, he.flight_rows(deal), economy

    def test_a_good_airline_inside_the_budget_keeps_its_row(self):
        deal, rows, _economy = self._card_rows("Qatar Airways", 26_000.0, 60_000.0)
        self.assertIn("Business", [cabin for cabin, _route, _total in rows])
        self.assertEqual(he.business_note_words(deal), "")

    def test_a_carrier_off_the_list_loses_its_row_and_says_why(self):
        deal, rows, economy = self._card_rows("SYNTHETIC carrier", 26_000.0, 60_000.0)
        priced = [total for cabin, _route, total in rows if cabin == "Business" and str(total).startswith("£")]
        self.assertEqual(priced, [])
        business = next(o for o in deal.flight_options if o["kind"] == "business")
        saving = he._gbp(business["true_d2d"] - economy["true_d2d"])
        self.assertEqual(he.business_note_words(deal),
                         f"Business not shown: not a deal for these dates (economy is {saving} less for 5)")


if __name__ == "__main__":
    unittest.main()
