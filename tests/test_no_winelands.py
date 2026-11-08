"""No Winelands itinerary (owner, 8 Nov 2026): "drop winelands because we don't drink alcohol, and prefer halal
restaurants and hotels."

Nothing the planner can offer, in any file it ships, names the Winelands as a destination or a leg.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from public_flight_search.multi_centre import load_multi_centre

DATA = Path(__file__).parents[1] / "src" / "public_flight_search" / "data"
WINE_WORDS = re.compile(r"wineland", re.I)


class NoWinelandsTests(unittest.TestCase):
    def test_no_shipped_data_file_names_a_wine_region(self):
        for path in sorted(DATA.glob("*.json")):
            hits = WINE_WORDS.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(hits, [], f"{path.name} names the Winelands")

    def test_no_loaded_trip_has_a_winelands_title_stop_or_basis(self):
        from test_holiday_email_compact import _config

        for trip in load_multi_centre(_config()):
            text = " ".join([trip.title, trip.operator_ref, trip.why, trip.catch, trip.cost_basis]
                            + [f"{s.place} {s.hotel} {s.basis}" for s in trip.stops])
            self.assertIsNone(WINE_WORDS.search(text), trip.id)

    def test_the_kruger_cape_town_self_build_stands_alone(self):
        from test_holiday_email_compact import _config

        trips = {t.id: t for t in load_multi_centre(_config())}
        self.assertNotIn("AF-07", trips)
        self.assertEqual(trips["AF-10"].compare_with, "")


if __name__ == "__main__":
    unittest.main()
