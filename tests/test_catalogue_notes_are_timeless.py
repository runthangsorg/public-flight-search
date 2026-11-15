"""Brief Q (15 Nov 2026): a catalogue note is timeless, and a run claim is not.

Each itinerary's ``why`` and ``catch`` are printed on the e-mail's card, above whatever this week's
run read. So they may describe the place, the journey, the season and a standing drawback, and they
may not say what was priced, what was cheapest, what a hotel's rate includes or what is or is not
available: those are facts of one run, and the run's own lines carry them.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "public_flight_search" / "data"
FILES = ("multi_centre.json", "trip_leads.json")

#: Phrases that only a run can know. Case-insensitive, matched as written (so "priced" also catches
#: "unpriced", and "£" or "$" catch any figure in a currency).
RUN_CLAIMS = (
    "priced",
    "cheapest",
    "lowest-cost",
    "lowest cost",
    "we found",
    "'from'",
    "from price",
    "budget",
    "unbudgeted",
    "room only",
    "states breakfast",
    "states no board",
    "no dated rate",
    "£",
    "$",
    "per person",
)


def _itineraries():
    for name in FILES:
        payload = json.loads((DATA / name).read_text(encoding="utf-8"))
        for trip in payload.get("itineraries", ()):
            yield name, trip


class TimelessNoteTests(unittest.TestCase):
    def test_no_why_or_catch_makes_a_run_claim(self):
        offenders = []
        for name, trip in _itineraries():
            for key in ("why", "catch"):
                text = str(trip.get(key, ""))
                lowered = text.lower()
                for phrase in RUN_CLAIMS:
                    if phrase in lowered:
                        offenders.append(f"{name} {trip.get('id')} {key}: {phrase!r} in {text!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_every_note_is_still_text_on_its_itinerary(self):
        for name, trip in _itineraries():
            with self.subTest(f"{name} {trip.get('id')}"):
                for key in ("why", "catch"):
                    text = trip.get(key)
                    self.assertIsInstance(text, str, f"{trip.get('id')}: {key} is text")
                    self.assertNotIn("\n", text)
                    self.assertEqual(text, text.strip(), f"{trip.get('id')}: {key} has no stray space")

    def test_the_priced_catalogue_still_carries_its_figures(self):
        # The notes stopped making run claims. Nothing else changed: the figures live on the trip.
        priced = [trip for name, trip in _itineraries() if name == "multi_centre.json" and "cost_low_gbp" in trip]
        self.assertTrue(priced, "the catalogue's own ranges are still in the file")
        for trip in priced:
            self.assertIsInstance(trip["cost_low_gbp"], (int, float))


if __name__ == "__main__":
    unittest.main()
