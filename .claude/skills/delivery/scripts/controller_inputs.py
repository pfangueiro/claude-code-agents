#!/usr/bin/env python3
"""Closed-schema v1 input boundary for optional local persistent delivery.

Validates an owner policy, a delivery plan and an authority declaration. This is an
input boundary, not a sandbox: declared checks are owner-approved exact argv that may
execute project code, and authority is an owner declaration guarded by private-file
checks -- not a cryptographic signature and not a boundary against the same OS user.
Nothing here creates state, reads credential or provider config contents, changes
HOME/USER, or contacts a network. Profile IDs are aliases, not proof of separate quota.
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import unicodedata

CODES = frozenset({'schema', 'path', 'file', 'git', 'dependency', 'unauthorized',
                   'unsupported', 'digest'})
PROVIDERS = ('claude', 'codex')
ROLES = ('implement', 'review')
EFFECTS = ('commit', 'integrate', 'push', 'pr', 'merge')
EXTERNAL_EFFECTS = ('push', 'pr', 'merge')
# Fixed root-owner mapping from engine catalog kinds to owner-policy effects. Workers
# never extend it; a catalog kind absent here carries no owner authority.
EFFECT_CATALOG = {'task.commit': 'commit', 'integrate': 'integrate', 'push': 'push',
                  'pr.create': 'pr', 'pr.merge': 'merge'}
# Internal kinds, permitted only inside the controller-owned state workspace (see ledger).
WORKSPACE_EFFECTS = ('worktree.create', 'worktree.remove')
MERGE_METHODS = ('merge', 'squash')
KINDS = ('feature', 'bugfix', 'refactor', 'investigation')
DEFAULT_CONFIG = {'claude': ('CLAUDE_CONFIG_DIR', '.claude'), 'codex': ('CODEX_HOME', '.codex')}
POLICY_KEYS = ('version', 'repository', 'profiles', 'auto_route', 'execution_enabled',
               'background_enabled', 'max_parallel', 'review_reserve', 'limits',
               'allowed_checks', 'effects', 'delivery', 'instruction_paths')
DELIVERY_KEYS = ('remote', 'remote_url', 'github_repo', 'base_branch', 'branch_prefix',
                 'required_checks', 'merge_method')
PROFILE_KEYS = ('id', 'provider', 'executable', 'config_dir', 'roles')
LIMIT_KEYS = ('max_attempts', 'attempt_seconds', 'max_total_seconds', 'max_no_progress',
              'max_cost_usd')
PLAN_KEYS = ('version', 'id', 'objective', 'input_revision', 'base_sha', 'tasks')
TASK_KEYS = ('id', 'objective', 'kind', 'depends_on', 'write_scope', 'resources', 'checks',
             'acceptance')
AUTHORITY_KEYS = ('version', 'plan_digest', 'effects', 'authorizer', 'approved_at')
MAX_FILE_BYTES = 1 << 20
MAX_RUNTIME_BYTES = 4 << 20
RUNTIME_DIGEST_VERSION = 'sdlc-runtime-v2'
# Known installed layouts only: the delivery skill directory name selects the edition and
# the one sibling bundle that ships the receipt producer. Nothing else is searched.
RUNTIME_LAYOUTS = {'delivery': ('claude', 'verified-handoff'),
                   'sdlc-delivery': ('codex', 'sdlc-verified-handoff')}
# Trusted non-controller bytes the engine loads: (stable logical key, bundle, relative path).
RUNTIME_RESOURCES = (
    ('delivery/SKILL.md', 'delivery', 'SKILL.md'),
    ('delivery/references/acceptance-by-task.md', 'delivery', 'references/acceptance-by-task.md'),
    ('delivery/references/task-contract.md', 'delivery', 'references/task-contract.md'),
    ('verified-handoff/scripts/evidence.py', 'handoff', 'scripts/evidence.py'),
)
CLOCK_SKEW = _dt.timedelta(minutes=5)
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
SAFE_RESOURCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}')
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
DIGEST = re.compile(r'[0-9a-f]{64}')
GITHUB_REPO = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100}')
REMOTE_URL = re.compile(r'(?:https|ssh)://[A-Za-z0-9._~@:/%+-]+'
                        r'|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._~/%+-]+')
BRANCH = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}')
UTC_STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z')
# Heuristics for credential-bearing argument forms and high-confidence secret shapes.
# Ordinary names and paths that merely contain words such as token or password are valid.
# These catch common mistakes only: passing them never proves a value holds no secret.
_SECRET_WORD = r'(?:password|passwd|secret|token|api[-_]?key|private[-_]?key)'
CREDENTIAL_FORM = re.compile(
    rf'(?:^|\s)--?(?:[a-z0-9]+[-_])*{_SECRET_WORD}=\S'
    rf'|^(?:[a-z0-9]+_)*{_SECRET_WORD}=\S'
    r'|\bauthorization\s*[:=]\s*\S|\bbearer\s+[a-z0-9._~+/=-]{8,}'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----', re.IGNORECASE)
CREDENTIAL_OPTION = re.compile(rf'--?(?:[a-z0-9]+[-_])*{_SECRET_WORD}', re.IGNORECASE)
CREDENTIAL_SHAPE = re.compile(
    r'\b(?:ghp|gho|ghs|ghu|ghr|github_pat)_[A-Za-z0-9]'
    r'|\bsk-(?:[a-z0-9]+-){0,3}[A-Za-z0-9_]{20,}'
    r'|\bAKIA[0-9A-Z]{16}|\bxox[abprs]-[A-Za-z0-9]|://[^/\s:@]+:[^/\s@]+@')


class InputError(Exception):
    """Rejected input; ``code`` is one of CODES."""

    def __init__(self, code: str, message: str) -> None:
        if code not in CODES:
            raise ValueError(f'unknown InputError code: {code}')
        super().__init__(f'{code}: {message}')
        self.code = code


# ---- primitive validators -------------------------------------------------------

def _has_control(value: str, allowed: str = '') -> bool:
    return any(unicodedata.category(ch)[0] == 'C' and ch not in allowed for ch in value)


def _fields(value, keys, where):
    if type(value) is not dict:
        raise InputError('schema', f'{where} must be an object')
    missing = sorted(set(keys) - value.keys())
    unknown = sorted(str(key) for key in value.keys() - set(keys))
    if missing or unknown:
        raise InputError('schema', f'{where}: missing {missing}, unknown {unknown}')
    return value


def _version(value, where):
    if type(value) is not int:
        raise InputError('schema', f'{where}.version must be the integer 1')
    if value != 1:
        raise InputError('unsupported', f'{where}.version {value} is not supported')


def _int(value, low, high, where):
    if type(value) is not int or not low <= value <= high:
        raise InputError('schema', f'{where} must be an integer in {low}..{high}')
    return value


def _bool(value, where):
    if type(value) is not bool:
        raise InputError('schema', f'{where} must be a boolean')
    return value


def _text(value, where, *, limit=4000, multiline=False):
    allowed = '\n\t' if multiline else ''
    if (type(value) is not str or not value.strip() or len(value) > limit
            or _has_control(value, allowed)):
        raise InputError('schema', f'{where} must be non-empty printable text of at most {limit}')
    return value


def _match(value, pattern, where):
    if type(value) is not str or not pattern.fullmatch(value):
        raise InputError('schema', f'{where} must match {pattern.pattern}')
    return value


def _enum(value, choices, where):
    if type(value) is not str or value not in choices:
        raise InputError('schema', f'{where} must be one of {list(choices)}')
    return value


def _list(value, where, *, min_len=0, max_len=256):
    if type(value) is not list or not min_len <= len(value) <= max_len:
        raise InputError('schema', f'{where} must be a list of {min_len}..{max_len} items')
    return value


def _unique(items, where):
    seen = set()
    for item in items:
        if item in seen:
            raise InputError('schema', f'duplicate {where}: {item}')
        seen.add(item)
    return items


def _no_credentials(value, where):
    """Refuse recognizable credential forms without echoing the value (heuristic only)."""
    if CREDENTIAL_FORM.search(value) or CREDENTIAL_SHAPE.search(value):
        raise InputError('unauthorized', f'{where} appears to carry a credential; refused')


# ---- paths and files ------------------------------------------------------------

def _rel_path(value, where, *, allow_dir):
    if type(value) is not str or not value or len(value) > 4096 or _has_control(value):
        raise InputError('path', f'{where} must be a non-empty printable relative path')
    is_dir = value.endswith('/')
    parts = (value[:-1] if is_dir else value).split('/')
    if ((is_dir and not allow_dir) or value.startswith(('/', '-', ':')) or '\\' in value
            or any(part in ('', '.', '..') for part in parts)
            or any(part.lower() == '.git' for part in parts)):
        raise InputError('path', f'{where} is not a normalized safe repository-relative path')
    return value


def _abs_path(value, where):
    if (type(value) is not str or not os.path.isabs(value) or _has_control(value)
            or value.startswith('//') or os.path.normpath(value) != value):
        raise InputError('path', f'{where} must be a normalized absolute path')
    return value


def _executable(value, where):
    _abs_path(value, where)
    _no_credentials(value, where)
    real = os.path.realpath(value)
    if not os.path.isfile(real) or not os.access(real, os.X_OK):
        raise InputError('path', f'{where} must be an existing executable file')
    return value


def _inside(path, roots) -> bool:
    real = os.path.realpath(path)
    return any(real == root or real.startswith(root.rstrip('/') + '/') for root in roots)


def _check_private_stat(info, mode, where):
    if (info.st_uid != os.geteuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & ~mode or not info.st_mode & stat.S_IRUSR):
        raise InputError('file', f'{where} must be a single-link file owned by the current '
                                 f'user with mode within {mode:o}')


def _check_ancestors(parent: Path, euid: int):
    try:
        info = os.lstat(parent)
        if info.st_uid != euid or info.st_mode & 0o022:
            raise InputError('file', 'private file parent must be owned by the current user '
                                     'and not group/world writable')
        for ancestor in parent.parents:
            info = os.lstat(ancestor)
            loose = info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX
            if info.st_uid not in (0, euid) or loose:
                raise InputError('file', 'private file ancestor directory is not safe')
    except OSError as err:
        raise InputError('file', f'private file ancestry unreadable: {err.strerror}') from err


def private_file(path, mode=0o600) -> Path:
    """Return ``path`` if it is a private, symlink-free regular file; raise otherwise."""
    if type(mode) is not int or mode & ~0o700 or not mode & 0o400:
        raise InputError('schema', 'private mode must be owner-only and owner-readable')
    text = _abs_path(os.fspath(path), 'private file')
    if os.path.realpath(text) != text:
        raise InputError('file', 'private file path must not traverse symlinks')
    try:
        info = os.lstat(text)
    except OSError as err:
        raise InputError('file', f'private file unavailable: {err.strerror}') from err
    if not stat.S_ISREG(info.st_mode):
        raise InputError('file', 'private file must be a regular file')
    _check_private_stat(info, mode, 'private file')
    _check_ancestors(Path(text).parent, os.geteuid())
    return Path(text)


def _read_fd(fd: int, limit: int) -> bytes:
    """Read at most ``limit + 1`` bytes so an oversize file is detectable."""
    chunks, remaining = [], limit + 1
    while remaining:
        chunk = os.read(fd, min(remaining, 1 << 16))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _read_regular(path, where, limit, mode=None) -> bytes:
    """Bytes of a regular file opened without following a final symlink. The opened
    descriptor is always fstat-checked as a regular file before any read (a directory,
    FIFO, socket or device is refused, and O_NONBLOCK keeps a writerless FIFO from
    hanging the open). Errors carry ``where`` and the OS reason only, never content, and
    the descriptor is closed on every path."""
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    try:
        fd = os.open(path, flags)
    except OSError as err:
        raise InputError('file', f'{where} unreadable: {err.strerror or type(err).__name__}') from err
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise InputError('file', f'{where} must be a regular file')
        if mode is not None:
            _check_private_stat(info, mode, where)
        data = _read_fd(fd, limit)
    except OSError as err:
        raise InputError('file', f'{where} unreadable: {err.strerror or type(err).__name__}') from err
    finally:
        os.close(fd)
    if len(data) > limit:
        raise InputError('file', f'{where} exceeds {limit} bytes')
    return data


def _parse_json(raw: bytes, where: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InputError('schema', f'{where} repeats key {key!r}')
            result[key] = value
        return result

    def finite(text):
        number = float(text)
        if not math.isfinite(number):
            raise InputError('schema', f'{where} contains a non-finite number')
        return number

    def constant(name):
        raise InputError('schema', f'{where} contains non-standard constant {name}')

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_float=finite,
                          parse_constant=constant)
    except (ValueError, RecursionError) as err:
        raise InputError('schema', f'{where} is not strict UTF-8 JSON: {err}') from err


# ---- git ------------------------------------------------------------------------

def _git_env() -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
               GIT_OPTIONAL_LOCKS='0', GIT_NO_REPLACE_OBJECTS='1', GIT_LITERAL_PATHSPECS='1',
               LC_ALL='C')
    return env


def _git(repo, *args, stdin=None) -> bytes:
    git = shutil.which('git')
    if not git:
        raise InputError('git', 'git executable not found')
    command = [git, '--no-replace-objects', '-c', 'core.fsmonitor=false', '-C', repo, *args]
    try:
        done = subprocess.run(command, input=stdin, capture_output=True, env=_git_env(),
                              timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise InputError('git', f'git {args[0]} could not run: {err}') from err
    if done.returncode != 0:
        lines = done.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise InputError('git', f'git {args[0]} failed: {lines[-1] if lines else done.returncode}')
    return done.stdout


def canonical_repo(path) -> dict:
    """Return the canonical work-tree root and common Git dir, ignoring inherited GIT_*."""
    text = _abs_path(os.fspath(path), 'repository path')
    try:
        out = _git(text, 'rev-parse', '--path-format=absolute', '--show-toplevel',
                   '--git-common-dir').decode('utf-8').splitlines()
    except UnicodeDecodeError as err:
        raise InputError('git', 'repository path is not UTF-8') from err
    if len(out) != 2:
        raise InputError('git', 'unexpected rev-parse output')
    return {'root': os.path.realpath(out[0]), 'common_dir': os.path.realpath(out[1])}


def _parse_batch(raw: bytes, count: int) -> list:
    blobs, pos = [], 0
    try:
        for _ in range(count):
            end = raw.index(b'\n', pos)
            _, kind, size = raw[pos:end].decode('ascii').split(' ')
            start = end + 1
            if kind != 'blob' or len(raw) < start + int(size):
                raise ValueError('not a complete blob')
            blobs.append(raw[start:start + int(size)])
            pos = start + int(size) + 1
    except ValueError as err:
        raise InputError('git', f'unreadable object batch: {err}') from err
    return blobs


def rules_digest(repo, base_sha, paths) -> str:
    """Hash committed instruction blobs at ``base_sha`` (object reads; no filters/hooks)."""
    root = canonical_repo(repo)['root']
    sha = _match(base_sha, SHA, 'base_sha')
    if type(paths) not in (list, tuple):
        raise InputError('schema', 'paths must be a list')
    names = sorted(_unique([_rel_path(p, 'instruction path', allow_dir=False) for p in paths],
                           'instruction path'))
    if _git(root, 'cat-file', '-t', sha).strip() != b'commit':
        raise InputError('git', 'base_sha is not a commit')
    entries = {}
    listing = _git(root, 'ls-tree', '-z', '--full-tree', sha, '--', *names) if names else b''
    for record in filter(None, listing.split(b'\0')):
        meta, _, name = record.partition(b'\t')
        entries[name.decode('utf-8', 'replace')] = meta.decode('ascii').split(' ')
    oids = []
    for name in names:
        mode, kind, oid = entries.get(name, (None, None, None))
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise InputError('git', f'instruction path {name} is not a regular file at base_sha')
        oids.append(oid)
    raw = _git(root, 'cat-file', '--batch', stdin=''.join(f'{o}\n' for o in oids).encode())
    digest = hashlib.sha256(b'sdlc-rules-v1\0')
    for name, blob in zip(names, _parse_batch(raw, len(oids))):
        digest.update(name.encode() + b'\0' + str(len(blob)).encode() + b'\0' + blob)
    return digest.hexdigest()


def _runtime_layout(directory) -> tuple:
    """(edition, scripts directory, {bundle: directory}) of a known installed layout."""
    text = _abs_path(os.fspath(directory), 'runtime directory')
    if os.path.realpath(text) != text:
        raise InputError('path', 'runtime directory must be canonical (no symlinks)')
    scripts = Path(text)
    skill = scripts.parent
    if scripts.name != 'scripts' or skill.name not in RUNTIME_LAYOUTS:
        raise InputError('path', 'runtime directory is not the scripts/ directory of a known '
                                 'delivery skill layout')
    edition, sibling = RUNTIME_LAYOUTS[skill.name]
    return edition, scripts, {'delivery': skill, 'handoff': skill.parent / sibling}


def _runtime_resource(path: Path, key: str) -> bytes:
    """Bytes of a required resource; a missing, aliased or non-regular one is refused."""
    if os.path.realpath(path) != os.fspath(path):
        raise InputError('file', f'runtime resource {key} must not be reached through a symlink')
    return _read_regular(path, f'runtime resource {key}', MAX_RUNTIME_BYTES)


def runtime_digest(directory) -> str:
    """Hash the trusted runtime bytes the engine uses (digest ``RUNTIME_DIGEST_VERSION``).

    ``directory`` is the canonical ``scripts/`` directory of a known installed delivery
    skill (Claude ``delivery`` beside ``verified-handoff``; Codex ``sdlc-delivery`` beside
    ``sdlc-verified-handoff``). Bound: every ``controller*.py`` and ``sdlc_controller.py``
    there, plus each RUNTIME_RESOURCES entry under its stable logical key, with the edition.
    A missing, symlinked, aliased or non-regular required file is refused, never skipped or
    taken from another bundle. Files are read as bytes, never imported or executed. Not
    covered: other skills, project instructions (see ``rules_digest``), global config and
    credentials. A changed digest calls for an explicit context reconcile by the caller."""
    edition, scripts, bundles = _runtime_layout(directory)
    try:
        names = sorted(n for n in os.listdir(scripts) if n == 'sdlc_controller.py'
                       or (n.startswith('controller') and n.endswith('.py')))
    except OSError as err:
        raise InputError('file', f'runtime directory unreadable: {err.strerror}') from err
    if not names:
        raise InputError('file', 'no controller runtime files found')
    entries = [(f'runtime/{name}', _read_regular(scripts / name, f'runtime file {name}',
                                                 MAX_RUNTIME_BYTES)) for name in names]
    entries += [(key, _runtime_resource(bundles[bundle] / rel, key))
                for key, bundle, rel in RUNTIME_RESOURCES]
    digest = hashlib.sha256(f'{RUNTIME_DIGEST_VERSION}\0{edition}\0'.encode())
    for key, data in sorted(entries):
        digest.update(key.encode() + b'\0' + str(len(data)).encode() + b'\0' + data)
    return digest.hexdigest()


def canonical_json(data) -> str:
    """The one canonical form shared by digests and the ledger: sorted keys, compact
    separators, non-ASCII kept literal for UTF-8 encoding, and no NaN or Infinity."""
    try:
        text = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False)
        text.encode('utf-8')
    except (TypeError, ValueError, RecursionError) as err:
        raise InputError('schema', f'value is not canonical JSON ({type(err).__name__})') from err
    return text


def canonical_digest(data) -> str:
    return hashlib.sha256(canonical_json(data).encode('utf-8')).hexdigest()


# ---- policy ---------------------------------------------------------------------

def _config_dir(provider, config_dir, where, roots) -> str:
    """Canonical account directory of a profile. A null ``config_dir`` is resolved once,
    from the provider variable or the home default, and passes the same checks as an
    explicit path. The caller freezes the result into the validated policy, so a later
    environment change cannot silently select another profile. Only the directory's
    existence is checked; nothing inside it is read and no identity is inferred."""
    variable, leaf = DEFAULT_CONFIG[provider]
    label = f'{where}.config_dir'
    if config_dir is None:
        label += f' (default from {variable} or ~/{leaf})'
        config_dir = os.environ.get(variable) or os.path.join(os.path.expanduser('~'), leaf)
    real = os.path.realpath(_abs_path(config_dir, label))
    if not os.path.isdir(real):
        raise InputError('path', f'{label} must be an existing directory')
    if real == os.path.realpath(os.path.expanduser('~')):
        raise InputError('unauthorized', f'{where}.config_dir must not repurpose the home directory')
    if _inside(real, roots):
        raise InputError('unauthorized', f'{where}.config_dir must live outside the repository')
    return real


def _validate_profiles(value, roots) -> list:
    profiles = _list(value, 'policy.profiles', min_len=1, max_len=16)
    ids, accounts, frozen = set(), {}, []
    for idx, profile in enumerate(profiles):
        where = f'policy.profiles[{idx}]'
        _fields(profile, PROFILE_KEYS, where)
        profile_id = _match(profile['id'], SAFE_ID, f'{where}.id')
        if profile_id in ids:
            raise InputError('schema', f'duplicate profile id: {profile_id}')
        ids.add(profile_id)
        provider = _enum(profile['provider'], PROVIDERS, f'{where}.provider')
        if _inside(_executable(profile['executable'], f'{where}.executable'), roots):
            raise InputError('unauthorized', f'{where}.executable must live outside the repository')
        roles = _list(profile['roles'], f'{where}.roles', min_len=1, max_len=len(ROLES))
        _unique([_enum(role, ROLES, f'{where}.roles[]') for role in roles], f'{where} role')
        account = _config_dir(provider, profile['config_dir'], where, roots)
        if account in accounts:
            raise InputError('schema', f'{where} aliases the config directory of profile '
                                       f'{accounts[account]}')
        accounts[account] = profile_id
        frozen.append(dict(profile, config_dir=account))
    return frozen


def _validate_limits(value):
    _fields(value, LIMIT_KEYS, 'policy.limits')
    _int(value['max_attempts'], 1, 20, 'policy.limits.max_attempts')
    attempt = _int(value['attempt_seconds'], 1, 86400, 'policy.limits.attempt_seconds')
    total = _int(value['max_total_seconds'], 1, 604800, 'policy.limits.max_total_seconds')
    if attempt > total:
        raise InputError('schema', 'attempt_seconds must not exceed max_total_seconds')
    _int(value['max_no_progress'], 1, 20, 'policy.limits.max_no_progress')
    # Checked by identity only: a non-null value is never converted, compared or echoed.
    if value['max_cost_usd'] is not None:
        raise InputError('unsupported', 'cost caps are not implemented (no cost is measured); '
                                        'policy.limits.max_cost_usd must be null')


def _validate_checks(value):
    if type(value) is not dict or len(value) > 64:
        raise InputError('schema', 'policy.allowed_checks must be an object of at most 64 checks')
    for key, argv in value.items():
        _match(key, SAFE_ID, 'policy.allowed_checks key')
        where = f'policy.allowed_checks.{key}'
        _list(argv, where, min_len=1, max_len=64)
        _executable(argv[0], f'{where}[0]')
        for idx, arg in enumerate(argv[1:], 1):
            if type(arg) is not str or len(arg) > 4096 or _has_control(arg):
                raise InputError('schema', f'{where}[{idx}] must be a printable literal string')
            _no_credentials(arg, f'{where}[{idx}]')
            if idx + 1 < len(argv) and CREDENTIAL_OPTION.fullmatch(arg):
                raise InputError('unauthorized', f'{where}[{idx + 1}] follows a credential '
                                                 'option; refused')


def _branch(value, where, *, prefix=False):
    _match(value, BRANCH, where)
    if prefix and not value.endswith('/'):
        raise InputError('schema', f'{where} must end with /')
    parts = (value[:-1] if prefix else value).split('/')
    if '..' in value or any(not part or part.startswith('.') or part.endswith(('.', '.lock'))
                            for part in parts):
        raise InputError('schema', f'{where} is not a safe branch name')
    return value


def _validate_delivery(value, effects):
    """Owner-frozen publication target. Null disables every external effect."""
    external = [effect for effect in effects if effect in EXTERNAL_EFFECTS]
    if value is None:
        if external:
            raise InputError('unauthorized', f'policy.effects {external} need a '
                                             'policy.delivery target')
        return
    _fields(value, DELIVERY_KEYS, 'policy.delivery')
    _match(value['remote'], SAFE_ID, 'policy.delivery.remote')
    url = _match(value['remote_url'], REMOTE_URL, 'policy.delivery.remote_url')
    if len(url) > 2000:
        raise InputError('schema', 'policy.delivery.remote_url is too long')
    _no_credentials(url, 'policy.delivery.remote_url')
    repo = _match(value['github_repo'], GITHUB_REPO, 'policy.delivery.github_repo')
    if repo.split('/')[1] in ('.', '..'):
        raise InputError('schema', 'policy.delivery.github_repo is not a repository name')
    base = _branch(value['base_branch'], 'policy.delivery.base_branch')
    prefix = _branch(value['branch_prefix'], 'policy.delivery.branch_prefix', prefix=True)
    if base.startswith(prefix):
        raise InputError('schema', 'policy.delivery.base_branch must sit outside branch_prefix')
    checks = _list(value['required_checks'], 'policy.delivery.required_checks', max_len=64)
    _unique([_text(check, 'policy.delivery.required_checks[]', limit=200) for check in checks],
            'required check')
    _enum(value['merge_method'], MERGE_METHODS, 'policy.delivery.merge_method')
    if 'merge' in effects and not checks:
        raise InputError('schema', 'automatic merge needs explicit non-empty '
                                   'policy.delivery.required_checks')


def validate_policy(data) -> dict:
    """Validate an owner policy and return its frozen form: a deep copy in which every
    profile carries its canonical ``config_dir`` (a null default is materialized)."""
    _fields(data, POLICY_KEYS, 'policy')
    _version(data['version'], 'policy')
    repository = _abs_path(data['repository'], 'policy.repository')
    repo = canonical_repo(repository)
    if repo['root'] != repository:
        raise InputError('path', 'policy.repository must be the canonical git root')
    profiles = _validate_profiles(data['profiles'], (repo['root'], repo['common_dir']))
    for key in ('auto_route', 'execution_enabled', 'background_enabled'):
        _bool(data[key], f'policy.{key}')
    max_parallel = _int(data['max_parallel'], 1, 16, 'policy.max_parallel')
    reserve = _int(data['review_reserve'], 0, 15, 'policy.review_reserve')
    if reserve >= max_parallel:
        raise InputError('schema', 'policy.review_reserve must be less than max_parallel')
    if reserve and not any('review' in p['roles'] for p in profiles):
        raise InputError('schema', 'policy.review_reserve needs a review-capable profile')
    if not any('implement' in p['roles'] for p in profiles):
        raise InputError('schema', 'policy.profiles needs an implement-capable profile')
    _validate_limits(data['limits'])
    _validate_checks(data['allowed_checks'])
    effects = _list(data['effects'], 'policy.effects', max_len=len(EFFECTS))
    _unique([_enum(e, EFFECTS, 'policy.effects[]') for e in effects], 'policy effect')
    _validate_delivery(data['delivery'], effects)
    paths = _list(data['instruction_paths'], 'policy.instruction_paths', max_len=64)
    _unique([_rel_path(p, 'policy.instruction_paths[]', allow_dir=False) for p in paths],
            'instruction path')
    return copy.deepcopy(dict(data, profiles=profiles))


def _require_outside(target, repository, where):
    repo = canonical_repo(repository)
    if _inside(target, (repo['root'], repo['common_dir'])):
        raise InputError('unauthorized', f'{where} file must live outside the repository '
                                         'and its Git directory')


def read_policy(path) -> dict:
    target = private_file(path)
    raw = _read_regular(target, 'policy', MAX_FILE_BYTES, 0o600)
    policy = validate_policy(_parse_json(raw, 'policy'))
    _require_outside(target, policy['repository'], 'policy')
    return policy


# ---- plan -----------------------------------------------------------------------

def _validate_task(task, where, allowed_checks) -> str:
    _fields(task, TASK_KEYS, where)
    task_id = _match(task['id'], SAFE_ID, f'{where}.id')
    _text(task['objective'], f'{where}.objective', multiline=True)
    kind = _enum(task['kind'], KINDS, f'{where}.kind')
    deps = _list(task['depends_on'], f'{where}.depends_on')
    _unique([_match(d, SAFE_ID, f'{where}.depends_on[]') for d in deps], f'{where} dependency')
    if task_id in deps:
        raise InputError('dependency', f'task {task_id} depends on itself')
    scope = _list(task['write_scope'], f'{where}.write_scope',
                  min_len=0 if kind == 'investigation' else 1)
    _unique([_rel_path(s, f'{where}.write_scope[]', allow_dir=True) for s in scope],
            f'{where} write scope')
    resources = _list(task['resources'], f'{where}.resources', max_len=64)
    _unique([_match(r, SAFE_RESOURCE, f'{where}.resources[]') for r in resources],
            f'{where} resource')
    checks = _list(task['checks'], f'{where}.checks', max_len=64)
    for check in _unique([_match(c, SAFE_ID, f'{where}.checks[]') for c in checks],
                         f'{where} check'):
        if check not in allowed_checks:
            raise InputError('unauthorized', f'{where} check {check} is not in allowed_checks')
    for item in _list(task['acceptance'], f'{where}.acceptance', min_len=1, max_len=64):
        _text(item, f'{where}.acceptance[]', multiline=True)
    return task_id


def _check_graph(graph: dict):
    for task_id, deps in graph.items():
        missing = [dep for dep in deps if dep not in graph]
        if missing:
            raise InputError('dependency', f'task {task_id} depends on unknown {missing}')
    remaining = {task_id: set(deps) for task_id, deps in graph.items()}
    while remaining:
        ready = [task_id for task_id, deps in remaining.items() if not deps]
        if not ready:
            raise InputError('dependency', f'dependency cycle among {sorted(remaining)}')
        for task_id in ready:
            del remaining[task_id]
        for deps in remaining.values():
            deps.difference_update(ready)


def validate_plan(data, policy) -> dict:
    _fields(data, PLAN_KEYS, 'plan')
    _version(data['version'], 'plan')
    _match(data['id'], SAFE_ID, 'plan.id')
    _text(data['objective'], 'plan.objective', multiline=True)
    _text(data['input_revision'], 'plan.input_revision', limit=200)
    _match(data['base_sha'], SHA, 'plan.base_sha')
    graph = {}
    for idx, task in enumerate(_list(data['tasks'], 'plan.tasks', min_len=1)):
        task_id = _validate_task(task, f'plan.tasks[{idx}]', policy['allowed_checks'])
        if task_id in graph:
            raise InputError('schema', f'duplicate task id: {task_id}')
        graph[task_id] = task['depends_on']
    _check_graph(graph)
    return copy.deepcopy(data)


def read_plan(path, policy) -> dict:
    target = _abs_path(os.fspath(path), 'plan path')
    return validate_plan(_parse_json(_read_regular(target, 'plan', MAX_FILE_BYTES), 'plan'),
                         policy)


# ---- scopes ---------------------------------------------------------------------

def _scope_list(scope, where) -> list:
    entries = [scope] if isinstance(scope, str) else scope
    if type(entries) not in (list, tuple):
        raise InputError('schema', f'{where} must be a path or list of paths')
    return [_rel_path(entry, where, allow_dir=True) for entry in entries]


def scope_allows(path, scope) -> bool:
    """True when file ``path`` equals an entry or sits under a directory prefix entry."""
    entries = _scope_list(scope, 'scope')
    try:
        _rel_path(path, 'path', allow_dir=False)
    except InputError:
        return False
    return any(path == e or (e.endswith('/') and path.startswith(e)) for e in entries)


def _overlap(left: str, right: str) -> bool:
    if left.rstrip('/') == right.rstrip('/'):
        return True
    return ((left.endswith('/') and right.startswith(left))
            or (right.endswith('/') and left.startswith(right)))


def scopes_conflict(left, right) -> bool:
    """True when any entries are equal or nest (parent/child); callers serialize these."""
    lefts, rights = _scope_list(left, 'left scope'), _scope_list(right, 'right scope')
    return any(_overlap(a, b) for a in lefts for b in rights)


# ---- authority ------------------------------------------------------------------

def _timestamp(value, where):
    _match(value, UTC_STAMP, where)
    try:
        moment = _dt.datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as err:
        raise InputError('schema', f'{where} is not a valid UTC timestamp') from err
    if moment > _dt.datetime.now(_dt.timezone.utc) + CLOCK_SKEW:
        raise InputError('schema', f'{where} is in the future')


def validate_authority(data, policy, plan) -> dict:
    _fields(data, AUTHORITY_KEYS, 'authority')
    _version(data['version'], 'authority')
    if _match(data['plan_digest'], DIGEST, 'authority.plan_digest') != canonical_digest(plan):
        raise InputError('digest', 'authority.plan_digest does not bind this plan')
    effects = _list(data['effects'], 'authority.effects', max_len=len(EFFECTS))
    _unique([_enum(e, EFFECTS, 'authority.effects[]') for e in effects], 'authority effect')
    widened = [effect for effect in effects if effect not in policy['effects']]
    if widened:
        raise InputError('unauthorized', f'authority effects {widened} exceed policy.effects')
    external = [effect for effect in effects if effect in EXTERNAL_EFFECTS]
    if external and policy.get('delivery') is None:
        raise InputError('unauthorized', f'authority effects {external} need a '
                                         'policy.delivery target')
    _text(data['authorizer'], 'authority.authorizer', limit=200)
    _timestamp(data['approved_at'], 'authority.approved_at')
    return copy.deepcopy(data)


def read_authority(path, policy, plan) -> dict:
    target = private_file(path)
    _require_outside(target, policy['repository'], 'authority')
    raw = _read_regular(target, 'authority', MAX_FILE_BYTES, 0o600)
    return validate_authority(_parse_json(raw, 'authority'), policy, plan)


# ---- publication target ---------------------------------------------------------

def check_delivery_spec(effect, spec, delivery) -> dict:
    """Bind an external effect spec to the frozen owner target and return the spec to
    record (with ``target`` set to that target). A worker-supplied remote, repository or
    base branch that differs is refused; ``branch`` is required and must sit inside
    ``branch_prefix``. Nothing here reads or changes a remote, Git config or GitHub."""
    if effect not in EXTERNAL_EFFECTS:
        raise InputError('schema', f'{effect!r} is not an external effect')
    if delivery is None:
        raise InputError('unauthorized', 'no policy.delivery target: external effects are disabled')
    if type(spec) is not dict:
        raise InputError('schema', 'effect spec must be an object')
    for key in (*DELIVERY_KEYS, 'target'):
        expected = delivery if key == 'target' else delivery[key]
        if key in spec and spec[key] != expected:
            raise InputError('unauthorized', f'effect spec {key} differs from the frozen '
                                             'policy.delivery target')
    branch = _branch(spec.get('branch'), 'effect spec branch')
    prefix = delivery['branch_prefix']
    if not branch.startswith(prefix) or len(branch) == len(prefix):
        raise InputError('unauthorized', 'effect spec branch must sit inside '
                                         'policy.delivery.branch_prefix')
    if effect == 'merge' and not delivery['required_checks']:
        raise InputError('unauthorized', 'automatic merge needs policy.delivery.required_checks')
    return {**spec, 'target': copy.deepcopy(delivery)}
