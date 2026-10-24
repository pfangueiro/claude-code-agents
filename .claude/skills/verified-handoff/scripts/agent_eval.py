#!/usr/bin/env python3
"""Compare baseline and candidate instructions on a small synthetic agent-evaluation corpus.

Usage:
    agent_eval.py run --baseline FILE --candidate FILE --adapter FILE --out-dir NEW_DIR
                      [--trials N] [--timeout SECONDS] [--task ID ...] [--corpus FILE]

run
    For every selected corpus task, trial and arm (baseline, candidate) a fresh disposable
    solver workspace is created holding the public fixture files and a prompt file with
    the arm's instructions, the public task requirements and the response protocol. No
    grader, gold patch or history is placed there. The adapter's literal argv is executed
    (never through a shell) in that workspace via evidence.supervise; only the literal
    `{prompt_file}` inside arguments is replaced. Raw adapter logs stay in --out-dir.

    The adapter JSON holds exactly "argv", "name", "version" and "requested_model", plus
    an optional "input_files": regular, non-symlink files such as the wrapper script or CLI
    binary the argv runs, named by the same path the argv uses. Relative entries join the
    --adapter path as given (its directory is not canonicalized first, so directory aliases
    are kept). For the config and every input the lexical path, its resolved location
    (canonical parent plus final name, the final entry never followed) and the file
    identity are frozen before the first trial and rechecked before every launch and at
    the end; a path that now resolves elsewhere (even to identical bytes) or changed
    content is not launched (UNAVAILABLE) and is reported as source drift. Stable aliases
    such as /var -> /private/var are accepted. Without input_files the adapter payload
    identity is recorded as unknown.

    The adapter prints ONE JSON envelope on stdout:
        {"status": "success"|"unavailable", "observed_model": string|null,
         "cost_usd": nonnegative finite number|null, "response": object}
    Exit 0, status success and an empty process group are all required; a missing
    binary, nonzero exit, signal, timeout, surviving descendants, adapter-reported
    unavailability or malformed output makes the trial UNAVAILABLE (never a pass and
    never a zero score). Nothing is retried and no model or account is chosen here.

    The response is strictly validated (closed schema, exact types, safe allowlisted
    paths), applied to a fresh grading copy of the fixture, and graded by trusted
    built-in graders that live only in this file. Code tasks execute the produced
    module in a bounded subprocess against independent requirement checks; review
    findings are proven by executing their concrete witness; the support case checks
    the diagnosis against synthetic captured evidence. Protocol violations and scope
    violations FAIL. Scope is a complete entry inventory (files, directories, symlinks,
    never followed): any entry added, modified or removed in the solver workspace outside
    the allowed paths, or anywhere in the grading copy while it is graded, is a scope
    violation, and it stays FAIL even when the trial is otherwise unavailable. A grader
    probe that cannot launch or yields no usable result is UNAVAILABLE; an executed
    mismatch or import error is FAIL.

    --out-dir must not exist and must lie outside the skill source and corpus
    directory; result.json is written atomically there.

Outcomes:
    trial    PASS | FAIL | UNAVAILABLE
    overall  FAIL if any candidate trial failed or a task regressed against the baseline
             (unavailable trials and source drift stay listed in reasons); else
             INCOMPLETE if any trial is UNAVAILABLE or a source input changed during the
             run; else PASS. Source drift never yields PASS.

Exit codes: 0 PASS, 1 FAIL, 2 usage error (nothing evaluated), 3 INCOMPLETE.

Limits are listed in LIMITATIONS and recorded in every result.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import inspect
import json
import math
import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Callable, NamedTuple

SCRIPT_PATH = Path(__file__).resolve()
EVIDENCE_PATH = SCRIPT_PATH.parent / 'evidence.py'
SKILL_ROOT = SCRIPT_PATH.parent.parent
DEFAULT_CORPUS = SKILL_ROOT / 'references' / 'eval-corpus.json'


def _load_evidence():
    """Load the sibling evidence helpers by explicit path, never via ambient sys.path."""
    spec = importlib.util.spec_from_file_location('verified_handoff_evidence', EVIDENCE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError('evidence helpers unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load_evidence()

RESULT_SCHEMA = 'verified-handoff/agent-eval-result/v1'
CORPUS_SCHEMA = 'verified-handoff/agent-eval-corpus/v1'
ARMS = ('baseline', 'candidate')
OUTCOMES = ('PASS', 'FAIL', 'UNAVAILABLE')
KINDS = ('feature', 'bug-repair', 'refactor', 'review', 'support')
CODE_KINDS = ('feature', 'bug-repair', 'refactor')
PLACEHOLDER = '{prompt_file}'
PROMPT_NAME = 'AGENT_EVAL_PROMPT.md'
PROBE_MARKER = 'AGENT-EVAL-PROBE '
SENTINEL = 'agent-eval-delegation-sentinel'
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
DEFAULT_TIMEOUT = 900.0
GRADER_TIMEOUT = 60.0
MAX_TRIALS = 20
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_INSTRUCTIONS_BYTES = 256 * 1024
MAX_FILE_CHARS = 256 * 1024
MAX_FILES = 20
MAX_FINDINGS = 50
MAX_TEXT = 2000
MAX_LINE = 100_000
WITNESS_BOUND = 1_000_000
MAX_ADAPTER_INPUTS = 16
MAX_REPORTED_ENTRIES = 50

CORPUS_KEYS = ('schema', 'description', 'tasks')
TASK_KEYS = ('id', 'kind', 'grader', 'statement', 'public_api', 'files', 'allowed_paths', 'evidence')
PROBE_EVIDENCE_KEYS = ('captured_by', 'probes')
PROBE_KEYS = ('id', 'argv', 'exit_code', 'stdout', 'stderr')
ADAPTER_KEYS = ('argv', 'name', 'version', 'requested_model')
ADAPTER_OPTIONAL_KEYS = ('input_files',)
ENVELOPE_KEYS = ('status', 'observed_model', 'cost_usd', 'response')
RESPONSE_KEYS = ('files', 'findings', 'diagnosis')
FILE_KEYS = ('path', 'content')
FINDING_KEYS = ('path', 'line', 'args', 'expected', 'actual', 'description')
DIAGNOSIS_KEYS = ('outcome', 'cause', 'missing_evidence', 'remaining_unknown')

LIMITATIONS = (
    'filesystem separation only: the adapter and the produced code run with the caller\'s '
    'privileges and inherited environment; this is not an OS sandbox and does not defend '
    'against a malicious adapter or malicious produced code, which can read outside the '
    'workspace, forge probe output or alter files',
    'the adapter is trusted to report observed_model and cost_usd honestly; cost is null '
    'unless the adapter reported it',
    'hidden behavioral checks are finite cases against stated requirements, not proof of '
    'correctness',
    'six small synthetic cases; repeated trials are descriptive counts with no statistical '
    'efficacy claim',
    'the support case interprets synthetic captured evidence; it does not measure the '
    'runtime of the machine running the evaluation',
    'descendants that leave the adapter process group are not observed',
    'source inputs, the adapter config and declared adapter input_files are checked before '
    'and after the run (the config and input_files, with their path resolution, also before '
    'every launch); changes reverted between checks, or made between the last pre-launch '
    'check and the exec, are not detected',
    'adapter identity is its config hash and resolved config location, the argv[0] '
    'executable hash and, only when declared, input_files bindings (lexical path, resolved '
    'location, file identity); argv is not parsed, so identity covers the declared paths '
    'only and argv must reach each wrapper through its declared path; undeclared scripts, '
    'imports, transitive dependencies, environment and remote services are not identified, '
    'and without input_files the adapter payload identity is unknown',
    'workspace scope compares complete entry inventories taken before and after each '
    'step; entries created and removed within a step, and writes outside the workspace, '
    'are not observed',
    'produced code that hangs or kills the grader probe makes the trial UNAVAILABLE '
    '(INCOMPLETE overall), not FAIL',
    'the review grader supports only a trusted fixture module holding nothing but '
    'docstrings and one plain top-level bucket definition (no decorators, defaults or '
    'annotations; no nested function, class, lambda, global or nonlocal) with exactly one '
    'return statement directly in its body, in a package whose __init__ holds only '
    'docstrings, that raises ZeroDivisionError for a zero denominator and returns a plain '
    'int for every probed nonzero pair (grid and witnesses); any other fixture shape '
    '(imports, module-level assignments or other definitions, extra or nested returns) or '
    'behavior (exceptions, None, floats, bool, a missing zero-divisor error) is UNAVAILABLE; '
    'call-time rebinding through exec, globals, setattr or other modules is not detected '
    'and is excluded only by trusting the bundled fixtures',
    'the aggregate reported cost is null with status overflow when the per-trial reported '
    'costs do not sum to a finite number; per-trial values and counts are still reported',
)

RESPONSE_PROTOCOL = """\
## Response protocol

Your final answer is ONE JSON object, the `response`, with exactly these keys and no others.
The adapter that launched you returns it as `response` inside its own envelope.

- `files`: list of `{"path": string, "content": string}`. Each entry is the COMPLETE new
  content of one file. Paths are relative POSIX paths from the workspace root: no leading
  `/`, no `..`, `.` or empty segments, no backslashes, no `.git` segment, each path at most
  once, and only paths from the allowed list above.
- `findings`: list of review findings, each exactly `{"path": string, "line": integer,
  "args": [integer, integer], "expected": integer, "actual": integer, "description": string}`.
  `line` is the 1-based line of the statement that produces the wrong value; `args` is a
  concrete input pair, each integer between -1000000 and 1000000 with a nonzero second
  value; `expected` is the result the requirement demands for those args; `actual` is what
  the current code returns for them; `description` (1-2000 characters) explains the defect.
- `diagnosis`: `null`, or exactly `{"outcome": "PASS" | "FAIL" | "INCOMPLETE",
  "cause": "repository" | "environment" | "none", "missing_evidence": [probe id strings],
  "remaining_unknown": string}`.

Per task kind:
- feature, bug-repair, refactor: at least one `files` entry; `findings` is `[]`;
  `diagnosis` is `null`.
- review: `files` is `[]`; `diagnosis` is `null`; `findings` lists every defect, or is `[]`
  when the code meets the requirement.
- support: `files` is `[]`; `findings` is `[]`; `diagnosis` is required.

Only `response.files` is applied, to a fresh copy of the fixture; edits made directly in the
workspace are not graded. Changing any file outside the allowed list, in the workspace or in
the response, fails the task, and so does creating any new file, directory or symlink in the
workspace (including caches such as `__pycache__`; run Python with `-B`). Grading uses hidden
behavioral checks against the stated requirements, not a comparison of source text.
"""


class Invalid(Exception):
    """Validation failure carrying a fixed reason code (never untrusted content)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ProbeError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Case(NamedTuple):
    name: str
    function: str
    args: list
    patch: str | None
    expected: dict


@dataclass(frozen=True)
class Grader:
    kind: str
    allowed: tuple[str, ...]
    fixtures: tuple[str, ...]
    grade: Callable
    validate_evidence: Callable | None = None


@dataclass(frozen=True)
class RunContext:
    out_dir: Path
    adapter: dict
    executable: Path | None
    executable_sha256: str | None
    executable_error: str | None
    timeout: float


# ---------------------------------------------------------------- strict values

def reject_duplicate_keys(pairs: list) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def parse_json(text: str):
    return json.loads(text, parse_constant=evidence.reject_constant,
                      object_pairs_hook=reject_duplicate_keys)


def read_json_file(path: Path, prefix: str) -> tuple[object, str]:
    """Strict JSON from a regular, non-symlink file; returns (data, sha256 of bytes)."""
    try:
        info = path.lstat()
    except OSError:
        raise Invalid(f'{prefix}-unreadable') from None
    if stat.S_ISLNK(info.st_mode):
        raise Invalid(f'{prefix}-symlink')
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON_BYTES:
        raise Invalid(f'{prefix}-unreadable')
    try:
        raw = path.read_bytes()
        return parse_json(raw.decode('utf-8')), hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise Invalid(f'{prefix}-unreadable') from None


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_finite_number(value) -> bool:
    """True for a bool-free int or float that converts to a finite float."""
    if is_int(value):
        try:
            return math.isfinite(float(value))
        except OverflowError:
            return False
    return isinstance(value, float) and math.isfinite(value)


def require_keys(value, keys: tuple[str, ...], code: str) -> None:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise Invalid(code)


def require_text(value, code: str, low: int = 0, high: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not low <= len(value) <= high or '\0' in value:
        raise Invalid(code)
    return value


def safe_rel_path(raw, code: str) -> str:
    """A normalized relative POSIX path with no traversal, '.git', backslash or NUL."""
    if not isinstance(raw, str) or not 0 < len(raw) <= 200 or '\\' in raw or '\0' in raw:
        raise Invalid(code)
    pure = PurePosixPath(raw)
    if pure.is_absolute() or pure.as_posix() != raw:
        raise Invalid(code)
    if any(part in ('', '.', '..') or part.lower() == '.git' for part in pure.parts):
        raise Invalid(code)
    return raw


def file_sha(path: Path) -> str | None:
    try:
        return evidence.sha256_file(path)
    except OSError:
        return None


def input_identity(path: Path) -> str | None:
    """lstat-based identity of a declared adapter input, or None unless it is a regular file."""
    try:
        identity = evidence.entry_digest(path)
    except OSError:
        return None
    return identity if identity.startswith('file') else None


def resolved_location(lexical: Path) -> str | None:
    """Canonical parent of a lexical path joined with its final name (never followed)."""
    try:
        return str(lexical.parent.resolve(strict=True) / lexical.name)
    except (OSError, RuntimeError):
        return None


# ---------------------------------------------------------------- inputs

def validate_files(raw) -> dict[str, str]:
    if not isinstance(raw, dict) or not 0 < len(raw) <= MAX_FILES:
        raise Invalid('corpus-files-invalid')
    lowered: set[str] = set()
    for rel, content in raw.items():
        safe_rel_path(rel, 'corpus-file-path')
        if rel == PROMPT_NAME or rel.lower() in lowered:
            raise Invalid('corpus-file-path')
        lowered.add(rel.lower())
        require_text(content, 'corpus-file-content', 0, MAX_FILE_CHARS)
    for rel in raw:
        if any(str(parent) in raw for parent in PurePosixPath(rel).parents if str(parent) != '.'):
            raise Invalid('corpus-file-path')
    return dict(raw)


def validate_support_evidence(raw) -> None:
    """Closed schema for the synthetic captured probes, pinned to the trusted grader."""
    require_keys(raw, PROBE_EVIDENCE_KEYS, 'corpus-evidence-schema')
    require_text(raw['captured_by'], 'corpus-evidence-schema', 1)
    probes = raw['probes']
    if not isinstance(probes, list) or not 0 < len(probes) <= 10:
        raise Invalid('corpus-evidence-schema')
    exits: dict[str, int] = {}
    for probe in probes:
        require_keys(probe, PROBE_KEYS, 'corpus-evidence-schema')
        probe_id, argv = probe['id'], probe['argv']
        if not isinstance(probe_id, str) or not ID_RE.match(probe_id) or probe_id in exits:
            raise Invalid('corpus-evidence-schema')
        if not isinstance(argv, list) or not 0 < len(argv) <= 20:
            raise Invalid('corpus-evidence-schema')
        for arg in argv:
            require_text(arg, 'corpus-evidence-schema', 1, 200)
        if not is_int(probe['exit_code']):
            raise Invalid('corpus-evidence-schema')
        require_text(probe['stdout'], 'corpus-evidence-schema')
        require_text(probe['stderr'], 'corpus-evidence-schema')
        exits[probe_id] = probe['exit_code']
    if exits != SUPPORT_PROBE_EXITS:
        raise Invalid('corpus-evidence-mismatch')


def validate_task(raw) -> dict:
    require_keys(raw, TASK_KEYS, 'corpus-task-schema')
    if not isinstance(raw['id'], str) or not ID_RE.match(raw['id']):
        raise Invalid('corpus-task-id')
    grader = GRADERS.get(raw['grader']) if isinstance(raw['grader'], str) else None
    if grader is None or raw['kind'] != grader.kind:
        raise Invalid('corpus-task-grader')
    require_text(raw['statement'], 'corpus-task-schema', 1, 4000)
    require_text(raw['public_api'], 'corpus-task-schema', 1, 4000)
    files = validate_files(raw['files'])
    allowed = raw['allowed_paths']
    if not isinstance(allowed, list) or len(set(map(str, allowed))) != len(allowed):
        raise Invalid('corpus-allowed-paths')
    for rel in allowed:
        safe_rel_path(rel, 'corpus-allowed-paths')
    if set(allowed) != set(grader.allowed):
        raise Invalid('corpus-allowed-paths')
    if any(rel not in files for rel in grader.fixtures):
        raise Invalid('corpus-fixture-missing')
    if grader.validate_evidence is not None:
        grader.validate_evidence(raw['evidence'])
    elif raw['evidence'] is not None:
        raise Invalid('corpus-evidence-unexpected')
    return {'id': raw['id'], 'kind': raw['kind'], 'grader': raw['grader'],
            'statement': raw['statement'], 'public_api': raw['public_api'], 'files': files,
            'allowed_paths': list(allowed), 'evidence': raw['evidence']}


def load_corpus(path: Path) -> tuple[list[dict], str]:
    data, digest = read_json_file(path, 'corpus')
    require_keys(data, CORPUS_KEYS, 'corpus-schema')
    if data['schema'] != CORPUS_SCHEMA:
        raise Invalid('corpus-schema')
    require_text(data['description'], 'corpus-schema', 1, 4000)
    if not isinstance(data['tasks'], list) or not data['tasks']:
        raise Invalid('corpus-schema')
    tasks = [validate_task(raw) for raw in data['tasks']]
    if len({task['id'] for task in tasks}) != len(tasks):
        raise Invalid('corpus-duplicate-task')
    return tasks, digest


def select_tasks(tasks: list[dict], wanted: list[str] | None) -> list[dict]:
    if not wanted:
        return tasks
    by_id = {task['id']: task for task in tasks}
    if any(task_id not in by_id for task_id in wanted):
        raise Invalid('unknown-task')
    return [by_id[task_id] for task_id in dict.fromkeys(wanted)]


def load_instructions(raw: str) -> dict:
    path = Path(raw).absolute()
    try:
        info = path.lstat()
    except OSError:
        raise Invalid('instructions-unreadable') from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise Invalid('instructions-unreadable')
    if info.st_size > MAX_INSTRUCTIONS_BYTES:
        raise Invalid('instructions-too-large')
    try:
        data = path.read_bytes()
        text = data.decode('utf-8')
    except (OSError, UnicodeDecodeError):
        raise Invalid('instructions-unreadable') from None
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'text': text}


def load_input_files(raw, base: Path) -> list[dict]:
    """Freeze declared adapter payload files: regular, non-symlink, each listed once.

    `base` is the adapter config's directory as given, not canonicalized, so a relative
    entry keeps every directory alias it is reached through. Each entry records that
    lexical path, its resolved location ('path') and its identity; all are rechecked.
    """
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_ADAPTER_INPUTS:
        raise Invalid('adapter-input-files-invalid')
    frozen: list[dict] = []
    for declared in raw:
        if (not isinstance(declared, str) or not 0 < len(declared) <= 4096 or '\0' in declared
                or declared.split('/')[-1] in ('', '.', '..')):
            raise Invalid('adapter-input-file-invalid')
        lexical = base / declared
        location = resolved_location(lexical)
        if location is None:
            raise Invalid('adapter-input-file-unreadable')
        if any(item['path'] == location for item in frozen):
            raise Invalid('adapter-input-file-duplicate')
        try:
            identity = evidence.entry_digest(Path(location))
        except OSError:
            raise Invalid('adapter-input-file-unreadable') from None
        if identity == 'absent':
            raise Invalid('adapter-input-file-missing')
        if identity.startswith('link:'):
            raise Invalid('adapter-input-file-symlink')
        if not identity.startswith('file'):
            raise Invalid('adapter-input-file-not-regular')
        frozen.append({'declared': declared, 'lexical_path': str(lexical), 'path': location,
                       'identity': identity})
    return frozen


def load_adapter(path: Path) -> dict:
    data, digest = read_json_file(path, 'adapter')
    if (not isinstance(data, dict)
            or not set(ADAPTER_KEYS) <= set(data) <= set(ADAPTER_KEYS + ADAPTER_OPTIONAL_KEYS)):
        raise Invalid('adapter-schema')
    argv = data['argv']
    if (not isinstance(argv, list) or not 1 < len(argv) <= 64
            or not all(isinstance(arg, str) and len(arg) <= 4096 and '\0' not in arg for arg in argv)
            or not argv[0]):
        raise Invalid('adapter-argv-invalid')
    if not any(PLACEHOLDER in arg for arg in argv[1:]):
        raise Invalid('adapter-placeholder-missing')
    require_text(data['name'], 'adapter-schema', 1, 100)
    require_text(data['version'], 'adapter-schema', 1, 100)
    if data['requested_model'] is not None:
        require_text(data['requested_model'], 'adapter-schema', 1, 200)
    resolved = resolved_location(path)
    if resolved is None:
        raise Invalid('adapter-unreadable')
    inputs = load_input_files(data['input_files'], path.parent) if 'input_files' in data else []
    return {'path': str(path), 'resolved_path': resolved, 'dir': Path(resolved).parent,
            'config_sha256': digest, 'argv': list(argv), 'name': data['name'],
            'version': data['version'], 'requested_model': data['requested_model'],
            'input_files': inputs}


def input_drift(item: dict) -> str | None:
    """'alias' if the declared path now resolves elsewhere, 'content' if the file changed."""
    lexical = Path(item['lexical_path'])
    if resolved_location(lexical) != item['path']:
        return 'alias'
    if input_identity(lexical) != item['identity']:
        return 'content'
    return None


def config_drift(adapter: dict) -> str | None:
    """'alias' if the adapter config path now resolves elsewhere, 'content' if its bytes changed."""
    lexical = Path(adapter['path'])
    if resolved_location(lexical) != adapter['resolved_path']:
        return 'alias'
    if input_identity(lexical) is None or file_sha(lexical) != adapter['config_sha256']:
        return 'content'
    return None


def drift_reason(subject: str, kind: str) -> str:
    return f'{subject}-alias-changed' if kind == 'alias' else f'{subject}-changed'


def create_out_dir(raw: str, protected_roots: list[Path]) -> Path:
    target = Path(raw).absolute()
    if target.name in ('', '.', '..'):
        raise Invalid('out-dir-unsafe')
    final = target.parent.resolve(strict=True) / target.name
    if any(evidence.is_within(final, root) for root in protected_roots):
        raise Invalid('out-dir-inside-source')
    os.mkdir(final, 0o700)
    info = final.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Invalid('out-dir-unsafe')
    return final


# ---------------------------------------------------------------- workspaces

def new_temp_dir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix)).resolve()


def remove_tree(path: Path) -> bool:
    try:
        shutil.rmtree(path)
    except OSError:
        return False
    return True


def write_file(root: Path, rel: str, content: str) -> None:
    """Write root/rel without following a symlinked parent or target."""
    current = root
    for part in PurePosixPath(rel).parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            os.mkdir(current, 0o700)
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise Invalid('scope-symlink-path')
    try:
        handle = os.open(root / rel, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise Invalid('scope-symlink-path') from None
    with os.fdopen(handle, 'w', encoding='utf-8', newline='') as stream:
        stream.write(content)


def inventory(root: Path) -> dict[str, str]:
    """Every entry under root (file, directory, symlink, other) -> its lstat-based identity.

    Symlinks are recorded, never followed; a directory that cannot be listed is recorded
    as 'unreadable' so its hidden contents still register as a change.
    """
    entries: dict[str, str] = {}

    def unlistable(err: OSError) -> None:
        location = Path(err.filename) if err.filename else root
        entries[location.relative_to(root).as_posix()] = 'unreadable'

    for current, dirs, files in os.walk(root, onerror=unlistable, followlinks=False):
        here = Path(current)
        for name in dirs + files:
            path = here / name
            try:
                identity = evidence.entry_digest(path)
            except OSError:
                identity = 'unreadable'
            entries[path.relative_to(root).as_posix()] = identity
    return entries


def entry_changes(before: dict[str, str], after: dict[str, str]) -> tuple[list[str], list[str]]:
    """(entries modified or removed, entries added) between two inventories."""
    changed = sorted(rel for rel, identity in before.items() if after.get(rel) != identity)
    added = sorted(set(after) - set(before))
    return changed, added


def build_prompt(task: dict, instructions_text: str) -> str:
    allowed = '\n'.join(f'- `{rel}`' for rel in task['allowed_paths'])
    sections = [
        f'# Agent evaluation task `{task["id"]}` ({task["kind"]})',
        '## Instructions under evaluation', instructions_text.strip() or '(empty)',
        '## Task', task['statement'],
        '## Public API', task['public_api'],
        '## Allowed changes', allowed or '- none: this task must not change any file',
        '## Workspace files',
        'The current working directory is a disposable copy of these files.',
    ]
    for rel in sorted(task['files']):
        content = task['files'][rel]
        if not content.endswith('\n'):
            content += '\n'
        sections.append(f'### `{rel}`\n\n```\n{content}```')
    if task['evidence'] is not None:
        sections.append('## Captured evidence (synthetic)')
        sections.append('```json\n' + json.dumps(task['evidence'], indent=2) + '\n```')
    sections.append(RESPONSE_PROTOCOL.strip())
    return '\n\n'.join(sections) + '\n'


# ---------------------------------------------------------------- adapter

def parse_envelope(path: Path) -> dict:
    size = path.stat().st_size
    if size == 0:
        raise Invalid('adapter-output-missing')
    if size > MAX_JSON_BYTES:
        raise Invalid('adapter-output-too-large')
    try:
        data = parse_json(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Invalid('adapter-output-malformed') from None
    require_keys(data, ENVELOPE_KEYS, 'adapter-output-schema')
    if data['status'] not in ('success', 'unavailable'):
        raise Invalid('adapter-output-schema')
    if data['observed_model'] is not None:
        require_text(data['observed_model'], 'adapter-output-schema', 1, 200)
    cost = data['cost_usd']
    if cost is not None and not (is_finite_number(cost) and cost >= 0):
        raise Invalid('adapter-output-schema')
    if not isinstance(data['response'], dict):
        raise Invalid('adapter-output-schema')
    return data


def adapter_gate(child: dict) -> list[str]:
    reasons = []
    if child['timedOut']:
        reasons.append('adapter-timed-out')
    if child['signal'] is not None:
        reasons.append('adapter-signalled')
    elif child['exitCode'] != 0:
        reasons.append('adapter-nonzero-exit')
    if child['descendantsOutlivedDeadline'] or not child['groupEmptyAtReceipt']:
        reasons.append('adapter-descendants-alive')
    return reasons


def invoke_adapter(ctx: RunContext, workspace: Path, prompt_path: Path,
                   logs_dir: Path) -> tuple[dict | None, list[str], dict]:
    """Run the adapter once; return (envelope or None, unavailable reasons, run record)."""
    info = {'launched': False, 'exit_code': None, 'signal': None, 'timed_out': False,
            'descendants_outlived_deadline': False, 'group_empty': None,
            'duration_seconds': None, 'logs': None}
    if ctx.executable is None:
        return None, [ctx.executable_error or 'executable-not-found'], info
    if file_sha(ctx.executable) != ctx.executable_sha256:
        return None, ['executable-changed'], info
    drift = [('adapter-config', config_drift(ctx.adapter))]
    drift += [('adapter-input', input_drift(item)) for item in ctx.adapter['input_files']]
    drifted = sorted({drift_reason(subject, kind) for subject, kind in drift if kind})
    if drifted:
        return None, drifted, info
    argv = [ctx.adapter['argv'][0]]
    argv += [arg.replace(PLACEHOLDER, str(prompt_path)) for arg in ctx.adapter['argv'][1:]]
    os.mkdir(logs_dir, 0o700)
    started = time.monotonic()
    try:
        child = evidence.supervise(argv, ctx.executable, workspace, logs_dir, ctx.timeout)
    except evidence.Refusal as refusal:
        return None, [refusal.code], info
    info.update(launched=True, exit_code=child['exitCode'], signal=child['signal'],
                timed_out=child['timedOut'],
                descendants_outlived_deadline=child['descendantsOutlivedDeadline'],
                group_empty=child['groupEmptyAtReceipt'],
                duration_seconds=round(time.monotonic() - started, 3),
                logs={name: evidence.log_record(logs_dir / f'{name}.log')
                      for name in ('stdout', 'stderr')})
    reasons = adapter_gate(child)
    if reasons:
        return None, reasons, info
    try:
        envelope = parse_envelope(logs_dir / 'stdout.log')
    except Invalid as invalid:
        return None, [invalid.code], info
    if envelope['status'] == 'unavailable':
        return envelope, ['adapter-reported-unavailable'], info
    return envelope, [], info


# ---------------------------------------------------------------- response

def validate_response_files(raw, task: dict) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_FILES:
        raise Invalid('response-files-invalid')
    seen: set[str] = set()
    for item in raw:
        require_keys(item, FILE_KEYS, 'response-file-schema')
        rel = safe_rel_path(item['path'], 'scope-unsafe-path')
        if rel in seen:
            raise Invalid('scope-duplicate-path')
        if rel not in task['allowed_paths']:
            raise Invalid('scope-path-not-allowed')
        seen.add(rel)
        require_text(item['content'], 'response-file-content', 0, MAX_FILE_CHARS)
    return [{'path': item['path'], 'content': item['content']} for item in raw]


def validate_findings(raw) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_FINDINGS:
        raise Invalid('response-findings-invalid')
    for item in raw:
        require_keys(item, FINDING_KEYS, 'response-finding-schema')
        safe_rel_path(item['path'], 'response-finding-path')
        if not is_int(item['line']) or not 1 <= item['line'] <= MAX_LINE:
            raise Invalid('response-finding-line')
        args = item['args']
        if (not isinstance(args, list) or len(args) != 2
                or not all(is_int(arg) and abs(arg) <= WITNESS_BOUND for arg in args)
                or args[1] == 0):
            raise Invalid('response-finding-args')
        if not is_int(item['expected']) or not is_int(item['actual']):
            raise Invalid('response-finding-values')
        require_text(item['description'], 'response-finding-description', 1)
    return [dict(item) for item in raw]


def validate_diagnosis(raw) -> dict:
    require_keys(raw, DIAGNOSIS_KEYS, 'response-diagnosis-schema')
    if raw['outcome'] not in ('PASS', 'FAIL', 'INCOMPLETE'):
        raise Invalid('response-diagnosis-outcome')
    if raw['cause'] not in ('repository', 'environment', 'none'):
        raise Invalid('response-diagnosis-cause')
    missing = raw['missing_evidence']
    if (not isinstance(missing, list) or len(missing) > 20
            or not all(isinstance(item, str) and ID_RE.match(item) for item in missing)
            or len(set(missing)) != len(missing)):
        raise Invalid('response-diagnosis-missing-evidence')
    require_text(raw['remaining_unknown'], 'response-diagnosis-remaining-unknown')
    return dict(raw)


def validate_response(raw: dict, task: dict) -> dict:
    require_keys(raw, RESPONSE_KEYS, 'response-schema')
    files = validate_response_files(raw['files'], task)
    findings = validate_findings(raw['findings'])
    diagnosis = raw['diagnosis']
    if task['kind'] in CODE_KINDS:
        if not files:
            raise Invalid('response-files-missing')
        if findings:
            raise Invalid('response-findings-not-applicable')
        if diagnosis is not None:
            raise Invalid('response-diagnosis-not-applicable')
    elif task['kind'] == 'review':
        if files:
            raise Invalid('scope-files-on-read-only-task')
        if diagnosis is not None:
            raise Invalid('response-diagnosis-not-applicable')
    else:
        if files:
            raise Invalid('scope-files-on-read-only-task')
        if findings:
            raise Invalid('response-findings-not-applicable')
        diagnosis = validate_diagnosis(diagnosis)
    return {'files': files, 'findings': findings, 'diagnosis': diagnosis}


# ---------------------------------------------------------------- behavioral probes

def encode_value(value):
    """Exact-type JSON encoding of a call result; shared verbatim with the probe subprocess."""
    kind = type(value)
    if value is None or kind in (bool, str):
        return {'type': kind.__name__, 'value': value}
    if kind is int:
        if value.bit_length() > 256:
            return {'type': 'int', 'repr': 'too-large'}
        return {'type': 'int', 'value': value}
    if kind is float:
        if value != value or value in (float('inf'), float('-inf')):
            return {'type': 'float', 'repr': repr(value)}
        return {'type': 'float', 'value': value}
    if kind is list:
        return {'type': 'list', 'length': len(value),
                'value': [encode_value(item) for item in value[:100]]}
    try:
        text = repr(value)[:200]
    except Exception:
        text = 'unrepresentable'
    return {'type': kind.__name__[:64], 'repr': text}


PROBE_BODY = r'''
with open(sys.argv[1], encoding='utf-8') as handle:
    spec = json.load(handle)
sys.path.insert(0, spec['root'])


def emit(payload):
    sys.stdout.write('\n' + spec['marker'] + json.dumps(payload) + '\n')
    sys.stdout.flush()


try:
    module = importlib.import_module(spec['module'])
except BaseException as exc:
    emit({'import_error': type(exc).__name__})
    raise SystemExit(0)


def sentinel(*args, **kwargs):
    return spec['sentinel']


missing = object()
results = []
for call in spec['calls']:
    patch = call['patch']
    original = module.__dict__.get(patch, missing) if patch else missing
    try:
        if patch:
            setattr(module, patch, sentinel)
        function = getattr(module, call['fn'])
        results.append({'value': encode_value(function(*call['args']))})
    except BaseException as exc:
        results.append({'raises': [klass.__name__ for klass in type(exc).__mro__]})
    finally:
        if patch and original is missing:
            module.__dict__.pop(patch, None)
        elif patch:
            setattr(module, patch, original)
emit({'results': results})
'''

PROBE_SCRIPT = ('import importlib\nimport json\nimport sys\n\n\n'
                + inspect.getsource(encode_value) + PROBE_BODY)


def validate_probe_payload(payload, call_count: int) -> dict:
    if not isinstance(payload, dict) or len(payload) != 1:
        raise ProbeError('probe-output-invalid')
    if 'import_error' in payload:
        name = payload['import_error']
        return {'import_error': name if isinstance(name, str) and NAME_RE.match(name) else 'unknown'}
    results = payload.get('results')
    if not isinstance(results, list) or len(results) != call_count:
        raise ProbeError('probe-output-invalid')
    for item in results:
        if not isinstance(item, dict) or len(item) != 1:
            raise ProbeError('probe-output-invalid')
        if 'value' in item and isinstance(item['value'], dict):
            continue
        raises = item.get('raises')
        if not isinstance(raises, list) or not all(isinstance(name, str) for name in raises):
            raise ProbeError('probe-output-invalid')
    return {'results': results}


def run_probe(root: Path, trial_dir: Path, module: str, calls: list[dict]) -> dict:
    """Import `module` from root in a bounded isolated subprocess and record each call."""
    probe_dir = trial_dir / 'grader'
    os.mkdir(probe_dir, 0o700)
    spec_path = probe_dir / 'probe-spec.json'
    with open(spec_path, 'x', encoding='utf-8') as handle:
        json.dump({'root': str(root), 'module': module, 'marker': PROBE_MARKER,
                   'sentinel': SENTINEL, 'calls': calls}, handle)
    executable = Path(sys.executable).resolve()
    argv = [str(executable), '-I', '-B', '-c', PROBE_SCRIPT, str(spec_path)]
    try:
        child = evidence.supervise(argv, executable, root, probe_dir, GRADER_TIMEOUT)
    except evidence.Refusal:
        raise ProbeError('probe-launch-failed') from None
    if (child['timedOut'] or child['signal'] is not None or child['exitCode'] != 0
            or not child['groupEmptyAtReceipt']
            or child['descendantsOutlivedDeadline'] or child['signalsSent']):
        raise ProbeError('probe-did-not-complete')
    stdout = probe_dir / 'stdout.log'
    if stdout.stat().st_size > MAX_JSON_BYTES:
        raise ProbeError('probe-output-too-large')
    lines = [line for line in stdout.read_text(encoding='utf-8', errors='replace').splitlines()
             if line.startswith(PROBE_MARKER)]
    if not lines:
        raise ProbeError('probe-output-missing')
    try:
        payload = parse_json(lines[-1][len(PROBE_MARKER):])
    except (ValueError, RecursionError):
        raise ProbeError('probe-output-invalid') from None
    return validate_probe_payload(payload, len(calls))


def expected_of(spec: Callable, args: tuple) -> dict:
    try:
        return {'value': encode_value(spec(*args))}
    except ValueError:
        return {'raises': 'ValueError'}


def matches(expected: dict, observed: dict) -> bool:
    if 'raises' in expected:
        return expected['raises'] in observed.get('raises', [])
    return observed == expected


def spec_cases(function: str, spec: Callable, arg_sets: list[tuple],
               patch: str | None = None) -> list[Case]:
    return [Case(f'{function}{tuple(args)!r}', function, list(args), patch, expected_of(spec, args))
            for args in arg_sets]


def make_verdict(passed: bool, reasons: list[str], checks: list | None = None,
                 review: dict | None = None, unavailable: str | None = None) -> dict:
    return {'passed': passed, 'reasons': reasons, 'checks': checks or [], 'review': review,
            'unavailable': unavailable}


def check_behavior(root: Path, trial_dir: Path, module: str, cases: list[Case]) -> dict:
    calls = [{'fn': case.function, 'args': case.args, 'patch': case.patch} for case in cases]
    try:
        probe = run_probe(root, trial_dir, module, calls)
    except ProbeError as err:
        # No usable probe evidence: unattributable, never a candidate FAIL.
        return make_verdict(False, [], unavailable=err.code)
    if 'import_error' in probe:
        check = {'name': f'import {module}', 'expected': 'importable',
                 'observed': probe['import_error'], 'ok': False}
        return make_verdict(False, ['module-import-failed'], checks=[check])
    checks = [{'name': case.name, 'expected': case.expected, 'observed': observed,
               'ok': matches(case.expected, observed)}
              for case, observed in zip(cases, probe['results'])]
    passed = all(check['ok'] for check in checks)
    return make_verdict(passed, [] if passed else ['behavior-mismatch'], checks=checks)


# ---------------------------------------------------------------- graders (never shown to solvers)

def spec_mean(values):
    values = list(values)
    if not values:
        raise ValueError('empty')
    return sum(values) / len(values)


def spec_clamp(value, low, high):
    if low > high:
        raise ValueError('inverted bounds')
    if value < low:
        return low
    if value > high:
        return high
    return value


# Boundary cases only use equal-typed bounds so every valid implementation agrees on the
# returned object's type.
CLAMP_ARGS = [(5, 0, 10), (-1, 0, 10), (11, 0, 10), (0, 0, 10), (10, 0, 10), (3, 3, 3),
              (2.5, 0, 1), (0.5, 0.0, 1.0), (-3.5, -1, 1), (1, 2, 1), (0, 1, 0)]
MEAN_ARGS = [([1, 2],), ([4],), ([2, 4, 9],), ([],)]


def grade_clamp_feature(task: dict, root: Path, trial_dir: Path, response: dict) -> dict:
    cases = spec_cases('clamp', spec_clamp, CLAMP_ARGS) + spec_cases('mean', spec_mean, MEAN_ARGS)
    return check_behavior(root, trial_dir, 'pkg.numbers', cases)


def spec_page_count(total, per_page):
    if not is_int(total) or total < 0 or not is_int(per_page) or per_page < 1:
        raise ValueError('invalid')
    pages, remainder = divmod(total, per_page)
    return pages + (1 if remainder else 0)


def spec_page_slice(items, page, per_page):
    if not is_int(page) or page < 1 or not is_int(per_page) or per_page < 1:
        raise ValueError('invalid')
    start = (page - 1) * per_page
    return list(items[start:start + per_page])


PAGE_COUNT_ARGS = [(0, 10), (10, 10), (11, 10), (1, 10), (9, 10), (25, 1), (100, 7), (99, 100),
                   (5, 0), (-1, 10), (5, -3), (True, 3), (3.0, 2)]
ITEMS = list(range(25))
PAGE_SLICE_ARGS = [(ITEMS, 1, 10), (ITEMS, 3, 10), (ITEMS, 4, 10), ([], 1, 5), ([1, 2, 3], 2, 2),
                   (ITEMS, 0, 10), (ITEMS, 1, 0)]


def grade_page_count_repair(task: dict, root: Path, trial_dir: Path, response: dict) -> dict:
    cases = (spec_cases('page_count', spec_page_count, PAGE_COUNT_ARGS)
             + spec_cases('page_slice', spec_page_slice, PAGE_SLICE_ARGS))
    return check_behavior(root, trial_dir, 'pkg.paging', cases)


def spec_format(kind, name, age):
    if kind not in ('user', 'admin'):
        raise ValueError('kind')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('name')
    if not is_int(age) or age < 0:
        raise ValueError('age')
    return f'{kind}: {name.strip()} ({age})'


REPORT_NAMES = ['Ana', '  Bo  ', '', '   ', 7, None]
REPORT_AGES = [0, 41, -1, True, 2.5]
REPORT_KINDS = ['user', 'admin', 'guest', 'User', None]
REPORT_RECORD_PAIRS = [('Ana', 3), ('  Bo  ', 0), ('', 3), ('Ana', -1)]


def grade_report_refactor(task: dict, root: Path, trial_dir: Path, response: dict) -> dict:
    pairs = [(name, age) for name in REPORT_NAMES for age in REPORT_AGES]
    cases: list[Case] = []
    for kind in ('user', 'admin'):
        cases += spec_cases(f'format_{kind}', partial(spec_format, kind), pairs)
    cases += spec_cases('format_record', spec_format,
                        [(kind, name, age) for kind in REPORT_KINDS for name, age in REPORT_RECORD_PAIRS])
    # Delegation is observed behaviorally: replacing the module-level format_record must
    # change what the existing entry points return.
    cases += [Case(f'format_{kind} delegates to format_record', f'format_{kind}', ['Ana', 1],
                   'format_record', {'value': encode_value(SENTINEL)})
              for kind in ('user', 'admin')]
    return check_behavior(root, trial_dir, 'pkg.report', cases)


REVIEW_PATH = 'pkg/ratio.py'
REVIEW_MODULE = 'pkg.ratio'
REVIEW_FUNCTION = 'bucket'
REVIEW_GRID = [(a, b) for a in range(-12, 13) for b in range(-5, 6) if b != 0]
# Run in the same probe as the grid: the task contract requires ZeroDivisionError here, and
# the integer-witness protocol cannot express an exception, so other behavior is unsupported.
REVIEW_ZERO_DIVISOR = [(0, 0), (7, 0), (-7, 0)]


NESTED_BINDINGS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda,
                   ast.Global, ast.Nonlocal)


def docstrings_only(nodes: list) -> bool:
    """True when every statement is a bare string literal (a docstring)."""
    return all(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
               and isinstance(node.value.value, str) for node in nodes)


def plain_signature(node: ast.FunctionDef) -> bool:
    """No decorators, defaults or annotations: nothing else is evaluated when the def runs."""
    arguments = node.args
    params = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
    params += [param for param in (arguments.vararg, arguments.kwarg) if param is not None]
    return (not node.decorator_list and node.returns is None and not arguments.defaults
            and not any(arguments.kw_defaults)
            and all(param.annotation is None for param in params))


def single_return_line(source: str, function: str) -> int | None:
    """Line of the only return in `function`, the module's only non-docstring statement.

    The grader attributes a wrong value to a line, which is only unambiguous when nothing
    else in the module can bind or rebind the name (only docstrings besides one plain
    definition, with no nested scope, global or nonlocal inside it) and the function has
    exactly one return statement placed directly in its body (not inside a branch, loop,
    try or with), so that it is the statement producing every returned value. Anything
    else is an unsupported fixture (None), not a reviewable one.
    """
    tree = ast.parse(source)
    statements = [node for node in tree.body if not docstrings_only([node])]
    if (len(statements) != 1 or not isinstance(statements[0], ast.FunctionDef)
            or statements[0].name != function or not plain_signature(statements[0])):
        return None
    node = statements[0]
    inner = list(ast.walk(node))[1:]
    if any(isinstance(child, NESTED_BINDINGS) for child in inner):
        return None
    returns = [child for child in inner if isinstance(child, ast.Return)]
    if len(returns) != 1 or returns[0] not in node.body or returns[0].value is None:
        return None
    return returns[0].lineno


def observed_int(observed: dict) -> int | None:
    value = observed.get('value')
    if isinstance(value, dict) and value.get('type') == 'int' and is_int(value.get('value')):
        return value['value']
    return None


def assess_finding(finding: dict, observed: dict, statement_lines: set[int]) -> dict:
    numerator, denominator = finding['args']
    truth = numerator // denominator
    actual = observed_int(observed)
    checks = {
        'path': finding['path'] == REVIEW_PATH,
        'line': finding['line'] in statement_lines,
        'expected_is_floor_division': finding['expected'] == truth,
        'actual_matches_execution': actual is not None and finding['actual'] == actual,
        'witness_differs': actual is not None and actual != truth,
    }
    return {'path': finding['path'], 'line': finding['line'], 'args': [numerator, denominator],
            'observed': observed, 'checks': checks, 'valid': all(checks.values())}


def grade_floor_division_review(task: dict, root: Path, trial_dir: Path, response: dict) -> dict:
    """Truth comes from executing the protected fixture; a finding counts only with a proven witness."""
    findings = response['findings']
    try:
        package_init = root / PurePosixPath(REVIEW_PATH).parent / '__init__.py'
        init_source = package_init.read_text(encoding='utf-8') if package_init.exists() else ''
        line = (single_return_line((root / REVIEW_PATH).read_text(encoding='utf-8'),
                                   REVIEW_FUNCTION)
                if docstrings_only(ast.parse(init_source).body) else None)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError, RecursionError):
        return make_verdict(False, [], unavailable='review-fixture-unreadable')
    if line is None:
        return make_verdict(False, [], unavailable='review-fixture-unsupported')
    statement_lines = {line}
    pairs = REVIEW_GRID + REVIEW_ZERO_DIVISOR + [tuple(item['args']) for item in findings]
    calls = [{'fn': REVIEW_FUNCTION, 'args': [a, b], 'patch': None} for a, b in pairs]
    try:
        probe = run_probe(root, trial_dir, REVIEW_MODULE, calls)
    except ProbeError as err:
        return make_verdict(False, [], unavailable=f'review-{err.code}')
    if 'import_error' in probe:
        return make_verdict(False, [], unavailable='review-fixture-import-failed')
    results = probe['results']
    grid_results = results[:len(REVIEW_GRID)]
    zero_results = results[len(REVIEW_GRID):len(REVIEW_GRID) + len(REVIEW_ZERO_DIVISOR)]
    witness_results = results[len(REVIEW_GRID) + len(REVIEW_ZERO_DIVISOR):]
    if not all('ZeroDivisionError' in observed.get('raises', []) for observed in zero_results):
        return make_verdict(False, [], unavailable='review-fixture-unsupported-zero-divisor')
    if any(observed_int(observed) is None for observed in grid_results + witness_results):
        return make_verdict(False, [], unavailable='review-fixture-unsupported-result')
    disagreements = sum(1 for (a, b), observed in zip(REVIEW_GRID, grid_results)
                        if observed_int(observed) != a // b)
    assessed = [assess_finding(item, observed, statement_lines)
                for item, observed in zip(findings, witness_results)]
    valid = sum(1 for item in assessed if item['valid'])
    true_positives = min(valid, 1)  # the fixture holds a single defective statement
    false_positives = len(assessed) - valid
    defective = disagreements > 0 or valid > 0
    false_negatives = 1 if defective and not true_positives else 0
    reasons = (['review-false-positive'] if false_positives else []) + \
              (['review-missed-defect'] if false_negatives else [])
    review = {'defective': defective, 'true_positives': true_positives,
              'false_positives': false_positives, 'false_negatives': false_negatives,
              'duplicates': valid - true_positives,
              'grid': {'cases': len(REVIEW_GRID), 'disagreements': disagreements},
              'findings': assessed}
    return make_verdict(not reasons, reasons, review=review)


SUPPORT_PROBE_EXITS = {'runtime-version': 127, 'behavioral-tests': 127, 'static-diff-check': 0}
SUPPORT_REQUIRED_MISSING = frozenset({'behavioral-tests'})
SUPPORT_OPTIONAL_MISSING = frozenset({'runtime-version'})


def grade_environment_diagnosis(task: dict, _root: Path, _trial_dir: Path, response: dict) -> dict:
    diagnosis = response['diagnosis']
    missing = set(diagnosis['missing_evidence'])
    permitted = SUPPORT_REQUIRED_MISSING | SUPPORT_OPTIONAL_MISSING
    stated = len(diagnosis['remaining_unknown'].strip())
    checks = [
        {'name': 'outcome', 'expected': 'INCOMPLETE', 'observed': diagnosis['outcome'],
         'ok': diagnosis['outcome'] == 'INCOMPLETE'},
        {'name': 'cause', 'expected': 'environment', 'observed': diagnosis['cause'],
         'ok': diagnosis['cause'] == 'environment'},
        {'name': 'missing behavioral evidence is listed',
         'expected': sorted(SUPPORT_REQUIRED_MISSING), 'observed': sorted(missing),
         'ok': SUPPORT_REQUIRED_MISSING <= missing},
        {'name': 'only probes without evidence are listed as missing',
         'expected': sorted(permitted), 'observed': sorted(missing), 'ok': missing <= permitted},
        {'name': 'remaining unknown is stated', 'expected': 'non-empty text',
         'observed': stated, 'ok': stated > 0},
    ]
    passed = all(check['ok'] for check in checks)
    return make_verdict(passed, [] if passed else ['diagnosis-mismatch'], checks=checks)


GRADERS: dict[str, Grader] = {
    'clamp-feature': Grader('feature', ('pkg/numbers.py',), ('pkg/numbers.py',),
                            grade_clamp_feature),
    'page-count-repair': Grader('bug-repair', ('pkg/paging.py',), ('pkg/paging.py',),
                                grade_page_count_repair),
    'report-refactor': Grader('refactor', ('pkg/report.py',), ('pkg/report.py',),
                              grade_report_refactor),
    'floor-division-review': Grader('review', (), (REVIEW_PATH,), grade_floor_division_review),
    'environment-diagnosis': Grader('support', (), ('pkg/clock.py',),
                                    grade_environment_diagnosis, validate_support_evidence),
}


# ---------------------------------------------------------------- trials

def new_record(ctx: RunContext, arm: str, task: dict, trial: int) -> dict:
    return {
        'arm': arm, 'task': task['id'], 'kind': task['kind'], 'grader': task['grader'],
        'trial': trial, 'outcome': None, 'reasons': [],
        'requested_model': ctx.adapter['requested_model'], 'observed_model': None,
        'cost_usd': None, 'adapter': None,
        'scope': {'allowed_paths': list(task['allowed_paths']), 'response_paths': [],
                  'protected_changed_by_provider': [], 'allowed_changed_in_workspace': [],
                  'workspace_extra_files': 0, 'workspace_extra_entries': [],
                  'protected_changed_by_grading': [], 'grading_extra_entries': []},
        'behavior': {'checks': [], 'passed': 0, 'total': 0},
        'review': None, 'diagnosis': None, 'unavailable_reasons': [], 'cleanup_failures': [],
        'trial_duration_seconds': None,
    }


def finish(record: dict, outcome: str, reasons: list[str]) -> None:
    record['outcome'] = outcome
    record['reasons'] = reasons


SCOPE_FAILURES = (
    ('protected_changed_by_provider', 'scope-protected-file-changed'),
    ('workspace_extra_entries', 'scope-workspace-entry-added'),
    ('protected_changed_by_grading', 'scope-protected-file-changed-during-grading'),
    ('grading_extra_entries', 'scope-entry-added-during-grading'),
)


def scope_failures(scope: dict) -> list[str]:
    """FAIL reasons for every observed scope violation recorded so far."""
    return [code for key, code in SCOPE_FAILURES if scope[key]]


def record_workspace_scope(scope: dict, task: dict, before: dict[str, str],
                           after: dict[str, str]) -> None:
    """Allowed paths may change in place; every other added, modified or removed entry is a violation."""
    changed, added = entry_changes(before, after)
    allowed = set(task['allowed_paths'])
    extra = [rel for rel in added if rel not in allowed]
    scope['protected_changed_by_provider'] = [rel for rel in changed if rel not in allowed]
    scope['allowed_changed_in_workspace'] = sorted(rel for rel in changed + added if rel in allowed)
    scope['workspace_extra_files'] = len(extra)
    scope['workspace_extra_entries'] = extra[:MAX_REPORTED_ENTRIES]


def grade_in(grading: Path, task: dict, response: dict,
             trial_dir: Path) -> tuple[dict, list[str], list[str]]:
    try:
        for rel, content in task['files'].items():
            write_file(grading, rel, content)
        for item in response['files']:
            write_file(grading, item['path'], item['content'])
    except Invalid as invalid:
        return make_verdict(False, [invalid.code]), [], []
    before = inventory(grading)
    verdict = GRADERS[task['grader']].grade(task, grading, trial_dir, response)
    changed, added = entry_changes(before, inventory(grading))
    return verdict, changed, added


def grade_response(task: dict, response: dict,
                   trial_dir: Path) -> tuple[dict, list[str], list[str], bool]:
    grading = new_temp_dir('agent-eval-grade-')
    try:
        verdict, changed, added = grade_in(grading, task, response, trial_dir)
    finally:
        cleaned = remove_tree(grading)
    return verdict, changed, added, cleaned


def solve_and_grade(ctx: RunContext, instructions: dict, task: dict, workspace: Path,
                    trial_dir: Path, record: dict) -> None:
    for rel, content in task['files'].items():
        write_file(workspace, rel, content)
    write_file(workspace, PROMPT_NAME, build_prompt(task, instructions['text']))
    before = inventory(workspace)
    envelope, unavailable, record['adapter'] = invoke_adapter(
        ctx, workspace, workspace / PROMPT_NAME, trial_dir / 'adapter')
    if envelope is not None:
        record['observed_model'] = envelope['observed_model']
        record['cost_usd'] = envelope['cost_usd']
    record['unavailable_reasons'] = list(unavailable)
    scope = record['scope']
    record_workspace_scope(scope, task, before, inventory(workspace))
    failures = scope_failures(scope)
    if unavailable:
        # An observed scope violation stays FAIL; the unavailability is kept separately.
        finish(record, 'FAIL' if failures else 'UNAVAILABLE', failures or list(unavailable))
        return
    try:
        response = validate_response(envelope['response'], task)
    except Invalid as invalid:
        finish(record, 'FAIL', failures + [invalid.code])
        return
    scope['response_paths'] = [item['path'] for item in response['files']]
    record['diagnosis'] = response['diagnosis']
    verdict, grading_changed, grading_added, cleaned = grade_response(task, response, trial_dir)
    if not cleaned:
        record['cleanup_failures'].append('grading-workspace')
    scope['protected_changed_by_grading'] = grading_changed
    scope['grading_extra_entries'] = grading_added[:MAX_REPORTED_ENTRIES]
    record['behavior'] = {'checks': verdict['checks'],
                          'passed': sum(1 for check in verdict['checks'] if check['ok']),
                          'total': len(verdict['checks'])}
    record['review'] = verdict['review']
    failures = scope_failures(scope)
    if verdict['unavailable'] is not None:
        record['unavailable_reasons'].append(verdict['unavailable'])
    elif not verdict['passed']:
        failures.extend(verdict['reasons'])
    if failures:
        finish(record, 'FAIL', failures)
    elif verdict['unavailable'] is not None:
        finish(record, 'UNAVAILABLE', [verdict['unavailable']])
    else:
        finish(record, 'PASS', [])


def run_trial(ctx: RunContext, arm: str, instructions: dict, task: dict, trial: int) -> dict:
    started = time.monotonic()
    trial_dir = ctx.out_dir / arm / task['id'] / f'trial-{trial}'
    os.makedirs(trial_dir, mode=0o700)
    record = new_record(ctx, arm, task, trial)
    workspace = new_temp_dir('agent-eval-solver-')
    try:
        solve_and_grade(ctx, instructions, task, workspace, trial_dir, record)
    except Exception as exc:  # recorded as a harness error, never as a pass
        reason = f'harness-error:{type(exc).__name__}'
        record['unavailable_reasons'].append(reason)
        observed = scope_failures(record['scope'])
        finish(record, 'FAIL' if observed else 'UNAVAILABLE', observed or [reason])
    finally:
        if not remove_tree(workspace):
            record['cleanup_failures'].append('solver-workspace')
    record['trial_duration_seconds'] = round(time.monotonic() - started, 3)
    return record


# ---------------------------------------------------------------- aggregate

def ratio(numerator: int, denominator: int, complete: bool) -> dict:
    value = round(numerator / denominator, 6) if complete and denominator else None
    return {'value': value, 'numerator': numerator, 'denominator': denominator}


def arm_summary(rows: list[dict]) -> dict:
    reviews = [row for row in rows if row['kind'] == 'review']
    assessed = [row['review'] for row in reviews if row['review'] is not None]
    complete = bool(reviews) and len(assessed) == len(reviews)
    tp = sum(item['true_positives'] for item in assessed)
    fp = sum(item['false_positives'] for item in assessed)
    fn = sum(item['false_negatives'] for item in assessed)
    costs = [row['cost_usd'] for row in rows if row['cost_usd'] is not None]
    total, total_status = None, 'none-reported'
    if costs:
        try:
            total = round(sum(costs), 6)
        except OverflowError:
            total = None
        if total is not None and (is_int(total) or math.isfinite(total)):
            total_status = 'reported'
        else:
            total, total_status = None, 'overflow'
    return {
        'trials': len(rows),
        'counts': {outcome: sum(1 for row in rows if row['outcome'] == outcome) for outcome in OUTCOMES},
        'review': {'trials': len(reviews), 'assessed_trials': len(assessed),
                   'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
                   'precision': ratio(tp, tp + fp, complete),
                   'recall': ratio(tp, tp + fn, complete)},
        'cost_usd': {'reported_total': total, 'reported_total_status': total_status,
                     'reported_trials': len(costs), 'trials': len(rows)},
    }


def compare_arms(results: list[dict], tasks: list[dict], trials: int) -> tuple[list[dict], list[str]]:
    regressions, undetermined = [], []
    for task in tasks:
        rows = {arm: [row for row in results if row['arm'] == arm and row['task'] == task['id']]
                for arm in ARMS}
        if any(row['outcome'] == 'UNAVAILABLE' for arm in ARMS for row in rows[arm]):
            undetermined.append(task['id'])
            continue
        passes = {arm: sum(1 for row in rows[arm] if row['outcome'] == 'PASS') for arm in ARMS}
        if passes['candidate'] < passes['baseline']:
            regressions.append({'task': task['id'], 'baseline_passes': passes['baseline'],
                                'candidate_passes': passes['candidate'], 'trials': trials})
    return regressions, undetermined


# ---------------------------------------------------------------- run

def usage(code: str) -> int:
    print(json.dumps({'outcome': 'usage-error', 'reasons': [code]}), file=sys.stderr)
    return 2


def resolve_adapter_executable(adapter: dict) -> tuple[Path | None, str | None, str | None]:
    try:
        executable = evidence.resolve_executable(adapter['argv'][0], adapter['dir'])
    except evidence.Refusal as refusal:
        return None, None, refusal.code
    digest = file_sha(executable)
    if digest is None:
        return None, None, 'executable-unreadable'
    return executable, digest, None


def run_evaluation(args: argparse.Namespace) -> int:
    if not 1 <= args.trials <= MAX_TRIALS:
        return usage('invalid-trials')
    if not 0 < args.timeout <= evidence.MAX_TIMEOUT:
        return usage('invalid-timeout')
    try:
        corpus_path = Path(args.corpus).absolute() if args.corpus else DEFAULT_CORPUS
        corpus, corpus_sha = load_corpus(corpus_path)
        tasks = select_tasks(corpus, args.task)
        arms = {'baseline': load_instructions(args.baseline),
                'candidate': load_instructions(args.candidate)}
        adapter = load_adapter(Path(args.adapter).absolute())
        out_dir = create_out_dir(args.out_dir, [SKILL_ROOT, corpus_path.resolve().parent])
    except Invalid as invalid:
        return usage(invalid.code)
    except FileExistsError:
        return usage('out-dir-exists')
    except OSError:
        return usage('out-dir-uncreatable')

    started_at = evidence.utc_now()
    python = Path(sys.executable).resolve()
    sources = {'corpus': corpus_path, 'baseline': Path(arms['baseline']['path']),
               'candidate': Path(arms['candidate']['path']), 'adapter': Path(adapter['path']),
               'harness': SCRIPT_PATH, 'evidence': EVIDENCE_PATH}
    initial = {'corpus': corpus_sha, 'baseline': arms['baseline']['sha256'],
               'candidate': arms['candidate']['sha256'], 'adapter': adapter['config_sha256'],
               'harness': file_sha(SCRIPT_PATH), 'evidence': file_sha(EVIDENCE_PATH)}
    executable, executable_sha, executable_error = resolve_adapter_executable(adapter)
    ctx = RunContext(out_dir, adapter, executable, executable_sha, executable_error, args.timeout)

    results = [run_trial(ctx, arm, arms[arm], task, trial)
               for task in tasks for trial in range(1, args.trials + 1) for arm in ARMS]

    input_kinds = [input_drift(item) for item in adapter['input_files']]
    source_changes = sorted(
        [name for name, path in sources.items() if file_sha(path) != initial[name]]
        + (['adapter-config-alias'] if config_drift(adapter) == 'alias' else [])
        + [f'adapter-input-{idx}' + ('-alias' if kind == 'alias' else '')
           for idx, kind in enumerate(input_kinds) if kind])
    summaries = {arm: arm_summary([row for row in results if row['arm'] == arm]) for arm in ARMS}
    regressions, undetermined = compare_arms(results, tasks, args.trials)
    unavailable = sum(summaries[arm]['counts']['UNAVAILABLE'] for arm in ARMS)
    candidate_failed = summaries['candidate']['counts']['FAIL']
    reasons = [f'source-changed:{name}' for name in source_changes]
    reasons += ['unavailable-trials'] if unavailable else []
    reasons += ['candidate-failed-acceptance'] if candidate_failed else []
    reasons += ['regression'] if regressions else []
    # A known acceptance failure wins; missing evidence and source drift stay in reasons.
    if candidate_failed or regressions:
        outcome = 'FAIL'
    elif unavailable or source_changes:
        outcome = 'INCOMPLETE'
    else:
        outcome = 'PASS'

    harness_digest = hashlib.sha256(json.dumps(
        {'harness': initial['harness'], 'evidence': initial['evidence'], 'corpus': corpus_sha},
        sort_keys=True).encode()).hexdigest()
    result = {
        'schema': RESULT_SCHEMA, 'started_at': started_at, 'ended_at': evidence.utc_now(),
        'outcome': outcome, 'reasons': reasons,
        'harness': {'script': str(SCRIPT_PATH), 'script_sha256': initial['harness'],
                    'evidence_sha256': initial['evidence'], 'corpus': str(corpus_path),
                    'corpus_sha256': corpus_sha, 'digest': harness_digest,
                    'grader_timeout_seconds': GRADER_TIMEOUT,
                    'python': {'implementation': sys.implementation.name,
                               'version': platform.python_version(),
                               'executable': str(python), 'executable_sha256': file_sha(python)}},
        'instructions': {arm: {key: arms[arm][key] for key in ('path', 'sha256', 'bytes')}
                         for arm in ARMS},
        'adapter': {'config': adapter['path'], 'config_resolved': adapter['resolved_path'],
                    'config_sha256': adapter['config_sha256'],
                    'name': adapter['name'], 'version': adapter['version'],
                    'requested_model': adapter['requested_model'], 'argv': adapter['argv'],
                    'resolved_executable': str(executable) if executable else None,
                    'executable_sha256': executable_sha, 'executable_error': executable_error,
                    'input_files': adapter['input_files'],
                    'payload_identity': ('declared-input-files' if adapter['input_files']
                                         else 'unknown')},
        'config': {'trials': args.trials, 'timeout_seconds': args.timeout,
                   'tasks': [task['id'] for task in tasks]},
        'source_changes': source_changes,
        'results': results,
        'aggregate': summaries,
        'regressions': regressions,
        'regressions_undetermined': undetermined,
        'limitations': list(LIMITATIONS),
    }
    evidence.write_receipt(out_dir, result)
    print(json.dumps({'outcome': outcome, 'reasons': reasons, 'outDir': str(out_dir)}))
    return {'PASS': 0, 'FAIL': 1}.get(outcome, 3)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    actions = root.add_subparsers(dest='action', required=True)
    run = actions.add_parser('run', help='evaluate baseline and candidate instructions')
    run.add_argument('--baseline', required=True, help='baseline instruction file')
    run.add_argument('--candidate', required=True, help='candidate instruction file')
    run.add_argument('--adapter', required=True, help='adapter JSON configuration')
    run.add_argument('--out-dir', required=True, help='new output directory')
    run.add_argument('--trials', type=int, default=1, help=f'trials per task and arm (1-{MAX_TRIALS})')
    run.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT,
                     help='adapter timeout in seconds per trial')
    run.add_argument('--task', action='append', default=None, help='restrict to a task id (repeatable)')
    run.add_argument('--corpus', default=None, help='corpus JSON (default: bundled corpus)')
    return root


def main(argv: list[str] | None = None) -> int:
    return run_evaluation(parser().parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
