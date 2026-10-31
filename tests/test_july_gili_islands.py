"""The July planner gains the Gili Islands (luxury), brief 2026-10-31.

Gili Trawangan, Gili Meno and Gili Air join the July catalogue as one key,
``gili_islands``: one top-end stay per island, reached the way the planner
already reaches other islands - a London flight to Lombok (LOP, about 24h)
and then the boat: about 15 minutes by private speedboat from Teluk Kodek for
Gili Trawangan, 20-30 minutes on the public Bangsal boat for Gili Meno, about
10 minutes from Lombok for Gili Air. The rules the existing destination
batches were added under are pinned here:

* **no price, no card** - every entry carries ``board: "unverified"``, no
  ``board_options`` and no rate fields, so nothing cards until the private
  rate reader has read a rate for the property's own ``hotel_url``;
* the one-booking unit and the card-level TripAdvisor gate figure stay
  *unverified* (``rooms_in_unit`` None, ``tripadvisor`` None) rather than
  assumed, even though each entry quotes the rating it was read from today;
* the transfer leg is priced only where a published tariff seats this party of
  five (Pondok Santi's own airport pick-up, "with a maximum of 5 people") and
  is marked unpriced - never estimated - where no page prices that leg;
* the owner's island board rule applies (HB/FB/AI, every sold basis priced
  separately), and what a resort only sells - breakfast, on these islands -
  is said out loud in the entry itself;
* the July example stays long-haul and the key is named in the report's filters
  data until a rate is read (the e-mail itself stays silent on an unpriced
  resort, which is the repo's no-price-no-card rule, not a gap here).

Everything here is offline: no network, no model calls, no private data.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from public_flight_search import holidays as hol
from public_flight_search import vendors as V
from public_flight_search.cabin import DEFAULT_FLIGHT_HOURS_LHR
from public_flight_search.holidays import (
    HOLIDAY_AIRPORTS,
    HOLIDAY_SEARCH_QUERIES,
    ISLAND_RULE_KEYS,
    SUMMER_RESORT_CATALOG,
    SUMMER_WEATHER,
    SUITE_ARCHITECTURE,
    WET_MONTHS_BY_DESTINATION,
    collect_holiday_deals,
    load_holiday_config,
    resort_catalog,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"

#: One top-end stay per island: Trawangan, Meno, Air.
GILI_NAMES = (
    "Pondok Santi Estate",
    "BASK Gili Meno",
    "Rimba Villas",
)

#: The only island leg a published tariff seats five: Pondok Santi's own
#: "Airport pick-up (private car, speed boat, & horse cart/cidomo) for up to 3
#: people at 1,500,000 IDR per way. For each additional person ... 500,000 IDR
#: per way, with a maximum of 5 people" (pondoksanti.com/contact.html, read
#: 2026-10-31) - 2,500,000 IDR per way for five, doubled for the return, at the
#: ECB reference rates this catalogue already converts at (EUR/GBP 0.85718,
#: EUR/IDR 20350.09). Every other Gili entry carries 0.0: unpriced, never
#: estimated.
PUBLISHED_TRANSFER_GBP = {"Pondok Santi Estate": 210.61}

#: The LOP flight benchmark the entries reuse (Google Flights, LHR-LOP,
#: 20-27 Jul 2027, 5 adults, read 2026-09-29), as Koh Phangan reuses the
#: USM one: the flight is identical, only the boat leg differs.
LOP_BENCHMARK_GBP = 4990.0


def _july():
    return load_holiday_config(JULY.read_text(encoding="utf-8"))


class GiliCatalogueTests(unittest.TestCase):
    def _entries(self):
        return SUMMER_RESORT_CATALOG["gili_islands"]

    def test_the_key_holds_one_luxury_resort_per_island(self):
        names = [entry["name"] for entry in self._entries()]
        self.assertEqual(names, list(GILI_NAMES))
        for island, entry in zip(("Trawangan", "Meno", "Air"), self._entries()):
            with self.subTest(island=island):
                self.assertIn(island, entry["destination_label"])

    def test_each_entry_carries_its_source_and_luxury_class(self):
        for entry in self._entries():
            with self.subTest(resort=entry["name"]):
                self.assertTrue(entry["hotel_url"].startswith("https://"))
                self.assertIn(entry["stars"], (4, 5))
                for field in ("destination_label", "highlights", "why",
                              "routing", "beach"):
                    self.assertTrue(entry[field], field)
                self.assertEqual(entry["airport"], "LOP")
                # "" = this entry claims no room-rate basis: with no rate read
                # it must not carry one (test_july_long_haul enforces that any
                # other value brings a rate with it), so no card forms.
                self.assertEqual(entry["confidence"], "")
                self.assertTrue(entry["airline"])

    def test_no_entry_carries_a_price_it_did_not_read(self):
        for entry in self._entries():
            with self.subTest(resort=entry["name"]):
                self.assertEqual(entry["board"], "unverified")
                self.assertNotIn("board_options", entry)
                for field in ("base_nightly_room_rate_gbp",
                              "peak_summer_nightly_room_rate_gbp"):
                    self.assertNotIn(field, entry)
                # The flight side is a READ benchmark: the entries reuse the
                # LOP facts, so both peak and benchmark carry that same figure.
                self.assertEqual(entry["flight_benchmark_5pax_gbp"],
                                 LOP_BENCHMARK_GBP)
                self.assertEqual(entry["peak_summer_flight_5pax_gbp"],
                                 LOP_BENCHMARK_GBP)
                # The transfer leg is priced only where a published tariff
                # seats this party of five; everywhere else it is the file's
                # "not priced" sentinel, never an invented figure. A priced
                # transfer does NOT relax the no-rate rule above: the transfer
                # is a leg cost, not a room rate.
                self.assertEqual(entry["transfer_gbp"],
                                 PUBLISHED_TRANSFER_GBP.get(entry["name"], 0.0))

    def test_the_unit_and_the_rating_stay_unverified(self):
        for name in GILI_NAMES:
            with self.subTest(resort=name):
                arch = SUITE_ARCHITECTURE[name]
                self.assertIsNone(arch["rooms_in_unit"])
                self.assertIsNone(arch["tripadvisor"])
                self.assertTrue(arch["beach_walkable"])
                self.assertEqual(arch["suite_peak_nightly_gbp"],
                                 arch["suite_nightly_gbp"])

    def test_july_is_stated_as_the_dry_season_for_the_key(self):
        self.assertIn("gili_islands", SUMMER_WEATHER)
        self.assertIn("gili_islands", WET_MONTHS_BY_DESTINATION)
        wet = WET_MONTHS_BY_DESTINATION["gili_islands"]
        self.assertIsInstance(wet, tuple)
        self.assertNotIn(7, wet, "July is the dry season on the Gilis")

    def test_the_key_names_its_airport_and_search_query(self):
        self.assertEqual(HOLIDAY_AIRPORTS["gili_islands"], "LOP")
        self.assertTrue(HOLIDAY_SEARCH_QUERIES["gili_islands"])

    def test_the_key_follows_the_owner_island_board_rule(self):
        # Brief 2026-10-31: "the owner's rule for islands is half board,
        # full board or all inclusive; B&B is the floor elsewhere". The
        # rule prices every basis a resort actually sells, so a B&B-only
        # resort says so instead of hiding it.
        self.assertIn("gili_islands", ISLAND_RULE_KEYS)

    def test_each_entry_says_plainly_what_the_resort_sells(self):
        for entry in self._entries():
            with self.subTest(resort=entry["name"]):
                text = " ".join(entry["why"]) + " " + " ".join(entry["highlights"])
                self.assertIn("breakfast", text.lower())

    def test_gili_air_is_chosen_on_rating_and_villa_not_a_five_star_claim(self):
        # Brief 2026-10-31 asks for "5-star or the best-rated luxury villas and
        # resorts, private pool villas where they exist". Tripadvisor gives Gili
        # Air's pick no Giata five-star line, so the entry says that out loud
        # and prints no star it cannot source.
        air = self._entries()[2]
        self.assertEqual(air["name"], "Rimba Villas")
        self.assertEqual(air["stars"], 4)
        joined = " ".join(air["highlights"]).lower()
        self.assertIn("five-star certification is not claimed", joined)
        self.assertIn("private pool", " ".join(air["why"] + air["highlights"]).lower())


class GiliFlightHoursTests(unittest.TestCase):
    def test_the_cabin_default_is_the_lop_flight_with_the_boat_stated(self):
        self.assertEqual(DEFAULT_FLIGHT_HOURS_LHR["gili_islands"], 24.0)

    def test_the_example_config_carries_sourced_hours_and_no_nonstop(self):
        config = _july()
        dest = next(d for d in config.destinations if d.key == "gili_islands")
        self.assertEqual(set(dest.airports), {"LOP"})
        self.assertEqual(dest.flight_hours, 24.0)
        self.assertEqual(dest.flight_hours,
                         DEFAULT_FLIGHT_HOURS_LHR["gili_islands"])
        self.assertFalse(dest.nonstop_from_london)
        self.assertGreater(len(dest.flight_hours_source), 20)
        self.assertGreater(len(dest.nonstop_source), 20)
        # The boat is a leg of the journey and must be stated, not folded
        # into the flight hours (the Koh Phangan precedent).
        self.assertIn("boat", dest.flight_hours_source.lower())

    def test_the_destination_is_long_haul_and_not_excluded(self):
        config = _july()
        dest = next(d for d in config.destinations if d.key == "gili_islands")
        self.assertGreater(dest.flight_hours, 6.0)
        self.assertFalse(set(dest.airports) & {"SIN", "KUL", "PEN", "BKI", "LGK"})


class GiliVendorTests(unittest.TestCase):
    def test_kuoni_links_the_lombok_and_gili_islands_destination_page(self):
        # Kuoni's own sitemap publishes one page for Lombok & the Gili
        # Islands; the new key points at it rather than falling back to
        # the destinations index.
        self.assertEqual(
            V.KUONI_DESTINATION_PATHS["gili_islands"],
            "https://www.kuoni.co.uk/destinations/south-east-asia/"
            "indonesia/lombok-and-gili-islands/",
        )


class GiliReportTests(unittest.TestCase):
    def test_no_gili_resort_cards_without_a_rate(self):
        config = _july()
        deals = collect_holiday_deals(config, max_budget_gbp=10 ** 9)
        names = {deal.resort_name for deal in deals}
        self.assertFalse(set(GILI_NAMES) & names)

    def test_the_report_states_the_gili_resorts_with_a_reason(self):
        # Never silent: until a rate is read each resort is listed in the
        # report's filters block with the reason it did not card.
        config = _july()
        collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
        catalog = resort_catalog(config)
        self.assertTrue(catalog.get("gili_islands"))
        filtered = {name: reason for name, reason in hol.LAST_FILTERED_OUT}
        for resort in catalog["gili_islands"]:
            with self.subTest(resort=resort["name"]):
                self.assertIn(resort["name"], filtered)
                self.assertTrue(filtered[resort["name"]])

    def test_the_gili_destination_never_vanishes_from_the_report(self):
        # The July example's own never-silent equation, scoped to the new
        # key: backed == carded | over | stated_filtered, gili edition.
        config = _july()
        deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
        carded = {d.destination_key for d in deals}
        over = {row["destination_key"] for row in hol.LAST_OVER_BUDGET}
        catalog = hol.resort_catalog(config)
        self.assertIn("gili_islands", catalog)
        filtered_names = {name for name, _reason in hol.LAST_FILTERED_OUT}
        all_stated = all(
            row["name"] in filtered_names
            for row in catalog["gili_islands"]
        )
        self.assertTrue(all_stated or "gili_islands" in carded | over,
                        "the Gili Islands vanished from the July report")


if __name__ == "__main__":
    unittest.main()
