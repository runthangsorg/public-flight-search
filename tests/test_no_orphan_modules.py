"""Every module in the package is either reachable from an entry point or tested.

The September flight digest was deleted on 2026-09-28, but two of the modules
it was built on stayed behind with nothing importing them and no test either:
``history_db`` (an unused SQLite fare store) and ``scoring`` (the flight
option scorer). Code nobody runs and nobody tests still has to be read by
every reviewer of this public repository, and it rots silently. This keeps
the next leftover from going unnoticed.
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "public_flight_search"
ENTRY_POINTS = ("__init__", "__main__", "cli")


def _imports(source: str) -> set[str]:
    """Package-local modules one file imports, relatively or by full name."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module:
                found.add(node.module.split(".")[0])
            elif node.level == 1:
                found.update(alias.name for alias in node.names)
            elif node.module == "public_flight_search":
                found.update(alias.name for alias in node.names)
            elif node.module and node.module.startswith("public_flight_search."):
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("public_flight_search."):
                    found.add(alias.name.split(".")[1])
    return found


class NoOrphanModulesTests(unittest.TestCase):
    def test_every_module_is_reachable_or_tested(self):
        modules = {path.stem for path in PACKAGE.glob("*.py")}
        graph = {
            path.stem: _imports(path.read_text(encoding="utf-8")) & modules
            for path in PACKAGE.glob("*.py")
        }
        reachable: set[str] = set()
        stack = [name for name in ENTRY_POINTS if name in modules]
        while stack:
            name = stack.pop()
            if name not in reachable:
                reachable.add(name)
                stack.extend(graph.get(name, ()))
        tested: set[str] = set()
        for path in (ROOT / "tests").glob("test_*.py"):
            tested |= _imports(path.read_text(encoding="utf-8")) & modules
        orphans = sorted(modules - reachable - tested)
        self.assertEqual(orphans, [], "modules nothing runs and nothing tests")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
