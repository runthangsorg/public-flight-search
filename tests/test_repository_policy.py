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
        self.assertNotIn("contents: write", workflows)
        self.assertNotIn("pull_request_target", workflows)

        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("schedule:", ci)
        for name in ("flight-digest.yml", "holiday-planner.yml"):
            production = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertNotIn("pull_request:", production)
            self.assertNotIn("push:", production)
            self.assertIn("default: true", production)

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
