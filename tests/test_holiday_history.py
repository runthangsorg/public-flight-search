"""Regression tests for holiday price history persistence and trend chips."""

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from public_flight_search.holiday_history import (
    append_history,
    read_history,
    render_history_html,
    summarize_trends,
)


@dataclass
class _Deal:
    resort_name: str
    destination_key: str
    destination_label: str
    outbound_date: str
    return_date: str
    nights: int
    total_package_price_gbp: float
    price_per_person_gbp: float
    flight_price_total_gbp: float
    hotel_price_total_gbp: float
    true_d2d_gbp: float
    confidence: str = "market-supported"
    unit_architecture: str = ""


def _deal(price: float = 3000.0) -> _Deal:
    return _Deal(
        resort_name="Test Resort",
        destination_key="dubai",
        destination_label="Dubai, UAE",
        outbound_date="2026-12-22",
        return_date="2026-12-30",
        nights=8,
        total_package_price_gbp=price,
        price_per_person_gbp=price / 5,
        flight_price_total_gbp=price / 2,
        hotel_price_total_gbp=price / 2,
        true_d2d_gbp=price + 66.5,
    )


def _backdate(path: Path, observed_at: str = "2026-09-10T08:00:00+00:00") -> None:
    """Rewrite all rows as prior-day observations (dedupe is per UTC day)."""
    rows = read_history(path=path)
    for r in rows:
        r["observed_at"] = observed_at
        r["run_id"] = "run-backdated"
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


class AppendHistoryTests(unittest.TestCase):
    def test_append_then_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            appended = append_history([_deal()], path=path)
            self.assertEqual(appended, 1)
            rows = read_history(path=path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["resort_name"], "Test Resort")
            self.assertEqual(rows[0]["outbound_date"], "2026-12-22")
            self.assertEqual(rows[0]["total_package_price_gbp"], 3000.0)
            self.assertIn("run_id", rows[0])
            self.assertIn("observed_at", rows[0])

    def test_fingerprint_stable_across_price_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            append_history([_deal(3000.0)], path=path)
            _backdate(path)
            append_history([_deal(2800.0)], path=path)
            rows = read_history(path=path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["fingerprint"], rows[1]["fingerprint"])

    def test_corrupt_lines_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            append_history([_deal()], path=path)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("{not valid json\n")
            _backdate(path)
            append_history([_deal(2999.0)], path=path)
            rows = read_history(path=path)
            self.assertEqual(len(rows), 2)

    def test_same_day_rerun_is_idempotent(self):
        """Job retries / manual re-runs must not duplicate observations."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            first = append_history([_deal(3000.0)], path=path)
            second = append_history([_deal(3100.0)], path=path)
            self.assertEqual(first, 1)
            self.assertEqual(second, 0)  # same UTC day -> deduped
            rows = read_history(path=path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["total_package_price_gbp"], 3000.0)

    def test_next_day_observation_is_kept(self):
        """A new day must produce a new observation for the same fingerprint."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            append_history([_deal(3000.0)], path=path)
            _backdate(path)
            appended = append_history([_deal(3050.0)], path=path)
            self.assertEqual(appended, 1)
            self.assertEqual(len(read_history(path=path)), 2)

    def test_non_finite_price_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            bad = _deal(float("nan"))
            good = _deal(3000.0)
            appended = append_history([bad, good], path=path)
            self.assertEqual(appended, 1)
            rows = read_history(path=path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["total_package_price_gbp"], 3000.0)


class SummarizeTrendsTests(unittest.TestCase):
    def test_first_observation_has_no_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            trends = summarize_trends([_deal()], path=path)
            self.assertEqual(trends[0]["prior_observations"], 0)
            self.assertIsNone(trends[0]["prior_min"])
            self.assertIsNone(trends[0]["delta_vs_min"])

    def test_delta_vs_prior_min_after_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            append_history([_deal(3000.0)], path=path)
            _backdate(path)
            append_history([_deal(2900.0)], path=path)
            # Current run is 2950: above the 2900 min.
            trends = summarize_trends([_deal(2950.0)], path=path)
            self.assertEqual(trends[0]["prior_observations"], 2)
            self.assertEqual(trends[0]["prior_min"], 2900.0)
            self.assertEqual(trends[0]["delta_vs_min"], 50.0)

    def test_trends_do_not_include_current_run(self):
        """summarize_trends must see only PRIOR history (called before append)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            trends = summarize_trends([_deal()], path=path)
            append_history([_deal()], path=path)
            self.assertEqual(trends[0]["prior_observations"], 0)


class RenderHistoryHtmlTests(unittest.TestCase):
    def test_first_run_chip_is_suppressed(self):
        # The digest's capped "new" pills already announce first sightings;
        # per-card "first time tracked" chips on every new resort card made
        # the first email a wall of the same sentence (2026-09-22 fix).
        trends = [{"prior_observations": 0}]
        snippets = render_history_html(trends)
        self.assertEqual(snippets, [""])

    def test_below_min_chip_is_positive(self):
        trends = [
            {
                "prior_observations": 3,
                "prior_min": 3000.0,
                "delta_vs_min": -40.0,
            }
        ]
        snippets = render_history_html(trends)
        self.assertIn("below tracked min", snippets[0])
        self.assertIn("40.00", snippets[0])

    def test_above_min_chip_is_negative(self):
        trends = [
            {
                "prior_observations": 3,
                "prior_min": 2900.0,
                "delta_vs_min": 50.0,
            }
        ]
        snippets = render_history_html(trends)
        self.assertIn("above tracked min", snippets[0])
    def test_unit_architecture_separates_price_series(self):
        """A 2-bed family suite and 3 separate rooms are different products:
        same resort + dates must yield DIFFERENT fingerprints and never
        collapse into one price series at the day-dedupe merge point."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            suite = _deal(price=2128.0)
            suite.unit_architecture = "2-Bedroom Family Suite (shared lounge)"
            three_rooms = _deal(price=4340.0)
            three_rooms.unit_architecture = ""
            append_history([suite], path=path)
            append_history([three_rooms], path=path)
            rows = read_history(path=path)
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0]["fingerprint"], rows[1]["fingerprint"])
            self.assertEqual(rows[0]["unit_architecture"], "2-Bedroom Family Suite (shared lounge)")


@dataclass
class _ScoredDeal(_Deal):
    value_score: float = 0.0
    rank_value: int = 0


def _scored_deal(price: float = 3000.0, *, value_score: float = 0.0,
                 rank_value: int = 0, resort_name: str = "Test Resort") -> _ScoredDeal:
    return _ScoredDeal(
        resort_name=resort_name,
        destination_key="dubai",
        destination_label="Dubai, UAE",
        outbound_date="2026-12-22",
        return_date="2026-12-30",
        nights=8,
        total_package_price_gbp=price,
        price_per_person_gbp=price / 5,
        flight_price_total_gbp=price / 2,
        hotel_price_total_gbp=price / 2,
        true_d2d_gbp=price + 66.5,
        value_score=value_score,
        rank_value=rank_value,
    )


class ValueRankTests(unittest.TestCase):
    """Value-score rank is persisted and surfaced as reader-worthy movement."""

    def test_append_persists_score_and_rank(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            deal = _scored_deal(resort_name="Scored Resort", value_score=78.4, rank_value=2)
            append_history([deal], path=path)
            rows = read_history(path=path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["value_score"], 78.4)
            self.assertEqual(rows[0]["rank_value"], 2)

    def test_rank_delta_positive_when_rank_improves(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            append_history([_scored_deal(value_score=70.0, rank_value=3)], path=path)
            _backdate(path)
            # Same price, better rank (3 -> 1): price-quiet, rank-moved.
            improved = _scored_deal(value_score=84.0, rank_value=1)
            trends = summarize_trends([improved], path=path)
            self.assertEqual(trends[0]["prior_rank"], 3)
            self.assertEqual(trends[0]["current_rank"], 1)
            self.assertEqual(trends[0]["rank_delta"], 2)  # +2 places
            self.assertEqual(trends[0]["score_delta"], 14.0)
            # Per-card rank chips were removed (2026-09-22): card-level rank
            # shuffle is noise; movement surfaces in the digest instead.
            snippets = render_history_html(trends)
            self.assertNotIn("rank", snippets[0])

    def test_rank_unchanged_produces_no_chip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            append_history([_scored_deal(value_score=70.0, rank_value=3)], path=path)
            _backdate(path)
            trends = summarize_trends([_scored_deal(value_score=70.0, rank_value=3)], path=path)
            # Same rank = zero movement (distinct from None = rank unknown).
            self.assertEqual(trends[0]["rank_delta"], 0)
            snippets = render_history_html(trends)
            self.assertNotIn("value rank", snippets[0])

    def test_legacy_rows_without_rank_yield_none(self):
        """Legacy history (pre-rank rows) must not fake a rank movement."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            append_history([_deal(price=3000.0)], path=path)  # no rank_value
            _backdate(path)
            trends = summarize_trends([_scored_deal(value_score=80.0, rank_value=1)], path=path)
            self.assertIsNone(trends[0]["prior_rank"])
            self.assertIsNone(trends[0]["rank_delta"])

    def test_digest_includes_value_changes(self):
        from public_flight_search.holiday_history import build_change_digest

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            append_history([_scored_deal(value_score=70.0, rank_value=3)], path=path)
            _backdate(path)
            digest = build_change_digest(
                summarize_trends([_scored_deal(value_score=84.0, rank_value=1)], path=path),
                path=path,
            )
            self.assertEqual(len(digest["value_changes"]), 1)
            vc = digest["value_changes"][0]
            self.assertEqual(vc["name"], "Test Resort")
            self.assertEqual(vc["current_rank"], 1)
            self.assertEqual(vc["prior_rank"], 3)

    def test_digest_value_changes_render(self):
        from public_flight_search.holiday_history import render_change_digest_html

        html = render_change_digest_html(
            {
                "has_prior": True,
                "drops": [],
                "rises": [],
                "new": [],
                "value_changes": [
                    {"name": "Resort A", "current_rank": 1, "prior_rank": 4, "delta": 3}
                ],
                "unchanged": 2,
            }
        )
        self.assertIn("is now #1 by value (was #4)", html)
        self.assertIn("Resort A", html)


if __name__ == "__main__":
    unittest.main()
