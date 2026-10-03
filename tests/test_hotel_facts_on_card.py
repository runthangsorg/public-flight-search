"""Facts on the card, and a value score built from them (brief 2026-10-03, H5).

Two claims a card makes about a hotel — how far the mosque is, whether there
is a kids' club, how many pools — were previously either absent or taken from
the resort catalogue by hand. When the private engine has read them, they
belong on the card:

* only when stated. A fact nobody read is not a fact, and inventing one is the
  failure this whole seam exists to prevent;
* with its source, and with BOTH sources when they disagree. "four pools" from
  the brand site and "2 pools" from an OTA are two claims; picking one
  silently makes the card look certain about something it is not;
* and they feed the value score, which then shows — because a score computed
  from real inputs is a measurement, while the neutral defaults are not
  (T11b: an unmeasured score is named as unknown, not printed).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_hotel_facts_line,
    render_holiday_report,
)
from public_flight_search.hotel_evidence import consume_hotel_skip_log, load_hotel_evidence

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/hotel_evidence_sample.json"

NOW = "2026-10-03T12:00:00+00:00"
RESORT = "Pullman Lombok Merujani Mandalika Beach Resort"

CONFIG = """
{
  "report_title": "Facts on the card",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 6,
  "max_nights": 10,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "lombok", "label": "Lombok", "airports": ["LOP"], "flight_hours": 24.0}
  ]
}
"""


def _collect(facts, *, ratings=None):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["facts"] = list(facts)
    if ratings is not None:
        payload["ratings"] = list(ratings)
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    config = load_holiday_config(CONFIG)
    loaded = load_hotel_evidence(config, path=handle.name, now=NOW)
    deals = collect_holiday_deals(config, max_budget_gbp=10 ** 9,
                                  hotel_evidence=loaded)
    consume_hotel_skip_log()
    return deals


def _fact(field: str, stated: str, where: str = "brand site",
          url: str = "https://example.invalid/f") -> dict:
    return {
        "property_name": RESORT,
        "field": field,
        "stated": stated,
        "where": where,
        "source_url": url,
        "observed_at": "2026-10-02T15:02:10+00:00",
    }


def _deal(facts, **kwargs):
    deals = _collect(facts, **kwargs)
    return next(deal for deal in deals if deal.resort_name == RESORT)


class FactsOnTheCardTests(unittest.TestCase):
    def test_the_nearest_mosque_is_shown_with_its_drive_time(self):
        deal = _deal([_fact("nearest_mosque", "Masjid Example - 7 min / 2.8 km by car")])
        html = render_hotel_facts_line(deal)
        self.assertIn("Masjid Example", html)
        self.assertIn("7 min", html)

    def test_the_kids_club_is_shown_when_stated(self):
        deal = _deal([_fact("kids_club", "kids club for ages 4-12")])
        html = render_hotel_facts_line(deal)
        self.assertIn("kids club for ages 4-12", html)

    def test_pools_are_shown(self):
        deal = _deal([_fact("pools", "four pools")])
        self.assertIn("four pools", render_hotel_facts_line(deal))

    def test_restaurants_are_shown(self):
        deal = _deal([_fact("restaurants", "3 restaurants, 1 swim-up bar")])
        self.assertIn("3 restaurants", render_hotel_facts_line(deal))

    def test_each_fact_names_its_source(self):
        deal = _deal([_fact("pools", "four pools", where="brand site")])
        self.assertIn("brand site", render_hotel_facts_line(deal))

    def test_disagreeing_sources_are_both_shown_with_their_own_sources(self):
        deal = _deal([
            _fact("pools", "four pools", where="brand site",
                  url="https://example.invalid/brand"),
            _fact("pools", "2 pools", where="OTA listing",
                  url="https://example.invalid/ota"),
        ])
        html = render_hotel_facts_line(deal)
        self.assertIn("four pools", html)
        self.assertIn("2 pools", html)
        self.assertIn("brand site", html)
        self.assertIn("OTA listing", html)

    def test_a_disagreement_is_flagged_rather_than_resolved(self):
        deal = _deal([
            _fact("pools", "four pools", where="brand site"),
            _fact("pools", "2 pools", where="OTA listing"),
        ])
        html = render_hotel_facts_line(deal).lower()
        self.assertTrue("sources disagree" in html or "disagree" in html)

    def test_a_fact_nobody_read_is_not_on_the_card(self):
        deal = _deal([_fact("kids_club", "kids club for ages 4-12")])
        html = render_hotel_facts_line(deal)
        self.assertNotIn("mosque", html.lower())
        self.assertNotIn("pool", html.lower())

    def test_no_facts_renders_no_line(self):
        deal = _deal([])
        self.assertEqual(render_hotel_facts_line(deal), "")

    def test_the_report_shows_the_facts_line(self):
        deals = _collect([_fact("nearest_mosque", "Masjid Example - 7 min / 2.8 km by car")])
        html = render_holiday_report(load_holiday_config(CONFIG), generated_at=NOW,
                                    deals=deals)
        self.assertIn("Masjid Example", html)


class ValueScoreFromFactsTests(unittest.TestCase):
    def test_a_score_built_from_read_facts_is_shown(self):
        deal = _deal([_fact("nearest_mosque", "Masjid Example - 7 min / 2.8 km by car")])
        self.assertTrue(deal.value_score_verified)

    def test_a_near_mosque_scores_better_than_a_far_one(self):
        near = _deal([_fact("nearest_mosque", "Masjid Example - 7 min / 2.8 km by car")])
        far = _deal([_fact("nearest_mosque", "Masjid Example - 45 min / 18 km by car")])
        self.assertGreater(near.mosque_location_score, far.mosque_location_score)

    def test_a_kids_club_scores_the_activities(self):
        with_club = _deal([_fact("kids_club", "kids club for ages 4-12")])
        without = _deal([])
        self.assertGreater(with_club.activities_score, without.activities_score)

    def test_an_unmeasured_score_is_not_shown(self):
        deal = _deal([])
        self.assertFalse(deal.value_score_verified)


if __name__ == "__main__":
    unittest.main()