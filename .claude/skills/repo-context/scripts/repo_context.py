#!/usr/bin/env python3
"""Read-only repository onboarding discovery, printed as JSON.

Usage:
    repo_context.py --cwd DIR

Reports the owning Git root, HEAD and dirty state (or states explicitly that the
directory is an archive/unversioned tree), instruction files, and Node/Python/Go
manifests with their declared toolchain and test declarations. Mixed repositories
report every ecosystem found.

Guarantees:
    - Nothing is executed except read-only `git` queries. Command candidates are
      data derived from declarations; they are never run.
    - Nothing is guessed: an undeclared package manager, default branch or CI gate
      is reported as unknown, not inferred from lockfiles or conventions.
    - No credential, home-directory or environment enumeration; remote URLs are not
      read. Only the repository tree is inspected and symlinks are not followed.
    - Malformed declarations are reported as explicit unknowns with a fixed reason
      code; their content is never echoed.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
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
MAKE_TARGET_RE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)', re.MULTILINE)
GO_DIRECTIVE_RE = re.compile(r'^(module|go|toolchain)\s+(\S+)\s*$', re.MULTILINE)
SAFE_TOKEN_RE = re.compile(r'^[A-Za-z0-9@._/+:-]{1,200}$')
MAX_DEPTH = 4
MAX_FILE_BYTES = 1024 * 1024
MAX_DIRS = 5000
GIT_SAFE = ['-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false']


# ---------------------------------------------------------------- helpers

def git(cwd: Path, *args: str) -> str | None:
    env = {'PATH': os.environ.get('PATH', ''), 'GIT_OPTIONAL_LOCKS': '0',
           'HOME': os.environ.get('HOME', ''), 'LC_ALL': 'C'}
    try:
        proc = subprocess.run(['git', *GIT_SAFE, '-C', str(cwd), *args], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, check=False)
    except OSError:
        return None
    return proc.stdout.decode('utf-8', 'replace') if proc.returncode == 0 else None


def safe_token(value) -> str | None:
    """Return a declared scalar only when it is a plain token; never echo arbitrary text."""
    return value if isinstance(value, str) and SAFE_TOKEN_RE.match(value) else None


def read_regular(path: Path, unknowns: list, rel: str) -> bytes | None:
    if path.is_symlink():
        unknowns.append({'path': rel, 'reason': 'symlink-not-followed'})
        return None
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            unknowns.append({'path': rel, 'reason': 'too-large'})
            return None
        return path.read_bytes()
    except OSError:
        unknowns.append({'path': rel, 'reason': 'unreadable'})
        return None


def file_fact(path: Path, root: Path) -> dict:
    data = path.read_bytes() if path.stat().st_size <= MAX_FILE_BYTES else b''
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(data).hexdigest() if data else None}


# ---------------------------------------------------------------- source identity

def source_identity(cwd: Path) -> tuple[Path, dict]:
    top = git(cwd, 'rev-parse', '--show-toplevel')
    if top is None:
        return cwd, {'kind': 'archive-or-unversioned', 'gitRoot': None, 'head': None,
                     'dirty': None, 'note': 'no owning Git checkout; identity must be '
                     'described explicitly (for example an archive name and digest)'}
    root = Path(top.strip()).resolve()
    head = git(root, 'rev-parse', '--verify', '-q', 'HEAD')
    status = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=normal')
    branch = git(root, 'symbolic-ref', '-q', '--short', 'HEAD')
    origin_head = git(root, 'symbolic-ref', '-q', '--short', 'refs/remotes/origin/HEAD')
    records = [r for r in (status or '').split('\0') if len(r) > 3 and r[2] == ' ']
    return root, {
        'kind': 'git',
        'gitRoot': str(root),
        'head': head.strip() if head else None,
        'branch': branch.strip() if branch else None,
        'dirty': None if status is None else bool(records),
        'trackedChanges': None if status is None else sum(not r.startswith('??') for r in records),
        'untrackedFiles': None if status is None else sum(r.startswith('??') for r in records),
        'defaultBranch': None,
        'localOriginHead': origin_head.strip() if origin_head else None,
        'note': 'defaultBranch is not determined locally; localOriginHead is a possibly '
                'stale local ref, not the hosting default',
    }


# ---------------------------------------------------------------- tree walk

def walk(root: Path) -> tuple[list[Path], bool]:
    dirs_out: list[Path] = []
    truncated = False
    for current, dirs, _files in os.walk(root, followlinks=False):
        here = Path(current)
        depth = len(here.relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and depth < MAX_DEPTH)
        dirs_out.append(here)
        if len(dirs_out) >= MAX_DIRS:
            truncated = True
            break
    return dirs_out, truncated


def instruction_files(root: Path, cwd: Path, dirs: list[Path]) -> list[dict]:
    found = []
    chain = [root] + [root.joinpath(*cwd.relative_to(root).parts[:i + 1])
                      for i in range(len(cwd.relative_to(root).parts))]
    for directory in dirs:
        scope = 'ancestor-or-cwd' if directory in chain else 'nested'
        for name in INSTRUCTION_NAMES + INSTRUCTION_NESTED:
            path = directory / name
            if path.is_file() and not path.is_symlink():
                found.append({**file_fact(path, root), 'scope': scope})
    for rule_dir in RULE_DIRS:
        base = root / rule_dir
        if base.is_dir() and not base.is_symlink():
            for path in sorted(base.glob('*.md*')):
                if path.is_file() and not path.is_symlink():
                    found.append({**file_fact(path, root), 'scope': 'rules'})
    return found


# ---------------------------------------------------------------- ecosystems

def node_manifest(directory: Path, root: Path, unknowns: list) -> dict | None:
    path = directory / 'package.json'
    if not path.exists():
        return None
    rel = path.relative_to(root).as_posix()
    entry = {'manifest': rel, 'lockfiles': [n for n in NODE_LOCKS if (directory / n).is_file()],
             'packageManager': None, 'toolchain': {}, 'scripts': [], 'tests': [], 'commands': []}
    for name in ('.nvmrc', '.node-version'):
        if (directory / name).is_file():
            entry['toolchain'][name] = 'declared-file'
    raw = read_regular(path, unknowns, rel)
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
    if declared is not None:
        if isinstance(declared, str) and PACKAGE_MANAGER_RE.match(declared):
            entry['packageManager'] = declared
        else:
            unknowns.append({'path': rel, 'reason': 'invalid-packageManager'})
    else:
        unknowns.append({'path': rel, 'reason': 'package-manager-not-declared'})
    engines = data.get('engines')
    if isinstance(engines, dict):
        entry['toolchain']['engines'] = {k: safe_token(v) for k, v in engines.items()
                                         if safe_token(k)}
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
                'cwd': directory.relative_to(root).as_posix() or '.',
                'argv': [runner, 'run', name] if runner else None,
                'basis': f'package.json scripts.{name}',
                'blockedBy': None if runner else 'package-manager-not-declared',
                'executed': False})
    return entry


def load_toml(path: Path, root: Path, unknowns: list) -> dict | None:
    rel = path.relative_to(root).as_posix()
    raw = read_regular(path, unknowns, rel)
    if raw is None:
        return None
    try:
        return tomllib.loads(raw.decode('utf-8'))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        unknowns.append({'path': rel, 'reason': 'invalid-toml'})
        return None


def load_ini(path: Path, root: Path, unknowns: list) -> configparser.ConfigParser | None:
    rel = path.relative_to(root).as_posix()
    raw = read_regular(path, unknowns, rel)
    if raw is None:
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw.decode('utf-8'))
    except (configparser.Error, UnicodeDecodeError):
        unknowns.append({'path': rel, 'reason': 'invalid-ini'})
        return None
    return parser


def python_manifest(directory: Path, root: Path, unknowns: list) -> dict | None:
    names = ('pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt', 'Pipfile',
             'tox.ini', 'pytest.ini', 'noxfile.py')
    present = [n for n in names if (directory / n).exists()]
    if not present:
        return None
    rel_dir = directory.relative_to(root).as_posix() or '.'
    entry = {'manifests': [f'{rel_dir}/{n}' if rel_dir != '.' else n for n in present],
             'lockfiles': [n for n in PY_LOCKS if (directory / n).is_file()],
             'buildBackend': None, 'toolchain': {}, 'tests': [], 'commands': []}
    if (directory / '.python-version').is_file():
        entry['toolchain']['.python-version'] = 'declared-file'
    if 'pyproject.toml' in present:
        data = load_toml(directory / 'pyproject.toml', root, unknowns)
        if data is not None:
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
    if 'pytest.ini' in present:
        entry['tests'].append('pytest.ini')
    if 'setup.cfg' in present:
        cfg = load_ini(directory / 'setup.cfg', root, unknowns)
        if cfg is not None and cfg.has_section('tool:pytest'):
            entry['tests'].append('setup.cfg [tool:pytest]')
    if 'tox.ini' in present:
        cfg = load_ini(directory / 'tox.ini', root, unknowns)
        if cfg is not None:
            entry['tests'].append('tox.ini')
            if cfg.has_section('pytest'):
                entry['tests'].append('tox.ini [pytest]')
            entry['commands'].append(command(rel_dir, ['tox'], 'tox.ini declared'))
    if 'noxfile.py' in present:
        entry['tests'].append('noxfile.py')
        entry['commands'].append(command(rel_dir, ['nox'], 'noxfile.py declared'))
    if any(t.startswith(('pyproject', 'pytest.ini', 'setup.cfg', 'tox.ini [pytest]'))
           for t in entry['tests']):
        entry['commands'].append(command(rel_dir, ['python3', '-m', 'pytest'],
                                         'pytest configuration declared'))
    return entry


def go_manifest(directory: Path, root: Path, unknowns: list) -> dict | None:
    path = directory / 'go.mod'
    if not path.exists():
        return None
    rel = path.relative_to(root).as_posix()
    rel_dir = directory.relative_to(root).as_posix() or '.'
    entry = {'manifest': rel, 'module': None, 'toolchain': {}, 'tests': [], 'commands': []}
    raw = read_regular(path, unknowns, rel)
    if raw is None:
        return entry
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        unknowns.append({'path': rel, 'reason': 'invalid-go-mod'})
        return entry
    directives = {k: v for k, v in GO_DIRECTIVE_RE.findall(text)}
    module = safe_token(directives.get('module'))
    if module is None:
        unknowns.append({'path': rel, 'reason': 'invalid-go-mod'})
        return entry
    entry['module'] = module
    for key in ('go', 'toolchain'):
        if safe_token(directives.get(key)):
            entry['toolchain'][key] = directives[key]
    test_files = count_go_tests(directory)
    if test_files:
        entry['tests'].append(f'{test_files} _test.go file(s)')
        entry['commands'].append(command(rel_dir, ['go', 'test', './...'],
                                         'go.mod with _test.go files'))
    return entry


def count_go_tests(directory: Path) -> int:
    total = 0
    for current, dirs, files in os.walk(directory, followlinks=False):
        here = Path(current)
        # A nested go.mod starts a different module.
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (here / d / 'go.mod').exists()]
        total += sum(1 for f in files if f.endswith('_test.go'))
    return total


def make_targets(directory: Path, root: Path, unknowns: list) -> dict | None:
    path = directory / 'Makefile'
    if not path.exists():
        return None
    rel = path.relative_to(root).as_posix()
    raw = read_regular(path, unknowns, rel)
    if raw is None:
        return {'manifest': rel, 'targets': []}
    targets = sorted(set(MAKE_TARGET_RE.findall(raw.decode('utf-8', 'replace'))))
    rel_dir = directory.relative_to(root).as_posix() or '.'
    return {'manifest': rel, 'targets': targets,
            'commands': [command(rel_dir, ['make', t], f'Makefile target {t}')
                         for t in targets if t == 'test' or t.startswith('test')]}


def command(cwd: str, argv: list[str], basis: str) -> dict:
    return {'cwd': cwd, 'argv': argv, 'basis': basis, 'blockedBy': None, 'executed': False}


def ci_files(root: Path) -> list[str]:
    found = [n for n in CI_FILES if (root / n).is_file()]
    workflows = root / '.github' / 'workflows'
    if workflows.is_dir() and not workflows.is_symlink():
        found += sorted(p.relative_to(root).as_posix() for p in workflows.iterdir()
                        if p.suffix in ('.yml', '.yaml') and p.is_file())
    return found


# ---------------------------------------------------------------- report

def discover(cwd: Path) -> dict:
    root, identity = source_identity(cwd)
    dirs, truncated = walk(root)
    unknowns: list[dict] = []
    ecosystems = {'node': [], 'python': [], 'go': [], 'make': []}
    for directory in dirs:
        for key, probe in (('node', node_manifest), ('python', python_manifest),
                           ('go', go_manifest), ('make', make_targets)):
            found = probe(directory, root, unknowns)
            if found is not None:
                ecosystems[key].append(found)
    if truncated:
        unknowns.append({'path': '.', 'reason': 'directory-scan-truncated'})
    languages = sorted(k for k in ('node', 'python', 'go') if ecosystems[k])
    candidates = [c for group in ecosystems.values() for e in group for c in e.get('commands', [])]
    ci = ci_files(root)
    return {
        'schema': 'repo-context/v1',
        'cwd': str(cwd),
        'scanRoot': str(root),
        'source': identity,
        'instructions': instruction_files(root, cwd, dirs),
        'languages': languages,
        'mixed': len(languages) > 1,
        'ecosystems': ecosystems,
        'commandCandidates': candidates,
        'ci': {'files': ci, 'gates': None,
               'note': 'CI files are listed, not interpreted; required gates are unknown'},
        'unknowns': unknowns,
        'executionStillNeeded': still_needed(identity, ecosystems, candidates, ci, unknowns),
    }


def still_needed(identity: dict, ecosystems: dict, candidates: list, ci: list,
                 unknowns: list) -> list[str]:
    needed = ['reconcile these facts with the instruction files; instructions win on conflicts']
    if identity['kind'] != 'git':
        needed.append('record an explicit source description for this unversioned tree')
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
