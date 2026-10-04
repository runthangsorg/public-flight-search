"""A short, readable flight-options block.

Owner brief 2026-10-02: the card listed every hub's (c)/(c2) line — about ten
lines per long-haul card. Show (a) Business, (b) Economy and the cheapest (c)
Economy stopover in full; collapse the other stopovers into one line
("Other stopovers: Doha £x · Muscat £y · Dubai £z (economy, totals)"). Show
Premium Economy lines only when within budget; otherwise they go in that one
compact line.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import unittest

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    priceable_date_pairs,
    render_flight_options,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"


def _opt(kind, total, *, within=True, hub=None, hub_label=None, flight=1000.0, hotel=2000.0, stop=0.0):
    return {
        "kind": kind,
        "cabin": "PREMIUM_ECONOMY" if "premium" in kind else ("BUSINESS" if kind == "business" else "ECONOMY"),
        "hub": hub,
        "hub_label": hub_label or hub,
        "hub_hotel": f"{hub_label or hub} Hotel",
        "hub_board": "Bed & Breakfast",
        "outbound": "2027-07-20",
        "return": "2027-07-27",
        "nights": 7,
        "origin": "LHR",
        "flight_cost": flight,
        "hotel_cost": hotel,
        "stopover_hotel_cost": stop,
        "stopover_nights": 4 if stop else 0,
        "uk_ground": 16.5,
        "transfer": 76.0,
        "total_pkg": total,
        "true_d2d": total + 92.5,
        "flight_basis": "benchmark",
        "within_budget": within,
        "hub_hotel_confidence": "estimate",
        "source_url": "",
    }


def _render(options):
    return render_flight_options(
        options, travellers=5, dates=("2027-07-20", "2027-07-27"),
        airport="HKT", origin="LHR",
    )


def _option_lines(html):
    """The full option lines (each carries the 'door to door' total)."""
    return [segment for segment in html.split("<br>") if "door to door" in segment]


JULY_HUBS = [
    _opt("business", 12873.0),
    _opt("economy", 5830.0),
    _opt("stopover", 9387.0, hub="DOH", hub_label="Doha", stop=2714.0),
    _opt("stopover", 8988.0, hub="MCT", hub_label="Muscat", stop=1663.0),
    _opt("stopover", 6840.0, hub="AUH", hub_label="Abu Dhabi", stop=1029.0),
    _opt("stopover", 8062.0, hub="DXB", hub_label="Dubai", stop=866.0),
]


def _synthetic_stopover_fares(config, airports=("HKT", "USM"), hubs=("DOH", "MCT")):
    """Whole-party stopover fares for the pairs THIS config prices.

    ``holidays.STOPOVER_FARES`` holds real multi-city fares read on 2026-09-30
    for 20 -> 27 July 2027, a pair the owner's July window (moved 2026-10-04)
    no longer contains, so no card is priced a stopover and every one falls
    back to the "price this yourself" link instead. The compact line only
    exists when more than one hub is priced, so this test needs fares for the
    pairs the report renders: synthetic ones, built here and stamped so they
    can never be mistaken for a read.
    """
    fares: dict[tuple[str, str], list[dict]] = {}
    for outbound, returning in priceable_date_pairs(config):
        for hub_index, hub in enumerate(hubs):
            for airport in airports:
                legs = (
                    ("LHR", hub, hol._shift_date(outbound, -2)),
                    (hub, airport, outbound),
                    (airport, hub, returning),
                    (hub, "LHR", hol._shift_date(returning, 2)),
                )
                fares.setdefault((hub, airport), []).append({
                    "pair": (outbound, returning),
                    "legs": legs,
                    "origin": "LHR",
                    "total_gbp": 5000.0 + 1000.0 * hub_index,
                    "carrier": "SYNTHETIC test carrier",
                    "observed_at": "synthetic",
                    "season": "summer",
                    "source_url": hol.build_google_flights_legs_url(
                        legs, travellers=5, cabin_class="ECONOMY"
                    ),
                })
    return {key: tuple(value) for key, value in fares.items()}


class ShorterFlightOptionsTests(unittest.TestCase):
    def test_only_the_cheapest_stopover_is_shown_in_full(self):
        html = _render(JULY_HUBS)
        self.assertIn("(a) Business", html)
        self.assertIn("(b) Economy", html)
        self.assertEqual(html.count("(c) Economy + 2 nights"), 1)
        # The cheapest (c) — Abu Dhabi — is the one expanded, hotel and all.
        self.assertIn("(c) Economy + 2 nights Abu Dhabi each way", html)
        self.assertIn("Abu Dhabi Hotel", html)
        # The rest collapse into one compact line with their totals.
        self.assertIn("Other stopovers:", html)
        self.assertIn("(economy, totals)", html)
        self.assertIn("Doha £9,387", html)
        self.assertIn("Muscat £8,988", html)
        self.assertIn("Dubai £8,062", html)
        # ...and are not also expanded.
        self.assertNotIn("Doha Hotel", html)
        self.assertNotIn("Muscat Hotel", html)
        self.assertNotIn("Dubai Hotel", html)

    def test_within_budget_premium_economy_is_still_shown(self):
        html = _render([
            _opt("business", 12873.0),
            _opt("economy", 5830.0),
            _opt("premium_economy", 8647.0, within=True),
        ])
        self.assertIn("(b2) Premium Economy, same route", html)
        self.assertNotIn("Premium Economy over budget", html)

    def test_over_budget_premium_economy_is_shown_once_marked_over_budget(self):
        html = _render([
            _opt("business", 12873.0),
            _opt("economy", 5830.0),
            _opt("premium_economy", 8647.0, within=False),
            _opt("stopover", 9387.0, hub="DOH", hub_label="Doha", stop=2714.0),
            _opt("stopover_premium_economy", 12710.0, hub="DOH", hub_label="Doha", within=False, stop=2714.0),
        ])
        self.assertIn("(c) Economy + 2 nights Doha each way", html)
        # Exactly one Premium Economy line: the cheapest PE, marked over budget,
        # not silently dropped and not the over-budget stopover variant.
        self.assertEqual(html.count("(b2) Premium Economy, same route"), 1)
        self.assertNotIn("(c2) Premium Economy", html)
        pe_line = next(ln for ln in _option_lines(html) if "Premium Economy" in ln)
        self.assertIn("over budget", pe_line)
        self.assertNotIn("within budget", pe_line)
        self.assertIn("£8,647", html)

    def test_a_long_haul_card_shows_at_most_four_full_option_lines(self):
        # The Pullman Khao Lak shape: every Gulf hub priced, plus a same-route
        # and a stopover Premium Economy. The fix caps it at (a) Business,
        # (b) Economy, (c) the cheapest stopover and ONE Premium Economy line.
        html = _render(JULY_HUBS + [
            _opt("premium_economy", 8647.0, within=True),
            _opt("stopover_premium_economy", 12710.0, hub="DOH", hub_label="Doha", within=True, stop=2714.0),
        ])
        self.assertEqual(len(_option_lines(html)), 4)
        self.assertIn("(a) Business", html)
        self.assertIn("(b) Economy", html)
        # Order: (a), (b), (c) cheapest stopover, then the single PE line.
        self.assertLess(html.index("(a) Business"), html.index("(b) Economy"))
        self.assertLess(html.index("(b) Economy"), html.index("(c) Economy + 2 nights"))
        self.assertLess(html.index("(c) Economy + 2 nights"), html.index("(b2) Premium Economy"))
        # The cheapest PE (same route, £8,647) is the one PE line shown.
        self.assertEqual(html.count("(b2) Premium Economy, same route"), 1)
        self.assertEqual(sum("Premium Economy" in ln for ln in _option_lines(html)), 1)

    def test_the_july_report_cards_use_the_compact_line(self):
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        # A priced stopover needs a fare read for a pair this run prices; the
        # committed ones were read for a pair the window no longer contains
        # (see _synthetic_stopover_fares).
        saved = hol.STOPOVER_FARES
        hol.STOPOVER_FARES = _synthetic_stopover_fares(config)
        try:
            html = render_holiday_report(
                config, generated_at="2026-10-02T00:00:00+00:00",
                deals=collect_holiday_deals(config),
            )
        finally:
            hol.STOPOVER_FARES = saved
        self.assertIn("Other stopovers:", html)
        self.assertIn("(economy, totals)", html)


if __name__ == "__main__":
    unittest.main()
