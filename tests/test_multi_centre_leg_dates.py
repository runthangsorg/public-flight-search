"""A plane change flies the same day; only leaving a stay moves the date on.

Live read 2026-10-15: MC-02 "Khao Lak 7 nights + Koh Phangan 7 nights" has the
legs LHR-HKT, HKT-BKK, BKK-USM, USM-LHR (a change of plane in Bangkok), and the
search it built flew BKK-USM a week after HKT-BKK: seven nights in Bangkok that
the trip never names. A leg advances the date only when it leaves the airport of
the stay it is ending.
"""

from __future__ import annotations

import unittest

from public_flight_search.multi_centre import _trip as parse_trip
from public_flight_search.multi_centre import trip_legs_for_dates


def _trip(stops, legs):
    trip = parse_trip({
        "id": "SYN-1", "title": "SYNTHETIC", "season": "summer",
        "stops": [{"place": place, "nights": nights, "airport": airport,
                   "hotel": "SYNTHETIC", "basis": "SYNTHETIC"}
                  for place, nights, airport in stops],
        "legs": [list(leg) for leg in legs],
        "cost_low_gbp": 1, "cost_high_gbp": 2, "cost_basis": "SYNTHETIC", "why": "x", "catch": "y",
    })
    assert trip is not None, "synthetic trip failed to parse"
    return trip


class LegDateTests(unittest.TestCase):
    def test_a_change_of_plane_flies_the_same_day(self):
        trip = _trip([("Khao Lak", 7, "HKT"), ("Koh Phangan", 7, "USM")],
                     [("LHR", "HKT"), ("HKT", "BKK"), ("BKK", "USM"), ("USM", "LHR")])
        self.assertEqual(
            [leg[2] for leg in trip_legs_for_dates(trip, "2027-06-27", "2027-07-14")],
            ["2027-06-27", "2027-07-04", "2027-07-04", "2027-07-14"],
        )

    def test_a_connection_before_the_first_stay_does_not_shift_the_rest(self):
        trip = _trip([("Bali", 7, "DPS"), ("Lombok", 7, "LOP")],
                     [("LHR", "DOH"), ("DOH", "DPS"), ("DPS", "LOP"), ("LOP", "LHR")])
        self.assertEqual(
            [leg[2] for leg in trip_legs_for_dates(trip, "2027-06-27", "2027-07-11")],
            ["2027-06-27", "2027-06-27", "2027-07-04", "2027-07-11"],
        )

    def test_three_stays_each_advance_by_their_own_nights(self):
        trip = _trip([("Bangkok", 3, "BKK"), ("Samui", 7, "USM"), ("Khao Lak", 7, "HKT")],
                     [("LHR", "BKK"), ("BKK", "USM"), ("USM", "HKT"), ("HKT", "LHR")])
        self.assertEqual(
            [leg[2] for leg in trip_legs_for_dates(trip, "2027-06-27", "2027-07-14")],
            ["2027-06-27", "2027-06-30", "2027-07-07", "2027-07-14"],
        )

    def test_an_open_jaw_and_a_round_trip_are_unchanged(self):
        open_jaw = _trip([("Bali", 7, "DPS"), ("Lombok", 7, "LOP")],
                         [("LHR", "DPS"), ("DPS", "LOP"), ("LOP", "LHR")])
        self.assertEqual(
            [leg[2] for leg in trip_legs_for_dates(open_jaw, "2027-06-27", "2027-07-14")],
            ["2027-06-27", "2027-07-04", "2027-07-14"],
        )
        round_trip = _trip([("Da Nang", 17, "DAD")], [("LHR", "DAD"), ("DAD", "LHR")])
        self.assertEqual(
            [leg[2] for leg in trip_legs_for_dates(round_trip, "2027-06-27", "2027-07-14")],
            ["2027-06-27", "2027-07-14"],
        )

    def test_the_return_leg_always_flies_on_the_return_date(self):
        trip = _trip([("Bali", 9, "DPS"), ("Lombok", 9, "LOP")],
                     [("LHR", "DPS"), ("DPS", "LOP"), ("LOP", "LHR")])
        legs = trip_legs_for_dates(trip, "2027-06-27", "2027-07-11")
        self.assertEqual(legs[-1][2], "2027-07-11")
        self.assertTrue(all(leg[2] <= "2027-07-11" for leg in legs))


if __name__ == "__main__":
    unittest.main()
