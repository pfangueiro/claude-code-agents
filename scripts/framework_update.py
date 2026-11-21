#!/usr/bin/env python3
"""Conservatively update EXISTING user-global SDLC framework installs. Python 3.11+.

  plan   Read-only. Prints one PLAN_READY JSON document (executed: false) to stdout.
         --out FILE additionally writes a private (0600) plan inside a private directory.
  apply  Requires --plan FILE. Refuses a source checkout that is no longer at the plan's commit
         before running any source code, then recomputes the plan from that exact clean committed
         source and the current target under a cooperative lock, refuses any difference, backs up every
         affected file, then applies one guarded transaction and verifies the result.

Only integrations that are already installed are updated (or the explicitly selected ones,
which must already be installed); nothing is newly installed. Claude ownership is proven
from the old baseline commit named by the install marker (its own install.sh mapping and
tracked bytes), never from basenames. The broad Claude installer is only ever run against a
private disposable staging home holding copies of settings.json, the markers and (when
manifested) the delivery manifest with its proven-owned files; the delivery update is applied
there first and install.sh --update (no optional flags) second, and the final staged state is
verified before anything live is planned. Staged settings are compared as whole JSON objects
and never published. Codex is planned with codex/framework.py's hash-owned planner against the
live logical home, after every manifest path is proven to be a shipped framework resource.

Every validated input (changed or not) is bound into the plan fingerprint by bytes, type, mode
and owner, rechecked before the first write and again after the last one. apply records an
owner-private operation log of the actual attempts and their outcomes beside its backup.

Never performed: source pulls/checkouts, new installs, optional-component selection, services
or schedules, network, credential reads, settings/CLAUDE.md/permission/model/sandbox/hook
trust changes. Limits are reported in every result (see LIMITS).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Iterator, NamedTuple

SCHEMA = 'sdlc-framework-update-plan/1'
EDITIONS = ('claude', 'codex')
# Repository paths whose bytes an update consumes; extra (even ignored) files here make the source dirty.
CONSUMED_SCOPES = ('.claude', 'global-config', 'install.sh', 'scripts/install-delivery.py', 'codex', 'observability')
CLAUDE_TREE_SCOPES = ('.claude', 'global-config', 'install.sh')
STATE_DIR = '.sdlc-framework-update'
LOCK = '.sdlc-framework-update.lock'
# Locks of the existing installers; a present one means another install may be running.
FOREIGN_LOCKS = ('.claude/.install.lock.d', '.claude/.sdlc-delivery.lock', '.sdlc-codex-install.lock')
MARKER = '.claude/.framework-version'
PATH_MARKER = '.claude/.framework-path'
SETTINGS = '.claude/settings.json'
DELIVERY_MANIFEST = '.claude/.sdlc-delivery/manifest.json'
CODEX_MANIFEST = '.codex/framework/manifest.json'
SELECTION_FIELDS = ('analytics', 'watchdog', 'notifications')
MAX_PLAN_BYTES = 4 * 1024 * 1024
SHORT_SHA = re.compile(r'[0-9a-f]{4,64}')
FULL_SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
SAFE_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9._-]*')
REGULAR_MODES = ('100644', '100755')
GIT_SAFETY = ('-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '--no-replace-objects',
              '--no-optional-locks', '--literal-pathspecs')
# Publication order: ordinary files first, each manifest/marker after the files it describes.
ORDER_FILE, ORDER_DELIVERY_MANIFEST, ORDER_CODEX_MANIFEST, ORDER_CLAUDE_MARKER = 0, 1, 2, 3
INVENTORY_ROOTS = ('.claude/agents', '.claude/lib', '.claude/rules', '.claude/commands', '.claude/skills',
                   '.claude/hooks', '.claude/output-styles', '.agents/skills', '.codex/agents', '.codex/framework')
# Files codex/framework.py ships (or shipped) directly in .codex/framework/. Anything else there is
# native runtime, approval or inventory state (manifest.json, lint-projects.json, events.jsonl,
# sessions/ ...) that a manifest entry can never make updatable.
CODEX_FRAMEWORK_RESOURCES = frozenset({'rules.md', 'inventory.json', 'mcp.example.toml',
                                       'statusline.example.toml', 'hook.py', 'lint.py'})
CODEX_PROTECTED_NAMES = frozenset({'manifest.json', 'lint-projects.json', 'events.jsonl', 'sessions'})
# Top-level settings keys install.sh --update reconciles; any other changed key is reported only
# as "other settings" so private keys never reach a diagnostic.
SETTINGS_CATEGORIES = ('hooks', 'permissions', 'statusLine', 'env', 'attribution')
OPERATION_LOG = 'operations.jsonl'
LIMITS = (
    'The lock is cooperative: a same-user process that ignores it can still write concurrently.',
    'Multi-file updates are not atomic under process kill or power loss; recover manually from the backup.',
    'Path and symlink checks are race-narrowing guards, not an operating-system security boundary.',
    'Optional Claude components (analytics, watchdog, notifications) are preserved, not updated or checked.',
    'settings.json and CLAUDE.md are never written; the update is refused if the broad installer would change settings.',
    'Native hook trust, authentication, model access and MCP connectivity are not checked.',
    'Retired framework paths without historical byte proof are retained and listed, never deleted.',
    'Rollback never overwrites a path another writer changed after this update wrote it; such paths are '
    'reported for manual recovery from the retained backup.',
    'Backups stay under <home>/.sdlc-framework-update/backups until the owner removes them.',
    'Directories emptied by removals are left in place.',
    'The operation log records each attempt before its mutation; an attempt without a later outcome '
    '(for example after a process kill) has an unknown outcome and must be compared with the backup.',
    'Root-owned system path aliases (for example /var or /tmp on macOS) are followed; any other '
    'symbolic link in the home, plan or output path is refused.',
)


class UpdateError(Exception):
    """A proven refusal or failure (FAIL)."""
    status = 'FAIL'


class Incomplete(UpdateError):
    """Required evidence is unavailable, unsupported or ambiguous (INCOMPLETE)."""
    status = 'INCOMPLETE'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------
# Git and source provenance
# ---------------------------------------------------------------------------------------------

@contextmanager
def scrubbed_git_environment() -> Iterator[None]:
    """Drop every inherited GIT_* selector/config injection for this process and its children.

    Also ignores system/global Git config so inherited config cannot add filters or hooks.
    The previous environment is restored on exit so callable main() has no lasting effect."""
    saved = dict(os.environ)
    try:
        for key in [key for key in os.environ if key.startswith('GIT_')]:
            del os.environ[key]
        os.environ.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                          GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def run_git(source: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(['git', *GIT_SAFETY, '-C', str(source), *args], input=stdin,
                              capture_output=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise Incomplete(f'git unavailable for source provenance: {err}') from err


def git(source: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result = run_git(source, *args, stdin=stdin)
    if result.returncode != 0:
        detail = result.stderr.decode(errors='replace').strip().splitlines()[:1]
        raise Incomplete(f'git {args[0]} failed in source: {" ".join(detail)}')
    return result.stdout


def check_tree_path(path: str) -> None:
    parts = path.split('/')
    if any(part in ('', '.', '..') or part.casefold() == '.git' or '\\' in part
           or any(ord(char) < 32 for char in part) for part in parts):
        raise UpdateError(f'unsafe committed path: {path!r}')


def tree_entries(source: Path, commit: str, scopes: tuple[str, ...] = ()) -> dict[str, tuple[str, str]]:
    """Map committed paths (optionally under scopes) to (mode, object id)."""
    listing = git(source, 'ls-tree', '-r', '-z', '--full-tree', commit, '--', *scopes)
    entries: dict[str, tuple[str, str]] = {}
    for record in filter(None, listing.split(b'\0')):
        meta, _, raw = record.partition(b'\t')
        try:
            mode, kind, oid = meta.decode('ascii').split(' ')
            path = raw.decode('utf-8')
        except (UnicodeDecodeError, ValueError) as err:
            raise Incomplete(f'unreadable committed tree entry: {record!r}') from err
        check_tree_path(path)
        if kind not in ('blob', 'commit') or not FULL_SHA.fullmatch(oid):
            raise Incomplete(f'unexpected committed entry {kind}: {path}')
        entries[path] = (mode, oid)
    return entries


def read_blobs(source: Path, oids: list[str]) -> dict[str, bytes]:
    """Read blobs in one batch and prove each content hashes to its object id."""
    unique = sorted(set(oids))
    if not unique:
        return {}
    output = git(source, 'cat-file', '--batch', stdin=''.join(f'{oid}\n' for oid in unique).encode())
    blobs: dict[str, bytes] = {}
    offset = 0
    for oid in unique:
        end = output.find(b'\n', offset)
        header = output[offset:end].decode(errors='replace').split(' ')
        if end < 0 or len(header) != 3 or header[:2] != [oid, 'blob'] or not header[2].isdigit():
            raise Incomplete(f'unreadable source object: {oid}')
        size, start = int(header[2]), end + 1
        data = output[start:start + size]
        algorithm = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
        if len(data) != size or algorithm(b'blob %d\0' % size + data).hexdigest() != oid:
            raise Incomplete(f'source object content does not match its id: {oid}')
        blobs[oid] = data
        offset = start + size + 1
    return blobs


class Source(NamedTuple):
    path: Path
    sha: str
    entries: dict[str, tuple[str, str]]   # every committed path at HEAD -> (mode, oid)
    blobs: dict[str, bytes]               # consumed committed regular files -> bytes


def in_scopes(path: str, scopes: tuple[str, ...]) -> bool:
    return any(path == scope or path.startswith(scope + '/') for scope in scopes)


def read_source(path: Path) -> Source:
    """Prove the source is a clean checkout of its committed HEAD and return HEAD's consumed bytes.

    Cleanliness is proven without running Git filters: hidden index flags, staged changes,
    tracked-file bytes/modes against HEAD objects, untracked files and (inside consumed scopes)
    any extra entry at all, ignored or not."""
    try:
        source = path.expanduser().resolve(strict=True)
    except OSError as err:
        raise Incomplete(f'source checkout unavailable: {err}') from err
    toplevel = git(source, 'rev-parse', '--show-toplevel').decode().strip()
    if not toplevel or not Path(toplevel).exists() or not Path(toplevel).samefile(source):
        raise Incomplete('--source must be the top level of a non-bare Git work tree')
    sha = git(source, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    if not FULL_SHA.fullmatch(sha):
        raise Incomplete('source HEAD is not a full commit id')
    entries = tree_entries(source, sha)
    dirty: list[str] = []
    for record in filter(None, git(source, 'ls-files', '-z', '-v').split(b'\0')):
        if not record.startswith(b'H '):
            dirty.append(f'{record[2:].decode(errors="replace")} (hidden index state)')
    staged = git(source, 'diff-index', '--cached', '--name-only', '-z', sha, '--')
    dirty += [f'{name.decode(errors="replace")} (staged change)' for name in filter(None, staged.split(b'\0'))]
    untracked = git(source, 'ls-files', '-z', '--others', '--exclude-standard')
    dirty += [f'{name.decode(errors="replace")} (untracked)' for name in filter(None, untracked.split(b'\0'))]
    for rel, (mode, _oid) in sorted(entries.items()):
        if mode == '160000':
            raise Incomplete(f'source has a submodule, whose state cannot be proven clean: {rel}')
        if in_scopes(rel, CONSUMED_SCOPES) and mode not in REGULAR_MODES:
            raise UpdateError(f'consumed committed entry is not a regular file ({mode}): {rel}')
    regular = {p: oid for p, (mode, oid) in entries.items() if mode in REGULAR_MODES}
    blobs_by_oid = read_blobs(source, [oid for _mode, oid in entries.values()])
    for rel, (mode, oid) in sorted(entries.items()):
        dirty += worktree_deviation(source, rel, mode, blobs_by_oid[oid])
    dirty += consumed_extras(source, set(entries))
    if dirty:
        raise UpdateError('source is not a clean committed checkout: ' + ', '.join(dirty[:20])
                          + (f' (+{len(dirty) - 20} more)' if len(dirty) > 20 else ''))
    consumed = {p: blobs_by_oid[oid] for p, oid in regular.items() if in_scopes(p, CONSUMED_SCOPES)}
    return Source(source, sha, entries, consumed)


def worktree_deviation(source: Path, rel: str, mode: str, data: bytes) -> list[str]:
    """Compare one tracked working-tree entry with its HEAD blob (a symlink blob is its target)."""
    file = source.joinpath(*rel.split('/'))
    for ancestor in list(reversed(file.relative_to(source).parents))[1:]:
        if (source / ancestor).is_symlink():
            return [f'{rel} (symlinked ancestor)']
    if mode == '120000':
        try:
            return [] if os.fsencode(os.readlink(file)) == data else [f'{rel} (differs from HEAD)']
        except OSError:
            return [f'{rel} (differs from HEAD)']
    try:
        info = os.lstat(file)
    except FileNotFoundError:
        return [f'{rel} (missing)']
    if not stat.S_ISREG(info.st_mode) or file.read_bytes() != data:
        return [f'{rel} (differs from HEAD)']
    if bool(info.st_mode & 0o100) != (mode == '100755'):
        return [f'{rel} (mode differs from HEAD)']
    return []


def consumed_extras(source: Path, tracked: set[str]) -> list[str]:
    tracked_dirs = {parent.as_posix() for rel in tracked for parent in Path(rel).parents}
    extras = []
    for scope in CONSUMED_SCOPES:
        root = source / scope
        if root.is_symlink():
            raise UpdateError(f'consumed source scope is a symlink: {scope}')
        if not root.is_dir():
            continue
        for directory, dirnames, filenames in os.walk(root):
            for name in sorted(dirnames + filenames):
                rel = Path(directory, name).relative_to(source).as_posix()
                if rel not in tracked and rel not in tracked_dirs:
                    extras.append(f'{rel} (not in HEAD)')
    return extras


# ---------------------------------------------------------------------------------------------
# Target home and file state
# ---------------------------------------------------------------------------------------------

def is_system_alias(path: Path, info: os.stat_result) -> bool:
    """A root-owned symlink inside a root-owned directory nobody else can write (e.g. macOS /var).

    Only such links, which this user cannot create or swap, are followed in a raw path."""
    if info.st_uid != 0:
        return False
    try:
        parent = os.lstat(path.parent)
    except OSError:
        return False
    return stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and not parent.st_mode & 0o022


def unaliased_path(raw: Path, label: str) -> Path:
    """Absolute form of a raw path, refusing any user-controllable symlink in it BEFORE resolving.

    Every existing component is checked with lstat, so resolve() can never silently erase a
    symlinked leaf or ancestor. A '..' component is refused because it would make the checked
    components differ from the ones the kernel walks."""
    expanded = raw.expanduser()
    path = expanded if expanded.is_absolute() else Path.cwd() / expanded
    if '..' in path.parts:
        raise UpdateError(f'{label} path must not contain ".." components')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as err:
            raise UpdateError(f'{label} path cannot be inspected: {err.strerror}') from err
        if stat.S_ISLNK(info.st_mode) and not is_system_alias(current, info):
            raise UpdateError(f'{label} path crosses a symbolic link; pass the real path instead')
    return path


def resolve_home(explicit: Path | None) -> Path:
    """Return a supported home-shaped target: an existing directory owned by this user.

    A Claude or Codex configuration directory itself is not home-shaped and is refused, and a
    raw path through a user-controllable symlink is refused before it is canonicalized."""
    raw = unaliased_path(explicit if explicit is not None else Path.home(), '--home')
    try:
        home = raw.resolve(strict=True)
    except OSError as err:
        raise Incomplete(f'target home unavailable: {err}') from err
    info = os.lstat(home)
    if not stat.S_ISDIR(info.st_mode):
        raise Incomplete('target home is not a directory')
    if info.st_uid != os.geteuid():
        raise Incomplete('target home is not owned by the current user')
    if home.name in ('.claude', '.codex', '.agents'):
        raise Incomplete('--home must be a home-shaped directory, not a Claude/Codex configuration directory')
    return home


def target_path(home: Path, rel: str) -> Path:
    """Refuse traversal and any symlink or non-directory ancestor between home and the path."""
    parts = rel.split('/')
    if not rel or rel.startswith('/') or any(part in ('', '.', '..') for part in parts):
        raise UpdateError(f'unsafe target path: {rel!r}')
    current = home
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise UpdateError(f'symlink in target path: {rel}')
        if index < len(parts) - 1 and current.exists() and not current.is_dir():
            raise UpdateError(f'not a directory in target path: {rel}')
    return current


State = dict  # {'digest': str, 'mode': int, 'uid': int, 'gid': int}


def read_regular(home: Path, rel: str) -> tuple[State | None, bytes | None]:
    """Return (state, bytes) of a regular target file, (None, None) if absent; refuse anything else."""
    path = target_path(home, rel)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, None
    except OSError as err:
        raise UpdateError(f'cannot read target file {rel}: {err.strerror}') from err
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise UpdateError(f'not a regular file: {rel}')
        data = stream.read()
    return {'digest': digest(data), 'mode': info.st_mode & 0o7777, 'uid': info.st_uid, 'gid': info.st_gid}, data


def entry_kind(path: Path) -> str | None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return 'symlink'
    if stat.S_ISDIR(info.st_mode):
        return 'dir'
    return 'file' if stat.S_ISREG(info.st_mode) else 'special'


def walk_entries(home: Path, rel: str) -> list[tuple[str, str]]:
    """Every entry below a target directory as (relative path, kind), never following symlinks."""
    found: list[tuple[str, str]] = []
    pending = [rel]
    while pending:
        current = pending.pop()
        with os.scandir(target_path(home, current)) as iterator:
            for entry in iterator:
                child = f'{current}/{entry.name}'
                kind = entry_kind(Path(entry.path)) or 'special'
                found.append((child, kind))
                if kind == 'dir':
                    pending.append(child)
    return sorted(found)


def inventory(home: Path) -> set[str]:
    """Regular files and symlinks under the framework-managed roots, for the net-removal check."""
    paths: set[str] = set()
    for root in INVENTORY_ROOTS:
        try:
            if entry_kind(target_path(home, root)) != 'dir':
                continue
            paths.update(rel for rel, kind in walk_entries(home, root) if kind != 'dir')
        except UpdateError:
            paths.add(root)
    return paths


def strict_json(data: bytes) -> object:
    """Parse JSON refusing duplicate keys and non-finite numbers.

    Error messages are static: a private input's keys or values never appear in them."""
    def pairs(items: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def constant(_name: str) -> object:
        raise ValueError('non-finite JSON number')

    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)


def load_source_module(source: 'Source', rel: str, name: str) -> object:
    """Execute a module from its verified committed bytes, never from cached or working-tree bytecode.

    ``__file__`` names the module's location in the clean source so its own path logic
    (for example codex/framework.py's REPO) resolves to the selected checkout."""
    code_bytes = source.blobs.get(rel)
    if code_bytes is None:
        raise Incomplete(f'source module is not a committed consumed file: {rel}')
    path = source.path / rel
    spec = importlib.util.spec_from_loader(name, loader=None, origin=str(path))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    try:
        exec(compile(code_bytes, str(path), 'exec', dont_inherit=True), module.__dict__)
    except ImportError as err:
        raise Incomplete(f'source module dependency unavailable for {rel}: {err}') from err
    except SyntaxError as err:
        raise UpdateError(f'source module does not compile: {rel}') from err
    return module


# ---------------------------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------------------------

class Op(NamedTuple):
    edition: str
    rel: str                  # path relative to the target home
    action: str               # 'write' or 'remove'
    before: State | None      # state observed while planning (None = absent)
    data: bytes | None        # bytes to publish for 'write'
    mode: int | None          # permission bits to publish for 'write'
    order: int


def marker_stable(data: bytes) -> bytes:
    """Marker bytes without the per-run installed_at timestamp (for comparison and fingerprint)."""
    return b''.join(line for line in data.splitlines(keepends=True) if not line.startswith(b'installed_at='))


def op_record(op: Op) -> dict:
    data = op.data
    if data is not None and op.rel == MARKER:
        data = marker_stable(data)
    return {'edition': op.edition, 'path': op.rel, 'action': op.action, 'before': op.before,
            'after': digest(data) if data is not None else None, 'mode': op.mode, 'order': op.order}


def write_op(edition: str, rel: str, before: State | None, data: bytes, new_mode: int, order: int = ORDER_FILE) -> Op:
    """Existing files keep their mode (plus any executable bits the installer would add)."""
    mode = new_mode if before is None else before['mode'] | (new_mode & 0o111)
    return Op(edition, rel, 'write', before, data, mode, order)


def merge_ops(groups: list[list[Op]]) -> list[Op]:
    """Combine planner outputs; two planners may target one path only with identical bytes.

    The earlier group's permission bits win (the broad Claude update runs after delivery and
    its copy is what finally lands), and the later publication order is kept."""
    merged: dict[str, Op] = {}
    for op in (op for group in groups for op in group):
        prior = merged.get(op.rel)
        if prior is None:
            merged[op.rel] = op
        elif (prior.action, prior.data, prior.before) != (op.action, op.data, op.before):
            raise UpdateError(f'conflicting planned results for {op.rel}')
        else:
            merged[op.rel] = prior._replace(order=max(prior.order, op.order))
    return sorted(merged.values(), key=lambda op: (op.order, op.rel))


# ---------------------------------------------------------------------------------------------
# Claude: declared install.sh mapping and old-baseline ownership
# ---------------------------------------------------------------------------------------------

class ClaudeMapping(NamedTuple):
    files: dict[str, str]         # target rel (".claude/...") -> repository path
    skills: frozenset[str]
    agents: tuple[str, ...]
    retired_lib: tuple[str, ...]
    retired_skills: tuple[str, ...]


def script_text(data: bytes, label: str) -> str:
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError as err:
        raise Incomplete(f'{label} install.sh is not UTF-8; its mapping cannot be read') from err


def parse_array(script: str, name: str, *, required: bool) -> tuple[str, ...]:
    """Read a literal bash array such as AGENTS=( "a" "b" ); refuse anything non-literal."""
    match = re.search(rf'^{name}=\(\n(.*?)^\)', script, re.M | re.S)
    if not match:
        if required:
            raise Incomplete(f'install.sh has no literal {name} array')
        return ()
    items = []
    for line in match[1].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        item = re.fullmatch(r'"([^"$`\\]+)"', stripped)
        if not item or not SAFE_NAME.fullmatch(item[1]):
            raise Incomplete(f'install.sh {name} array is not a plain literal list')
        items.append(item[1])
    return tuple(items)


def optional_hooks(script: str) -> frozenset[str]:
    """Hook basenames install.sh maps to an optional component (never written by a plain --update)."""
    match = re.search(r'^_hook_component\(\) \{\n(.*?)^\}', script, re.M | re.S)
    if not match:
        raise Incomplete('install.sh hook component policy is not recognisable')
    names: set[str] = set()
    for pattern in re.findall(r'^\s*([A-Za-z0-9_.|-]+)\)\s*echo\s+(?:analytics|notifications)\s*;;', match[1], re.M):
        names.update(pattern.split('|'))
    if not names:
        raise Incomplete('install.sh hook component policy lists no optional hooks')
    return frozenset(names)


def top_level(entries: dict[str, tuple[str, str]], directory: str, *, suffix: str = '') -> list[str]:
    """Names of committed files directly in a directory, as a non-dotglob bash glob would see them."""
    names = []
    for path in entries:
        if not path.startswith(directory + '/'):
            continue
        name = path[len(directory) + 1:]
        if '/' not in name and not name.startswith('.') and name.endswith(suffix) and name != '.DS_Store':
            names.append(name)
    return sorted(names)


def claude_mapping(entries: dict[str, tuple[str, str]], script: str, *, include_optional_hooks: bool) -> ClaudeMapping:
    """The files install.sh --update copies from this tree, following its declared policies."""
    files: dict[str, str] = {}
    agents = parse_array(script, 'AGENTS', required=True)
    for agent in agents:
        if f'.claude/agents/{agent}.md' in entries:
            files[f'.claude/agents/{agent}.md'] = f'.claude/agents/{agent}.md'
    for lib in parse_array(script, 'LIB_FILES', required=True):
        if f'.claude/lib/{lib}' in entries:
            files[f'.claude/lib/{lib}'] = f'.claude/lib/{lib}'
    for kind in ('rules', 'commands'):
        for name in top_level(entries, f'.claude/{kind}', suffix='.md'):
            files[f'.claude/{kind}/{name}'] = f'.claude/{kind}/{name}'
    skills = set()
    for path in entries:
        if path.startswith('.claude/skills/') and path.count('/') >= 3:
            name = path.split('/')[2]
            if not name.startswith('.'):
                skills.add(name)
                files[path] = path
    excluded = set() if include_optional_hooks else optional_hooks(script)
    for name in top_level(entries, 'global-config/hooks'):
        if name.endswith('.json') or (name.endswith('.sh') and name not in excluded):
            files[f'.claude/hooks/{name}'] = f'global-config/hooks/{name}'
    for name in top_level(entries, 'global-config/output-styles'):
        files[f'.claude/output-styles/{name}'] = f'global-config/output-styles/{name}'
    if 'global-config/statusline.sh' in entries:
        files['.claude/statusline.sh'] = 'global-config/statusline.sh'
    for rel in files:
        if entries[files[rel]][0] not in REGULAR_MODES:
            raise UpdateError(f'installer source is not a regular file: {files[rel]}')
    return ClaudeMapping(files, frozenset(skills), agents,
                         parse_array(script, 'RETIRED_LIB_FILES', required=False),
                         parse_array(script, 'RETIRED_SKILLS', required=False))


def source_mapping(source: Source) -> ClaudeMapping:
    """What a plain install.sh --update from the clean source HEAD copies (optional hooks excluded)."""
    if 'install.sh' not in source.blobs:
        raise Incomplete('source HEAD has no regular install.sh')
    return claude_mapping(source.entries, script_text(source.blobs['install.sh'], 'source'),
                          include_optional_hooks=False)


def parse_marker(data: bytes) -> dict[str, str]:
    """Parse key=value marker lines as data; duplicate or malformed fields are not evidence."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as err:
        raise Incomplete('install marker is not UTF-8') from err
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[a-z_]+', key):
            raise Incomplete('install marker has a malformed line')
        if key in fields:
            raise Incomplete(f'install marker repeats field {key}')
        fields[key] = value
    return fields


def resolve_baseline(source: Source, fields: dict[str, str]) -> str:
    """Resolve the marker's abbreviated SHA to exactly one commit in HEAD's history."""
    short = fields.get('sha', '')
    if not SHORT_SHA.fullmatch(short):
        raise Incomplete('install marker has no usable baseline sha (absent, unknown or malformed)')
    result = run_git(source.path, 'rev-parse', f'--disambiguate={short}')
    candidates = result.stdout.decode().split() if result.returncode == 0 else []
    commits = []
    if candidates:
        checked = git(source.path, 'cat-file', '--batch-check', stdin=''.join(f'{c}\n' for c in candidates).encode())
        commits = [line.split()[0] for line in checked.decode().splitlines() if line.split()[1:2] == ['commit']]
    if len(commits) != 1:
        raise Incomplete(f'install marker baseline resolves to {len(commits)} commits; ownership cannot be proven')
    baseline = commits[0]
    ancestry = run_git(source.path, 'merge-base', '--is-ancestor', baseline, source.sha)
    if ancestry.returncode != 0:
        raise Incomplete('install marker baseline is not in the source HEAD history')
    return baseline


class Baseline(NamedTuple):
    sha: str
    mapping: ClaudeMapping
    blobs: dict[str, bytes]       # target rel -> old shipped bytes


def load_baseline(source: Source, fields: dict[str, str]) -> Baseline:
    sha = resolve_baseline(source, fields)
    entries = tree_entries(source.path, sha, CLAUDE_TREE_SCOPES)
    if entries.get('install.sh', ('', ''))[0] not in REGULAR_MODES:
        raise Incomplete('baseline commit has no regular install.sh')
    script_blob = read_blobs(source.path, [entries['install.sh'][1]])[entries['install.sh'][1]]
    mapping = claude_mapping(entries, script_text(script_blob, 'baseline'), include_optional_hooks=True)
    oids = {rel: entries[repo][1] for rel, repo in mapping.files.items()}
    blobs = read_blobs(source.path, list(oids.values()))
    return Baseline(sha, mapping, {rel: blobs[oid] for rel, oid in oids.items()})


# ---------------------------------------------------------------------------------------------
# Claude: broad --update planning
# ---------------------------------------------------------------------------------------------

class ClaudePlan(NamedTuple):
    ops: list[Op]
    notes: list[str]
    inputs: dict[str, State] = {}     # every validated owned input the decisions relied on
    same: dict[str, bytes] = {}       # shipped files already holding the source bytes


def load_delivery_manifest(home: Path, delivery: object) -> dict:
    """The delivery manifest validated strictly; refusals never echo manifest contents."""
    _state, raw = read_regular(home, DELIVERY_MANIFEST)
    try:
        if raw is not None:
            strict_json(raw)
        return delivery.load_manifest(home / '.claude')
    except (ValueError, UnicodeDecodeError, delivery.InstallError) as err:
        raise UpdateError('delivery manifest is not strict JSON or lists a path outside the delivery '
                          'resources; refused without changes') from err


def delivery_proofs(home: Path, delivery: object | None) -> dict[str, str]:
    """Delivery-manifest ownership hashes, as target rels; empty when delivery is not manifested."""
    if delivery is None:
        return {}
    manifest = load_delivery_manifest(home, delivery)
    return {f'.claude/{rel}': checksum for rel, checksum in manifest['files'].items()}


def plan_claude_broad(home: Path, source: Source, delivery: object | None) -> ClaudePlan:
    marker_state, marker_bytes = read_regular(home, MARKER)
    if marker_state is None:
        raise Incomplete('broad Claude install marker is absent')
    baseline = load_baseline(source, parse_marker(marker_bytes))
    new = source_mapping(source)
    proofs = delivery_proofs(home, delivery)
    old = baseline.mapping

    def owned(rel: str, data: bytes) -> bool:
        return baseline.blobs.get(rel) == data or proofs.get(rel) == digest(data)

    ops: list[Op] = []
    notes: list[str] = []
    inputs: dict[str, State] = {MARKER: marker_state}
    same: dict[str, bytes] = {}
    for name in sorted(new.skills - old.skills):
        rel = f'.claude/skills/{name}'
        if entry_kind(target_path(home, rel)) is not None and not any(p.startswith(rel + '/') for p in proofs):
            raise UpdateError(f'newly shipped skill collides with an existing entry: {rel}')
    for rel, repo in sorted(new.files.items()):
        want = source.blobs[repo]
        state, data = read_regular(home, rel)
        if state is None:
            ops.append(write_op('claude', rel, None, want, 0o755 if source.entries[repo][0] == '100755' else 0o644))
            continue
        inputs[rel] = state
        if rel not in old.files and rel not in proofs:
            raise UpdateError(f'newly shipped file collides with an existing file: {rel}')
        elif data == want:
            same[rel] = data
        elif owned(rel, data):
            ops.append(write_op('claude', rel, state, want, 0o755 if source.entries[repo][0] == '100755' else 0o644))
        else:
            raise UpdateError(f'locally modified or foreign file: {rel}')
    for name in sorted(new.skills):
        ops += replaced_skill_extras(home, name, old, new, baseline, proofs)
    retired, retained = retired_removals(home, new, baseline)
    ops += retired
    notes += [f'retained without ownership proof: {rel}' for rel in retained]
    notes.append(f'old Claude baseline proven from marker: {baseline.sha}')
    inputs.update((op.rel, op.before) for op in ops if op.before is not None)
    return ClaudePlan(ops, notes, inputs, same)


def mode_repairs(claude: ClaudePlan, modes: dict[str, int]) -> tuple[list[Op], list[str]]:
    """Same-byte shipped files lacking executable bits the real installer sets (for example a
    core hook). Each becomes an explicit mode-only repair that keeps the file's existing
    read/write bits and adds only the staged executable bits; never 'already up to date'."""
    ops, notes = [], []
    for rel, data in sorted(claude.same.items()):
        state = claude.inputs[rel]
        if modes.get(rel, 0) & 0o111 & ~state['mode']:
            ops.append(write_op('claude', rel, state, data, modes[rel]))
            notes.append(f'mode-only repair (adds executable bits, bytes unchanged): {rel}')
    return ops, notes


def replaced_skill_extras(home: Path, name: str, old: ClaudeMapping, new: ClaudeMapping,
                          baseline: Baseline, proofs: dict[str, str]) -> list[Op]:
    """install.sh replaces a shipped skill directory wholesale; refuse any entry that is not owned.

    Old owned files the new source no longer ships are planned as removals."""
    root = f'.claude/skills/{name}'
    kind = entry_kind(target_path(home, root))
    if kind is None:
        return []
    if kind != 'dir':
        raise UpdateError(f'shipped skill path is not a directory: {root}')
    known = set(old.files) | set(new.files) | set(proofs)
    known_dirs = {parent.as_posix() for rel in known if rel.startswith(root + '/') for parent in Path(rel).parents}
    ops = []
    for rel, entry in walk_entries(home, root):
        if entry == 'dir' and rel in known_dirs:
            continue
        if entry != 'file' or rel not in known:
            raise UpdateError(f'extra or non-regular entry inside shipped skill {name}: {rel} ({entry})')
        if rel in new.files:
            continue
        state, data = read_regular(home, rel)
        if baseline.blobs.get(rel) != data and proofs.get(rel) != digest(data):
            raise UpdateError(f'locally modified file the update would remove: {rel}')
        ops.append(Op('claude', rel, 'remove', state, None, None, ORDER_FILE))
    return ops


def retired_removals(home: Path, new: ClaudeMapping, baseline: Baseline) -> tuple[list[Op], list[str]]:
    """Paths install.sh prunes (retired lists, AGENTS entries without source); removed only with byte proof."""
    candidates: list[str] = [f'.claude/lib/{name}' for name in new.retired_lib]
    candidates += [f'.claude/agents/{a}.md' for a in new.agents if f'.claude/agents/{a}.md' not in new.files]
    ops: list[Op] = []
    retained: list[str] = []
    for rel in candidates:
        state, data = read_regular(home, rel)
        if state is None:
            continue
        if baseline.blobs.get(rel) == data:
            ops.append(Op('claude', rel, 'remove', state, None, None, ORDER_FILE))
        else:
            retained.append(rel)
    for name in new.retired_skills:
        root = f'.claude/skills/{name}'
        if name in new.skills or entry_kind(target_path(home, root)) is None:
            continue
        removal = proven_tree_removal(home, root, baseline)
        if removal is None:
            retained.append(root)
        else:
            ops += removal
    return ops, retained


def proven_tree_removal(home: Path, root: str, baseline: Baseline) -> list[Op] | None:
    if entry_kind(target_path(home, root)) != 'dir':
        return None
    shipped = {rel for rel in baseline.blobs if rel.startswith(root + '/')}
    shipped_dirs = {parent.as_posix() for rel in shipped for parent in Path(rel).parents}
    ops = []
    for rel, entry in walk_entries(home, root):
        if entry == 'dir' and rel in shipped_dirs:
            continue
        if entry != 'file' or rel not in shipped:
            return None
        state, data = read_regular(home, rel)
        if baseline.blobs[rel] != data:
            return None
        ops.append(Op('claude', rel, 'remove', state, None, None, ORDER_FILE))
    return ops


# ---------------------------------------------------------------------------------------------
# Claude: private staging forecast of install.sh --update (no optional flags)
# ---------------------------------------------------------------------------------------------

class StagedForecast(NamedTuple):
    ops: list[Op]                 # marker writes
    modes: dict[str, int]         # permission bits install.sh produced per shipped file
    guards: dict[str, State | None]
    order: tuple[str, ...] = ('broad',)   # the update steps actually run in the private stage


def staging_env(stage_home: Path, scratch: Path) -> dict[str, str]:
    """A minimal explicit environment: no inherited account, config or Git selectors."""
    return {'HOME': str(stage_home), 'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C', 'LC_ALL': 'C',
            'TMPDIR': str(scratch), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'}


def collect_staged(stage_home: Path) -> dict[str, tuple[bytes, int]]:
    staged: dict[str, tuple[bytes, int]] = {}
    for directory, dirnames, filenames in os.walk(stage_home):
        for name in dirnames + filenames:
            path = Path(directory, name)
            rel = path.relative_to(stage_home).as_posix()
            kind = entry_kind(path)
            if kind in ('symlink', 'special'):
                raise UpdateError(f'staged broad installer produced a {kind}: {rel}')
            if kind == 'file':
                staged[rel] = (path.read_bytes(), os.lstat(path).st_mode & 0o7777)
    return staged


def seed_stage(stage_home: Path, inputs: dict[str, bytes], modes: dict[str, int], dirs: tuple[str, ...]) -> None:
    """Copy only the given proven-owned inputs (never auth, sessions, env, profiles or controller
    data) into the private stage, with their live permission bits, plus the live directories the
    delivery planner's directory bookkeeping observes."""
    for rel in sorted(dirs):
        (stage_home / rel).mkdir(parents=True, exist_ok=True, mode=0o700)
    for rel, data in inputs.items():
        path = stage_home / rel
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_private(path, data)
        if rel in modes:
            os.chmod(path, modes[rel] & 0o777)


def stage_delivery(stage_home: Path, source: Source, delivery: object) -> None:
    """Apply the real delivery update to the private stage with delivery's own planner and
    transaction (the live target is never passed to it)."""
    claude = stage_home / '.claude'
    try:
        writes, expected, _old, origin, deviations = delivery.plan(claude, source.path, uninstall=False, baseline=None)
        if deviations or origin.get('sha') != source.sha:
            raise Incomplete('staged delivery update did not read the clean source HEAD')
        if writes:
            delivery.transaction(claude, writes, expected, [])
    except delivery.InstallError as err:
        raise Incomplete('staged delivery update refused; nothing was planned') from err


def run_staged_installer(source: Source, inputs: dict[str, bytes], *, delivery: object | None = None,
                         modes: dict[str, int] | None = None,
                         dirs: tuple[str, ...] = ()) -> tuple[dict[str, tuple[bytes, int]], str]:
    """Run the update steps against a private disposable home seeded only with inputs.

    When delivery is given (an already-manifested delivery install), its update is applied to the
    stage FIRST; the source's install.sh --update (no optional flags) runs second. Returns every
    regular file the staged home holds afterwards and the staging HOME string."""
    bash = shutil.which('bash', path=os.environ.get('PATH', os.defpath))
    if bash is None:
        raise Incomplete('bash is unavailable; the broad installer forecast cannot run')
    with tempfile.TemporaryDirectory(prefix='sdlc-update-stage-') as scratch_name:
        scratch = Path(scratch_name).resolve()
        os.chmod(scratch, 0o700)
        stage_home = scratch / 'home'
        (stage_home / '.claude').mkdir(parents=True, mode=0o700)
        seed_stage(stage_home, inputs, modes or {}, dirs)
        if delivery is not None:
            stage_delivery(stage_home, source, delivery)
        try:
            result = subprocess.run([bash, str(source.path / 'install.sh'), '--update'], cwd=scratch,
                                    env=staging_env(stage_home, scratch), stdin=subprocess.DEVNULL,
                                    capture_output=True, timeout=600, check=False)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise Incomplete(f'staged broad installer could not run: {err}') from err
        if result.returncode != 0:
            raise Incomplete(f'staged broad installer exited {result.returncode}; nothing was planned')
        return collect_staged(stage_home), str(stage_home)


def normalize_home(value: object, staged_home: str, live_home: str) -> object:
    """Treat the staging HOME string as the live HOME (comparison data only, never published)."""
    if isinstance(value, str):
        return value.replace(staged_home, live_home)
    if isinstance(value, list):
        return [normalize_home(item, staged_home, live_home) for item in value]
    if isinstance(value, dict):
        return {key: normalize_home(item, staged_home, live_home) for key, item in value.items()}
    return value


def forecast_settings(live: bytes, staged: bytes, staged_home: str, live_home: Path) -> None:
    """Refuse unless the broad installer would leave settings.json as the same whole JSON object."""
    try:
        live_object = strict_json(live)
        staged_object = normalize_home(strict_json(staged), staged_home, str(live_home))
    except (ValueError, UnicodeDecodeError) as err:
        raise UpdateError('settings.json is not strict JSON (for example a duplicate key or '
                          'invalid encoding); refused without changes') from err
    if live_object == staged_object:
        return
    if isinstance(live_object, dict) and isinstance(staged_object, dict):
        changed = {key for key in set(live_object) | set(staged_object)
                   if live_object.get(key) != staged_object.get(key)}
        categories = [name for name in SETTINGS_CATEGORIES if name in changed]
        if changed - set(SETTINGS_CATEGORIES):
            categories.append('other settings')
        detail = f'changed: {", ".join(categories)}'
    else:
        detail = 'whole object'
    raise UpdateError(f'the broad installer would change settings.json ({detail}); review and run '
                      'install.sh --update explicitly. settings.json was not modified')


def check_staged_marker(staged: bytes, live_fields: dict[str, str], source: Source) -> None:
    fields = parse_marker(staged)
    short = fields.get('sha', '')
    if not SHORT_SHA.fullmatch(short) or not source.sha.startswith(short):
        raise Incomplete('staged install marker does not record the source HEAD')
    for name in SELECTION_FIELDS:
        prior = live_fields.get(name)
        expected = prior if prior in ('enabled', 'disabled') else 'unknown'
        if fields.get(name) != expected:
            raise UpdateError(f'staged install marker would change the {name} selection')


def check_staged_delivery(staged: dict[str, tuple[bytes, int]], plan: 'DeliveryPlan', source: Source) -> None:
    """After delivery-first and broad-second staging, the delivery manifest must be exactly the
    planned one and every file it owns must hold the committed source bytes it records."""
    final = staged.get(DELIVERY_MANIFEST)
    if final is None or final[0] != plan.manifest:
        raise Incomplete('the delivery-first stage did not reproduce the planned delivery manifest')
    try:
        files = strict_json(final[0])['files']
    except (ValueError, UnicodeDecodeError, KeyError, TypeError) as err:
        raise Incomplete('the staged delivery manifest is unreadable') from err
    for rel, checksum in files.items():
        target = f'.claude/{rel}'
        output, committed = staged.get(target), source.blobs.get(target)
        if output is None or committed is None or digest(output[0]) != checksum or digest(committed) != checksum:
            raise Incomplete('after staging, the delivery manifest does not match the files it owns')


def stage_broad_update(home: Path, source: Source, delivery_plan: 'DeliveryPlan | None' = None) -> StagedForecast:
    """Forecast the update in a private stage: manifested delivery first, broad --update second."""
    settings_state, settings = read_regular(home, SETTINGS)
    if settings_state is None:
        raise UpdateError('settings.json is absent: the broad installer would create it; '
                          'run install.sh explicitly to review that change')
    marker_state, marker = read_regular(home, MARKER)
    path_state, path_marker = read_regular(home, PATH_MARKER)
    inputs = {SETTINGS: settings, MARKER: marker}
    if path_marker is not None:
        inputs[PATH_MARKER] = path_marker
    modes: dict[str, int] = {}
    if delivery_plan is not None:
        for rel, (data, mode) in delivery_plan.seeds.items():
            inputs[rel], modes[rel] = data, mode
    staged, staged_home = run_staged_installer(
        source, inputs, delivery=delivery_plan.module if delivery_plan else None, modes=modes,
        dirs=delivery_plan.dirs if delivery_plan else ())
    shipped = source_mapping(source).files
    expected = set(shipped) | {SETTINGS, MARKER, PATH_MARKER}
    if delivery_plan is not None:
        expected |= {DELIVERY_MANIFEST} | delivery_plan.outputs
    unexpected = sorted(set(staged) - expected)
    if unexpected:
        raise UpdateError('the broad installer would write unexpected paths: ' + ', '.join(unexpected[:20]))
    missing = sorted(expected - set(staged))
    if missing:
        raise Incomplete('the staged broad installer did not produce: ' + ', '.join(missing[:20]))
    for rel, repo in shipped.items():
        if staged[rel][0] != source.blobs[repo]:
            raise UpdateError(f'staged installer output differs from the committed source: {rel}')
    if delivery_plan is not None:
        check_staged_delivery(staged, delivery_plan, source)
    forecast_settings(settings, staged[SETTINGS][0], staged_home, home)
    check_staged_marker(staged[MARKER][0], parse_marker(marker), source)
    if staged[PATH_MARKER][0] != f'{source.path}\n'.encode():
        raise Incomplete('staged framework path marker does not name the source checkout')
    ops = []
    if marker_stable(marker) != marker_stable(staged[MARKER][0]):
        ops.append(write_op('claude', MARKER, marker_state, staged[MARKER][0], staged[MARKER][1] & 0o777,
                            ORDER_CLAUDE_MARKER))
    if path_marker != staged[PATH_MARKER][0]:
        ops.append(write_op('claude', PATH_MARKER, path_state, staged[PATH_MARKER][0],
                            staged[PATH_MARKER][1] & 0o777, ORDER_CLAUDE_MARKER))
    modes = {rel: staged[rel][1] & 0o777 for rel in shipped}
    guards = {SETTINGS: settings_state, MARKER: marker_state, PATH_MARKER: path_state}
    return StagedForecast(ops, modes, guards, ('delivery', 'broad') if delivery_plan else ('broad',))


def with_staged_modes(ops: list[Op], modes: dict[str, int]) -> list[Op]:
    """Use the permission bits the real installer produced for each shipped file it writes."""
    return [write_op(op.edition, op.rel, op.before, op.data, modes[op.rel], op.order)
            if op.action == 'write' and op.rel in modes else op for op in ops]


# ---------------------------------------------------------------------------------------------
# Delivery resources and the Codex edition (existing hash-owned planners)
# ---------------------------------------------------------------------------------------------

class DeliveryPlan(NamedTuple):
    module: object
    ops: list[Op]
    inputs: dict[str, State | None]           # every target path delivery's planner relied on
    seeds: dict[str, tuple[bytes, int]]       # proven-owned live delivery files + manifest -> (bytes, mode)
    dirs: tuple[str, ...]                     # live directories delivery's dir bookkeeping observes
    manifest: bytes                           # the delivery manifest after the update
    outputs: frozenset[str]                   # target paths delivery writes (not removes)


def delivery_forecast(home: Path, source: Source, delivery: object) -> DeliveryPlan:
    """Plan the manifested delivery resources with scripts/install-delivery.py's own read-only planner
    and capture every input it read (unchanged ones included) as exact state."""
    if f'.claude/{delivery.MANIFEST}' != DELIVERY_MANIFEST:
        raise Incomplete('source delivery installer uses an unexpected manifest location')
    load_delivery_manifest(home, delivery)
    try:
        writes, expected, _old, origin, deviations = delivery.plan(home / '.claude', source.path,
                                                                   uninstall=False, baseline=None)
    except delivery.InstallError as err:
        raise UpdateError(f'delivery planner refused: {err}') from err
    if deviations or origin.get('sha') != source.sha:
        raise UpdateError('delivery planner source provenance does not match the clean source HEAD')
    ops: list[Op] = []
    inputs: dict[str, State | None] = {}
    seeds: dict[str, tuple[bytes, int]] = {}
    dirs: set[str] = set()
    for rel in sorted(expected):
        target = f'.claude/{rel}'
        state, current = read_regular(home, target)
        if current != expected[rel]:
            raise UpdateError(f'target changed during planning: {target}')
        inputs[target] = state
        if state is not None:
            seeds[target] = (current, state['mode'])
        dirs.update(f'.claude/{parent.as_posix()}' for parent in Path(rel).parents if parent != Path('.')
                    and entry_kind(target_path(home, f'.claude/{parent.as_posix()}')) == 'dir')
        if rel not in writes:
            continue
        order = ORDER_DELIVERY_MANIFEST if rel == delivery.MANIFEST else ORDER_FILE
        if writes[rel] is None:
            ops.append(Op('claude', target, 'remove', state, None, None, order))
        else:
            ops.append(write_op('claude', target, state, writes[rel], 0o600, order))
    manifest = writes.get(delivery.MANIFEST) or expected[delivery.MANIFEST]
    outputs = frozenset(f'.claude/{rel}' for rel, data in writes.items() if data is not None)
    return DeliveryPlan(delivery, ops, inputs, seeds, tuple(sorted(dirs)), manifest, outputs)


def plan_delivery(home: Path, source: Source, delivery: object) -> list[Op]:
    """Plan the manifested delivery resources with scripts/install-delivery.py's own read-only planner."""
    return delivery_forecast(home, source, delivery).ops


def check_codex_home(home: Path) -> None:
    configured = os.environ.get('CODEX_HOME')
    if configured and Path(configured).expanduser().resolve() != (home / '.codex').resolve():
        raise Incomplete('CODEX_HOME selects a non-default Codex home; only <home>/.codex is supported')


def codex_resource(rel: object, desired: set[str]) -> bool:
    """True only for a path the Codex edition ships or shipped in its own namespaces.

    Protected native, runtime, approval and inventory state never qualifies, whatever hash a
    manifest records for it."""
    if not isinstance(rel, str):
        return False
    parts = rel.split('/')
    if any(part in ('', '.', '..') or '\\' in part or any(ord(char) < 32 for char in part) for part in parts):
        return False
    if parts[:2] == ['.codex', 'framework']:
        return len(parts) == 3 and parts[2] not in CODEX_PROTECTED_NAMES and (
            parts[2] in CODEX_FRAMEWORK_RESOURCES or rel in desired)
    if rel in desired or rel == '.codex/hooks.json':
        return True
    if parts[:2] == ['.agents', 'skills']:
        return len(parts) >= 4 and parts[2].startswith('sdlc-') and SAFE_NAME.fullmatch(parts[2]) is not None
    return (len(parts) == 3 and parts[:2] == ['.codex', 'agents'] and parts[2].endswith('.toml')
            and SAFE_NAME.fullmatch(parts[2]) is not None)


def validate_codex_manifest(home: Path, framework: object) -> set[str]:
    """Strictly read the Codex manifest and prove every listed path is a shipped resource BEFORE the
    native planner reads any listed payload. Returns the allowed managed path set."""
    state, raw = read_regular(home, CODEX_MANIFEST)
    if state is None:
        raise UpdateError('no Codex user install manifest at this home')
    try:
        manifest = strict_json(raw)
    except (ValueError, UnicodeDecodeError) as err:
        raise UpdateError('Codex ownership manifest is not strict JSON; refused without changes') from err
    files = manifest.get('files') if isinstance(manifest, dict) else None
    if not isinstance(files, dict) or not files:
        raise UpdateError('no Codex user install manifest at this home')
    if manifest.get('user') is not True:
        raise Incomplete('Codex install at this home is project-scoped; only user installs are supported')
    hooks = manifest.get('hooks')
    if type(hooks) is not bool:
        raise Incomplete('Codex ownership manifest has no valid hook choice; refused without changes')
    if hooks != ('.codex/hooks.json' in files):
        raise Incomplete('Codex ownership manifest hook choice does not match its file list; refused before '
                         'the native planner could add or remove the hook configuration')
    try:
        desired = set(framework.build())
    except (ValueError, OSError, framework.yaml.YAMLError) as err:
        raise UpdateError('Codex edition could not be built from the source') from err
    if not all(codex_resource(rel, desired) for rel in files):
        raise UpdateError('Codex ownership manifest lists a path that is not a shipped framework resource '
                          '(for example native approval, runtime or inventory state); refused before reading it')
    return desired | set(files) | {'.codex/hooks.json'}


def codex_plan_paths_allowed(home: Path, plan: object, allowed: set[str]) -> bool:
    """Defensive output scope: the native plan may touch only validated resources, its manifest
    and the user instruction file."""
    extra = {CODEX_MANIFEST, '.codex/AGENTS.md'}
    for path in set(plan.writes) | set(plan.expected):
        try:
            rel = path.relative_to(home).as_posix()
        except ValueError:
            return False
        if rel not in allowed and rel not in extra:
            return False
    return True


class CodexPlan(NamedTuple):
    ops: list[Op]
    inputs: dict[str, State | None]
    framework: object


def codex_native_plan(home: Path, framework: object) -> object:
    """Prevalidate the manifest namespace, then run the native pure planner on the logical home."""
    allowed = validate_codex_manifest(home, framework)
    try:
        plan = framework.plan_installation(home, user=True)
    except subprocess.CalledProcessError as err:
        raise Incomplete('Codex planner could not resolve the source HEAD') from err
    except (ValueError, OSError, framework.yaml.YAMLError) as err:
        raise UpdateError(f'Codex planner refused: {err}') from err
    if plan.root != home:
        raise Incomplete('Codex planner resolved a different home')
    if not codex_plan_paths_allowed(home, plan, allowed):
        raise UpdateError('Codex planner produced a path outside the validated framework resources')
    return plan


def codex_forecast(home: Path, source: Source) -> CodexPlan:
    """Plan the Codex user install with codex/framework.py's pure planner on the live logical home,
    capturing every path it read (unchanged ones included) as exact state."""
    check_codex_home(home)
    framework = load_source_module(source, 'codex/framework.py', 'sdlc_update_codex_framework')
    if not callable(getattr(framework, 'plan_installation', None)):
        raise Incomplete('source codex/framework.py has no pure plan_installation API')
    if Path(framework.REPO).resolve() != source.path:
        raise Incomplete('source codex/framework.py does not build from the selected source')
    plan = codex_native_plan(home, framework)
    ops: list[Op] = []
    inputs: dict[str, State | None] = {}
    for path in sorted(plan.expected):
        rel = path.relative_to(home).as_posix()
        state, current = read_regular(home, rel)
        if current != plan.expected[path]:
            raise UpdateError(f'target changed during planning: {rel}')
        inputs[rel] = state
        if path not in plan.writes:
            continue
        data = plan.writes[path]
        if path == plan.manifest_path and data is not None and strict_json(data).get('source_sha') != source.sha:
            raise Incomplete('Codex manifest would not record the clean source HEAD')
        order = ORDER_CODEX_MANIFEST if path == plan.manifest_path else ORDER_FILE
        if data is None:
            ops.append(Op('codex', rel, 'remove', state, None, None, order))
        else:
            ops.append(write_op('codex', rel, state, data, 0o600, order))
    if set(plan.writes) - set(plan.expected):
        raise UpdateError('Codex planner wrote a path it did not read')
    # The managed instruction block was validated even when unchanged: bind its exact state too.
    inputs.setdefault('.codex/AGENTS.md', read_regular(home, '.codex/AGENTS.md')[0])
    return CodexPlan(ops, inputs, framework)


def plan_codex(home: Path, source: Source) -> tuple[list[Op], object]:
    """Plan the Codex user install with codex/framework.py's pure planner on the live logical home."""
    forecast = codex_forecast(home, source)
    return forecast.ops, forecast.framework


# ---------------------------------------------------------------------------------------------
# Whole plan, fingerprint and private plan file
# ---------------------------------------------------------------------------------------------

class UpdatePlan(NamedTuple):
    source: Source
    home: Path
    identity: dict
    editions: tuple[str, ...]
    ops: list[Op]
    guards: dict[str, State | None]       # every validated input no operation writes (exact state)
    trees: dict[str, list[list[str]]]     # shipped and touched skill roots -> [[path, kind], ...]
    notes: list[str]
    fingerprint: str
    broad: bool
    delivery: object | None
    codex: object | None


def exists(home: Path, rel: str) -> bool:
    return entry_kind(target_path(home, rel)) is not None


def select_editions(home: Path, requested: str | None) -> tuple[str, ...]:
    """Default: every installed integration. Explicit selection must name installed ones only."""
    installed = {'claude': exists(home, MARKER) or exists(home, DELIVERY_MANIFEST),
                 'codex': exists(home, CODEX_MANIFEST)}
    if requested is None:
        chosen = tuple(name for name in EDITIONS if installed[name])
        if not chosen:
            raise UpdateError('no installed framework integration found at this home; new installs are not performed')
        return chosen
    chosen = EDITIONS if requested == 'both' else (requested,)
    absent = [name for name in chosen if not installed[name]]
    if absent:
        raise UpdateError(f'selected edition is not installed at this home: {", ".join(absent)}; '
                          'new installs are not performed')
    return chosen


def claude_config_notes(home: Path) -> list[str]:
    configured = os.environ.get('CLAUDE_CONFIG_DIR')
    if configured and Path(configured).expanduser().resolve() != (home / '.claude').resolve():
        return ['CLAUDE_CONFIG_DIR selects a different Claude configuration directory (not shown); '
                'this run updates only the global install target <home>/.claude, never that directory']
    return []


def target_identity(home: Path) -> dict:
    info = os.stat(home)
    return {'home': str(home), 'device': info.st_dev, 'inode': info.st_ino}


def skill_root(rel: str) -> str | None:
    parts = rel.split('/')
    return '/'.join(parts[:3]) if len(parts) > 3 and parts[:2] == ['.claude', 'skills'] else None


def tree_snapshot(home: Path, root: str) -> list[list[str]]:
    if entry_kind(target_path(home, root)) != 'dir':
        return []
    return [[rel, kind] for rel, kind in walk_entries(home, root)]


def skill_tree_guards(home: Path, ops: list[Op], shipped_roots: tuple[str, ...] = ()) -> dict[str, list[list[str]]]:
    """Complete entry inventory (hidden, empty-dir, special and symlink entries included) of
    every shipped skill directory the decisions relied on, plus every one this update writes
    into or removes from."""
    roots = {root for op in ops if op.edition == 'claude' and (root := skill_root(op.rel))}
    roots.update(shipped_roots)
    return {root: tree_snapshot(home, root) for root in sorted(roots)}


def merge_inputs(groups: list[dict[str, State | None]], ops: list[Op]) -> dict[str, State | None]:
    """Every validated input that no operation writes, as exact state. Two planners (or a planner
    and an operation) that observed different states for one path mean the target moved."""
    merged: dict[str, State | None] = {}
    for inputs in groups:
        for rel, state in inputs.items():
            if rel in merged and merged[rel] != state:
                raise UpdateError(f'target changed during planning: {rel}')
            merged[rel] = state
    for op in ops:
        if op.rel in merged and merged.pop(op.rel) != op.before:
            raise UpdateError(f'target changed during planning: {op.rel}')
    return merged


def compute_fingerprint(source: Source, identity: dict, editions: tuple[str, ...], ops: list[Op],
                        guards: dict[str, State | None], trees: dict[str, list[list[str]]]) -> str:
    document = {'schema': SCHEMA, 'source': {'path': str(source.path), 'sha': source.sha}, 'target': identity,
                'editions': list(editions), 'operations': [op_record(op) for op in ops], 'guards': guards,
                'trees': trees}
    return digest(json.dumps(document, sort_keys=True, separators=(',', ':')).encode())


def build_plan(home: Path, source_path: Path, requested: str | None,
               expected_source: dict | None = None) -> UpdatePlan:
    """Read-only: compute every operation, guard and note for an update of this home.

    expected_source ({'path', 'sha'} of a reviewed plan) is enforced immediately after the source
    is read, before any source module is executed or any installer is staged."""
    source = read_source(source_path)
    if expected_source is not None and {'path': str(source.path), 'sha': source.sha} != expected_source:
        raise UpdateError('the source checkout no longer matches the plan (source); no source code was run '
                          'and nothing was changed. Run plan again and review it')
    editions = select_editions(home, requested)
    notes: list[str] = []
    groups: list[list[Op]] = []
    inputs: list[dict[str, State | None]] = []
    shipped_roots: set[str] = set()
    broad = False
    delivery = codex = None
    if 'claude' in editions:
        notes += claude_config_notes(home)
        delivery_plan = None
        if exists(home, DELIVERY_MANIFEST):
            delivery = load_source_module(source, 'scripts/install-delivery.py', 'sdlc_update_install_delivery')
            delivery_plan = delivery_forecast(home, source, delivery)
            shipped_roots.update(f'.claude/skills/{name}' for name in delivery.SKILLS)
        if exists(home, MARKER):
            broad = True
            claude = plan_claude_broad(home, source, delivery)
            staged = stage_broad_update(home, source, delivery_plan)
            repairs, repair_notes = mode_repairs(claude, staged.modes)
            # Broad first: on an identical shared path its staged (final) permission bits win.
            groups.append(with_staged_modes(claude.ops, staged.modes) + repairs + staged.ops)
            inputs += [claude.inputs, staged.guards]
            shipped_roots.update(f'.claude/skills/{name}' for name in source_mapping(source).skills)
            notes += claude.notes + repair_notes
            notes.append('staged forecast order: ' + ' then '.join(staged.order))
        else:
            notes.append('broad Claude install marker absent: only delivery-manifested resources are updated')
        if delivery_plan is not None:
            groups.append(delivery_plan.ops)
            inputs.append(delivery_plan.inputs)
    if 'codex' in editions:
        codex_plan = codex_forecast(home, source)
        codex = codex_plan.framework
        groups.append(codex_plan.ops)
        inputs.append(codex_plan.inputs)
        notes.append('Codex hook definitions keep their installed edition; native /hooks trust is not checked')
    ops = merge_ops(groups)
    guards = merge_inputs(inputs, ops)
    trees = skill_tree_guards(home, ops, tuple(sorted(shipped_roots)))
    # The Codex build and the staged installer read working-tree bytes: prove they still are HEAD's.
    if read_source(source.path) != source:
        raise UpdateError('source checkout changed while planning; nothing was planned')
    identity = target_identity(home)
    return UpdatePlan(source, home, identity, editions, ops, guards, trees, notes,
                      compute_fingerprint(source, identity, editions, ops, guards, trees),
                      broad, delivery, codex)


PLAN_KEYS = frozenset({'schema', 'status', 'executed', 'source', 'target', 'editions', 'fingerprint',
                       'operations', 'notes', 'limits'})


def plan_document(plan: UpdatePlan) -> dict:
    return {'schema': SCHEMA, 'status': 'PLAN_READY', 'executed': False,
            'source': {'path': str(plan.source.path), 'sha': plan.source.sha}, 'target': plan.identity,
            'editions': list(plan.editions), 'fingerprint': plan.fingerprint,
            'operations': [{'edition': op.edition, 'path': op.rel, 'action': op.action} for op in plan.ops],
            'notes': list(plan.notes), 'limits': list(LIMITS)}


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def require_private_dir(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError as err:
        raise UpdateError(f'{label} directory does not exist') from err
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise UpdateError(f'{label} directory must be a private (0700) non-symlink directory owned by you')


def open_private_parent(path: Path, label: str) -> int:
    """Open a plan file's parent without following symlinks and prove it is a private directory
    owned by this user. Callers open the leaf relative to the returned descriptor (O_NOFOLLOW), so
    neither an ancestor checked by unaliased_path nor the parent can be swapped between check
    and use without the open failing (a same-user race limit still applies; see LIMITS)."""
    try:
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError as err:
        raise UpdateError(f'{label} directory does not exist') from err
    except OSError as err:
        raise UpdateError(f'{label} directory must be a private (0700) non-symlink directory owned by you') from err
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        os.close(fd)
        raise UpdateError(f'{label} directory must be a private (0700) non-symlink directory owned by you')
    return fd


def write_plan_file(path: Path, document: dict) -> Path:
    path = unaliased_path(path, '--out')
    parent = open_private_parent(path, '--out')
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    except FileExistsError as err:
        raise UpdateError('--out file already exists; refusing to overwrite it') from err
    except OSError as err:
        raise UpdateError(f'cannot create --out file: {err.strerror}') from err
    finally:
        os.close(parent)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write((json.dumps(document, indent=2, sort_keys=True) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    return path


def load_plan_file(path: Path) -> dict:
    """Read a private plan file and validate its closed schema. Plans carry no payloads or argv."""
    path = unaliased_path(path, '--plan')
    parent = open_private_parent(path, '--plan')
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except OSError as err:
        raise UpdateError(f'cannot open plan file: {err.strerror}') from err
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise UpdateError('plan file must be a private (0600) regular file owned by you')
        if info.st_size > MAX_PLAN_BYTES:
            raise UpdateError('plan file is too large')
        raw = stream.read(MAX_PLAN_BYTES + 1)
    try:
        document = strict_json(raw)
    except (ValueError, UnicodeDecodeError) as err:
        raise UpdateError('plan file is not strict JSON') from err
    validate_plan_document(document)
    return document


def is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_plan_document(document: object) -> None:
    def require(condition: bool, what: str) -> None:
        if not condition:
            raise UpdateError(f'invalid plan file: {what}')

    require(isinstance(document, dict) and set(document) == PLAN_KEYS, 'unexpected or missing keys')
    require(document['schema'] == SCHEMA and document['status'] == 'PLAN_READY'
            and document['executed'] is False, 'schema/status')
    source = document['source']
    require(isinstance(source, dict) and set(source) == {'path', 'sha'} and isinstance(source['path'], str)
            and isinstance(source['sha'], str) and FULL_SHA.fullmatch(source['sha']) is not None, 'source')
    target = document['target']
    require(isinstance(target, dict) and set(target) == {'home', 'device', 'inode'}
            and isinstance(target['home'], str) and is_int(target['device']) and is_int(target['inode']), 'target')
    editions = document['editions']
    require(isinstance(editions, list) and editions and len(set(editions)) == len(editions)
            and all(name in EDITIONS for name in editions), 'editions')
    require(isinstance(document['fingerprint'], str)
            and re.fullmatch('[0-9a-f]{64}', document['fingerprint']) is not None, 'fingerprint')
    operations = document['operations']
    require(isinstance(operations, list), 'operations')
    for op in operations:
        require(isinstance(op, dict) and set(op) == {'edition', 'path', 'action'} and op['edition'] in EDITIONS
                and op['action'] in ('write', 'remove') and isinstance(op['path'], str), 'operation entry')
        parts = op['path'].split('/')
        require(op['path'].startswith(('.claude/', '.codex/', '.agents/skills/'))
                and not any(part in ('', '.', '..') for part in parts), 'operation path')
    for key in ('notes', 'limits'):
        require(isinstance(document[key], list) and all(isinstance(item, str) for item in document[key]), key)


# ---------------------------------------------------------------------------------------------
# Locks: this updater's own cooperative lock plus the existing installers' locks
# ---------------------------------------------------------------------------------------------

class HeldLock(NamedTuple):
    path: Path
    is_dir: bool                  # install.sh uses a mkdir lock holding a pid file
    token: bytes


def acquire_lock(home: Path, rel: str, token: bytes) -> HeldLock:
    path = target_path(home, rel)
    is_dir = rel.endswith('.lock.d')
    try:
        if is_dir:
            os.mkdir(path, 0o700)
    except FileExistsError as err:
        raise Incomplete(f'lock is held: {rel}; another install or update may be running (a stale lock '
                         'needs owner investigation; it is never removed automatically)') from err
    try:
        fd = os.open(path / 'pid' if is_dir else path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as err:
        if is_dir:
            path.rmdir()
        if isinstance(err, FileExistsError):
            raise Incomplete(f'lock is held: {rel}; another install or update may be running (a stale lock '
                             'needs owner investigation; it is never removed automatically)') from err
        raise
    with os.fdopen(fd, 'wb') as stream:
        stream.write(token)
    return HeldLock(path, is_dir, token)


def release_lock(lock: HeldLock) -> str | None:
    """Remove a lock only while it still holds this run's token; report anything else."""
    token_file = lock.path / 'pid' if lock.is_dir else lock.path
    try:
        info = os.lstat(token_file)
        if not stat.S_ISREG(info.st_mode) or token_file.read_bytes() != lock.token:
            return f'lock {lock.path.name} no longer holds this run\'s token; left in place'
        token_file.unlink()
        if lock.is_dir:
            lock.path.rmdir()
    except OSError as err:
        return f'lock {lock.path.name} could not be released ({err.strerror}); remove it after investigation'
    return None


@contextmanager
def held_locks(home: Path, notes: list[str]) -> Iterator[None]:
    """Hold this updater's lock and every existing installer lock that applies to this home.

    Holding the installers' own locks makes a cooperating install.sh --update, delivery or
    Codex installer back off. Locks are cooperative only (see LIMITS)."""
    held: list[HeldLock] = []
    pid_token = f'{os.getpid()}\n'.encode()
    try:
        held.append(acquire_lock(home, LOCK, f'{os.getpid()} {time.time_ns()}\n'.encode()))
        has_claude_dir = entry_kind(target_path(home, '.claude')) == 'dir'
        for rel in FOREIGN_LOCKS:
            if rel.startswith('.claude/') and not has_claude_dir:
                continue
            held.append(acquire_lock(home, rel, pid_token))
        yield
    finally:
        for lock in reversed(held):
            problem = release_lock(lock)
            if problem:
                notes.append(problem)


# ---------------------------------------------------------------------------------------------
# Verified owner-private backup (written and verified before the first live mutation)
# ---------------------------------------------------------------------------------------------

class Backup(NamedTuple):
    directory: Path
    copies: dict[str, Path]       # target rel -> private copy of its pre-update bytes


def utc_now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def log_line(record: dict) -> bytes:
    return (json.dumps({**record, 'time': utc_now()}, sort_keys=True, separators=(',', ':')) + '\n').encode()


class RunLog:
    """Owner-private, append-only JSON-lines record of this run's ACTUAL attempts and outcomes.

    It lives beside the backup and carries only paths, actions, digests/modes and outcomes (never
    file payloads, settings or credentials). Each record is fsynced before the step it announces
    proceeds, so after a crash an "attempt" without a later outcome marks an unknown boundary.
    The planned operations are in backup.json; this log never repeats them as if they ran."""

    def __init__(self) -> None:
        self.directory: Path | None = None    # backup directory, as soon as it exists
        self.path: Path | None = None         # this log, as soon as it exists
        self.gaps = 0                          # best-effort records that could not be written

    def start(self, header: dict) -> None:
        path = self.directory / OPERATION_LOG
        write_private(path, log_line(header))
        self.path = path

    def record(self, event: str, **fields: object) -> None:
        """Append one record durably; raises (fail-closed) so no mutation proceeds unlogged."""
        if self.path is None:
            raise UpdateError('the operation log is unavailable; nothing further is attempted')
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        with os.fdopen(fd, 'ab') as stream:
            stream.write(log_line({'event': event, **fields}))
            stream.flush()
            os.fsync(stream.fileno())

    def best_effort(self, event: str, **fields: object) -> None:
        """Used where stopping would be worse (rollback, final status); a failure is counted and
        reported as an incomplete log rather than silently dropped."""
        try:
            self.record(event, **fields)
        except (OSError, UpdateError):
            self.gaps += 1

    def notes(self) -> list[str]:
        if self.path is not None and self.gaps:
            return [f'the operation log could not record {self.gaps} step(s); it is incomplete']
        return []


def ensure_private_dir(home: Path, rel: str) -> Path:
    path = target_path(home, rel)
    if entry_kind(path) is None:
        os.mkdir(path, 0o700)
    require_private_dir(path, rel)
    return path


def read_private_copy(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise UpdateError(f'backup copy is not a private regular file: {path.name}')
        return stream.read()


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_backup(home: Path, plan: UpdatePlan, run_log: RunLog | None = None) -> Backup:
    """Copy every pre-update file an operation replaces or removes, then prove each copy on disk.

    The backup directory and the operation log are published on run_log the moment they exist, so
    a failure part-way through still reports where the partial private artifacts are."""
    run_log = run_log if run_log is not None else RunLog()
    ensure_private_dir(home, STATE_DIR)
    backups = ensure_private_dir(home, f'{STATE_DIR}/backups')
    directory = backups / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + f'-{os.getpid()}')
    os.mkdir(directory, 0o700)
    run_log.directory = directory
    require_private_dir(directory, 'backup')
    run_log.start({'event': 'start', 'schema': 'sdlc-framework-update-log/1', 'fingerprint': plan.fingerprint,
                   'source': {'path': str(plan.source.path), 'sha': plan.source.sha}, 'home': str(home),
                   'planned_operations': len(plan.ops),
                   'meaning': 'Planned operations are listed in backup.json. Only attempt/applied and rollback '
                              'records describe what actually ran; an attempt without a later outcome record '
                              'has an unknown outcome (for example after a process kill).'})
    entries: list[dict] = []
    copies: dict[str, Path] = {}
    for index, op in enumerate(plan.ops):
        state, data = read_regular(home, op.rel)
        if state != op.before:
            raise UpdateError(f'target changed before backup: {op.rel}')
        record = {'path': op.rel, 'action': op.action, 'before': op.before, 'copy': None}
        if data is not None:
            record['copy'] = f'{index:05d}'
            copies[op.rel] = directory / record['copy']
            write_private(copies[op.rel], data)
        entries.append(record)
    index_bytes = (json.dumps({
        'schema': 'sdlc-framework-update-backup/1', 'fingerprint': plan.fingerprint,
        'source_sha': plan.source.sha, 'home': str(home), 'entries': entries, 'operation_log': OPERATION_LOG,
        'restore': 'For each entry with a copy, the copy holds the exact pre-update bytes of <home>/<path> '
                   '(mode/uid/gid in "before"); an entry without a copy did not exist before the update. '
                   'Entries are PLANNED operations; operations.jsonl records which were actually attempted.',
    }, indent=2, sort_keys=True) + '\n').encode()
    write_private(directory / 'backup.json', index_bytes)
    fsync_directory(directory)
    for record in entries:
        if record['copy'] and digest(read_private_copy(directory / record['copy'])) != record['before']['digest']:
            raise UpdateError(f'backup verification failed for {record["path"]}')
    if read_private_copy(directory / 'backup.json') != index_bytes:
        raise UpdateError('backup index verification failed')
    run_log.record('backup-verified', copies=len(copies))
    return Backup(directory, copies)


# ---------------------------------------------------------------------------------------------
# Guarded live transaction
# ---------------------------------------------------------------------------------------------

UNEXPECTED = 'unexpected'     # observed entry is not a plain regular file reachable without symlinks


class Attempt(NamedTuple):
    op: Op
    after: State | None           # exact state this attempt published (None = removed)


def observe(home: Path, rel: str) -> State | None | str:
    try:
        state, _data = read_regular(home, rel)
    except UpdateError:
        return UNEXPECTED
    return state


def require_state(home: Path, rel: str, expected: State | None) -> None:
    if observe(home, rel) != expected:
        raise UpdateError(f'concurrent modification detected at write boundary: {rel}')


def stage_temp(path: Path, data: bytes, mode: int, owner: State | None) -> tuple[str, State]:
    """Write a fully prepared sibling temporary file and return its name and exact state."""
    fd, name = tempfile.mkstemp(prefix='.sdlc-update-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            info = os.fstat(stream.fileno())
            if owner is not None and (info.st_uid, info.st_gid) != (owner['uid'], owner['gid']):
                os.fchown(stream.fileno(), owner['uid'], owner['gid'])
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
            info = os.fstat(stream.fileno())
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return name, {'digest': digest(data), 'mode': info.st_mode & 0o7777, 'uid': info.st_uid, 'gid': info.st_gid}


def make_parents(home: Path, path: Path, made_dirs: list[Path]) -> None:
    """Create missing ancestors one by one; a failing mkdir never marks the destination written."""
    for parent in reversed(path.parents):
        if parent != home and home in parent.parents and entry_kind(parent) is None:
            os.mkdir(parent)
            made_dirs.append(parent)


def state_summary(state: State | None) -> dict | None:
    """Digest and mode only: enough to identify an output, never its payload."""
    return None if state is None else {'digest': state['digest'], 'mode': state['mode']}


def publish(home: Path, op: Op, attempts: list[Attempt], made_dirs: list[Path],
            run_log: RunLog | None = None) -> None:
    """Apply one operation after a fresh expected-state check at its real write boundary.

    The attempt is logged durably and recorded only after parents and the temporary file are
    prepared, immediately before the os.replace/os.unlink that mutates the destination (so a
    replace-then-error is still undone, and a failed mkdir never marks the destination
    attempted); a destination whose mutation never landed is recognised by its unchanged state."""
    path = target_path(home, op.rel)
    require_state(home, op.rel, op.before)
    announce = {'edition': op.edition, 'path': op.rel, 'action': op.action}
    if op.action == 'remove':
        if run_log is not None:
            run_log.record('attempt', **announce)
        attempts.append(Attempt(op, None))
        os.unlink(path)
        if run_log is not None:
            run_log.record('applied', **announce, after=None)
        return
    make_parents(home, path, made_dirs)
    name, after = stage_temp(path, op.data, op.mode, op.before)
    try:
        target_path(home, op.rel)
        require_state(home, op.rel, op.before)
        if run_log is not None:
            run_log.record('attempt', **announce)
        attempts.append(Attempt(op, after))
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    if run_log is not None:
        run_log.record('applied', **announce, after=state_summary(after))


class Recovery(NamedTuple):
    unrecovered: list[str]
    retained_dirs: list[str]
    outcomes: list[dict] = []     # per actual attempt: edition, path, action, outcome


def restore_attempt(home: Path, attempt: Attempt, backup: Backup) -> tuple[str, str | None]:
    """Undo one attempted mutation only while the path still holds exactly this attempt's output.

    Returns (outcome, problem); problem is None when the path is back to its pre-update state."""
    rel, before = attempt.op.rel, attempt.op.before
    current = observe(home, rel)
    if current == before:
        return 'not-landed', None
    if current != attempt.after:
        return 'left-concurrent', f'{rel} (changed by another writer after this update wrote it; left as found)'
    path = target_path(home, rel)
    if before is None:
        os.unlink(path)
        return 'rolled-back', None
    data = read_private_copy(backup.copies[rel])
    if digest(data) != before['digest']:
        return 'restore-refused', f'{rel} (backup copy no longer matches; not restored)'
    name, _state = stage_temp(path, data, before['mode'], before)
    try:
        if observe(home, rel) != attempt.after:
            return 'left-concurrent', f'{rel} (changed by another writer during rollback; left as found)'
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    if observe(home, rel) == before:
        return 'rolled-back', None
    return 'metadata-differs', f'{rel} (restored bytes but not its exact metadata)'


def restore_one(home: Path, attempt: Attempt, backup: Backup) -> str | None:
    """Undo one attempted mutation only while the path still holds exactly this attempt's output."""
    return restore_attempt(home, attempt, backup)[1]


def rollback(home: Path, attempts: list[Attempt], made_dirs: list[Path], backup: Backup,
             run_log: RunLog | None = None) -> Recovery:
    """Restore only this run's own recorded attempts, newest first; every step is logged best-effort
    (a log failure must not stop recovery, and is reported as an incomplete log)."""
    log = run_log if run_log is not None else RunLog()
    unrecovered: list[str] = []
    outcomes: list[dict] = []
    for attempt in reversed(attempts):
        announce = {'edition': attempt.op.edition, 'path': attempt.op.rel, 'action': attempt.op.action}
        log.best_effort('rollback-attempt', **announce)
        try:
            outcome, problem = restore_attempt(home, attempt, backup)
        except (OSError, UpdateError) as err:
            reason = safe_os_error(err) if isinstance(err, OSError) else str(err)
            outcome, problem = 'restore-failed', f'{attempt.op.rel} (restore failed: {reason})'
        log.best_effort('rollback-outcome', **announce, outcome=outcome)
        outcomes.append({**announce, 'outcome': outcome})
        if problem:
            unrecovered.append(problem)
    retained: list[str] = []
    for directory in reversed(made_dirs):
        try:
            directory.rmdir()
        except OSError:
            retained.append(directory.relative_to(home).as_posix())
    outcomes.reverse()
    return Recovery(unrecovered, retained, outcomes)


# ---------------------------------------------------------------------------------------------
# Final postchecks (any problem triggers the guarded rollback)
# ---------------------------------------------------------------------------------------------

def expected_tree(root: str, entries: list[list[str]], attempts: list[Attempt], made_dirs: list[Path],
                  home: Path) -> set[tuple[str, str]]:
    tree = {(rel, kind) for rel, kind in entries}
    for attempt in attempts:
        if skill_root(attempt.op.rel) != root:
            continue
        if attempt.after is None:
            tree.discard((attempt.op.rel, 'file'))
        else:
            tree.add((attempt.op.rel, 'file'))
    tree.update((path.relative_to(home).as_posix(), 'dir') for path in made_dirs
                if path.relative_to(home).as_posix().startswith(root + '/'))
    return tree


def replan_problems(home: Path, plan: UpdatePlan) -> list[str]:
    """The existing hash-owned planners must now report no remaining change."""
    problems: list[str] = []
    if plan.delivery is not None:
        try:
            load_delivery_manifest(home, plan.delivery)
            writes = plan.delivery.plan(home / '.claude', plan.source.path, uninstall=False, baseline=None)[0]
        except (UpdateError, plan.delivery.InstallError, OSError):
            writes = {'(delivery planner refused the updated state)': None}
        problems += [f'delivery still differs: {rel}' for rel in sorted(writes)]
    if plan.codex is not None:
        try:
            changes = codex_native_plan(home, plan.codex).changes
        except (UpdateError, OSError):
            changes = ['(Codex planner refused the updated state)']
        problems += [f'Codex install still differs: {change}' for change in changes]
    return problems


def postcheck(home: Path, plan: UpdatePlan, attempts: list[Attempt], made_dirs: list[Path],
              inventory_before: set[str]) -> list[str]:
    problems: list[str] = []
    published = {attempt.op.rel: attempt.after for attempt in attempts}
    for op in plan.ops:
        if op.rel not in published or observe(home, op.rel) != published[op.rel]:
            problems.append(f'{op.rel} does not hold the published result')
    problems += [f'{rel} changed during the update' for rel, state in plan.guards.items()
                 if observe(home, rel) != state]
    for root, entries in plan.trees.items():
        actual = {(rel, kind) for rel, kind in tree_snapshot(home, root)}
        if actual != expected_tree(root, entries, attempts, made_dirs, home):
            problems.append(f'unexpected entries changed inside {root}')
    removed = {op.rel for op in plan.ops if op.action == 'remove'}
    lost = sorted(inventory_before - removed - inventory(home))
    problems += [f'path lost without a planned removal: {rel}' for rel in lost[:20]]
    return problems + replan_problems(home, plan)


# ---------------------------------------------------------------------------------------------
# Plan binding and apply orchestration
# ---------------------------------------------------------------------------------------------

RESULT_SCHEMA = 'sdlc-framework-update-result/1'


def check_binding(plan: UpdatePlan, document: dict) -> None:
    """Refuse before any mutation unless the recomputed plan is exactly the reviewed one."""
    mismatched = [name for name, same in (
        ('source', document['source'] == {'path': str(plan.source.path), 'sha': plan.source.sha}),
        ('target', document['target'] == plan.identity),
        ('editions', document['editions'] == list(plan.editions)),
        ('operations', document['operations'] == plan_document(plan)['operations']),
        ('fingerprint', document['fingerprint'] == plan.fingerprint)) if not same]
    if mismatched:
        raise UpdateError('the source or target no longer matches the plan (' + ', '.join(mismatched)
                          + '); nothing was changed. Run plan again and review it')


def result_document(status: str, *, executed: bool, plan: UpdatePlan | None = None, error: str | None = None,
                    backup: Path | None = None, recovery: str = 'not-needed', recovery_paths: Recovery | None = None,
                    notes: list[str] | None = None, operation_log: Path | None = None,
                    attempts: list[dict] | None = None) -> dict:
    """'operations' are the PLANNED operations; 'attempts' are the ones actually attempted, each
    with its final outcome, and 'operation_log' is the private durable log when one was created."""
    document = {'schema': RESULT_SCHEMA, 'status': status, 'executed': executed, 'error': error,
                'backup': str(backup) if backup else None, 'recovery': recovery,
                'operation_log': str(operation_log) if operation_log else None,
                'attempts': list(attempts or []),
                'unrecovered': recovery_paths.unrecovered if recovery_paths else [],
                'retained_directories': recovery_paths.retained_dirs if recovery_paths else [],
                'notes': list(notes or []), 'limits': list(LIMITS)}
    if plan is not None:
        document.update(source={'path': str(plan.source.path), 'sha': plan.source.sha}, target=plan.identity,
                        editions=list(plan.editions), fingerprint=plan.fingerprint,
                        operations=plan_document(plan)['operations'])
        document['notes'] = list(plan.notes) + document['notes']
    return document


def run_transaction(home: Path, plan: UpdatePlan) -> dict:
    """Back up, recheck, publish in order, postcheck; roll back only this attempt's own output on error."""
    if not plan.ops:
        return result_document('PASS', executed=False, plan=plan, notes=['already up to date; nothing written'])
    inventory_before = inventory(home)
    run_log = RunLog()
    try:
        backup = create_backup(home, plan, run_log)
    except Exception as err:  # noqa: BLE001 - reported (sanitized) with the partial artifacts' location
        run_log.best_effort('backup-failed')
        notes = ['the backup was not completed and verified; no framework file was written. The partial '
                 'private backup directory is retained for review'] if run_log.directory else []
        return result_document(getattr(err, 'status', 'FAIL'), executed=False, plan=plan, error=error_text(err),
                                backup=run_log.directory, operation_log=run_log.path,
                                notes=notes + run_log.notes())
    attempts: list[Attempt] = []
    made_dirs: list[Path] = []
    try:
        for root, entries in plan.trees.items():
            if tree_snapshot(home, root) != entries:
                raise UpdateError(f'entries inside {root} changed before the first write')
        for rel, state in plan.guards.items():
            require_state(home, rel, state)
        run_log.record('prechecked', guards=len(plan.guards), trees=len(plan.trees))
        for op in plan.ops:
            publish(home, op, attempts, made_dirs, run_log)
        problems = postcheck(home, plan, attempts, made_dirs, inventory_before)
        if problems:
            raise UpdateError('postcheck failed: ' + '; '.join(problems[:20]))
    except BaseException as err:
        run_log.best_effort('rollback-start', reason=type(err).__name__)
        recovery = rollback(home, attempts, made_dirs, backup, run_log)
        status = 'INCOMPLETE' if recovery.unrecovered else getattr(err, 'status', 'FAIL')
        outcome = 'manual-required' if recovery.unrecovered else ('rolled-back' if attempts else 'not-needed')
        run_log.best_effort('end', status=status if isinstance(err, Exception) else 'INTERRUPTED', recovery=outcome)
        if not isinstance(err, Exception):
            raise
        return result_document(status, executed=bool(attempts), plan=plan, error=error_text(err),
                               backup=backup.directory, recovery=outcome, recovery_paths=recovery,
                               operation_log=run_log.path, attempts=recovery.outcomes, notes=run_log.notes())
    run_log.best_effort('end', status='PASS', recovery='not-needed')
    applied = [{'edition': a.op.edition, 'path': a.op.rel, 'action': a.op.action, 'outcome': 'applied'}
               for a in attempts]
    # The verified files stay installed, but a run whose required operation log is incomplete is not PASS.
    status = 'INCOMPLETE' if run_log.gaps else 'PASS'
    gap_notes = ['every planned change was applied, verified and kept, but the operation log is incomplete, '
                 'so the run evidence is incomplete; compare the log with the retained backup'] if run_log.gaps else []
    return result_document(status, executed=True, plan=plan, backup=backup.directory,
                           operation_log=run_log.path, attempts=applied, notes=gap_notes + run_log.notes())


def error_text(err: BaseException) -> str:
    return str(err) if isinstance(err, UpdateError) else safe_os_error(err)


def apply_update(plan_file: Path) -> dict:
    document = load_plan_file(plan_file)
    home = resolve_home(Path(document['target']['home']))
    if target_identity(home) != document['target']:
        raise UpdateError('target home identity differs from the plan; nothing was changed')
    editions = document['editions']
    requested = 'both' if len(editions) == len(EDITIONS) else editions[0]
    lock_notes: list[str] = []
    try:
        with held_locks(home, lock_notes):
            plan = build_plan(home, Path(document['source']['path']), requested,
                              expected_source=document['source'])
            check_binding(plan, document)
            result = run_transaction(home, plan)
    except UpdateError as err:
        return result_document(err.status, executed=False, error=str(err), notes=lock_notes)
    except OSError as err:
        return result_document('FAIL', executed=False, error=safe_os_error(err), notes=lock_notes)
    result['notes'] += lock_notes
    return result


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------

EXIT_CODES = {'PLAN_READY': 0, 'PASS': 0, 'FAIL': 1, 'INCOMPLETE': 2}


def safe_os_error(err: BaseException) -> str:
    """Error metadata only: the exception type, OS reason and path, never file contents."""
    if isinstance(err, OSError):
        location = f' ({err.filename})' if err.filename else ''
        return f'{type(err).__name__}: {err.strerror or "operating-system error"}{location}'
    return f'unexpected {type(err).__name__}; details withheld so no settings or credential contents are printed'


def plan_command(args: argparse.Namespace) -> dict:
    home = resolve_home(args.home)
    document = plan_document(build_plan(home, args.source, args.edition))
    if args.out is not None:
        write_plan_file(args.out, document)
    return document


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan', help='read-only: print a PLAN_READY document (executed: false)')
    plan.add_argument('--source', type=Path, default=Path(__file__).resolve().parent.parent,
                      help='clean framework checkout (default: the checkout owning this script)')
    plan.add_argument('--home', type=Path, default=None, help='home-shaped target directory (default: your home)')
    plan.add_argument('--edition', choices=('claude', 'codex', 'both'), default=None,
                      help='update only these installed integrations (default: every installed one)')
    plan.add_argument('--out', type=Path, default=None,
                      help='also write the plan as a new 0600 file inside a private (0700) directory')
    apply = commands.add_parser('apply', help='apply a reviewed private plan after recomputing and matching it')
    apply.add_argument('--plan', type=Path, required=True, help='private plan file written by plan --out')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with scrubbed_git_environment():
            document = plan_command(args) if args.command == 'plan' else apply_update(args.plan)
    except UpdateError as err:
        document = result_document(err.status, executed=False, error=str(err))
    except Exception as err:  # noqa: BLE001 - reported as metadata only, never contents
        document = result_document('INCOMPLETE' if not isinstance(err, OSError) else 'FAIL',
                                   executed=False, error=safe_os_error(err))
    print(json.dumps(document, indent=2, sort_keys=True))
    return EXIT_CODES[document['status']]


if __name__ == '__main__':
    raise SystemExit(main())
