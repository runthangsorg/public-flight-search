"""Hotel evidence is seeded in both planner workflows, like flight evidence.

Owner brief 2026-10-03 (H1). The private engine now writes
`data/holiday_hotel_evidence.json` next to the flight evidence, and both
planner workflows must copy it from the private checkout alongside
`data/holiday_live_evidence.json` — same deploy key, same reuse of the
history clone, same warning when the file is missing — and log one honest
count line. The file is runtime private data: .gitignore covers it, and it is
never committed.
"""

from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]

WORKFLOWS = (
    ROOT / ".github/workflows/holiday-planner.yml",
    ROOT / ".github/workflows/july-holiday-planner.yml",
)


def _step_body(text: str, marker: str) -> str:
    """The YAML of one step, from its name line to the next '- name:' line."""
    start = text.index(marker)
    nxt = text.find("- name:", start + len(marker))
    return text[start:nxt if nxt != -1 else len(text)]


class HotelEvidenceSeedingTests(unittest.TestCase):
    def test_both_workflows_seed_hotel_evidence(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                marker = "Seed hotel evidence from private data repo"
                self.assertIn(marker, text)
                body = _step_body(text, marker)

    def test_seed_step_reuses_the_flight_evidence_transport(self):
        # Same trigger conditions, same deploy key, same reuse of the history
        # clone: the hotel evidence rides exactly the proven flight path.
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                hotel = _step_body(
                    text, "Seed hotel evidence from private data repo")
                flight = _step_body(
                    text, "Seed live-fare evidence from private data repo")
                self.assertEqual(
                    hotel[hotel.index("if:") : hotel.index("env:")].strip(),
                    flight[flight.index("if:") : flight.index("env:")].strip(),
                    "hotel evidence must be seeded under the same conditions "
                    "as flight evidence",
                )
                self.assertIn("HISTORY_DEPLOY_KEY: ${{ secrets.HISTORY_DEPLOY_KEY }}", hotel)
                # Reuses the history clone before re-cloning, like the flight
                # evidence step does.
                self.assertIn("/tmp/history-seed/data/holiday_hotel_evidence.json", hotel)
                self.assertIn("runthangsorg/dealsearch.git", hotel)

    def test_seed_step_warns_when_the_file_is_missing(self):
        # The same warning shape as the flight evidence step: a ::warning::,
        # and the run continues on benchmarks rather than failing.
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                body = _step_body(
                    text, "Seed hotel evidence from private data repo")
                self.assertIn(
                    "::warning::No holiday_hotel_evidence.json in private repo;",
                    body,
                )

    def test_seed_step_logs_rates_and_properties(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                body = _step_body(
                    text, "Seed hotel evidence from private data repo")
                self.assertIn("Seeded hotel evidence:", body)
                self.assertIn("'rates'", body)
                self.assertIn("'properties'", body)

    def test_gitignore_covers_the_hotel_evidence_file(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/holiday_hotel_evidence.json", ignored)
        # And the tracked tree never contains it.
        self.assertFalse(
            (ROOT / "data" / "holiday_hotel_evidence.json").exists()
            and (ROOT / "data" / "holiday_hotel_evidence.json").is_file()
            and True
            and __import__("subprocess").run(
                ["git", "ls-files", "--error-unmatch",
                 "data/holiday_hotel_evidence.json"],
                cwd=ROOT, capture_output=True,
            ).returncode == 0,
            "holiday_hotel_evidence.json must never be tracked",
        )


if __name__ == "__main__":
    unittest.main()
