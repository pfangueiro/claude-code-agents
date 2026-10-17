#!/usr/bin/env python3
"""Opt-in post-edit lint runner for the Codex hook.

A user-owned registry (`lint-projects.json`, next to this file in the installed
`.codex/framework/` directory) names projects that have explicitly approved a lint
command. The installer never generates or trusts this file. On a successful,
supported PostToolUse edit whose canonical event cwd exactly matches an approved
project root, the configured argv is run directly (no shell, no interpolation,
no --fix default) with stdin/stdout/stderr discarded. Only an approved root is
run: a nested working directory under a root is not automatically approved.

A user-selected command trusts that project's own code and dependencies; it is not
sandboxed or read-only. The run is bounded by a per-project timeout and its own
POSIX process group so that a timed-out leader and any descendants are terminated
and an early-exiting leader cannot leave descendants running. No argv, stdout,
stderr, environment or patch content is placed in the hook output or evidence; only
a static status and the process exit code are reported. This is not a sandbox.
Python 3.11+.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess

# Registry of user-approved projects, resolved beside the installed runner.
REGISTRY = Path(__file__).resolve().parent / 'lint-projects.json'
# Bounded grace between SIGTERM and SIGKILL and for descendant cleanup. Kept small so
# the whole run (<=30s command + cleanup) stays inside the hook's 40s PostToolUse budget.
GRACE = 2.0
MIN_TIMEOUT, MAX_TIMEOUT, DEFAULT_TIMEOUT = 1, 30, 10

SUCCESS = 'Post-edit lint passed (exit code 0) for this approved project; the edit is applied.'
FAILURE = ('Post-edit lint failed (exit code {code}) for this approved project. The edit was applied '
           'and not rolled back; fix the reported failures before claiming the change is verified. '
           'The command, its output and environment are not shown here.')
TIMEOUT = ('Post-edit lint for this approved project timed out and its process group was terminated. '
           'The edit was applied and not rolled back; run the project quality gate manually.')
UNAVAILABLE = ('Post-edit lint for this approved project could not start (the configured command is '
               'missing or not executable); no command output is retained. Run the project quality '
               'gate manually.')
UNSAFE = ('A post-edit lint registry is present but was rejected as unsafe or malformed; no command '
          'ran. Review the lint-projects.json registry. Run the project quality gate manually.')


class LintError(Exception):
    """A present-but-unusable registry or entry: report feedback, never run anything."""


def _feedback(message: str) -> dict:
    return {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': message}}


def load_registry(path: Path) -> list[dict]:
    """Validate the registry file and return canonical approved entries, or raise LintError."""
    if path.is_symlink():
        raise LintError('registry is a symlink')
    for parent in path.parents:
        if parent.is_symlink():
            raise LintError('registry ancestor is a symlink')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise LintError('registry is not a regular file')
    if info.st_uid != os.geteuid():
        raise LintError('registry is not owned by the effective user')
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise LintError('registry is group- or world-writable')
    try:
        data = json.loads(path.read_bytes())
    except (ValueError, UnicodeDecodeError) as err:
        raise LintError('registry is not valid JSON') from err
    if not isinstance(data, dict) or data.get('version') != 1:
        raise LintError('registry version is missing or unsupported')
    projects = data.get('projects')
    if not isinstance(projects, list):
        raise LintError('registry projects must be a list')
    entries: list[dict] = []
    seen: set[str] = set()
    for item in projects:
        entries.append(_entry(item, seen))
    return entries


def _entry(item: object, seen: set[str]) -> dict:
    if not isinstance(item, dict) or set(item) - {'root', 'command', 'timeout'}:
        raise LintError('malformed registry entry')
    root = item.get('root')
    if not isinstance(root, str) or not root or not os.path.isabs(root) or '\x00' in root:
        raise LintError('entry root must be an absolute path')
    canonical = os.path.realpath(root)
    if canonical in seen:
        raise LintError('duplicate registry root')
    seen.add(canonical)
    command = item.get('command')
    if (not isinstance(command, list) or not command
            or not all(isinstance(arg, str) and arg and '\x00' not in arg for arg in command)):
        raise LintError('entry command must be a non-empty list of literal strings')
    if not os.path.isabs(command[0]):
        raise LintError('entry command[0] must be an absolute executable path')
    timeout = item.get('timeout', DEFAULT_TIMEOUT)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT:
        raise LintError('entry timeout must be an integer between 1 and 30')
    return {'root': canonical, 'argv': list(command), 'timeout': timeout}


def run_lint(event: dict) -> dict | None:
    """Return PostToolUse feedback, or None to fall back to the existing reminder.

    None means the project has not opted in (no registry or no matching approved root).
    A present-but-unsafe registry, an unavailable command, a failure and a timeout each
    return static feedback.
    """
    if not os.path.lexists(REGISTRY):
        return None
    try:
        entries = load_registry(REGISTRY)
    except (LintError, OSError):
        return _feedback(UNSAFE)
    cwd = event.get('cwd')
    if not isinstance(cwd, str) or not cwd:
        return None
    canonical = os.path.realpath(cwd)
    match = next((entry for entry in entries if entry['root'] == canonical), None)
    if match is None:
        return None
    return _run_command(match['argv'], match['root'], match['timeout'])


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _run_command(argv: list[str], cwd: str, timeout: int) -> dict:
    executable = argv[0]
    if not (os.path.isabs(executable) and os.path.isfile(executable) and os.access(executable, os.X_OK)):
        return _feedback(UNAVAILABLE)
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError:
        return _feedback(UNAVAILABLE)
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        pgid = proc.pid
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _signal_group(pgid, signal.SIGTERM)
        try:
            proc.wait(timeout=GRACE)
        except subprocess.TimeoutExpired:
            _signal_group(pgid, signal.SIGKILL)
            try:
                proc.wait(timeout=GRACE)
            except subprocess.TimeoutExpired:
                pass
    finally:
        # Kill any descendants lingering in the leader's process group, whether the
        # leader timed out or exited early on its own. Never leave a group running.
        _signal_group(pgid, signal.SIGKILL)
    if timed_out:
        return _feedback(TIMEOUT)
    if proc.returncode == 0:
        return _feedback(SUCCESS)
    return _feedback(FAILURE.format(code=proc.returncode))
