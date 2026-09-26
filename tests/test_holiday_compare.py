"""Regression tests for the holiday deal-delta analysis.

The point of these tests is the honesty rules: a cheaper total that is only
cheaper because the holiday is shorter, the board is lower, a live fare
became a benchmark or a transfer vanished must never be called a price
drop. Each bucket is pinned with an explicit case.
"""

import json
import tempfile
import unittest
from pathlib import Path

from public_flight_search.holiday_compare import (
    COMPARABLE_NEW_LOW,
    EXACT_DROP,
    NEW_DEAL,
    NEW_TRACKED,
    NO_CHANGE,
    PRICE_RISE,
    Observation,
    board_rank,
    build_callouts,
    build_report,
    classify,
    detect_false_drops,
    load_observations,
    observation_from_row,
    render_json,
    render_markdown,
)


def _row(
    *,
    resort: str = "Resort A",
    fingerprint: str = "fp1",
    nights: int = 7,
    outbound: str = "2026-12-22",
    return_: str = "2026-12-29",
    total: float = 5000.0,
    per_person: float = 1000.0,
    board: str = "All Inclusive",
    cabin: str = "ECONOMY",
    unit: str = "2-Bedroom Suite",
    live: bool = False,
    transfer: float = 30.0,
    observed_at: str = "2026-09-20T08:00:00+00:00",
) -> dict:
    return {
        "fingerprint": fingerprint,
        "resort_name": resort,
        "destination_key": "antalya",
        "destination_label": "Antalya",
        "outbound_date": outbound,
        "return_date": return_,
        "nights": nights,
        "unit_architecture": unit,
        "cabin_class": cabin,
        "board_basis": board,
        "total_package_price_gbp": total,
        "price_per_person_gbp": per_person,
        "flight_price_total_gbp": total / 2,
        "hotel_price_total_gbp": total / 2,
        "true_d2d_gbp": total + 46.5,
        "confidence": "verified-exact-date" if live else "market-supported",
        "live_used": live,
        "value_score": 50.0,
        "rank_value": 3,
        "transfer_gbp": transfer,
        "uk_ground_gbp": 16.5,
        "observed_at": observed_at,
        "run_id": "run-test",
    }


def _obs(**kwargs) -> Observation:
    return observation_from_row(_row(**kwargs))


class PricePerNightTests(unittest.TestCase):
    def test_pppn_uses_recorded_per_person_figure(self):
        obs = _obs(nights=8, per_person=800.0, total=4000.0)
        self.assertEqual(obs.price_per_person_per_night, 100.0)

    def test_pppn_falls_back_to_total_when_per_person_missing(self):
        obs = _obs(nights=4, per_person=0.0, total=2000.0)
        self.assertEqual(obs.price_per_person_per_night, 500.0)

    def test_pppn_zero_when_no_nights(self):
        obs = _obs(nights=0, per_person=1000.0)
        self.assertEqual(obs.price_per_person_per_night, 0.0)


class BoardRankTests(unittest.TestCase):
    def test_all_inclusive_plus_outranks_all_inclusive(self):
        self.assertGreater(board_rank("All Inclusive Plus"), board_rank("All Inclusive"))

    def test_half_board_beats_bed_and_breakfast(self):
        self.assertGreater(board_rank("Half Board"), board_rank("Bed & Breakfast"))

    def test_unknown_board_is_none(self):
        self.assertIsNone(board_rank("Mystery Plan"))
        self.assertIsNone(board_rank(""))


class ClassifyTests(unittest.TestCase):
    def test_exact_drop_same_fingerprint_lower_price(self):
        prior = _obs(total=5000.0, per_person=1000.0, observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(total=4700.0, per_person=940.0, observed_at="2026-09-23T08:00:00+00:00")
        result = classify(current, [prior, current])
        self.assertEqual(result.kind, EXACT_DROP)
        self.assertEqual(result.saving_gbp, 300.0)
        self.assertEqual(result.saving_per_person_gbp, 60.0)
        self.assertTrue(result.significant)

    def test_same_fingerprint_higher_price_is_a_rise(self):
        prior = _obs(total=5000.0, observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(total=5200.0, observed_at="2026-09-23T08:00:00+00:00")
        self.assertEqual(classify(current, [prior, current]).kind, PRICE_RISE)

    def test_same_fingerprint_identical_price_is_no_change(self):
        prior = _obs(total=5000.0, observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(total=5000.0, observed_at="2026-09-23T08:00:00+00:00")
        self.assertEqual(classify(current, [prior, current]).kind, NO_CHANGE)

    def test_first_sighting_is_new_tracked(self):
        current = _obs(observed_at="2026-09-23T08:00:00+00:00")
        self.assertEqual(classify(current, [current]).kind, NEW_TRACKED)

    def test_comparable_new_low_same_resort_board_different_dates(self):
        prior = _obs(
            fingerprint="fp-old", outbound="2026-12-20", return_="2026-12-27",
            total=6000.0, per_person=1200.0, observed_at="2026-09-20T08:00:00+00:00",
        )
        current = _obs(
            fingerprint="fp-new", outbound="2026-12-22", return_="2026-12-29",
            total=5100.0, per_person=1020.0, observed_at="2026-09-23T08:00:00+00:00",
        )
        result = classify(current, [prior, current])
        self.assertEqual(result.kind, COMPARABLE_NEW_LOW)
        self.assertGreaterEqual(result.saving_pppn_pct, 5.0)

    def test_new_deal_when_no_like_for_like_but_resort_cheaper(self):
        # Same resort + cabin, different board: no like-for-like prior, but
        # the resort's comparable is materially more expensive per night.
        prior = _obs(
            fingerprint="fp-hb", board="Half Board", total=6000.0, per_person=1200.0,
            observed_at="2026-09-20T08:00:00+00:00",
        )
        current = _obs(
            fingerprint="fp-ai", board="All Inclusive", total=5100.0, per_person=1020.0,
            observed_at="2026-09-23T08:00:00+00:00",
        )
        result = classify(current, [prior, current])
        self.assertEqual(result.kind, NEW_DEAL)

    def test_same_report_rows_are_not_compared_with_each_other(self):
        """Two products in one run share an observed_at and must not compare."""
        other = _obs(fingerprint="fp2", total=4000.0, per_person=800.0,
                     observed_at="2026-09-23T08:00:00+00:00")
        current = _obs(fingerprint="fp1", total=5000.0, per_person=1000.0,
                       observed_at="2026-09-23T08:00:00+00:00")
        self.assertEqual(classify(current, [other, current]).kind, NEW_TRACKED)


class FalseDropTests(unittest.TestCase):
    def test_fewer_nights_is_not_a_price_drop(self):
        prior = _obs(fingerprint="fp-long", nights=10, total=5000.0, per_person=1000.0,
                     observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(fingerprint="fp-short", nights=7, total=4200.0, per_person=840.0,
                       observed_at="2026-09-23T08:00:00+00:00")
        fd = detect_false_drops(current, [prior, current])
        self.assertIsNotNone(fd)
        self.assertEqual(fd.apparent_saving_gbp, 800.0)
        self.assertTrue(any("fewer nights" in reason for reason in fd.reasons))
        # ...and it is not classed as a comparable new low either.
        self.assertNotEqual(classify(current, [prior, current]).kind, COMPARABLE_NEW_LOW)

    def test_lower_board_basis_is_not_a_price_drop(self):
        prior = _obs(fingerprint="fp-ai", board="All Inclusive", total=5000.0,
                     per_person=1000.0, observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(fingerprint="fp-hb", board="Half Board", total=4600.0,
                       per_person=920.0, observed_at="2026-09-23T08:00:00+00:00")
        fd = detect_false_drops(current, [prior, current])
        self.assertIsNotNone(fd)
        self.assertTrue(any("lower board basis" in reason for reason in fd.reasons))

    def test_cross_cabin_comparison_is_scoped_out_not_flagged(self):
        # The report renders the same resort in Economy AND Business, so
        # comparing across cabins would flag every Economy card. Cabin is a
        # comparison KEY, never a like-for-like claim — so a cheaper Economy
        # row is not called a false drop against a Business one.
        prior = _obs(fingerprint="fp-biz", cabin="BUSINESS", total=9000.0,
                     per_person=1800.0, observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(fingerprint="fp-econ", cabin="ECONOMY", total=5000.0,
                       per_person=1000.0, observed_at="2026-09-23T08:00:00+00:00")
        self.assertIsNone(detect_false_drops(current, [prior, current]))

    def test_live_fare_replaced_by_benchmark_is_not_a_price_drop(self):
        prior = _obs(fingerprint="fp-live", live=True, total=5300.0, per_person=1060.0,
                     observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(fingerprint="fp-bench", live=False, total=5000.0,
                       per_person=1000.0, observed_at="2026-09-23T08:00:00+00:00")
        fd = detect_false_drops(current, [prior, current])
        self.assertIsNotNone(fd)
        self.assertTrue(any("benchmark" in reason for reason in fd.reasons))

    def test_lost_transfer_is_not_a_price_drop(self):
        prior = _obs(fingerprint="fp-tfr", transfer=120.0, total=5300.0,
                     per_person=1060.0, observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(fingerprint="fp-notfr", transfer=0.0, total=5150.0,
                       per_person=1030.0, observed_at="2026-09-23T08:00:00+00:00")
        fd = detect_false_drops(current, [prior, current])
        self.assertIsNotNone(fd)
        self.assertTrue(any("transfer" in reason for reason in fd.reasons))

    def test_legacy_row_without_board_never_claims_a_board_downgrade(self):
        prior_row = _row(fingerprint="fp-legacy", observed_at="2026-09-20T08:00:00+00:00")
        del prior_row["board_basis"]  # pre-board-basis history
        prior = observation_from_row(prior_row)
        current = _obs(fingerprint="fp-new", nights=5, board="Half Board", total=100.0,
                       per_person=20.0, observed_at="2026-09-23T08:00:00+00:00")
        fd = detect_false_drops(current, [prior, current])
        # Shorter stay is recorded, so a false drop IS detected; but the
        # board basis the legacy row never carried must not be invented.
        self.assertIsNotNone(fd)
        self.assertFalse(any("board" in reason for reason in fd.reasons))

    def test_genuine_drop_produces_no_false_drop(self):
        prior = _obs(fingerprint="fp1", total=5000.0, per_person=1000.0,
                     observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(fingerprint="fp1", total=4700.0, per_person=940.0,
                       observed_at="2026-09-23T08:00:00+00:00")
        self.assertIsNone(detect_false_drops(current, [prior, current]))


class DateCombinationTests(unittest.TestCase):
    def test_longer_stay_cheaper_than_shorter_is_flagged(self):
        short = _obs(fingerprint="fp7", nights=7, total=4200.0, per_person=840.0,
                     outbound="2026-12-22", return_="2026-12-29",
                     observed_at="2026-09-23T08:00:00+00:00")
        long_ = _obs(fingerprint="fp8", nights=8, total=4000.0, per_person=800.0,
                     outbound="2026-12-22", return_="2026-12-30",
                     observed_at="2026-09-23T08:00:00+00:00")
        report = build_report([short, long_], history_path="x")
        group = report.date_groups[0]
        self.assertTrue(group.longer_cheaper)
        self.assertEqual(group.longer_cheaper[0][2], 200.0)

    def test_best_value_is_lowest_pppn_not_lowest_total(self):
        cheap_total_short = _obs(fingerprint="fp6", nights=6, total=3600.0,
                                 per_person=720.0, observed_at="2026-09-23T08:00:00+00:00")
        better_pppn_long = _obs(fingerprint="fp10", nights=10, total=5000.0,
                                per_person=1000.0, outbound="2026-12-20",
                                return_="2026-12-30", observed_at="2026-09-23T08:00:00+00:00")
        report = build_report([cheap_total_short, better_pppn_long], history_path="x")
        group = report.date_groups[0]
        # 6n at 720/6=120 pppn vs 10n at 1000/10=100 pppn.
        self.assertEqual(group.best_value.nights, 10)


class ReportRenderingTests(unittest.TestCase):
    def _report(self):
        prior = _obs(fingerprint="fp1", total=5000.0, per_person=1000.0,
                     observed_at="2026-09-20T08:00:00+00:00")
        current = _obs(fingerprint="fp1", total=4700.0, per_person=940.0,
                       observed_at="2026-09-23T08:00:00+00:00")
        return build_report([prior, current], history_path="hist.jsonl")

    def test_markdown_has_four_tables(self):
        report = self._report()
        text = render_markdown(report, build_callouts(report))
        for heading in ("Table 1", "Table 2", "Table 3", "Table 4"):
            self.assertIn(heading, text)
        self.assertIn("Summary callouts", text)

    def test_json_is_parseable_and_classifies(self):
        report = self._report()
        payload = json.loads(render_json(report, build_callouts(report)))
        self.assertEqual(payload["exact_drops"][0]["saving_gbp"], 300.0)
        self.assertIn("callouts", payload)

    def test_callouts_pick_boards(self):
        half = _obs(fingerprint="h", board="Half Board", total=4000.0, per_person=800.0,
                    observed_at="2026-09-23T08:00:00+00:00")
        all_in = _obs(fingerprint="a", board="All Inclusive", total=4200.0, per_person=840.0,
                      outbound="2026-12-20", return_="2026-12-27",
                      observed_at="2026-09-23T08:00:00+00:00")
        report = build_report([half, all_in], history_path="x")
        callouts = build_callouts(report)
        self.assertEqual(callouts.best_half_board.resort_name, "Resort A")
        self.assertEqual(callouts.best_all_inclusive.board_basis, "All Inclusive")


class LoadObservationsTests(unittest.TestCase):
    def test_roundtrip_and_corrupt_line_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(_row()) + "\n")
                handle.write("{not valid json\n")
                handle.write(json.dumps(_row(fingerprint="fp2", total=6000.0)) + "\n")
            observations = load_observations(path)
            self.assertEqual(len(observations), 2)

    def test_missing_file_is_empty(self):
        self.assertEqual(load_observations(Path("/nonexistent/history.jsonl")), [])


if __name__ == "__main__":
    unittest.main()
