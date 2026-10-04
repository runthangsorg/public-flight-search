"""Integrity tests for the package-evidence loader.

The private engine writes ``data/holiday_package_evidence.json``; this loader is
the only way a package price in that file may reach a card. Every test below
exists so that a price which fails one of the brief's conditions cannot be
priced, even by accident:

* the season is the one this run prices;
* ``exact_date_match`` is true and the dates are a pair this run prices;
* the party is the report's party and the booking is one or two rooms;
* the board is breakfast or better (``RO`` is never a deal);
* the confidence is ``verified-exact-date``;
* the observation is fresh.

The price is only ever a GBP figure: a whole-party total the operator
displayed, or a per-person figure with the engine's own ``derived_total_gbp``.
Everything the loader returns carries its own source URL and observation time.

All data here is synthetic: made-up operators, resorts and figures.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from public_flight_search.holidays import load_holiday_config
from public_flight_search.package_evidence import (
    DEFAULT_PACKAGE_EVIDENCE_PATH,
    PACKAGE_EVIDENCE_MAX_AGE_HOURS,
    SCHEMA,
    consume_package_skip_log,
    load_package_evidence,
    package_evidence_max_age_hours,
    package_price_for,
    package_provenance,
)

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/package_evidence_sample.json"

#: The synthetic fixture was observed around this instant; every test measures
#: age against it, so nothing in this file is a time bomb.
NOW = "2026-10-04T12:00:00+00:00"

SUMMER_CONFIG = """
{
  "report_title": "Package evidence loader test",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "khao_lak", "label": "Khao Lak", "airports": ["HKT"], "flight_hours": 11.5},
    {"key": "koh_samui", "label": "Koh Samui", "airports": ["USM"], "flight_hours": 13.0}
  ]
}
"""

OUTBOUND = "2027-07-20"
RETURNING = "2027-07-27"
PROPERTY = "Example Resort Khao Lak"
PROPERTY_WITH_COMMA = "Example Resort, Khao Lak"

#: Every record the fixture uses to break one rule, and the keyword its skip
#: reason must contain.
BAD_RECORDS = {
    "Room Only Resort": "breakfast",
    "Winter Dates Resort": "season",
    "Stale Package Resort": "stale",
    "Party Four Resort": "party",
    "Euro Price Resort": "GBP",
    "Approx Dates Resort": "exact_date_match",
    "Market Confidence Resort": "confidence",
    "Unpriced Pair Resort": "pair",
    "Three Rooms Resort": "rooms",
    "No Derived Resort": "derived_total_gbp",
}


def _load(config_json: str = SUMMER_CONFIG, *, path: str = str(FIXTURE), **kwargs):
    return load_package_evidence(
        load_holiday_config(config_json), path=path, now=NOW, **kwargs
    )


def _by_operator(loaded) -> dict[tuple[str, str], object]:
    return {(entry.property_name, entry.operator_key): entry for entry in loaded.values()}


def _skips() -> dict[str, str]:
    reasons: dict[str, str] = {}
    for entry in consume_package_skip_log():
        name, _, reason = entry.partition(": ")
        reasons[name] = reason
    return reasons


class TestLoaderPath(unittest.TestCase):
    def test_default_path_is_the_evidence_the_workflow_seeds(self):
        self.assertEqual(DEFAULT_PACKAGE_EVIDENCE_PATH, "data/holiday_package_evidence.json")

    def test_schema_is_the_producers_schema(self):
        self.assertEqual(SCHEMA, "holiday_package_evidence/1")

    def test_default_max_age_is_one_week(self):
        self.assertEqual(PACKAGE_EVIDENCE_MAX_AGE_HOURS, 168)
        self.assertEqual(package_evidence_max_age_hours(), 168)

    def test_max_age_is_configurable_from_the_environment(self):
        previous = os.environ.get("PACKAGE_EVIDENCE_MAX_AGE_HOURS")
        os.environ["PACKAGE_EVIDENCE_MAX_AGE_HOURS"] = "72"
        try:
            self.assertEqual(package_evidence_max_age_hours(), 72)
        finally:
            if previous is None:
                os.environ.pop("PACKAGE_EVIDENCE_MAX_AGE_HOURS", None)
            else:
                os.environ["PACKAGE_EVIDENCE_MAX_AGE_HOURS"] = previous

    def test_unreadable_max_age_falls_back_to_the_default(self):
        previous = os.environ.get("PACKAGE_EVIDENCE_MAX_AGE_HOURS")
        os.environ["PACKAGE_EVIDENCE_MAX_AGE_HOURS"] = "not-a-number"
        try:
            self.assertEqual(package_evidence_max_age_hours(), 168)
        finally:
            if previous is None:
                os.environ.pop("PACKAGE_EVIDENCE_MAX_AGE_HOURS", None)
            else:
                os.environ["PACKAGE_EVIDENCE_MAX_AGE_HOURS"] = previous


class TestQualifyingPrices(unittest.TestCase):
    def setUp(self):
        self.loaded = _load()
        self.entries = _by_operator(self.loaded)
        consume_package_skip_log()

    def test_the_two_good_records_load(self):
        self.assertIn((PROPERTY, "loveholidays"), self.entries)
        self.assertIn((PROPERTY, "jet2holidays"), self.entries)

    def test_a_per_person_record_carries_the_derived_total_and_its_how(self):
        entry = self.entries[(PROPERTY, "jet2holidays")]
        self.assertAlmostEqual(entry.total_gbp, 5900.0)
        self.assertEqual(entry.price_basis, "per_person")
        self.assertEqual(
            entry.price_how,
            "1180 per person x 5 travellers as shown on the results card",
        )

    def test_a_whole_party_record_has_no_derived_how(self):
        entry = self.entries[(PROPERTY, "loveholidays")]
        self.assertEqual(entry.price_basis, "whole_party_total")
        self.assertEqual(entry.price_how, "")

    def test_the_cheaper_duplicate_of_a_key_wins(self):
        entry = self.entries[(PROPERTY, "loveholidays")]
        self.assertAlmostEqual(entry.total_gbp, 6100.0)

    def test_every_qualifying_price_carries_its_source_and_observation_time(self):
        for entry in self.loaded.values():
            with self.subTest(property=entry.property_name, operator=entry.operator_key):
                self.assertTrue(entry.source_url.startswith(("http://", "https://")))
                self.assertTrue(entry.observed_at)

    def test_a_punctuated_property_name_still_loads(self):
        self.assertIn((PROPERTY_WITH_COMMA, "tui"), self.entries)


class TestDisqualifyingConditions(unittest.TestCase):
    def setUp(self):
        self.loaded = _load()
        self.names = {entry.property_name for entry in self.loaded.values()}
        self.skips = _skips()

    def test_every_bad_record_is_absent_and_explained(self):
        for name, keyword in BAD_RECORDS.items():
            with self.subTest(property=name):
                self.assertNotIn(name, self.names, f"{name} was priced despite {keyword}")
                self.assertIn(name, self.skips)
                self.assertIn(keyword, self.skips[name])

    def test_room_only_board_is_explained_as_no_breakfast(self):
        self.assertIn("no breakfast (room only)", self.skips["Room Only Resort"])

    def test_stale_reason_states_the_age(self):
        self.assertIn("stale: observed", self.skips["Stale Package Resort"])


class TestMissingOrUnreadable(unittest.TestCase):
    def test_missing_file_is_a_no_op_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = _load(path=os.path.join(tmp, "absent.json"))
        self.assertEqual(loaded, {})
        self.assertEqual(consume_package_skip_log(), [])

    def test_unreadable_file_is_a_no_op_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "broken.json")
            with open(broken, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            capture = io.StringIO()
            with contextlib.redirect_stderr(capture):
                loaded = _load(path=broken)
        self.assertEqual(loaded, {})
        self.assertIn("unreadable", capture.getvalue())

    def test_a_wrong_schema_is_refused_and_named(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["schema"] = "holiday_hotel_evidence/1"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "packages.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            capture = io.StringIO()
            with contextlib.redirect_stderr(capture):
                loaded = _load(path=path)
        self.assertEqual(loaded, {})
        self.assertIn("holiday_hotel_evidence/1", capture.getvalue())


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.loaded = _load()
        consume_package_skip_log()

    def test_finds_the_property_through_a_punctuation_variant(self):
        found = package_price_for(self.loaded, PROPERTY_WITH_COMMA, OUTBOUND, RETURNING)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found.total_gbp, 5900.0)

    def test_returns_the_cheapest_across_operators(self):
        found = package_price_for(self.loaded, PROPERTY, OUTBOUND, RETURNING)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found.total_gbp, 5900.0)
        self.assertEqual(found.operator_key, "jet2holidays")

    def test_operator_key_restricts_to_that_operator(self):
        found = package_price_for(
            self.loaded, PROPERTY, OUTBOUND, RETURNING, operator_key="jet2holidays"
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.operator_key, "jet2holidays")
        self.assertAlmostEqual(found.total_gbp, 5900.0)

    def test_unknown_dates_return_none(self):
        self.assertIsNone(package_price_for(self.loaded, PROPERTY, "2027-08-01", "2027-08-08"))
        self.assertIsNone(package_price_for({}, PROPERTY, OUTBOUND, RETURNING))


class TestProvenance(unittest.TestCase):
    def setUp(self):
        self.loaded = _load()
        consume_package_skip_log()

    def test_provenance_names_operator_board_and_year(self):
        price = package_price_for(self.loaded, PROPERTY, OUTBOUND, RETURNING)
        sentence = package_provenance(price)
        self.assertIn("Jet2holidays", sentence)
        self.assertIn("HB", sentence)
        self.assertIn("2026", sentence)
        self.assertIn("per-person price x 5 as shown", sentence)

    def test_whole_party_provenance_says_as_shown(self):
        price = package_price_for(
            self.loaded, PROPERTY, OUTBOUND, RETURNING, operator_key="loveholidays"
        )
        sentence = package_provenance(price)
        self.assertIn("whole-party total as shown", sentence)
        self.assertIn("2 rooms", sentence)


class TestGitignore(unittest.TestCase):
    def test_the_runtime_file_is_ignored(self):
        lines = [
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("data/holiday_package_evidence.json", lines)


if __name__ == "__main__":
    unittest.main()
