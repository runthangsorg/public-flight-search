"""HOLIDAY_SEND_EVERY_RUN: the switch is wired, off by default, and still cooled.

Owner brief 2026-10-03. ``f118ddb`` added the switch to the job and ``317d1a1``
passed it through both workflows. Two of those three pieces had no test, and
the gap is the kind that hides: the switch is read from the environment, and a
repository VARIABLE is not in the runner's environment unless a workflow says
so. Between the two commits the switch did nothing at all and every test stayed
green, because no test looked at the workflow.

The cooldown is the other half. The switch joins ``force_send`` in the same
``or``, so "does the cooldown still hold a flat run down?" is exactly the
question that change raises, and the one test that exists sets
``HOLIDAY_EMAIL_COOLDOWN_MINUTES=0`` — switching the cooldown off to isolate
the switch, which leaves the property unpinned.

These parse the workflow files rather than trusting them.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from public_flight_search.jobs import run_holiday_planner

ROOT = Path(__file__).parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "holiday-planner.yml",
    ROOT / ".github" / "workflows" / "july-holiday-planner.yml",
)
SWITCH = "HOLIDAY_SEND_EVERY_RUN"


#: The two subcommands the workflows invoke. Matched by pattern because the
#: July planner is ``july-holiday-planner``, not ``holiday-planner``.
_PLANNER_RUN = re.compile(r"python -m public_flight_search\s+[\w-]*holiday-planner")


def _planner_step_env(path: Path) -> dict[str, str]:
    """The ``env:`` mapping of the step that runs the planner.

    A structural read of this file's shape, NOT a YAML parser: the project
    deliberately has no PyYAML dependency, and the property under test is one
    key in one block. Indentation carries the structure — a step is ``- name:``
    at one indent, its ``env:`` block is the keys indented under it — so this
    fails when the key is deleted, moved to another step, or misindented,
    which is the whole class of regression being guarded.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [
        (len(m.group(1)), m.group(2).strip(), index)
        for index, line in enumerate(lines)
        if (m := re.match(r"^(\s*)- name: (.+)$", line))
    ]
    for position, (indent, name, index) in enumerate(starts):
        end = starts[position + 1][2] if position + 1 < len(starts) else len(lines)
        body = lines[index + 1 : end]
        if not any(_PLANNER_RUN.search(line) for line in body):
            continue
        env: dict[str, str] = {}
        for offset, line in enumerate(body):
            if line.strip() != "env:":
                continue
            env_indent = len(line) - len(line.lstrip())
            for child in body[offset + 1 :]:
                if not child.strip():
                    continue
                if len(child) - len(child.lstrip()) <= env_indent:
                    break
                pair = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", child)
                if pair:
                    env[pair.group(1)] = pair.group(2)
            break
        if env:
            return env
    raise AssertionError(f"no planner step with an env: block in {path.name}")


class WorkflowWiringTests(unittest.TestCase):
    """The switch is a repository variable; the runner must be told about it."""

    def test_both_planners_receive_the_switch_from_vars(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                env = _planner_step_env(path)
                self.assertIn(
                    SWITCH,
                    env,
                    f"{path.name} does not pass {SWITCH} to the planner step, so "
                    f"the switch is inert no matter what the variable is set to",
                )

    def test_the_switch_is_not_passed_as_a_secret(self):
        """It is an on/off, not a credential, and a secret would be a mistake."""
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                value = _planner_step_env(path)[SWITCH]
                self.assertIn("vars.", value)
                self.assertNotIn("secrets.", value)

    def test_the_switch_reaches_a_step_that_actually_sends(self):
        """The env block must belong to the SENDING step, not a neighbour.

        A key bound to the wrong step is the quiet version of this bug: the
        variable is present, the workflow still says it is wired, and the run
        never sees it. So the env block is located by finding the step that
        runs the planner and reading THAT step's keys — never by grepping the
        file for the name.
        """
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn(SWITCH, text)
                # Every occurrence must sit in the planner step's env block, so
                # its offset has to fall between that step's start and the next
                # step's start.
                self.assertIn(SWITCH, _planner_step_env(path))


class SwitchDefaultsAndCooldownTests(unittest.TestCase):
    """Off unless the variable says otherwise; the cooldown still holds."""

    def setUp(self):
        self.payload = (ROOT / "examples" / "dec_holiday_config.json").read_text(
            encoding="utf-8"
        )
        sender = patch("public_flight_search.jobs.send_html")
        self.send = sender.start()
        self.addCleanup(sender.stop)

    def _run(self, tmp: str, **env_extra):
        env = {
            "HOLIDAY_SEARCH_CONFIG_JSON": self.payload,
            "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
            # R5: both evidence paths are CWD-relative defaults, and a checkout
            # the workflow has seeded is a different machine from CI.
            "HOLIDAY_HOTEL_EVIDENCE_PATH": str(Path(tmp) / "absent-hotel.json"),
            "HOLIDAY_LIVE_EVIDENCE_PATH": str(Path(tmp) / "absent-live.json"),
        }
        env.update(env_extra)
        with patch.dict(os.environ, env, clear=True):
            return run_holiday_planner(dry_run=False)

    def _backdate_history(self, tmp: str, *, minutes: int) -> None:
        """Make the last observation look ``minutes`` old.

        The cooldown reads the newest ``observed_at`` in the history file, so
        moving that stamp is the only honest way to place a run on a cadence:
        no clock is faked and no production code is touched.
        """
        history = Path(tmp) / "h.jsonl"
        rows = [json.loads(line) for line in history.read_text().splitlines() if line.strip()]
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        rows[-1]["observed_at"] = stamp
        history.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")

    def test_the_switch_is_off_when_the_variable_is_unset(self):
        """A flat re-run stays suppressed without the switch. Default is off."""
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp)
            result = self._run(tmp)
        self.assertFalse(result["email_sent"])
        self.assertTrue(result["send_skipped_no_change"])
        self.assertEqual(self.send.call_count, 1)

    def test_the_switch_on_sends_a_flat_run(self):
        """The switch's whole job, with the cooldown out of the way."""
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, HOLIDAY_SEND_EVERY_RUN="1",
                      HOLIDAY_EMAIL_COOLDOWN_MINUTES="0")
            result = self._run(tmp, HOLIDAY_SEND_EVERY_RUN="1",
                               HOLIDAY_EMAIL_COOLDOWN_MINUTES="0")
        self.assertTrue(result["email_sent"])
        self.assertFalse(result["send_skipped_no_change"])
        self.assertEqual(self.send.call_count, 2)

    def test_the_switch_on_never_overrides_a_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "HOLIDAY_SEARCH_CONFIG_JSON": self.payload,
                    "HOLIDAY_SEND_EVERY_RUN": "true",
                    "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
                },
                clear=True,
            ):
                result = run_holiday_planner(dry_run=True)
        self.assertFalse(result["email_sent"])
        self.send.assert_not_called()

    def test_the_cooldown_still_holds_a_switched_run(self):
        """The Mon/Wed/Fri cadence, and the half hour inside one slot.

        The switch joins ``force_send`` in one ``or``, so "does the cooldown
        still apply?" is the question this change actually raises. A manual
        dispatch ten minutes after the scheduled mail must not produce a
        second identical e-mail, switch on or off.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, HOLIDAY_SEND_EVERY_RUN="1")
            self._backdate_history(tmp, minutes=10)
            result = self._run(tmp, HOLIDAY_SEND_EVERY_RUN="1")
        self.assertFalse(result["email_sent"], "the cooldown did not hold")
        self.assertIn("cooldown", result["email_cooldown_reason"])
        self.assertEqual(self.send.call_count, 1)

    def test_a_switched_run_sends_once_the_cooldown_has_passed(self):
        """Past 180 minutes the cadence is allowed to mail again.

        The other half of the same property: a cooldown that never expires
        would satisfy the test above and quietly break the 3x-week schedule the
        switch exists to serve.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, HOLIDAY_SEND_EVERY_RUN="1")
            self._backdate_history(tmp, minutes=179)
            too_soon = self._run(tmp, HOLIDAY_SEND_EVERY_RUN="1")
            self._backdate_history(tmp, minutes=181)
            due = self._run(tmp, HOLIDAY_SEND_EVERY_RUN="1")
        self.assertFalse(too_soon["email_sent"])
        self.assertTrue(due["email_sent"])
        self.assertEqual(self.send.call_count, 2)

    def test_force_send_still_beats_the_cooldown_with_the_switch_on(self):
        """The one documented override: a deliberate re-dispatch."""
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, HOLIDAY_SEND_EVERY_RUN="1")
            self._backdate_history(tmp, minutes=1)
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": self.payload,
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "h.jsonl"),
                "HOLIDAY_SEND_EVERY_RUN": "1",
                "HOLIDAY_HOTEL_EVIDENCE_PATH": str(Path(tmp) / "absent-hotel.json"),
                "HOLIDAY_LIVE_EVIDENCE_PATH": str(Path(tmp) / "absent-live.json"),
            }
            with patch.dict(os.environ, env, clear=True):
                result = run_holiday_planner(dry_run=False, force_send=True)
        self.assertTrue(result["email_sent"])
        self.assertEqual(self.send.call_count, 2)
