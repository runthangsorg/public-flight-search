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


JULY_HUBS = [
    _opt("business", 12873.0),
    _opt("economy", 5830.0),
    _opt("stopover", 9387.0, hub="DOH", hub_label="Doha", stop=2714.0),
    _opt("stopover", 8988.0, hub="MCT", hub_label="Muscat", stop=1663.0),
    _opt("stopover", 6840.0, hub="AUH", hub_label="Abu Dhabi", stop=1029.0),
    _opt("stopover", 8062.0, hub="DXB", hub_label="Dubai", stop=866.0),
]


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

    def test_over_budget_premium_economy_collapses_into_the_compact_line(self):
        html = _render([
            _opt("business", 12873.0),
            _opt("economy", 5830.0),
            _opt("premium_economy", 8647.0, within=False),
            _opt("stopover", 9387.0, hub="DOH", hub_label="Doha", stop=2714.0),
            _opt("stopover_premium_economy", 12710.0, hub="DOH", hub_label="Doha", within=False, stop=2714.0),
        ])
        self.assertNotIn("(b2) Premium Economy, same route", html)
        self.assertNotIn("(c2) Premium Economy", html)
        self.assertIn("(c) Economy + 2 nights Doha each way", html)
        self.assertIn("Premium Economy over budget", html)
        self.assertIn("£8,647", html)

    def test_the_july_report_cards_use_the_compact_line(self):
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=collect_holiday_deals(config),
        )
        self.assertIn("Other stopovers:", html)
        self.assertIn("(economy, totals)", html)


if __name__ == "__main__":
    unittest.main()
