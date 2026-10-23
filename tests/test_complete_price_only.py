"""A trip is shown only with a complete price: flights read for its dates (owner, 23 Oct 2026).

"What use is flights not priced package prices, either give the complete price or don't bother." A trip with no flights
read for its dates (an estimate or a dated-line package) is a guide price, not a price, so the report leaves it out until the
nightly pricer has read flights for it. Everything here is synthetic
(the example config's trips; no private evidence).
"""
from __future__ import annotations

import dataclasses
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_multi_centre_reads as base  # noqa: E402  (shares its synthetic reads and config)
from public_flight_search.holiday_email import (  # noqa: E402
    _multi_centre_rows,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import collect_holiday_deals  # noqa: E402


class CompletePriceOnly(unittest.TestCase):
    def setUp(self):
        self.config = base._config()

    def test_a_trip_is_shown_only_when_flights_were_read_for_its_dates(self):
        every = _multi_centre_rows(self.config)
        complete = _multi_centre_rows(self.config, complete_only=True)
        kept = {r["trip"].id for r in complete}
        for row in every:
            has_read = bool(any((row["reads"] or {}).values()) or row["read"])
            self.assertEqual(row["trip"].id in kept, has_read, row["trip"].id)
        self.assertLess(len(complete), len(every), "the example data has trips with no flight read")

    def test_a_trip_that_has_a_flight_read_stays_even_when_it_is_an_estimate(self):
        confidence = {r["trip"].id: r["trip"].confidence for r in _multi_centre_rows(self.config)}
        estimate = next(w for w in base._declared(self.config) if confidence[w["trip"]] == "estimate")
        fares = {base.hol.multi_centre_fare_key(estimate["trip"], estimate["legs"]): base._multi_centre_read(estimate)}
        ids = {r["trip"].id for r in _multi_centre_rows(self.config, fares=fares, complete_only=True)}
        self.assertIn(estimate["trip"], ids)

    def test_the_report_never_says_flights_not_priced_on_a_trip_row(self):
        deals = collect_holiday_deals(self.config)
        config = dataclasses.replace(self.config, complete_price_only=True)
        html = render_holiday_report_compact(config, generated_at=base.GENERATED_AT, deals=deals, multi_centre_fares={})
        text = render_holiday_report_compact_text(config, generated_at=base.GENERATED_AT, deals=deals, multi_centre_fares={})
        self.assertNotRegex(html, r"operator package[^<]{0,80}flights not priced")
        self.assertNotRegex(text, r"operator package[^\n]{0,80}flights not priced")

    def test_a_config_with_no_such_field_means_complete_prices_only(self):
        from public_flight_search.holidays import load_holiday_config
        text = base.JULY.read_text(encoding="utf-8")
        self.assertTrue(load_holiday_config(text).complete_price_only)
        import json
        off = json.loads(text)
        off["complete_price_only"] = False
        self.assertFalse(load_holiday_config(json.dumps(off)).complete_price_only)

    def test_the_pricer_is_still_asked_for_every_trip(self):
        """Dropping an unpriced trip from the report must not drop it from the pricer's list, or it would never be priced."""
        from public_flight_search.holiday_email import multi_centre_wanted
        wanted = {w["trip"] for w in multi_centre_wanted(self.config)}
        every = {r["trip"].id for r in _multi_centre_rows(self.config)}
        self.assertEqual(wanted, every)


if __name__ == "__main__":
    unittest.main()
