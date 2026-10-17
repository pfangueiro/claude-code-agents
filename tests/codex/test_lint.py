"""Opt-in post-edit lint runs only approved commands, and only in disposable dirs/homes.

Every temporary directory is resolved so that the macOS /var symlink does not trip the
registry's own symlink-ancestor guard. Commands executed here are dummy Python helpers.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'codex'))
import lint
import hook

PY = sys.executable  # Absolute interpreter path satisfies the argv[0]-absolute rule.


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_dead(pid: int, timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline and alive(pid):
        time.sleep(0.05)
    return not alive(pid)


def force_kill(pid: int | None) -> None:
    """Defensive cleanup so a mutated (broken) cleanup path never leaks a sleeping process."""
    if pid is not None and alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


class LintBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='codex-lint-')
        self.root = Path(self.tmp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.registry = self.root / 'lint-projects.json'
        self._patch = patch.object(lint, 'REGISTRY', self.registry)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def write_registry(self, projects, version=1, mode=0o600):
        self.registry.write_text(json.dumps({'version': version, 'projects': projects}))
        self.registry.chmod(mode)

    def event(self, cwd=None):
        return {'hook_event_name': 'PostToolUse', 'tool_name': 'Write',
                'cwd': str(cwd if cwd is not None else self.project), 'tool_input': {'file_path': 'x'}}

    def context(self, result):
        return (result or {}).get('hookSpecificOutput', {}).get('additionalContext')

    def helper(self, name, body):
        path = self.root / name
        path.write_text(body)
        return str(path)


class RegistryGating(LintBase):
    def test_disabled_when_no_registry(self):
        self.assertIsNone(lint.run_lint(self.event()))

    def test_approved_root_runs_and_reports_pass(self):
        self.write_registry([{'root': str(self.project), 'command': [PY, '-c', 'import sys; sys.exit(0)']}])
        self.assertEqual(self.context(lint.run_lint(self.event())), lint.SUCCESS)

    def test_unapproved_cwd_falls_back_to_reminder(self):
        other = self.root / 'other'
        other.mkdir()
        self.write_registry([{'root': str(other), 'command': [PY, '-c', 'pass']}])
        self.assertIsNone(lint.run_lint(self.event()))

    def test_nested_cwd_is_not_approved(self):
        nested = self.project / 'sub'
        nested.mkdir()
        self.write_registry([{'root': str(self.project), 'command': [PY, '-c', 'pass']}])
        self.assertIsNone(lint.run_lint(self.event(cwd=nested)))

    def test_missing_cwd_falls_back(self):
        self.write_registry([{'root': str(self.project), 'command': [PY, '-c', 'pass']}])
        event = self.event()
        del event['cwd']
        self.assertIsNone(lint.run_lint(event))


class RegistrySafety(LintBase):
    def assertUnsafe(self):
        self.assertEqual(self.context(lint.run_lint(self.event())), lint.UNSAFE)

    def test_symlink_registry_rejected(self):
        real = self.root / 'real.json'
        real.write_text(json.dumps({'version': 1, 'projects': []}))
        self.registry.symlink_to(real)
        self.assertUnsafe()

    def test_group_or_world_writable_rejected(self):
        self.write_registry([], mode=0o666)
        self.assertUnsafe()

    def test_not_owned_by_effective_user_rejected(self):
        self.write_registry([{'root': str(self.project), 'command': [PY, '-c', 'pass']}])
        other_uid = os.geteuid() + 1
        with patch.object(lint.os, 'geteuid', lambda: other_uid):
            self.assertUnsafe()

    def test_malformed_json_rejected(self):
        self.registry.write_text('{not json')
        self.registry.chmod(0o600)
        self.assertUnsafe()

    def test_unknown_version_rejected(self):
        self.write_registry([], version=2)
        self.assertUnsafe()

    def test_duplicate_root_rejected(self):
        self.write_registry([{'root': str(self.project), 'command': [PY, '-c', 'pass']},
                             {'root': str(self.project), 'command': [PY, '-c', 'pass']}])
        self.assertUnsafe()

    def test_unsafe_entries_rejected(self):
        bad = [
            {'root': 'relative/path', 'command': [PY, '-c', 'pass']},
            {'root': str(self.project), 'command': []},
            {'root': str(self.project), 'command': ['eslint', '.']},            # argv[0] not absolute
            {'root': str(self.project), 'command': [PY], 'timeout': 0},
            {'root': str(self.project), 'command': [PY], 'timeout': 31},
            {'root': str(self.project), 'command': [PY], 'timeout': True},
            {'root': str(self.project), 'command': [PY], 'extra': 1},           # unknown key
            {'root': str(self.project), 'command': 'eslint'},                   # command not a list
        ]
        for entry in bad:
            with self.subTest(entry=entry):
                self.write_registry([entry])
                self.assertUnsafe()


class CommandExecution(LintBase):
    def test_failing_command_reports_exit_code_without_output_or_argv(self):
        marker = 'SECRET_LINT_OUTPUT_MARKER'
        script = self.helper('fail.py', f'import sys\nprint("{marker}")\nsys.stderr.write("{marker}")\nsys.exit(3)\n')
        self.write_registry([{'root': str(self.project), 'command': [PY, script]}])
        context = self.context(lint.run_lint(self.event()))
        self.assertIn('exit code 3', context)
        self.assertNotIn(marker, context)
        self.assertNotIn(script, context)
        self.assertNotIn('fail.py', context)

    def test_unavailable_command_reported(self):
        self.write_registry([{'root': str(self.project), 'command': [str(self.root / 'missing-binary')]}])
        self.assertEqual(self.context(lint.run_lint(self.event())), lint.UNAVAILABLE)

    def test_shell_metacharacters_are_literal(self):
        out = self.root / 'argv.json'
        script = self.helper('record.py', 'import json, sys\njson.dump(sys.argv[2:], open(sys.argv[1], "w"))\n')
        argv = [PY, script, str(out), ';echo pwned', '$(echo hi)', '&& ls', '`id`']
        self.write_registry([{'root': str(self.project), 'command': argv}])
        self.assertEqual(self.context(lint.run_lint(self.event())), lint.SUCCESS)
        self.assertEqual(json.loads(out.read_text()), argv[3:])
        self.assertFalse((self.project / 'pwned').exists())

    def test_timeout_terminates_leader_and_grandchild(self):
        gpid = self.root / 'grandchild.pid'
        sleeper = self.helper('sleeper.py', 'import os, sys, time\n'
                              'open(sys.argv[1], "w").write(str(os.getpid()))\ntime.sleep(60)\n')
        leader = self.helper('leader.py', 'import os, subprocess, sys, time\n'
                             'subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n'
                             'for _ in range(200):\n'
                             '    if os.path.exists(sys.argv[2]):\n        break\n    time.sleep(0.02)\n'
                             'time.sleep(60)\n')
        self.write_registry([{'root': str(self.project),
                              'command': [PY, leader, sleeper, str(gpid)], 'timeout': 1}])
        grandchild = None
        try:
            self.assertEqual(self.context(lint.run_lint(self.event())), lint.TIMEOUT)
            self.assertTrue(gpid.exists(), 'grandchild never started')
            grandchild = int(gpid.read_text())
            self.assertTrue(wait_dead(grandchild), 'grandchild survived timeout cleanup')
        finally:
            force_kill(grandchild)

    def test_leader_exit_cleans_lingering_descendant(self):
        dpid = self.root / 'descendant.pid'
        sleeper = self.helper('sleeper2.py', 'import os, sys, time\n'
                              'open(sys.argv[1], "w").write(str(os.getpid()))\ntime.sleep(60)\n')
        leader = self.helper('leader2.py', 'import os, subprocess, sys, time\n'
                             'subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n'
                             'for _ in range(200):\n'
                             '    if os.path.exists(sys.argv[2]):\n        break\n    time.sleep(0.02)\n'
                             'sys.exit(0)\n')
        self.write_registry([{'root': str(self.project),
                              'command': [PY, leader, sleeper, str(dpid)], 'timeout': 10}])
        descendant = None
        try:
            self.assertEqual(self.context(lint.run_lint(self.event())), lint.SUCCESS)
            self.assertTrue(dpid.exists(), 'descendant never started')
            descendant = int(dpid.read_text())
            self.assertTrue(wait_dead(descendant), 'descendant left running after leader exit')
        finally:
            force_kill(descendant)


class HookIntegration(LintBase):
    def test_non_edit_events_never_lint(self):
        with patch.object(lint, 'run_lint') as spy:
            for name in ('SessionStart', 'SessionEnd', 'SubagentStart', 'PreCompact', 'PermissionRequest'):
                hook.inspect_event({'hook_event_name': name, 'tool_name': 'Write',
                                    'cwd': str(self.project), 'tool_input': {'file_path': 'x'}})
            hook.inspect_event({'hook_event_name': 'PreToolUse', 'tool_name': 'Write',
                                'cwd': str(self.project), 'tool_input': {'file_path': 'src/main.py'}})
            spy.assert_not_called()
            hook.inspect_event(self.event())
            spy.assert_called_once()

    def test_failed_edit_event_skips_lint_and_output(self):
        with patch.object(lint, 'run_lint') as spy:
            event = self.event()
            event['tool_output'] = {'status': 'error'}
            self.assertEqual(hook.inspect_event(event), {})
            spy.assert_not_called()

    def test_reminder_fallback_when_not_opted_in(self):
        out = hook.inspect_event(self.event())
        self.assertEqual(out['hookSpecificOutput']['additionalContext'], hook.QUALITY_GATE_REMINDER)


if __name__ == '__main__':
    unittest.main()
