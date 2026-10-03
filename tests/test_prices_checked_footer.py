"""A "Prices last checked" footer on every card.

Owner brief 2026-10-03 (F4). A card's numbers are only as good as their age,
so each card ends with one short footer line — "Prices last checked: flights
<age>, hotel <age>" — built from the observed-at fields the data already
carries, never an invented date:

- flights: the age of the observed fare (``live_observed_at``) at render
  time; when no fare was observed the footer says so plainly instead of
  dressing a benchmark up as an observation.
- hotel: there is no hotel observed-at field anywhere in the data, so the
  hotel leg states the rate's basis rather than a fabricated age. When the
  rate is an estimate built from the nearest dates on sale, the footer says
  "hotel rate from nearest dates, not your exact dates".
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import unittest

from public_flight_search.holidays import (
    PackageDeal,
    collect_holiday_deals,
    load_holiday_config,
    prices_checked_footer,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"

GENERATED_AT = "2026-10-03T00:00:00+00:00"


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
        hotel_rate_basis="market-supported",
        live_observed_at="2026-09-30T00:00:00+00:00",
    )
    base.update(overrides)
    return PackageDeal(**base)


class PricesCheckedFooterTests(unittest.TestCase):
    def test_flight_age_is_shown_in_words(self):
        html = prices_checked_footer(_base_deal(), generated_at=GENERATED_AT)
        self.assertIn("Prices last checked:", html)
        self.assertIn("flights 3 days ago", html)

    def test_a_benchmark_flight_never_wears_an_observed_age(self):
        html = prices_checked_footer(
            _base_deal(live_observed_at=""), generated_at=GENERATED_AT)
        self.assertIn("flights not observed", html)
        self.assertNotIn("flights 3 days ago", html)
        self.assertNotIn("days ago, hotel", html)

    def test_nearest_dates_hotel_rate_says_so_in_the_briefs_words(self):
        html = prices_checked_footer(
            _base_deal(hotel_rate_basis="estimate"), generated_at=GENERATED_AT)
        self.assertIn("hotel rate from nearest dates, not your exact dates", html)

    def test_exact_dates_hotel_rate_is_stated_as_read(self):
        html = prices_checked_footer(
            _base_deal(hotel_rate_basis="market-supported"),
            generated_at=GENERATED_AT,
        )
        self.assertIn("hotel rate read for these dates", html)
        self.assertNotIn("nearest dates", html)

    def test_an_unreadable_observation_timestamp_says_date_unknown(self):
        html = prices_checked_footer(
            _base_deal(live_observed_at="not-a-timestamp"),
            generated_at=GENERATED_AT,
        )
        self.assertIn("date unknown", html)
        self.assertNotIn("flights not observed", html)


class PricesCheckedFooterRenderTests(unittest.TestCase):
    def test_every_rendered_card_carries_the_footer(self):
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        html = render_holiday_report(
            config, generated_at=GENERATED_AT, deals=deals,
        )
        self.assertGreaterEqual(
            html.count("Prices last checked:"), len(deals))

    def test_the_footer_sits_under_each_card_at_the_end(self):
        # The footer is the card's last line: it follows the room-only
        # metasearch line, inside the card, so the age of the numbers above it
        # is the last thing a reader sees.
        config = dataclasses.replace(
            load_holiday_config(JULY.read_text(encoding="utf-8")),
            max_budget_gbp=60000.0,
        )
        deals = collect_holiday_deals(config)
        html = render_holiday_report(
            config, generated_at=GENERATED_AT, deals=deals,
        )
        marker = "Prices last checked:"
        first = html.index(marker)
        room_line = html.index("Room only, your dates:", 0, first)
        self.assertLess(room_line, first)


class _DatedRate:
    observed_at = "2026-10-01T09:00:00+00:00"
    vendor = "Example brand booking engine"


class _UndatedRate:
    observed_at = ""
    vendor = "Example brand booking engine"


class _Evidence:
    """The minimum shape prices_checked_footer reads off a rate."""

    def __init__(self, rate):
        self.cheapest = rate


class HotelAgeInTheFooterTests(unittest.TestCase):
    """F2b: with a read rate the footer states its age, like the flight leg.

    The hotel half used to have no observed-at field at all, so it could only
    state a basis. Now the rate carries the instant it was read, and the same
    words the flight leg uses are available for it.
    """

    def test_a_read_rate_shows_its_age(self):
        html = prices_checked_footer(
            _base_deal(hotel_evidence=_Evidence(_DatedRate()),
                       hotel_rate_basis="exact-date-rate"),
            generated_at="2026-10-03T00:00:00+00:00",
        )
        self.assertIn("hotel rate read 1 day ago", html)
        self.assertIn("Example brand booking engine", html)

    def test_an_unknown_observation_date_is_not_invented(self):
        html = prices_checked_footer(
            _base_deal(hotel_evidence=_Evidence(_UndatedRate()),
                       hotel_rate_basis="exact-date-rate"),
            generated_at="2026-10-03T00:00:00+00:00",
        )
        self.assertIn("hotel rate date unknown", html)

    def test_a_catalogue_rate_still_states_its_basis_not_an_age(self):
        html = prices_checked_footer(
            _base_deal(hotel_rate_basis="estimate"),
            generated_at="2026-10-03T00:00:00+00:00",
        )
        self.assertIn("hotel rate from nearest dates, not your exact dates", html)
        self.assertNotIn("hotel rate read", html)


if __name__ == "__main__":
    unittest.main()
