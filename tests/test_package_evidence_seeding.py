"""Package evidence is seeded in both planner workflows, like hotel evidence.

The private engine writes ``data/holiday_package_evidence.json``
(``holiday_package_evidence/1``) beside the hotel evidence, and both planner
workflows copy it inside the same seed step: same clone, same deploy key,
same warning shape when the file is missing, one honest count line. It is
runtime private data: .gitignore covers it, and it is never committed.
"""

from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]

WORKFLOWS = (
    ROOT / ".github/workflows/holiday-planner.yml",
    ROOT / ".github/workflows/july-holiday-planner.yml",
)

MARKER = "Seed hotel evidence from private data repo"


def _step_body(text: str, marker: str) -> str:
    start = text.index(marker)
    nxt = text.find("- name:", start + len(marker))
    return text[start:nxt if nxt != -1 else len(text)]


class PackageEvidenceSeedingTests(unittest.TestCase):
    def test_both_workflows_copy_the_package_file_from_the_same_clone(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                body = _step_body(path.read_text(encoding="utf-8"), MARKER)
                # Derived from HOTEL_SRC, so it comes from whichever clone the
                # hotel file came from and never opens a second transport.
                self.assertIn('PKG_SRC="$(dirname "${HOTEL_SRC}")/holiday_package_evidence.json"', body)
                self.assertIn('cp "${PKG_SRC}" data/holiday_package_evidence.json', body)

    def test_seed_step_logs_packages_operators_and_blocked_reads(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                body = _step_body(path.read_text(encoding="utf-8"), MARKER)
                self.assertIn("Seeded package evidence:", body)
                self.assertIn("'packages across'", body)
                self.assertIn("'blocked reads'", body)

    def test_seed_step_warns_when_the_package_file_is_missing(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                body = _step_body(path.read_text(encoding="utf-8"), MARKER)
                self.assertIn(
                    "::warning::No holiday_package_evidence.json in private repo;", body)

    def test_runtime_file_is_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/holiday_package_evidence.json", ignore)


if __name__ == "__main__":
    unittest.main()
