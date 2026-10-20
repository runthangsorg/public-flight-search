"""Africa multi-stop trips: operator shapes and self-builds, side by side.

Owner direction 2026-10-15 / 2026-10-17: Tanzania safari + Zanzibar, Kenya Mara +
Diani, Kruger + Cape Town or Mauritius; copy what the top agencies sell and show
the self-build of the same shape beside it. The previous attempt put two invented
rows in the e-mail's data; these tests pin that a trip says WHERE its figures
came from, and that Cape Town's wet winter is flagged rather than hidden.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from public_flight_search import climate
from public_flight_search.multi_centre import (
    DEFAULT_MULTI_CENTRE_PATH,
    consume_multi_centre_skip_log,
    load_multi_centre,
)

DATA = Path(DEFAULT_MULTI_CENTRE_PATH)


def _item(**over):
    base = {
        "id": "MC-X1",
        "title": "Serengeti 4 nights + Zanzibar 7 nights",
        "season": "summer",
        "stops": [
            {"place": "Serengeti", "nights": 4, "airport": "JRO",
             "hotel": "A named lodge", "basis": "rate card"},
            {"place": "Zanzibar (Nungwi)", "nights": 7, "airport": "ZNZ",
             "hotel": "A named resort", "basis": "rate card"},
        ],
        "legs": [["LHR", "JRO"], ["JRO", "ZNZ"], ["ZNZ", "LHR"]],
        "flight_shape": "open-jaw",
        "cost_low_gbp": 14000, "cost_high_gbp": 19000,
        "cost_basis": "built line by line",
        "why": "w", "catch": "c", "confidence": "estimate",
        "kind": "self-build",
        "operator_ref": "Shape copied from an operator's 11-night Serengeti and Zanzibar tour",
        "source_urls": ["https://example.org/x"],
    }
    base.update(over)
    return base


def _load(items):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mc.json"
        path.write_text(json.dumps({"schema": "multi_centre/1", "itineraries": items}))
        return load_multi_centre(path=str(path), season="summer")


class KindTests(unittest.TestCase):
    def test_a_trip_carries_its_kind_and_the_operator_it_copies(self):
        trip = _load([_item()])[0]
        self.assertEqual(trip.kind, "self-build")
        self.assertIn("operator's", trip.operator_ref)

    def test_a_trip_without_a_kind_is_a_self_build(self):
        item = _item()
        del item["kind"], item["operator_ref"]
        trip = _load([item])[0]
        self.assertEqual(trip.kind, "self-build")
        self.assertEqual(trip.operator_ref, "")

    def test_an_unknown_kind_is_dropped_with_a_reason(self):
        self.assertEqual(_load([_item(kind="invented")]), [])
        self.assertTrue(any("kind" in line for line in consume_multi_centre_skip_log()))

    def test_an_operator_trip_must_name_its_operator(self):
        self.assertEqual(_load([_item(kind="operator", operator_ref="")]), [])
        self.assertTrue(any("operator" in line for line in consume_multi_centre_skip_log()))


class CapeTownWinterTests(unittest.TestCase):
    def test_cape_town_in_june_or_july_is_warned_never_removed(self):
        for months in ({6}, {7}):
            warnings = climate.warnings_for(
                text="Cape Town CPT", airports=["CPT"], stay_months=months)
            self.assertTrue(any("wet" in w.text for w in warnings), warnings)
            self.assertIsNone(climate.exclusion_for(
                text="Cape Town CPT", airports=["CPT"], stay_months=months))

    def test_kruger_in_july_carries_no_wet_warning(self):
        self.assertEqual(climate.warnings_for(
            text="Kruger MQP", airports=["MQP"], stay_months={7}), [])


class ShippedAfricaTests(unittest.TestCase):
    """Whatever Africa rows ship, each one is sourced and named."""

    def _africa(self):
        payload = json.loads(DATA.read_text(encoding="utf-8"))
        return [i for i in payload["itineraries"] if i.get("region") == "africa"]

    def test_every_africa_trip_has_named_lodges_and_a_source(self):
        for item in self._africa():
            with self.subTest(itinerary=item["id"]):
                self.assertTrue(item["source_urls"], "no source")
                for url in item["source_urls"]:
                    self.assertNotIn("example.invalid", url)
                for stop in item["stops"]:
                    self.assertTrue(stop["hotel"].strip(), stop)
                    self.assertNotIn("(4-star eq.)", stop["hotel"])
                self.assertIn(item.get("kind"), ("self-build", "operator"))
                self.assertIn(item["season"], ("summer",))


class RenderTests(unittest.TestCase):
    """The row says whose shape it is, in both the HTML and the text part."""

    def _config(self):
        from public_flight_search.holidays import load_holiday_config
        root = Path(__file__).parents[1]
        return load_holiday_config(
            (root / "examples" / "july_holiday_config.json").read_text(encoding="utf-8"))

    def _render(self, items):
        from unittest import mock
        from public_flight_search import holiday_email as he

        trips = _load(items)
        with mock.patch.object(he, "load_multi_centre", return_value=trips):
            return (he._multi_centre_html(self._config()),
                    "\n".join(he._multi_centre_lines(self._config())))

    def test_the_row_names_its_kind_and_the_operator_shape_it_copies(self):
        html, text = self._render([_item()])
        for part in (html, text):
            self.assertIn("self-build", part)
            self.assertIn("Shape copied from an operator", part)

    def test_an_operator_package_is_labelled_as_one(self):
        html, text = self._render([_item(
            kind="operator", operator_ref="Tropical Sky: 11-night Safari & Zanzibar")])
        for part in (html, text):
            self.assertIn("operator package", part)
            self.assertIn("Tropical Sky", part)
