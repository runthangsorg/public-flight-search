"""Integrity tests for the hotel-evidence loader.

Owner brief 2026-10-03 (H2). The private engine writes
``data/holiday_hotel_evidence.json``; this loader is the only way a rate in
that file may reach a card. Every test below exists so that a rate which
fails one of the brief's conditions cannot be priced, even by accident:

* the season is the one this run prices;
* ``exact_date_match`` is true and the dates are a pair this run prices;
* the party is the report's party;
* the booking is one booking (``one_unit`` or two rooms in one booking);
* the board is breakfast or better (``RO`` is never a deal);
* the observation is fresh.

The price is only ever a GBP ``public`` figure, or a ``derived_gbp``
conversion that says so on its face. Everything the loader returns carries
its own source URL and observation time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from public_flight_search.holidays import load_holiday_config
from public_flight_search.hotel_evidence import (
    DEFAULT_HOTEL_EVIDENCE_PATH,
    HOTEL_EVIDENCE_MAX_AGE_HOURS,
    consume_hotel_skip_log,
    hotel_evidence_max_age_hours,
    load_hotel_evidence,
)

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/hotel_evidence_sample.json"

#: The synthetic fixture was observed on this instant; every test measures
#: age against it, so nothing in this file is a time bomb.
NOW = "2026-10-03T12:00:00+00:00"

SUMMER_CONFIG = """
{
  "report_title": "Hotel evidence loader test",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2027-07-20"],
  "return_dates": ["2027-07-27"],
  "destinations": [
    {"key": "khao_lak", "label": "Khao Lak", "airports": ["HKT"], "flight_hours": 11.5},
    {"key": "koh_samui", "label": "Koh Samui", "airports": ["USM"], "flight_hours": 13.0},
    {"key": "lombok", "label": "Lombok", "airports": ["LOP"], "flight_hours": 17.0}
  ]
}
"""

WINTER_CONFIG = """
{
  "report_title": "Hotel evidence loader winter test",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2026-12-22"],
  "return_dates": ["2026-12-30"],
  "destinations": [
    {"key": "sharm_el_sheikh", "label": "Sharm", "airports": ["SSH"], "flight_hours": 5.5}
  ]
}
"""


def _load(config_json: str = SUMMER_CONFIG, *, path: str = str(FIXTURE), **kwargs):
    return load_hotel_evidence(
        load_holiday_config(config_json), path=path, now=NOW, **kwargs
    )


def _properties(loaded) -> dict[str, object]:
    return {entry.property_name: entry for entry in loaded.values()}


class TestLoaderPath(unittest.TestCase):
    def test_default_path_is_the_evidence_the_workflow_seeds(self):
        self.assertEqual(DEFAULT_HOTEL_EVIDENCE_PATH, "data/holiday_hotel_evidence.json")

    def test_default_max_age_is_one_week(self):
        self.assertEqual(HOTEL_EVIDENCE_MAX_AGE_HOURS, 168)
        self.assertEqual(hotel_evidence_max_age_hours(), 168)

    def test_max_age_is_configurable_from_the_environment(self):
        previous = os.environ.get("HOTEL_EVIDENCE_MAX_AGE_HOURS")
        os.environ["HOTEL_EVIDENCE_MAX_AGE_HOURS"] = "72"
        try:
            self.assertEqual(hotel_evidence_max_age_hours(), 72)
        finally:
            if previous is None:
                os.environ.pop("HOTEL_EVIDENCE_MAX_AGE_HOURS", None)
            else:
                os.environ["HOTEL_EVIDENCE_MAX_AGE_HOURS"] = previous

    def test_unreadable_max_age_falls_back_to_the_default(self):
        previous = os.environ.get("HOTEL_EVIDENCE_MAX_AGE_HOURS")
        os.environ["HOTEL_EVIDENCE_MAX_AGE_HOURS"] = "not-a-number"
        try:
            self.assertEqual(hotel_evidence_max_age_hours(), 168)
        finally:
            if previous is None:
                os.environ.pop("HOTEL_EVIDENCE_MAX_AGE_HOURS", None)
            else:
                os.environ["HOTEL_EVIDENCE_MAX_AGE_HOURS"] = previous


class TestMissingFile(unittest.TestCase):
    def test_missing_file_is_a_no_op_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = _load(path=os.path.join(tmp, "absent.json"))
        self.assertEqual(loaded, {})

    def test_unreadable_file_is_a_no_op_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "broken.json")
            with open(broken, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            loaded = _load(path=broken)
        self.assertEqual(loaded, {})


class TestDisqualifyingConditions(unittest.TestCase):
    def setUp(self):
        self.properties = _properties(_load())
        consume_hotel_skip_log()

    def _assert_not_loaded(self, name: str, reason: str):
        self.assertNotIn(
            name, self.properties, f"{name} was priced despite {reason}"
        )

    def test_other_season_is_not_priced(self):
        self._assert_not_loaded("Winter Season Resort", "a winter rate in a July run")

    def test_party_of_four_is_not_priced(self):
        self._assert_not_loaded("Party Of Four Resort", "a different party size")

    def test_room_only_is_not_priced(self):
        self._assert_not_loaded("Room Only Resort", "board RO is never a deal")

    def test_three_rooms_is_not_priced(self):
        self._assert_not_loaded("Three Rooms Resort", "the booking is not one booking")

    def test_stale_observation_is_not_priced(self):
        self._assert_not_loaded("Stale Resort", "the observation is older than a week")

    def test_approximate_dates_are_not_priced(self):
        self._assert_not_loaded(
            "Approx Dates Resort", "exact_date_match is false"
        )

    def test_dates_this_run_does_not_price_are_not_priced(self):
        self._assert_not_loaded(
            "Unpriced Pair Resort", "those dates are not a priced pair"
        )

    def test_rate_without_any_price_is_not_priced(self):
        self._assert_not_loaded(
            "No Conversion Resort", "it carries neither a GBP public price nor a derived one"
        )

    def test_each_rejection_is_explained_rather_than_silently_dropped(self):
        _load()
        reasons = "\n".join(consume_hotel_skip_log())
        for needle in (
            "Winter Season Resort",
            "Party Of Four Resort",
            "Room Only Resort",
            "Three Rooms Resort",
            "Stale Resort",
            "Approx Dates Resort",
            "Unpriced Pair Resort",
            "No Conversion Resort",
        ):
            with self.subTest(property=needle):
                self.assertIn(needle, reasons)

    def test_stale_reason_states_the_age(self):
        _load()
        reasons = "\n".join(consume_hotel_skip_log())
        self.assertIn("stale", reasons.lower())

    def test_a_winter_run_prices_nothing_from_a_summer_file(self):
        loaded = _load(WINTER_CONFIG)
        self.assertEqual(loaded, {})
        consume_hotel_skip_log()


class TestQualifyingRates(unittest.TestCase):
    def setUp(self):
        self.properties = _properties(_load())
        consume_hotel_skip_log()

    def test_cheapest_qualifying_rate_is_returned(self):
        entry = self.properties["Example Beach Resort"]
        self.assertAlmostEqual(entry.cheapest.price_gbp, 1105.00)
        self.assertEqual(entry.cheapest.rate_name, "SAVER NON-REFUNDABLE")
        self.assertFalse(entry.cheapest.refundable)

    def test_flexible_rate_is_returned_separately_when_it_differs(self):
        entry = self.properties["Example Beach Resort"]
        self.assertIsNotNone(entry.flexible)
        self.assertAlmostEqual(entry.flexible.price_gbp, 1275.00)
        self.assertTrue(entry.flexible.refundable)
        self.assertNotEqual(
            entry.flexible.rate_name, entry.cheapest.rate_name
        )

    def test_when_the_cheapest_is_already_flexible_no_second_rate_is_invented(self):
        entry = self.properties["GBP Direct Resort"]
        self.assertAlmostEqual(entry.cheapest.price_gbp, 2100.00)
        self.assertTrue(entry.cheapest.refundable)
        self.assertIsNone(entry.flexible)

    def test_gbp_public_price_wins_over_a_derived_conversion(self):
        entry = self.properties["GBP Direct Resort"]
        self.assertEqual(entry.cheapest.price_basis, "public")
        self.assertEqual(entry.cheapest.currency, "GBP")
        self.assertNotIn("converted", entry.cheapest.price_label.lower())

    def test_derived_price_carries_its_own_label(self):
        entry = self.properties["Example Beach Resort"]
        label = entry.cheapest.price_label.lower()
        self.assertEqual(entry.cheapest.price_basis, "derived")
        self.assertIn("converted", label)
        self.assertIn("not a gbp price", label)

    def test_nightly_basis_is_labelled_and_priced_for_the_stay(self):
        entry = self.properties["Nightly Basis Resort"]
        self.assertAlmostEqual(entry.cheapest.price_gbp, 833.00)
        self.assertEqual(entry.cheapest.stay_basis, "nightly_x_nights")
        self.assertEqual(entry.cheapest.nights, 7)

    def test_every_rate_carries_its_source_and_observation_time(self):
        for entry in self.properties.values():
            for rate in (entry.cheapest, entry.flexible):
                if rate is None:
                    continue
                with self.subTest(property=entry.property_name, rate=rate.rate_name):
                    self.assertTrue(rate.source_url.startswith("https://"))
                    self.assertTrue(rate.observed_at)
                    self.assertTrue(rate.vendor)

    def test_terms_travel_with_the_rate(self):
        entry = self.properties["Example Beach Resort"]
        self.assertIn("Non-refundable", " ".join(entry.cheapest.terms))
        self.assertIn("Free cancellation", " ".join(entry.flexible.terms))

    def test_entry_states_the_dates_and_destination_it_prices(self):
        entry = self.properties["Example Beach Resort"]
        self.assertEqual(entry.check_in, "2027-07-20")
        self.assertEqual(entry.check_out, "2027-07-27")
        self.assertEqual(entry.destination_key, "khao_lak")

    def test_two_rooms_in_one_booking_are_labelled_as_one_booking(self):
        entry = self.properties["Example Beach Resort"]
        self.assertEqual(entry.booking_shape, "two_rooms_one_booking")

    def test_entries_are_keyed_by_property_and_date_pair(self):
        loaded = _load()
        self.assertIn(
            ("Example Beach Resort", "2027-07-20", "2027-07-27"), loaded
        )


class TestPassthrough(unittest.TestCase):
    def setUp(self):
        self.properties = _properties(_load())
        consume_hotel_skip_log()

    def test_unit_checks_are_returned(self):
        entry = self.properties["Example Beach Resort"]
        self.assertEqual(len(entry.unit_checks), 1)
        check = entry.unit_checks[0]
        self.assertIn("refused", check.finding)
        self.assertTrue(check.source_url.startswith("https://"))

    def test_rating_is_returned_with_its_source_and_count(self):
        entry = self.properties["Example Beach Resort"]
        self.assertEqual(len(entry.ratings), 1)
        rating = entry.ratings[0]
        self.assertEqual(rating.source, "Google")
        self.assertAlmostEqual(rating.score, 4.6)
        self.assertEqual(rating.review_count, "1.2k")
        self.assertTrue(rating.source_url.startswith("https://"))

    def test_facts_are_returned_each_with_their_own_source(self):
        entry = self.properties["Example Beach Resort"]
        fields = {fact.field: fact for fact in entry.facts}
        self.assertIn("beach", fields)
        self.assertIn("kids_club", fields)
        self.assertIn("nearest_mosque", fields)
        self.assertTrue(fields["beach"].source_url.startswith("https://"))

    def test_disagreeing_sources_are_both_kept(self):
        entry = self.properties["Example Beach Resort"]
        pools = [fact for fact in entry.facts if fact.field == "pools"]
        self.assertEqual(len(pools), 2)
        self.assertEqual({fact.stated for fact in pools}, {"four pools", "2 pools"})

    def test_blocked_source_is_returned_with_its_reason(self):
        entry = self.properties["Example Beach Resort"]
        self.assertEqual(len(entry.blocked), 1)
        self.assertEqual(entry.blocked[0].what, "TripAdvisor")
        self.assertIn("DataDome", entry.blocked[0].reason)

    def test_a_property_with_no_supplementary_records_returns_empty_lists(self):
        entry = self.properties["GBP Direct Resort"]
        self.assertEqual(entry.unit_checks, ())
        self.assertEqual(entry.ratings, ())
        self.assertEqual(entry.facts, ())
        self.assertEqual(entry.blocked, ())


class TestTolerance(unittest.TestCase):
    def test_unknown_fields_are_ignored(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["a_field_added_next_year"] = {"nested": [1, 2, 3]}
        payload["rates"][0]["some_new_vendor_field"] = "surprise"
        payload["rates"][0]["units"][0]["floor"] = 3
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hotel.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            loaded = _load(path=path)
        entry = _properties(loaded)["Example Beach Resort"]
        self.assertAlmostEqual(entry.cheapest.price_gbp, 1105.00)
        consume_hotel_skip_log()

    def test_junk_entries_are_skipped_without_raising(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["rates"] = payload["rates"] + ["not an object", None, 7, {}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hotel.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            loaded = _load(path=path)
        self.assertIn("Example Beach Resort", _properties(loaded))
        consume_hotel_skip_log()

    def test_a_rate_with_no_source_url_is_not_priced(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for rate in payload["rates"]:
            if rate["property_name"] == "GBP Direct Resort":
                rate["source_url"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hotel.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            loaded = _load(path=path)
        self.assertNotIn("GBP Direct Resort", _properties(loaded))
        consume_hotel_skip_log()

    def test_a_future_dated_observation_is_not_priced(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for rate in payload["rates"]:
            if rate["property_name"] == "GBP Direct Resort":
                rate["observed_at"] = "2026-10-04T15:02:10+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hotel.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            loaded = _load(path=path)
        self.assertNotIn("GBP Direct Resort", _properties(loaded))
        consume_hotel_skip_log()

    def test_max_age_override_widens_what_counts_as_fresh(self):
        # The fixture's stale record is ~1509h old, so the widened ceiling has
        # to clear that or the test would pass for the wrong reason.
        loaded = _load(max_age_hours=24 * 90)
        self.assertIn("Stale Resort", _properties(loaded))
        consume_hotel_skip_log()


if __name__ == "__main__":
    unittest.main()