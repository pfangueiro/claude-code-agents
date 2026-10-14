#!/usr/bin/env python3
"""Incrementally install the portable delivery resources into one Claude home.

Manages only the delivery, repo-context and verified-handoff skills, the delivery
rule and the provider-neutral commit-pr command. It never runs the broad Claude
installer and never touches settings, hooks, credentials, models, CLAUDE.md or
daemons. Ownership is recorded as per-file hashes in a manifest; foreign or
customized files, symlinked destinations and dirty sources are refused before any
write. Writes happen under a lock with rollback of caught errors. A process kill or
power loss during a multi-file write is not guaranteed to roll back. Python 3.11+.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SKILLS = ('delivery', 'repo-context', 'verified-handoff')
SINGLE_FILES = ('rules/delivery.md', 'commands/commit-pr.md')
STATE_DIR = '.sdlc-delivery'
MANIFEST = f'{STATE_DIR}/manifest.json'
LOCK = '.sdlc-delivery.lock'
SHA_PATTERN = re.compile(r'[0-9a-f]{40}')


class InstallError(Exception):
    """Refusal or failure that leaves the target unchanged."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(source: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(['git', '-C', str(source), *args], capture_output=True)
    if result.returncode != 0:
        raise InstallError(f'git {args[0]} failed in source: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout if binary else result.stdout.decode().strip()


def source_files(source: Path) -> dict[str, bytes]:
    """Map Claude-home-relative paths to the exact source bytes."""
    files: dict[str, bytes] = {}
    claude = source / '.claude'
    for name in SKILLS:
        skill = claude / 'skills' / name
        if skill.is_symlink() or not (skill / 'SKILL.md').is_file():
            raise InstallError(f'missing or symlinked source skill: {name}')
        for path in sorted(skill.rglob('*')):
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if path.is_symlink():
                raise InstallError(f'source resource symlink: {path.relative_to(source)}')
            if path.is_file():
                files[path.relative_to(claude).as_posix()] = path.read_bytes()
    for rel in SINGLE_FILES:
        path = claude / rel
        if path.is_symlink() or not path.is_file():
            raise InstallError(f'missing or symlinked source file: .claude/{rel}')
        files[rel] = path.read_bytes()
    return files


def provenance(source: Path) -> dict:
    sha = git(source, 'rev-parse', 'HEAD')
    paths = [f'.claude/skills/{name}' for name in SKILLS] + [f'.claude/{rel}' for rel in SINGLE_FILES]
    status = git(source, 'status', '--porcelain', '--untracked-files=all', '--', *paths)
    return {'sha': sha, 'dirty': bool(status)}


def baseline_blob(source: Path, baseline: str, rel: str) -> bytes | None:
    result = subprocess.run(['git', '-C', str(source), 'cat-file', 'blob', f'{baseline}:.claude/{rel}'],
                            capture_output=True)
    return result.stdout if result.returncode == 0 else None


def check_baseline(source: Path, baseline: str | None) -> None:
    if baseline is None:
        return
    if not SHA_PATTERN.fullmatch(baseline):
        raise InstallError('--baseline must be a full 40-character lowercase commit SHA')
    kind = subprocess.run(['git', '-C', str(source), 'cat-file', '-t', baseline], capture_output=True, text=True)
    if kind.returncode != 0 or kind.stdout.strip() != 'commit':
        raise InstallError('--baseline is not a commit in the source repository')


def reject_symlinks(home: Path, rel: str, *, directory: bool = False) -> Path:
    """Refuse traversal and any symlink between the filesystem root and the destination."""
    parts = Path(rel).parts
    if not parts or Path(rel).is_absolute() or any(part in ('.', '..') for part in parts):
        raise InstallError(f'unsafe managed path: {rel}')
    path = home / rel
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise InstallError(f'symlink destination: {candidate}')
        if candidate != path and candidate.exists() and not candidate.is_dir():
            raise InstallError(f'not a directory: {candidate}')
    if path.exists() and path.is_dir() != directory:
        raise InstallError(f'{"non-directory" if directory else "non-file"} collision: {rel}')
    return path


def allowed(rel: str) -> bool:
    return rel in SINGLE_FILES or any(rel.startswith(f'skills/{name}/') for name in SKILLS)


def allowed_dir(rel: str) -> bool:
    return rel in ('skills', 'rules', 'commands') or allowed(rel + '/')


def load_manifest(home: Path) -> dict:
    path = reject_symlinks(home, MANIFEST)
    if not path.exists():
        return {'version': 1, 'files': {}, 'adopted': {}, 'dirs': []}
    try:
        meta = json.loads(path.read_bytes())
    except (ValueError, UnicodeDecodeError) as err:
        raise InstallError('unreadable delivery manifest') from err
    if (not isinstance(meta, dict) or meta.get('version') != 1 or not isinstance(meta.get('files'), dict)
            or not isinstance(meta.get('adopted'), dict) or not isinstance(meta.get('dirs'), list)):
        raise InstallError('invalid delivery manifest')
    for rel, checksum in meta['files'].items():
        if not allowed(rel) or not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum):
            raise InstallError(f'invalid manifest entry: {rel}')
        reject_symlinks(home, rel)
    for rel, record in meta['adopted'].items():
        if rel not in meta['files'] or not isinstance(record, dict) or not isinstance(record.get('original'), str):
            raise InstallError(f'invalid adopted entry: {rel}')
    for rel in meta['dirs']:
        if not isinstance(rel, str) or not allowed_dir(rel):
            raise InstallError(f'invalid manifest directory: {rel}')
        reject_symlinks(home, rel, directory=True)
    return meta


def plan(home: Path, source: Path, *, uninstall: bool, baseline: str | None) -> tuple[dict, dict, bytes | None, dict]:
    """Return writes, expected current bytes, new manifest bytes and source provenance."""
    old = load_manifest(home)
    origin = provenance(source)
    desired = {} if uninstall else source_files(source)
    adopted = {} if uninstall else dict(old['adopted'])
    writes: dict[str, bytes | None] = {}
    expected: dict[str, bytes | None] = {}
    for rel in sorted(set(old['files']) | set(desired)):
        path = reject_symlinks(home, rel)
        current = path.read_bytes() if path.exists() else None
        expected[rel] = current
        if current is not None and rel in old['files'] and digest(current) != old['files'][rel]:
            raise InstallError(f'locally modified managed file: {rel}')
        if current is not None and rel not in old['files']:
            blob = baseline_blob(source, baseline, rel) if baseline else None
            if blob is None or blob != current:
                raise InstallError(f'foreign file not owned by the delivery manifest: {rel}'
                                   + ('' if baseline else ' (pass --baseline only if it was shipped by that commit)'))
            adopted[rel] = {'baseline': baseline, 'original': base64.b64encode(current).decode()}
        if rel in desired:
            if current != desired[rel]:
                writes[rel] = desired[rel]
            continue
        record = old['adopted'].get(rel)
        restore = base64.b64decode(record['original']) if record else None
        adopted.pop(rel, None)
        if current != restore:
            writes[rel] = restore
    dirs = sorted(set(old['dirs']) | {parent for rel, data in writes.items() if data is not None
                                      for parent in created_parents(home, rel)})
    if uninstall:
        manifest = None
    else:
        manifest = (json.dumps({'version': 1, 'source_sha': origin['sha'], 'source_dirty': origin['dirty'],
                                'files': {rel: digest(data) for rel, data in desired.items()},
                                'adopted': adopted, 'dirs': dirs}, indent=2, sort_keys=True) + '\n').encode()
    manifest_path = reject_symlinks(home, MANIFEST)
    expected[MANIFEST] = manifest_path.read_bytes() if manifest_path.exists() else None
    if manifest != expected[MANIFEST]:
        writes[MANIFEST] = manifest
    return writes, expected, old, origin


def created_parents(home: Path, rel: str) -> list[str]:
    parents = []
    for parent in Path(rel).parents:
        if parent != Path('.') and not (home / parent).exists() and allowed_dir(parent.as_posix()):
            parents.append(parent.as_posix())
    return parents


def transaction(home: Path, writes: dict[str, bytes | None], expected: dict[str, bytes | None],
                prune_dirs: list[str]) -> None:
    """Recheck under a lock, apply every write and roll back all of them on a caught error."""
    lock = home / LOCK
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as err:
        raise InstallError(f'another install holds {lock}; investigate before removing it') from err
    applied: list[str] = []
    made: list[Path] = []
    try:
        for rel, before in expected.items():
            path = reject_symlinks(home, rel)
            if (path.read_bytes() if path.exists() else None) != before:
                raise InstallError(f'concurrent modification: {rel}')
        # The manifest is written last so a failure never records unapplied ownership.
        for rel in sorted(writes, key=lambda item: item == MANIFEST):
            path = reject_symlinks(home, rel)
            applied.append(rel)
            if writes[rel] is None:
                path.unlink(missing_ok=True)
                continue
            for parent in reversed(path.parents):
                if (parent == home or home in parent.parents) and not parent.exists():
                    parent.mkdir()
                    made.append(parent)
            atomic_write(path, writes[rel])
    except BaseException:
        for rel in reversed(applied):
            path, before = home / rel, expected[rel]
            if before is None:
                path.unlink(missing_ok=True)
            elif not path.exists() or path.read_bytes() != before:
                atomic_write(path, before)
        for parent in reversed(made):
            remove_empty(parent)
        raise
    finally:
        os.close(fd)
        lock.unlink()
    for rel in sorted(prune_dirs, key=lambda item: item.count('/'), reverse=True):
        remove_empty(home / rel)


def remove_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass  # Non-empty or already gone: the owner's files stay in place.


def atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix='.sdlc-delivery-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def resolve_home(explicit: Path | None) -> Path:
    configured = explicit or (Path(os.environ['CLAUDE_CONFIG_DIR']) if os.environ.get('CLAUDE_CONFIG_DIR')
                              else Path.home() / '.claude')
    home = configured.expanduser().absolute()
    for candidate in (home, *home.parents):
        if candidate.is_symlink():
            raise InstallError(f'symlink in Claude home path: {candidate}')
    if not home.is_dir():
        raise InstallError(f'Claude home does not exist: {home}')
    return home


def run(home: Path, source: Path, *, dry_run: bool = False, check: bool = False,
        uninstall: bool = False, baseline: str | None = None) -> tuple[list[str], dict]:
    source = source.absolute()
    check_baseline(source, baseline)
    writes, expected, old, origin = plan(home, source, uninstall=uninstall, baseline=baseline)
    changes = sorted(writes)
    if check:
        if changes:
            raise InstallError('delivery drift: ' + ', '.join(changes))
        return changes, origin
    if dry_run or not changes:
        return changes, origin
    if origin['dirty'] and not uninstall:
        raise InstallError('source has uncommitted delivery changes; commit them before installing')
    transaction(home, writes, expected, old['dirs'] if uninstall else [])
    if uninstall:
        remove_empty(home / STATE_DIR)
    return changes, origin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--claude-home', type=Path, help='target Claude home (default: CLAUDE_CONFIG_DIR or ~/.claude)')
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent.parent,
                        help='source repository (default: the repository owning this script)')
    parser.add_argument('--baseline', help='full commit SHA whose shipped bytes may be adopted and later restored')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='report changes without writing')
    mode.add_argument('--check', action='store_true', help='exit nonzero if the target differs from the source')
    mode.add_argument('--uninstall', action='store_true', help='remove owned files and restore adopted originals')
    args = parser.parse_args()
    try:
        home = resolve_home(args.claude_home)
        changes, origin = run(home, args.source, dry_run=args.dry_run, check=args.check,
                              uninstall=args.uninstall, baseline=args.baseline)
    except (InstallError, OSError) as err:
        print(f'FAIL: {err}', file=sys.stderr)
        return 1
    verb = 'Would change' if args.dry_run else ('Checked' if args.check else 'Changed')
    print(f'source {origin["sha"]}{" (dirty)" if origin["dirty"] else ""}; target {home}')
    print(f'{verb} {len(changes)} paths')
    for rel in changes:
        print(rel)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
