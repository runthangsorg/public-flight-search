"""July multi-centre: Kenya (Masai Mara + Diani) and Hokkaido + Okinawa.

These two trips were missing from ``data/multi_centre.json``, so the July
planner's multi-centre section and the private fan-out never priced them.
They now enter through ``multi_centre.py``'s own loader, like every other
itinerary in that file.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import unittest

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import multi_centre_wanted
from public_flight_search.multi_centre import (
    DEFAULT_MULTI_CENTRE_PATH,
    load_multi_centre,
)


ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"

WINDOW_START = date(2027, 6, 25)
WINDOW_END = date(2027, 7, 21)


def _config():
    return hol.load_holiday_config(JULY.read_text(encoding="utf-8"))


class MultiCentreJsonLoadsTests(unittest.TestCase):
    def test_the_json_loads_through_multi_centre_own_loader(self):
        trips = load_multi_centre(path=DEFAULT_MULTI_CENTRE_PATH, season="summer")
        ids = {trip.id for trip in trips}
        self.assertIn("KE-01", ids)
        self.assertIn("JP-02", ids)


class KenyaAndHokkaidoShapeTests(unittest.TestCase):
    def _trip(self, trip_id):
        trips = {t.id: t for t in load_multi_centre(
            path=DEFAULT_MULTI_CENTRE_PATH, season="summer")}
        return trips[trip_id]

    def test_ke01_is_a_summer_trip_with_the_right_airports(self):
        trip = self._trip("KE-01")
        self.assertEqual(trip.season, "summer")
        self.assertEqual(trip.title, "Masai Mara 4 nights + Diani 9 nights")
        self.assertEqual([s.airport for s in trip.stops], ["NBO", "MBA"])
        self.assertEqual([s.nights for s in trip.stops], [4, 9])
        for stop in trip.stops:
            self.assertEqual(stop.basis, "estimate")
        for leg in trip.legs:
            self.assertEqual(len(leg), 2)
            for airport in leg:
                self.assertRegex(airport, r"^[A-Z]{3}$")

    def test_jp02_is_a_summer_trip_with_the_right_airports(self):
        trip = self._trip("JP-02")
        self.assertEqual(trip.season, "summer")
        self.assertEqual(trip.title, "Hokkaido 5 nights + Okinawa 7 nights")
        self.assertEqual([s.airport for s in trip.stops], ["CTS", "OKA"])
        self.assertEqual([s.nights for s in trip.stops], [5, 7])
        for stop in trip.stops:
            self.assertEqual(stop.basis, "estimate")
        for leg in trip.legs:
            self.assertEqual(len(leg), 2)
            for airport in leg:
                self.assertRegex(airport, r"^[A-Z]{3}$")

    def test_lodges_reuse_catalogue_property_names(self):
        trips = {t.id: t for t in load_multi_centre(
            path=DEFAULT_MULTI_CENTRE_PATH, season="summer")}
        ke_lodges = {lodge.name for stop in trips["KE-01"].stops for lodge in stop.lodges}
        jp_lodges = {lodge.name for stop in trips["JP-02"].stops for lodge in stop.lodges}
        self.assertTrue(ke_lodges & {"Angama Mara", "Mara Serena Safari Lodge"})
        self.assertTrue(ke_lodges & {"The Sands at Nomad", "Almanara Luxury Villas"})
        self.assertTrue(jp_lodges & {"Park Hyatt Niseko Hanazono", "Hoshino Resorts Tomamu"})
        self.assertIn("Halekulani Okinawa", jp_lodges)


class WantedRowsTests(unittest.TestCase):
    def test_multi_centre_wanted_includes_ke01_and_jp02(self):
        config = _config()
        wanted = multi_centre_wanted(config)
        by_trip = {row["trip"]: row for row in wanted}
        self.assertIn("KE-01", by_trip)
        self.assertIn("JP-02", by_trip)
        for trip_id in ("KE-01", "JP-02"):
            row = by_trip[trip_id]
            self.assertEqual(row["season"], "summer")
            for leg in row["legs"]:
                self.assertEqual(len(leg), 3)
                for airport in leg[:2]:
                    self.assertRegex(airport, r"^[A-Z]{3}$")
                day = _parse_date(leg[2])
                self.assertIsNotNone(day)
                self.assertGreaterEqual(day, WINDOW_START)
                self.assertLessEqual(day, WINDOW_END)


def _parse_date(value):
    try:
        y, m, d = (int(part) for part in str(value).split("-"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    unittest.main()