"""A read rate beats a catalogue guess, island boards, and a package's own rooms
(owner brief 2026-10-05, H14).

Three defects in one report, and one root cause wearing three costumes: the
card described something other than the thing it was priced on.

1. **A catalogue guess beat a read rate.** A card on a pair nobody read a hotel
   rate for was priced from the CATALOGUE nightly while the same property had
   been read for other pairs in the same season. The catalogue nightly is a
   guess; a read for other dates is a measurement, and the card must never
   quote the guess while the measurement sits in the same evidence file. So a
   read for this property, this board and this unit in this season is priced
   onto the card's own nights as a DERIVED nightly, labelled with the read it
   came from, and the catalogue nightly is used only when no read exists at all.
   The budget rules then decide card vs over-budget list exactly as before —
   which is how a card priced honestly leaves the card list.
2. **Island boards.** An island resort (Maldives, Mauritius, Zanzibar,
   Seychelles) shows every board basis the hotel sells, each priced, because
   eating out is not realistic there and the choice of board IS the price.
   Nungwi Dreams rendered "Bed & Breakfast" alone on a July card whose reads
   carried half board, full board and all inclusive. A board nobody stated is
   still "board unverified" and never becomes a priced row.
3. **A package card described the wrong rooms.** A card priced at an operator's
   package described the CATALOGUE's rooms under the package's price: the
   package is two Grand Deluxe rooms, and the card said "Presidential Suite, one
   unit for 5". On a package-priced card the sleeping line describes the
   package's rooms.

Every fixture here is synthetic in its own fields — the property names are the
real ones, the numbers are the real reads' own figures, and no budget, party
address, name or path from the owner's setup appears anywhere. A fixture built
from invented prices would make the arithmetic on the card harder to check
against the card it is testing.
"""

from __future__ import annotations

import json
import tempfile
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    board_line,
    freshness_tag,
    render_holiday_report_compact,
)
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    package_rooms_words,
)
from public_flight_search.hotel_evidence import (
    consume_hotel_skip_log,
    hotel_rates_near,
    load_hotel_evidence,
)
from public_flight_search.package_evidence import load_package_evidence

ISLAND = "Nungwi Dreams by Mantis"
MAINLAND = "Pullman Khao Lak Resort"
MELATI = "Melati Beach Resort & Spa"

NOW = "2026-10-05T09:00:00+00:00"

#: Khao Lak: the 14-night pair carries the read, the 13-night pair does not.
#: At GBP 1,000 a night the read puts the first pair at 4,695 + 14,000 + 16.50
#: + 76.58 = 18,788.08 and the derived one at 17,788.08, so a ceiling of 18,000
#: admits only the pair that was NOT read. That is the real case: the read
#: priced the honest pair out of the budget, and the engine fell back to a
#: catalogue nightly to find something that fitted.
MAINLAND_BUDGET = 18000.0
#: Nungwi: 5,349 + 17,881.14 + 16.50 = 23,246.64 read, 21,969.43 derived.
ISLAND_BUDGET = 22500.0

ISLAND_CONFIG = """
{
  "report_title": "Island boards",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 22500,
  "min_nights": 12,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-06-25", "2027-06-26"],
  "return_dates": ["2027-07-09"],
  "destinations": [
    {"key": "zanzibar", "label": "Zanzibar", "airports": ["ZNZ"], "flight_hours": 11.67}
  ]
}
"""

MAINLAND_CONFIG = """
{
  "report_title": "A read rate on another pair",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 18000,
  "min_nights": 12,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-06-25", "2027-06-26"],
  "return_dates": ["2027-07-09"],
  "destinations": [
    {"key": "khao_lak", "label": "Khao Lak", "airports": ["HKT"], "flight_hours": 14.5}
  ]
}
"""

WINTER_ISLAND_CONFIG = """
{
  "report_title": "Island boards in December",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 19000,
  "min_nights": 7,
  "max_nights": 9,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2026-12-17", "2026-12-18", "2026-12-20"],
  "return_dates": ["2026-12-25", "2026-12-26", "2026-12-28"],
  "destinations": [
    {"key": "zanzibar", "label": "Zanzibar", "airports": ["ZNZ"], "flight_hours": 11.67}
  ]
}
"""

PACKAGE_CONFIG = """
{
  "report_title": "Package rooms",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 12,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-06-25"],
  "return_dates": ["2027-07-09"],
  "destinations": [
    {"key": "koh_samui", "label": "Koh Samui", "airports": ["USM"], "flight_hours": 14.92}
  ]
}
"""


def _rate(property_name: str, *, board: str = "BB", check_in: str = "2027-06-25",
          check_out: str = "2027-07-09", nights: int = 14, public: float = 0.0,
          shape: str = "single_unit", units: str = "FOUR BEDROOM PRESIDENTIAL VILLA",
          season: str = "summer", destination_key: str = "zanzibar",
          **overrides) -> dict:
    """One hotel rate read, in the exporter's own shape."""
    record = {
        "property_name": property_name,
        "destination_key": destination_key,
        "season": season,
        "vendor": "Example brand booking engine",
        "check_in": check_in,
        "check_out": check_out,
        "nights": nights,
        "party": {"adults": 5, "children": 0},
        "booking_shape": shape,
        "units": [{"name": units, "adults": 5, "max_persons_stated": "12 pers. max"}],
        "board": board,
        "rate_name": f"SAVER RATE - {board}",
        "price_basis": "total_stay_rate",
        "currency": "GBP",
        "taxes_included": True,
        "prices_shown": [{"unit": units, "public": public}],
        "source_url": f"https://example.invalid/booking?dateIn={check_in}",
        "observed_at": "2026-10-05T08:10:00+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
    }
    record.update(overrides)
    return record


def _island_reads() -> list[dict]:
    """Nungwi's shape: three boards on the 14-night pair, none on the other."""
    return [
        _rate(ISLAND, board="HB", public=17881.14),
        _rate(ISLAND, board="FB", public=22377.61),
        _rate(ISLAND, board="AI", public=23094.81),
    ]


def _mainland_reads(public: float = 14000.0, **overrides) -> list[dict]:
    """Khao Lak's shape: one bed & breakfast read for the 14-night pair."""
    fields = {"public": public, "shape": "two_rooms_one_booking",
              "units": "FAMILY SUITE + DELUXE ROOM",
              "destination_key": "khao_lak"}
    fields.update(overrides)
    return [_rate(MAINLAND, **fields)]


def _melati_package(**overrides) -> dict:
    """Destination2's shape: two rooms, named, with the exporter's own words."""
    room = ("room {n}: {adults} adults, Melati Beach Resort and Spa - "
            "Grand Deluxe - Bed and Breakfast")
    record = {
        "operator_key": "destination2",
        "operator": "Example Operator",
        "property_name": "Melati Beach Resort and Spa",
        "destination_key": "koh_samui",
        "season": "summer",
        "departure_airport": "LHR",
        "outbound_date": "2027-06-25",
        "return_date": "2027-07-09",
        "nights": 14,
        "party": {"adults": 5, "children": 0, "child_ages": []},
        "rooms": 2,
        "room_descriptions": [room.format(n=1, adults=2), room.format(n=2, adults=3)],
        "board": "BB",
        "price_shown": {"amount": 9374.13, "currency": "GBP", "basis": "rooms_sum"},
        "derived_total_gbp": {
            "value": 9374.13,
            "how": ("room 1 £3,875.85 (2 adults, Melati Beach Resort and Spa - "
                    "Grand Deluxe - Bed and Breakfast) + room 2 £5,498.28 (3 adults, "
                    "Melati Beach Resort and Spa - Grand Deluxe - Bed and Breakfast)"),
        },
        "read_method": "dom-text",
        "link_kind": "deep-link",
        "source_url": "https://example.invalid/package/1",
        "observed_at": "2026-10-05T08:00:00+00:00",
        "exact_date_match": True,
        "confidence": "verified-exact-date",
        "flight_cabin": "ECONOMY",
        "flight_cabin_basis": "searched as Class=E (example.py)",
    }
    record.update(overrides)
    return record


def _write(payload: dict) -> str:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    return handle.name


def _deals(config_payload: str, rates: list[dict], packages: list[dict] | None = None):
    """The deals for one synthetic run, with the given evidence loaded."""
    config = load_holiday_config(config_payload)
    loaded = load_hotel_evidence(
        config,
        path=_write({"schema": "holiday_hotel_evidence/1", "rates": rates}),
        now=NOW,
    )
    consume_hotel_skip_log()
    loaded_packages = None
    if packages is not None:
        loaded_packages = load_package_evidence(
            config,
            path=_write({"schema": "holiday_package_evidence/1", "packages": packages}),
            now=NOW,
        )
    deals = collect_holiday_deals(
        config,
        max_budget_gbp=float(config.max_budget_gbp),
        hotel_evidence=loaded,
        package_evidence=loaded_packages,
    )
    consume_hotel_skip_log()
    return config, deals


def _deal(deals, name: str):
    for deal in deals:
        if deal.resort_name == name:
            return deal
    raise AssertionError(f"no card for {name}: {[d.resort_name for d in deals]}")


def _card_html(config, deals) -> str:
    return render_holiday_report_compact(config, generated_at=NOW, deals=deals)


class TestTheNearestReadPricesTheStay(unittest.TestCase):
    """§1: a read for another pair beats the catalogue nightly."""

    def test_the_card_is_built_on_the_pair_that_was_not_read(self):
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads())
        deal = _deal(deals, MAINLAND)
        self.assertEqual((deal.outbound_date, deal.return_date),
                         ("2027-06-26", "2027-07-09"))
        self.assertEqual(deal.nights, 13)

    def test_the_stay_is_the_read_nightly_times_the_card_nights(self):
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads())
        deal = _deal(deals, MAINLAND)
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 1000.0 * 13, places=2)

    def test_the_card_is_not_priced_from_the_catalogue_nightly(self):
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads())
        deal = _deal(deals, MAINLAND)
        catalogue_nightly = hol.SUITE_ARCHITECTURE[MAINLAND]["suite_nightly_gbp"]
        self.assertAlmostEqual(catalogue_nightly * deal.nights, 162.18 * 13, places=2)
        self.assertNotAlmostEqual(deal.hotel_price_total_gbp,
                                  catalogue_nightly * deal.nights, places=2)

    def test_the_card_says_the_stay_is_derived_from_a_read(self):
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads())
        deal = _deal(deals, MAINLAND)
        self.assertEqual(deal.hotel_rate_basis, "read-rate-estimate")
        self.assertEqual(tuple(deal.hotel_rate_read_dates),
                         ("2027-06-25", "2027-07-09"))

    def test_the_board_line_names_the_read_it_came_from(self):
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads())
        line = board_line(_deal(deals, MAINLAND), travellers=5)
        self.assertIn("estimate from a read rate for 25 Jun – 9 Jul", line)

    def test_the_live_tag_does_not_claim_the_stay_was_checked_today(self):
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads())
        deal = _deal(deals, MAINLAND)
        object.__setattr__(deal, "confidence", "verified-exact-date")
        tag, _colour = freshness_tag(deal, generated_at=NOW)
        self.assertNotIn("checked today", tag)
        self.assertIn("read rate", tag)

    def test_the_catalogue_nightly_is_used_when_no_read_exists(self):
        config, deals = _deals(MAINLAND_CONFIG, [])
        deal = _deal(deals, MAINLAND)
        self.assertNotEqual(deal.hotel_rate_basis, "read-rate-estimate")
        self.assertEqual(tuple(deal.hotel_rate_read_dates), ())
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 162.18 * 13, places=2)
        self.assertNotIn("estimate from a read rate", board_line(deal, travellers=5))

    def test_a_read_on_another_board_does_not_price_the_card(self):
        # Khao Lak's board is Bed & Breakfast; a half-board read is a different
        # holiday at a different price and cannot price this card.
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads(board="HB"))
        deal = _deal(deals, MAINLAND)
        self.assertEqual(deal.hotel_rate_basis, "market-supported")
        self.assertEqual(tuple(deal.hotel_rate_read_dates), ())
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 162.18 * 13, places=2)

    def test_a_read_for_another_unit_does_not_price_the_card(self):
        # One villa is not two rooms on one booking. The read has to be for the
        # shape the card's unit is.
        config, deals = _deals(MAINLAND_CONFIG,
                               _mainland_reads(shape="single_unit",
                                               units="FAMILY SUITE"))
        deal = _deal(deals, MAINLAND)
        self.assertEqual(tuple(deal.hotel_rate_read_dates), ())
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 162.18 * 13, places=2)

    def test_a_read_for_another_property_prices_nothing(self):
        config, deals = _deals(MAINLAND_CONFIG, _island_reads())
        deal = _deal(deals, MAINLAND)
        self.assertEqual(tuple(deal.hotel_rate_read_dates), ())

    def test_a_read_for_another_season_prices_nothing(self):
        config, deals = _deals(
            MAINLAND_CONFIG,
            _mainland_reads(destination_key="khao_lak", season="winter"))
        deal = _deal(deals, MAINLAND)
        self.assertEqual(tuple(deal.hotel_rate_read_dates), ())

    def test_an_exact_read_still_outranks_a_derived_one(self):
        # H12's ranking is untouched: a rate read for THIS pair is a stronger
        # claim than one read for a different pair, so the card moves to it.
        config, deals = _deals(ISLAND_CONFIG.replace(
            '"max_budget_gbp": 22500', '"max_budget_gbp": 100000000'),
            _island_reads())
        deal = _deal(deals, ISLAND)
        self.assertEqual((deal.outbound_date, deal.return_date),
                         ("2027-06-25", "2027-07-09"))
        self.assertEqual(deal.hotel_rate_basis, "exact-date-rate")
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 17881.14, places=2)

    def test_a_stay_no_cheaper_than_the_read_leaves_the_card_list(self):
        # The rule the owner asked for: the budget decides, as usual. At a
        # ceiling below every option the read allows — 6,000, where even the
        # two-nights-shorter stopover row clears 6,286 — no card is made and
        # the resort is listed over budget at the read's figure, rather than
        # carrying a cheaper number than anybody read for it.
        config, deals = _deals(
            MAINLAND_CONFIG.replace('"max_budget_gbp": 18000',
                                    '"max_budget_gbp": 6000'),
            _mainland_reads(),
        )
        self.assertEqual([d.resort_name for d in deals], [])
        row = next((r for r in hol.LAST_OVER_BUDGET if r["resort_name"] == MAINLAND),
                   None)
        self.assertIsNotNone(row, f"no over-budget row: {hol.LAST_OVER_BUDGET}")
        self.assertAlmostEqual(row["hotel_cost"], 14000.0, places=2)
        self.assertAlmostEqual(row["true_d2d"], 18788.08, places=2)

    def test_with_no_evidence_the_card_is_unchanged(self):
        # The regression guard: no reads means the engine behaves exactly as
        # H13 left it.
        config, deals = _deals(MAINLAND_CONFIG, [])
        deal = _deal(deals, MAINLAND)
        self.assertEqual(deal.hotel_evidence, None)
        self.assertEqual(deal.board_options, ())
        self.assertEqual(hol.board_code(deal.board_basis), "BB")

    def test_the_footer_names_the_read_the_stay_came_from(self):
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads())
        footer = hol.prices_checked_footer(_deal(deals, MAINLAND), generated_at=NOW)
        self.assertIn("hotel rate estimate from a read for 2027-06-25 to 2027-07-09",
                      footer)
        self.assertNotIn("hotel rate read for these dates", footer)


class TestIslandBoards(unittest.TestCase):
    """§2: an island card shows every board the hotel sells, each priced."""

    def setUp(self):
        self.config, self.deals = _deals(ISLAND_CONFIG, _island_reads())
        self.deal = _deal(self.deals, ISLAND)
        self.line = board_line(self.deal, travellers=5)

    def test_the_card_is_built_on_the_pair_without_a_read(self):
        self.assertEqual((self.deal.outbound_date, self.deal.return_date),
                         ("2027-06-26", "2027-07-09"))

    def test_the_cheapest_read_board_is_the_headline(self):
        self.assertEqual(hol.board_code(self.deal.board_basis), "HB")
        self.assertTrue(self.line.startswith("Half Board · about £"))

    def test_the_stay_is_the_cheapest_read_board_for_the_card_nights(self):
        self.assertAlmostEqual(self.deal.hotel_price_total_gbp,
                               (17881.14 / 14) * 13, places=2)

    def test_every_other_read_board_is_priced_on_the_card(self):
        # Each row is the same trip with that board's stay: the card's door-to-
        # door total, minus this card's stay, plus the other board's.
        stay = (17881.14 / 14) * 13
        for label, public in (("Full Board", 22377.61), ("All Inclusive", 23094.81)):
            with self.subTest(board=label):
                other = (public / 14) * 13
                expected = self.deal.true_d2d_gbp - stay + other
                self.assertIn(f"{label} £{round(expected):,}", self.line)

    def test_the_rows_are_exactly_the_boards_the_reads_priced(self):
        rows = {row["basis"]: row for row in self.deal.board_options}
        self.assertEqual(set(rows), {"HB", "FB", "AI"})
        self.assertAlmostEqual(rows["AI"]["hotel_cost"], (23094.81 / 14) * 13,
                               places=2)

    def test_the_rows_name_the_boards_in_words(self):
        for label in ("Half Board", "Full Board", "All Inclusive"):
            with self.subTest(board=label):
                self.assertIn(label, self.line)

    def test_an_island_card_with_no_reads_keeps_the_catalogue_board(self):
        # The July catalogue entry was read when Bed & Breakfast was the only
        # basis on offer. Nothing read means nothing added: the catalogue's own
        # board and its own rows, exactly as H13 left them.
        config, deals = _deals(ISLAND_CONFIG, [])
        deal = _deal(deals, ISLAND)
        self.assertTrue(board_line(deal, travellers=5).startswith(
            "Bed & Breakfast · about £"))
        self.assertEqual({row["basis"] for row in deal.board_options}, {"BB"})
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 508.27 * 13, places=2)

    def test_a_board_nobody_stated_is_never_priced_as_a_row(self):
        # Room only is not a deal and states no breakfast, so the loader drops
        # it: the card keeps the catalogue's bed & breakfast, the catalogue's
        # one row, and the catalogue's nightly. Nothing is assumed into being
        # a basis nobody sold.
        config, deals = _deals(ISLAND_CONFIG, [
            _rate(ISLAND, board="RO", public=9000.00),
        ])
        deal = _deal(deals, ISLAND)
        self.assertEqual({row["basis"] for row in deal.board_options}, {"BB"})
        self.assertEqual(hol.board_code(deal.board_basis), "BB")
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 508.27 * 13, places=2)

    def test_an_over_budget_island_row_prices_its_boards_from_the_read(self):
        # The row that replaces the card has to say the same thing the card
        # would have: "every basis the hotel sells", then the read's three.
        # Listing the catalogue's single bed & breakfast at a fifth of the stay
        # above it would be describing a different holiday. The ceiling is a
        # synthetic 12,000 — below every option this fixture can price.
        config, deals = _deals(
            ISLAND_CONFIG.replace('"max_budget_gbp": 22500',
                                  '"max_budget_gbp": 12000'),
            _island_reads(),
        )
        self.assertEqual([d.resort_name for d in deals], [])
        row = next((r for r in hol.LAST_OVER_BUDGET if r["resort_name"] == ISLAND),
                   None)
        self.assertIsNotNone(row, f"no over-budget row: {hol.LAST_OVER_BUDGET}")
        self.assertEqual({b["basis"] for b in row["board_options"]},
                         {"HB", "FB", "AI"})
        self.assertEqual(hol.board_code(row["board"]), "HB")
        self.assertAlmostEqual(row["hotel_cost"], 17881.14, places=2)

    def test_a_mainland_card_does_not_gain_read_board_rows(self):
        # The island rule is the island rule: a Khao Lak read that happens to
        # carry a second board does not turn its card into a board table.
        config, deals = _deals(MAINLAND_CONFIG, _mainland_reads() + [
            _rate(MAINLAND, board="HB", public=20000.00,
                  shape="two_rooms_one_booking",
                  units="FAMILY SUITE + DELUXE ROOM", destination_key="khao_lak"),
        ])
        deal = _deal(deals, MAINLAND)
        self.assertEqual(deal.board_options, ())
        self.assertEqual(hol.board_code(deal.board_basis), "BB")
        self.assertIn("Bed & Breakfast", board_line(deal, travellers=5))


class TestIslandBoardsReadInDecember(unittest.TestCase):
    """§2 on the winter entry, whose catalogue board is Half Board."""

    def test_the_reads_beat_the_catalogue_board_options(self):
        # A ceiling above every option, so the card lands on the pair that WAS
        # read and prices the read itself.
        config, deals = _deals(WINTER_ISLAND_CONFIG.replace(
            '"max_budget_gbp": 19000', '"max_budget_gbp": 100000000'), [
            _rate(ISLAND, board="HB", check_in="2026-12-18",
                  check_out="2026-12-26", nights=8, public=14057.95,
                  season="winter"),
            _rate(ISLAND, board="FB", check_in="2026-12-18",
                  check_out="2026-12-26", nights=8, public=15421.03,
                  season="winter"),
        ])
        deal = _deal(deals, ISLAND)
        self.assertEqual((deal.outbound_date, deal.return_date),
                         ("2026-12-18", "2026-12-26"))
        # The catalogue prices half board at 1,120.04 a night and full board at
        # 1,250.12; the read prices them at 1,757.24 and 1,927.63, and the read
        # is the number the card carries.
        self.assertAlmostEqual(deal.hotel_price_total_gbp, 14057.95, places=2)
        self.assertEqual({row["basis"] for row in deal.board_options}, {"HB", "FB"})
        rows = {row["basis"]: row for row in deal.board_options}
        self.assertAlmostEqual(rows["FB"]["hotel_cost"], 15421.03, places=2)

    def test_a_winter_read_on_another_pair_prices_the_stay(self):
        # The same rule in December, on a pair nobody read: the card is built on
        # 17-25 Dec and the stay is the read's nightly for eight nights.
        config, deals = _deals(WINTER_ISLAND_CONFIG, [
            _rate(ISLAND, board="HB", check_in="2026-12-20",
                  check_out="2026-12-28", nights=8, public=14057.95,
                  season="winter"),
            _rate(ISLAND, board="FB", check_in="2026-12-20",
                  check_out="2026-12-28", nights=8, public=15421.03,
                  season="winter"),
        ])
        deal = _deal(deals, ISLAND)
        # 20-28 Dec is priced at the read itself and clears the ceiling at
        # 20,028.45, so the card is built on the 7-night pair beside it and the
        # stay is the read's nightly for seven nights.
        self.assertEqual((deal.outbound_date, deal.return_date),
                         ("2026-12-18", "2026-12-25"))
        self.assertEqual(deal.nights, 7)
        self.assertEqual(deal.hotel_rate_basis, "read-rate-estimate")
        self.assertEqual(tuple(deal.hotel_rate_read_dates),
                         ("2026-12-20", "2026-12-28"))
        self.assertAlmostEqual(deal.hotel_price_total_gbp,
                               (14057.95 / 8) * 7, places=2)

    def test_a_winter_card_with_no_reads_still_shows_the_catalogue_boards(self):
        config, deals = _deals(WINTER_ISLAND_CONFIG, [])
        deal = _deal(deals, ISLAND)
        self.assertEqual({row["basis"] for row in deal.board_options},
                         {"HB", "FB", "AI"})
        line = board_line(deal, travellers=5)
        self.assertTrue(line.startswith("Half Board · about £"))
        self.assertIn("Full Board £", line)
        self.assertIn("All Inclusive £", line)


class TestNearestReadLookup(unittest.TestCase):
    """The lookup itself: same property, nearest first, one booking shape."""

    #: Four priceable pairs, so every read below survives the loader's own
    #: "is this a pair this run prices" gate and the ordering is the lookup's.
    CONFIG = """
{
  "report_title": "Nearest read",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "max_budget_gbp": 100000000,
  "min_nights": 12,
  "max_nights": 21,
  "departure_window": ["06:00", "23:59"],
  "origins": ["LHR"],
  "outbound_dates": ["2027-06-20", "2027-06-25", "2027-06-30"],
  "return_dates": ["2027-07-04", "2027-07-09", "2027-07-20"],
  "destinations": [
    {"key": "zanzibar", "label": "Zanzibar", "airports": ["ZNZ"], "flight_hours": 11.67}
  ]
}
"""

    def setUp(self):
        config = load_holiday_config(self.CONFIG)
        self.loaded = load_hotel_evidence(
            config,
            path=_write({"schema": "holiday_hotel_evidence/1", "rates": [
                _rate(ISLAND, public=17881.14),                       # 25 Jun-9 Jul
                _rate(ISLAND, board="FB", public=22377.61),           # 25 Jun-9 Jul
                _rate(ISLAND, board="AI", public=23094.81),           # 25 Jun-9 Jul
                _rate(ISLAND, public=25507.78, check_in="2027-06-30",
                      check_out="2027-07-20", nights=20),
                # Far away, much cheaper, and two rooms rather than one villa.
                _rate(ISLAND, public=5000.00, check_in="2027-06-20",
                      check_out="2027-07-04", nights=14,
                      shape="two_rooms_one_booking"),
            ]}),
            now=NOW,
        )
        consume_hotel_skip_log()

    def test_the_read_pair_itself_is_not_offered_as_near(self):
        starts = [entry.check_in for entry in hotel_rates_near(
            self.loaded, ISLAND, "2027-06-25", "2027-07-09")]
        self.assertNotIn("2027-06-25", starts)

    def test_the_nearest_read_is_first_not_the_cheapest(self):
        # From 26 Jun: 25 Jun-9 Jul is one day away, 20 Jun-4 Jul eleven days,
        # 30 Jun-20 Jul fifteen — and the nearest read is the dearest of the
        # three, which is the point. A nightly carried from a nearer pair is a
        # better guide to these dates than a cheaper one from further off.
        near = hotel_rates_near(self.loaded, ISLAND, "2027-06-26", "2027-07-09")
        self.assertEqual([entry.check_in for entry in near],
                         ["2027-06-25", "2027-06-20", "2027-06-30"])
        self.assertAlmostEqual(near[0].cheapest.price_gbp, 17881.14, places=2)

    def test_the_read_pair_itself_is_excluded_from_every_query(self):
        near = hotel_rates_near(self.loaded, ISLAND, "2027-06-20",
                                "2027-07-04")
        self.assertEqual([entry.check_in for entry in near],
                         ["2027-06-25", "2027-06-30"])

    def test_only_the_asked_booking_shape_is_offered(self):
        near = hotel_rates_near(self.loaded, ISLAND, "2027-06-26", "2027-07-09")
        villas = [entry.check_in for entry in near
                  if entry.cheapest.booking_shape == "single_unit"]
        two_rooms = [entry.check_in for entry in near
                     if entry.cheapest.booking_shape == "two_rooms_one_booking"]
        self.assertEqual(villas, ["2027-06-25", "2027-06-30"])
        self.assertEqual(two_rooms, ["2027-06-20"])
        self.assertEqual(
            [entry.check_in for entry in hotel_rates_near(
                self.loaded, ISLAND, "2027-06-26", "2027-07-09",
                booking_shape="two_rooms_one_booking")],
            ["2027-06-20"])

    def test_a_shape_nobody_read_is_not_offered(self):
        self.assertEqual(
            hotel_rates_near(self.loaded, ISLAND, "2027-06-26", "2027-07-09",
                             booking_shape="three_rooms"),
            ())

    def test_another_property_offers_nothing(self):
        self.assertEqual(
            hotel_rates_near(self.loaded, "Nowhere Resort", "2027-06-26",
                             "2027-07-09"),
            ())

    def test_nothing_loaded_offers_nothing(self):
        self.assertEqual(
            hotel_rates_near({}, ISLAND, "2027-06-26", "2027-07-09"), ())

    def test_a_read_with_no_priceable_nightly_offers_nothing(self):
        # A rate whose nights cannot divide is not a nightly and may not be
        # carried onto other dates; the loader admits no such record, so this is
        # the guard on the arithmetic itself.
        config = load_holiday_config(self.CONFIG)
        loaded = load_hotel_evidence(
            config,
            path=_write({"schema": "holiday_hotel_evidence/1", "rates": [
                _rate(ISLAND, public=17881.14, nights=0),
            ]}),
            now=NOW,
        )
        consume_hotel_skip_log()
        self.assertEqual(
            hotel_rates_near(loaded, ISLAND, "2027-06-26", "2027-07-09"), ())


class TestAPackageCardDescribesItsOwnRooms(unittest.TestCase):
    """§3: the sleeping line on a package-priced card is the package's rooms."""

    def _card(self, **overrides):
        config, deals = _deals(PACKAGE_CONFIG, [],
                               packages=[_melati_package(**overrides)])
        return config, _deal(deals, MELATI)

    def test_the_card_is_priced_at_the_package(self):
        config, deal = self._card()
        self.assertTrue(deal.package_priced)
        self.assertAlmostEqual(deal.total_package_price_gbp, 9374.13, places=2)

    def test_the_sleeping_line_is_the_packages_rooms(self):
        config, deal = self._card()
        self.assertEqual(package_rooms_words(deal),
                         "2 rooms: Grand Deluxe (2 adults), Grand Deluxe (3 adults)")

    def test_the_catalogue_unit_is_not_on_a_package_card(self):
        config, deal = self._card()
        html = _card_html(config, [deal])
        self.assertIn("Grand Deluxe", html)
        self.assertNotIn("Presidential Suite", html)

    def test_a_package_priced_card_names_no_read_behind_its_stay(self):
        # The operator's quote IS this stay, so the card must not point at a
        # hotel read that priced nothing: "estimate from a read rate for ..." on
        # a card priced by a package would be naming a figure that is not there.
        config, deal = self._card()
        self.assertEqual(tuple(deal.hotel_rate_read_dates), ())
        self.assertEqual(deal.hotel_rate_basis, "operator package")
        line = board_line(deal, travellers=5)
        self.assertNotIn("estimate from a read rate", line)

    def test_occupants_alone_are_stated_when_the_room_is_not(self):
        # Older records name no room type. Who sleeps where is still the
        # package's own rooms; inventing a room name is not.
        config, deal = self._card(room_descriptions=["room 1: 3 adults",
                                                     "room 2: 2 adults, same booking"])
        self.assertEqual(package_rooms_words(deal), "2 rooms: 3 adults, 2 adults")

    def test_a_package_that_states_no_rooms_keeps_the_catalogue_unit(self):
        config, deal = self._card(room_descriptions=[])
        self.assertEqual(package_rooms_words(deal), "")
        self.assertIn("Presidential Suite", _card_html(config, [deal]))

    def test_a_comparison_package_does_not_rewrite_the_card(self):
        # A package that only rides BESIDE the headline did not price this
        # card, so the card's rooms are still the catalogue's.
        config, deals = _deals(PACKAGE_CONFIG, [], packages=[
            _melati_package(flight_cabin="", price_shown={
                "amount": 40000.00, "currency": "GBP", "basis": "whole_party_total"}),
        ])
        deal = _deal(deals, MELATI)
        self.assertFalse(deal.package_priced)
        self.assertEqual(package_rooms_words(deal), "")

    def test_an_engine_priced_card_still_describes_the_catalogue_unit(self):
        config, deals = _deals(PACKAGE_CONFIG, [])
        html = _card_html(config, deals)
        self.assertIn("Presidential Suite", html)

    def test_the_detailed_renderer_names_the_package_rooms_too(self):
        # Both renderers state the same rooms: the audit page is not allowed to
        # describe the booking the e-mail describes differently.
        config, deal = self._card()
        html = hol.render_holiday_report(config, generated_at=NOW, deals=[deal])
        self.assertIn("Package rooms for 5", html)
        self.assertIn("Grand Deluxe (2 adults)", html)
        self.assertNotIn("Family Unit for 5", html)

    def test_the_detailed_renderer_keeps_the_catalogue_unit_without_a_package(self):
        config, deals = _deals(PACKAGE_CONFIG, [])
        html = hol.render_holiday_report(config, generated_at=NOW, deals=deals)
        self.assertIn("Family Unit for 5", html)


if __name__ == "__main__":
    unittest.main()
