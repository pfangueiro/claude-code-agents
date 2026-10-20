#!/usr/bin/env python3
"""Create and inspect working-state checkpoints without disturbing the caller's state.

Usage:
    checkpoint.py save NAME [--repo DIR]
    checkpoint.py list        [--repo DIR]
    checkpoint.py diff NAME   [--repo DIR]

A checkpoint is a snapshot of the current working tree captured into a NEW ref under
``refs/checkpoint/`` using Git plumbing only. Unlike the stash/pop/branch-switch recipe
it replaces, it NEVER runs ``git stash``, ``stash pop``, ``checkout``, ``switch``,
``reset`` or ``clean``, so the caller's branch, real index bytes, working tree and any
pre-existing stash entries are left exactly as they were.

How a snapshot is built (``save`` and the current-state side of ``diff``):
    A temporary index in the system temp dir (GIT_INDEX_FILE, never the repo index) is
    seeded from HEAD, ``git add -A`` overlays the worktree onto it (so staged, unstaged,
    deleted and non-ignored untracked files are all captured, and a tracked-but-ignored
    file is still updated because it is already in the seeded index), ``write-tree``
    records the tree and ``commit-tree -p HEAD`` records a commit. ``save`` then creates
    ``refs/checkpoint/NAME`` with an atomic create-only ``update-ref`` transaction.
    Ignored, untracked files are excluded from the snapshot (documented, not silent).

Why some states are refused before any object or ref is written:
    - unsafe/colliding name, or an already-existing checkpoint ref (``save``);
    - an unborn HEAD or a merge/conflict in progress (an ambiguous state the single-tree
      snapshot cannot round-trip honestly);
    - skip-worktree/assume-unchanged index flags, submodules (gitlinks), an untracked
      embedded Git repository (which ``add -A`` would record as a gitlink, dropping its
      current bytes), and any path ``add -A`` would stage -- cached OR non-ignored
      untracked -- routed through a configured content-filter driver. These are the same
      classes evidence.py refuses, because ``add``/``hash-object`` would then run a
      repository-configured command or silently drop state;
    - an active ``reference-transaction`` or ``post-index-change`` hook. ``update-ref``
      invokes the former and the temp-index writes invoke the latter; an owner-configured
      hook could mutate owner state, and disabling or skipping hooks is not an option
      here, so the honest choice is to refuse. Presence is detected by Git's own rule
      (the hook file exists and is executable); the hook is never run as a probe.

No signing, ``--no-verify`` or other permission/hook-bypass flag is ever passed. Auto-gc
is turned off for the run (``gc.auto=0``) so object writes trigger no maintenance side
effect; that disables maintenance, not a hook. The plumbing only writes snapshot objects
and the one ref -- nothing is pushed.

Honest limits: the snapshot records the current worktree content, so when a file is
staged as A but present as B in the worktree, B is captured. Recovery is explicit (the
command prints the exact Git commands); this helper never restores for you.

Exit codes: 0 ok, 1 git/runtime error, 2 usage error, 3 refused before any mutation.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REF_PREFIX = 'refs/checkpoint/'
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
# Flags that keep every query hermetic: ignore replace refs, never take an optional lock
# (so a read never rewrites the real index), and switch off fsmonitor/untracked-cache and
# auto-gc so no background process or maintenance writes during the run. Mirrors the git
# safety set used by codex/framework.py and scripts/evidence.py.
GIT_SAFE = ['--no-replace-objects', '--no-optional-locks', '-c', 'core.fsmonitor=false',
            '-c', 'core.untrackedCache=false', '-c', 'gc.auto=0', '--literal-pathspecs']
# Inherited variables that would point Git at another repository, index or object store,
# or inject configuration. All are dropped; only config-file selectors (no more authority
# than HOME's global config) are kept, matching scripts/evidence.py.
GIT_CONFIG_FILE_ENV = frozenset({'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_NOSYSTEM'})
# Hooks the snapshot plumbing could trigger: update-ref -> reference-transaction;
# read-tree/add writing the temp index -> post-index-change.
RELEVANT_HOOKS = ('reference-transaction', 'post-index-change')

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2, 3


class Refusal(Exception):
    """A pre-mutation refusal carrying a fixed reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class GitError(Exception):
    """A git command failed after preflight passed."""


class Usage(Exception):
    """An argument/input problem reported as a fixed code, never echoing input."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_') or key in GIT_CONFIG_FILE_ENV}
    env['GIT_OPTIONAL_LOCKS'] = '0'
    if extra:
        env.update(extra)
    return env


def run_git(repo: Path, *args: str, env: dict[str, str] | None = None,
            stdin: bytes | None = None) -> bytes:
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(repo), *args],
                          env=env or git_env(), input=stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise GitError(f'{args[0]}: {proc.stderr.decode(errors="replace").strip()}')
    return proc.stdout


def resolve_repo(raw: str) -> Path:
    cwd = Path(raw).resolve()
    if not cwd.is_dir():
        raise Usage('repo-not-directory')
    if shutil.which('git') is None:
        raise Refusal('git-unavailable')
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                          env=git_env(), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise Refusal('not-a-git-checkout')
    return Path(proc.stdout.decode().strip()).resolve()


def validate_name(name: str) -> None:
    if not NAME_RE.match(name) or '..' in name or name.endswith(('.lock', '.')):
        raise Refusal('invalid-name')


def head_commit(repo: Path) -> str:
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(repo), 'rev-parse', '--verify', '--quiet', 'HEAD^{commit}'],
                          env=git_env(), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    head = proc.stdout.decode().strip()
    if proc.returncode != 0 or not head:
        raise Refusal('unborn-head')
    return head


def ref_exists(repo: Path, ref: str) -> bool:
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(repo), 'rev-parse', '--verify', '--quiet', ref],
                          env=git_env(), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return proc.returncode == 0


def configured_filter_drivers(repo: Path) -> set[bytes]:
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(repo), 'config', '--name-only',
                           '--get-regexp', r'^filter\..*\.(clean|smudge|process)$'],
                          env=git_env(), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode not in (0, 1):
        raise GitError('config: cannot read filter drivers')
    keys = proc.stdout.splitlines() if proc.returncode == 0 else []
    return {key.split(b'.', 1)[1].rsplit(b'.', 1)[0] for key in keys}


def tracked_paths(repo: Path) -> bytes:
    """NUL-terminated cached entries (includes tracked-but-ignored paths)."""
    return run_git(repo, 'ls-files', '-z')


def untracked_candidate_paths(repo: Path) -> bytes:
    """NUL-terminated non-ignored untracked entries that ``git add -A`` would consume.
    Git refuses to descend into an embedded repository, so one appears as a single entry
    with a trailing slash; an ordinary untracked directory is listed as its files. Ignored
    untracked paths are excluded here exactly as ``add -A`` and the snapshot exclude them."""
    return run_git(repo, 'ls-files', '--others', '--exclude-standard', '-z')


def content_filters_active(repo: Path) -> bool:
    """True when any path ``git add -A`` would stage carries a filter attribute naming a
    configured driver, so that staging it would run a repository-configured command. The
    scan covers the full add candidate set -- cached entries AND non-ignored untracked
    files -- not just cached paths, because ``add -A`` consumes both. ``check-attr`` honors
    the worktree ``.gitattributes`` (even an untracked one) and itself runs no filter."""
    drivers = configured_filter_drivers(repo)
    if not drivers:
        return False
    paths = tracked_paths(repo) + untracked_candidate_paths(repo)
    if not paths:
        return False
    fields = run_git(repo, 'check-attr', '--stdin', '-z', 'filter', stdin=paths).split(b'\0')
    return any(value in drivers for value in fields[2::3])


def embedded_repos_present(repo: Path) -> bool:
    """True when a non-ignored untracked directory is itself a Git repository. ``git add -A``
    records such a directory as a mode 160000 gitlink, silently dropping its current
    (committed, dirty and untracked) bytes, so the single-tree snapshot cannot capture it
    honestly. Detected by Git's own walk (trailing-slash entry), before any mutation."""
    return any(entry.endswith(b'/') for entry in untracked_candidate_paths(repo).split(b'\0') if entry)


def preflight_input(repo: Path) -> None:
    """Refuse states the single-tree snapshot cannot capture honestly, before any write."""
    if content_filters_active(repo):
        raise Refusal('content-filters-unsupported')
    flags = run_git(repo, 'ls-files', '-v', '-z')
    # ls-files -v tags: 'S' marks skip-worktree; a lowercase tag marks assume-unchanged.
    if any(entry[:1] == b'S' or entry[:1].islower() for entry in flags.split(b'\0') if entry):
        raise Refusal('index-flags-unsupported')
    staged = run_git(repo, 'ls-files', '-s', '-z')
    if any(record[:6] == b'160000' for record in staged.split(b'\0') if record):
        raise Refusal('submodules-unsupported')
    if embedded_repos_present(repo):
        raise Refusal('nested-repo-unsupported')
    if run_git(repo, 'ls-files', '-u', '-z').strip(b'\0'):
        raise Refusal('conflict-in-progress')


def active_hooks(repo: Path, names: tuple[str, ...]) -> list[str]:
    """Hook names in the effective hooks directory that Git would run (present and
    executable). Honors core.hooksPath via ``--git-path hooks``; the hook is never run."""
    raw = run_git(repo, 'rev-parse', '--git-path', 'hooks').decode().strip()
    hooks_dir = Path(raw)
    if not hooks_dir.is_absolute():
        hooks_dir = (repo / hooks_dir).resolve()
    found = []
    for name in names:
        path = hooks_dir / name
        if path.is_file() and os.access(path, os.X_OK):
            found.append(name)
    return found


def refuse_active_hooks(repo: Path, names: tuple[str, ...]) -> None:
    found = active_hooks(repo, names)
    if found:
        raise Refusal('active-hooks:' + ','.join(found))


def snapshot_tree(repo: Path, head: str) -> str:
    """Build a tree object for the current worktree via a throwaway temp index."""
    tmp = Path(tempfile.mkdtemp(prefix='sdlc-checkpoint-'))
    try:
        env = git_env({'GIT_INDEX_FILE': str(tmp / 'index')})
        run_git(repo, 'read-tree', head, env=env)
        run_git(repo, 'add', '-A', env=env)
        # Defense in depth: preflight already refuses embedded repos before any mutation;
        # this rejects any gitlink that still reached the temp index (temp index only, the
        # real index is never touched) rather than recording an unrecoverable snapshot.
        staged = run_git(repo, 'ls-files', '-s', '-z', env=env)
        if any(record[:6] == b'160000' for record in staged.split(b'\0') if record):
            raise Refusal('nested-repo-unsupported')
        return run_git(repo, 'write-tree', env=env).decode().strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def current_branch(repo: Path) -> str:
    proc = subprocess.run(['git', *GIT_SAFE, '-C', str(repo), 'symbolic-ref', '--quiet', '--short', 'HEAD'],
                          env=git_env(), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return proc.stdout.decode().strip() if proc.returncode == 0 else '(detached HEAD)'


def change_counts(repo: Path, head: str, tree: str) -> dict[str, int]:
    raw = run_git(repo, 'diff-tree', '-z', '--no-commit-id', '--name-status', '-r', head, tree)
    fields = [field for field in raw.split(b'\0') if field]
    counts = {'A': 0, 'M': 0, 'D': 0, 'other': 0}
    for status in fields[0::2]:
        key = status.decode()[:1]
        counts[key if key in counts else 'other'] += 1
    return counts


def save(repo: Path, name: str) -> int:
    validate_name(name)
    head = head_commit(repo)
    ref = REF_PREFIX + name
    if ref_exists(repo, ref):
        raise Refusal('checkpoint-exists')
    preflight_input(repo)
    refuse_active_hooks(repo, RELEVANT_HOOKS)

    tree = snapshot_tree(repo, head)
    branch = current_branch(repo)
    created = datetime.now(timezone.utc).isoformat(timespec='seconds')
    message = f'checkpoint: {name}\n\nbranch: {branch}\ncreated: {created}\n'.encode()
    identity = {'GIT_AUTHOR_NAME': 'SDLC Checkpoint', 'GIT_AUTHOR_EMAIL': 'checkpoint@localhost',
                'GIT_COMMITTER_NAME': 'SDLC Checkpoint', 'GIT_COMMITTER_EMAIL': 'checkpoint@localhost'}
    commit = run_git(repo, 'commit-tree', tree, '-p', head,
                     env=git_env(identity), stdin=message).decode().strip()
    # create verifies the ref does not exist and fails atomically if it was raced in.
    transaction = b'create ' + ref.encode() + b'\x00' + commit.encode() + b'\x00'
    run_git(repo, 'update-ref', '-z', '--stdin', stdin=transaction)

    counts = change_counts(repo, head, tree)
    print(f"Checkpoint '{name}' saved.")
    print(f'  ref:     {ref}')
    print(f'  commit:  {commit}')
    print(f'  parent:  {head}')
    print(f'  branch:  {branch}')
    print(f"  vs HEAD: {counts['A']} added, {counts['M']} modified, {counts['D']} deleted"
          + (f", {counts['other']} other" if counts['other'] else ''))
    print(f'Recover (new branch): git switch -c {name}-restore {ref}')
    print(f'Recover (files only): git restore --source={ref} -- <path>')
    print('Ignored files are excluded from the snapshot.')
    return EXIT_OK


def list_checkpoints(repo: Path) -> int:
    fmt = '%(refname:lstrip=2)%09%(objectname:short)%09%(creatordate:iso-strict)%09%(contents:subject)'
    raw = run_git(repo, 'for-each-ref', '--sort=-creatordate', f'--format={fmt}', REF_PREFIX)
    lines = [line for line in raw.decode().splitlines() if line]
    if not lines:
        print('No checkpoints (refs/checkpoint/*).')
        return EXIT_OK
    print('Checkpoints (refs/checkpoint/*):')
    for line in lines:
        name, short, created, *subject = line.split('\t')
        print(f'  {name}\t{short}\t{created}\t{subject[0] if subject else ""}')
    return EXIT_OK


def diff(repo: Path, name: str) -> int:
    validate_name(name)
    ref = REF_PREFIX + name
    if not ref_exists(repo, ref):
        raise Refusal('checkpoint-missing')
    head = head_commit(repo)
    preflight_input(repo)
    # diff builds a current snapshot in a temp index (post-index-change) but writes no ref.
    refuse_active_hooks(repo, ('post-index-change',))
    checkpoint_tree = run_git(repo, 'rev-parse', '--verify', f'{ref}^{{tree}}').decode().strip()
    current_tree = snapshot_tree(repo, head)
    stat = run_git(repo, 'diff-tree', '--stat', '-r', checkpoint_tree, current_tree).decode()
    patch = run_git(repo, 'diff-tree', '-p', '-r', checkpoint_tree, current_tree).decode()
    print(f'Diff: {ref} -> current working tree')
    if not patch.strip():
        print('  (identical)')
        return EXIT_OK
    if stat.strip():
        print(stat.rstrip())
    print(patch, end='')
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Create and inspect working-state checkpoints.')
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('save', 'diff'):
        node = sub.add_parser(action)
        node.add_argument('name')
        node.add_argument('--repo', default='.')
    node = sub.add_parser('list')
    node.add_argument('--repo', default='.')
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        repo = resolve_repo(args.repo)
        if args.action == 'save':
            return save(repo, args.name)
        if args.action == 'diff':
            return diff(repo, args.name)
        return list_checkpoints(repo)
    except Usage as exc:
        print(f'usage-error: {exc.code}', file=sys.stderr)
        return EXIT_USAGE
    except Refusal as exc:
        print(f'refused: {exc.code}', file=sys.stderr)
        return EXIT_REFUSED
    except GitError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return EXIT_ERROR


if __name__ == '__main__':
    raise SystemExit(main())
