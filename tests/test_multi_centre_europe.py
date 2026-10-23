"""The Switzerland / Italy trips (EU-xx) in multi_centre.json are internally consistent."""
import json
import re
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "public_flight_search" / "data" / "multi_centre.json"


class EuropeTripsTest(unittest.TestCase):
    def setUp(self):
        self.trips = [t for t in json.loads(DATA.read_text(encoding="utf-8"))["itineraries"] if t["id"].startswith("EU-")]

    def test_there_are_europe_trips(self):
        self.assertGreaterEqual(len(self.trips), 2)

    def test_every_trip_is_17_nights_and_starts_and_ends_in_london(self):
        for t in self.trips:
            with self.subTest(t["id"]):
                self.assertEqual(sum(s["nights"] for s in t["stops"]), 17)
                self.assertEqual(t["legs"][0][0], "LHR")
                self.assertEqual(t["legs"][-1][1], "LHR")

    def test_one_figure_and_cost_lines_add_up_with_a_flights_line(self):
        # multi_centre only keeps cost lines for a trip with ONE figure (low == high) that they sum to.
        for t in self.trips:
            with self.subTest(t["id"]):
                self.assertEqual(t["cost_low_gbp"], t["cost_high_gbp"])
                self.assertLessEqual(abs(sum(l["gbp"] for l in t["cost_lines"]) - t["cost_low_gbp"]), 1)
                self.assertTrue(any("flight" in l["label"].lower() for l in t["cost_lines"]))

    def test_every_url_is_https_and_each_lodge_has_one(self):
        for t in self.trips:
            with self.subTest(t["id"]):
                urls = list(t["source_urls"]) + [lg.get("url", "") for s in t["stops"] for lg in s["lodges"]]
                self.assertTrue(urls)
                for u in urls:
                    self.assertTrue(u.startswith("https://"), u)
                for s in t["stops"]:
                    for lg in s["lodges"]:
                        self.assertTrue(lg.get("url"), lg["name"])

    def test_estimates_are_labelled_and_nothing_claims_a_dated_rate(self):
        for t in self.trips:
            with self.subTest(t["id"]):
                self.assertEqual(t["confidence"], "estimate")
                for l in t["cost_lines"]:
                    if re.search(r"rail|train|ferry|transfer|pass|express", l["label"], re.I) and l["gbp"]:
                        self.assertIn("estimate", l["label"])

    def test_no_budget_or_personal_data_in_the_europe_trips(self):
        text = json.dumps(self.trips).lower()
        for word in ("budget", "chowdhree", "kashif", "password"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
