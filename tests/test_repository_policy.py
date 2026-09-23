import unittest
from pathlib import Path
import re


ROOT = Path(__file__).parents[1]


class RepositoryPolicyTests(unittest.TestCase):
    def test_workflows_are_read_only_bounded_and_never_publish_reports(self):
        workflows = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
        )
        self.assertIn("permissions:\n  contents: read", workflows)
        self.assertIn("concurrency:", workflows)
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", workflows)
        self.assertIn("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", workflows)
        self.assertNotIn("upload-artifact", workflows)
        self.assertNotIn("Dump debug log", workflows)
        self.assertNotIn("cat /tmp/flight-debug.log", workflows)
        self.assertNotIn("playwright install", workflows)
        self.assertNotIn(".[browser]", workflows)
        self.assertNotIn("contents: write", workflows)
        self.assertNotIn("pull_request_target", workflows)

        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("schedule:", ci)
        for name in ("flight-digest.yml", "holiday-planner.yml", "july-holiday-planner.yml"):
            production = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertNotIn("pull_request:", production)
            self.assertNotIn("push:", production)
            self.assertIn("default: true", production)

        flight = (ROOT / ".github/workflows/flight-digest.yml").read_text(encoding="utf-8")
        holiday = (ROOT / ".github/workflows/holiday-planner.yml").read_text(encoding="utf-8")
        july = (ROOT / ".github/workflows/july-holiday-planner.yml").read_text(encoding="utf-8")
        self.assertNotIn("HOLIDAY_SEARCH_CONFIG_JSON", flight)
        self.assertLess(flight.index("Run safety tests"), flight.index("FLIGHT_SEARCH_CONFIG_JSON"))
        self.assertLess(holiday.index("Run safety tests"), holiday.index("HOLIDAY_SEARCH_CONFIG_JSON"))
        self.assertLess(july.index("Run safety tests"), july.index("JULY_HOLIDAY_SEARCH_CONFIG_JSON"))

    def test_holiday_planners_seed_live_fare_evidence_before_build(self):
        # A planner that builds without the live-evidence seed silently
        # degrades every card to benchmarks; pin the seed in both planners.
        for name in ("holiday-planner.yml", "july-holiday-planner.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertIn(
                "Seed live-fare evidence from private data repo", workflow, name
            )
            self.assertIn(
                'cp "${EVIDENCE_SRC}" data/holiday_live_evidence.json', workflow, name
            )
            self.assertLess(
                workflow.index("holiday_live_evidence.json"),
                workflow.index("Build and optionally deliver"),
                name,
            )
            # Evidence must be seedable on its own, so an operator can verify
            # the private-vault transport with dry_run=true+seed_evidence=true
            # (read-only, no email) instead of learning a deploy key broke from
            # a report that had quietly fallen back to benchmarks.
            self.assertIn("seed_evidence", workflow, name)
            self.assertIn("inputs.seed_evidence == true", workflow, name)

    def test_live_fare_evidence_is_not_seeded_by_the_history_step(self):
        # Evidence is CURRENT MARKET DATA; price history is history-memory, and
        # a dry run must never see prior observations. Merging the two seeds
        # back into one step would either let a dry run read history (breaking
        # "a dry run reflects a fresh build") or make the live path
        # unverifiable without sending an email.
        for name in ("holiday-planner.yml", "july-holiday-planner.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertNotIn(
                "cp /tmp/history-seed/data/holiday_live_evidence.json", workflow, name
            )
            history_step = workflow.index("Seed price history from private data repo")
            evidence_step = workflow.index(
                "Seed live-fare evidence from private data repo"
            )
            self.assertLess(history_step, evidence_step, name)

    def test_holiday_seed_log_reports_records_not_airports(self):
        # The seed step printed the RECORD count while labelling it
        # "airports", overstating live coverage many times over: 125 records
        # covered 14 airports, and only 45 were from the priced origin.
        for name in ("holiday-planner.yml", "july-holiday-planner.yml"):
            workflow = (ROOT / ".github" / "workflows" / name).read_text(
                encoding="utf-8"
            )
            self.assertIn("records across", workflow, name)
            self.assertNotIn("else echo 0) airports.", workflow, name)

    def test_readme_does_not_claim_browser_runtime_or_history_provenance(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("browser-backed", readme)
        self.assertNotIn("Fresh public history", readme)

    def test_public_tree_contains_no_personalized_defaults(self):
        production = [ROOT / "README.md"]
        production += list((ROOT / "src").rglob("*.py"))
        production += list((ROOT / "examples").rglob("*"))
        production += list((ROOT / ".github/workflows").glob("*.yml"))
        for path in production:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            self.assertIsNone(
                re.search(r"[a-z0-9._%+-]+@(?!example\.test)[a-z0-9.-]+\.[a-z]{2,}", text),
                str(path.relative_to(ROOT)),
            )
            self.assertIsNone(
                re.search(r"\b[a-z]{1,2}\d[a-z\d]?\s*\d[a-z]{2}\b", text, re.I),
                str(path.relative_to(ROOT)),
            )


if __name__ == "__main__":
    unittest.main()
