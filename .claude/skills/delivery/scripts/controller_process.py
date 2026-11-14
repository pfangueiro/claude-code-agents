#!/usr/bin/env python3
"""Owned, pollable command lifecycle for the persistent delivery controller (stdlib only).

One generic helper that provider adapters, external-effect steps and verification checks
share to run ONE owner-compiled literal argv. It is NOT a provider adapter, agent/tool
loop, sandbox or acceptance oracle: it records what the OS showed about the process tree
and never infers that the work itself succeeded. POSIX (macOS/Linux) only.

API
    CommandSpec(argv, cwd, stdin, attempt_id, env_selectors={})
    prepare(attempts_root, spec, timeout_seconds, term_grace_seconds=5, linger_seconds=5,
            bindings=None) -> Path       new 0700 attempt; stdin + immutable intent first
    spawn(attempt, environment=None) -> Pending   anchored bootstrap blocked on release
    Pending.identity                      the caller persists this durably, then
    Pending.release() -> OwnedProcess  |  Pending.abort()
    OwnedProcess.attach(attempt)          re-attach after a controller restart
    OwnedProcess.poll() -> Recovery       short; never blocks beyond a bounded reap
    OwnedProcess.request_stop() / request_stop(attempt) -> 'owned'|'not-owned'|'unknown'|'not-spawned'
    OwnedProcess.finalize() / finalize(attempt) -> lifecycle record dict, written once
                                          (the handle reaps its own bootstrap first and
                                          refuses with 'bootstrap-unreaped' or
                                          'attempt-<state>' while it is still unreaped)
    recover(attempt) -> Recovery(state, relaunch_safe, identity_status, reason)
    read_status(attempt) -> status dict   read-only; creates nothing
    escaped_settled(record) -> bool       escaped-descendant predicate for a VALIDATED record
    python3 -I -B controller_process.py --status <attempt>

States: prepared, awaiting-release, releasing, running, exiting (the four active states),
exited, not-launched, lost, unknown, corrupt, finalized. relaunch_safe is True only for
'prepared' and conclusive not-launched evidence: it means the SAME unlaunched work may be
launched (under a NEW attempt id). It is NOT a quiescence flag: it is False for every
launched attempt, including a finalized successful one; read the quiescence of a finalized
attempt from its validated record (executionSuccess, escaped_settled, group fields).
Only a structurally valid native journal ending in a recognized pre-launch abort is
conclusive; once launch is journaled, nothing but an exit record settles the attempt.

Lifecycle record (v4): schema, attemptId, intentSha256, identity, commandPid, commandStart,
termination, stopSource, exitCode, signal, forced, signalsSent, lingering, membersAtExit,
groupEmpty, groupObservation, escapedDescendants, escapedOverflow, escapedSettlement,
unresolvedDescendants, startedAt, endedAt, durationSeconds,
logs{stdout,stderr: {path,size,sha256} | null}, reasons, executionSuccess, limitations,
finalizedAt. escapedDescendants is the HISTORICAL count of distinct (pid, start) identities
the supervisor saw leave the group (a reused pid with another start, or an unknown start, is
its own identity; only exact duplicates collapse); escapedOverflow says one more was seen
after MAX_ESCAPED were retained; escapedSettlement {observationComplete, bootId, observedAt,
identities[{pid, start, status, proof, currentStart}], settled, live, unknown} is the
supervisor's OWN bounded probe of every recorded identity, captured after the owned group
drained and BEFORE exit/v2 closed (durationSeconds includes it), and copied unchanged into
lifecycle/v4 (gone/reused settle an identity; live/unknown never do). finalize never
re-probes, so a later exit, reboot or absence cannot upgrade an incomplete capture.
Synthetic v4 records hold no identity: not-launched is complete and empty, lost is
incomplete (unknown, never settled). An exit/v1 written by an older supervisor still
finalizes to the exact v3 record (no settlement; any escape fails); an exit/v2 without a
settlement is invalid (corrupt), never upgraded. identity is the BOOTSTRAP anchor (its pid is the group leader, never
the declared command). commandPid/commandStart are the declared command's own pid and OS start
identity copied from the raw exit record (commandStart null when the OS could not report it);
they must differ from the anchor pid and equal the journal's command-started pid, and are null
for launch-failed and the synthetic not-launched/lost records (a lost attempt has no settled
exit record to bind a command pid to). Exit-derived fields must equal the retained raw exit.json; membersAtExit is the
supervisor's group count at that record (null = unobserved) and a group found empty later
never replaces it. executionSuccess means only: exit 0, no signal, no forced cleanup, no
lingering or unresolved descendants, escaped_settled(record), zero members at the exit
record, a proven-empty group at finalization and both logs present.

Contract: the caller persists its durable claim before prepare/spawn and persists
Pending.identity before release(); it owns check/effect authorization, pausing and
scheduling; when it is the spawning process it reaps through OwnedProcess. Module-level
finalize(attempt) cannot reap a bootstrap held by another handle: an unreaped exited
bootstrap is a zombie that keeps the group non-empty, so that record reports groupEmpty
false and never executionSuccess. The command
environment is the caller's base environment unchanged except allowlisted selector
deltas and removal of the Git repository selectors; it is never logged. Each selector
directory is bound by device/inode like cwd and declared bindings and rechecked before
exec. Native model,
permission and hook settings are inherited, never set here.

Trust limit: attempt files and process identity are same-user state. They detect
accidents, races, crashes and casual tampering; they are NOT authentic or tamper-proof
against a malicious process running as the same user or as root.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # set before further imports: status/bootstrap entries write no bytecode

import contextlib  # noqa: E402
import errno  # noqa: E402
import functools  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import select  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Mapping  # noqa: E402

SCHEMA_INTENT = 'sdlc-controller/process-intent/v2'
SCHEMA_SPAWN = 'sdlc-controller/process-spawn/v1'
SCHEMA_RELEASE = 'sdlc-controller/process-release/v1'
SCHEMA_EXIT = 'sdlc-controller/process-exit/v2'  # adds escapedOverflow + the supervisor's escapedSettlement
SCHEMA_EXIT_V1 = 'sdlc-controller/process-exit/v1'  # older supervisor: still read, finalizes to v3
SCHEMA_RECORD = 'sdlc-controller/process-lifecycle/v4'  # adds the escaped settlement proof
SCHEMA_RECORD_V3 = 'sdlc-controller/process-lifecycle/v3'  # still read with its exact old meaning
# v2 lifecycle records (no command pid) read as corrupt, never migrated
SCHEMA_STATUS = 'sdlc-controller/process-status/v1'

INTENT = 'intent.json'
STDIN = 'stdin.bin'
SPAWN_LOCK = 'spawn.lock'
SPAWN = 'spawn.json'
RELEASE = 'release.json'
JOURNAL = 'journal.jsonl'
EXIT = 'exit.json'
RECORD = 'lifecycle.json'
STOP = 'stop.request'
STDOUT = 'stdout.log'
STDERR = 'stderr.log'
BOOTSTRAP_LOG = 'bootstrap.log'

# Per-invocation environment deltas: profile/temp selectors only, never credentials.
SELECTOR_KEYS = frozenset({'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'TMPDIR', 'TEMP', 'TMP'})
# Removed so a command (or a Git hook it triggers) cannot be pointed at another repository.
GIT_SELECTORS = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
                 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_COMMON_DIR', 'GIT_NAMESPACE')

STATES = ('prepared', 'awaiting-release', 'releasing', 'running', 'exiting', 'exited',
          'not-launched', 'lost', 'unknown', 'corrupt', 'finalized')
ACTIVE_STATES = frozenset({'awaiting-release', 'releasing', 'running', 'exiting'})
FINALIZABLE_STATES = frozenset({'exited', 'not-launched', 'lost'})
EXIT_TERMINATIONS = ('exited', 'stopped', 'timeout', 'launch-failed')
COMMAND_TERMINATIONS = frozenset({'exited', 'stopped', 'timeout'})  # the declared command ran
TERMINATIONS = EXIT_TERMINATIONS + ('not-launched', 'lost')
STOP_SOURCES = ('file', 'signal')
SIGNALS_SENT = ('SIGTERM', 'SIGKILL')
OBSERVATIONS = ('ok', 'unavailable')
# Fields each journal event carries beyond 'event' and 'at'; the reader rejects anything else.
JOURNAL_FIELDS = {'bootstrap-started': frozenset({'pid'}), 'aborted': frozenset({'reason'}),
                  'launching': frozenset(), 'command-started': frozenset({'pid'}),
                  'launch-failed': frozenset()}
JOURNAL_EVENTS = frozenset(JOURNAL_FIELDS)
# The only sequences the bootstrap emits (every prefix is itself listed), mapped to a phase.
JOURNAL_SEQUENCES = {
    (): 'none',
    ('bootstrap-started',): 'started',
    ('bootstrap-started', 'aborted'): 'aborted',
    ('bootstrap-started', 'launching'): 'launching',
    ('bootstrap-started', 'launching', 'command-started'): 'command-started',
    ('bootstrap-started', 'launching', 'launch-failed'): 'launch-failed',
}
LAUNCHED_PHASES = frozenset({'launching', 'command-started', 'launch-failed'})
ABORT_REASONS = frozenset({
    'release-timeout', 'release-channel-closed', 'release-message-invalid', 'stop-requested',
    'release-record-missing', 'cwd-binding-changed', 'config-binding-changed',
    'executable-binding-changed', 'selector-binding-changed', 'stdin-tampered', 'log-unsafe',
    'intent-tampered',
    'intent-missing', 'intent-invalid', 'record-malformed', 'artifact-unsafe',
    'artifact-too-large', 'io-error'})
REASONS = frozenset({
    'termination-stopped', 'termination-timeout', 'termination-launch-failed',
    'termination-not-launched', 'termination-lost', 'exit-status-missing', 'nonzero-exit',
    'signalled', 'forced', 'lingering-descendants', 'exit-group-not-proven-empty',
    'group-not-proven-empty',
    'group-observation-unavailable', 'escaped-descendants', 'unresolved-descendants',
    'escaped-observation-truncated', 'escaped-descendants-unsettled', 'logs-missing'})

IDENTITY_KEYS = frozenset({'attemptId', 'intentSha256', 'pid', 'pgid', 'bootId',
                           'processStart', 'token'})
INTENT_KEYS = frozenset({'schema', 'attemptId', 'argv', 'cwd', 'executable', 'stdin',
                         'environment', 'bindings', 'timeoutSeconds', 'termGraceSeconds',
                         'lingerSeconds', 'releaseTimeoutSeconds', 'createdAt'})
EXIT_KEYS_V1 = frozenset({'schema', 'attemptId', 'termination', 'stopSource', 'commandPid',
                          'commandStart', 'exitCode', 'signal', 'lingering', 'signalsSent',
                          'forced', 'membersAtRecord', 'groupObservation', 'escaped',
                          'startedAt', 'endedAt', 'durationSeconds'})
EXIT_KEYS = EXIT_KEYS_V1 | {'escapedOverflow', 'escapedSettlement'}
RECORD_KEYS_V3 = frozenset({'schema', 'attemptId', 'intentSha256', 'identity', 'commandPid',
                            'commandStart', 'termination', 'stopSource', 'exitCode', 'signal', 'forced', 'signalsSent',
                            'lingering', 'membersAtExit', 'groupEmpty', 'groupObservation',
                            'escapedDescendants',
                            'unresolvedDescendants', 'startedAt', 'endedAt', 'durationSeconds',
                            'logs', 'reasons', 'executionSuccess', 'limitations', 'finalizedAt'})
RECORD_KEYS = RECORD_KEYS_V3 | {'escapedOverflow', 'escapedSettlement'}
SETTLEMENT_KEYS = frozenset({'observationComplete', 'bootId', 'observedAt', 'identities',
                             'settled', 'live', 'unknown'})
SETTLEMENT_ITEM_KEYS = frozenset({'pid', 'start', 'status', 'proof', 'currentStart'})
# status -> the only proofs that may support it. gone: kernel ESRCH, procfs ENOENT or absence
# from one complete typed snapshot, or a different boot; reused: same boot, both starts known
# and different. live/unknown never settle an identity.
SETTLEMENT_PROOFS = {'gone': frozenset({'esrch', 'absent', 'boot-changed'}),
                     'reused': frozenset({'start-differs'}),
                     'live': frozenset({'start-matches'}),
                     'unknown': frozenset({'boot-unknown', 'query-failed', 'original-start-missing'})}
SETTLED_STATUSES = frozenset({'gone', 'reused'})
LOG_KEYS = frozenset({'path', 'size', 'sha256'})
DIR_BINDING_KEYS = frozenset({'path', 'device', 'inode'})

ATTEMPT_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
BINDING_NAME_RE = re.compile(r'^[a-z][a-z0-9-]{0,63}$')
TOKEN_RE = re.compile(r'^[0-9a-f]{32}$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
SIGNAL_RE = re.compile(r'^SIG[A-Z0-9]{1,16}$')

SYSTEM_PATH = '/bin:/usr/bin:/usr/sbin:/sbin'  # ps/sysctl location is never chosen by caller PATH
SYSTEM_ENV = {'PATH': SYSTEM_PATH, 'LC_ALL': 'C', 'TZ': 'UTC'}
BOOTSTRAP_FLAG = '--bootstrap'
BOOTSTRAP_SCRIPT = os.path.realpath(__file__)
DIR_FLAGS = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | os.O_NOFOLLOW
NEW_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW

DEFAULT_TERM_GRACE = 5.0
DEFAULT_LINGER = 5.0
RELEASE_TIMEOUT_SECONDS = 300.0
MAX_TIMEOUT = 86400.0
MAX_TERM_GRACE = 60.0
MAX_LINGER = 600.0
MAX_RELEASE_TIMEOUT = 3600.0
MAX_DURATION = 2 * MAX_TIMEOUT
POLL_SECONDS = 0.05
SCAN_SECONDS = 0.2
GROUP_PROBE_SECONDS = 2.0
REAP_SECONDS = 2.0
SYSTEM_QUERY_TIMEOUT = 5.0
PUBLISH_RETRIES = 50
MAX_ARGV = 4096
MAX_STDIN_BYTES = 64 << 20
MAX_RECORD_BYTES = 4 << 20
MAX_JOURNAL_BYTES = 4 << 20
MAX_COUNT = 1 << 40
MAX_PID = (1 << 31) - 1  # pid_t bound: a larger JSON int must never reach os.kill/killpg
MAX_ESCAPED = 4096
MAX_TEXT = 512

LIMITATIONS = (
    'ownership is a same-user POSIX process group anchored by the bootstrap; this is not an OS '
    'sandbox or container and promises no containment',
    'attempt files and identities are same-user state; they are not authentic or tamper-proof '
    'against a malicious same-user or root process',
    'descendants that leave the group are observed only while their parent chain is visible to '
    'periodic ps scans; escapes between scans or after reparenting are not observed',
    'the executable, cwd, declared bindings and env selector directories are rechecked by path '
    'and device/inode immediately before exec; a same-user swap inside that window is not '
    'prevented',
    'a clean lifecycle record says the process tree ended cleanly; it is never semantic or '
    'acceptance evidence',
    'recover() assumes no other live controller is concurrently driving the same attempt',
    "escaped-descendant settlement is the supervisor's bounded probe before its exit record "
    'closes (kernel ESRCH, procfs ENOENT or one complete ps snapshot, with boot and start '
    'identity); it proves only that each recorded pid/start identity was gone then, not what '
    'that process did before it exited, and it is never re-probed or upgraded later',
    'start identity has OS resolution (ps lstart is whole seconds): a pid reused within the '
    'same second is indistinguishable and stays live/unknown, never settled',
)


class ProcessError(Exception):
    """Refusal or contract violation carrying a fixed reason code (never untrusted text)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


@dataclass(frozen=True)
class CommandSpec:
    argv: tuple[str, ...]
    cwd: str
    stdin: bytes
    attempt_id: str
    env_selectors: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Recovery:
    """Classification of an attempt. relaunch_safe means only that the SAME unlaunched work
    may be launched again under a NEW attempt id ('prepared' or conclusive not-launched
    evidence). It is never a quiescence flag: it is False for every launched attempt,
    including a finalized successful one."""

    state: str
    relaunch_safe: bool
    identity_status: str | None
    reason: str | None = None


# ---------------------------------------------------------------- typed checks

def _optional(value, check) -> bool:
    return value is None or bool(check(value))


def _seconds_ok(value, high: float, allow_zero: bool) -> bool:
    """A bounded duration; ints are bounded as ints, so a huge JSON int never meets float()."""
    if type(value) is int:
        in_range = 0 <= value <= int(high)
    elif type(value) is float:
        in_range = math.isfinite(value) and 0 <= value <= high
    else:
        return False
    return in_range and (value > 0 or (allow_zero and value == 0))


def _pid_ok(value) -> bool:
    return type(value) is int and 1 < value <= MAX_PID


def _dir_binding_shape_ok(binding) -> bool:
    return (isinstance(binding, dict) and set(binding) == DIR_BINDING_KEYS
            and isinstance(binding['path'], str) and type(binding['device']) is int
            and type(binding['inode']) is int)


def _count_ok(value) -> bool:
    return type(value) is int and 0 <= value <= MAX_COUNT


def _text_ok(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_TEXT


def _exit_code_ok(value) -> bool:
    return type(value) is int and 0 <= value <= 255


def _signal_ok(value) -> bool:
    return isinstance(value, str) and SIGNAL_RE.match(value) is not None


def _signals_ok(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item in SIGNALS_SENT
                                           for item in value)


def _argv_ok(argv) -> bool:
    return (isinstance(argv, (list, tuple)) and 0 < len(argv) <= MAX_ARGV
            and all(isinstance(arg, str) and '\0' not in arg for arg in argv))


# ---------------------------------------------------------------- private directories and files

def _canonical(path, code: str) -> str:
    if not isinstance(path, str) or not path or '\0' in path or not os.path.isabs(path) \
            or os.path.normpath(path) != path or os.path.realpath(path) != path:
        raise ProcessError(code)
    return path


def _safe_ancestors(path: str) -> None:
    """Every ancestor is a real directory owned by root/us and not shared-writable (sticky excepted)."""
    current = os.path.dirname(path)
    while True:
        try:
            info = os.lstat(current)
        except OSError:
            raise ProcessError('root-ancestor-unsafe') from None
        shared = info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()) or shared:
            raise ProcessError('root-ancestor-unsafe')
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def _is_private_dir(info: os.stat_result) -> bool:
    return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077


def _open_root(root: str) -> int:
    _canonical(root, 'root-not-canonical')
    _safe_ancestors(root)
    try:
        before = os.lstat(root)
        fd = os.open(root, DIR_FLAGS)
    except OSError:
        raise ProcessError('root-unavailable') from None
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino) or not _is_private_dir(info):
        os.close(fd)
        raise ProcessError('root-not-private')
    return fd


def _attempt_parts(attempt) -> tuple[str, str]:
    try:
        path = os.fspath(attempt)
    except TypeError:
        raise ProcessError('attempt-not-found') from None
    if not isinstance(path, str):
        raise ProcessError('attempt-not-found')
    root, name = os.path.split(path)
    if not ATTEMPT_ID_RE.match(name):
        raise ProcessError('attempt-not-found')
    return root, name


@contextlib.contextmanager
def _attempt_dir(attempt):
    """Yield a verified fd for a private attempt directory under a safe private root."""
    root, name = _attempt_parts(attempt)
    root_fd = _open_root(root)
    try:
        fd = os.open(name, DIR_FLAGS, dir_fd=root_fd)
    except OSError:
        raise ProcessError('attempt-not-found') from None
    finally:
        os.close(root_fd)
    try:
        if not _is_private_dir(os.fstat(fd)):
            raise ProcessError('attempt-not-private')
        yield fd
    finally:
        os.close(fd)


def _fsync_dir(dir_fd: int) -> None:
    try:
        os.fsync(dir_fd)
    except OSError as err:
        # Some filesystems reject fsync on a directory; the files themselves are synced.
        if err.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte or raise; a short write is continued, a zero-length write is an error."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, 'zero-length write')
        view = view[written:]


def _create_file(dir_fd: int, name: str, data: bytes) -> None:
    """Publish a new synced 0600 file atomically; an existing name is never replaced."""
    temp = f'.{name}.{secrets.token_hex(6)}.tmp'
    fd = os.open(temp, NEW_FILE_FLAGS, 0o600, dir_fd=dir_fd)
    try:
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(temp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    finally:
        os.unlink(temp, dir_fd=dir_fd)
    _fsync_dir(dir_fd)


def _create_json(dir_fd: int, name: str, record: dict) -> None:
    text = json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n'
    _create_file(dir_fd, name, text.encode('utf-8'))


def _open_artifact(dir_fd: int, name: str) -> int | None:
    """Open an owner-only single-link regular file without following links; None if absent."""
    for _attempt in range(PUBLISH_RETRIES):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise ProcessError('artifact-unsafe') from None
        info = os.fstat(fd)
        private = stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() \
            and not info.st_mode & 0o077
        if private and info.st_nlink == 1:
            return fd
        os.close(fd)
        if not private or info.st_nlink != 2:
            raise ProcessError('artifact-unsafe')
        time.sleep(POLL_SECONDS / 2)  # a publish is between linking and unlinking its temp name
    raise ProcessError('artifact-unsafe')


def _read_bytes(dir_fd: int, name: str, limit: int) -> bytes | None:
    fd = _open_artifact(dir_fd, name)
    if fd is None:
        return None
    chunks, total = [], 0
    try:
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ProcessError('artifact-too-large')
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b''.join(chunks)


def _exists(dir_fd: int, name: str) -> bool:
    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise ProcessError('artifact-unsafe')
    return True


def _reject_constant(_name: str):
    raise ValueError('non-finite JSON constant')


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number')
    return value


def _unique_object(pairs):
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate key')
    return dict(pairs)


def _parse_json(data: bytes):
    try:
        return json.loads(data.decode('utf-8'), parse_constant=_reject_constant,
                          parse_float=_finite_float, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        raise ProcessError('record-malformed') from None


def _load_json(dir_fd: int, name: str) -> dict | None:
    data = _read_bytes(dir_fd, name, MAX_RECORD_BYTES)
    if data is None:
        return None
    value = _parse_json(data)
    if not isinstance(value, dict):
        raise ProcessError('record-malformed')
    return value


def _append_journal(dir_fd: int, event: str, **fields) -> None:
    """Append one complete synced line; a failed append leaves a torn tail, read as unknown."""
    line = json.dumps({'event': event, 'at': utc_now(), **fields}, sort_keys=True, allow_nan=False)
    fd = os.open(JOURNAL, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600,
                 dir_fd=dir_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ProcessError('artifact-unsafe')
        _write_all(fd, line.encode('utf-8') + b'\n')
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(dir_fd)


def _journal_event_ok(event) -> bool:
    """Exactly the fields and types the bootstrap emits for this event kind."""
    if not isinstance(event, dict):
        return False
    kind = event.get('event')
    if not isinstance(kind, str) or kind not in JOURNAL_FIELDS:
        return False
    if set(event) != {'event', 'at'} | JOURNAL_FIELDS[kind] or not _text_ok(event['at']):
        return False
    if 'pid' in event and not _pid_ok(event['pid']):
        return False
    return kind != 'aborted' or (isinstance(event['reason'], str)
                                 and event['reason'] in ABORT_REASONS)


def _read_journal(dir_fd: int) -> tuple[list[dict], str]:
    """(events, 'missing' | 'complete' | 'torn' | 'corrupt'); a torn tail is never ignored."""
    data = _read_bytes(dir_fd, JOURNAL, MAX_JOURNAL_BYTES)
    if data is None:
        return [], 'missing'
    lines = data.split(b'\n')
    events = []
    for line in lines[:-1]:
        try:
            event = _parse_json(line)
        except ProcessError:
            return [], 'corrupt'
        if not _journal_event_ok(event):
            return [], 'corrupt'
        events.append(event)
    return events, ('complete' if lines[-1] == b'' else 'torn')


# ---------------------------------------------------------------- process identity (never signals)

def _system_query(argv: list[str]) -> str | None:
    tool = shutil.which(argv[0], path=SYSTEM_PATH)
    if tool is None:
        return None
    try:
        proc = subprocess.run([tool, *argv[1:]], env=SYSTEM_ENV, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=SYSTEM_QUERY_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = proc.stdout.decode('utf-8', 'replace').strip()
    return text if proc.returncode == 0 and text else None


@functools.lru_cache(maxsize=1)
def boot_identity() -> str | None:
    """An identifier that changes on every host boot, or None when it cannot be read."""
    try:
        return 'linux:' + Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        pass  # not Linux or no procfs: fall through to the next OS source
    if sys.platform == 'darwin':
        for key in ('kern.bootsessionuuid', 'kern.boottime'):
            value = _system_query(['sysctl', '-n', key])
            if value:
                return f'darwin:{key}:{value}'
    return None


def _procfs() -> bool:
    return Path('/proc/self/stat').exists()


def process_start(pid: int) -> str | None:
    """Start identity of a live process, or None when it cannot be observed."""
    if _procfs():
        try:
            raw = Path(f'/proc/{pid}/stat').read_bytes()
        except OSError:
            return None
        tail = raw.rsplit(b')', 1)[-1].split()  # starttime is field 22, index 19 after the comm
        return 'ticks:' + tail[19].decode() if len(tail) > 19 else None
    value = _system_query(['ps', '-o', 'lstart=', '-p', str(pid)])
    return 'lstart:' + ' '.join(value.split()) if value else None


def process_command(pid: int) -> list[str] | None:
    if _procfs():
        try:
            raw = Path(f'/proc/{pid}/cmdline').read_bytes()
        except OSError:
            return None
        return [part.decode('utf-8', 'replace') for part in raw.split(b'\0') if part]
    value = _system_query(['ps', '-ww', '-o', 'command=', '-p', str(pid)])
    return value.split() if value else None


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except ProcessLookupError:
        return None
    except PermissionError:
        value = _system_query(['ps', '-o', 'pgid=', '-p', str(pid)])
        return int(value) if value is not None and value.isdigit() else None


def _identity_shape_ok(identity) -> bool:
    if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
        return False
    pid, pgid = identity['pid'], identity['pgid']
    return (_pid_ok(pid) and type(pgid) is int and pgid == pid
            and all(_text_ok(identity[key]) for key in ('attemptId', 'bootId', 'processStart'))
            and isinstance(identity['token'], str) and TOKEN_RE.match(identity['token']) is not None
            and isinstance(identity['intentSha256'], str)
            and SHA256_RE.match(identity['intentSha256']) is not None)


def _identity_ok(identity, attempt_id: str, intent_sha: str) -> bool:
    return _identity_shape_ok(identity) and identity['attemptId'] == attempt_id \
        and identity['intentSha256'] == intent_sha


def identify(identity) -> str:
    """'owned' only when boot, PID, process start, token and group all match the bootstrap.

    'not-owned': the recorded bootstrap is provably no longer that process. 'unknown': it
    could not be proven either way; callers must neither signal nor treat it as finished.
    """
    if not _identity_shape_ok(identity):
        return 'unknown'
    current_boot = boot_identity()
    if current_boot is None:
        return 'unknown'
    pid = identity['pid']
    if current_boot != identity['bootId'] or not _pid_exists(pid):
        return 'not-owned'
    start = process_start(pid)
    if start is None:
        return 'unknown' if _pid_exists(pid) else 'not-owned'
    if start != identity['processStart']:
        return 'not-owned'
    command = process_command(pid)
    if command is None:
        return 'unknown' if _pid_exists(pid) else 'not-owned'
    if identity['token'] not in command:
        return 'not-owned'
    group = _process_group(pid)
    if group is None:
        return 'unknown' if _pid_exists(pid) else 'not-owned'
    return 'owned' if group == identity['pgid'] else 'not-owned'


def _capture_identity(intent: dict, intent_sha: str, pid: int, token: str) -> dict | None:
    boot, start, group = boot_identity(), process_start(pid), _process_group(pid)
    command = process_command(pid)
    if boot is None or start is None or group != pid or command is None or token not in command:
        return None
    return {'attemptId': intent['attemptId'], 'intentSha256': intent_sha, 'pid': pid,
            'pgid': group, 'bootId': boot, 'processStart': start, 'token': token}


def _group_empty(pgid: int) -> bool:
    """True only on ESRCH: no group with this id exists, so ours is empty."""
    deadline = time.monotonic() + GROUP_PROBE_SECONDS
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass  # zombie-only or foreign group: not proof of emptiness; keep probing
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)


def _escaped_alive(item: dict) -> bool:
    """v3 records only (exit/v1): the legacy alive count, kept with its exact old meaning."""
    current = process_start(item['pid'])
    if current is None:
        return _pid_exists(item['pid'])
    return item['start'] is None or current == item['start']


def _presence(pid: int) -> str:
    """'absent' only on kernel ESRCH. Signal 0 is the permission/existence check: nothing is
    delivered, so no process outside the owned group is ever signalled."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return 'absent'
    except PermissionError:
        return 'present'
    except OSError:
        return 'unknown'
    return 'present'


def _procfs_start(pid: int) -> tuple[str, str | None]:
    """('ok', start) | ('absent', None) on ENOENT/ESRCH | ('unknown', None) otherwise."""
    try:
        raw = Path(f'/proc/{pid}/stat').read_bytes()
    except (FileNotFoundError, ProcessLookupError):
        return 'absent', None
    except OSError:
        return 'unknown', None
    tail = raw.rsplit(b')', 1)[-1].split()
    if len(tail) > 19 and tail[19].isdigit():
        return 'ok', 'ticks:' + tail[19].decode()
    return 'unknown', None


def _start_table() -> dict[int, str] | None:
    """One complete typed ps snapshot of every process start, or None. A missing tool, a
    nonzero exit, timeout, empty output, any malformed or duplicate row, or a table that
    omits this very process (truncated) is never read as anyone's absence."""
    text = _system_query(['ps', '-A', '-o', 'pid=', '-o', 'lstart='])
    if text is None:
        return None
    table: dict[int, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 6 or not (parts[0].isascii() and parts[0].isdigit()):
            return None
        pid = int(parts[0])
        if pid in table:
            return None
        table[pid] = 'lstart:' + ' '.join(parts[1:])  # the same form process_start() records
    return table if os.getpid() in table else None


def _start_lookup():
    """pid -> ('ok', start) | ('absent', None) | ('unknown', None) for one settlement round;
    without procfs one snapshot is taken lazily and shared by every identity."""
    if _procfs():
        return _procfs_start
    snapshot: list[dict[int, str] | None] = []

    def lookup(pid: int) -> tuple[str, str | None]:
        if not snapshot:
            snapshot.append(_start_table())
        table = snapshot[0]
        if table is None:
            return 'unknown', None
        start = table.get(pid)
        return ('absent', None) if start is None else ('ok', start)
    return lookup


def _probe_escaped(item: dict, anchor_boot: str | None, current_boot: str | None, lookup) -> dict:
    """Typed settlement proof for one recorded escaped identity; observes, never signals."""
    pid, start = item['pid'], item['start']

    def proof(status: str, code: str, current: str | None = None) -> dict:
        return {'pid': pid, 'start': start, 'status': status, 'proof': code, 'currentStart': current}
    if current_boot is not None and anchor_boot is not None and current_boot != anchor_boot:
        return proof('gone', 'boot-changed')
    if _presence(pid) == 'absent':
        return proof('gone', 'esrch')
    if current_boot is None or anchor_boot is None:
        return proof('unknown', 'boot-unknown')
    found, current = lookup(pid)
    if found == 'absent':
        return proof('gone', 'absent')
    if found != 'ok':
        return proof('unknown', 'query-failed')
    if start is None:
        return proof('unknown', 'original-start-missing', current)
    if current != start:
        return proof('reused', 'start-differs', current)
    return proof('live', 'start-matches', current)


def _escaped_settlement(items: list[dict], anchor_boot: str | None,
                        observation_complete: bool) -> dict:
    """One probe round over EVERY recorded identity (the full history is kept)."""
    current_boot = boot_identity()
    lookup = _start_lookup()
    identities = [_probe_escaped(item, anchor_boot, current_boot, lookup) for item in items]
    statuses = [entry['status'] for entry in identities]
    return {'observationComplete': observation_complete, 'bootId': current_boot,
            'observedAt': utc_now(), 'identities': identities,
            'settled': sum(status in SETTLED_STATUSES for status in statuses),
            'live': statuses.count('live'), 'unknown': statuses.count('unknown')}


def _settle_escaped(items: list[dict], anchor_boot: str | None, observation_complete: bool,
                    drain_seconds: float, interrupted=None) -> dict:
    """Re-probe while any identity is unsettled, for at most drain_seconds (one round when
    it is 0 or interrupted() is true); the last round is recorded as observed, never upgraded."""
    deadline = time.monotonic() + drain_seconds
    while True:
        settlement = _escaped_settlement(items, anchor_boot, observation_complete)
        if not (settlement['live'] or settlement['unknown']) or time.monotonic() >= deadline \
                or (interrupted is not None and interrupted()):
            return settlement
        time.sleep(SCAN_SECONDS)


# ---------------------------------------------------------------- prepare

def _executable_binding(path) -> dict:
    if not isinstance(path, str) or '\0' in path or not os.path.isabs(path):
        raise ProcessError('executable-not-absolute')
    real = os.path.realpath(path)
    try:
        info = os.stat(real)
    except OSError:
        raise ProcessError('executable-unavailable') from None
    if not stat.S_ISREG(info.st_mode) or not os.access(real, os.X_OK):
        raise ProcessError('executable-not-executable')
    if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
        raise ProcessError('executable-unsafe')
    return {'path': path, 'realpath': real, 'device': info.st_dev, 'inode': info.st_ino,
            'size': info.st_size, 'mtimeNs': info.st_mtime_ns, 'mode': info.st_mode,
            'uid': info.st_uid}


def _dir_binding(path, code: str) -> dict:
    _canonical(path, code)
    try:
        info = os.stat(path)
    except OSError:
        raise ProcessError(code) from None
    if not stat.S_ISDIR(info.st_mode):
        raise ProcessError(code)
    return {'path': path, 'device': info.st_dev, 'inode': info.st_ino}


def _selector_delta(selectors) -> dict:
    if not isinstance(selectors, Mapping):
        raise ProcessError('invalid-env-selectors')
    delta = {}
    for key, value in selectors.items():
        if not isinstance(key, str) or key not in SELECTOR_KEYS:
            raise ProcessError('env-selector-not-allowed')
        # Bound like any declared directory, so a rename/symlink swap is caught before exec.
        delta[key] = _dir_binding(value, 'env-selector-not-canonical')
    return delta


def _declared_bindings(bindings) -> dict:
    if bindings is None:
        return {}
    if not isinstance(bindings, Mapping):
        raise ProcessError('invalid-bindings')
    declared = {}
    for name, path in bindings.items():
        if not isinstance(name, str) or not BINDING_NAME_RE.match(name):
            raise ProcessError('invalid-binding-name')
        declared[name] = _dir_binding(path, 'binding-not-canonical')
    return declared


def _validate_spec(spec) -> None:
    if not isinstance(spec, CommandSpec):
        raise ProcessError('invalid-spec')
    if not isinstance(spec.attempt_id, str) or not ATTEMPT_ID_RE.match(spec.attempt_id):
        raise ProcessError('invalid-attempt-id')
    if not _argv_ok(spec.argv):
        raise ProcessError('invalid-argv')
    if not isinstance(spec.stdin, bytes) or len(spec.stdin) > MAX_STDIN_BYTES:
        raise ProcessError('invalid-stdin')


def _overlaps(first: str, second: str) -> bool:
    return os.path.commonpath([first, second]) in (first, second)


def prepare(attempts_root, spec: CommandSpec, timeout_seconds,
            term_grace_seconds=DEFAULT_TERM_GRACE, linger_seconds=DEFAULT_LINGER,
            bindings: Mapping[str, str] | None = None) -> Path:
    """Create a NEW private attempt; persist stdin and the immutable intent before any spawn."""
    _validate_spec(spec)
    if not _seconds_ok(timeout_seconds, MAX_TIMEOUT, False):
        raise ProcessError('invalid-timeout')
    if not _seconds_ok(term_grace_seconds, MAX_TERM_GRACE, False):
        raise ProcessError('invalid-term-grace')
    if not _seconds_ok(linger_seconds, MAX_LINGER, True):
        raise ProcessError('invalid-linger')
    executable = _executable_binding(spec.argv[0])
    cwd = _dir_binding(spec.cwd, 'cwd-not-canonical')
    selectors = _selector_delta(spec.env_selectors)
    declared = _declared_bindings(bindings)
    root = _canonical(attempts_root if isinstance(attempts_root, str) else
                      os.fspath(attempts_root) if isinstance(attempts_root, os.PathLike) else None,
                      'root-not-canonical')
    if _overlaps(root, cwd['path']):
        raise ProcessError('attempts-root-overlaps-cwd')
    root_fd = _open_root(root)
    try:
        try:
            os.mkdir(spec.attempt_id, 0o700, dir_fd=root_fd)
        except FileExistsError:
            raise ProcessError('attempt-exists') from None
        _fsync_dir(root_fd)
        attempt_fd = os.open(spec.attempt_id, DIR_FLAGS, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    try:
        if not _is_private_dir(os.fstat(attempt_fd)):
            raise ProcessError('attempt-not-private')
        _create_file(attempt_fd, STDIN, spec.stdin)
        _create_json(attempt_fd, INTENT, {
            'schema': SCHEMA_INTENT, 'attemptId': spec.attempt_id, 'argv': list(spec.argv),
            'cwd': cwd, 'executable': executable,
            'stdin': {'file': STDIN, 'bytes': len(spec.stdin),
                      'sha256': hashlib.sha256(spec.stdin).hexdigest()},
            'environment': {'selectors': selectors, 'unset': list(GIT_SELECTORS)},
            'bindings': declared, 'timeoutSeconds': float(timeout_seconds),
            'termGraceSeconds': float(term_grace_seconds), 'lingerSeconds': float(linger_seconds),
            'releaseTimeoutSeconds': RELEASE_TIMEOUT_SECONDS, 'createdAt': utc_now()})
    finally:
        os.close(attempt_fd)
    return Path(root, spec.attempt_id)


def _intent_ok(intent, name: str) -> bool:
    try:
        environment, stdin_ref = intent['environment'], intent['stdin']
        return (set(intent) == INTENT_KEYS and intent['schema'] == SCHEMA_INTENT
                and intent['attemptId'] == name and _argv_ok(intent['argv'])
                and intent['argv'][0] == intent['executable']['path']
                and _dir_binding_shape_ok(intent['cwd'])
                and set(stdin_ref) == {'file', 'bytes', 'sha256'} and _count_ok(stdin_ref['bytes'])
                and isinstance(stdin_ref['sha256'], str)
                and SHA256_RE.match(stdin_ref['sha256']) is not None
                and set(environment) == {'selectors', 'unset'}
                and isinstance(environment['selectors'], dict)
                and set(environment['selectors']) <= SELECTOR_KEYS
                and all(_dir_binding_shape_ok(value) for value in environment['selectors'].values())
                and environment['unset'] == list(GIT_SELECTORS)
                and isinstance(intent['bindings'], dict)
                and all(_dir_binding_shape_ok(binding) for binding in intent['bindings'].values())
                and _seconds_ok(intent['timeoutSeconds'], MAX_TIMEOUT, False)
                and _seconds_ok(intent['termGraceSeconds'], MAX_TERM_GRACE, False)
                and _seconds_ok(intent['lingerSeconds'], MAX_LINGER, True)
                and _seconds_ok(intent['releaseTimeoutSeconds'], MAX_RELEASE_TIMEOUT, False))
    except (KeyError, TypeError, AttributeError, IndexError):
        return False


def _load_intent(dir_fd: int, name: str) -> tuple[dict, str]:
    data = _read_bytes(dir_fd, INTENT, MAX_RECORD_BYTES)
    if data is None:
        raise ProcessError('intent-missing')
    intent = _parse_json(data)
    if not _intent_ok(intent, name):
        raise ProcessError('intent-invalid')
    return intent, hashlib.sha256(data).hexdigest()


def _spawn_identity(spawn_record: dict, intent: dict, intent_sha: str) -> dict:
    if set(spawn_record) != {'schema', 'identity', 'spawnedAt'} \
            or spawn_record['schema'] != SCHEMA_SPAWN:
        raise ProcessError('spawn-record-invalid')
    identity = spawn_record['identity']
    if not _identity_ok(identity, intent['attemptId'], intent_sha):
        raise ProcessError('identity-invalid')
    return identity


# ---------------------------------------------------------------- spawn / release / handles

def _launch_environment(base: Mapping[str, str], intent: dict) -> dict:
    env = {key: value for key, value in base.items() if key not in GIT_SELECTORS}
    env.update({key: binding['path']
                for key, binding in intent['environment']['selectors'].items()})
    return env


def _bounded_wait(popen: subprocess.Popen) -> None:
    # A bootstrap still alive after the bound is reported by recover(), never assumed gone.
    with contextlib.suppress(subprocess.TimeoutExpired):
        popen.wait(timeout=REAP_SECONDS)


def _start_bootstrap(dir_fd: int, attempt_path: str, env: dict, token: str, intent_sha: str):
    try:
        log_fd = os.open(BOOTSTRAP_LOG, NEW_FILE_FLAGS, 0o600, dir_fd=dir_fd)
    except OSError:
        raise ProcessError('bootstrap-log-unsafe') from None
    read_fd, write_fd = os.pipe()  # the write end is non-inheritable and never passed on
    try:
        popen = subprocess.Popen(
            [sys.executable, '-I', '-B', BOOTSTRAP_SCRIPT, BOOTSTRAP_FLAG, attempt_path,
             str(read_fd), token, intent_sha],
            cwd='/', env=env, stdin=subprocess.DEVNULL, stdout=log_fd, stderr=log_fd,
            pass_fds=(read_fd,), start_new_session=True, close_fds=True)
    except OSError:
        os.close(write_fd)
        raise ProcessError('bootstrap-launch-failed') from None
    finally:
        os.close(read_fd)
        os.close(log_fd)
    return popen, write_fd


def spawn(attempt, environment: Mapping[str, str] | None = None) -> 'Pending':
    """Start the anchored bootstrap for a persisted intent; it launches nothing until release.

    If this controller dies before release, the pipe's only writer closes and the
    bootstrap exits without launching the command.
    """
    root, name = _attempt_parts(attempt)
    attempt_path = os.path.join(root, name)
    with _attempt_dir(attempt_path) as dir_fd:
        intent, intent_sha = _load_intent(dir_fd, name)
        try:
            os.close(os.open(SPAWN_LOCK, NEW_FILE_FLAGS, 0o600, dir_fd=dir_fd))
        except FileExistsError:
            raise ProcessError('attempt-already-spawned') from None
        _fsync_dir(dir_fd)
        env = _launch_environment(os.environ if environment is None else environment, intent)
        token = secrets.token_hex(16)
        popen, release_fd = _start_bootstrap(dir_fd, attempt_path, env, token, intent_sha)
        identity = _capture_identity(intent, intent_sha, popen.pid, token)
        try:
            if identity is None:
                raise ProcessError('identity-unavailable')
            _create_json(dir_fd, SPAWN, {'schema': SCHEMA_SPAWN, 'identity': identity,
                                         'spawnedAt': utc_now()})
        except ProcessError:
            os.close(release_fd)
            _bounded_wait(popen)
            raise
        except OSError:
            os.close(release_fd)
            _bounded_wait(popen)
            raise ProcessError('spawn-record-failed') from None
    return Pending(Path(attempt_path), identity, popen, release_fd)


class OwnedProcess:
    """Pollable handle on a released attempt; holds no lock and never blocks long."""

    def __init__(self, attempt: Path, identity: dict, popen: subprocess.Popen | None = None):
        self.attempt = attempt
        self.identity = dict(identity)
        self._popen = popen

    @classmethod
    def attach(cls, attempt) -> 'OwnedProcess':
        root, name = _attempt_parts(attempt)
        attempt_path = os.path.join(root, name)
        with _attempt_dir(attempt_path) as dir_fd:
            intent, intent_sha = _load_intent(dir_fd, name)
            spawn_record = _load_json(dir_fd, SPAWN)
        if spawn_record is None:
            raise ProcessError('spawn-record-missing')
        return cls(Path(attempt_path), _spawn_identity(spawn_record, intent, intent_sha))

    def _reap(self) -> bool:
        """Bounded reap of this handle's own bootstrap; True while it remains unreaped.

        Only the Popen this process spawned is waited on: no pid is guessed or signalled.
        """
        if self._popen is None or self._popen.poll() is not None:
            return False
        with _attempt_dir(self.attempt) as dir_fd:
            settled = _exists(dir_fd, EXIT)
        if settled:
            _bounded_wait(self._popen)  # the bootstrap exits right after its exit record
        return self._popen.returncode is None

    def poll(self) -> Recovery:
        self._reap()
        recovery = recover(self.attempt)
        if recovery.state == 'exited':
            self._reap()  # exit published after the first reap: collect the zombie now
        return recovery

    def request_stop(self) -> str:
        return request_stop(self.attempt)

    def finalize(self) -> dict:
        """Finalize only once this handle's own bootstrap is reaped (or was never ours).

        A live bootstrap may publish its exit record and leave a zombie in the group between
        any check and classification, so an unreaped one is refused, never recorded.
        """
        state = self.poll().state
        if self._reap():
            if state == 'finalized':
                raise ProcessError('already-finalized')
            raise ProcessError('bootstrap-unreaped' if state in FINALIZABLE_STATES
                               else f'attempt-{state}')
        return finalize(self.attempt)


class Pending:
    """A spawned bootstrap that will not start the command until release()."""

    def __init__(self, attempt: Path, identity: dict, popen: subprocess.Popen, release_fd: int):
        self.attempt = attempt
        self._identity = identity
        self._popen = popen
        self._release_fd: int | None = release_fd

    @property
    def identity(self) -> dict:
        return dict(self._identity)

    def release(self) -> OwnedProcess:
        """Call only after the identity is durably persisted; release intent is synced first."""
        if self._release_fd is None:
            raise ProcessError('release-channel-closed')
        fd, self._release_fd = self._release_fd, None
        try:
            if identify(self._identity) != 'owned':
                raise ProcessError('bootstrap-not-owned')
            with _attempt_dir(self.attempt) as dir_fd:
                if _exists(dir_fd, STOP):
                    raise ProcessError('stop-requested')
                _create_json(dir_fd, RELEASE, {'schema': SCHEMA_RELEASE,
                                               'attemptId': self._identity['attemptId'],
                                               'releasedAt': utc_now()})
            _write_all(fd, b'RELEASE ' + self._identity['token'].encode('ascii') + b'\n')
        except BrokenPipeError:
            raise ProcessError('bootstrap-gone') from None
        except OSError:
            raise ProcessError('release-failed') from None
        finally:
            os.close(fd)
        return OwnedProcess(self.attempt, self._identity, self._popen)

    def abort(self) -> None:
        """Close the release channel; the bootstrap exits without launching anything."""
        if self._release_fd is not None:
            os.close(self._release_fd)
            self._release_fd = None
        _bounded_wait(self._popen)


def request_stop(attempt) -> str:
    """Durably publish STOP before returning; report whether an owned bootstrap will honor it.

    Returns 'owned', 'not-owned', 'unknown' or 'not-spawned'. Nothing is signalled here.
    """
    root, name = _attempt_parts(attempt)
    with _attempt_dir(os.path.join(root, name)) as dir_fd:
        if not _exists(dir_fd, STOP):
            # A concurrent request may publish the same durable marker first; either one stands.
            with contextlib.suppress(FileExistsError):
                _create_file(dir_fd, STOP, utc_now().encode('ascii') + b'\n')
        intent, intent_sha = _load_intent(dir_fd, name)
        spawn_record = _load_json(dir_fd, SPAWN)
    if spawn_record is None:
        return 'not-spawned'
    return identify(_spawn_identity(spawn_record, intent, intent_sha))


# ---------------------------------------------------------------- classification

@dataclass(frozen=True)
class _Facts:
    recovery: Recovery
    intent: dict | None = None
    intent_sha: str | None = None
    identity: dict | None = None
    exit_record: dict | None = None
    record: dict | None = None


def _journal_phase(events: list[dict], identity: dict) -> str | None:
    """Phase of a native event sequence, or None when order or pids contradict the bootstrap."""
    phase = JOURNAL_SEQUENCES.get(tuple(event['event'] for event in events))
    if phase is None or (events and events[0]['pid'] != identity['pid']):
        return None
    if phase == 'command-started' and events[-1]['pid'] == identity['pid']:
        return None
    return phase


def _exit_matches_journal(exit_record: dict, phase: str, events: list[dict]) -> bool:
    if exit_record['termination'] == 'launch-failed':
        return phase == 'launch-failed'
    return phase == 'command-started' and events[-1]['pid'] == exit_record['commandPid']


def _launch_state(identity: dict, status: str, release_sent: bool, events: list[dict],
                  phase: str, journal: str) -> Recovery:
    """Classify an attempt with no exit record from a structurally valid journal phase."""
    launched = phase in LAUNCHED_PHASES
    if not release_sent:
        # release.json is synced before the release message, so no launch can have happened.
        if launched:
            return Recovery('corrupt', False, status, 'launch-without-release')
        if status == 'owned':
            return Recovery('awaiting-release', False, status)
        if status == 'not-owned':
            return Recovery('not-launched', True, status, 'never-released')
        return Recovery('unknown', False, status, 'ownership-unknown')
    if journal != 'complete':
        return Recovery('unknown', False, status, f'journal-{journal}')
    if launched:
        # Launch was journaled: only an exit record settles it, never a retry.
        if status == 'owned':
            return Recovery('running', False, status)
        if status == 'not-owned':
            return Recovery('lost', False, status, 'supervisor-lost')
        return Recovery('unknown', False, status, 'ownership-unknown')
    if status == 'owned':
        return Recovery('releasing', False, status)
    if status == 'not-owned' and phase == 'aborted':
        if not _group_empty(identity['pgid']):
            return Recovery('unknown', False, status, 'group-not-proven-empty')
        # The reader admitted only a recognized pre-launch reason right after bootstrap-started.
        return Recovery('not-launched', True, status, events[-1]['reason'])
    return Recovery('unknown', False, status, 'release-unresolved')


def _classify_checked(dir_fd: int, attempt_path: str) -> _Facts:
    intent, intent_sha = _load_intent(dir_fd, os.path.basename(attempt_path))
    known = {'intent': intent, 'intent_sha': intent_sha}
    record = _load_json(dir_fd, RECORD)
    if record is not None:
        problem = _record_problem(dir_fd, attempt_path, record, intent, intent_sha)
        if problem is not None:
            return _Facts(Recovery('corrupt', False, None, problem), **known)
        safe = record['termination'] == 'not-launched'
        return _Facts(Recovery('finalized', safe, None), record=record, **known)
    if not _exists(dir_fd, SPAWN_LOCK):
        if any(_exists(dir_fd, name) for name in (SPAWN, RELEASE, JOURNAL, EXIT)):
            return _Facts(Recovery('corrupt', False, None, 'spawn-lock-missing'), **known)
        return _Facts(Recovery('prepared', True, None), **known)
    spawn_record = _load_json(dir_fd, SPAWN)
    release_sent = _exists(dir_fd, RELEASE)
    if spawn_record is None:
        if release_sent:
            return _Facts(Recovery('corrupt', False, None, 'spawn-record-missing'), **known)
        # No Pending was ever returned, so release was unreachable.
        return _Facts(Recovery('not-launched', True, None, 'spawn-incomplete'), **known)
    identity = _spawn_identity(spawn_record, intent, intent_sha)
    status = identify(identity)
    # Identity first: a bootstrap proven gone cannot append afterwards. The exit record is
    # read before the journal because it is published only after the final append.
    exit_record = _load_json(dir_fd, EXIT)
    events, journal = _read_journal(dir_fd)
    if journal == 'torn' and status == 'owned' and exit_record is None:
        time.sleep(POLL_SECONDS)  # a live bootstrap may be mid-append
        events, journal = _read_journal(dir_fd)
    phase = None if journal == 'corrupt' else _journal_phase(events, identity)
    known['identity'] = identity
    if exit_record is not None and not _exit_ok(exit_record, intent['attemptId']):
        return _Facts(Recovery('corrupt', False, status, 'exit-record-invalid'), **known)
    if phase is None:
        return _Facts(Recovery('corrupt', False, status, 'journal-corrupt'), **known)
    if exit_record is not None:
        if journal != 'complete' or not _exit_matches_journal(exit_record, phase, events):
            return _Facts(Recovery('corrupt', False, status, 'exit-journal-mismatch'), **known)
        state = 'exiting' if status == 'owned' else 'exited'
        return _Facts(Recovery(state, False, status), exit_record=exit_record, **known)
    return _Facts(_launch_state(identity, status, release_sent, events, phase, journal), **known)


def _classify(dir_fd: int, attempt_path: str) -> _Facts:
    try:
        return _classify_checked(dir_fd, attempt_path)
    except ProcessError as err:
        return _Facts(Recovery('corrupt', False, None, err.code))
    except OSError:
        return _Facts(Recovery('unknown', False, None, 'io-error'))
    except (OverflowError, ValueError, TypeError, KeyError):
        # Fail closed on a malformed value the typed checks did not anticipate; never retryable.
        return _Facts(Recovery('corrupt', False, None, 'record-unclassifiable'))


def recover(attempt) -> Recovery:
    """Classify an attempt from durable files and OS evidence; never signals or writes."""
    root, name = _attempt_parts(attempt)
    attempt_path = os.path.join(root, name)
    with _attempt_dir(attempt_path) as dir_fd:
        return _classify(dir_fd, attempt_path).recovery


def read_status(attempt) -> dict:
    """Read-only status; the validated lifecycle record is included once finalized."""
    root, name = _attempt_parts(attempt)
    attempt_path = os.path.join(root, name)
    with _attempt_dir(attempt_path) as dir_fd:
        facts = _classify(dir_fd, attempt_path)
    recovery = facts.recovery
    return {'schema': SCHEMA_STATUS, 'attemptId': name, 'state': recovery.state,
            'relaunchSafe': recovery.relaunch_safe, 'identityStatus': recovery.identity_status,
            'reason': recovery.reason,
            'record': facts.record if recovery.state == 'finalized' else None}


# ---------------------------------------------------------------- records

def _escaped_item_ok(item) -> bool:
    return (isinstance(item, dict) and set(item) == {'pid', 'start'}
            and _pid_ok(item['pid']) and _optional(item['start'], _text_ok))


def _overflow_ok(record: dict) -> bool:
    """exit/v2: overflow is set only once the retained history is full."""
    overflow = record['escapedOverflow']
    return type(overflow) is bool and (not overflow or len(record['escaped']) == MAX_ESCAPED)


def _exit_consistent(record: dict) -> bool:
    """Cross-field facts the supervisor always emits; types are already checked."""
    if record['termination'] == 'launch-failed':
        return (record['stopSource'] is None and record['commandStart'] is None
                and record['exitCode'] is None and record['signal'] is None
                and record['lingering'] is False and record['signalsSent'] == []
                and record['forced'] is False and record['membersAtRecord'] == 0
                and record['groupObservation'] == 'ok' and record['escaped'] == [])
    signals, members = record['signalsSent'], record['membersAtRecord']
    status_missing = record['exitCode'] is None and record['signal'] is None
    # SIGKILL follows whenever the command or any group member was not proven gone.
    needs_kill = status_missing or members is None or members > 0
    terminated = record['termination'] != 'exited' or record['lingering']
    return ((record['stopSource'] is not None) == (record['termination'] == 'stopped')
            and (record['exitCode'] is None or record['signal'] is None)
            and not (record['termination'] == 'exited' and status_missing)
            and (not record['lingering'] or record['termination'] == 'exited')
            and signals in ([], ['SIGTERM'], ['SIGTERM', 'SIGKILL'])
            and ('SIGTERM' in signals) == terminated
            and ('SIGKILL' in signals) == needs_kill
            and (members is not None or record['groupObservation'] == 'unavailable'))


def _exit_ok(record: dict, attempt_id: str) -> bool:
    """An exit/v2 (current supervisor: unique escaped identities and its own pre-closure
    settlement of exactly that history) or an exit/v1 (older supervisor, no overflow flag
    and no settlement)."""
    try:
        schema = record['schema']
        keys = EXIT_KEYS if schema == SCHEMA_EXIT else EXIT_KEYS_V1 if schema == SCHEMA_EXIT_V1 else None
        return (keys is not None and set(record) == keys
                and record['attemptId'] == attempt_id
                and record['termination'] in EXIT_TERMINATIONS
                and _optional(record['stopSource'], lambda value: value in STOP_SOURCES)
                and _optional(record['commandPid'], _pid_ok)
                and (record['commandPid'] is None) == (record['termination'] == 'launch-failed')
                and _optional(record['commandStart'], _text_ok)
                and _optional(record['exitCode'], _exit_code_ok)
                and _optional(record['signal'], _signal_ok)
                and type(record['lingering']) is bool and type(record['forced']) is bool
                and _signals_ok(record['signalsSent'])
                and record['forced'] == bool(record['signalsSent'])
                and _optional(record['membersAtRecord'], _count_ok)
                and record['groupObservation'] in OBSERVATIONS
                and isinstance(record['escaped'], list) and len(record['escaped']) <= MAX_ESCAPED
                and all(_escaped_item_ok(item) for item in record['escaped'])
                and (schema == SCHEMA_EXIT_V1 or (_overflow_ok(record)
                                                  and _escaped_unique(record['escaped'])
                                                  and _exit_settlement_ok(record)))
                and _text_ok(record['startedAt']) and _text_ok(record['endedAt'])
                and _seconds_ok(record['durationSeconds'], MAX_DURATION, True)
                and _exit_consistent(record))
    except (KeyError, TypeError):
        return False


def _settlement_item_ok(item, anchor_boot: str | None, settle_boot: str | None) -> bool:
    """One identity's proof is typed and agrees with its status, starts and boot context."""
    if not isinstance(item, dict) or set(item) != SETTLEMENT_ITEM_KEYS:
        return False
    if not _escaped_item_ok({'pid': item['pid'], 'start': item['start']}):
        return False
    status, code, start, current = item['status'], item['proof'], item['start'], item['currentStart']
    if not isinstance(status, str) or not isinstance(code, str) \
            or code not in SETTLEMENT_PROOFS.get(status, ()) or not _optional(current, _text_ok):
        return False
    same_boot = anchor_boot is not None and settle_boot == anchor_boot
    if code == 'boot-changed':
        return (current is None and anchor_boot is not None and settle_boot is not None
                and settle_boot != anchor_boot)
    if code == 'esrch':
        return current is None and (settle_boot is None or anchor_boot is None or same_boot)
    if code == 'boot-unknown':
        return current is None and (settle_boot is None or anchor_boot is None)
    if not same_boot:
        return False
    if code in ('absent', 'query-failed'):
        return current is None
    if code == 'original-start-missing':
        return start is None and current is not None
    if code == 'start-differs':
        return start is not None and current is not None and current != start
    return start is not None and current == start  # start-matches


def _settlement_counts(settlement, count: int, complete: bool,
                       anchor_boot: str | None) -> tuple[int, int, int] | None:
    """(settled, live, unknown) of a typed settlement holding exactly `count` proofs whose
    observation status and counts agree with its own proofs; None otherwise."""
    if not isinstance(settlement, dict) or set(settlement) != SETTLEMENT_KEYS:
        return None
    items, settle_boot = settlement['identities'], settlement['bootId']
    if not isinstance(items, list) or len(items) != count \
            or not _optional(settle_boot, _text_ok) or not _text_ok(settlement['observedAt']):
        return None
    if settlement['observationComplete'] is not complete:
        return None
    if not all(_settlement_item_ok(item, anchor_boot, settle_boot) for item in items):
        return None
    statuses = [item['status'] for item in items]
    counts = (sum(status in SETTLED_STATUSES for status in statuses), statuses.count('live'),
              statuses.count('unknown'))
    if not all(_count_ok(settlement[key]) for key in ('settled', 'live', 'unknown')) \
            or (settlement['settled'], settlement['live'], settlement['unknown']) != counts:
        return None
    return counts


def _escaped_unique(items: list[dict]) -> bool:
    """exit/v2 retains each observed (pid, start) identity once; a repeat is never emitted."""
    return len({(item['pid'], item['start']) for item in items}) == len(items)


def _exit_settlement_ok(record: dict) -> bool:
    """exit/v2: the supervisor's own settlement of exactly its escaped history, in order. It
    probed inside its own boot, so its anchor is its own boot identity (never boot-changed)."""
    settlement = record['escapedSettlement']
    if not isinstance(settlement, dict):
        return False
    complete = record['groupObservation'] == 'ok' and record['escapedOverflow'] is False
    if _settlement_counts(settlement, len(record['escaped']), complete,
                          settlement.get('bootId')) is None:
        return False
    pairs = [(item['pid'], item['start']) for item in settlement['identities']]
    return pairs == [(item['pid'], item['start']) for item in record['escaped']]


def _settlement_ok(record: Mapping) -> bool:
    """A v4 settlement is typed, keeps one proof per historical identity, and its counts,
    observation status and unresolved total agree with its proofs and the record. An
    exit-backed capture was taken inside the anchor's boot; a synthetic one holds nothing."""
    settlement, identity = record['escapedSettlement'], record['identity']
    anchor_boot = identity.get('bootId') if isinstance(identity, dict) else None
    complete = record['groupObservation'] == 'ok' and record['escapedOverflow'] is False
    counts = _settlement_counts(settlement, record['escapedDescendants'], complete, anchor_boot)
    if counts is None:
        return False
    settle_boot = settlement['bootId']
    if record['termination'] in EXIT_TERMINATIONS:
        if None not in (anchor_boot, settle_boot) and settle_boot != anchor_boot:
            return False
    elif counts != (0, 0, 0):
        return False
    unresolved = (counts[1] + counts[2] + (1 if record['groupEmpty'] is False else 0)
                  + (1 if record['escapedOverflow'] is True else 0))
    return record['unresolvedDescendants'] == unresolved


def escaped_settled(record) -> bool:
    """Escaped-descendant predicate for a record ALREADY validated by finalize/read_status.

    v3 keeps its exact old meaning: no escaped identity was ever observed (historical 0).
    v4: the supervisor's pre-exit capture (copied unchanged from exit/v2) is complete (group
    observed, history not truncated), was taken inside the anchor's boot, and positively
    settles EVERY recorded (pid, start) identity with self-consistent proofs and counts. A
    synthetic lost record is incomplete and never settled. The exact raw-exit binding is
    checked only by read_status, so call this after a validated read. Anything else
    (unknown schema, missing/mistyped fields) is False.
    """
    if not isinstance(record, Mapping):
        return False
    try:
        schema = record['schema']
        if schema == SCHEMA_RECORD_V3:
            return _count_ok(record['escapedDescendants']) and record['escapedDescendants'] == 0
        if schema != SCHEMA_RECORD or not _count_ok(record['escapedDescendants']) \
                or type(record['escapedOverflow']) is not bool or not _settlement_ok(record):
            return False
        settlement = record['escapedSettlement']
        return (settlement['observationComplete'] is True and settlement['live'] == 0
                and settlement['unknown'] == 0
                and settlement['settled'] == record['escapedDescendants'])
    except (KeyError, TypeError):
        return False


def _log_reference(dir_fd: int, attempt_path: str, name: str) -> dict | None:
    fd = _open_artifact(dir_fd, name)
    if fd is None:
        return None
    digest, size = hashlib.sha256(), 0
    try:
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(fd)
    return {'path': os.path.join(attempt_path, name), 'size': size, 'sha256': digest.hexdigest()}


def _logs_shape_ok(logs) -> bool:
    if not isinstance(logs, dict) or set(logs) != {'stdout', 'stderr'}:
        return False
    return all(ref is None or (isinstance(ref, dict) and set(ref) == LOG_KEYS
                               and isinstance(ref['path'], str) and _count_ok(ref['size'])
                               and isinstance(ref['sha256'], str)
                               and SHA256_RE.match(ref['sha256']) is not None)
               for ref in logs.values())


def _escaped_checks(record: dict) -> tuple[tuple[bool, str], ...]:
    """v3: any historical escape fails (exact old meaning). v4: a truncated history or any
    identity not positively settled fails; a settled historical escape does not."""
    if record['schema'] == SCHEMA_RECORD_V3:
        return ((record['escapedDescendants'] > 0, 'escaped-descendants'),)
    settlement = record['escapedSettlement']
    return ((record['escapedOverflow'] is True, 'escaped-observation-truncated'),
            (settlement['live'] + settlement['unknown'] > 0, 'escaped-descendants-unsettled'))


def _reasons(record: dict) -> list[str]:
    termination = record['termination']
    checks = (
        (termination != 'exited', f'termination-{termination}'),
        (termination == 'exited' and record['exitCode'] is None and record['signal'] is None,
         'exit-status-missing'),
        (record['exitCode'] not in (None, 0), 'nonzero-exit'),
        (record['signal'] is not None, 'signalled'),
        (record['forced'] or bool(record['signalsSent']), 'forced'),
        (record['lingering'], 'lingering-descendants'),
        (termination in EXIT_TERMINATIONS and record['membersAtExit'] != 0,
         'exit-group-not-proven-empty'),
        (record['groupEmpty'] is not True, 'group-not-proven-empty'),
        (record['groupObservation'] != 'ok', 'group-observation-unavailable'),
        *_escaped_checks(record),
        (record['unresolvedDescendants'] > 0, 'unresolved-descendants'),
        (any(record['logs'][key] is None for key in ('stdout', 'stderr')), 'logs-missing'),
    )
    return [code for failed, code in checks if failed]


def _execution_success(record: dict) -> bool:
    return (record['termination'] == 'exited' and not record['reasons']
            and _pid_ok(record['commandPid'])
            and type(record['exitCode']) is int and record['exitCode'] == 0
            and type(record['membersAtExit']) is int and record['membersAtExit'] == 0
            and record['groupEmpty'] is True and escaped_settled(record))


def _record_types_ok(record: dict) -> bool:
    return (record['termination'] in TERMINATIONS
            and _optional(record['commandPid'], _pid_ok)
            and _optional(record['commandStart'], _text_ok)
            and _optional(record['exitCode'], _exit_code_ok)
            and _optional(record['signal'], _signal_ok)
            and _optional(record['stopSource'], lambda value: value in STOP_SOURCES)
            and all(type(record[key]) is bool for key in ('forced', 'lingering', 'executionSuccess'))
            and _signals_ok(record['signalsSent'])
            and _optional(record['membersAtExit'], _count_ok)
            and (record['termination'] in EXIT_TERMINATIONS or record['membersAtExit'] is None)
            and _optional(record['groupEmpty'], lambda value: type(value) is bool)
            and record['groupObservation'] in OBSERVATIONS
            and _count_ok(record['escapedDescendants']) and _count_ok(record['unresolvedDescendants'])
            and (record['schema'] == SCHEMA_RECORD_V3 or type(record['escapedOverflow']) is bool)
            and _optional(record['durationSeconds'], lambda value: _seconds_ok(value, MAX_DURATION, True))
            and all(_optional(record[key], _text_ok) for key in ('startedAt', 'endedAt'))
            and _text_ok(record['finalizedAt'])
            and isinstance(record['reasons'], list)
            and all(isinstance(reason, str) and reason in REASONS for reason in record['reasons'])
            and isinstance(record['limitations'], list)
            and all(isinstance(item, str) for item in record['limitations']))


def _record_command_consistent(record: dict) -> bool:
    """A launched command carries its own pid, distinct from the bootstrap anchor; else none."""
    pid, start = record['commandPid'], record['commandStart']
    if record['termination'] not in COMMAND_TERMINATIONS:
        return pid is None and start is None
    return _pid_ok(pid) and pid != record['identity']['pid']


def _record_matches_journal(dir_fd: int, record: dict) -> bool:
    """An exit-settled record's command pid equals the native journal's command-started pid."""
    if record['termination'] not in EXIT_TERMINATIONS:
        return True
    events, journal = _read_journal(dir_fd)
    if journal != 'complete':
        return False
    phase = _journal_phase(events, record['identity'])
    return phase is not None and _exit_matches_journal(record, phase, events)


def _record_problem(dir_fd: int, attempt_path: str, record: dict, intent: dict,
                    intent_sha: str) -> str | None:
    """Fixed problem code for a stored lifecycle record, or None when it fully checks out."""
    schema = record.get('schema')
    keys = RECORD_KEYS if schema == SCHEMA_RECORD else RECORD_KEYS_V3 if schema == SCHEMA_RECORD_V3 else None
    if keys is None or set(record) != keys:
        return 'record-fields'
    if record['attemptId'] != intent['attemptId']:
        return 'record-attempt-mismatch'
    if record['intentSha256'] != intent_sha:
        return 'intent-tampered'
    identity = record['identity']
    if (identity is None and record['termination'] != 'not-launched') or \
            (identity is not None and not _identity_ok(identity, intent['attemptId'], intent_sha)):
        return 'record-identity-invalid'
    if not _record_types_ok(record):
        return 'record-types-invalid'
    if not _record_command_consistent(record):
        return 'record-command-inconsistent'
    if not _logs_shape_ok(record['logs']):
        return 'record-logs-invalid'
    if record['schema'] == SCHEMA_RECORD and not _settlement_ok(record):
        return 'record-settlement-invalid'
    if record['reasons'] != _reasons(record):
        return 'record-reasons-inconsistent'
    if record['executionSuccess'] is not _execution_success(record):
        return 'record-success-inconsistent'
    if not _record_matches_exit(dir_fd, record, intent['attemptId']):
        return 'record-exit-mismatch'
    if not _record_matches_journal(dir_fd, record):
        return 'record-journal-mismatch'
    for stream, name in (('stdout', STDOUT), ('stderr', STDERR)):
        if record['logs'][stream] != _log_reference(dir_fd, attempt_path, name):
            return 'log-tampered'
    return None


def _synthetic_exit(state: str) -> dict:
    return {'termination': 'not-launched' if state == 'not-launched' else 'lost',
            'commandPid': None, 'commandStart': None, 'stopSource': None, 'exitCode': None, 'signal': None, 'forced': False,
            'signalsSent': [], 'lingering': False, 'membersAtRecord': None,
            'groupObservation': 'ok' if state == 'not-launched' else 'unavailable',
            'escaped': [], 'escapedOverflow': False, 'startedAt': None, 'endedAt': None,
            'durationSeconds': None}


def _synthetic_settlement(source: dict) -> dict:
    """No supervisor recorded an exit: not-launched is proven to have no command (complete,
    no identity); lost is UNKNOWN (incomplete, never settled). Nothing is probed or invented."""
    return {'observationComplete': source['groupObservation'] == 'ok', 'bootId': boot_identity(),
            'observedAt': utc_now(), 'identities': [], 'settled': 0, 'live': 0, 'unknown': 0}


def _exit_facts(source: dict) -> dict:
    """Lifecycle-record fields copied verbatim from an exit (or synthetic) record."""
    return {'termination': source['termination'], 'commandPid': source['commandPid'],
            'commandStart': source['commandStart'], 'stopSource': source['stopSource'],
            'exitCode': source['exitCode'], 'signal': source['signal'],
            'forced': source['forced'], 'signalsSent': list(source['signalsSent']),
            'lingering': source['lingering'], 'membersAtExit': source['membersAtRecord'],
            'groupObservation': source['groupObservation'],
            'escapedDescendants': len(source['escaped']), 'startedAt': source['startedAt'],
            'endedAt': source['endedAt'], 'durationSeconds': source['durationSeconds'],
            # exit/v1 carries no overflow flag, so its v3 record has none either.
            **({'escapedOverflow': source['escapedOverflow']} if 'escapedOverflow' in source else {}),
            # exit/v2: the supervisor's pre-closure settlement, copied (and compared) exactly.
            **({'escapedSettlement': source['escapedSettlement']}
               if 'escapedSettlement' in source else {})}


def _facts_equal(record: dict, expected: dict) -> bool:
    return {key: record.get(key) for key in expected} == expected


def _record_matches_exit(dir_fd: int, record: dict, attempt_id: str) -> bool:
    """Exit-derived record fields equal the retained raw exit.json (absent when synthetic).

    A v3 record pairs only with an exit/v1, a v4 record only with an exit/v2, whose
    settlement the record must equal exactly (and every identity is bound, in order, to the
    raw exit's escaped pid/start history).
    """
    exit_record = _load_json(dir_fd, EXIT)
    current = record['schema'] == SCHEMA_RECORD
    if record['termination'] not in EXIT_TERMINATIONS:
        if exit_record is not None:
            return False
        return not current or _facts_equal(record, _exit_facts(_synthetic_exit(record['termination'])))
    if exit_record is None or not _exit_ok(exit_record, attempt_id) \
            or exit_record['schema'] != (SCHEMA_EXIT if current else SCHEMA_EXIT_V1):
        return False
    if not _facts_equal(record, _exit_facts(exit_record)):
        return False
    if not current:
        return True
    settled = [(item['pid'], item['start']) for item in record['escapedSettlement']['identities']]
    return settled == [(item['pid'], item['start']) for item in exit_record['escaped']]


def _build_record(dir_fd: int, attempt_path: str, facts: _Facts) -> dict:
    state, identity = facts.recovery.state, facts.identity
    source = facts.exit_record if state == 'exited' else _synthetic_exit(state)
    legacy = source.get('schema') == SCHEMA_EXIT_V1  # older supervisor: the exact v3 record
    group_empty = _group_empty(identity['pgid']) if identity is not None else None
    record = {
        'schema': SCHEMA_RECORD_V3 if legacy else SCHEMA_RECORD,
        'attemptId': facts.intent['attemptId'],
        'intentSha256': facts.intent_sha, 'identity': identity,
        **_exit_facts(source),
        # Observed now; it never replaces the settlement evidence kept in membersAtExit.
        'groupEmpty': group_empty,
    }
    group_unresolved = 1 if group_empty is False else 0
    if legacy:
        alive = sum(1 for item in source['escaped'] if _escaped_alive(item))
        record['unresolvedDescendants'] = alive + group_unresolved
    else:
        # exit/v2: the supervisor's capture, already copied verbatim by _exit_facts. It is never
        # re-probed here, so a later exit, absence or reboot cannot upgrade it.
        if state != 'exited':
            record['escapedSettlement'] = _synthetic_settlement(source)
        settlement = record['escapedSettlement']
        record['unresolvedDescendants'] = (settlement['live'] + settlement['unknown'] + group_unresolved
                                           + (1 if source['escapedOverflow'] else 0))
    # Hashed only now: the group is terminal (or recorded as not proven so) and settled
    # escaped identities can no longer append to an inherited log.
    record.update(logs={'stdout': _log_reference(dir_fd, attempt_path, STDOUT),
                        'stderr': _log_reference(dir_fd, attempt_path, STDERR)},
                  limitations=list(LIMITATIONS), finalizedAt=utc_now())
    record['reasons'] = _reasons(record)
    record['executionSuccess'] = _execution_success(record)
    return record


def finalize(attempt) -> dict:
    """Write the single lifecycle record of a settled attempt; never overwrites, refuses active,
    unknown or corrupt attempts (code 'attempt-<state>')."""
    root, name = _attempt_parts(attempt)
    attempt_path = os.path.join(root, name)
    with _attempt_dir(attempt_path) as dir_fd:
        facts = _classify(dir_fd, attempt_path)
        state = facts.recovery.state
        if state == 'finalized':
            raise ProcessError('already-finalized')
        if state not in FINALIZABLE_STATES:
            raise ProcessError(f'attempt-{state}')
        record = _build_record(dir_fd, attempt_path, facts)
        try:
            _create_json(dir_fd, RECORD, record)
        except FileExistsError:
            raise ProcessError('already-finalized') from None
        except OSError:
            raise ProcessError('record-write-failed') from None
    return record


# ---------------------------------------------------------------- bootstrap (anchor side)

def _table_int_ok(part: str) -> bool:
    return part.isdigit() and len(part) <= 10 and int(part) <= MAX_PID


def _process_table() -> list[tuple[int, int, int, str]] | None:
    """One complete typed ps snapshot: (pid, ppid, pgid, lstart identity) per process, or None.

    A missing tool, nonzero exit, timeout, non-ASCII, empty, malformed, truncated or duplicate
    row, an out-of-range id, or a table that omits this observer itself is UNAVAILABLE, never
    a clean partial inventory. Only the ps process itself is left out of the rows."""
    tool = shutil.which('ps', path=SYSTEM_PATH)
    if tool is None:
        return None
    try:
        proc = subprocess.Popen([tool, '-A', '-o', 'pid=', '-o', 'ppid=', '-o', 'pgid=',
                                 '-o', 'lstart='],
                                env=SYSTEM_ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        return None
    try:
        output, _ = proc.communicate(timeout=SYSTEM_QUERY_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None
    if proc.returncode != 0:
        return None
    try:
        lines = output.decode('ascii').splitlines()
    except UnicodeDecodeError:
        return None
    rows, listed = [], set()
    for line in lines:
        parts = line.split()
        if len(parts) != 8 or not all(_table_int_ok(part) for part in parts[:3]):
            return None
        pid, ppid, pgid = (int(part) for part in parts[:3])
        if pid in listed:
            return None
        listed.add(pid)
        if pid != proc.pid:
            rows.append((pid, ppid, pgid, 'lstart:' + ' '.join(parts[3:])))
    return rows if os.getpid() in listed else None


class _GroupWatch:
    """Observes (never signals) owned group members and descendants that left the group.

    Escaped descendants are retained as distinct (pid, start) identities: a pid reused by a
    later observed descendant with another start is a SECOND identity, never folded into the
    first, and an unknown start (None) is its own uncertain identity; only exact duplicates
    collapse. Two descendants started within one lstart second under the same pid cannot be
    told apart and stay one identity that a probe can only call live/unknown. Past
    MAX_ESCAPED distinct identities, overflow is recorded (blocking), never a clean history."""

    def __init__(self, pgid: int):
        self.pid = os.getpid()
        self.pgid = pgid
        self._escaped: set[tuple[int, str | None]] = set()
        self.overflow = False  # an escape was seen after the retained history was full
        self.available = True
        self._next_scan = 0.0

    def identities(self) -> list[dict]:
        """The retained history ordered by pid, then start (an unknown start first)."""
        ordered = sorted(self._escaped,
                         key=lambda pair: (pair[0], pair[1] is not None, pair[1] or ''))
        return [{'pid': pid, 'start': start} for pid, start in ordered]

    def _retain(self, identity: tuple[int, str | None]) -> None:
        if identity in self._escaped:
            return
        if len(self._escaped) < MAX_ESCAPED:
            self._escaped.add(identity)
        else:
            self.overflow = True  # recorded, never truncated into a clean history

    def snapshot(self) -> set[int] | None:
        rows = _process_table()
        if rows is None:
            self.available = False
            return None
        procfs = _procfs()
        children: dict[int, list[int]] = {}
        groups, starts = {}, {}
        for pid, ppid, pgid, start in rows:
            children.setdefault(ppid, []).append(pid)
            groups[pid], starts[pid] = pgid, start
        stack, seen = [self.pid], set()
        while stack:
            for child in children.get(stack.pop(), ()):
                if child in seen:
                    continue
                seen.add(child)
                stack.append(child)
                if groups[child] != self.pgid:
                    # The start form the settlement probe compares: procfs ticks, else this
                    # snapshot's own lstart (the form process_start() and _start_table use).
                    self._retain((child, process_start(child) if procfs else starts[child]))
        return {pid for pid, _ppid, pgid, _start in rows if pgid == self.pgid and pid != self.pid}

    def maybe_scan(self) -> None:
        now = time.monotonic()
        if now >= self._next_scan:
            self._next_scan = now + SCAN_SECONDS
            self.snapshot()


def _stop_present(dir_fd: int) -> bool:
    try:
        return _exists(dir_fd, STOP)
    except ProcessError:
        return True  # an unsafe STOP artifact is treated as a stop (fail closed)


def _await_release(dir_fd: int, fd: int, token: str, timeout: float, stop: dict) -> str:
    expected = b'RELEASE ' + token.encode('ascii') + b'\n'
    deadline = time.monotonic() + timeout
    received = b''
    while True:
        if stop['signal'] or _stop_present(dir_fd):
            return 'stop-requested'
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 'release-timeout'
        ready, _, _ = select.select([fd], [], [], min(remaining, 0.25))
        if not ready:
            continue
        chunk = os.read(fd, len(expected) + 1 - len(received))
        if not chunk:
            return 'release-channel-closed'
        received += chunk
        if not expected.startswith(received):
            return 'release-message-invalid'
        if received == expected:
            return 'released'


def _binding_problem(intent: dict) -> str | None:
    checks = [('cwd-binding-changed', intent['cwd'])] + \
        [('config-binding-changed', binding) for binding in intent['bindings'].values()] + \
        [('selector-binding-changed', binding)
         for binding in intent['environment']['selectors'].values()]
    for code, binding in checks:
        try:
            if _dir_binding(binding['path'], code) != binding:
                return code
        except (ProcessError, KeyError, TypeError):
            return code
    try:
        if _executable_binding(intent['executable']['path']) != intent['executable']:
            return 'executable-binding-changed'
    except (ProcessError, KeyError, TypeError):
        return 'executable-binding-changed'
    return None


def _verified_stdin(dir_fd: int, expected: dict) -> int | None:
    """Open stdin, check size+hash on the same fd that the command will read."""
    fd = _open_artifact(dir_fd, STDIN)
    if fd is None:
        return None
    digest, size = hashlib.sha256(), 0
    while True:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    if size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
        os.close(fd)
        return None
    os.lseek(fd, 0, os.SEEK_SET)
    os.set_blocking(fd, True)
    return fd


def _close_all(fds) -> None:
    for fd in fds or ():
        os.close(fd)


def _prelaunch(dir_fd: int, intent: dict):
    if not _exists(dir_fd, RELEASE):
        return 'release-record-missing', None
    problem = _binding_problem(intent)
    if problem is not None:
        return problem, None
    stdin_fd = _verified_stdin(dir_fd, intent['stdin'])
    if stdin_fd is None:
        return 'stdin-tampered', None
    opened = [stdin_fd]
    try:
        for name in (STDOUT, STDERR):
            opened.append(os.open(name, NEW_FILE_FLAGS, 0o600, dir_fd=dir_fd))
    except OSError:
        _close_all(opened)
        return 'log-unsafe', None
    return 'released', tuple(opened)


def _prelaunch_checked(dir_fd: int, intent: dict, stop: dict):
    try:
        verdict, fds = _prelaunch(dir_fd, intent)
    except ProcessError as err:
        return err.code, None
    except OSError:
        return 'io-error', None
    if verdict == 'released' and (stop['signal'] or _stop_present(dir_fd)):
        _close_all(fds)
        return 'stop-requested', None
    return verdict, fds


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return 'SIGUNKNOWN'


def _await_command(command, dir_fd, intent, watch, stop, began) -> tuple[str, str | None]:
    deadline = began + intent['timeoutSeconds']
    while command.poll() is None:
        if stop['signal']:
            return 'stopped', 'signal'
        if _stop_present(dir_fd):
            return 'stopped', 'file'
        if time.monotonic() >= deadline:
            return 'timeout', None
        watch.maybe_scan()
        time.sleep(POLL_SECONDS)
    return 'exited', None


def _await_drain(watch, members, dir_fd, stop, linger: float):
    """Command exit is not group exit: give remaining members a bounded drain."""
    deadline = time.monotonic() + linger
    while members and time.monotonic() < deadline and not stop['signal'] \
            and not _stop_present(dir_fd):
        time.sleep(SCAN_SECONDS)
        members = watch.snapshot()
    return members


def _await_term(command, watch, grace: float):
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if command.poll() is None:
            time.sleep(POLL_SECONDS)
            continue
        members = watch.snapshot()
        if members is not None and not members:
            return members
        time.sleep(SCAN_SECONDS)
    command.poll()
    return watch.snapshot()


def _empty_exit_record(intent: dict) -> dict:
    return {'schema': SCHEMA_EXIT, 'attemptId': intent['attemptId'], 'termination': None,
            'stopSource': None, 'commandPid': None, 'commandStart': None, 'exitCode': None,
            'signal': None, 'lingering': False, 'signalsSent': [], 'forced': False,
            'membersAtRecord': None, 'groupObservation': 'ok', 'escaped': [],
            'escapedOverflow': False, 'escapedSettlement': None, 'startedAt': utc_now(),
            'endedAt': None, 'durationSeconds': None}


def _closed(record: dict, began: float) -> dict:
    record['endedAt'] = utc_now()
    record['durationSeconds'] = round(time.monotonic() - began, 3)
    return record


def _supervise(dir_fd: int, intent: dict, fds, stop: dict) -> dict:
    record = _empty_exit_record(intent)
    began = time.monotonic()
    stdin_fd, out_fd, err_fd = fds
    try:
        command = subprocess.Popen(intent['argv'], cwd=intent['cwd']['path'], stdin=stdin_fd,
                                   stdout=out_fd, stderr=err_fd, close_fds=True)
    except OSError:
        command = None
    finally:
        _close_all(fds)
    if command is None:
        _append_journal(dir_fd, 'launch-failed')
        # Nothing ran, so nothing escaped: a complete, empty capture in this boot.
        record.update(termination='launch-failed', membersAtRecord=0,
                      escapedSettlement=_escaped_settlement([], boot_identity(), True))
        return _closed(record, began)
    record.update(commandPid=command.pid, commandStart=process_start(command.pid))
    _append_journal(dir_fd, 'command-started', pid=command.pid)
    pgid = os.getpgid(0)
    watch = _GroupWatch(pgid)
    termination, source = _await_command(command, dir_fd, intent, watch, stop, began)
    settle_by = time.monotonic() + intent['lingerSeconds']  # one drain budget, shared below
    members = watch.snapshot()
    if termination == 'exited':
        members = _await_drain(watch, members, dir_fd, stop, intent['lingerSeconds'])
        record['lingering'] = members is None or bool(members)
    if termination != 'exited' or record['lingering']:
        os.killpg(pgid, signal.SIGTERM)  # own group only; the anchor's handler absorbs its copy
        record['signalsSent'].append('SIGTERM')
        members = _await_term(command, watch, intent['termGraceSeconds'])
    code = command.poll()
    kill_pending = code is None or members is None or bool(members)
    if kill_pending:
        record['signalsSent'].append('SIGKILL')  # sent by the anchor right after this record
    record.update(
        termination=termination, stopSource=source, forced=bool(record['signalsSent']),
        exitCode=code if code is not None and code >= 0 else None,
        signal=_signal_name(-code) if code is not None and code < 0 else None,
        membersAtRecord=None if members is None else len(members),
        groupObservation='ok' if watch.available else 'unavailable',
        escaped=watch.identities(), escapedOverflow=watch.overflow)
    budget = 0.0 if kill_pending else settle_by - time.monotonic()
    record['escapedSettlement'] = _capture_settlement(record, dir_fd, stop, budget)
    return _closed(record, began)


def _capture_settlement(record: dict, dir_fd: int, stop: dict, budget: float) -> dict:
    """Probe every escaped identity after the owned group drained and BEFORE the exit record
    closes, inside this supervisor's own boot. Unsettled identities are re-probed only within
    the remaining drain budget (one round while a SIGKILL is pending or a stop is requested).
    Observes; never signals anything outside the owned group."""
    complete = record['groupObservation'] == 'ok' and not record['escapedOverflow']
    return _settle_escaped(record['escaped'], boot_identity(), complete, max(0.0, budget),
                           lambda: stop['signal'] or _stop_present(dir_fd))


def _run_supervised(dir_fd: int, intent: dict, fds, stop: dict) -> int:
    pgid = os.getpgid(0)
    try:
        record = _supervise(dir_fd, intent, fds, stop)
        _create_json(dir_fd, EXIT, record)
    except BaseException:
        os.killpg(pgid, signal.SIGKILL)  # fail closed: an unrecorded supervisor leaves nothing running
        raise
    if record['signalsSent'][-1:] == ['SIGKILL']:
        os.killpg(pgid, signal.SIGKILL)  # the anchor goes with its group; the record is already durable
    return 0


def _bootstrap_attempt(dir_fd: int, attempt: str, release_fd: int, token: str,
                       intent_sha: str, stop: dict) -> int:
    intent, verdict = None, 'io-error'
    try:
        _append_journal(dir_fd, 'bootstrap-started', pid=os.getpid())
        intent, actual_sha = _load_intent(dir_fd, os.path.basename(attempt))
        verdict = 'intent-tampered' if actual_sha != intent_sha else \
            _await_release(dir_fd, release_fd, token, intent['releaseTimeoutSeconds'], stop)
    except ProcessError as err:
        verdict = err.code
    except OSError:
        verdict = 'io-error'
    finally:
        os.close(release_fd)
    fds = None
    if verdict == 'released':
        verdict, fds = _prelaunch_checked(dir_fd, intent, stop)
    if verdict != 'released':
        _append_journal(dir_fd, 'aborted', reason=verdict if verdict in ABORT_REASONS else 'io-error')
        return 3
    try:
        _append_journal(dir_fd, 'launching')  # durable before exec, or nothing is launched
    except BaseException:
        _close_all(fds)
        raise
    return _run_supervised(dir_fd, intent, fds, stop)


def _bootstrap_main(args: list[str]) -> int:
    attempt, release_text, token, intent_sha = args
    release_fd = int(release_text)
    stop = {'signal': False}
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, lambda _signum, _frame: stop.__setitem__('signal', True))
    try:
        with _attempt_dir(attempt) as dir_fd:
            return _bootstrap_attempt(dir_fd, attempt, release_fd, token, intent_sha, stop)
    except ProcessError as err:
        # The attempt is not safely usable: nothing was launched. Goes to bootstrap.log.
        print(json.dumps({'bootstrap': 'refused', 'code': err.code}), file=sys.stderr)
        return 3


def _main(argv: list[str]) -> int:
    if len(argv) == 5 and argv[0] == BOOTSTRAP_FLAG:
        return _bootstrap_main(argv[1:])
    if len(argv) == 2 and argv[0] == '--status':
        try:
            status = read_status(argv[1])
        except ProcessError as err:
            print(json.dumps({'error': err.code}))
            return 2
        print(json.dumps(status, sort_keys=True))
        return 0
    print(json.dumps({'error': 'usage'}), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
