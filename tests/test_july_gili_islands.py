"""The July planner prices the Gili Islands (luxury), brief 2026-10-31.

Gili Trawangan, Gili Meno and Gili Air join the July catalogue as one key,
``gili_islands``: one top-end stay per island, reached the way the planner
already reaches other islands - a London flight to Lombok (LOP, about 24h)
and then the boat: about 15 minutes by private speedboat from Teluk Kodek for
Gili Trawangan, 20-30 minutes on the public Bangsal boat for Gili Meno, about
10 minutes from Lombok for Gili Air. The rules the existing destination
batches were added under are pinned here, and the 2026-10-31 rate read is
what changed two of them:

* **no price, no card** - unchanged, and now exercised: the stays carry the
  nightly their OWN booking engine quoted, so a card forms only where a rate
  and a breakfast-or-better board were both read;
* **breakfast is the minimum** - BASK Gili Meno and Rimba Villas are priced
  for July and sell no board (every one of BASK's own plans is flagged
  "Room Only", and Rimba's villa plan puts breakfast "at an additional
  cost"), so they are refused with that reason rather than carded at a rate
  the owner's rule rejects;
* the transfer leg is priced only where a published tariff seats this party of
  five (Pondok Santi's own airport pick-up, "with a maximum of 5 people", and
  Rimba's own engine car + whole-boat add-ons) and is marked unpriced - never
  estimated - where no page prices that leg (BASK);
* the owner's island board rule applies (HB/FB/AI, every sold basis priced
  separately), and what these islands actually sell - breakfast at best - is
  said out loud in the entry itself;
* the one-booking UNIT is a read (the engine that quoted the rate also said
  the unit takes five), while the card-level TripAdvisor gate figure stays
  *unverified* (``tripadvisor`` None) because this engine has read no
  Tripadvisor score - the ratings the entries quote are property-page text.

Everything here is offline: no network, no model calls, no private data.
"""

from __future__ import annotations

import re
import unittest
from html import unescape
from pathlib import Path

from public_flight_search import holidays as hol
from public_flight_search import vendors as V
from public_flight_search.cabin import DEFAULT_FLIGHT_HOURS_LHR
from public_flight_search.holiday_email import render_holiday_report_compact
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
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"

#: One top-end stay per island: Trawangan, Meno, Air.
GILI_NAMES = (
    "Pondok Santi Estate",
    "BASK Gili Meno",
    "Rimba Villas",
)

#: The whole airport-to-resort leg, per party of five, return, from a tariff
#: that seats five. Pondok Santi's own site (pondoksanti.com/contact.html,
#: read 2026-10-31): "Airport pick-up (private car, speed boat, & horse
#: cart/cidomo) for up to 3 people at 1,500,000 IDR per way. For each
#: additional person ... 500,000 IDR per way, with a maximum of 5 people" -
#: 2,500,000 IDR per way for five, doubled for the return. Rimba's own
#: booking engine (swiftbook property 15086 ExtrasData, read 2026-10-31):
#: "Airport to or from Teluk Nara Harbor Transport ... One time Private
#: Driver" at IDR 700,000 a way and "Private Speedboat Gili Air to or from
#: Teluk Nara Harbor ... Price includes the entire boat, accommodating up to
#: 7 adults with luggage" at IDR 800,000 a way - 3,000,000 IDR both legs both
#: ways. Both at the ECB reference rates this catalogue converts at
#: (EUR/GBP 0.85718, EUR/IDR 20350.09). BASK carries 0.0: unpriced, never
#: estimated - no page read prices a Lombok-airport road leg seating five.
PUBLISHED_TRANSFER_GBP = {
    "Pondok Santi Estate": 210.61,
    "Rimba Villas": 126.37,
}

#: The rate each property's OWN booking engine quoted for a July stay of this
#: party, as read on 2026-10-31: the nightly, the basis it was mapped to, and
#: whether the engine opened a window this trip can actually book (12-21
#: nights). Pondok Santi's is the example config's own 25 Jun-9 Jul 2027 pair.
READ_RATES = {
    "Pondok Santi Estate": {
        "nightly_gbp": 321.35, "basis": "BB", "confidence": "market-supported",
        "rooms_in_unit": 1, "on_config_dates": True,
    },
    "BASK Gili Meno": {
        "nightly_gbp": 419.66, "basis": "RO", "confidence": "estimate",
        "rooms_in_unit": 1, "on_config_dates": False,
    },
    "Rimba Villas": {
        "nightly_gbp": 271.87, "basis": "RO", "confidence": "estimate",
        "rooms_in_unit": 1, "on_config_dates": False,
    },
}

#: The only July card the three islands produce: priced AND with breakfast.
CARDED_GILI_RESORT = "Pondok Santi Estate"

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
                # Every entry now claims a room-rate basis because every entry
                # now carries a READ rate (test_july_long_haul enforces that a
                # non-empty confidence brings a rate with it, and that a rate
                # never arrives without one).
                self.assertEqual(entry["confidence"],
                                 READ_RATES[entry["name"]]["confidence"])
                self.assertIn(entry["confidence"], ("market-supported", "estimate"))
                self.assertTrue(entry["airline"])

    def test_every_entry_carries_the_rate_its_own_engine_quoted(self):
        for entry in self._entries():
            read = READ_RATES[entry["name"]]
            with self.subTest(resort=entry["name"]):
                self.assertEqual(entry["base_nightly_room_rate_gbp"],
                                 read["nightly_gbp"])
                self.assertEqual(entry["peak_summer_nightly_room_rate_gbp"],
                                 read["nightly_gbp"])
                # July is the season priced, so no peak discount is claimed.
                self.assertEqual(SUITE_ARCHITECTURE[entry["name"]]["suite_nightly_gbp"],
                                 read["nightly_gbp"])
                # The board the engine mapped, in the entry's own words: "Bed &
                # breakfast" on the villa it quoted, "Room Only" on the two
                # that sell no meals.
                self.assertEqual(hol.board_code(entry["board"]), read["basis"])
                # The only stay with a basis to price is the one with a basis.
                self.assertEqual(bool(entry.get("board_options")),
                                 read["basis"] in hol.BREAKFAST_BASES)
                # The flight side is a READ benchmark: the entries reuse the
                # LOP facts, so both peak and benchmark carry that same figure.
                self.assertEqual(entry["flight_benchmark_5pax_gbp"],
                                 LOP_BENCHMARK_GBP)
                self.assertEqual(entry["peak_summer_flight_5pax_gbp"],
                                 LOP_BENCHMARK_GBP)
                # The transfer leg is priced only where a published tariff
                # seats this party of five; everywhere else it is the file's
                # "not priced" sentinel, never an invented figure. A priced
                # transfer does NOT relax the rate rule above: the transfer is
                # a leg cost, not a room rate.
                self.assertEqual(entry["transfer_gbp"],
                                 PUBLISHED_TRANSFER_GBP.get(entry["name"], 0.0))

    def test_a_priced_board_row_names_the_engine_the_rate_came_from(self):
        # No price without a source the owner can re-open.
        for entry in self._entries():
            for option in entry.get("board_options") or ():
                with self.subTest(resort=entry["name"], basis=option["basis"]):
                    self.assertIn("engine", option["source"])
                    self.assertIn("2026-10-31", option["source"])
                    self.assertGreater(option["nightly_gbp"], 0)

    def test_the_unit_is_read_and_the_rating_gate_is_not(self):
        for name in GILI_NAMES:
            read = READ_RATES[name]
            with self.subTest(resort=name):
                arch = SUITE_ARCHITECTURE[name]
                # The engine that quoted the rate also said the unit takes the
                # party: one villa, one key, whatever bedrooms it has.
                self.assertEqual(arch["rooms_in_unit"], read["rooms_in_unit"])
                self.assertTrue(arch["suite_type"])
                # The gate figure stays a non-read: this engine has read no
                # Tripadvisor score, so the >=4.5 gate is not applied and the
                # report says so.
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
    """What the collected July report does with the three priced stays.

    Every figure here is what the planner produced on 2026-10-31 with the
    rates as written into the catalogue, so the test is the record of the run
    the brief asked for: a card renders, it carries the read rate and the read
    board, and the two stays the board rule refuses are named with that reason.
    """

    def _run(self, *, max_budget_gbp=10 ** 9):
        config = _july()
        deals = collect_holiday_deals(config, max_budget_gbp=max_budget_gbp)
        return config, deals

    def _email_text(self, config, deals) -> str:
        """The compact e-mail as readable text: tags gone, entities decoded.

        The e-mail's own assertions read the words a human sees, so the test
        decodes what the renderer escaped rather than matching on ``&amp;``.
        """
        rendered = render_holiday_report_compact(
            config, generated_at="2026-10-31T12:00:00+00:00", deals=deals)
        return re.sub(r"\|+", "|", unescape(re.sub(r"<[^>]+>", "|", rendered)))

    def test_the_priced_breakfast_stay_now_cards(self):
        # The no-price-no-card rule is unchanged; what changed is that a rate
        # and a breakfast basis were read for Pondok Santi, so its card forms.
        config, deals = self._run()
        names = {deal.resort_name for deal in deals}
        self.assertEqual(set(GILI_NAMES) & names, {CARDED_GILI_RESORT})
        for name in GILI_NAMES:
            with self.subTest(resort=name):
                self.assertFalse(hol.resort_is_unpriced(name),
                                 f"{name} is still unpriced, so it can never card")

    def test_the_card_is_priced_at_the_read_rate_for_the_read_board(self):
        config, deals = self._run()
        deal = next(d for d in deals if d.resort_name == CARDED_GILI_RESORT)
        read = READ_RATES[CARDED_GILI_RESORT]
        self.assertEqual(deal.destination_key, "gili_islands")
        self.assertEqual(hol.board_code(deal.board_basis), read["basis"])
        self.assertEqual(deal.rooms_in_unit, read["rooms_in_unit"])
        self.assertEqual(deal.confidence, read["confidence"])
        # The stay the card prices is the engine's nightly over the booked
        # nights, and the transfer is the published whole airport-to-resort leg.
        self.assertAlmostEqual(deal.hotel_price_total_gbp,
                               round(read["nightly_gbp"] * deal.nights, 2))
        self.assertAlmostEqual(deal.transfer_gbp,
                               PUBLISHED_TRANSFER_GBP[CARDED_GILI_RESORT])
        self.assertTrue(config.min_nights <= deal.nights <= config.max_nights)

    def test_the_board_line_states_every_basis_the_villa_sells(self):
        # render_board_line is the card's board row: the basis, and each sold
        # basis priced hotel-only for the party across this stay's nights.
        config, deals = self._run()
        deal = next(d for d in deals if d.resort_name == CARDED_GILI_RESORT)
        line = hol.render_board_line(deal)
        self.assertIn("Board:", line)
        self.assertIn("Bed &amp; Breakfast", line)
        self.assertIn(f"{deal.nights} nights for the party", line)
        self.assertIn("£3,856", line)
        rows = hol.board_totals(SUMMER_RESORT_CATALOG["gili_islands"][0], deal.nights)
        self.assertEqual([row["label"] for row in rows], ["Bed & Breakfast"])

    def test_the_room_only_stays_are_refused_on_breakfast_not_on_price(self):
        config, deals = self._run()
        names = {deal.resort_name for deal in deals}
        filtered = dict(hol.LAST_FILTERED_OUT)
        for name in ("BASK Gili Meno", "Rimba Villas"):
            with self.subTest(resort=name):
                self.assertNotIn(name, names)
                self.assertIn("breakfast is the minimum", filtered[name])
                self.assertIn("room only", filtered[name])

    def test_the_email_shows_the_board_next_to_the_priced_stay(self):
        config, deals = self._run()
        plain = self._email_text(config, deals)
        # The at-a-glance table carries the basis beside the resort and the island.
        self.assertRegex(
            plain,
            r"Pondok Santi Estate\|Gili Trawangan[^|]*\|[^|]*\|Bed & Breakfast\|£[\d,]+")
        # The card itself (the star line is only on a card, never the glance
        # table) states the basis beside the stay price it read.
        card = re.search(r"Pondok Santi Estate \|★+\|Gili Trawangan.{0,400}", plain, re.S)
        self.assertIsNotNone(card, "no card for the Gili villa in the compact e-mail")
        self.assertIn("Bed & Breakfast", card.group(0))
        self.assertIn("stay £3,856", card.group(0))

    def test_the_email_names_the_refused_stays_with_their_reason(self):
        # Priced-but-refused resorts are listed, not dropped: possible only
        # because both now carry a rate, since an unpriced resort is not
        # named in the compact e-mail's filtered block at all.
        config, deals = self._run()
        plain = self._email_text(config, deals)
        for name in ("BASK Gili Meno", "Rimba Villas"):
            with self.subTest(resort=name):
                self.assertRegex(
                    re.sub(r"\|+", " ", plain),
                    name + r"\s+—\s+room only.{0,60}breakfast is the minimum")

    def test_the_gili_destination_never_vanishes_from_the_report(self):
        # The July example's own never-silent equation, scoped to the new
        # key: every Gili resort the catalogue holds is carded or named with a
        # reason, at the config's real ceiling and at an unbounded one.
        for budget in (10 ** 9, None):
            config = _july()
            deals = collect_holiday_deals(
                config, max_budget_gbp=budget or config.max_budget_gbp)
            carded = {deal.resort_name for deal in deals}
            stated = ({name for name, _reason in hol.LAST_FILTERED_OUT}
                      | {row["resort_name"] for row in hol.LAST_OVER_BUDGET})
            catalog = hol.resort_catalog(config)
            self.assertIn("gili_islands", catalog)
            for row in catalog["gili_islands"]:
                with self.subTest(resort=row["name"],
                                  budget=budget or "config ceiling"):
                    self.assertTrue(row["name"] in carded | stated,
                                    f"{row['name']} vanished from the July report")


if __name__ == "__main__":
    unittest.main()
