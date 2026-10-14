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
    --expected-sha: the cwd must be a Git checkout whose HEAD is FULLSHA and whose
    index and tracked worktree content equal that commit, with no untracked files.
    Skip-worktree/assume-unchanged entries, submodules and tracked paths routed through
    a configured content filter driver are refused (inspecting them would run
    repository-configured commands). All refusals happen BEFORE the child is launched. A HEAD change or a
    tracked-source change during the run fails the gate even when the child exits 0.
    --source-only: for archives and other unversioned trees; DESCRIPTION records what
    the source is. Pre-existing files are fingerprinted before and after the run.

verify
    Read-only. Compares receipts with predeclared checks. A missing receipt is
    pending. Every receipt is first validated against the closed v1 schema (all
    emitted fields required with exact JSON types, no unknown fields); only then are
    identity, gate, timing, input and logs compared. A wrong identity, schema
    violation, failed gate, mutated input, symlinked manifest or evidence path,
    non-regular/aliased log or altered log hash is rejected. Diagnostics are fixed
    codes and never echo untrusted content.

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
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SCHEMA = 'verified-handoff/evidence-receipt/v1'
LABEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
SHA_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
HEX64_RE = re.compile(r'^[0-9a-f]{64}$')
TIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$')
LOG_NAMES = ('stdout.log', 'stderr.log')
DEFAULT_TIMEOUT = 900.0
MAX_TIMEOUT = 86400.0
TERM_GRACE_SECONDS = 5.0
POLL_SECONDS = 0.05
CLOCK_SLACK_SECONDS = 1.0
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
    return git_input(root, b'', *args)


def git_input(root: Path, data: bytes, *args: str) -> bytes:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(root), *args], env=env, input=data,
                          capture_output=True, check=False)
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


def configured_filter_drivers(root: Path) -> set[bytes]:
    """Names of filter drivers with a configured command; config values are never read."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(root), 'config', '--name-only',
                           '--get-regexp', r'^filter\..*\.(clean|smudge|process)$'],
                          env=env, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if proc.returncode not in (0, 1):
        raise Refusal('git-query-failed')
    keys = proc.stdout.splitlines() if proc.returncode == 0 else []
    return {key.split(b'.', 1)[1].rsplit(b'.', 1)[0] for key in keys}


def content_filters_active(root: Path) -> bool:
    """True when a tracked path's filter attribute names a configured driver.

    Only then could inspecting content run a repository-configured command. Attribute
    lookup (`check-attr`) itself runs nothing.
    """
    drivers = configured_filter_drivers(root)
    if not drivers:
        return False
    paths = git(root, 'ls-files', '-z')
    if not paths:
        return False
    fields = git_input(root, paths, 'check-attr', '--stdin', '-z', 'filter').split(b'\0')
    return any(value in drivers for value in fields[2::3])


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


def status_counts(root: Path) -> tuple[int, int]:
    # Submodules are not recursed: their own configuration could run callbacks.
    raw = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all',
              '--ignore-submodules=all')
    tracked = untracked = 0
    fields = iter(raw.split(b'\0'))
    for field in fields:
        if len(field) < 4:
            continue
        if field.startswith(b'??'):
            untracked += 1
            continue
        tracked += 1
        if field[:1] in b'RC' or field[1:2] in b'RC':
            next(fields, None)  # a rename/copy source path is a separate field
    return tracked, untracked


def parse_entries(raw: bytes, sha_field: int) -> dict[bytes, tuple[bytes, bytes, bytes]]:
    """Map path -> (mode, object id, stage) for ls-tree (sha_field 2) or ls-files -s (1)."""
    entries = {}
    for record in raw.split(b'\0'):
        if b'\t' not in record:
            continue
        meta, path = record.split(b'\t', 1)
        parts = meta.split(b' ')
        stage = parts[2] if sha_field == 1 else b'0'
        entries[path] = (parts[0], parts[sha_field], stage)
    return entries


def worktree_blob_ids(root: Path, entries: dict) -> dict[bytes, bytes | None]:
    """Blob id of each tracked worktree entry, or None when its kind or mode differs.

    Only called after filter drivers are excluded, so `hash-object` applies built-in
    conversions only and runs no repository-configured command. Nothing is written.
    """
    ids: dict[bytes, bytes | None] = {}
    regular: list[bytes] = []
    for path, (mode, _oid, _stage) in entries.items():
        ids[path] = None
        local = root / os.fsdecode(path)
        try:
            info = local.lstat()
        except OSError:
            continue
        if mode in (b'100644', b'100755') and stat.S_ISREG(info.st_mode) and b'\n' not in path:
            if (mode == b'100755') == bool(info.st_mode & stat.S_IXUSR):
                regular.append(path)
        elif mode == b'120000' and stat.S_ISLNK(info.st_mode):
            target = os.fsencode(os.readlink(local))
            ids[path] = git_input(root, target, 'hash-object', '--no-filters', '--stdin').strip()
    if regular:
        output = git_input(root, b'\n'.join(regular) + b'\n', 'hash-object', '--stdin-paths')
        ids.update(zip(regular, output.split()))
    return ids


def head_content_mismatches(root: Path, head: str, index_raw: bytes) -> tuple[int, int]:
    """Count index or worktree entries that differ from HEAD, and count gitlinks."""
    tree = parse_entries(git(root, 'ls-tree', '-r', '-z', '--full-tree', head), 2)
    index = parse_entries(index_raw, 1)
    mismatches = len(set(tree) ^ set(index))
    gitlinks = sum(1 for mode, _oid, _stage in tree.values() if mode == b'160000')
    shared = {p: index[p] for p in tree.keys() & index.keys()}
    mismatches += sum(1 for p, entry in shared.items()
                      if entry[2] != b'0' or entry[:2] != tree[p][:2])
    files = {p: e for p, e in shared.items() if e[0] != b'160000'}
    actual = worktree_blob_ids(root, files)
    mismatches += sum(1 for p, entry in files.items() if actual.get(p) != entry[1])
    return mismatches, gitlinks


def git_state(root: Path) -> dict:
    """Committed-input identity, compared with HEAD content rather than trusted status.

    Tracked paths routed through a configured filter driver are refused instead of
    inspected, because inspecting them would execute that driver's command.
    """
    if content_filters_active(root):
        raise Refusal('content-filters-unsupported')
    head = git(root, 'rev-parse', '--verify', 'HEAD').decode().strip()
    flags = git(root, 'ls-files', '-v', '-z')
    # ls-files -v tags: 'S' marks skip-worktree; a lowercase tag marks assume-unchanged.
    flagged = sum(1 for e in flags.split(b'\0') if e and (e[:1] == b'S' or e[:1].islower()))
    tracked, untracked = status_counts(root)
    index = git(root, 'ls-files', '-s', '-z')
    mismatches, gitlinks = head_content_mismatches(root, head, index)
    paths = [os.fsdecode(p) for p in parse_entries(index, 1)]
    return {
        'head': head,
        'trackedChanges': tracked,
        'untrackedFiles': untracked,
        'flaggedIndexEntries': flagged,
        'headContentMismatches': mismatches,
        'gitlinks': gitlinks,
        'trackedCount': len(paths),
        'indexFingerprint': hashlib.sha256(index + b'\0flags\0' + flags).hexdigest(),
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


def committed_input_changed(before: dict, after: dict) -> bool:
    return bool(after['trackedChanges'] or after['flaggedIndexEntries']
                or after['headContentMismatches'] or after['gitlinks']
                or after['indexFingerprint'] != before['indexFingerprint']
                or after['trackedFingerprint'] != before['trackedFingerprint'])


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
        if committed_input_changed(before, after):
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
        if before['flaggedIndexEntries']:
            raise Refusal('index-flags-unsupported')
        if before['gitlinks']:
            raise Refusal('submodules-unsupported')
        if before['trackedChanges'] or before['untrackedFiles'] or before['headContentMismatches']:
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


def reject_constant(_name: str):
    raise ValueError('non-finite JSON constant')


def load_json(path: Path):
    """Strict JSON: NaN/Infinity are rejected rather than parsed as floats. Integers
    beyond the interpreter's digit limit raise ValueError and are rejected too."""
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=reject_constant)


def load_manifest(path: Path) -> list[dict]:
    """Load checks. The manifest file itself must be a regular file, not a symlink.

    Trust boundary: the manifest's directory is canonicalized once and becomes the
    evidence root; directories ABOVE it are the caller's choice of location (common
    temporary roots are themselves symlinks on some systems). Every component BELOW
    the evidence root is checked without following links (evidence_dir_problem).
    """
    try:
        info = path.lstat()
    except (OSError, ValueError):
        raise ManifestError('manifest-unreadable') from None
    if stat.S_ISLNK(info.st_mode):
        raise ManifestError('manifest-symlink')
    if not stat.S_ISREG(info.st_mode):
        raise ManifestError('manifest-unreadable')
    try:
        base = path.resolve(strict=True).parent
        data = load_json(path)
    except (OSError, UnicodeDecodeError, ValueError):
        raise ManifestError('manifest-unreadable') from None
    if not isinstance(data, dict) or not isinstance(data.get('checks'), list) or not data['checks']:
        raise ManifestError('manifest-checks-missing')
    checks, labels, results = [], set(), set()
    for idx, raw in enumerate(data['checks']):
        check = normalize_check(raw, idx, base)
        if check['label'] in labels or check['resultParts'] in results:
            raise ManifestError('duplicate-check', idx)
        labels.add(check['label'])
        results.add(check['resultParts'])
        checks.append(check)
    return checks


def result_parts(raw: str) -> tuple[str, ...] | None:
    """A result path must be relative to the manifest directory with no '..' or '.' parts."""
    if '\\' in raw or raw.startswith('/'):
        return None
    parts = tuple(raw.split('/'))
    if len(parts) < 2 or any(p in ('', '.', '..') for p in parts):
        return None
    return parts


def normalize_check(raw, idx: int, base: Path) -> dict:
    if not isinstance(raw, dict):
        raise ManifestError('check-not-object', idx)
    label, cwd, command, result = (raw.get(k) for k in ('label', 'cwd', 'command', 'resultFile'))
    if not isinstance(label, str) or not LABEL_RE.match(label):
        raise ManifestError('invalid-label', idx)
    if not isinstance(cwd, str) or not cwd or not isinstance(result, str) or not result \
            or '\0' in cwd or '\0' in result:
        raise ManifestError('invalid-path', idx)
    parts = result_parts(result)
    if parts is None:
        raise ManifestError('invalid-result-path', idx)
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
            'base': base, 'resultParts': parts}


def evidence_dir_problem(base: Path, parts: tuple[str, ...]) -> str | None:
    """Every directory between the manifest directory and the receipt must be a real
    directory: a symlinked component anywhere would redirect the evidence."""
    current = base
    for part in parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return 'missing'
        except OSError:
            return 'unreadable'
        if stat.S_ISLNK(info.st_mode):
            return 'path-symlink'
        if not stat.S_ISDIR(info.st_mode):
            return 'path-not-directory'
    return None


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


# ---------------------------------------------------------------- receipt schema v1
#
# A receipt is validated against this closed schema BEFORE any semantic comparison.
# Every field the recorder emits for a launched child is required, with an exact JSON
# type: booleans are not integers, numbers are never coerced from strings, hashes are
# lowercase hexadecimal strings, and unknown fields are rejected (a new field requires
# a new schema version). Problems are reported as fixed codes built from schema paths,
# never from receipt content.

MAX_COUNT = 2 ** 63 - 1
MAX_SECONDS = 10 ** 9
SIGNAL_NAME_RE = re.compile(r'SIG[A-Z0-9]{1,12}')


def full(pattern: re.Pattern, value) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def is_count(value) -> bool:
    return type(value) is int and 0 <= value <= MAX_COUNT


def is_positive(value) -> bool:
    return type(value) is int and 0 < value <= MAX_COUNT


def is_seconds(value) -> bool:
    # Integers are range-checked as integers, so a huge value never reaches float().
    if type(value) is int:
        return 0 <= value <= MAX_SECONDS
    return type(value) is float and math.isfinite(value) and 0 <= value <= MAX_SECONDS


def is_text(value) -> bool:
    return type(value) is str and value != ''


def is_absolute(value) -> bool:
    return is_text(value) and os.path.isabs(value) and '\0' not in value


def is_bool(value) -> bool:
    return type(value) is bool


def is_null(value) -> bool:
    return value is None


def is_exit_code(value) -> bool:
    return value is None or (type(value) is int and 0 <= value <= 255)


def is_signal_name(value) -> bool:
    return full(SIGNAL_NAME_RE, value)


def list_of(predicate):
    return lambda value: type(value) is list and all(predicate(item) for item in value)


def is_arg(value) -> bool:
    return type(value) is str


def is_timestamp(value) -> bool:
    return parse_time(value) is not None


def is_description(value) -> bool:
    return is_text(value) and len(value) <= MAX_DESCRIPTION


def is_signal_sent(value) -> bool:
    return type(value) is str and (is_signal_name(value) or
                                   (value.endswith('-denied') and is_signal_name(value[:-7])))


def constant(expected):
    return lambda value: type(value) is type(expected) and value == expected


def one_of(*allowed):
    return lambda value: type(value) is str and value in allowed


class AnyOf(tuple):
    """Alternative object shapes for one position."""


LOG_RECORD = {'file': is_text, 'bytes': is_count, 'sha256': lambda v: full(HEX64_RE, v)}
COMMITTED_STATE = {
    'head': lambda v: full(SHA_RE, v), 'trackedChanges': is_count, 'untrackedFiles': is_count,
    'flaggedIndexEntries': is_count, 'headContentMismatches': is_count, 'gitlinks': is_count,
    'trackedCount': is_count, 'indexFingerprint': lambda v: full(HEX64_RE, v),
    'trackedFingerprint': lambda v: full(HEX64_RE, v),
}
SOURCE_STATE = {'fileCount': is_count, 'fingerprint': lambda v: full(HEX64_RE, v)}
UNAVAILABLE_STATE = {'error': is_text}
CHILD = {
    'launched': is_bool, 'pid': is_positive, 'timedOut': is_bool,
    'descendantsObservedAfterExit': is_bool, 'descendantsOutlivedDeadline': is_bool,
    'groupEmptyAtReceipt': is_bool, 'signalsSent': list_of(is_signal_sent),
    'exitCode': is_exit_code, 'signal': lambda v: v is None or is_signal_name(v),
}


def receipt_schema(mode: str) -> dict:
    committed = mode == 'committed'
    state = COMMITTED_STATE if committed else SOURCE_STATE
    return {
        'schema': constant(SCHEMA),
        'label': lambda v: full(LABEL_RE, v),
        'cwd': is_absolute,
        'mode': constant(mode),
        'expectedSha': (lambda v: full(SHA_RE, v)) if committed else is_null,
        'sourceOnly': is_null if committed else is_description,
        'command': {'executable': is_text, 'args': list_of(is_arg),
                    'resolvedExecutable': is_absolute,
                    'executableSha256': lambda v: full(HEX64_RE, v)},
        'timeoutSeconds': is_seconds,
        'limitations': constant(list(LIMITATIONS)),
        'startedAt': is_timestamp,
        'endedAt': is_timestamp,
        'durationSeconds': is_seconds,
        'child': CHILD,
        'logs': {'stdout': LOG_RECORD, 'stderr': LOG_RECORD},
        'input': {'before': state, 'after': AnyOf((state, UNAVAILABLE_STATE))},
        'gate': {'outcome': one_of('pass', 'fail'), 'reasons': list_of(is_text)},
    }


def schema_problems(value, spec, path: str) -> list[str]:
    if isinstance(spec, AnyOf):
        if any(not schema_problems(value, option, path) for option in spec):
            return []
        return [f'receipt-schema-invalid:{path}']
    if isinstance(spec, dict):
        if type(value) is not dict:
            return [f'receipt-schema-invalid:{path}']
        problems = []
        if set(value) - set(spec):
            problems.append(f'receipt-schema-unknown-field:{path}')
        for key, child_spec in spec.items():
            child_path = key if path == '.' else f'{path}/{key}'
            if key not in value:
                problems.append(f'receipt-schema-missing:{child_path}')
            else:
                problems.extend(schema_problems(value[key], child_spec, child_path))
        return problems
    return [] if spec(value) else [f'receipt-schema-invalid:{path}']


def receipt_schema_problems(receipt) -> list[str]:
    if type(receipt) is not dict:
        return ['receipt-schema-invalid:.']
    mode = receipt.get('mode')
    if mode not in ('committed', 'source-only'):
        return ['receipt-schema-invalid:mode']
    return schema_problems(receipt, receipt_schema(mode), '.')


# ---------------------------------------------------------------- semantic checks
# These run only on a schema-valid receipt, so every field has its exact type.

def parse_time(value) -> datetime | None:
    if not full(TIME_RE, value):
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def timing_reasons(receipt: dict) -> list[str]:
    reasons = []
    started, ended = parse_time(receipt['startedAt']), parse_time(receipt['endedAt'])
    if ended < started:
        reasons.append('invalid-timestamps')
    timeout, duration = receipt['timeoutSeconds'], receipt['durationSeconds']
    if not 0 < timeout <= MAX_TIMEOUT:
        reasons.append('invalid-timeout')
    if duration > timeout + CLOCK_SLACK_SECONDS \
            or duration > (ended - started).total_seconds() + CLOCK_SLACK_SECONDS:
        reasons.append('invalid-duration')
    return reasons


def child_reasons(child: dict) -> list[str]:
    reasons = []
    if child['launched'] is not True:
        reasons.append('child-not-launched')
    if child['signal'] is not None:
        reasons.append('child-signalled')
    if child['exitCode'] != 0:
        reasons.append('child-nonzero-exit')
    if child['timedOut'] or not child['groupEmptyAtReceipt'] \
            or child['descendantsOutlivedDeadline'] or child['signalsSent']:
        reasons.append('child-not-cleanly-finished')
    return reasons


def identity_reasons(check: dict, receipt: dict) -> list[str]:
    reasons = []
    if receipt['label'] != check['label']:
        reasons.append('wrong-label')
    if receipt['cwd'] != check['cwd']:
        reasons.append('wrong-cwd')
    command = receipt['command']
    if command['executable'] != check['command']['executable'] \
            or command['args'] != check['command']['args']:
        reasons.append('wrong-command')
    expected_mode = 'committed' if check['expectedSha'] else 'source-only'
    if receipt['mode'] != expected_mode or receipt['expectedSha'] != check['expectedSha'] \
            or receipt['sourceOnly'] != check['sourceOnly']:
        reasons.append('wrong-source-identity')
    return reasons


CLEAN_BEFORE = ('trackedChanges', 'untrackedFiles', 'flaggedIndexEntries',
                'headContentMismatches', 'gitlinks')
CLEAN_AFTER = ('trackedChanges', 'flaggedIndexEntries', 'headContentMismatches', 'gitlinks')
STABLE_COMMITTED = ('head', 'trackedCount', 'indexFingerprint', 'trackedFingerprint')


def input_reasons(check: dict, receipt: dict) -> list[str]:
    before, after = receipt['input']['before'], receipt['input']['after']
    if 'error' in after:
        return ['input-state-unavailable']
    if receipt['mode'] == 'committed':
        reasons = []
        if before['head'] != check['expectedSha'] or after['head'] != check['expectedSha']:
            reasons.append('wrong-commit')
        if any(before[k] for k in CLEAN_BEFORE) or any(after[k] for k in CLEAN_AFTER) \
                or any(before[k] != after[k] for k in STABLE_COMMITTED):
            reasons.append('input-mutated')
        return reasons
    if before != after:
        return ['input-mutated']
    return []


def outcome_reasons(check: dict, receipt: dict) -> list[str]:
    gate = receipt['gate']
    reasons = [] if gate['outcome'] == 'pass' and gate['reasons'] == [] else ['gate-not-passed']
    return reasons + timing_reasons(receipt) + child_reasons(receipt['child']) \
        + input_reasons(check, receipt)


def log_reasons(result_dir: Path, receipt: dict) -> list[str]:
    reasons = []
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
        record = receipt['logs'][key]
        try:
            actual = sha256_file(path)
        except OSError:
            reasons.append(f'{key}-log-unreadable')
            continue
        if record['file'] != name or record['sha256'] != actual or record['bytes'] != info.st_size:
            reasons.append(f'{key}-log-altered')
    if len(inodes) == 1 and not reasons:
        reasons.append('logs-aliased')
    return reasons


def verify_check(check: dict) -> tuple[str, list[str]]:
    problem = evidence_dir_problem(check['base'], check['resultParts'])
    if problem == 'missing':
        return 'pending', ['receipt-missing']
    if problem:
        return 'rejected', [f'receipt-{problem}']
    result_path = check['base'].joinpath(*check['resultParts'])
    problem = regular_file_problem(result_path)
    if problem == 'missing':
        return 'pending', ['receipt-missing']
    if problem:
        return 'rejected', [f'receipt-{problem}']
    try:
        if result_path.stat().st_size > MAX_RECEIPT_BYTES:
            return 'rejected', ['receipt-too-large']
        receipt = load_json(result_path)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return 'rejected', ['receipt-unparseable']
    problems = receipt_schema_problems(receipt)
    if problems:
        return 'rejected', problems
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
