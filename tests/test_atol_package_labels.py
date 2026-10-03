"""ATOL honesty on every card: the package route vs the self-build route.

Owner brief 2026-10-03 (F2). A card shows two ways to book the same week:

- a package from an operator — ATOL-protected where the operator is a UK ATOL
  holder, so the card says "ATOL-protected package available" and names the
  operator(s), each with its ATOL number so the claim is checkable; and
- the self-built trip (flights plus a hotel booked separately) — NOT
  ATOL-protected, said plainly as a booking term on the existing Booking
  terms line.

ATOL numbers come from the CAA's own public "Check an ATOL" register (POST
https://aircraftapi.caa.co.uk/api/checkanatol/search, searched by name on
2026-10-03). An operator that does not appear in the register under its own
name is never named as ATOL-protected: Qatar Airways Holidays returns no
results under that name, "Qatar Airways" or "qatarairways" (all searched
2026-10-03), so its link stays but the ATOL line does not name it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import re
import unittest

from public_flight_search import vendors as V
from public_flight_search.holidays import (
    PackageDeal,
    collect_holiday_deals,
    load_holiday_config,
    render_booking_terms,
    render_holiday_report,
    render_vendor_block,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"


def _base_deal(**overrides) -> PackageDeal:
    base = dict(
        resort_name="Test Resort",
        destination_label="Kuta Mandalika, Lombok",
        destination_key="lombok",
        star_rating=5,
        board_basis="Bed & Breakfast",
        outbound_date="2027-07-10",
        return_date="2027-07-20",
        nights=10,
        airline="Test Air",
        origin_airports=("LHR",),
        destination_airport="LOP",
        flight_price_total_gbp=5000.0,
        hotel_price_total_gbp=2000.0,
        total_package_price_gbp=7000.0,
        price_per_person_gbp=1400.0,
        flight_booking_url="https://example.invalid/flight",
        hotel_booking_url="https://example.invalid/hotel",
        is_under_budget=True,
        value_score_verified=True,
        # Non-empty flight_options is what marks a card long-haul.
        flight_options=({"kind": "economy"},),
    )
    base.update(overrides)
    return PackageDeal(**base)


class PackageRouteAtolTests(unittest.TestCase):
    def test_long_haul_block_names_the_atol_protected_operators_with_numbers(self):
        html = render_vendor_block(_base_deal(), adults=5, rooms=(2, 3))
        self.assertIn("ATOL-protected package available", html)
        for statement in (
            "Love Holidays (ATOL 10989)",
            "British Airways Holidays (ATOL 5985)",
            "Emirates Holidays (ATOL 4086)",
            "Etihad Holidays (ATOL 11125)",
            "Kuoni (ATOL 0132)",
            "Trailfinders (ATOL T1458)",
        ):
            with self.subTest(operator=statement):
                self.assertIn(statement, html)

    def test_an_operator_absent_from_the_register_is_never_named_atol_protected(self):
        # Qatar Airways Holidays returned no results in the CAA register
        # (2026-10-03): the link stays, the ATOL claim does not.
        html = render_vendor_block(_base_deal(), adults=5, rooms=(2, 3))
        self.assertIn("Qatar Airways Holidays", html)
        self.assertIsNone(
            re.search(r"Qatar Airways Holidays \(ATOL", html),
            "an unregistered operator must not wear the ATOL claim",
        )
        atol_line = html.split("ATOL-protected package available", 1)[1]
        atol_line = atol_line.split("</div>", 1)[0]
        self.assertNotIn("Qatar Airways Holidays", atol_line)

    def test_short_haul_block_names_its_own_atol_operators(self):
        # Tenerife: a short-haul destination both Love Holidays and
        # Destination2 publish pages for.
        html = render_vendor_block(
            _base_deal(
                flight_options=(), destination_key="tenerife",
                destination_label="Tenerife, Canary Islands",
                destination_airport="TFS",
            ), adults=5, rooms=(2, 3))
        self.assertIn("ATOL-protected package available", html)
        self.assertIn("Love Holidays (ATOL 10989)", html)
        self.assertIn("Destination2 (ATOL 11462)", html)
        self.assertNotIn("Kuoni (ATOL", html)

    def test_every_vendor_name_that_can_render_is_registered_or_excluded(self):
        # The register map must cover every vendor the block can name, or the
        # vendor is the one documented exclusion — otherwise a new operator
        # could be added and silently left out of the ATOL line.
        trip = V.TripQuery(
            destination_key="tenerife", destination_airport="TFS",
            origin_airports=("LGW",), outbound_date="2026-12-22",
            return_date="2026-12-30", nights=8, adults=5, rooms=(2, 2, 1),
        )
        names = {link.vendor for link in V.build_vendor_links(trip)}
        names |= {link.vendor for link in V.build_atol_operator_links(trip)}
        for name in names:
            with self.subTest(vendor=name):
                self.assertTrue(
                    name in V.ATOL_REGISTER_BY_VENDOR
                    or name == "Qatar Airways Holidays",
                    f"{name} is neither in the CAA register map nor the "
                    "documented exclusion",
                )


class SelfBuildAtolTests(unittest.TestCase):
    def test_booking_terms_say_the_self_build_route_is_not_atol_protected(self):
        html = render_booking_terms(_base_deal())
        self.assertIn("Booking terms", html)
        self.assertIn("self-build: not ATOL-protected", html)
        # It is a stated fact, not an unverified gap.
        self.assertNotIn(
            "self-build", html.split("not verified:", 1)[-1]
        )

    def test_the_self_build_statement_survives_a_verified_atol_resort_fact(self):
        # atol_protected is a tri-state fact about the resort's own package
        # data; the self-build statement is about the route the card prices.
        # Both may be true on one card, and the resort fact keeps its wording.
        html = render_booking_terms(_base_deal(atol_protected=True))
        self.assertIn("ATOL protected", html)
        self.assertIn("self-build: not ATOL-protected", html)

    def test_every_card_carries_both_atol_statements(self):
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        html = render_holiday_report(
            config, generated_at="2026-10-03T00:00:00+00:00", deals=deals,
        )
        self.assertGreaterEqual(
            html.count("ATOL-protected package available"), len(deals))
        self.assertGreaterEqual(
            html.count("self-build: not ATOL-protected"), len(deals))


if __name__ == "__main__":
    unittest.main()
