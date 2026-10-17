#!/usr/bin/env python3
"""Opt-in post-edit lint runner for the Codex hook.

Approval always comes from a single owner-global registry (`lint-projects.json` under
`~/.codex/framework/`), never a project-local file, so a project install cannot carry its
own execution approval. The installer never generates or trusts this file. The literal
(unresolved) registry path is used for the symlink/ancestor checks so that swapping an
ancestor directory for a symlink is caught rather than resolved away. On a recognized
successful, supported PostToolUse edit whose canonical event cwd exactly matches an
approved project root, the configured argv is run directly (no shell, no interpolation,
no --fix default) with stdin/stdout/stderr discarded. Only an approved root is run: a
nested working directory under a root is not automatically approved.

A user-selected command trusts that project's own code and dependencies; it is not
sandboxed or read-only. The run is bounded by a per-project timeout and its own POSIX
process group. A timed-out leader, or a leader that exits while descendants it spawned are
still running, is reported as timed-out/incomplete — never as a pass — and the group is
signalled (TERM then KILL) within a bounded grace. Cleanup is best effort: a process that
escapes the group is not contained, so the feedback claims only that a stop was signalled.
No argv, stdout, stderr, environment or patch content is placed in the hook output or
evidence; only a static status and the process exit code are reported. This is not a
sandbox. Python 3.11+.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time

# Approval registry, always the owner-global file regardless of install scope. Kept as a
# literal (unresolved) path so the symlink-ancestor guard in load_registry still fires.
REGISTRY = Path.home() / '.codex/framework/lint-projects.json'
# Bounded grace between SIGTERM and SIGKILL and for descendant cleanup. Kept small so
# the whole run (<=30s command + cleanup) stays inside the hook's 40s PostToolUse budget.
GRACE = 2.0
MIN_TIMEOUT, MAX_TIMEOUT, DEFAULT_TIMEOUT = 1, 30, 10

SUCCESS = 'Post-edit lint passed (exit code 0) for this approved project; the edit is applied.'
FAILURE = ('Post-edit lint failed (exit code {code}) for this approved project. The edit was applied '
           'and not rolled back; fix the reported failures before claiming the change is verified. '
           'The command, its output and environment are not shown here.')
TIMEOUT = ('Post-edit lint for this approved project timed out before completing; its process group '
           'was signalled to stop. The edit was applied and not rolled back; run the project quality '
           'gate manually.')
INCOMPLETE = ('Post-edit lint for this approved project did not finish: background processes it started '
              'were still running after the command exited and were signalled to stop. The edit was '
              'applied and not rolled back; do not treat lint as passed — run the project quality gate '
              'manually.')
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
    if not isinstance(data, dict):
        raise LintError('registry must be a JSON object')
    # JSON true equals 1 in Python, so reject bool explicitly before the version compare.
    if isinstance(data.get('version'), bool) or data.get('version') != 1:
        raise LintError('registry version is missing or unsupported')
    if set(data) - {'version', 'projects'}:
        raise LintError('registry has unexpected top-level keys')
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
    # An absent, relative, NUL-bearing or otherwise invalid cwd never matches an approved
    # absolute root: fall back to the reminder without executing anything.
    if not isinstance(cwd, str) or not cwd or '\x00' in cwd or not os.path.isabs(cwd):
        return None
    try:
        canonical = os.path.realpath(cwd)
    except (ValueError, OSError):
        return None
    match = next((entry for entry in entries if entry['root'] == canonical), None)
    if match is None:
        return None
    return _run_command(match['argv'], match['root'], match['timeout'])


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _group_alive(pgid: int) -> bool:
    """True if any process still belongs to the group (the reaped leader does not count)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # cannot prove it is empty: assume members remain and clean up.
    return True


def _wait_group_exit(pgid: int, grace: float) -> bool:
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _group_alive(pgid):
            return True
        time.sleep(0.02)
    return not _group_alive(pgid)


def _terminate_group(pgid: int, timed_out: bool) -> bool:
    """Signal any group members still alive after the leader finished.

    Returns True when live members had to be signalled — a timed-out run, or a leader that
    exited while descendants it spawned were still running (both are unfinished lint work).
    Returns False when the leader exited and the group was already empty. Escalates TERM ->
    KILL within the bounded grace; this is best effort and guarantees no containment.
    """
    if not timed_out and not _group_alive(pgid):
        return False
    _signal_group(pgid, signal.SIGTERM)
    if not _wait_group_exit(pgid, GRACE):
        _signal_group(pgid, signal.SIGKILL)
        _wait_group_exit(pgid, GRACE)
    return True


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
    killed = _terminate_group(pgid, timed_out)
    try:
        proc.wait(timeout=GRACE)  # reap the leader itself after the group is cleaned.
    except subprocess.TimeoutExpired:
        pass
    if timed_out:
        return _feedback(TIMEOUT)
    if killed:
        return _feedback(INCOMPLETE)
    if proc.returncode == 0:
        return _feedback(SUCCESS)
    return _feedback(FAILURE.format(code=proc.returncode))
