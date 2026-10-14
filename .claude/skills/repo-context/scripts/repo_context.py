#!/usr/bin/env python3
"""Read-only repository onboarding discovery, printed as JSON.

Usage:
    repo_context.py --cwd DIR

Reports the owning Git root, HEAD and dirty state (or states explicitly that the
directory is an archive/unversioned tree), instruction files, and Node/Python/Go
manifests with their declared toolchain and test declarations. Mixed repositories
report every ecosystem found.

Guarantees:
    - Nothing is executed except read-only `git` queries, and no query that could run
      a repository-configured command: when a tracked path is routed through a
      configured content filter driver the dirty state is reported as unknown instead
      of running `git status`, and
      submodules are never recursed. Command candidates are data; they are never run.
    - Nothing is guessed: an undeclared package manager, default branch or CI gate
      is reported as unknown, not inferred from lockfiles or conventions.
    - No credential, home-directory or environment enumeration; Git configuration
      values and remote URLs are not read. Only the repository tree is inspected, and
      no symlink is followed at any path component.
    - Malformed declarations and bounded-scan pruning are reported as explicit
      unknowns with fixed reason codes; malformed content is never echoed.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

INSTRUCTION_NAMES = ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', 'CLAUDE.local.md',
                     'GEMINI.md', '.cursorrules', 'CONTRIBUTING.md')
INSTRUCTION_NESTED = ('.claude/CLAUDE.md', '.github/copilot-instructions.md')
RULE_DIRS = ('.claude/rules', '.cursor/rules')
SKIP_DIRS = {'.git', 'node_modules', 'vendor', '.venv', 'venv', '__pycache__', 'dist',
             'build', 'target', '.tox', '.nox', '.mypy_cache', '.pytest_cache', '.next'}
NODE_LOCKS = ('package-lock.json', 'npm-shrinkwrap.json', 'yarn.lock', 'pnpm-lock.yaml',
              'bun.lock', 'bun.lockb')
PY_LOCKS = ('uv.lock', 'poetry.lock', 'Pipfile.lock', 'pdm.lock')
CI_FILES = ('.gitlab-ci.yml', '.circleci/config.yml', 'azure-pipelines.yml',
            'Jenkinsfile', '.travis.yml', 'bitbucket-pipelines.yml')
PACKAGE_MANAGER_RE = re.compile(r'^(npm|pnpm|yarn|bun)@[0-9][0-9A-Za-z.+-]*$')
ENGINE_RANGE_RE = re.compile(r'^[0-9A-Za-z.*^~<>=|, +-]{1,100}$')
MAKE_TARGET_RE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)', re.MULTILINE)
GO_DIRECTIVE_RE = re.compile(r'^(module|go|toolchain)\s+(\S+)\s*$', re.MULTILINE)
SAFE_TOKEN_RE = re.compile(r'^[A-Za-z0-9@._/+:-]{1,200}$')
MAX_DEPTH = 4
MAX_FILE_BYTES = 1024 * 1024
MAX_DIRS = 5000
GIT_SAFE = ['-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false']


# ---------------------------------------------------------------- helpers

def git_proc(cwd: Path, *args: str) -> subprocess.CompletedProcess | None:
    env = {'PATH': os.environ.get('PATH', ''), 'GIT_OPTIONAL_LOCKS': '0',
           'HOME': os.environ.get('HOME', ''), 'LC_ALL': 'C'}
    try:
        return subprocess.run(['git', *GIT_SAFE, '-C', str(cwd), *args], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, check=False)
    except OSError:
        return None


def git(cwd: Path, *args: str) -> str | None:
    proc = git_proc(cwd, *args)
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.decode('utf-8', 'replace')


def safe_token(value) -> str | None:
    """Return a declared scalar only when it is a plain token; never echo arbitrary text."""
    return value if isinstance(value, str) and SAFE_TOKEN_RE.match(value) else None


def path_kind(root: Path, rel: str, unknowns: list) -> str | None:
    """'file' or 'dir' when every component under root is a real entry; None otherwise.

    A symlink at ANY component is not followed and is recorded as a fixed unknown, so a
    symlinked ancestor cannot redirect discovery outside the repository.
    """
    current = root
    for part in rel.split('/'):
        current = current / part
        try:
            info = current.lstat()
        except OSError:
            return None
        if stat.S_ISLNK(info.st_mode):
            unknowns.append({'path': current.relative_to(root).as_posix(),
                             'reason': 'symlink-not-followed'})
            return None
    if stat.S_ISREG(info.st_mode):
        return 'file'
    return 'dir' if stat.S_ISDIR(info.st_mode) else None


def rel_join(rel_dir: str, name: str) -> str:
    return name if rel_dir == '.' else f'{rel_dir}/{name}'


def read_regular(root: Path, rel: str, unknowns: list) -> bytes | None:
    if path_kind(root, rel, unknowns) != 'file':
        return None
    path = root / rel
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            unknowns.append({'path': rel, 'reason': 'too-large'})
            return None
        return path.read_bytes()
    except OSError:
        unknowns.append({'path': rel, 'reason': 'unreadable'})
        return None


def file_fact(root: Path, rel: str) -> dict:
    path = root / rel
    size = path.lstat().st_size
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if size <= MAX_FILE_BYTES else None
    return {'path': rel, 'bytes': size, 'sha256': digest}


# ---------------------------------------------------------------- source identity

def filters_active(root: Path) -> bool | None:
    """Whether a tracked path's filter attribute names a configured driver command.

    Driver names come from configuration key names; values are never read. Attribute
    lookup (`check-attr`) runs nothing. None means the question could not be answered.
    """
    proc = git_proc(root, 'config', '--name-only', '--get-regexp',
                    r'^filter\..*\.(clean|smudge|process)$')
    if proc is None or proc.returncode not in (0, 1):
        return None
    if proc.returncode == 1:
        return False
    drivers = {key.split(b'.', 1)[1].rsplit(b'.', 1)[0] for key in proc.stdout.splitlines()}
    listed = git_proc(root, 'ls-files', '-z')
    if listed is None or listed.returncode != 0:
        return None
    if not listed.stdout:
        return False
    env = {'PATH': os.environ.get('PATH', ''), 'GIT_OPTIONAL_LOCKS': '0',
           'HOME': os.environ.get('HOME', ''), 'LC_ALL': 'C'}
    try:
        attrs = subprocess.run(['git', *GIT_SAFE, '-C', str(root), 'check-attr', '--stdin',
                                '-z', 'filter'], env=env, input=listed.stdout,
                               capture_output=True, check=False)
    except OSError:
        return None
    if attrs.returncode != 0:
        return None
    return any(value in drivers for value in attrs.stdout.split(b'\0')[2::3])


def status_counts(root: Path) -> tuple[int, int] | None:
    # Submodules are not recursed: their own configuration could run callbacks.
    raw = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=normal',
              '--ignore-submodules=all')
    if raw is None:
        return None
    tracked = untracked = 0
    fields = iter(raw.split('\0'))
    for field in fields:
        if len(field) < 4:
            continue
        if field.startswith('??'):
            untracked += 1
            continue
        tracked += 1
        if field[0] in 'RC' or field[1] in 'RC':
            next(fields, None)  # a rename/copy source path is a separate field
    return tracked, untracked


def dirty_state(root: Path, unknowns: list) -> dict:
    unknown = {'dirty': None, 'trackedChanges': None, 'untrackedFiles': None}
    configured = filters_active(root)
    if configured is not False:
        # Inspecting content would run the configured filter commands: refuse instead.
        unknowns.append({'path': '.', 'reason': 'dirty-state-uninspected-content-filters'
                         if configured else 'dirty-state-unavailable'})
        return unknown
    counts = status_counts(root)
    if counts is None:
        unknowns.append({'path': '.', 'reason': 'dirty-state-unavailable'})
        return unknown
    index = git(root, 'ls-files', '-s', '-z') or ''
    if any(entry.startswith('160000 ') for entry in index.split('\0')):
        unknowns.append({'path': '.', 'reason': 'submodule-state-not-inspected'})
    tracked, untracked = counts
    return {'dirty': bool(tracked or untracked), 'trackedChanges': tracked,
            'untrackedFiles': untracked}


def source_identity(cwd: Path, unknowns: list) -> tuple[Path, dict]:
    top = git(cwd, 'rev-parse', '--show-toplevel')
    if top is None:
        return cwd, {'kind': 'archive-or-unversioned', 'gitRoot': None, 'head': None,
                     'dirty': None, 'note': 'no owning Git checkout; identity must be '
                     'described explicitly (for example an archive name and digest)'}
    root = Path(top.strip()).resolve()
    head = git(root, 'rev-parse', '--verify', '-q', 'HEAD')
    branch = git(root, 'symbolic-ref', '-q', '--short', 'HEAD')
    origin_head = git(root, 'symbolic-ref', '-q', '--short', 'refs/remotes/origin/HEAD')
    return root, {
        'kind': 'git',
        'gitRoot': str(root),
        'head': head.strip() if head else None,
        'branch': branch.strip() if branch else None,
        **dirty_state(root, unknowns),
        'defaultBranch': None,
        'localOriginHead': origin_head.strip() if origin_head else None,
        'note': 'defaultBranch is not determined locally; localOriginHead is a possibly '
                'stale local ref, not the hosting default',
    }


# ---------------------------------------------------------------- tree walk

def walk(root: Path) -> tuple[list[tuple[Path, list[str]]], dict]:
    """Bounded walk. Returns (directory, file names) pairs and the pruning facts."""
    visited: list[tuple[Path, list[str]]] = []
    scan = {'maxDepth': MAX_DEPTH, 'maxDirectories': MAX_DIRS, 'directoriesVisited': 0,
            'depthPruned': 0, 'countTruncated': False, 'symlinkedDirectoriesNotFollowed': 0,
            'skippedDirectoryNames': sorted(SKIP_DIRS)}
    for current, dirs, files in os.walk(root, followlinks=False):
        here = Path(current)
        depth = len(here.relative_to(root).parts)
        real = []
        for name in sorted(dirs):
            if name in SKIP_DIRS:
                continue
            if (here / name).is_symlink():
                scan['symlinkedDirectoriesNotFollowed'] += 1
            else:
                real.append(name)
        if depth >= MAX_DEPTH:
            scan['depthPruned'] += len(real)
            real = []
        dirs[:] = real
        visited.append((here, sorted(files)))
        if len(visited) >= MAX_DIRS:
            # Conservative: the budget is exhausted, so unvisited directories may remain.
            scan['countTruncated'] = True
            break
    scan['directoriesVisited'] = len(visited)
    return visited, scan


def instruction_files(root: Path, cwd: Path, dirs: list[Path], unknowns: list) -> list[dict]:
    found = []
    parts = cwd.relative_to(root).parts
    chain = {root.joinpath(*parts[:i]) for i in range(len(parts) + 1)}
    for directory in dirs:
        scope = 'ancestor-or-cwd' if directory in chain else 'nested'
        rel_dir = directory.relative_to(root).as_posix() or '.'
        for name in INSTRUCTION_NAMES + INSTRUCTION_NESTED:
            rel = rel_join(rel_dir, name)
            if path_kind(root, rel, unknowns) == 'file':
                found.append({**file_fact(root, rel), 'scope': scope})
    for rule_dir in RULE_DIRS:
        if path_kind(root, rule_dir, unknowns) != 'dir':
            continue
        for path in sorted((root / rule_dir).iterdir()):
            rel = f'{rule_dir}/{path.name}'
            if '.md' in path.suffixes and path_kind(root, rel, unknowns) == 'file':
                found.append({**file_fact(root, rel), 'scope': 'rules'})
    return found


# ---------------------------------------------------------------- ecosystems

def present(root: Path, rel_dir: str, names: tuple, unknowns: list) -> list[str]:
    return [n for n in names if path_kind(root, rel_join(rel_dir, n), unknowns) == 'file']


def node_engines(engines, rel: str, unknowns: list) -> dict:
    declared = {}
    for name, value in engines.items():
        if not safe_token(name) or not isinstance(value, str):
            unknowns.append({'path': rel, 'reason': 'invalid-engine-entry'})
        elif ENGINE_RANGE_RE.match(value):
            declared[name] = value
        else:
            unknowns.append({'path': rel, 'reason': 'unsupported-engine-range'})
    return declared


def node_manifest(root: Path, rel_dir: str, files: list, unknowns: list) -> dict | None:
    rel = rel_join(rel_dir, 'package.json')
    if 'package.json' not in files:
        return None
    entry = {'manifest': rel, 'lockfiles': present(root, rel_dir, NODE_LOCKS, unknowns),
             'packageManager': None, 'toolchain': {}, 'scripts': [], 'tests': [], 'commands': []}
    for name in present(root, rel_dir, ('.nvmrc', '.node-version'), unknowns):
        entry['toolchain'][name] = 'declared-file'
    raw = read_regular(root, rel, unknowns)
    if raw is None:
        return entry
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        unknowns.append({'path': rel, 'reason': 'invalid-json'})
        return entry
    declared = data.get('packageManager')
    if declared is None:
        unknowns.append({'path': rel, 'reason': 'package-manager-not-declared'})
    elif isinstance(declared, str) and PACKAGE_MANAGER_RE.match(declared):
        entry['packageManager'] = declared
    else:
        unknowns.append({'path': rel, 'reason': 'invalid-packageManager'})
    engines = data.get('engines')
    if isinstance(engines, dict):
        entry['toolchain']['engines'] = node_engines(engines, rel, unknowns)
    elif engines is not None:
        unknowns.append({'path': rel, 'reason': 'invalid-engines'})
    scripts = data.get('scripts', {})
    if not isinstance(scripts, dict):
        unknowns.append({'path': rel, 'reason': 'invalid-scripts'})
        scripts = {}
    runner = entry['packageManager'].split('@')[0] if entry['packageManager'] else None
    for name, body in sorted(scripts.items()):
        if not isinstance(body, str) or not safe_token(name):
            unknowns.append({'path': rel, 'reason': 'invalid-script-entry'})
            continue
        entry['scripts'].append({'name': name, 'body': body})
        if name == 'test' or name.startswith('test:'):
            entry['tests'].append(f'scripts.{name}')
            entry['commands'].append({
                'cwd': rel_dir,
                'argv': [runner, 'run', name] if runner else None,
                'basis': f'package.json scripts.{name}',
                'blockedBy': None if runner else 'package-manager-not-declared',
                'executed': False})
    return entry


def load_toml(root: Path, rel: str, unknowns: list) -> dict | None:
    raw = read_regular(root, rel, unknowns)
    if raw is None:
        return None
    try:
        return tomllib.loads(raw.decode('utf-8'))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        unknowns.append({'path': rel, 'reason': 'invalid-toml'})
        return None


def load_ini(root: Path, rel: str, unknowns: list) -> configparser.ConfigParser | None:
    raw = read_regular(root, rel, unknowns)
    if raw is None:
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw.decode('utf-8'))
    except (configparser.Error, UnicodeDecodeError):
        unknowns.append({'path': rel, 'reason': 'invalid-ini'})
        return None
    return parser


def pyproject_facts(root: Path, rel_dir: str, entry: dict, unknowns: list) -> None:
    data = load_toml(root, rel_join(rel_dir, 'pyproject.toml'), unknowns)
    if data is None:
        return
    build = data.get('build-system', {})
    entry['buildBackend'] = safe_token(build.get('build-backend')) if isinstance(build, dict) else None
    project = data.get('project', {}) if isinstance(data.get('project'), dict) else {}
    requires = project.get('requires-python')
    if requires is not None:
        entry['toolchain']['requires-python'] = requires if isinstance(requires, str) \
            and len(requires) <= 100 else None
    tool = data.get('tool', {}) if isinstance(data.get('tool'), dict) else {}
    entry['toolSections'] = sorted(k for k in tool if safe_token(k))
    pytest_cfg = tool.get('pytest')
    if isinstance(pytest_cfg, dict) and 'ini_options' in pytest_cfg:
        entry['tests'].append('pyproject.toml [tool.pytest.ini_options]')


def python_manifest(root: Path, rel_dir: str, files: list, unknowns: list) -> dict | None:
    names = ('pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt', 'Pipfile',
             'tox.ini', 'pytest.ini', 'noxfile.py')
    found = [n for n in names if n in files]
    if not found:
        return None
    entry = {'manifests': [rel_join(rel_dir, n) for n in found],
             'lockfiles': present(root, rel_dir, PY_LOCKS, unknowns),
             'buildBackend': None, 'toolchain': {}, 'tests': [], 'commands': []}
    if present(root, rel_dir, ('.python-version',), unknowns):
        entry['toolchain']['.python-version'] = 'declared-file'
    if 'pyproject.toml' in found:
        pyproject_facts(root, rel_dir, entry, unknowns)
    if 'pytest.ini' in found:
        entry['tests'].append('pytest.ini')
    if 'setup.cfg' in found:
        cfg = load_ini(root, rel_join(rel_dir, 'setup.cfg'), unknowns)
        if cfg is not None and cfg.has_section('tool:pytest'):
            entry['tests'].append('setup.cfg [tool:pytest]')
    if 'tox.ini' in found:
        cfg = load_ini(root, rel_join(rel_dir, 'tox.ini'), unknowns)
        if cfg is not None:
            entry['tests'].append('tox.ini')
            if cfg.has_section('pytest'):
                entry['tests'].append('tox.ini [pytest]')
            entry['commands'].append(command(rel_dir, ['tox'], 'tox.ini declared'))
    if 'noxfile.py' in found:
        entry['tests'].append('noxfile.py')
        entry['commands'].append(command(rel_dir, ['nox'], 'noxfile.py declared'))
    if any(t.startswith(('pyproject', 'pytest.ini', 'setup.cfg', 'tox.ini [pytest]'))
           for t in entry['tests']):
        entry['commands'].append(command(rel_dir, ['python3', '-m', 'pytest'],
                                         'pytest configuration declared'))
    return entry


def go_manifest(root: Path, rel_dir: str, files: list, unknowns: list,
                test_counts: dict) -> dict | None:
    if 'go.mod' not in files:
        return None
    rel = rel_join(rel_dir, 'go.mod')
    entry = {'manifest': rel, 'module': None, 'toolchain': {}, 'tests': [], 'commands': []}
    raw = read_regular(root, rel, unknowns)
    if raw is None:
        return entry
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        unknowns.append({'path': rel, 'reason': 'invalid-go-mod'})
        return entry
    directives = dict(GO_DIRECTIVE_RE.findall(text))
    module = safe_token(directives.get('module'))
    if module is None:
        unknowns.append({'path': rel, 'reason': 'invalid-go-mod'})
        return entry
    entry['module'] = module
    for key in ('go', 'toolchain'):
        if safe_token(directives.get(key)):
            entry['toolchain'][key] = directives[key]
    tests = test_counts.get(rel_dir, 0)
    if tests:
        entry['tests'].append(f'{tests} _test.go file(s) within the bounded scan')
        entry['commands'].append(command(rel_dir, ['go', 'test', './...'],
                                         'go.mod with _test.go files'))
    return entry


def go_test_counts(root: Path, visited: list) -> dict[str, int]:
    """Attribute _test.go files from the bounded walk to their nearest enclosing module."""
    modules = {d for d, files in visited if 'go.mod' in files}
    counts: dict[str, int] = {}
    for directory, files in visited:
        tests = sum(1 for f in files if f.endswith('_test.go'))
        if not tests:
            continue
        owner = next((p for p in (directory, *directory.parents) if p in modules), None)
        if owner is not None:
            key = owner.relative_to(root).as_posix() or '.'
            counts[key] = counts.get(key, 0) + tests
    return counts


def make_targets(root: Path, rel_dir: str, files: list, unknowns: list) -> dict | None:
    if 'Makefile' not in files:
        return None
    rel = rel_join(rel_dir, 'Makefile')
    raw = read_regular(root, rel, unknowns)
    if raw is None:
        return {'manifest': rel, 'targets': [], 'commands': []}
    targets = sorted(set(MAKE_TARGET_RE.findall(raw.decode('utf-8', 'replace'))))
    return {'manifest': rel, 'targets': targets,
            'commands': [command(rel_dir, ['make', t], f'Makefile target {t}')
                         for t in targets if t.startswith('test')]}


def command(cwd: str, argv: list[str], basis: str) -> dict:
    return {'cwd': cwd, 'argv': argv, 'basis': basis, 'blockedBy': None, 'executed': False}


def ci_files(root: Path, unknowns: list) -> list[str]:
    found = [n for n in CI_FILES if path_kind(root, n, unknowns) == 'file']
    if path_kind(root, '.github/workflows', unknowns) == 'dir':
        for path in sorted((root / '.github' / 'workflows').iterdir()):
            rel = f'.github/workflows/{path.name}'
            if path.suffix in ('.yml', '.yaml') and path_kind(root, rel, unknowns) == 'file':
                found.append(rel)
    return found


# ---------------------------------------------------------------- report

def scan_unknowns(scan: dict) -> list[dict]:
    reasons = []
    if scan['depthPruned']:
        reasons.append({'path': '.', 'reason': 'directory-scan-depth-limit'})
    if scan['countTruncated']:
        reasons.append({'path': '.', 'reason': 'directory-scan-count-limit'})
    return reasons


def discover(cwd: Path) -> dict:
    unknowns: list[dict] = []
    root, identity = source_identity(cwd, unknowns)
    visited, scan = walk(root)
    unknowns.extend(scan_unknowns(scan))
    test_counts = go_test_counts(root, visited)
    ecosystems = {'node': [], 'python': [], 'go': [], 'make': []}
    for directory, files in visited:
        rel_dir = directory.relative_to(root).as_posix() or '.'
        probes = (('node', node_manifest(root, rel_dir, files, unknowns)),
                  ('python', python_manifest(root, rel_dir, files, unknowns)),
                  ('go', go_manifest(root, rel_dir, files, unknowns, test_counts)),
                  ('make', make_targets(root, rel_dir, files, unknowns)))
        for key, found in probes:
            if found is not None:
                ecosystems[key].append(found)
    languages = sorted(k for k in ('node', 'python', 'go') if ecosystems[k])
    candidates = [c for group in ecosystems.values() for e in group for c in e.get('commands', [])]
    instructions = instruction_files(root, cwd, [d for d, _ in visited], unknowns)
    ci = ci_files(root, unknowns)
    return {
        'schema': 'repo-context/v1',
        'cwd': str(cwd),
        'scanRoot': str(root),
        'source': identity,
        'scan': scan,
        'instructions': instructions,
        'languages': languages,
        'mixed': len(languages) > 1,
        'ecosystems': ecosystems,
        'commandCandidates': candidates,
        'ci': {'files': ci, 'gates': None,
               'note': 'CI files are listed, not interpreted; required gates are unknown'},
        'unknowns': dedupe(unknowns),
        'executionStillNeeded': still_needed(identity, ecosystems, candidates, ci, unknowns),
    }


def dedupe(unknowns: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for item in unknowns:
        key = (item['path'], item['reason'])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def still_needed(identity: dict, ecosystems: dict, candidates: list, ci: list,
                 unknowns: list) -> list[str]:
    needed = ['reconcile these facts with the instruction files; instructions win on conflicts']
    if identity['kind'] != 'git':
        needed.append('record an explicit source description for this unversioned tree')
    elif identity['dirty'] is None:
        needed.append('dirty state was not inspected; establish it by a means that runs no '
                      'repository-configured command')
    elif identity['dirty']:
        needed.append('decide how to handle uncommitted changes before recording evidence')
    if any(c['blockedBy'] for c in candidates):
        needed.append('confirm the package manager from project instructions; it is not declared')
    if candidates:
        needed.append('run selected command candidates and record receipts; none were executed')
    else:
        needed.append('no test declaration found; ask for or locate the verification command')
    if ecosystems['node'] or ecosystems['python'] or ecosystems['go']:
        needed.append('confirm toolchain versions and dependency installation in the target environment')
    needed.append('determine required CI gates from the hosting configuration'
                  if ci else 'no CI configuration found; required gates are unknown')
    if unknowns:
        needed.append('resolve the listed unknowns before relying on affected declarations')
    return needed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only repository context discovery.')
    parser.add_argument('--cwd', required=True)
    args = parser.parse_args(argv)
    cwd = Path(args.cwd).resolve()
    if not cwd.is_dir():
        print(json.dumps({'error': 'cwd-not-directory'}), file=sys.stderr)
        return 2
    print(json.dumps(discover(cwd), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
