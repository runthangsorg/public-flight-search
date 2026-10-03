"""Every ATOL number carries its source, and an unsourceable one is gone.

Owner brief 2026-10-03 (F2b). An ATOL number on a card is a claim the reader
may act on, so it must be checkable against a public register without asking
us. Each entry records the exact query that produced it, and an operator the
register does not list is not named at all — a link may stay, a number may not
be invented.

This also pins the fix to the booking-terms line: the self-build route's ATOL
position is always stated, so "not verified: ATOL" alongside it was the same
sentence contradicting itself.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from public_flight_search import vendors as V
from public_flight_search.holidays import PackageDeal, _booking_term_values

ROOT = Path(__file__).parents[1]
VENDORS_SOURCE = ROOT / "src/public_flight_search/vendors.py"


def _deal(**overrides) -> PackageDeal:
    base = dict(
        resort_name="Test Resort",
        destination_label="Lombok",
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
    )
    base.update(overrides)
    return PackageDeal(**base)


class RegisterSourceTests(unittest.TestCase):
    def test_the_register_endpoint_is_the_public_caa_api(self):
        self.assertEqual(
            V.ATOL_REGISTER_SOURCE_URL,
            "https://aircraftapi.caa.co.uk/api/checkanatol/search",
        )

    def test_every_number_names_the_query_that_produced_it(self):
        # The register matches on the holder's own spelling, which is not
        # always the vendor's trading name: Destination2 is listed as
        # "Destination 2", so a lookup by the brand name returns nothing and
        # the number would have looked unsourceable.
        self.assertEqual(
            sorted(V.ATOL_REGISTER_BY_VENDOR),
            sorted(V.ATOL_REGISTER_QUERIES),
            "every ATOL number must record the register name that was queried",
        )

    def test_a_brand_that_differs_from_the_register_spells_out_the_query(self):
        self.assertEqual(V.ATOL_REGISTER_QUERIES["Destination2"], "Destination 2")
        self.assertEqual(V.ATOL_REGISTER_QUERIES["Kuoni"], "Kuoni")

    def test_the_query_date_is_recorded(self):
        self.assertRegex(V.ATOL_REGISTER_QUERIED_ON, r"^\d{4}-\d{2}-\d{2}$")

    def test_the_source_block_is_in_the_source_file_next_to_the_numbers(self):
        # A source that lives only in a test is a source nobody reading
        # vendors.py will ever find.
        text = VENDORS_SOURCE.read_text(encoding="utf-8")
        self.assertIn("ATOL_REGISTER_SOURCE_URL", text)
        self.assertIn("aircraftapi.caa.co.uk", text)
        self.assertIn("atol.org.uk", text)

    def test_every_number_sits_on_a_line_naming_its_holder(self):
        text = VENDORS_SOURCE.read_text(encoding="utf-8")
        for vendor, number in V.ATOL_REGISTER_BY_VENDOR.items():
            pattern = re.compile(
                rf'^\s*"{re.escape(vendor)}":\s*"{re.escape(number)}",.*#',
                re.MULTILINE,
            )
            with self.subTest(vendor=vendor):
                self.assertRegex(
                    text,
                    pattern,
                    "each ATOL number must carry a comment naming its holder",
                )

    def test_qatar_holidays_is_not_named_as_atol_protected(self):
        # The register returns nothing under "Qatar Airways Holidays",
        # "Qatar Airways" or "qatarairways" (queried 2026-10-03), so there is
        # no number to show and the link carries no ATOL claim.
        self.assertNotIn("Qatar Airways", V.ATOL_REGISTER_BY_VENDOR)


class BookingTermsAtolTests(unittest.TestCase):
    def test_atol_is_not_listed_as_unverified_when_the_self_build_fact_is_stated(self):
        verified, unknown = _booking_term_values(_deal())
        self.assertIn("self-build: not ATOL-protected", verified)
        self.assertNotIn(
            "ATOL", unknown,
            "the card already states the ATOL position of the route it prices",
        )

    def test_a_known_package_position_is_still_stated(self):
        verified, unknown = _booking_term_values(_deal(atol_protected=True))
        self.assertIn("ATOL protected", verified)
        self.assertNotIn("ATOL", unknown)

    def test_a_known_unprotected_package_is_still_stated(self):
        verified, unknown = _booking_term_values(_deal(atol_protected=False))
        self.assertIn("not ATOL protected", verified)
        self.assertNotIn("ATOL", unknown)


if __name__ == "__main__":
    unittest.main()