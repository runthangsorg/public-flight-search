"""Brief P (15 Nov 2026): five stopover-both-ways variants of trips whose hotels already price.

The reader's rule is that any flight leg over eight hours must be Business, and that he prefers economy with a
stop of a night or more each way (Doha, Dubai, Istanbul, Muscat). These five lead-only variants break the journey
at Doha or Dubai in both directions so that every flight is short enough to price in economy; nothing here is
priced, and this file only checks the shapes the brief names and that the planner's wanted lists ask for them.
"""

from __future__ import annotations

import unittest

from public_flight_search import trip_totals as tt
from public_flight_search.holiday_email import _multi_centre_rows, multi_centre_wanted
from public_flight_search.multi_centre import load_multi_centre

from test_holiday_email_compact import _config
from test_price_says_what_it_covers import load

#: Each variant as the brief names it: the hub it stops in, its title, and its legs in flying order.
VARIANTS = {
    "LD-13": (
        "DOH",
        "Doha 2 nights + Anuradhapura 4 nights + Trincomalee 4 nights + Kalkudah 4 nights + Doha 1 night",
        [["LHR", "DOH"], ["DOH", "CMB"], ["CMB", "DOH"], ["DOH", "LHR"]],
    ),
    "LD-14": (
        "DOH",
        "Doha 2 nights + Masai Mara 4 nights + Diani 7 nights + Doha 1 night",
        [["LHR", "DOH"], ["DOH", "NBO"], ["NBO", "MBA"], ["MBA", "NBO"], ["NBO", "DOH"], ["DOH", "LHR"]],
    ),
    "LD-15": (
        "DXB",
        "Dubai 2 nights + Zanzibar 10 nights + Dubai 1 night",
        [["LHR", "DXB"], ["DXB", "ZNZ"], ["ZNZ", "DXB"], ["DXB", "LHR"]],
    ),
    "LD-16": (
        "DXB",
        "Dubai 2 nights + Mauritius 9 nights + Dubai 1 night",
        [["LHR", "DXB"], ["DXB", "MRU"], ["MRU", "DXB"], ["DXB", "LHR"]],
    ),
    "LD-17": (
        "DOH",
        "Doha 2 nights + Kuala Lumpur 2 nights + Tanjong Jara 4 nights + Redang Island 6 nights + Doha 1 night",
        [["LHR", "DOH"], ["DOH", "KUL"], ["KUL", "TGG"], ["TGG", "KUL"], ["KUL", "DOH"], ["DOH", "LHR"]],
    ),
}


#: The city each hub is named by in a lead's ``why``.
HUB_CITY = {"DOH": "Doha", "DXB": "Dubai"}


def _leads():
    return {t.id: t for t in load_multi_centre(_config(), include_leads=True) if t.confidence == "lead"}


class StopoverVariantLeadTests(unittest.TestCase):
    """The shipped file carries the five variants, with no figure and a stop of a night at the hub each way."""

    @classmethod
    def setUpClass(cls):
        cls.leads = _leads()

    def test_each_variant_loads_as_the_lead_the_brief_names(self):
        for ident, (hub, title, legs) in VARIANTS.items():
            with self.subTest(ident):
                lead = self.leads.get(ident)
                self.assertIsNotNone(lead, f"{ident} is not a shipped lead")
                self.assertEqual(lead.title, title)
                self.assertEqual(lead.season, "summer")
                self.assertEqual(lead.kind, "self-build")
                self.assertEqual((lead.cost_low_gbp, lead.cost_high_gbp), (0.0, 0.0), "a lead carries no figure")
                self.assertEqual([list(leg) for leg in lead.legs], legs)
                self.assertIn("eight hours or less", lead.why, f"{ident}: why says every flight is short")
                self.assertIn(HUB_CITY[hub], lead.why, f"{ident}: why names the hub")
                self.assertIn("stopover each way", lead.why)
                self.assertTrue(lead.catch, f"{ident}: a lead says what it costs you")

    def test_every_variant_is_twelve_to_twenty_one_nights(self):
        for ident in VARIANTS:
            with self.subTest(ident):
                self.assertTrue(12 <= sum(stop.nights for stop in self.leads[ident].stops) <= 21,
                                f"{ident}: {sum(stop.nights for stop in self.leads[ident].stops)} nights")

    def test_the_legs_chain_from_heathrow_to_heathrow_through_stop_airports(self):
        for ident, (_hub, _title, _legs) in VARIANTS.items():
            with self.subTest(ident):
                lead, legs = self.leads[ident], [list(leg) for leg in self.leads[ident].legs]
                self.assertEqual(legs[0][0], "LHR", "the first leg leaves Heathrow")
                self.assertEqual(legs[-1][1], "LHR", "the last leg lands at Heathrow")
                for before, after in zip(legs, legs[1:]):
                    self.assertEqual(before[1], after[0], f"{ident}: {before} then {after} is not one journey")
                # A leg's airports are the airports of the trip's own stops, or Heathrow. Strict adjacency is not
                # asked for and cannot hold: LD-17 returns from Redang through Kuala Lumpur to reach the Doha
                # flight, just as the shipped LD-02 flies TGG-LHR.
                airports = {stop.airport for stop in lead.stops}
                for leg in legs:
                    for code in leg:
                        self.assertIn(code, airports | {"LHR"}, f"{ident}: {code} is not an airport of this trip")
                self.assertLessEqual(len(lead.stops), len(legs) + 1, f"{ident}: no more stops than legs plus one")

    def test_the_journey_is_broken_at_the_same_hub_both_ways(self):
        for ident, (hub, _title, _legs) in VARIANTS.items():
            with self.subTest(ident):
                lead = self.leads[ident]
                self.assertEqual((lead.stops[0].airport, lead.stops[-1].airport), (hub, hub),
                                 f"{ident}: the hub is the first and last stop")
                self.assertGreaterEqual(lead.stops[0].nights, 1, f"{ident}: a night at the hub on the way out")
                self.assertGreaterEqual(lead.stops[-1].nights, 1, f"{ident}: a night at the hub on the way back")
                self.assertEqual([s.airport for s in lead.stops if s.airport == hub], [hub, hub])

    def test_every_lodge_page_is_one_of_the_trips_own_sources(self):
        for ident in VARIANTS:
            with self.subTest(ident):
                lead = self.leads[ident]
                for stop in lead.stops:
                    for lodge in stop.lodges:
                        self.assertTrue(lodge.url.startswith("https://"), f"{ident}: {lodge.name} has no page")
                        self.assertIn(lodge.url, lead.source_urls, f"{ident}: {lodge.name} is not in source_urls")

    def test_the_wanted_lists_ask_for_every_variant_and_every_one_of_its_properties(self):
        rows = [r for r in _multi_centre_rows(_config(), fares=load([]), include_leads=True)
                if r["trip"].id in VARIANTS]
        self.assertEqual(sorted(r["trip"].id for r in rows), sorted(VARIANTS))
        wanted = {w["trip"] for w in multi_centre_wanted(_config(), include_leads=True)}
        stays = {s["property_name"] for s in tt.stay_wanted(_config(), rows)["stays"]}
        for ident in VARIANTS:
            with self.subTest(ident):
                self.assertIn(ident, wanted, "the fare reader is asked for this trip")
                for stop in self.leads[ident].stops:
                    for lodge in stop.lodges:
                        self.assertIn(lodge.name, stays, f"{ident}: the stay reader is asked for {lodge.name}")


class RenamedPropertyTests(unittest.TestCase):
    """Part 2: three properties are named as the search lists them, so a stay found by that name opens."""

    NAMES = {
        "Museum Hotel": "Uchisar, Cappadocia",
        "Perdue Hotel": "Faralya, Fethiye",
        "Nusfjord Village & Resort": "Nusfjord, Lofoten",
    }

    def test_the_three_properties_carry_the_name_and_area_the_search_lists(self):
        leads = _leads()
        found = {lodge.name: lodge.area for lead in leads.values() for stop in lead.stops
                 for lodge in stop.lodges if lodge.name in self.NAMES}
        self.assertEqual(found, self.NAMES)

    def test_the_old_names_are_gone_from_the_leads(self):
        page = " ".join(lodge.name for lead in _leads().values() for stop in lead.stops for lodge in stop.lodges)
        for old in ("Museum Hotel Cappadocia", "Perdue Hotel Faralya", "Nusfjord Arctic Resort"):
            self.assertNotIn(old, page)


if __name__ == "__main__":
    unittest.main()


def test_the_one_way_sri_lanka_trip_is_retired_for_its_stopover_both_ways_version():
    """Owner, 15 Nov 2026: "retire the old Sri Lanka trip" (LD-04 is replaced by LD-13)."""
    import json as _json
    from pathlib import Path as _Path

    path = _Path(__file__).resolve().parents[1] / "src" / "public_flight_search" / "data" / "trip_leads.json"
    ids = [t["id"] for t in _json.loads(path.read_text(encoding="utf-8"))["itineraries"]]
    assert "LD-04" not in ids and "LD-13" in ids
