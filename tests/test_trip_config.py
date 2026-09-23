"""Trip windows must be derived from the clock, never hardcoded literals.

2026-09-22: the digest's September window was hardcoded in
``trip_config``, those dates had passed, every Google Flights search
returned zero cards, and the job burned nine minutes to report a generic
``collection_failed``. The same code was green on 2026-09-03 with thirteen
paired itineraries; the dates were the only thing that changed.
"""

import unittest
from datetime import date, timedelta

from public_flight_search.trip_config import (
    DEFAULT_HOLIDAY_TRIP_DEFINITION,
    DEFAULT_TRIP_DEFINITIONS,
    december_holiday_dates,
    default_holiday_trip_definition,
    default_trip_definitions,
    rolling_trip_dates,
)


class RollingTripWindowTests(unittest.TestCase):
    def test_reproduces_the_original_handwritten_window(self):
        # The shape is unchanged — only its expiry is. A 2026-08-25 run
        # reproduces the literals this replaced exactly.
        outbound, returning = rolling_trip_dates(date(2026, 8, 25))

        self.assertEqual(outbound, ("2026-09-15", "2026-09-16"))
        self.assertEqual(returning, ("2026-09-26", "2026-09-27", "2026-09-28"))

    def test_nights_between_the_windows_are_preserved(self):
        outbound, returning = rolling_trip_dates(date(2026, 9, 23))

        self.assertEqual(
            date.fromisoformat(returning[0]) - date.fromisoformat(outbound[0]),
            timedelta(days=11),
        )

    def test_no_run_date_produces_a_past_date(self):
        # The regression itself: literals are correct on the day they are
        # written and expired a fortnight later.
        for today in (
            date(2026, 9, 23),
            date(2026, 9, 24),
            date(2027, 1, 1),
            date(2030, 6, 30),
        ):
            outbound, returning = rolling_trip_dates(today)
            for day in outbound + returning:
                self.assertGreater(
                    date.fromisoformat(day),
                    today,
                    f"{day} is not in the future for a {today} run",
                )

    def test_default_definitions_are_dated_from_the_reference(self):
        reference = date(2026, 9, 23)
        trips = default_trip_definitions(reference)

        self.assertEqual(len(trips), 2)
        for trip in trips:
            self.assertEqual(len(trip.outbound_dates), 2)
            self.assertEqual(len(trip.return_dates), 3)
            for day in trip.outbound_dates + trip.return_dates:
                self.assertGreater(date.fromisoformat(day), reference)

    def test_module_level_alias_is_not_already_expired(self):
        # Guards the convenience constant too: importing it must not hand a
        # caller a search plan whose dates are in the past.
        today = date.today()

        for trip in DEFAULT_TRIP_DEFINITIONS:
            for day in trip.outbound_dates + trip.return_dates:
                self.assertGreater(
                    date.fromisoformat(day),
                    today,
                    f"{trip.key} would search the past date {day}",
                )


class DecemberHolidayWindowTests(unittest.TestCase):
    """The December definition carried the digest's expiry bug as literals.

    It was hardcoded to 2026-12-20/22/24 — correct when written, dead after
    that Christmas. The shape is fixed; the year now rolls.
    """

    def test_reproduces_the_original_hardcoded_christmas_window(self):
        outbound, returning = december_holiday_dates(2026)

        self.assertEqual(outbound, ("2026-12-20", "2026-12-22", "2026-12-24"))
        self.assertEqual(returning, ("2026-12-28", "2026-12-30", "2026-12-31"))

    def test_current_year_is_used_before_that_christmas(self):
        trip = default_holiday_trip_definition(date(2026, 9, 23))

        self.assertEqual(trip.outbound_dates[0], "2026-12-20")

    def test_last_day_before_the_window_still_uses_this_year(self):
        trip = default_holiday_trip_definition(date(2026, 12, 19))

        self.assertEqual(trip.outbound_dates[0], "2026-12-20")

    def test_year_rolls_once_the_window_has_begun(self):
        # On 2026-12-20 this year's outbound is no longer ahead of the run, so
        # the plan must describe the next Christmas rather than a past one.
        trip = default_holiday_trip_definition(date(2026, 12, 20))

        self.assertEqual(trip.outbound_dates[0], "2027-12-20")

    def test_year_rolls_once_the_window_is_past(self):
        trip = default_holiday_trip_definition(date(2027, 1, 5))

        self.assertEqual(trip.outbound_dates[0], "2027-12-20")
        self.assertEqual(trip.return_dates[-1], "2027-12-31")

    def test_the_definition_is_never_expired(self):
        for today in (
            date(2026, 9, 23),
            date(2026, 12, 24),
            date(2026, 12, 25),
            date(2027, 6, 1),
            date(2030, 12, 30),
        ):
            with self.subTest(today=today):
                trip = default_holiday_trip_definition(today)
                for day in trip.outbound_dates + trip.return_dates:
                    self.assertGreater(
                        date.fromisoformat(day),
                        today,
                        f"{day} is not in the future for a {today} run",
                    )

    def test_module_level_alias_is_not_already_expired(self):
        today = date.today()

        for day in (
            DEFAULT_HOLIDAY_TRIP_DEFINITION.outbound_dates
            + DEFAULT_HOLIDAY_TRIP_DEFINITION.return_dates
        ):
            self.assertGreater(date.fromisoformat(day), today)


if __name__ == "__main__":
    unittest.main()
