"""One honest label per fare: never both "read" and "benchmark".

Owner brief 2026-10-02. A fare label that says the fare was READ and is a
BENCHMARK at once tells the reader two contradictory things. The economy
fallback, "economy fare read (benchmark)", did exactly that. A benchmark is a
modelled figure and must not claim to have been observed; an observed fare must
not be called a benchmark.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import unittest

from public_flight_search.holidays import (
    _FLIGHT_BASIS_WORDS,
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"


def _july_uncapped():
    config = load_holiday_config(JULY.read_text(encoding="utf-8"))
    return dataclasses.replace(config, max_budget_gbp=60000.0)


class OneFareLabelTests(unittest.TestCase):
    def test_no_flight_option_is_labelled_both_read_and_benchmark(self):
        labels = {
            str(option.get("flight_basis", ""))
            for deal in collect_holiday_deals(_july_uncapped())
            for option in deal.flight_options
        }
        self.assertTrue(labels)
        for label in labels:
            with self.subTest(label=label):
                low = label.lower()
                self.assertFalse(
                    "read" in low and "benchmark" in low,
                    f"a fare label cannot say both 'read' and 'benchmark': {label!r}",
                )

    def test_a_benchmark_economy_fare_is_not_described_as_read(self):
        # No live offers are supplied, so every headline fare is a benchmark.
        labels = {
            str(option.get("flight_basis", ""))
            for deal in collect_holiday_deals(_july_uncapped())
            for option in deal.flight_options
            if option.get("kind") == "economy"
        }
        self.assertTrue(labels)
        for label in labels:
            with self.subTest(label=label):
                self.assertNotIn("read", label.lower())
                self.assertIn("benchmark", label.lower())

    def test_the_shared_basis_words_never_say_both(self):
        for basis, words in _FLIGHT_BASIS_WORDS.items():
            with self.subTest(basis=basis):
                low = words.lower()
                self.assertFalse("read" in low and "benchmark" in low)

    def test_the_rendered_report_does_not_contradict_itself(self):
        config = _july_uncapped()
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=collect_holiday_deals(config),
        )
        self.assertNotIn("fare read (benchmark)", html)


if __name__ == "__main__":
    unittest.main()
