"""A "Booking terms" line that shows only what was verified.

Owner brief 2026-10-02 (T7). Each card must carry a compact Booking terms line
built from VERIFIED resort/offer data only: free-cancellation deadline,
deposit/payment terms, checked baggage, package protection (ATOL or not),
transfer time, beach access and pool. Anything unknown is listed once as
"not verified: …". A value is never invented — an unknown field is stated as
unknown, not guessed.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import unittest

from public_flight_search import holidays as hol
from public_flight_search.holidays import (
    PackageDeal,
    collect_holiday_deals,
    load_holiday_config,
    render_booking_terms,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"


def _base_deal(**overrides) -> PackageDeal:
    base = dict(
        resort_name="Test Resort",
        destination_label="Test, Thailand",
        destination_key="khao_lak",
        star_rating=5,
        board_basis="Bed & Breakfast",
        outbound_date="2027-07-20",
        return_date="2027-07-27",
        nights=7,
        airline="Test Air",
        origin_airports=("LHR",),
        destination_airport="HKT",
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


class BookingTermsModelTests(unittest.TestCase):
    def test_the_data_model_has_optional_term_fields_defaulting_to_none(self):
        deal = _base_deal()
        for field in (
            "free_cancellation_until",
            "deposit_payment",
            "checked_baggage",
            "atol_protected",
            "beach_access",
            "pool",
        ):
            with self.subTest(field=field):
                self.assertTrue(hasattr(deal, field), f"missing optional field {field}")
                self.assertIsNone(getattr(deal, field), f"{field} must default to None")


class BookingTermsRenderingTests(unittest.TestCase):
    def setUp(self):
        # Register the fixture resort so "criteria scores" is treated as
        # assessed; tests that want it unknown simply leave mosque_name empty.
        self._registered = "Test Resort" not in hol.RESORT_CRITERIA
        if self._registered:
            hol.RESORT_CRITERIA["Test Resort"] = {"food": 7}

    def tearDown(self):
        if self._registered:
            hol.RESORT_CRITERIA.pop("Test Resort", None)

    def test_unknown_terms_are_listed_as_not_verified_and_never_invented(self):
        html = render_booking_terms(_base_deal())
        self.assertIn("Booking terms", html)
        self.assertIn("not verified:", html)
        for label in ("cancellation", "baggage", "ATOL", "transfer", "beach", "pool"):
            with self.subTest(label=label):
                self.assertIn(label, html)
        # Nothing was verified, so no field may claim a value.
        self.assertNotIn("ATOL protected", html)
        self.assertNotIn("resort transfer", html)

    def test_verified_terms_are_shown_and_drop_out_of_the_not_verified_list(self):
        html = render_booking_terms(_base_deal(
            mosque_name="Test Mosque",
            mosque_walk_minutes=5,
            free_cancellation_until="free cancellation until 2027-07-06",
            deposit_payment="20% deposit, balance 8 weeks before",
            checked_baggage="23 kg checked bag included",
            atol_protected=True,
            transfer_gbp=77.0,
            beach_access="walkable beach",
            pool="pool heated to 28°C",
        ))
        for value in (
            "free cancellation until 2027-07-06",
            "20% deposit, balance 8 weeks before",
            "23 kg checked bag included",
            "ATOL protected",
            "resort transfer £77",
            "walkable beach",
            "pool heated to 28°C",
        ):
            with self.subTest(value=value):
                self.assertIn(value, html)
        self.assertNotIn("not verified:", html)

    def test_beach_and_transfer_come_from_data_the_code_already_has(self):
        # A real priced card: the resort passed the beach_walkable filter and
        # the code prices a ground transfer. Neither may be listed as unknown.
        html = render_booking_terms(_base_deal(
            transfer_gbp=77.0,
            beach_access="walkable beach",
        ))
        self.assertIn("walkable beach", html)
        self.assertIn("resort transfer £77", html)
        self.assertNotIn("resort transfer £77", html.split("not verified:")[1])

    def test_a_partially_known_card_lists_only_the_unknowns(self):
        html = render_booking_terms(_base_deal(
            checked_baggage="23 kg checked bag included",
            atol_protected=False,
        ))
        self.assertIn("23 kg checked bag included", html)
        # A known "not protected" is a fact, stated as one, not an unknown.
        self.assertIn("not ATOL protected", html)
        self.assertIn("not verified:", html)
        self.assertIn("cancellation", html)
        self.assertIn("beach", html)
        self.assertNotIn("baggage", html.split("not verified:")[1])

    def test_every_rendered_card_carries_the_booking_terms_line(self):
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00", deals=deals,
        )
        self.assertGreaterEqual(html.count("Booking terms"), len(deals))

    def test_the_report_stays_within_the_email_budget(self):
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=collect_holiday_deals(config),
        )
        self.assertLessEqual(len(html.encode("utf-8")), hol.EMAIL_HTML_BUDGET_BYTES)


if __name__ == "__main__":
    unittest.main()
