"""The September Muscat/UAE flight digest is deleted, not gated off.

Owner instruction 2026-09-28: delete `.github/workflows/flight-digest.yml`
and every reference to it. It had been stopped on 2026-09-25
(`ENABLE_FLIGHT_DIGEST=false`, workflow disabled, its trip configs deleted);
a disabled workflow still publishes a dispatch button, a CLI command and a
test contract, which is exactly the redundancy being removed.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class FlightDigestRemovedTests(unittest.TestCase):
    def test_workflow_file_is_gone(self):
        self.assertFalse(
            (ROOT / ".github/workflows/flight-digest.yml").exists(),
            "flight-digest.yml must be deleted",
        )

    def test_no_source_or_test_references_remain(self):
        """No live code or docs may mention the deleted job.

        The two files that name it are the CONTRACT, not staleness: this test
        (which pins the deletion) and test_repository_policy.py (which pins
        the workflow-absence rule). egg-info is untracked build output.
        """
        contract_files = {
            "tests/test_flight_digest_removed.py",
            "tests/test_repository_policy.py",
            "AGENTS.md",  # records the deletion decision itself
        }
        offenders = []
        for base in ("src", "tests", "README.md", "AGENTS.md", ".github"):
            root = ROOT / base
            paths = root.rglob("*") if root.is_dir() else [root]
            for path in paths:
                if not path.is_file() or path.suffix == ".pyc":
                    continue
                rel = str(path.relative_to(ROOT))
                if rel in contract_files or "egg-info" in rel:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                if "flight-digest" in text or "run_flight_digest" in text:
                    offenders.append(rel)
        self.assertEqual(offenders, [], "stale flight-digest references remain")

    def test_flight_digest_example_config_is_gone(self):
        # dec_config.json was the digest's last flight-search payload (a
        # December flights-only search); nothing else read it.
        self.assertFalse(
            (ROOT / "examples" / "dec_config.json").exists(),
            "the flight-digest example payload is deleted with its job",
        )

    def test_the_cli_no_longer_offers_the_command(self):
        from public_flight_search.cli import main

        with self.assertRaises(SystemExit):
            main(["flight-digest", "--dry-run"])


if __name__ == "__main__":
    unittest.main()
