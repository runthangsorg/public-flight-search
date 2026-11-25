"""The daily run line says whether any fare could have alerted, not only that none did.

Since 9 Nov 2026 the watcher e-mails on its own only for a fare at least 40% under its route median, and that median
needs ``min_observations`` earlier readings of the same route; a regional cap alone mails only with ``cap_alerts``.
From 11 to 21 Nov every run said "deals 0, mail not sent" while no fare it read had a route with five earlier
readings (the most any had was four), so no fare could have alerted whatever its price. The line read as "nothing
was cheap" when the truth was "nothing could be judged yet", and the owner was left asking why nothing was sent.
"""

from __future__ import annotations

import unittest

from test_business_deals import JobCase, median_history, raw_config, write_history


class MedianReadinessInRunLineTests(JobCase):
    def line(self, out):
        lines = [ln for ln in out.splitlines() if ln.startswith("business-deals")]
        self.assertEqual(len(lines), 1)
        return lines[0]

    def test_cold_routes_and_caps_off_say_no_fare_could_alert(self):
        cfg = raw_config(absolute_caps_gbp={}, cap_alerts=False)
        write_history(self.history, median_history("LHR", 2000, n=4))
        result, sink, out = self.run_job({"LHR": 900}, config=cfg)
        self.assertEqual(result.deals, [])
        self.assertEqual(sink.sent, [])
        line = self.line(out)
        self.assertIn("median ready 0 of 1 (needs 5 earlier readings), cap alerts off", line)
        self.assertEqual(result.median_ready, 0)

    def test_warm_route_is_counted(self):
        cfg = raw_config(absolute_caps_gbp={}, cap_alerts=False)
        write_history(self.history, median_history("LHR", 2000, n=5))
        result, _, out = self.run_job({"LHR": 1900}, config=cfg)
        self.assertEqual(result.deals, [])
        self.assertIn("median ready 1 of 1 (needs 5 earlier readings), cap alerts off", self.line(out))
        self.assertEqual(result.median_ready, 1)

    def test_readings_outside_the_window_do_not_count(self):
        cfg = raw_config(absolute_caps_gbp={}, cap_alerts=False, median_window_days=14)
        old = [dict(row, observed_at=row["observed_at"].replace("2026-10-", "2026-09-"))
               for row in median_history("LHR", 2000, n=6)]
        write_history(self.history, old)
        _, _, out = self.run_job({"LHR": 1900}, config=cfg)
        self.assertIn("median ready 0 of 1", self.line(out))

    def test_caps_on_are_not_called_off(self):
        result, _, out = self.run_job({"LHR": 2500})
        line = self.line(out)
        self.assertIn("median ready 0 of 1 (needs 5 earlier readings)", line)
        self.assertNotIn("cap alerts off", line)

    def test_a_run_that_read_no_fare_says_zero_of_zero(self):
        cfg = raw_config(cap_alerts=False)
        _, _, out = self.run_job({}, config=cfg)
        self.assertIn("median ready 0 of 0", self.line(out))


if __name__ == "__main__":
    unittest.main()
