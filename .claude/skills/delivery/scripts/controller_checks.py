#!/usr/bin/env python3
"""Predeclared deterministic checks for the persistent delivery controller (stdlib only).

Each check is recorded by the EXISTING verified-handoff v1 producer (evidence.run_check)
and admitted only by its v1 validator (load_manifest + verify_check). The ACTUAL check
argv is launched directly by the shared owned-process helper through evidence.run_check's
keyword-only in-process `supervisor` seam; no recorder CLI is nested in a session.

API
    CheckSpec(check_id, attempt_id, argv, cwd, expected_sha, evidence_path, timeout_seconds)
    predeclare_checks(specs, artifact_root, allowed_argv) -> tuple[PreparedCheck, ...]
        validates every spec first, then writes each immutable manifest + intent (0600,
        exclusive, no symlink following) BEFORE any run
    run_check(prepared, *, on_spawn, authorize_release, should_stop) -> CheckOutcome
        spawn held -> on_spawn(identity, process_path) -> authorize_release() is True ->
        release; should_stop() polled while active (STOP goes through the helper)
    run_checks(prepared_checks, **callbacks) -> tuple[CheckOutcome, ...]   runs ALL
    inspect_check(prepared) -> CheckOutcome      read-only; creates/finalizes nothing
    request_stop(prepared) -> 'owned'|'not-owned'|'unknown'|'not-spawned'
    aggregate(outcomes) -> (status, reasons)     any FAIL -> FAIL; empty -> INCOMPLETE
    child_from_record(record) -> v1 receipt child dict

Status: PASS only when the v1 validator verifies the receipt AND the finalized lifecycle
record reports executionSuccess for the same command pid. FAIL only for a verified-shape
receipt whose sole findings are a nonzero exit with a clean lifecycle. Everything else
(refused, timeout, stopped, forced, lingering, unknown/corrupt process, input drift,
missing receipt) is INCOMPLETE. A receipt is necessary evidence, never review or CI.

Limits: same-user trust as the helper and recorder; the launched argv[0] is the resolved
executable path; descendantsObservedAfterExit maps only the helper's lingering fact.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import inspect
import json
import math
import os
import re
import secrets
import stat
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import controller_process as process

SCHEMA_INTENT = 'sdlc-controller/check-intent/v1'
MANIFEST = 'manifest.json'
INTENT = 'check-intent.json'
RECEIPT_DIR = 'receipt'
PROCESS_DIR = 'process'
TMP_DIR = 'tmp'
RESULT = 'result.json'

LABEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
SHA_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
CODE_RE = re.compile(r'^[a-z0-9][a-z0-9:/_-]{0,95}$')
EVIDENCE_PARENTS = frozenset({'verified-handoff', 'sdlc-verified-handoff'})
TEMP_SELECTORS = ('TMPDIR', 'TMP', 'TEMP')
NONZERO_ONLY = frozenset({'gate-not-passed', 'child-nonzero-exit'})
MAX_TIMEOUT = 86400.0
MAX_FILE_BYTES = 4 << 20
POLL_SECONDS = 0.1
SETTLE_MARGIN = 30.0
DIR_FLAGS = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | os.O_NOFOLLOW
NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


class CheckError(Exception):
    """Refusal carrying a fixed reason code (never untrusted text)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    attempt_id: str
    argv: tuple[str, ...]
    cwd: str
    expected_sha: str
    evidence_path: str
    timeout_seconds: float


@dataclass(frozen=True)
class PreparedCheck:
    spec: CheckSpec
    attempt_dir: str
    manifest_sha256: str
    intent_sha256: str
    evidence_sha256: str


@dataclass(frozen=True)
class CheckOutcome:
    check_id: str
    attempt_id: str
    status: str
    receipt: str | None
    process: str | None
    reasons: tuple[str, ...]
    duration_seconds: float | None
    input_sha: str


# ---------------------------------------------------------------- private files

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def _overlaps(first: str, second: str) -> bool:
    return os.path.commonpath([first, second]) in (first, second)


def _canonical_dir(path, code: str) -> str:
    if not isinstance(path, str) or '\0' in path or not os.path.isabs(path) \
            or os.path.realpath(path) != path or not os.path.isdir(path):
        raise CheckError(code)
    return path


def _private_dir_ok(info: os.stat_result) -> bool:
    return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077


def _open_private_dir(path, code: str) -> int:
    _canonical_dir(path, code)
    try:
        fd = os.open(path, DIR_FLAGS)
    except OSError:
        raise CheckError(code) from None
    if not _private_dir_ok(os.fstat(fd)):
        os.close(fd)
        raise CheckError(code)
    return fd


def _fsync_dir(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError as err:
        if err.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, 'short write')
        view = view[written:]


def _write_new(dir_fd: int, name: str, data: bytes) -> None:
    fd = os.open(name, NEW_FILE, 0o600, dir_fd=dir_fd)
    try:
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_regular(path: str, code: str) -> tuple[bytes, os.stat_result]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise CheckError(code) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES:
            raise CheckError(code)
        chunks = []
        while chunk := os.read(fd, 1 << 16):
            chunks.append(chunk)
    except OSError:
        raise CheckError(code) from None
    finally:
        os.close(fd)
    data = b''.join(chunks)
    if len(data) > MAX_FILE_BYTES:
        raise CheckError(code)
    return data, info


# ---------------------------------------------------------------- evidence instance

def _evidence_source(path) -> tuple[bytes, str]:
    if not isinstance(path, str) or '\0' in path or not os.path.isabs(path) \
            or os.path.normpath(path) != path:
        raise CheckError('evidence-path-invalid')
    location = Path(path)
    if location.name != 'evidence.py' or location.parent.name != 'scripts' \
            or location.parent.parent.name not in EVIDENCE_PARENTS:
        raise CheckError('evidence-path-invalid')
    data, info = _read_regular(path, 'evidence-unavailable')
    if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
        raise CheckError('evidence-unsafe')
    return data, _sha256(data)


def _discard(*_args, **_kwargs) -> None:
    """Stands in for print inside a private evidence instance; result.json is the record."""


def _load_evidence(path: str, expected_sha: str) -> types.ModuleType:
    """A fresh, unregistered module instance per call: no shared global is patched."""
    data, digest = _evidence_source(path)
    if digest != expected_sha:
        raise CheckError('evidence-changed')
    module = types.ModuleType(f'controller_check_evidence_{secrets.token_hex(8)}')
    module.__file__ = path
    try:
        exec(compile(data, path, 'exec', dont_inherit=True), module.__dict__)
        seam = inspect.signature(module.run_check).parameters.get('supervisor')
    except Exception:
        raise CheckError('evidence-load-failed') from None
    if seam is None or seam.kind is not inspect.Parameter.KEYWORD_ONLY or seam.default is not None:
        raise CheckError('evidence-seam-missing')
    module.print = _discard
    return module


# ---------------------------------------------------------------- predeclaration

def _timeout_ok(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 < value <= MAX_TIMEOUT


def _validate_spec(spec, allowed: frozenset, root: str) -> None:
    if not isinstance(spec, CheckSpec):
        raise CheckError('invalid-spec')
    if not isinstance(spec.check_id, str) or not LABEL_RE.match(spec.check_id):
        raise CheckError('invalid-check-id')
    if not isinstance(spec.attempt_id, str) or not process.ATTEMPT_ID_RE.match(spec.attempt_id):
        raise CheckError('invalid-attempt-id')
    argv = spec.argv
    if not isinstance(argv, tuple) or not argv \
            or not all(isinstance(arg, str) and '\0' not in arg for arg in argv) \
            or not os.path.isabs(argv[0]):
        raise CheckError('invalid-argv')
    if argv not in allowed:
        raise CheckError('argv-not-allowlisted')
    cwd = _canonical_dir(spec.cwd, 'invalid-cwd')
    if not isinstance(spec.expected_sha, str) or not SHA_RE.match(spec.expected_sha):
        raise CheckError('invalid-expected-sha')
    if not _timeout_ok(spec.timeout_seconds):
        raise CheckError('invalid-timeout')
    if _overlaps(root, cwd):
        raise CheckError('artifact-root-overlaps-input')


def _manifest_bytes(spec: CheckSpec) -> bytes:
    check = {'label': spec.check_id, 'cwd': spec.cwd,
             'command': {'executable': spec.argv[0], 'args': list(spec.argv[1:])},
             'expectedSha': spec.expected_sha, 'resultFile': f'{RECEIPT_DIR}/{RESULT}'}
    return _json_bytes({'checks': [check]})


def _declare(spec: CheckSpec, root: str, evidence_sha: str) -> PreparedCheck:
    manifest = _manifest_bytes(spec)
    intent = _json_bytes({
        'schema': SCHEMA_INTENT, 'checkId': spec.check_id, 'attemptId': spec.attempt_id,
        'argv': list(spec.argv), 'cwd': spec.cwd, 'expectedSha': spec.expected_sha,
        'timeoutSeconds': float(spec.timeout_seconds), 'evidencePath': spec.evidence_path,
        'evidenceSha256': evidence_sha, 'manifestSha256': _sha256(manifest),
        'createdAt': process.utc_now()})
    root_fd = _open_private_dir(root, 'artifact-root-not-private')
    try:
        try:
            os.mkdir(spec.attempt_id, 0o700, dir_fd=root_fd)
        except FileExistsError:
            raise CheckError('attempt-exists') from None
        _fsync_dir(root_fd)
        attempt_fd = os.open(spec.attempt_id, DIR_FLAGS, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    try:
        if not _private_dir_ok(os.fstat(attempt_fd)):
            raise CheckError('attempt-not-private')
        _write_new(attempt_fd, MANIFEST, manifest)
        _write_new(attempt_fd, INTENT, intent)
        _fsync_dir(attempt_fd)
    finally:
        os.close(attempt_fd)
    return PreparedCheck(spec, os.path.join(root, spec.attempt_id), _sha256(manifest),
                         _sha256(intent), evidence_sha)


def predeclare_checks(specs: Iterable[CheckSpec], artifact_root: str,
                      allowed_argv: Iterable[Iterable[str]]) -> tuple[PreparedCheck, ...]:
    """Validate ALL specs, then persist each exact argv/SHA manifest before any run."""
    specs = tuple(specs)
    allowed = frozenset(tuple(argv) for argv in allowed_argv)
    root = _canonical_dir(artifact_root, 'artifact-root-not-canonical')
    os.close(_open_private_dir(root, 'artifact-root-not-private'))
    ids, attempts, digests = set(), set(), {}
    for spec in specs:
        _validate_spec(spec, allowed, root)
        if spec.check_id in ids or spec.attempt_id in attempts:
            raise CheckError('duplicate-check')
        if os.path.lexists(os.path.join(root, spec.attempt_id)):
            raise CheckError('attempt-exists')
        ids.add(spec.check_id)
        attempts.add(spec.attempt_id)
        if spec.evidence_path not in digests:
            digests[spec.evidence_path] = _evidence_source(spec.evidence_path)[1]
    try:
        return tuple(_declare(spec, root, digests[spec.evidence_path]) for spec in specs)
    except OSError:
        raise CheckError('declare-failed') from None


def _require_prepared(prepared) -> None:
    if not isinstance(prepared, PreparedCheck) or not isinstance(prepared.spec, CheckSpec):
        raise CheckError('invalid-prepared-check')


def _verified_inputs(prepared: PreparedCheck) -> types.ModuleType:
    """Manifest, intent and evidence source must be exactly what was predeclared."""
    os.close(_open_private_dir(prepared.attempt_dir, 'attempt-not-private'))
    manifest, _ = _read_regular(os.path.join(prepared.attempt_dir, MANIFEST), 'manifest-unavailable')
    intent, _ = _read_regular(os.path.join(prepared.attempt_dir, INTENT), 'intent-unavailable')
    if _sha256(manifest) != prepared.manifest_sha256 or manifest != _manifest_bytes(prepared.spec):
        raise CheckError('manifest-changed')
    if _sha256(intent) != prepared.intent_sha256:
        raise CheckError('intent-changed')
    return _load_evidence(prepared.spec.evidence_path, prepared.evidence_sha256)


# ---------------------------------------------------------------- shared-runner backend

def child_from_record(record: dict) -> dict:
    """Map a validated lifecycle record onto the v1 child; only facts the record states."""
    if 'commandPid' not in record or 'commandStart' not in record:
        raise CheckError('command-identity-missing')
    pid, identity = record['commandPid'], record.get('identity')
    bootstrap_pid = identity.get('pid') if isinstance(identity, dict) else None
    if type(pid) is not int or pid <= 1 or pid == bootstrap_pid:
        raise CheckError('command-identity-invalid')
    lingering = record['lingering'] is True
    group_clean = (record['groupEmpty'] is True and record['membersAtExit'] == 0
                   and record['groupObservation'] == 'ok'
                   and record['escapedDescendants'] == 0 and record['unresolvedDescendants'] == 0)
    return {'launched': True, 'pid': pid, 'timedOut': record['termination'] == 'timeout',
            'descendantsObservedAfterExit': lingering, 'descendantsOutlivedDeadline': lingering,
            'groupEmptyAtReceipt': group_clean, 'signalsSent': list(record['signalsSent']),
            'exitCode': record['exitCode'], 'signal': record['signal']}


def _copy_exclusive(source: str, target: Path) -> tuple[str, int]:
    src = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(src)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CheckError('process-log-unsafe')
        dst = os.open(target, NEW_FILE, 0o600)
        try:
            digest, size = hashlib.sha256(), 0
            while chunk := os.read(src, 1 << 20):
                digest.update(chunk)
                size += len(chunk)
                _write_all(dst, chunk)
            os.fsync(dst)
        finally:
            os.close(dst)
    finally:
        os.close(src)
    return digest.hexdigest(), size


def _copy_logs(attempt: str, record: dict, out_dir: Path) -> None:
    """Full raw helper logs into the recorder out-dir; bytes must equal the validated record."""
    for stream, name in (('stdout', process.STDOUT), ('stderr', process.STDERR)):
        reference = record['logs'][stream]
        if reference is None:
            raise CheckError('process-log-missing')
        try:
            digest, size = _copy_exclusive(os.path.join(attempt, name), out_dir / name)
        except OSError:
            raise CheckError('process-log-copy-failed') from None
        if (digest, size) != (reference['sha256'], reference['size']):
            raise CheckError('process-log-mismatch')


class _Backend:
    """evidence.run_check supervisor: the helper launches the ACTUAL argv, never the recorder."""

    def __init__(self, prepared: PreparedCheck, module: types.ModuleType,
                 on_spawn: Callable, authorize_release: Callable, should_stop: Callable):
        self.prepared, self.module = prepared, module
        self.on_spawn, self.authorize_release, self.should_stop = on_spawn, authorize_release, should_stop

    def _refusal(self, code: str) -> Exception:
        return self.module.Refusal(code)  # only for conclusively not-launched outcomes

    def __call__(self, argv, executable, cwd, out_dir, timeout) -> dict:
        base = self.prepared.attempt_dir
        if tuple(argv) != self.prepared.spec.argv or str(cwd) != self.prepared.spec.cwd \
                or str(out_dir) != os.path.join(base, RECEIPT_DIR):
            raise CheckError('backend-input-mismatch')
        temp = os.path.join(base, TMP_DIR)
        spec = process.CommandSpec(argv=(str(executable), *argv[1:]), cwd=str(cwd), stdin=b'',
                                   attempt_id=self.prepared.spec.attempt_id,
                                   env_selectors={key: temp for key in TEMP_SELECTORS})
        try:
            attempt = process.prepare(os.path.join(base, PROCESS_DIR), spec, float(timeout))
            pending = process.spawn(attempt)
        except process.ProcessError as err:
            raise self._refusal(f'process-{err.code}') from None
        owned = self._release(pending, str(attempt))
        record = self._settle(owned, float(timeout))
        child = child_from_record(record)
        _copy_logs(str(owned.attempt), record, Path(out_dir))
        return child

    def _release(self, pending, attempt: str):
        try:
            self.on_spawn(pending.identity, attempt)
            authorized = self.authorize_release() is True
        except BaseException as exc:
            pending.abort()
            if isinstance(exc, Exception):
                raise self._refusal('release-callback-failed') from None
            raise
        if not authorized:
            pending.abort()
            raise self._refusal('release-not-authorized')
        try:
            return pending.release()
        except process.ProcessError as err:
            pending.abort()
            raise self._refusal(f'process-{err.code}') from None

    def _stop_wanted(self) -> bool:
        try:
            return bool(self.should_stop())
        except Exception:
            return True  # fail closed: an unreadable STOP/lease is a stop

    def _await_settlement(self, owned, timeout: float) -> None:
        """Live, startup and unknown states are non-admissible; wait, STOP, then give up."""
        settle = process.DEFAULT_TERM_GRACE + process.DEFAULT_LINGER + SETTLE_MARGIN
        deadline = time.monotonic() + timeout + settle
        stopping = False
        while True:
            try:
                state = owned.poll().state
            except process.ProcessError as err:
                raise CheckError(f'process-{err.code}') from None
            if state in process.FINALIZABLE_STATES:
                return
            if state in ('finalized', 'corrupt'):
                raise CheckError(f'process-{state}')
            now = time.monotonic()
            if stopping and now >= deadline:
                raise CheckError('process-unsettled')
            if not stopping and (now >= deadline or self._stop_wanted()):
                try:
                    owned.request_stop()
                except process.ProcessError as err:
                    raise CheckError(f'process-stop-{err.code}') from None
                stopping, deadline = True, now + settle
            time.sleep(POLL_SECONDS)

    def _settle(self, owned, timeout: float) -> dict:
        try:
            self._await_settlement(owned, timeout)
        except BaseException:
            # Fail closed: the original error is re-raised; a stop request failure adds nothing.
            with contextlib.suppress(process.ProcessError, OSError):
                owned.request_stop()
            raise
        try:
            record = owned.finalize()
            status = process.read_status(owned.attempt)
        except process.ProcessError as err:
            raise CheckError(f'process-{err.code}') from None
        if status['state'] != 'finalized' or status['record'] != record:
            raise CheckError('process-record-unverified')
        termination = record['termination']
        if termination in ('not-launched', 'launch-failed'):
            raise self._refusal(f'process-{termination}')
        if termination == 'lost':
            raise CheckError('process-lost')
        return record


# ---------------------------------------------------------------- classification

def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _process_status(prepared: PreparedCheck) -> tuple[str | None, dict | None]:
    attempt = os.path.join(prepared.attempt_dir, PROCESS_DIR, prepared.spec.attempt_id)
    if not os.path.lexists(attempt):
        return None, None
    try:
        return attempt, process.read_status(attempt)
    except process.ProcessError as err:
        return attempt, {'state': f'unreadable-{err.code}', 'reason': None, 'record': None}


def _verify_receipt(module: types.ModuleType, base: str) -> tuple[str, list[str]]:
    try:
        check = module.load_manifest(Path(base, MANIFEST))[0]
    except module.ManifestError as err:
        return 'rejected', [f'manifest-{err.code}']
    status, reasons = module.verify_check(check)
    return status, list(reasons)


def _load_receipt(module: types.ModuleType, path: str) -> dict | None:
    try:
        receipt = module.load_json(Path(path))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    return receipt if isinstance(receipt, dict) else None


def _refusal_codes(receipt: dict | None) -> list[str]:
    gate = receipt.get('gate') if receipt else None
    if not isinstance(gate, dict) or gate.get('outcome') != 'refused' \
            or not isinstance(gate.get('reasons'), list):
        return []
    return [f'refused-{code}' for code in gate['reasons']
            if isinstance(code, str) and CODE_RE.match(code)]


def _pid_matches(receipt: dict | None, record: dict | None) -> bool:
    child = receipt.get('child') if receipt else None
    pid = record.get('commandPid') if record else None
    return isinstance(child, dict) and type(pid) is int and child.get('pid') == pid


def _clean_nonzero(record: dict | None) -> bool:
    return (record is not None and record['termination'] == 'exited'
            and type(record['exitCode']) is int and record['exitCode'] != 0
            and record['reasons'] == ['nonzero-exit'] and record['executionSuccess'] is False)


def _classify(prepared: PreparedCheck, module: types.ModuleType, extra: list[str],
              duration: float | None) -> CheckOutcome:
    base = prepared.attempt_dir
    reasons = list(extra)
    process_path, status = _process_status(prepared)
    record = status.get('record') if status else None
    if status and status['state'] != 'finalized':
        reasons.append(f"process-{status['state']}")
        if status.get('reason'):
            reasons.append(f"process-reason-{status['reason']}")
    receipt_path = os.path.join(base, RECEIPT_DIR, RESULT)
    verdict, findings = _verify_receipt(module, base)
    receipt = _load_receipt(module, receipt_path) if verdict != 'pending' else None
    if duration is None and receipt is not None and type(receipt.get('durationSeconds')) in (int, float):
        duration = receipt['durationSeconds']
    matches = _pid_matches(receipt, record)
    final = 'INCOMPLETE'
    if verdict == 'verified' and not reasons and matches and record['executionSuccess'] is True:
        final = 'PASS'
    elif verdict == 'rejected' and not reasons and matches and 'child-nonzero-exit' in findings \
            and set(findings) <= NONZERO_ONLY and _clean_nonzero(record):
        final, findings = 'FAIL', ['check-nonzero-exit']
    else:
        if verdict == 'verified':
            reasons.append('process-record-not-clean')
        reasons += _refusal_codes(receipt)
        if record:
            reasons += [f'process-{reason}' for reason in record['reasons']]
    return CheckOutcome(prepared.spec.check_id, prepared.spec.attempt_id, final,
                        receipt_path if os.path.lexists(receipt_path) else None, process_path,
                        _unique(reasons + findings), duration, prepared.spec.expected_sha)


def _not_run(prepared: PreparedCheck, code: str, started: float | None) -> CheckOutcome:
    duration = None if started is None else round(time.monotonic() - started, 3)
    return CheckOutcome(prepared.spec.check_id, prepared.spec.attempt_id, 'INCOMPLETE', None,
                        None, (code,), duration, prepared.spec.expected_sha)


def _evidence_args(prepared: PreparedCheck) -> argparse.Namespace:
    spec = prepared.spec
    return argparse.Namespace(label=spec.check_id, source_only=None, expected_sha=spec.expected_sha,
                              timeout=float(spec.timeout_seconds), command=list(spec.argv),
                              cwd=spec.cwd, out_dir=os.path.join(prepared.attempt_dir, RECEIPT_DIR))


# ---------------------------------------------------------------- public operations

def run_check(prepared: PreparedCheck, *, on_spawn: Callable, authorize_release: Callable,
              should_stop: Callable) -> CheckOutcome:
    """Run one predeclared check once; a rerun needs a NEW predeclared attempt id."""
    _require_prepared(prepared)
    started = time.monotonic()
    try:
        module = _verified_inputs(prepared)
        base = prepared.attempt_dir
        if any(os.path.lexists(os.path.join(base, name)) for name in (RECEIPT_DIR, PROCESS_DIR, TMP_DIR)):
            raise CheckError('attempt-already-run')
        for name in (PROCESS_DIR, TMP_DIR):
            os.mkdir(os.path.join(base, name), 0o700)
    except CheckError as err:
        return _not_run(prepared, err.code, started)
    except OSError:
        return _not_run(prepared, 'attempt-setup-failed', started)
    backend = _Backend(prepared, module, on_spawn, authorize_release, should_stop)
    reasons = []
    try:
        if module.run_check(_evidence_args(prepared), supervisor=backend) == module.EXIT_USAGE:
            reasons.append('evidence-usage-error')
    except CheckError as err:
        reasons.append(err.code)  # no receipt is synthesized; raw artifacts stay for inspection
    except Exception:
        reasons.append('backend-error')
    return _classify(prepared, module, reasons, round(time.monotonic() - started, 3))


def run_checks(prepared_checks: Iterable[PreparedCheck], *, on_spawn: Callable,
               authorize_release: Callable, should_stop: Callable) -> tuple[CheckOutcome, ...]:
    """Run and collect EVERY predeclared check; a failure never short-circuits the rest."""
    return tuple(run_check(prepared, on_spawn=on_spawn, authorize_release=authorize_release,
                           should_stop=should_stop) for prepared in prepared_checks)


def inspect_check(prepared: PreparedCheck) -> CheckOutcome:
    """Read-only re-verification after a restart; never creates, finalizes or relabels."""
    _require_prepared(prepared)
    try:
        module = _verified_inputs(prepared)
    except CheckError as err:
        return _not_run(prepared, err.code, None)
    return _classify(prepared, module, [], None)


def request_stop(prepared: PreparedCheck) -> str:
    """Publish STOP through the helper; it signals only a positively owned group."""
    _require_prepared(prepared)
    attempt = os.path.join(prepared.attempt_dir, PROCESS_DIR, prepared.spec.attempt_id)
    if not os.path.lexists(attempt):
        return 'not-spawned'
    try:
        return process.request_stop(attempt)
    except process.ProcessError:
        return 'unknown'


def aggregate(outcomes: Iterable[CheckOutcome]) -> tuple[str, tuple[str, ...]]:
    """Any FAIL -> FAIL; all PASS -> PASS; otherwise (including none run) INCOMPLETE."""
    outcomes = tuple(outcomes)
    if not outcomes:
        return 'INCOMPLETE', ('no-checks-declared',)
    statuses = {outcome.status for outcome in outcomes}
    status = 'FAIL' if 'FAIL' in statuses else 'PASS' if statuses == {'PASS'} else 'INCOMPLETE'
    return status, tuple(f'{outcome.check_id}:{outcome.status}' for outcome in outcomes
                         if outcome.status != 'PASS')
