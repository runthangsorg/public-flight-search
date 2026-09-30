"""Owner rules of 2026-09-30: board basis and three flight options.

Board basis (both planners):

* every hotel deal includes breakfast at minimum; room-only is not a deal;
* a rate whose page did not state the board is "board unverified" and is never
  assumed to include breakfast;
* island resorts (Maldives, Mauritius, Zanzibar, Seychelles) show every board
  basis the hotel actually sells, each priced separately, and nothing invented;
* stopover hotels (Doha, Muscat) are breakfast at minimum too.

Flights, for every long-haul (over 8 hours) destination, side by side and each
a total for the whole party:

* (a) Business on the normal route: the default headline;
* (b) Economy on the same route;
* (c) Economy with about two nights in Doha or Muscat each way, stopover
  hotels included.

The budget is tested against each option separately, and no option is hidden
because another fits better.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holidays import (
    BREAKFAST_BASES,
    ISLAND_RULE_KEYS,
    STOPOVER_HUBS,
    STOPOVER_LINK_HUBS,
    board_code,
    collect_holiday_deals,
    filter_resorts,
    load_holiday_config,
    render_holiday_report,
    resort_catalog,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
DEC = ROOT / "examples" / "dec_holiday_config.json"
#: Synthetic ceilings; neither is the owner's budget.
UNCAPPED_GBP = 60000.0


def _resort(name: str, board: str, **extra) -> dict:
    hol.SUITE_ARCHITECTURE.setdefault(
        name,
        {
            "suite_type": "test unit", "suite_nightly_gbp": 100.0,
            "suite_peak_nightly_gbp": 100.0, "beach_walkable": True,
            "pool_heated_c": 28, "tripadvisor": 4.6, "nonstop_from": (),
        },
    )
    resort = {"name": name, "board": board}
    resort.update(extra)
    return resort


class BoardCodeTests(unittest.TestCase):
    def test_board_text_maps_to_a_basis(self):
        cases = {
            "Bed & Breakfast": "BB",
            "Half Board": "HB",
            "Full Board": "FB",
            "All Inclusive": "AI",
            "Ultra All Inclusive": "AI",
            "Golden Inclusive": "AI",
            "Luxury All Inclusive": "AI",
            "Room only": "RO",
            "board unverified": "UNVERIFIED",
            "": "UNVERIFIED",
            "something new": "UNVERIFIED",
        }
        for text, code in cases.items():
            with self.subTest(text=text):
                self.assertEqual(board_code(text), code)
        self.assertEqual(BREAKFAST_BASES, frozenset({"BB", "HB", "FB", "AI"}))


class BreakfastMinimumTests(unittest.TestCase):
    def test_room_only_is_never_a_deal(self):
        kept, dropped = filter_resorts([_resort("Test Room Only Resort", "Room only")])
        self.assertEqual(kept, [])
        self.assertIn("room only", dropped[0][1])

    def test_an_unstated_board_is_never_assumed(self):
        kept, dropped = filter_resorts([_resort("Test Unverified Resort", "board unverified")])
        self.assertEqual(kept, [])
        self.assertIn("board unverified", dropped[0][1])

    def test_breakfast_and_above_are_kept(self):
        for board in ("Bed & Breakfast", "Half Board", "Full Board", "All Inclusive"):
            with self.subTest(board=board):
                kept, _ = filter_resorts([_resort(f"Test {board} Resort", board)])
                self.assertEqual(len(kept), 1)

    def test_no_catalogue_card_is_room_only_or_unverified(self):
        for config_path in (JULY, DEC):
            config = load_holiday_config(config_path.read_text(encoding="utf-8"))
            for deal in collect_holiday_deals(config, max_budget_gbp=UNCAPPED_GBP):
                with self.subTest(config=config_path.name, resort=deal.resort_name):
                    self.assertIn(board_code(deal.board_basis), BREAKFAST_BASES)


class IslandBoardTests(unittest.TestCase):
    def test_island_keys(self):
        for key in ("maldives", "mauritius", "zanzibar", "seychelles"):
            self.assertIn(key, ISLAND_RULE_KEYS)

    def test_an_island_resort_must_price_each_basis_it_sells(self):
        bare = _resort("Test Island Bare", "Half Board")
        kept, dropped = filter_resorts([bare], island=True)
        self.assertEqual(kept, [])
        self.assertIn("board", dropped[0][1])
        priced = _resort(
            "Test Island Priced", "Half Board",
            board_options=(
                {"basis": "HB", "nightly_gbp": 400.0, "source": "test"},
                {"basis": "AI", "nightly_gbp": 520.0, "source": "test"},
            ),
        )
        kept, dropped = filter_resorts([priced], island=True)
        self.assertEqual(len(kept), 1, dropped)

    def test_an_island_option_cannot_be_room_only_or_unpriced(self):
        for options in (
            ({"basis": "RO", "nightly_gbp": 300.0, "source": "test"},),
            ({"basis": "HB", "nightly_gbp": 0.0, "source": "test"},),
            ({"basis": "HB", "nightly_gbp": 300.0, "source": ""},),
        ):
            with self.subTest(options=options):
                resort = _resort("Test Island Broken", "Half Board", board_options=options)
                kept, _ = filter_resorts([resort], island=True)
                self.assertEqual(kept, [])

    def test_every_catalogue_island_resort_prices_its_bases(self):
        for config_path in (JULY, DEC):
            config = load_holiday_config(config_path.read_text(encoding="utf-8"))
            catalog = resort_catalog(config)
            for key in ISLAND_RULE_KEYS:
                for resort in catalog.get(key, []):
                    with self.subTest(resort=resort["name"]):
                        options = resort.get("board_options") or ()
                        self.assertTrue(options)
                        for option in options:
                            self.assertIn(option["basis"], BREAKFAST_BASES)
                            self.assertGreater(option["nightly_gbp"], 0)
                            self.assertTrue(option["source"])
                        self.assertEqual(
                            board_code(resort["board"]),
                            min(options, key=lambda o: o["nightly_gbp"])["basis"],
                        )


class StopoverHotelTests(unittest.TestCase):
    def test_hubs_include_doha_and_muscat_with_breakfast(self):
        # Doha and Muscat are the two hubs the unpriced "price this yourself"
        # link shows (STOPOVER_LINK_HUBS); STOPOVER_HUBS may hold more hubs
        # than that (Abu Dhabi, Dubai, added 2026-09-30) for the priced path.
        self.assertTrue({"DOH", "MCT"}.issubset(set(STOPOVER_HUBS)))
        for hub, info in STOPOVER_HUBS.items():
            with self.subTest(hub=hub):
                self.assertIn(board_code(info["hotel"]["board"]), BREAKFAST_BASES)
                self.assertEqual(info["nights_each_way"], 2)
                self.assertTrue(info["hotel"]["hotel_url"].startswith("https://"))
                self.assertTrue(info["hotel"]["source"])


class StopoverSeasonTests(unittest.TestCase):
    """Owner direction 2026-09-30: Economy-with-stopover is wanted in every
    season, not just July. The fare is therefore season-scoped — a July read
    and a December read coexist, and neither can leak into the other's card."""

    def test_every_read_fare_declares_the_season_it_was_read_for(self):
        for key, fares in hol.STOPOVER_FARES.items():
            for fare in fares:
                with self.subTest(key=key):
                    self.assertIn(
                        str(fare.get("season", "")).strip().lower(), {"summer", "winter"}
                    )

    def test_a_fare_answers_only_for_its_own_season(self):
        # The July reads exist; they must never surface on a December card.
        self.assertTrue(hol.stopover_fares_for("DOH", "HKT", "summer"))
        self.assertEqual(hol.stopover_fares_for("DOH", "HKT", "winter"), ())

    def test_december_cards_gain_no_stopover_from_the_july_reads(self):
        december = load_holiday_config(DEC.read_text(encoding="utf-8"))
        for deal in collect_holiday_deals(december):
            for option in deal.flight_options:
                with self.subTest(resort=deal.resort_name):
                    self.assertNotEqual(option.get("kind"), "stopover")

    def test_a_card_with_no_read_fare_offers_the_hub_itinerary_to_price(self):
        december = load_holiday_config(DEC.read_text(encoding="utf-8"))
        html = render_holiday_report(december, generated_at="2026-09-30T00:00:00+00:00",
                                     deals=collect_holiday_deals(december))
        # No invented price: the block says nothing is priced and links the
        # multi-city itinerary per hub, naming the hub hotel the owner would stay in.
        self.assertIn("One click to price it:", html)
        self.assertIn("price this multi-city itinerary", html)
        self.assertIn("Rixos Gulf Hotel Doha", html)
        self.assertIn("Mövenpick Hotel and Apartments Ghala Muscat", html)
        # And the whole report still fits the e-mail budget (Gmail clips at 102 KB).
        self.assertLess(len(html.encode("utf-8")), 102_000)

    def test_every_link_hub_is_a_real_stopover_hub(self):
        self.assertTrue(STOPOVER_LINK_HUBS)
        self.assertTrue(set(STOPOVER_LINK_HUBS).issubset(set(STOPOVER_HUBS)))

    def test_adding_a_stopover_hub_does_not_grow_the_unpriced_link_list(self):
        # STOPOVER_HUBS can gain hubs for the *priced* path (a real fare read)
        # without inflating the "price this yourself" link list on every
        # long-haul card with no read fare — that list is capped to
        # STOPOVER_LINK_HUBS, because each line costs ~400 bytes and the
        # December report (no priced fares yet, so every long-haul card hits
        # this link path) already sits close to the Gmail 102 KB clip.
        december = load_holiday_config(DEC.read_text(encoding="utf-8"))
        baseline_html = render_holiday_report(
            december, generated_at="2026-09-30T00:00:00+00:00", deals=collect_holiday_deals(december)
        )
        baseline_lines = baseline_html.count("price this multi-city itinerary")
        hol.STOPOVER_HUBS["TEST_EXTRA_HUB"] = {
            "label": "Test Hub",
            "nights_each_way": 2,
            "hotel": {
                "name": "Test Hub Hotel", "hotel_url": "https://example.invalid/test-hub",
                "board": "Bed & Breakfast", "unit": "Test Room",
                "nightly_gbp": 100.0, "source": "test", "confidence": "estimate",
            },
        }
        try:
            grown_html = render_holiday_report(
                december, generated_at="2026-09-30T00:00:00+00:00", deals=collect_holiday_deals(december)
            )
        finally:
            del hol.STOPOVER_HUBS["TEST_EXTRA_HUB"]
        self.assertEqual(grown_html.count("price this multi-city itinerary"), baseline_lines)
        self.assertNotIn("Test Hub Hotel", grown_html)


def _july_uncapped():
    config = load_holiday_config(JULY.read_text(encoding="utf-8"))
    return dataclasses.replace(config, max_budget_gbp=UNCAPPED_GBP)


class FlightOptionTests(unittest.TestCase):
    def test_every_long_haul_card_carries_business_economy_and_stopover(self):
        config = _july_uncapped()
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        thai = {"koh_samui", "koh_phangan", "khao_lak"}
        for deal in deals:
            with self.subTest(resort=deal.resort_name):
                kinds = [o["kind"] for o in deal.flight_options]
                self.assertEqual(kinds[:2], ["business", "economy"])
                self.assertEqual(deal.flight_options[0]["cabin"], "BUSINESS")
                self.assertEqual(deal.flight_options[1]["cabin"], "ECONOMY")
                # The headline stays Business.
                self.assertEqual(deal.cabin_class, "BUSINESS")
                self.assertEqual(deal.total_package_price_gbp, deal.flight_options[0]["total_pkg"])
                if deal.destination_key in thai:
                    self.assertIn("stopover", kinds, "Thailand cards carry a Doha/Muscat stopover option")

    def test_each_option_total_adds_up(self):
        for deal in collect_holiday_deals(_july_uncapped()):
            for option in deal.flight_options:
                if option["total_pkg"] is None:
                    continue
                with self.subTest(resort=deal.resort_name, kind=option["kind"], hub=option.get("hub")):
                    self.assertAlmostEqual(
                        option["total_pkg"],
                        option["flight_cost"] + option["hotel_cost"] + option["stopover_hotel_cost"],
                        places=2,
                    )
                    self.assertAlmostEqual(
                        option["true_d2d"],
                        option["total_pkg"] + option["uk_ground"] + option["transfer"],
                        places=2,
                    )
                    if option["kind"] == "stopover":
                        self.assertEqual(option["cabin"], "ECONOMY")
                        self.assertGreater(option["stopover_hotel_cost"], 0)
                        self.assertEqual(option["stopover_nights"], 4)
                    else:
                        self.assertEqual(option["stopover_hotel_cost"], 0)

    def test_the_budget_is_tested_per_option_and_no_option_is_hidden(self):
        config = _july_uncapped()
        deals = collect_holiday_deals(config)
        khao_lak = next(d for d in deals if d.destination_key == "khao_lak")
        business = khao_lak.flight_options[0]["true_d2d"]
        economy = khao_lak.flight_options[1]["true_d2d"]
        self.assertLess(economy, business)
        # A ceiling between the two: Business over, Economy within. The resort
        # is still a card and still shows its Business option, flagged over.
        ceiling = round((economy + business) / 2, 2)
        squeezed = dataclasses.replace(config, max_budget_gbp=ceiling)
        card = next(
            d for d in collect_holiday_deals(squeezed) if d.resort_name == khao_lak.resort_name
        )
        flags = {o["kind"]: o["within_budget"] for o in card.flight_options if o.get("hub") is None}
        self.assertFalse(flags["business"])
        self.assertTrue(flags["economy"])
        html = render_holiday_report(squeezed, generated_at="2026-09-30T00:00:00+00:00",
                                     deals=collect_holiday_deals(squeezed))
        self.assertIn("Flight options for 5", html)
        self.assertIn("over budget", html)
        self.assertIn("within budget", html)

    def test_a_resort_is_over_budget_only_when_every_option_is(self):
        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        tiny = dataclasses.replace(config, max_budget_gbp=1000.0)
        self.assertEqual(collect_holiday_deals(tiny), ())
        for row in hol.LAST_OVER_BUDGET:
            with self.subTest(resort=row["resort_name"]):
                self.assertTrue(row["flight_options"])
                self.assertFalse(any(o["within_budget"] for o in row["flight_options"]))

    def test_december_doha_and_muscat_are_never_silent(self):
        december = load_holiday_config(DEC.read_text(encoding="utf-8"))
        deals = collect_holiday_deals(december)
        carded = {d.destination_key for d in deals}
        listed = {row["destination_key"] for row in hol.LAST_OVER_BUDGET}
        for key in ("doha", "muscat", "zanzibar", "mauritius", "riviera_maya"):
            with self.subTest(key=key):
                self.assertIn(key, carded | listed)
        html = render_holiday_report(december, generated_at="2026-09-30T00:00:00+00:00", deals=deals)
        self.assertIn("Rixos Gulf Hotel Doha", html)
        self.assertIn("InterContinental Muscat", html)
        self.assertIn("Rule not applied — pools heated", html)

    def test_short_haul_cards_are_unchanged(self):
        december = load_holiday_config(DEC.read_text(encoding="utf-8"))
        for deal in collect_holiday_deals(december):
            if deal.cabin_class == "ECONOMY":
                self.assertEqual(deal.flight_options, ())

    def test_the_card_labels_the_board_and_every_option(self):
        config = _july_uncapped()
        deals = collect_holiday_deals(config)
        html = render_holiday_report(config, generated_at="2026-09-30T00:00:00+00:00", deals=deals)
        self.assertIn("(a) Business", html)
        self.assertIn("(b) Economy", html)
        self.assertIn("(c) Economy + 2 nights", html)
        self.assertIn("Board:", html)


class SeasonCatalogueTests(unittest.TestCase):
    def test_december_only_keys_never_price_a_july_card(self):
        july = load_holiday_config(JULY.read_text(encoding="utf-8"))
        summer = resort_catalog(july)
        winter = hol.WINTER_RESORT_CATALOG
        for key in winter:
            if key not in hol.BOTH_SEASON_WINTER_KEYS:
                with self.subTest(key=key):
                    self.assertIsNot(summer.get(key), winter[key])


if __name__ == "__main__":
    unittest.main()
