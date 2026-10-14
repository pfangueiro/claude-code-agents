#!/usr/bin/env python3
"""Run one predeclared check and record a receipt; verify receipts against a manifest.

Usage:
    evidence.py run --cwd DIR --out-dir NEW_DIR --label LABEL
                    (--expected-sha FULLSHA | --source-only DESCRIPTION)
                    [--timeout SECONDS] -- COMMAND [ARGS...]
    evidence.py verify --manifest FILE

run
    Launches COMMAND as a literal argv (never through a shell) in its own process
    group. --out-dir must not exist; it is created for this run only and receives
    stdout.log, stderr.log and an atomically written result.json.
    --expected-sha: the cwd must be a clean Git checkout whose HEAD is FULLSHA; dirty
    or mismatched input is refused BEFORE the child is launched. A HEAD change or a
    tracked-source change during the run fails the gate even when the child exits 0.
    --source-only: for archives and other unversioned trees; DESCRIPTION records what
    the source is. Pre-existing files are fingerprinted before and after the run.

verify
    Read-only. Compares receipts with predeclared checks. A missing receipt is
    pending; a wrong identity, failed gate, mutated input, non-regular/aliased log
    or altered log hash is rejected. Diagnostics are fixed codes and never echo
    untrusted manifest or receipt content.

Exit codes:
    run:    0 gate passed, 1 child ran and the gate failed, 2 usage error,
            3 refused or not launched (no child ran)
    verify: 0 every check verified, 1 at least one rejected, 2 manifest invalid,
            3 none rejected but at least one pending

Limits (stated in every receipt):
    A receipt is necessary evidence, not proof of producer identity, honest
    predeclaration, semantic test coverage, review, CI or deployment. Hashes detect
    later log edits only when the receipt itself is untouched; nothing here is
    cryptographically authenticated. Input fingerprints are taken before and after
    the run, so a change reverted during the run is not detected. Descendants that
    leave the run's process group (for example via a new session) are not observed.
    The environment is inherited by the child and is not recorded.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'verified-handoff/evidence-receipt/v1'
LABEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
SHA_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
LOG_NAMES = ('stdout.log', 'stderr.log')
DEFAULT_TIMEOUT = 900.0
MAX_TIMEOUT = 86400.0
TERM_GRACE_SECONDS = 5.0
POLL_SECONDS = 0.05
MAX_DESCRIPTION = 500
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
GIT_SAFE = ['-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false']
LIMITATIONS = (
    'necessary evidence only: not producer identity, honest predeclaration, '
    'semantic coverage, review, CI or deployment',
    'not cryptographically authenticated; log hashes are only as trustworthy as this receipt',
    'input is fingerprinted before and after; transient changes reverted during the run are not detected',
    'descendants that leave the run process group (for example a new session) are not observed',
    'environment is inherited by the child and not recorded',
)

EXIT_PASS, EXIT_FAIL, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2, 3


class Refusal(Exception):
    """Pre-launch refusal carrying a fixed reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def is_within(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


# ---------------------------------------------------------------- input state

def git(root: Path, *args: str) -> bytes:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(root), *args], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if proc.returncode != 0:
        raise Refusal('git-query-failed')
    return proc.stdout


def git_root(cwd: Path) -> Path | None:
    if shutil.which('git') is None:
        raise Refusal('git-unavailable')
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                          stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.decode().strip()).resolve()


def entry_digest(path: Path) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return 'absent'
    if stat.S_ISLNK(info.st_mode):
        return 'link:' + hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
    if stat.S_ISREG(info.st_mode):
        executable = 'x' if info.st_mode & stat.S_IXUSR else '-'
        return f'file{executable}:' + sha256_file(path)
    if stat.S_ISDIR(info.st_mode):
        return 'dir'
    return 'other'


def tree_digest(root: Path, rel_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(rel_paths):
        digest.update(os.fsencode(rel) + b'\0' + entry_digest(root / rel).encode() + b'\n')
    return digest.hexdigest()


def git_state(root: Path) -> dict:
    status = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    entries = [e for e in status.split(b'\0') if e]
    # Rename/copy records carry the source path as an extra NUL-separated field.
    records = [e for e in entries if len(e) > 3 and e[2:3] == b' ']
    tracked = sum(1 for e in records if not e.startswith(b'??'))
    untracked = sum(1 for e in records if e.startswith(b'??'))
    index = git(root, 'ls-files', '-s', '-z')
    paths = [os.fsdecode(e.split(b'\t', 1)[1]) for e in index.split(b'\0') if b'\t' in e]
    return {
        'head': git(root, 'rev-parse', '--verify', 'HEAD').decode().strip(),
        'trackedChanges': tracked,
        'untrackedFiles': untracked,
        'trackedCount': len(paths),
        'indexFingerprint': hashlib.sha256(index).hexdigest(),
        'trackedFingerprint': tree_digest(root, paths),
    }


def list_source_files(root: Path) -> list[str]:
    found: list[str] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        here = Path(current)
        found.extend((here / name).relative_to(root).as_posix() for name in files)
    return found


def source_state(root: Path, paths: list[str]) -> dict:
    return {'fileCount': len(paths), 'fingerprint': tree_digest(root, paths)}


# ---------------------------------------------------------------- run

def resolve_executable(name: str, cwd: Path) -> Path:
    if '/' in name:
        candidate = Path(name) if os.path.isabs(name) else cwd / name
    else:
        located = shutil.which(name)
        if located is None:
            raise Refusal('executable-not-found')
        candidate = Path(located)
    if not candidate.is_file():
        raise Refusal('executable-not-found')
    if not os.access(candidate, os.X_OK):
        raise Refusal('executable-not-executable')
    return candidate.resolve()


def group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_group(pgid: int, leader: subprocess.Popen) -> list[str]:
    """Signal only the run-created process group; return the signals actually sent.

    The leader is reaped while polling: some kernels report EPERM for a group whose
    only member is an unreaped zombie, which would otherwise look like a live group.
    """
    sent: list[str] = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        leader.poll()
        if not group_alive(pgid):
            break
        try:
            os.killpg(pgid, sig)
            sent.append(sig.name)
        except ProcessLookupError:
            break
        except PermissionError:
            sent.append(f'{sig.name}-denied')
            continue
        deadline = time.monotonic() + TERM_GRACE_SECONDS
        while time.monotonic() < deadline:
            leader.poll()
            if not group_alive(pgid):
                break
            time.sleep(POLL_SECONDS)
    return sent


def supervise(argv: list[str], executable: Path, cwd: Path, out_dir: Path,
              timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    with open(out_dir / 'stdout.log', 'xb') as out, open(out_dir / 'stderr.log', 'xb') as err:
        try:
            child = subprocess.Popen(argv, executable=str(executable), cwd=cwd,
                                     stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                     start_new_session=True, close_fds=True)
        except OSError as exc:
            code = errno.errorcode.get(exc.errno or 0, 'unknown')
            raise Refusal(f'launch-failed-{code.lower()}') from None
    pgid = child.pid
    result = {'launched': True, 'pid': child.pid, 'timedOut': False,
              'descendantsObservedAfterExit': False, 'descendantsOutlivedDeadline': False,
              'signalsSent': []}
    try:
        child.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        result['timedOut'] = True
        result['signalsSent'] = terminate_group(pgid, child)
        child.wait()
    if not result['timedOut'] and group_alive(pgid):
        # The leader exited but owned descendants remain; logs are not final yet.
        result['descendantsObservedAfterExit'] = True
        while time.monotonic() < deadline and group_alive(pgid):
            time.sleep(POLL_SECONDS)
        if group_alive(pgid):
            result['descendantsOutlivedDeadline'] = True
            result['signalsSent'] = terminate_group(pgid, child)
    result['groupEmptyAtReceipt'] = not group_alive(pgid)
    code = child.returncode
    result['exitCode'] = code if code >= 0 else None
    result['signal'] = signal.Signals(-code).name if code < 0 else None
    return result


def log_record(path: Path) -> dict:
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha256_file(path)}


def write_receipt(out_dir: Path, receipt: dict) -> None:
    temp = out_dir / '.result.json.tmp'
    with open(temp, 'x', encoding='utf-8') as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, out_dir / 'result.json')


def gate_reasons(child: dict, mode: str, before: dict, after: dict, expected: str | None) -> list[str]:
    reasons: list[str] = []
    if child['timedOut']:
        reasons.append('timed-out')
    if child['signal'] is not None:
        reasons.append('child-signalled')
    elif child['exitCode'] != 0:
        reasons.append('child-nonzero-exit')
    if child['descendantsOutlivedDeadline'] or not child['groupEmptyAtReceipt']:
        reasons.append('descendants-alive')
    if 'error' in after:
        reasons.append('input-state-unavailable')
    elif mode == 'committed':
        if after['head'] != expected:
            reasons.append('head-changed')
        if after['trackedChanges'] or after['indexFingerprint'] != before['indexFingerprint'] \
                or after['trackedFingerprint'] != before['trackedFingerprint']:
            reasons.append('tracked-input-changed')
    elif after['fingerprint'] != before['fingerprint']:
        reasons.append('source-input-changed')
    return reasons


def prepare_input(args: argparse.Namespace, cwd: Path, out_dir: Path):
    """Return (mode, before_state, after_fn); raise Refusal before any launch."""
    if args.expected_sha is not None:
        if not SHA_RE.match(args.expected_sha):
            raise Refusal('expected-sha-not-full-hex')
        root = git_root(cwd)
        if root is None:
            raise Refusal('not-a-git-checkout')
        if is_within(out_dir, root):
            raise Refusal('out-dir-inside-input')
        before = git_state(root)
        if before['head'] != args.expected_sha:
            raise Refusal('head-mismatch')
        if before['trackedChanges'] or before['untrackedFiles']:
            raise Refusal('dirty-input')
        return 'committed', before, lambda: git_state(root)
    if is_within(out_dir, cwd):
        raise Refusal('out-dir-inside-input')
    paths = list_source_files(cwd)
    before = source_state(cwd, paths)
    return 'source-only', before, lambda: source_state(cwd, paths)


def create_out_dir(raw: str) -> Path:
    out_dir = Path(raw).absolute()
    out_dir.parent.resolve(strict=True)
    os.mkdir(out_dir, 0o700)
    return out_dir.resolve()


def run_check(args: argparse.Namespace) -> int:
    if not LABEL_RE.match(args.label):
        return usage('invalid-label')
    if args.source_only is not None and not 0 < len(args.source_only) <= MAX_DESCRIPTION:
        return usage('invalid-source-description')
    if not 0 < args.timeout <= MAX_TIMEOUT:
        return usage('invalid-timeout')
    argv = list(args.command)
    if argv and argv[0] == '--':
        argv = argv[1:]
    if not argv:
        return usage('missing-command')
    cwd = Path(args.cwd).resolve()
    if not cwd.is_dir():
        return usage('cwd-not-directory')
    try:
        out_dir = create_out_dir(args.out_dir)
    except FileExistsError:
        return usage('out-dir-exists')
    except OSError:
        return usage('out-dir-uncreatable')

    receipt: dict = {
        'schema': SCHEMA, 'label': args.label, 'cwd': str(cwd),
        'mode': 'committed' if args.expected_sha is not None else 'source-only',
        'expectedSha': args.expected_sha, 'sourceOnly': args.source_only,
        'command': {'executable': argv[0], 'args': argv[1:], 'resolvedExecutable': None,
                    'executableSha256': None},
        'timeoutSeconds': args.timeout, 'limitations': list(LIMITATIONS),
        'startedAt': utc_now(),
    }
    try:
        mode, before, after_fn = prepare_input(args, cwd, out_dir)
        receipt['input'] = {'before': before}
        executable = resolve_executable(argv[0], cwd)
        receipt['command']['resolvedExecutable'] = str(executable)
        receipt['command']['executableSha256'] = sha256_file(executable)
        started = time.monotonic()
        child = supervise(argv, executable, cwd, out_dir, args.timeout)
    except Refusal as refusal:
        receipt.update(endedAt=utc_now(), child={'launched': False},
                       gate={'outcome': 'refused', 'reasons': [refusal.code]})
        write_receipt(out_dir, receipt)
        print(json.dumps({'outcome': 'refused', 'reasons': [refusal.code], 'outDir': str(out_dir)}))
        return EXIT_REFUSED
    receipt['durationSeconds'] = round(time.monotonic() - started, 3)
    receipt['child'] = child
    receipt['logs'] = {name.split('.')[0]: log_record(out_dir / name) for name in LOG_NAMES}
    try:
        after = after_fn()
    except Refusal as refusal:
        after = {'error': refusal.code}
    receipt['input'] = {'before': before, 'after': after}
    reasons = gate_reasons(child, mode, before, after, args.expected_sha)
    receipt['gate'] = {'outcome': 'fail' if reasons else 'pass', 'reasons': reasons}
    receipt['endedAt'] = utc_now()
    write_receipt(out_dir, receipt)
    print(json.dumps({'outcome': receipt['gate']['outcome'], 'reasons': reasons,
                      'exitCode': child['exitCode'], 'signal': child['signal'],
                      'outDir': str(out_dir)}))
    return EXIT_FAIL if reasons else EXIT_PASS


def usage(code: str) -> int:
    print(json.dumps({'outcome': 'usage-error', 'reasons': [code]}), file=sys.stderr)
    return EXIT_USAGE


# ---------------------------------------------------------------- verify

class ManifestError(Exception):
    def __init__(self, code: str, index: int | None = None):
        super().__init__(code)
        self.code, self.index = code, index


def load_manifest(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ManifestError('manifest-unreadable') from None
    if not isinstance(data, dict) or not isinstance(data.get('checks'), list) or not data['checks']:
        raise ManifestError('manifest-checks-missing')
    checks, labels, results = [], set(), set()
    for idx, raw in enumerate(data['checks']):
        check = normalize_check(raw, idx, path.parent)
        if check['label'] in labels or check['resultFile'] in results:
            raise ManifestError('duplicate-check', idx)
        labels.add(check['label'])
        results.add(check['resultFile'])
        checks.append(check)
    return checks


def normalize_check(raw, idx: int, base: Path) -> dict:
    if not isinstance(raw, dict):
        raise ManifestError('check-not-object', idx)
    label, cwd, command, result = (raw.get(k) for k in ('label', 'cwd', 'command', 'resultFile'))
    if not isinstance(label, str) or not LABEL_RE.match(label):
        raise ManifestError('invalid-label', idx)
    if not isinstance(cwd, str) or not cwd or not isinstance(result, str) or not result:
        raise ManifestError('invalid-path', idx)
    if not isinstance(command, dict) or not isinstance(command.get('executable'), str) \
            or not command['executable'] or not isinstance(command.get('args'), list) \
            or not all(isinstance(a, str) for a in command['args']):
        raise ManifestError('invalid-command', idx)
    sha, source = raw.get('expectedSha'), raw.get('sourceOnly')
    if (sha is None) == (source is None):
        raise ManifestError('identity-not-exclusive', idx)
    if sha is not None and (not isinstance(sha, str) or not SHA_RE.match(sha)):
        raise ManifestError('invalid-expected-sha', idx)
    if source is not None and (not isinstance(source, str) or not 0 < len(source) <= MAX_DESCRIPTION):
        raise ManifestError('invalid-source-description', idx)
    return {'label': label, 'cwd': str((base / cwd).resolve()),
            'command': {'executable': command['executable'], 'args': list(command['args'])},
            'expectedSha': sha, 'sourceOnly': source,
            'resultFile': str((base / result).absolute())}


def regular_file_problem(path: Path) -> str | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'unreadable'
    if stat.S_ISLNK(info.st_mode):
        return 'symlink'
    if stat.S_ISDIR(info.st_mode):
        return 'directory'
    if not stat.S_ISREG(info.st_mode):
        return 'not-regular'
    if info.st_nlink != 1:
        return 'aliased'
    if not os.access(path, os.R_OK):
        return 'unreadable'
    return None


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def identity_reasons(check: dict, receipt: dict) -> list[str]:
    reasons = []
    if receipt.get('schema') != SCHEMA:
        reasons.append('wrong-schema')
    if receipt.get('label') != check['label']:
        reasons.append('wrong-label')
    if receipt.get('cwd') != check['cwd']:
        reasons.append('wrong-cwd')
    command = as_dict(receipt.get('command'))
    if command.get('executable') != check['command']['executable'] \
            or command.get('args') != check['command']['args']:
        reasons.append('wrong-command')
    expected_mode = 'committed' if check['expectedSha'] else 'source-only'
    if receipt.get('mode') != expected_mode or receipt.get('expectedSha') != check['expectedSha'] \
            or receipt.get('sourceOnly') != check['sourceOnly']:
        reasons.append('wrong-source-identity')
    return reasons


def outcome_reasons(check: dict, receipt: dict) -> list[str]:
    reasons = []
    gate, child = as_dict(receipt.get('gate')), as_dict(receipt.get('child'))
    if gate.get('outcome') != 'pass' or gate.get('reasons') != []:
        reasons.append('gate-not-passed')
    if child.get('launched') is not True:
        reasons.append('child-not-launched')
    if child.get('signal') is not None:
        reasons.append('child-signalled')
    if child.get('exitCode') != 0:
        reasons.append('child-nonzero-exit')
    if child.get('timedOut') is not False or child.get('groupEmptyAtReceipt') is not True:
        reasons.append('child-not-cleanly-finished')
    data = as_dict(receipt.get('input'))
    before, after = as_dict(data.get('before')), as_dict(data.get('after'))
    if check['expectedSha']:
        if before.get('head') != check['expectedSha'] or after.get('head') != check['expectedSha']:
            reasons.append('wrong-commit')
        keys = ('indexFingerprint', 'trackedFingerprint')
        if before.get('trackedChanges') != 0 or before.get('untrackedFiles') != 0 \
                or after.get('trackedChanges') != 0 \
                or any(not before.get(k) or before.get(k) != after.get(k) for k in keys):
            reasons.append('input-mutated')
    elif not before.get('fingerprint') or before.get('fingerprint') != after.get('fingerprint'):
        reasons.append('input-mutated')
    return reasons


def log_reasons(result_dir: Path, receipt: dict) -> list[str]:
    reasons = []
    logs = as_dict(receipt.get('logs'))
    inodes = set()
    for name in LOG_NAMES:
        key = name.split('.')[0]
        path = result_dir / name
        problem = regular_file_problem(path)
        if problem:
            reasons.append(f'{key}-log-{problem}')
            continue
        info = path.lstat()
        inodes.add((info.st_dev, info.st_ino))
        record = as_dict(logs.get(key))
        try:
            actual = sha256_file(path)
        except OSError:
            reasons.append(f'{key}-log-unreadable')
            continue
        if record.get('file') != name or record.get('sha256') != actual \
                or record.get('bytes') != info.st_size:
            reasons.append(f'{key}-log-altered')
    if len(inodes) == 1 and not reasons:
        reasons.append('logs-aliased')
    return reasons


def verify_check(check: dict) -> tuple[str, list[str]]:
    result_path = Path(check['resultFile'])
    problem = regular_file_problem(result_path)
    if problem == 'missing':
        return 'pending', ['receipt-missing']
    if problem:
        return 'rejected', [f'receipt-{problem}']
    try:
        if result_path.stat().st_size > MAX_RECEIPT_BYTES:
            return 'rejected', ['receipt-too-large']
        receipt = json.loads(result_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 'rejected', ['receipt-unparseable']
    if not isinstance(receipt, dict):
        return 'rejected', ['receipt-unparseable']
    reasons = identity_reasons(check, receipt) + outcome_reasons(check, receipt) \
        + log_reasons(result_path.parent, receipt)
    return ('rejected', reasons) if reasons else ('verified', [])


def verify_manifest(args: argparse.Namespace) -> int:
    try:
        checks = load_manifest(Path(args.manifest))
    except ManifestError as err:
        print(json.dumps({'outcome': 'manifest-invalid', 'reason': err.code, 'checkIndex': err.index}))
        return EXIT_USAGE
    results = []
    for idx, check in enumerate(checks):
        status, reasons = verify_check(check)
        results.append({'index': idx, 'label': check['label'], 'status': status, 'reasons': reasons})
    statuses = {r['status'] for r in results}
    outcome = 'rejected' if 'rejected' in statuses else 'pending' if 'pending' in statuses else 'verified'
    print(json.dumps({'outcome': outcome, 'checks': results, 'scope': LIMITATIONS[0]}, indent=2))
    return {'verified': EXIT_PASS, 'rejected': EXIT_FAIL, 'pending': EXIT_REFUSED}[outcome]


# ---------------------------------------------------------------- cli

class QuietParser(argparse.ArgumentParser):
    """Argument errors are reported as a fixed code, never by echoing input."""

    def error(self, message: str):
        sys.exit(usage('invalid-arguments'))


def parser() -> argparse.ArgumentParser:
    root = QuietParser(description='Record and verify command evidence receipts.')
    sub = root.add_subparsers(dest='action', required=True, parser_class=QuietParser)
    run = sub.add_parser('run', help='run one check and write a receipt')
    run.add_argument('--cwd', required=True)
    run.add_argument('--out-dir', required=True)
    run.add_argument('--label', required=True)
    identity = run.add_mutually_exclusive_group(required=True)
    identity.add_argument('--expected-sha')
    identity.add_argument('--source-only', metavar='DESCRIPTION')
    run.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT)
    run.add_argument('command', nargs=argparse.REMAINDER)
    check = sub.add_parser('verify', help='verify receipts against a manifest (read-only)')
    check.add_argument('--manifest', required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return run_check(args) if args.action == 'run' else verify_manifest(args)


if __name__ == '__main__':
    sys.exit(main())
