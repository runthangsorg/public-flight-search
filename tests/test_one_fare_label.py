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
import re
import unittest

from public_flight_search.holidays import (
    _FLIGHT_BASIS_WORDS,
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)
from public_flight_search.live_verify import LiveFareEvidence

#: A fare's parenthesised provenance in a rendered line: "flights £4,695 (...)".
_FARE_LABEL = re.compile(r"flights £[\d,]+[^(]*\(([^)]*)\)")
#: The four provenance words a fare label may use, one at a time.
_PROVENANCE = ("read", "observed", "benchmark", "estimate")

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

    def test_every_rendered_fare_label_carries_exactly_one_provenance(self):
        # Four provenances in one report: a benchmark-fallback Economy fare, a
        # read multi-city stopover fare, an aged observed headline fare, and an
        # x1.6 estimate. Each label must pick exactly one of the four words.
        config = _july_uncapped()
        aged = LiveFareEvidence(
            airport="HKT",
            total_gbp=11100.0,
            basis="whole_party_return_total",
            source_url="https://example.invalid/hkt",
            observed_at="2026-09-01T00:00:00+00:00",
            exact_date_match=True,
            cabin_class="BUSINESS",
            stale=True,
        )
        html = render_holiday_report(
            config, generated_at="2026-10-02T00:00:00+00:00",
            deals=collect_holiday_deals(config, live_flight_offers={("HKT", "BUSINESS"): aged}),
        )
        labels = _FARE_LABEL.findall(html)
        self.assertTrue(labels)
        for label in labels:
            with self.subTest(label=label):
                hits = [word for word in _PROVENANCE if word in label.lower()]
                self.assertEqual(
                    len(hits), 1, f"{label!r} carries {hits}, expected exactly one"
                )
        joined = " | ".join(labels).lower()
        for word in _PROVENANCE:
            with self.subTest(missing=word):
                self.assertIn(word, joined, f"the report should exercise {word!r}")
        # And the one rule the brief states outright: no fare is both read and
        # a benchmark.
        for label in labels:
            with self.subTest(label=label):
                low = label.lower()
                self.assertFalse("read" in low and "benchmark" in low)


if __name__ == "__main__":
    unittest.main()
