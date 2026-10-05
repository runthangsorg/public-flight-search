"""Stopover reads are seeded in both planner workflows, like hotel evidence.

Owner brief 2026-10-05 (H13 §1). The private engine writes one
``data/stopover_reads*.json`` batch (``stopover_reads/1``) per reading session,
and `holidays.load_stopover_reads` has always globbed for them at run time — but
neither planner workflow copied them in, so a live run could only ever price the
committed tuple and the winter reads never reached a December card. Both
workflows now copy every batch beside the hotel and package evidence: same clone,
same deploy key, no new secret, one honest count line per file and a warning
when the private repo holds none. They are runtime private data: .gitignore
covers them, and they are never committed.
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
    """The YAML of one step, from its name line to the next '- name:' line."""
    start = text.index(marker)
    nxt = text.find("- name:", start + len(marker))
    return text[start:nxt if nxt != -1 else len(text)]


class StopoverReadsSeedingTests(unittest.TestCase):
    def test_both_workflows_copy_every_stopover_batch_from_the_same_clone(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                body = _step_body(path.read_text(encoding="utf-8"), MARKER)
                # Derived from the hotel file's own directory, so the batches
                # come from whichever clone this run made and never open a
                # second transport. Globbed, so a run uses every batch the
                # engine has exported, not only the newest filename.
                self.assertIn('"$(dirname "${HOTEL_SRC}")"/stopover_reads*.json', body)
                self.assertIn('cp "${src}" "data/${name}"', body)

    def test_each_batch_gets_one_honest_count_line(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                body = _step_body(path.read_text(encoding="utf-8"), MARKER)
                self.assertIn('Seeded stopover reads: ${name} (', body)
                # The count is of rows that can become a fare, read back from
                # the file that was copied rather than assumed.
                self.assertIn('"priced"', body)
                self.assertIn('$(priced_stopover_reads "data/${name}")', body)

    def test_the_seed_step_warns_when_the_private_repo_holds_no_batch(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                body = _step_body(path.read_text(encoding="utf-8"), MARKER)
                self.assertIn("::warning::No stopover_reads", body)

    def test_the_seeding_opens_no_new_secret(self):
        # The stopover batches ride the step's existing transport. A new secret
        # here would be a second way into the private repo for no reason.
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                body = _step_body(path.read_text(encoding="utf-8"), MARKER)
                self.assertEqual(
                    body.count("${{ secrets."), 1,
                    "the stopover seeding must ride HISTORY_DEPLOY_KEY alone",
                )
                self.assertIn(
                    "HISTORY_DEPLOY_KEY: ${{ secrets.HISTORY_DEPLOY_KEY }}", body
                )

    def test_the_runtime_batches_are_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/stopover_reads*.json", ignore)


if __name__ == "__main__":
    unittest.main()
