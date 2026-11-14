#!/usr/bin/env python3
"""Support library for controller_engine.py (stdlib only; not a CLI).

Bounded read-only Git queries run through the shared owned-process helper
(controller_process), private state directories, the native assignment prompt, review
evidence (inline, or a collision-checked bundle inside the reviewer worktree) and the
destination checks the engine applies to every effect spec before it acts or recovers.
It holds no policy, ledger or scheduling state and grants nothing.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import stat
import time
from urllib.parse import urlsplit

import controller_effects as fx
import controller_process as process

BRANCH_ROOT = 'sdlc-controller/'
QUERY_TIMEOUT = 120.0
QUERY_GRACE = 2.0
QUERY_LINGER = 1.0
SETTLE_MARGIN = 30.0
FILE_LIMIT = 4 << 20
INLINE_LIMIT = 192 << 10
MARKERS = frozenset({'SDLC_ASSIGNMENT', 'END_SDLC_ASSIGNMENT'})
ENVELOPE_KEYS = frozenset({'version', 'role', 'plan_id', 'task_id', 'kind', 'objective', 'base_sha',
                           'result_sha', 'write_scope', 'acceptance', 'dependencies', 'checks',
                           'evidence_manifest'})
_READ = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)
_NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


class EngineError(Exception):
    """Engine refusal with a fixed code; the detail never carries credentials."""

    def __init__(self, code, detail=''):
        super().__init__(f'{code}: {detail}' if detail else code)
        self.code = code


# ---- private files ------------------------------------------------------------------

def private_dir(path, mode='ensure'):
    """An owner-only 0700 directory, else EngineError. ``mode`` 'ensure' creates it when
    absent; 'new' must create it now (an existing entry is ``state_exists``); 'existing'
    never creates it (absence is ``state_missing``: a lost directory is never recreated)."""
    path = os.fspath(path)
    name = os.path.basename(path)
    if mode not in ('ensure', 'new', 'existing'):
        raise ValueError(f'private_dir mode {mode!r}')
    if mode != 'existing':
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            if mode == 'new':
                raise EngineError('state_exists', name) from None
        except OSError as err:
            raise EngineError('state_unwritable', name) from err
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise EngineError('state_missing', name) from None
    except OSError as err:
        raise EngineError('state_unreadable', name) from err
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or os.path.realpath(path) != path):
        raise EngineError('state_unsafe', os.path.basename(path))
    return path


def read_file(path, limit=FILE_LIMIT):
    """(sha256, bytes) of a regular file read without following a final symlink."""
    try:
        fd = os.open(path, _READ)
    except OSError as err:
        raise EngineError('file_unreadable', os.path.basename(str(path))) from err
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise EngineError('file_unsafe', os.path.basename(str(path)))
        chunks = []
        while chunk := os.read(fd, 1 << 16):
            chunks.append(chunk)
    finally:
        os.close(fd)
    data = b''.join(chunks)
    return hashlib.sha256(data).hexdigest(), data


def write_new(path, data):
    fd = os.open(path, _NEW, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def executable(name, required=True):
    found = shutil.which(name)
    if not found:
        if required:
            raise EngineError('tool_missing', name)
        return None
    return os.path.realpath(found)


def short_hash(*parts):
    return hashlib.sha256('\0'.join(parts).encode('utf-8')).hexdigest()[:20]


# ---- bounded Git queries --------------------------------------------------------------

class Queries:
    """Read-only Git queries. Each is one NEW owned helper attempt under a private root:
    literal argv, anchored group, the helper's timeout and a finalized lifecycle record;
    raw logs stay there as evidence."""

    def __init__(self, root, git):
        self.root, self.git, self.count = private_dir(root), git, 0

    def run(self, cwd, *args, accept=(0,)):
        self.count += 1
        attempt_id = f'q{time.time_ns()}-{os.getpid()}-{self.count}'
        argv = (self.git, '--no-replace-objects', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                '-C', cwd, *args)
        spec = process.CommandSpec(argv, cwd, b'', attempt_id)
        try:
            pending = process.spawn(process.prepare(self.root, spec, QUERY_TIMEOUT, QUERY_GRACE,
                                                    QUERY_LINGER))
        except process.ProcessError as err:
            raise EngineError('query_launch', err.code) from None
        try:
            owned = pending.release()
        except process.ProcessError as err:
            pending.abort()
            raise EngineError('query_launch', err.code) from None
        record = _settle_query(owned)
        if (record['termination'] != 'exited' or record['exitCode'] not in accept or record['forced']
                or record['lingering'] or record['groupEmpty'] is not True):
            raise EngineError('query_failed', args[0])
        return record['exitCode'], _stdout(record)

    def text(self, cwd, *args):
        return self.run(cwd, *args)[1].decode('utf-8', 'replace').strip()

    def head(self, cwd):
        return self.text(cwd, 'rev-parse', '--verify', '--quiet', 'HEAD^{commit}')

    def branch(self, cwd):
        code, out = self.run(cwd, 'symbolic-ref', '--quiet', 'HEAD', accept=(0, 1))
        name = out.decode('utf-8', 'replace').strip()
        return name[len('refs/heads/'):] if code == 0 and name.startswith('refs/heads/') else None

    def ancestor(self, cwd, older, newer):
        return self.run(cwd, 'merge-base', '--is-ancestor', older, newer, accept=(0, 1))[0] == 0

    def tree(self, cwd, sha):
        return self.text(cwd, 'rev-parse', '--verify', f'{sha}^{{tree}}')

    def changed(self, cwd):
        """[(XY, path)] of tracked changes and untracked files (renames disabled)."""
        out = self.run(cwd, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--no-renames')[1]
        entries = []
        for item in out.split(b'\0'):
            if len(item) > 3:
                entries.append((item[:2].decode('ascii', 'replace'),
                                item[3:].decode('utf-8', 'surrogateescape')))
        return entries

    def untracked(self, cwd):
        return sorted(path for code, path in self.changed(cwd) if code == '??')

    def tracked_clean(self, cwd):
        return not self.run(cwd, 'status', '--porcelain=v1', '-z', '--untracked-files=no')[1].strip(b'\0')

    def recover(self):
        """Settle query attempts left by an earlier controller: STOP for live owned ones,
        evidence-only finalize for settled ones. Returns how many are still unresolved."""
        unresolved = 0
        for name in sorted(os.listdir(self.root)):
            path = os.path.join(self.root, name)
            try:
                state = process.read_status(path)['state']
                if state in process.ACTIVE_STATES:
                    process.request_stop(path)
                    unresolved += 1
                elif state in process.FINALIZABLE_STATES:
                    process.finalize(path)
            except process.ProcessError as err:
                if err.code != 'already-finalized':
                    unresolved += 1
        return unresolved


def _settle_query(owned):
    deadline = time.monotonic() + QUERY_TIMEOUT + QUERY_GRACE + QUERY_LINGER + SETTLE_MARGIN
    while True:
        recovery = owned.poll()
        if recovery.state in process.FINALIZABLE_STATES:
            break
        live = recovery.state in process.ACTIVE_STATES or (
            recovery.state == 'unknown' and recovery.identity_status != 'not-owned')
        if not live or time.monotonic() >= deadline:
            with contextlib.suppress(process.ProcessError):
                owned.request_stop()
            raise EngineError('query_unsettled', recovery.state)
        time.sleep(0.01)
    for _ in range(500):
        try:
            return owned.finalize()
        except process.ProcessError as err:
            if err.code != 'bootstrap-unreaped':
                raise EngineError('query_unsettled', err.code) from None
            time.sleep(0.01)
    raise EngineError('query_unsettled', 'bootstrap-unreaped')


def _stdout(record):
    reference = record['logs']['stdout']
    if reference is None:
        raise EngineError('query_log_missing')
    digest, data = read_file(reference['path'], limit=64 << 20)
    if digest != reference['sha256'] or len(data) != reference['size']:
        raise EngineError('query_log_mismatch')
    return data


# ---- native assignment ----------------------------------------------------------------

def _guard(line):
    return '| ' + line if line.strip() in MARKERS else line


def quoted(text):
    """Untrusted text (logs, producer notes) as quoted data lines; never instructions."""
    return '\n'.join('| ' + line for line in text.replace('\0', '\\0').splitlines()) or '| (empty)'


def assignment(envelope, sections):
    """SDLC_ASSIGNMENT / one compact JSON line / END_SDLC_ASSIGNMENT, then the human
    sections. A section line equal to a marker is quoted, so the header stays unique."""
    if set(envelope) != ENVELOPE_KEYS or envelope['version'] != 1:
        raise EngineError('envelope_fields')
    lines = ['SDLC_ASSIGNMENT', json.dumps(envelope, sort_keys=True, separators=(',', ':')),
             'END_SDLC_ASSIGNMENT', '']
    for title, text in sections:
        lines.append(f'## {title}')
        lines.extend(_guard(line) for line in text.replace('\0', '\\0').splitlines())
        lines.append('')
    return '\n'.join(lines) + '\n'


# ---- review evidence ------------------------------------------------------------------

def review_evidence(items, worktree, bundle_name, queries):
    """Raw check evidence for a reviewer. ``items`` are (label, path, expected sha256 or
    None); a digest mismatch is refused. Small evidence is inlined as quoted data; larger
    evidence is copied byte-exactly into a NEW untracked bundle inside the reviewer
    worktree with a hash manifest. Returns (manifest relative path | None, text, bundle)."""
    files = []
    for label, path, expected in items:
        digest, data = read_file(path)
        if expected is not None and digest != expected:
            raise EngineError('evidence_mismatch', label)
        files.append((label, path, digest, data))
    if not files:
        return None, 'No declared checks: no check ran, so there is no check evidence.', None
    if sum(len(item[3]) for item in files) <= INLINE_LIMIT:
        text = '\n\n'.join(f'### {label}\nsource: {path}\nsha256: {digest} ({len(data)} bytes)\n'
                           + quoted(data.decode('utf-8', 'replace'))
                           for label, path, digest, data in files)
        return None, text, None
    target = os.path.join(worktree, bundle_name)
    if os.path.lexists(target) or queries.run(worktree, 'ls-files', '-z', '--', bundle_name)[1]:
        raise EngineError('evidence_collision', bundle_name)
    os.mkdir(target, 0o700)
    entries = []
    for index, (label, path, digest, data) in enumerate(files):
        name = f'{index:02d}.txt'
        write_new(os.path.join(target, name), data)
        entries.append({'file': name, 'label': label, 'source': path, 'sha256': digest, 'bytes': len(data)})
    manifest = (json.dumps({'version': 1, 'files': entries}, sort_keys=True, indent=2) + '\n').encode()
    write_new(os.path.join(target, 'manifest.json'), manifest)
    record = {'dir': target, 'files': {**{entry['file']: entry['sha256'] for entry in entries},
                                       'manifest.json': hashlib.sha256(manifest).hexdigest()}}
    text = (f'The raw check evidence is the immutable controller bundle {bundle_name}/manifest.json '
            'in this worktree; read every listed file (sha256 given) before the producer notes.')
    return f'{bundle_name}/manifest.json', text, record


def bundle_intact(record):
    if record is None:
        return True
    try:
        if set(os.listdir(record['dir'])) != set(record['files']):
            return False
        return all(read_file(os.path.join(record['dir'], name))[0] == digest
                   for name, digest in record['files'].items())
    except (OSError, EngineError):
        return False


# ---- effect destinations --------------------------------------------------------------

def github_target_ok(delivery, actual_url):
    """The configured remote URL is the frozen one and names github.com/<github_repo>."""
    url = delivery['remote_url']
    if actual_url != url:
        return False
    if url.startswith(('https://', 'ssh://')):
        parts = urlsplit(url)
        host, path = parts.hostname or '', parts.path.lstrip('/')
    elif '@' in url and ':' in url:
        host, path = url.split('@', 1)[1].split(':', 1)
    else:
        return False
    path = path[:-4] if path.endswith('.git') else path
    return host.lower() == 'github.com' and path.lower() == delivery['github_repo'].lower()


def _inside(path, root):
    return path.startswith(root + os.sep)


def _ours(branch):
    return branch.startswith(BRANCH_ROOT)


def _registered(path, branch, meta, ctx, any_epoch=False, exact=False):
    """The ledger registration of a plan integration workspace naming EXACTLY this path
    and branch, else None. Only the current context counts unless ``any_epoch`` (cleanup,
    or observe-only reconciliation). A ledger-written ``workspace`` id in ``meta`` must
    name that same row; with ``exact`` it is required (the recorded registration only)."""
    for row in ctx['plan_workspaces']:
        if (row['path'], row['branch']) != (path, branch) or not (any_epoch or row['current']):
            continue
        if (meta.get('workspace') if exact else meta.get('workspace', row['id'])) == row['id']:
            return row
    return None


def _private(path, branch, ctx):
    """A native task or candidate workspace: the private BRANCH_ROOT namespace, sharing
    neither path nor branch with any plan registration."""
    return _ours(branch) and not any(path == row['path'] or branch == row['branch']
                                     for row in ctx['plan_workspaces'])


def check_fx(kind, mapping, meta, ctx, observe_only=False):
    """Rebuild a strict effect spec and re-verify its ACTUAL destination (not just the
    envelope metadata): this repository and common dir, and controller-owned workspaces
    and branches -- the private BRANCH_ROOT namespace for task/candidate work, or exactly
    the path and branch of a ledger plan registration (``ctx['plan_workspaces']``) for
    plan integration work -- and for external kinds the frozen policy.delivery target.
    ``meta`` is the envelope metadata, which must agree with the spec. ``observe_only``
    (reconciling an already journalled effect; nothing is executed) also accepts a plan
    registration of an earlier context, but only the exact row the stored envelope names
    by its ledger-written ``workspace`` id. Returns the spec."""
    spec = fx.spec_from_mapping(kind, mapping)
    delivery, root = ctx['delivery'], ctx['workspaces']
    local = kind in (fx.WORKTREE_CREATE, fx.TASK_COMMIT, fx.INTEGRATE, fx.WORKTREE_REMOVE, fx.PUSH)
    if local and (spec.repo, spec.common_dir) != (ctx['repo'], ctx['common_dir']):
        raise EngineError('effect_destination', kind)
    if kind == fx.WORKTREE_CREATE:
        plan = _registered(spec.path, spec.branch, meta, ctx, any_epoch=observe_only, exact=observe_only)
        ok = (_inside(spec.path, root)
              and (_private(spec.path, spec.branch, ctx)
                   or (plan is not None and spec.base_sha == plan['base_sha']))
              and all(meta.get(key) == value for key, value in (
                  ('path', spec.path), ('branch', spec.branch), ('base_sha', spec.base_sha))))
    elif kind == fx.TASK_COMMIT:
        ok = (_inside(spec.worktree, root) and _private(spec.worktree, spec.branch, ctx)
              and (meta.get('path'), meta.get('branch')) == (spec.worktree, spec.branch))
    elif kind == fx.INTEGRATE:
        ok = (_inside(spec.integration_worktree, root)
              and _registered(spec.integration_worktree, spec.target_branch, meta, ctx,
                              any_epoch=observe_only, exact=observe_only) is not None
              and _private(None, spec.task_branch, ctx)
              and (meta.get('expected_base'), meta.get('result'), meta.get('branch'))
              == (spec.expected_base, spec.task_result, spec.target_branch))
    elif kind == fx.WORKTREE_REMOVE:
        ok = (_inside(spec.path, root) and spec.cleanup_root == root
              and (_private(spec.path, spec.branch, ctx)
                   or _registered(spec.path, spec.branch, meta, ctx, any_epoch=True) is not None))
    elif delivery is None:
        ok = False
    elif kind == fx.PUSH:
        ok = (spec.remote == delivery['remote'] and spec.remote_url == delivery['remote_url']
              and spec.base_branch == delivery['base_branch'] and _private(None, spec.local_branch, ctx)
              and spec.remote_branch.startswith(delivery['branch_prefix'])
              and (meta.get('branch'), meta.get('result')) == (spec.remote_branch, spec.expected_result))
    elif kind == fx.PR_CREATE:
        ok = (spec.github_repo == delivery['github_repo'] and spec.base_branch == delivery['base_branch']
              and (meta.get('branch'), meta.get('result')) == (spec.head_branch, spec.head_sha))
    else:
        ok = (spec.github_repo == delivery['github_repo'] and spec.base_branch == delivery['base_branch']
              and spec.required_checks == tuple(delivery['required_checks'])
              and spec.method == delivery['merge_method']
              and (meta.get('branch'), meta.get('result')) == (spec.head_branch, spec.expected_head))
    if not ok:
        raise EngineError('effect_destination', kind)
    return spec
