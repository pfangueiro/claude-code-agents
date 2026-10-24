"""Offline behavioral checks of the verified-handoff agent evaluator.

Every run drives a local fake adapter (a Python script following a JSON plan) in
disposable directories: no network, provider, account or model is contacted. Tests call
the evaluator through the module-level `agent_eval` alias so mutations.py can substitute
an in-memory defect. Assertions target observable outcomes: genuinely different correct
work passes, wrong or out-of-scope work fails, and broken adapters are UNAVAILABLE rather
than passing or scoring zero. Every comparison run keeps a correct baseline arm as its
positive control.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import sys
import tempfile
import time
from typing import NamedTuple
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / '.claude/skills/verified-handoff'
AGENT_EVAL_PATH = SKILL / 'scripts/agent_eval.py'
EVIDENCE_PATH = SKILL / 'scripts/evidence.py'
CORPUS_PATH = SKILL / 'references/eval-corpus.json'
ARMS = ('baseline', 'candidate')


def load_agent_eval():
    spec = importlib.util.spec_from_file_location('verified_handoff_agent_eval', AGENT_EVAL_PATH)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


agent_eval = load_agent_eval()
CORPUS = json.loads(CORPUS_PATH.read_text(encoding='utf-8'))
TASKS = {task['id']: task for task in CORPUS['tasks']}
TASK_IDS = [task['id'] for task in CORPUS['tasks']]


# ---------------------------------------------------------------- fake adapter

FAKE_ADAPTER = r'''
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

prompt_path, plan_path, trace = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
prompt = prompt_path.read_text(encoding='utf-8')
task = re.search(r'^# Agent evaluation task `([a-z0-9-]+)`', prompt, re.M).group(1)
arm = re.search(r'fake-arm=([a-z]+)', prompt).group(1)
key = arm + '.' + task
counter = trace / (key + '.count')
index = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(index + 1))
steps = json.loads(plan_path.read_text(encoding='utf-8'))[arm][task]
step = steps[min(index, len(steps) - 1)]

cwd = Path.cwd()
entries = {}
for current, dirs, files in os.walk(cwd):
    for name in dirs + files:
        path = Path(current) / name
        kind = 'link' if path.is_symlink() else 'dir' if path.is_dir() else 'file'
        entries[path.relative_to(cwd).as_posix()] = kind
view = {'cwd': str(cwd), 'argv': sys.argv[1:], 'entries': entries}
(trace / f'{key}.{index}.json').write_text(json.dumps(view))
(trace / f'{key}.{index}.prompt').write_text(prompt, encoding='utf-8')

for action in step.get('actions', []):
    target = cwd / action['path']
    op = action['op']
    if op == 'write':
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(action['content'], encoding='utf-8')
    elif op == 'append':
        with open(target, 'a', encoding='utf-8') as handle:
            handle.write(action['content'])
    elif op == 'mkdir':
        target.mkdir()
    elif op == 'symlink':
        os.symlink(action['target'], target)
    elif op == 'remove':
        target.unlink()
    elif op == 'chmod_x':
        target.chmod(target.stat().st_mode | 0o100)
    elif op == 'swap_dir_for_symlink':
        shutil.copytree(target, action['target'])
        shutil.rmtree(target)
        os.symlink(action['target'], target)
    else:
        raise SystemExit('unknown fake adapter action: ' + op)

for seconds, escaped in step.get('descendants', []):
    child = subprocess.Popen([sys.executable, '-I', '-c', f'import time; time.sleep({seconds})'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=escaped)
    with open(trace / 'pids', 'a') as handle:
        handle.write(f'{child.pid} {int(escaped)}\n')

if 'stdout' in step:
    sys.stdout.write(step['stdout'])
elif 'envelope' in step:
    sys.stdout.write(json.dumps(step['envelope']))
else:
    sys.stdout.write(json.dumps({'status': 'success',
                                 'observed_model': step.get('observed_model', 'fake-observed'),
                                 'cost_usd': step.get('cost_usd'), 'response': step['response']}))
sys.stdout.flush()
if step.get('self_signal'):
    os.kill(os.getpid(), signal.SIGTERM)
time.sleep(step.get('sleep', 0))
sys.exit(step.get('exit', 0))
'''

INSTRUCTIONS = 'fake-arm={arm}\nSolve the task exactly as stated and answer with the response protocol.\n'


def write_lab_files(directory: Path, plan, *, executable: str | None = None,
                    requested_model: str | None = 'fake-requested') -> dict:
    """Write the fake adapter, its plan, both instruction arms and the adapter config.

    `plan` may be a callable receiving the file map, for plans that name lab paths.
    """
    directory.mkdir(parents=True)
    trace = directory / 'trace'
    trace.mkdir()
    files = {'dir': directory, 'trace': trace, 'out': directory / 'out',
             'script': directory / 'fake_adapter.py', 'plan': directory / 'plan.json',
             'baseline': directory / 'baseline.md', 'candidate': directory / 'candidate.md',
             'adapter': directory / 'adapter.json'}
    files['script'].write_text(FAKE_ADAPTER, encoding='utf-8')
    for arm in ARMS:
        files[arm].write_text(INSTRUCTIONS.format(arm=arm), encoding='utf-8')
    if callable(plan):
        plan = plan(files)
    files['plan'].write_text(json.dumps(plan), encoding='utf-8')
    argv = [executable or sys.executable, '-I', str(files['script']), '{prompt_file}',
            str(files['plan']), str(trace)]
    files['adapter'].write_text(json.dumps({'argv': argv, 'name': 'fake-offline-adapter', 'version': '1',
                                            'requested_model': requested_model}), encoding='utf-8')
    return files


# ---------------------------------------------------------------- responses

def fixture(task_id: str, rel: str) -> str:
    return TASKS[task_id]['files'][rel]


def replaced(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise AssertionError(f'fixture anchor is not unique: {old!r}')
    return text.replace(old, new)


def edit(path: str, content) -> dict:
    return {'path': path, 'content': content}


def response(files=(), findings=(), diagnosis=None) -> dict:
    return {'files': list(files), 'findings': list(findings), 'diagnosis': diagnosis}


def answer(reply: dict, **extra) -> dict:
    return dict(extra, response=reply)


def steps(responses: dict, **extra) -> dict:
    return {task: answer(reply, **extra) for task, reply in responses.items()}


def build_plan(baseline: dict, candidate: dict) -> dict:
    def normalize(entries):
        return {task: value if isinstance(value, list) else [value] for task, value in entries.items()}
    return {'baseline': normalize(baseline), 'candidate': normalize(candidate)}


NUMBERS_PATH, PAGING_PATH, REPORT_PATH, RATIO_PATH = ('pkg/numbers.py', 'pkg/paging.py',
                                                      'pkg/report.py', 'pkg/ratio.py')

NUMBERS_A = fixture('feature-clamp', NUMBERS_PATH) + '''

def clamp(value, low, high):
    """Return value limited to the inclusive range [low, high]."""
    if low > high:
        raise ValueError('low must not exceed high')
    if value < low:
        return low
    if value > high:
        return high
    return value
'''

NUMBERS_B = '''def mean(values):
    total = count = 0
    for item in values:
        total += item
        count += 1
    if count == 0:
        raise ValueError('empty input')
    return total / count


def clamp(value, low, high):
    if high < low:
        raise ValueError('inverted bounds')
    return sorted((low, value, high))[1]
'''

NUMBERS_NO_RAISE = fixture('feature-clamp', NUMBERS_PATH) + '''

def clamp(value, low, high):
    return max(low, min(value, high))
'''

NUMBERS_MEAN_BROKEN = replaced(NUMBERS_A, "raise ValueError('mean requires at least one value')", 'return 0.0')

NUMBERS_TAMPER = ("from pathlib import Path\n"
                  "Path(__file__).with_name('__init__.py').write_text('TAMPERED = True\\n')\n" + NUMBERS_A)

# Correct code that adds an entry, or rewrites the graded file, while it is being graded.
NUMBERS_ADDS_ENTRY = ("from pathlib import Path\n"
                      "Path(__file__).with_name('cache.txt').write_text('cached')\n" + NUMBERS_A)
NUMBERS_SELF_EDIT = ("with open(__file__, 'a', encoding='utf-8') as _handle:\n"
                     "    _handle.write('# touched while graded')\n" + NUMBERS_A)

PAGING_A = replaced(fixture('bug-page-count', PAGING_PATH), '    return total // per_page\n',
                    '    return -(-total // per_page)\n')

PAGING_B = '''"""Pagination helpers."""


def _require_int(name, value, minimum):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def page_count(total, per_page):
    total = _require_int('total', total, 0)
    per_page = _require_int('per_page', per_page, 1)
    return (total + per_page - 1) // per_page


def page_slice(items, page, per_page):
    page = _require_int('page', page, 1)
    per_page = _require_int('per_page', per_page, 1)
    first = (page - 1) * per_page
    return [item for item in items[first:first + per_page]]
'''

PAGING_BOOL_ACCEPTED = replaced(PAGING_A, '    if isinstance(total, bool) or not isinstance(total, int) or total < 0:\n',
                                '    if not isinstance(total, int) or total < 0:\n')
PAGING_SLICE_SHIFTED = replaced(PAGING_A, '    start = (page - 1) * per_page\n', '    start = page * per_page\n')

REPORT_A = '''"""Row formatting for the account report."""


def format_record(kind, name, age):
    if kind not in ('user', 'admin'):
        raise ValueError('kind must be user or admin')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('name must be a non-empty string')
    if isinstance(age, bool) or not isinstance(age, int) or age < 0:
        raise ValueError('age must be a non-negative integer')
    return f'{kind}: {name.strip()} ({age})'


def format_user(name, age):
    return format_record('user', name, age)


def format_admin(name, age):
    return format_record('admin', name, age)
'''

REPORT_B = '''"""Row formatting for the account report."""

_LABELS = {'user': 'user', 'admin': 'admin'}


def _clean_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('name must be a non-empty string')
    return name.strip()


def _checked_age(age):
    if type(age) is not int or age < 0:
        raise ValueError('age must be a non-negative integer')
    return age


def format_record(kind, name, age):
    label = _LABELS.get(kind) if isinstance(kind, str) else None
    if label is None:
        raise ValueError('kind must be user or admin')
    return '{}: {} ({})'.format(label, _clean_name(name), _checked_age(age))


def format_user(name, age):
    return format_record('user', name, age)


def format_admin(name, age):
    return format_record('admin', name, age)
'''

# Correct format_record, but the entry points keep their duplicated bodies (no delegation).
REPORT_NOT_DELEGATING = fixture('refactor-report', REPORT_PATH) + '''

def format_record(kind, name, age):
    if kind == 'admin':
        return format_admin(name, age)
    if kind == 'user':
        return format_user(name, age)
    raise ValueError('kind must be user or admin')
'''

REPORT_ANY_KIND = replaced(REPORT_A, "    if kind not in ('user', 'admin'):\n        raise ValueError('kind must be user or admin')\n", '')


def return_line(task_id: str) -> int:
    lines = fixture(task_id, RATIO_PATH).splitlines()
    return next(number for number, line in enumerate(lines, 1) if line.lstrip().startswith('return '))


DEFECT_LINE = return_line('review-defective-floor')
CLEAN_LINE = return_line('review-clean-floor')

# Review fixtures outside the single-return integer-witness protocol (custom corpus copies only).
RATIO_ZERO_RETURNS = ('def bucket(numerator, denominator):\n'
                      '    if denominator == 0:\n'
                      '        return 0\n'
                      '    return numerator // denominator\n')
DEAD_RETURN_LINE, LIVE_RETURN_LINE = 3, 4
RATIO_DEAD_RETURN = ('def bucket(numerator, denominator):\n'
                     '    if False:\n'
                     '        return numerator // denominator\n'
                     '    return int(numerator / denominator)\n')
# The visible bucket body is correct, but a module-level rebinding makes bucket a truncating helper.
REBOUND_BUCKET_RETURN_LINE = 6
RATIO_REBOUND = ('def _truncating(numerator, denominator):\n'
                 '    return int(numerator / denominator)\n'
                 '\n'
                 '\n'
                 'def bucket(numerator, denominator):\n'
                 '    return numerator // denominator\n'
                 '\n'
                 '\n'
                 'bucket = _truncating\n')


def finding(args, expected, actual, line=DEFECT_LINE,
            description='int() truncates toward zero, so a negative quotient is rounded up, not floored.'):
    return {'path': RATIO_PATH, 'line': line, 'args': list(args), 'expected': expected, 'actual': actual,
            'description': description}


SUPPORT_A = {'outcome': 'INCOMPLETE', 'cause': 'environment', 'missing_evidence': ['behavioral-tests'],
             'remaining_unknown': 'Whether the tests pass under the required Python 3.12 runtime is unknown.'}
SUPPORT_B = {'outcome': 'INCOMPLETE', 'cause': 'environment',
             'missing_evidence': ['runtime-version', 'behavioral-tests'],
             'remaining_unknown': 'No Python 3.12 interpreter was available, so behavior on the required '
                                  'runtime is unverified.'}

RESPONSES_A = {
    'feature-clamp': response(files=[edit(NUMBERS_PATH, NUMBERS_A)]),
    'bug-page-count': response(files=[edit(PAGING_PATH, PAGING_A)]),
    'refactor-report': response(files=[edit(REPORT_PATH, REPORT_A)]),
    'review-defective-floor': response(findings=[finding([-7, 2], -4, -3)]),
    'review-clean-floor': response(),
    'support-missing-runtime': response(diagnosis=SUPPORT_A),
}
RESPONSES_B = {
    'feature-clamp': response(files=[edit(NUMBERS_PATH, NUMBERS_B)]),
    'bug-page-count': response(files=[edit(PAGING_PATH, PAGING_B)]),
    'refactor-report': response(files=[edit(REPORT_PATH, REPORT_B)]),
    'review-defective-floor': response(findings=[finding(
        [7, -2], -4, -3, description='Truncation differs from floor division whenever the operand signs differ.')]),
    'review-clean-floor': response(),
    'support-missing-runtime': response(diagnosis=SUPPORT_B),
}
WRONG_CANDIDATE = dict(RESPONSES_B, **{'feature-clamp': response(files=[edit(NUMBERS_PATH, NUMBERS_NO_RAISE)])})


# ---------------------------------------------------------------- running

class Run(NamedTuple):
    code: int
    result: dict | None
    stdout: str
    stderr: str
    files: dict

    def rows(self, arm: str, task: str | None = None) -> list[dict]:
        return [row for row in self.result['results']
                if row['arm'] == arm and (task is None or row['task'] == task)]

    def outcomes(self, arm: str, task: str | None = None) -> list[str]:
        return [row['outcome'] for row in self.rows(arm, task)]

    def usage_reasons(self) -> list[str]:
        report = json.loads(self.stderr)
        assert report['outcome'] == 'usage-error', report
        return report['reasons']


def evaluate(files: dict, *, tasks=(), trials=1, timeout=30.0, corpus=None, out=None) -> Run:
    """Call the module-level agent_eval alias in-process (mutations.py may replace it)."""
    out = Path(out) if out is not None else files['out']
    argv = ['run', '--baseline', str(files['baseline']), '--candidate', str(files['candidate']),
            '--adapter', str(files['adapter']), '--out-dir', str(out), '--trials', str(trials),
            '--timeout', str(timeout)]
    for task in tasks:
        argv += ['--task', task]
    if corpus is not None:
        argv += ['--corpus', str(corpus)]
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = agent_eval.main(argv)
    receipt = out / 'result.json'
    result = json.loads(receipt.read_text(encoding='utf-8')) if receipt.is_file() else None
    return Run(code, result, stdout.getvalue(), stderr.getvalue(), files)


class Lab:
    """Disposable root holding one directory per evaluator run."""

    def __init__(self, case: unittest.TestCase):
        tmp = tempfile.TemporaryDirectory(prefix='agent-eval-lab-')
        case.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.count = 0
        case.addCleanup(self.stop_descendants)

    def prepare(self, plan, **options) -> dict:
        self.count += 1
        return write_lab_files(self.root / f'run-{self.count}', plan, **options)

    def run(self, plan, **options) -> Run:
        return evaluate(self.prepare(plan), **options)

    def stop_descendants(self) -> None:
        """Defensive cleanup of exactly the pids the fake adapter recorded."""
        for record in self.root.rglob('pids'):
            for pid, _escaped in read_pids(record):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(pid, signal.SIGKILL)


def read_pids(path: Path) -> list[tuple[int, bool]]:
    if not path.is_file():
        return []
    return [(int(pid), escaped == '1') for pid, escaped in
            (line.split() for line in path.read_text().splitlines() if line.strip())]


def launches(trace: Path) -> int:
    return sum(int(path.read_text()) for path in trace.glob('*.count'))


def solver_views(trace: Path):
    """Yield (arm, task, index, workspace view, prompt) for every adapter launch."""
    for meta in sorted(trace.glob('*.json')):
        arm, task, index = meta.name[:-len('.json')].split('.')
        prompt = (trace / f'{arm}.{task}.{index}.prompt').read_text(encoding='utf-8')
        yield arm, task, int(index), json.loads(meta.read_text(encoding='utf-8')), prompt


def sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256(path) for path in sorted(root.rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts}


def write_corpus(directory: Path, data) -> Path:
    directory.mkdir(parents=True)
    path = directory / 'corpus.json'
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
    return path


def task_named(data: dict, task_id: str) -> dict:
    return next(task for task in data['tasks'] if task['id'] == task_id)


def declare_inputs(files: dict, inputs) -> dict:
    """Add the optional `input_files` declaration to a lab's adapter config."""
    config = json.loads(files['adapter'].read_text(encoding='utf-8'))
    files['adapter'].write_text(json.dumps(dict(config, input_files=inputs)), encoding='utf-8')
    return files


def process_running(pid: int) -> bool:
    """True for a live process; an unreaped zombie counts as exited."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat_file = Path(f'/proc/{pid}/stat')
    if stat_file.exists():
        return stat_file.read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


def wait_until(predicate, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


# ---------------------------------------------------------------- installed-resource helpers

INSTALLED_TASKS = ('feature-clamp', 'review-defective-floor', 'support-missing-runtime')


def run_installed_evaluator(script: Path, directory: Path, candidate: dict, env=None):
    """Run an installed agent_eval.py offline from an unrelated cwd; return (process, result)."""
    files = write_lab_files(directory, build_plan(steps(RESPONSES_A), steps(candidate)))
    cwd = directory / 'unrelated-cwd'
    cwd.mkdir()
    argv = [sys.executable, str(script), 'run', '--baseline', str(files['baseline']),
            '--candidate', str(files['candidate']), '--adapter', str(files['adapter']),
            '--out-dir', str(files['out']), '--timeout', '60']
    for task in INSTALLED_TASKS:
        argv += ['--task', task]
    proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    receipt = files['out'] / 'result.json'
    return proc, (json.loads(receipt.read_text(encoding='utf-8')) if receipt.is_file() else None)


def check_installed_evaluator(case: unittest.TestCase, script: Path, directory: Path, env=None) -> None:
    """An installed evaluator grades for real: correct work passes, wrong work fails, bytes stay put."""
    skill = script.resolve().parents[1]
    before = tree_hashes(skill)
    proc, result = run_installed_evaluator(script, directory / 'correct', RESPONSES_B, env)
    case.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
    case.assertEqual(result['outcome'], 'PASS')
    case.assertEqual(result['harness']['script'], str(script.resolve()))
    case.assertEqual(result['harness']['script_sha256'], sha256(script))
    case.assertEqual(result['harness']['corpus'], str(skill / 'references/eval-corpus.json'))
    case.assertEqual(result['config']['tasks'], list(INSTALLED_TASKS))
    case.assertEqual({row['outcome'] for row in result['results']}, {'PASS'})
    proc, result = run_installed_evaluator(script, directory / 'wrong', WRONG_CANDIDATE, env)
    case.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
    case.assertEqual(result['outcome'], 'FAIL')
    case.assertEqual({(row['arm'], row['task']) for row in result['results'] if row['outcome'] != 'PASS'},
                     {('candidate', 'feature-clamp')})
    case.assertEqual(tree_hashes(skill), before)


# ---------------------------------------------------------------- tests

def parent_dirs(rel: str) -> set[str]:
    return {parent.as_posix() for parent in PurePosixPath(rel).parents if str(parent) != '.'}


class EvalCase(unittest.TestCase):
    def against_baseline(self, task: str, candidate, *, timeout: float = 30.0) -> Run:
        """One trial per candidate step on `task`; the correct baseline arm is the positive control."""
        candidate = candidate if isinstance(candidate, list) else [candidate]
        run = Lab(self).run(build_plan({task: answer(RESPONSES_A[task])}, {task: candidate}),
                            tasks=[task], trials=len(candidate), timeout=timeout)
        self.assertIsNotNone(run.result, run.stderr)
        self.assertEqual(run.outcomes('baseline'), ['PASS'] * len(candidate), 'positive control')
        return run

    def assertSolverInputsPublic(self, run: Run) -> None:
        forbidden = [*agent_eval.GRADERS, agent_eval.SENTINEL, 'REVIEW_GRID', 'spec_', 'result.json',
                     str(run.files['out']), str(run.files['dir']), str(AGENT_EVAL_PATH.parent)]
        views = list(solver_views(run.files['trace']))
        self.assertEqual(len(views), len(run.result['results']))
        for arm, task, index, view, prompt in views:
            with self.subTest(arm=arm, task=task, trial=index):
                expected = set(TASKS[task]['files']) | {agent_eval.PROMPT_NAME}
                entries = view['entries']
                self.assertEqual({rel for rel, kind in entries.items() if kind == 'file'}, expected)
                self.assertEqual({rel for rel, kind in entries.items() if kind != 'file'},
                                 set().union(*(parent_dirs(rel) for rel in expected)))
                self.assertTrue(all(kind != 'link' for kind in entries.values()))
                workspace = Path(view['cwd'])
                self.assertEqual(view['argv'][0], str(workspace / agent_eval.PROMPT_NAME))
                self.assertFalse(workspace.exists(), 'solver workspace must be removed after the trial')
                for root in (run.files['dir'], SKILL):
                    self.assertFalse(workspace.is_relative_to(root))
                other = 'candidate' if arm == 'baseline' else 'baseline'
                self.assertIn(f'fake-arm={arm}', prompt)
                self.assertNotIn(f'fake-arm={other}', prompt)
                self.assertIn(TASKS[task]['statement'], prompt)
                for secret in forbidden:
                    self.assertNotIn(secret, prompt)


class CorpusEndToEnd(EvalCase):
    def test_two_distinct_correct_arms_pass_all_six_cases(self):
        self.assertEqual(sorted(task['kind'] for task in CORPUS['tasks']),
                         ['bug-repair', 'feature', 'refactor', 'review', 'review', 'support'])
        lab = Lab(self)
        files = lab.prepare(build_plan(steps(RESPONSES_A, observed_model='fake-observed-a'),
                                       steps(RESPONSES_B, observed_model='fake-observed-b', cost_usd=0.25)))
        inputs = {name: files[name] for name in ('baseline', 'candidate', 'adapter', 'script', 'plan')}
        inputs.update(corpus=CORPUS_PATH, harness=AGENT_EVAL_PATH, evidence=EVIDENCE_PATH)
        before = {name: sha256(path) for name, path in inputs.items()}
        run = evaluate(files)
        self.assertEqual(run.code, 0, run.stdout + run.stderr)
        result = run.result
        self.assertEqual((result['outcome'], result['reasons']), ('PASS', []))
        self.assertEqual(json.loads(run.stdout)['outcome'], 'PASS')
        self.assertEqual(result['config']['tasks'], TASK_IDS)
        self.assertEqual({(row['arm'], row['task']): row['outcome'] for row in result['results']},
                         {(arm, task): 'PASS' for arm in ARMS for task in TASK_IDS})
        for row in result['results']:
            with self.subTest(arm=row['arm'], task=row['task']):
                self.assertEqual(row['requested_model'], 'fake-requested')
                baseline = row['arm'] == 'baseline'
                self.assertEqual(row['observed_model'], 'fake-observed-a' if baseline else 'fake-observed-b')
                self.assertEqual(row['cost_usd'], None if baseline else 0.25)

        harness = result['harness']
        self.assertEqual(harness['script'], str(AGENT_EVAL_PATH.resolve()))
        self.assertEqual(harness['script_sha256'], sha256(AGENT_EVAL_PATH))
        self.assertEqual(harness['evidence_sha256'], sha256(EVIDENCE_PATH))
        self.assertEqual((harness['corpus'], harness['corpus_sha256']), (str(CORPUS_PATH.resolve()), sha256(CORPUS_PATH)))
        for arm in ARMS:
            self.assertEqual(result['instructions'][arm], {'path': str(files[arm]), 'sha256': sha256(files[arm]),
                                                           'bytes': files[arm].stat().st_size})
        adapter = result['adapter']
        self.assertEqual((adapter['config'], adapter['config_sha256'], adapter['requested_model']),
                         (str(files['adapter']), sha256(files['adapter']), 'fake-requested'))
        self.assertEqual(adapter['resolved_executable'], str(Path(sys.executable).resolve()))
        self.assertIsNone(adapter['executable_error'])

        summaries = result['aggregate']
        for arm in ARMS:
            self.assertEqual(summaries[arm]['counts'], {'PASS': 6, 'FAIL': 0, 'UNAVAILABLE': 0})
            review = summaries[arm]['review']
            self.assertEqual((review['true_positives'], review['false_positives'], review['false_negatives']), (1, 0, 0))
            self.assertEqual((review['precision']['value'], review['recall']['value']), (1.0, 1.0))
        # Unreported cost stays unknown (null, status none-reported), never a zero total.
        self.assertEqual(summaries['baseline']['cost_usd'],
                         {'reported_total': None, 'reported_total_status': 'none-reported',
                          'reported_trials': 0, 'trials': 6})
        self.assertEqual(summaries['candidate']['cost_usd'],
                         {'reported_total': 1.5, 'reported_total_status': 'reported',
                          'reported_trials': 6, 'trials': 6})
        self.assertEqual((result['regressions'], result['regressions_undetermined'], result['source_changes']),
                         ([], [], []))
        self.assertEqual({name: sha256(path) for name, path in inputs.items()}, before)
        self.assertSolverInputsPublic(run)

    def test_prompts_carry_no_history_or_other_arm_text(self):
        tasks = ['feature-clamp', 'review-defective-floor']
        candidate = {'feature-clamp': [answer(response(files=[edit(NUMBERS_PATH, NUMBERS_NO_RAISE)])),
                                       answer(RESPONSES_B['feature-clamp'])],
                     'review-defective-floor': [answer(response()), answer(RESPONSES_B['review-defective-floor'])]}
        run = Lab(self).run(build_plan(steps(RESPONSES_A), candidate), tasks=tasks, trials=2)
        self.assertEqual(run.outcomes('candidate'), ['FAIL', 'PASS', 'FAIL', 'PASS'])
        prompts = {(arm, task, index): prompt for arm, task, index, _, prompt in solver_views(run.files['trace'])}
        for task in tasks:
            reference = prompts[('baseline', task, 0)]
            for arm in ARMS:
                for index in (0, 1):
                    with self.subTest(task=task, arm=arm, trial=index):
                        normalized = prompts[(arm, task, index)].replace(f'fake-arm={arm}', 'fake-arm=baseline')
                        self.assertEqual(normalized, reference)
        self.assertSolverInputsPublic(run)


class CodeGrading(EvalCase):
    WRONG = {
        'feature-clamp': (NUMBERS_PATH, [('untouched', fixture('feature-clamp', NUMBERS_PATH)),
                                         ('no error for inverted bounds', NUMBERS_NO_RAISE),
                                         ('existing mean altered', NUMBERS_MEAN_BROKEN)]),
        'bug-page-count': (PAGING_PATH, [('untouched', fixture('bug-page-count', PAGING_PATH)),
                                         ('bool total accepted', PAGING_BOOL_ACCEPTED),
                                         ('page_slice altered', PAGING_SLICE_SHIFTED)]),
        'refactor-report': (REPORT_PATH, [('untouched', fixture('refactor-report', REPORT_PATH)),
                                          ('entry points do not delegate', REPORT_NOT_DELEGATING),
                                          ('unknown kind accepted', REPORT_ANY_KIND)]),
    }

    def test_untouched_wrong_and_regressing_implementations_fail(self):
        for task, (path, variants) in self.WRONG.items():
            with self.subTest(task=task):
                run = self.against_baseline(task, [answer(response(files=[edit(path, content)]))
                                                   for _, content in variants])
                self.assertEqual((run.code, run.result['outcome']), (1, 'FAIL'))
                for (label, _), row in zip(variants, run.rows('candidate')):
                    with self.subTest(task=task, variant=label):
                        self.assertEqual(row['outcome'], 'FAIL')
                        self.assertLess(row['behavior']['passed'], row['behavior']['total'])
                self.assertEqual([item['task'] for item in run.result['regressions']], [task])

    def test_alternative_correct_implementations_pass_side_by_side(self):
        for task in ('feature-clamp', 'bug-page-count', 'refactor-report'):
            with self.subTest(task=task):
                run = self.against_baseline(task, [answer(RESPONSES_B[task]), answer(RESPONSES_A[task])])
                self.assertEqual(run.outcomes('candidate'), ['PASS', 'PASS'])
                self.assertEqual(run.code, 0)

    def test_grader_launch_refusal_is_unavailable_and_executed_defects_still_fail(self):
        real = agent_eval.evidence.supervise

        def refuse_grader(argv, executable, cwd, out_dir, timeout):
            # Only the grader probe launch is refused; the adapter still runs for real.
            if Path(out_dir).name == 'grader':
                raise agent_eval.evidence.Refusal('launch-failed-eperm')
            return real(argv, executable, cwd, out_dir, timeout)
        tasks = ['feature-clamp', 'review-defective-floor']
        files = Lab(self).prepare(build_plan(steps(RESPONSES_A), steps(RESPONSES_B)))
        with mock.patch.object(agent_eval.evidence, 'supervise', refuse_grader):
            refused = evaluate(files, tasks=tasks)
        self.assertIsNotNone(refused.result, refused.stderr)
        self.assertEqual((refused.code, refused.result['outcome']), (3, 'INCOMPLETE'))
        self.assertNotIn('candidate-failed-acceptance', refused.result['reasons'])
        for row in refused.result['results']:
            with self.subTest(arm=row['arm'], task=row['task']):
                self.assertEqual(row['outcome'], 'UNAVAILABLE', row['reasons'])
                self.assertTrue(row['adapter']['launched'])
                self.assertTrue(row['unavailable_reasons'])
                self.assertIsNone(row['review'])
        review = refused.result['aggregate']['candidate']['review']
        self.assertEqual(review['true_positives'], 0)
        self.assertIsNone(review['precision']['value'])
        # Unrefused control: the same correct work passes; executed wrong or unimportable code fails.
        run = self.against_baseline('feature-clamp', [answer(RESPONSES_B['feature-clamp']),
                                                      answer(response(files=[edit(NUMBERS_PATH, NUMBERS_NO_RAISE)])),
                                                      answer(response(files=[edit(NUMBERS_PATH, 'def clamp(:')]))])
        self.assertEqual(run.outcomes('candidate'), ['PASS', 'FAIL', 'FAIL'])
        self.assertEqual(run.rows('candidate')[2]['reasons'], ['module-import-failed'])

    def test_incomplete_grader_supervision_is_unavailable(self):
        # Inert supervise mock: nothing is launched; it writes a valid probe payload and returns
        # the supervision record, so only run_probe's admission guard decides the verdict.
        clean = {'launched': True, 'pid': 123, 'timedOut': False,
                 'descendantsObservedAfterExit': False, 'descendantsOutlivedDeadline': False,
                 'signalsSent': [], 'groupEmptyAtReceipt': True, 'exitCode': 0, 'signal': None}
        incomplete = {
            'deadline overrun cleaned up': {'descendantsObservedAfterExit': True,
                                            'descendantsOutlivedDeadline': True,
                                            'signalsSent': ['SIGTERM']},
            'deadline overrun without signals': {'descendantsObservedAfterExit': True,
                                                 'descendantsOutlivedDeadline': True},
            'forced cleanup signals': {'signalsSent': ['SIGTERM']},
        }
        payload = agent_eval.PROBE_MARKER + json.dumps({'results': [{'value': {}}]}) + '\n'

        def probe(record):
            def supervise(argv, executable, cwd, out_dir, timeout):
                (Path(out_dir) / 'stdout.log').write_text(payload, encoding='utf-8')
                return dict(record)
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(agent_eval.evidence, 'supervise', supervise):
                return agent_eval.run_probe(Path(tmp), Path(tmp), 'module', [{}])
        self.assertEqual(probe(clean), {'results': [{'value': {}}]})
        for label, overrides in incomplete.items():
            with self.subTest(case=label):
                with self.assertRaises(agent_eval.ProbeError) as raised:
                    probe({**clean, **overrides})
                self.assertEqual(raised.exception.code, 'probe-did-not-complete')


class ReviewGrading(EvalCase):
    def test_defect_witness_is_true_positive_and_silence_is_false_negative(self):
        run = self.against_baseline('review-defective-floor', [answer(RESPONSES_B['review-defective-floor']),
                                                               answer(response())])
        witnessed, silent = run.rows('candidate')
        self.assertEqual(witnessed['outcome'], 'PASS')
        self.assertEqual((witnessed['review']['true_positives'], witnessed['review']['false_negatives']), (1, 0))
        self.assertEqual(silent['outcome'], 'FAIL')
        self.assertEqual((silent['review']['true_positives'], silent['review']['false_negatives']), (0, 1))
        self.assertTrue(silent['review']['defective'])

    def test_false_positive_on_clean_review_fails(self):
        variants = [answer(response(findings=[finding([7, 2], 3, 3, line=CLEAN_LINE)])),
                    answer(response(findings=[finding([7, 2], 3, 4, line=CLEAN_LINE)])),
                    answer(response(files=[edit(RATIO_PATH, fixture('review-clean-floor', RATIO_PATH))]))]
        run = self.against_baseline('review-clean-floor', variants)
        self.assertEqual(run.outcomes('candidate'), ['FAIL'] * 3)
        for row in run.rows('candidate')[:2]:
            self.assertEqual(row['review']['false_positives'], 1)
            self.assertFalse(row['review']['defective'])
        self.assertIsNone(run.rows('candidate')[2]['review'])

    def test_fabricated_witness_is_not_a_true_positive(self):
        # Executing bucket(-7, 2) returns -3; claiming it returns -4 is a fabricated witness.
        run = self.against_baseline('review-defective-floor', answer(response(findings=[finding([-7, 2], -4, -4)])))
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'FAIL')
        self.assertEqual(row['review']['true_positives'], 0)

    def test_wrong_line_or_non_witness_is_not_a_true_positive(self):
        variants = [finding([-7, 2], -4, -3, line=DEFECT_LINE - 2),  # the zero-check statement
                    finding([6, 2], 3, 3),                           # exact division: no disagreement
                    finding([-7, 2], -3, -3)]                        # expected is truncation, not floor
        run = self.against_baseline('review-defective-floor', [answer(response(findings=[item])) for item in variants])
        for row in run.rows('candidate'):
            self.assertEqual(row['outcome'], 'FAIL')
            self.assertEqual((row['review']['true_positives'], row['review']['false_negatives']), (0, 1))

    def test_malformed_findings_on_clean_review_are_not_clean(self):
        variants = [{'files': [], 'findings': value, 'diagnosis': None} for value in (None, 'none', {})]
        run = self.against_baseline('review-clean-floor', [answer(item) for item in variants])
        for row in run.rows('candidate'):
            self.assertEqual(row['outcome'], 'FAIL')
            self.assertIsNone(row['review'])

    def test_malformed_finding_evidence_is_not_clean(self):
        good = finding([-7, 2], -4, -3)
        malformed = [{key: value for key, value in good.items() if key != 'args'},
                     {key: value for key, value in good.items() if key != 'description'},
                     dict(good, args=[True, 2]), dict(good, args=[1, 0]), dict(good, args=[-7, 2, 1]),
                     dict(good, args=[10 ** 7, 2]), dict(good, expected=-4.0), dict(good, actual='-3'),
                     dict(good, line=0), dict(good, line=True), dict(good, description=''),
                     dict(good, severity='high'), dict(good, path='../pkg/ratio.py')]
        candidate = [answer(response(findings=[item])) for item in malformed]
        tasks = ['review-defective-floor', 'review-clean-floor']
        run = Lab(self).run(build_plan(steps(RESPONSES_A), {task: candidate for task in tasks}),
                            tasks=tasks, trials=len(malformed))
        self.assertEqual(run.outcomes('baseline'), ['PASS'] * 2 * len(malformed), 'positive control')
        for task in tasks:
            for item, row in zip(malformed, run.rows('candidate', task)):
                with self.subTest(task=task, finding=item):
                    self.assertEqual(row['outcome'], 'FAIL')
                    self.assertIsNone(row['review'])

    def test_fixtures_outside_the_single_return_witness_protocol_are_not_credited(self):
        # An integer witness cannot express a zero-denominator return value or say which of
        # several returns is live, so such fixtures yield neither a clean review nor a TP.
        data = copy.deepcopy(CORPUS)
        task_named(data, 'review-clean-floor')['files'][RATIO_PATH] = RATIO_ZERO_RETURNS
        task_named(data, 'review-defective-floor')['files'][RATIO_PATH] = RATIO_DEAD_RETURN
        lab = Lab(self)
        corpus = write_corpus(lab.root / 'corpus', data)
        tasks = ['review-clean-floor', 'review-defective-floor']
        baseline = {'review-clean-floor': answer(response()),
                    'review-defective-floor': answer(response(findings=[finding([-7, 2], -4, -3,
                                                                                line=LIVE_RETURN_LINE)]))}
        candidate = {'review-clean-floor': answer(response()),
                     'review-defective-floor': answer(response(findings=[finding([-7, 2], -4, -3,
                                                                                 line=DEAD_RETURN_LINE)]))}
        run = evaluate(lab.prepare(build_plan(baseline, candidate)), tasks=tasks, corpus=corpus)
        self.assertIsNotNone(run.result, run.stderr)
        for row in run.result['results']:
            with self.subTest(arm=row['arm'], task=row['task']):
                self.assertEqual(row['outcome'], 'UNAVAILABLE', row['reasons'])
                self.assertTrue(row['unavailable_reasons'])
                self.assertTrue(row['review'] is None or row['review']['true_positives'] == 0, row['review'])
        for arm in ARMS:
            review = run.result['aggregate'][arm]['review']
            self.assertEqual(review['true_positives'], 0)
            self.assertIsNone(review['precision']['value'])
        self.assertEqual((run.code, run.result['outcome']), (3, 'INCOMPLETE'))

    def test_module_level_rebinding_of_the_reviewed_function_is_not_credited(self):
        # bucket(-7, 2) really returns -3, but from _truncating, not from the line the finding
        # names; crediting it would locate the defect in correct code. The bundled clean task
        # in the same run is the positive control.
        data = copy.deepcopy(CORPUS)
        task_named(data, 'review-defective-floor')['files'][RATIO_PATH] = RATIO_REBOUND
        lab = Lab(self)
        corpus = write_corpus(lab.root / 'corpus', data)
        located = answer(response(findings=[finding([-7, 2], -4, -3, line=REBOUND_BUCKET_RETURN_LINE)]))
        plan = {'review-clean-floor': answer(response()), 'review-defective-floor': located}
        run = evaluate(lab.prepare(build_plan(plan, plan)),
                       tasks=['review-clean-floor', 'review-defective-floor'], corpus=corpus)
        self.assertIsNotNone(run.result, run.stderr)
        for arm in ARMS:
            with self.subTest(arm=arm):
                self.assertEqual(run.outcomes(arm, 'review-clean-floor'), ['PASS'], 'positive control')
                row, = run.rows(arm, 'review-defective-floor')
                self.assertEqual(row['outcome'], 'UNAVAILABLE', row['reasons'])
                self.assertTrue(row['unavailable_reasons'])
                self.assertTrue(row['review'] is None or row['review']['true_positives'] == 0, row['review'])
                review = run.result['aggregate'][arm]['review']
                self.assertEqual(review['true_positives'], 0)
                self.assertIsNone(review['precision']['value'])
        self.assertEqual((run.code, run.result['outcome']), (3, 'INCOMPLETE'))


class SupportDiagnosis(EvalCase):
    def test_missing_required_runtime_is_incomplete_environment(self):
        def diagnosis(**changes):
            return answer(response(diagnosis=dict(SUPPORT_A, **changes)))
        wrong = [diagnosis(outcome='FAIL', cause='repository'),           # reported as a code failure
                 diagnosis(outcome='PASS', cause='none', missing_evidence=[]),  # healthy zero
                 diagnosis(cause='repository'),
                 diagnosis(missing_evidence=[]),
                 diagnosis(missing_evidence=['behavioral-tests', 'static-diff-check']),
                 diagnosis(missing_evidence=['behavioral-tests', 'compile']),
                 diagnosis(remaining_unknown='   '),
                 answer(response()),
                 answer(response(files=[edit('pkg/clock.py', fixture('support-missing-runtime', 'pkg/clock.py'))],
                                 diagnosis=SUPPORT_A))]
        run = self.against_baseline('support-missing-runtime', [answer(RESPONSES_B['support-missing-runtime'])] + wrong)
        self.assertEqual(run.outcomes('candidate'), ['PASS'] + ['FAIL'] * len(wrong))
        self.assertEqual((run.code, run.result['outcome']), (1, 'FAIL'))


class Aggregation(EvalCase):
    def test_review_precision_and_recall_from_witnessed_findings(self):
        tasks = ['review-defective-floor', 'review-clean-floor']
        candidate = {'review-defective-floor': answer(response()),
                     'review-clean-floor': answer(response(findings=[finding([7, 2], 3, 3, line=CLEAN_LINE)]))}
        run = Lab(self).run(build_plan(steps(RESPONSES_A), candidate), tasks=tasks)
        summaries = run.result['aggregate']
        expected = {'baseline': (1, 0, 0, 1.0, 1.0), 'candidate': (0, 1, 1, 0.0, 0.0)}
        for arm, values in expected.items():
            review = summaries[arm]['review']
            self.assertEqual((review['true_positives'], review['false_positives'], review['false_negatives'],
                              review['precision']['value'], review['recall']['value']), values)
        self.assertEqual((run.code, run.result['outcome']), (1, 'FAIL'))
        self.assertEqual(sorted(item['task'] for item in run.result['regressions']), sorted(tasks))

    def test_repeated_trials_count_every_regression(self):
        candidate = [answer(RESPONSES_A['feature-clamp']),
                     answer(response(files=[edit(NUMBERS_PATH, NUMBERS_NO_RAISE)])),
                     answer(RESPONSES_B['feature-clamp'])]
        run = self.against_baseline('feature-clamp', candidate)
        self.assertEqual([row['trial'] for row in run.rows('candidate')], [1, 2, 3])
        self.assertEqual(run.result['aggregate']['candidate']['counts'], {'PASS': 2, 'FAIL': 1, 'UNAVAILABLE': 0})
        self.assertEqual(run.result['regressions'], [{'task': 'feature-clamp', 'baseline_passes': 3,
                                                      'candidate_passes': 2, 'trials': 3}])
        self.assertEqual((run.code, run.result['outcome']), (1, 'FAIL'))

    def test_pass_totals_do_not_cancel_a_per_task_regression(self):
        tasks = ['feature-clamp', 'bug-page-count']
        baseline = {'feature-clamp': answer(RESPONSES_A['feature-clamp']),
                    'bug-page-count': answer(response(files=[edit(PAGING_PATH, fixture('bug-page-count', PAGING_PATH))]))}
        candidate = {'feature-clamp': answer(response(files=[edit(NUMBERS_PATH, NUMBERS_NO_RAISE)])),
                     'bug-page-count': answer(RESPONSES_A['bug-page-count'])}
        run = Lab(self).run(build_plan(baseline, candidate), tasks=tasks)
        summaries = run.result['aggregate']
        self.assertEqual(summaries['baseline']['counts']['PASS'], summaries['candidate']['counts']['PASS'])
        self.assertEqual([item['task'] for item in run.result['regressions']], ['feature-clamp'])
        self.assertEqual((run.code, run.result['outcome']), (1, 'FAIL'))
        self.assertIn('candidate-failed-acceptance', run.result['reasons'])

    def test_known_candidate_failure_stays_visible_beside_unavailable_trials(self):
        tasks = ['feature-clamp', 'review-defective-floor']
        baseline = {'feature-clamp': answer(RESPONSES_A['feature-clamp']),
                    'review-defective-floor': answer(RESPONSES_A['review-defective-floor'], exit=3)}
        candidate = {'feature-clamp': answer(response(files=[edit(NUMBERS_PATH, NUMBERS_NO_RAISE)])),
                     'review-defective-floor': answer(RESPONSES_A['review-defective-floor'])}
        run = Lab(self).run(build_plan(baseline, candidate), tasks=tasks)
        result = run.result
        # A known candidate failure wins; the unavailable baseline trial stays visible.
        self.assertEqual((run.code, result['outcome']), (1, 'FAIL'))
        self.assertIn('unavailable-trials', result['reasons'])
        self.assertIn('candidate-failed-acceptance', result['reasons'])
        self.assertIn('regression', result['reasons'])
        self.assertEqual(result['aggregate']['candidate']['counts'], {'PASS': 1, 'FAIL': 1, 'UNAVAILABLE': 0})
        self.assertEqual(result['aggregate']['baseline']['counts'], {'PASS': 1, 'FAIL': 0, 'UNAVAILABLE': 1})
        self.assertEqual([item['task'] for item in result['regressions']], ['feature-clamp'])
        self.assertEqual(result['regressions_undetermined'], ['review-defective-floor'])
        # An unassessed review trial leaves precision unknown rather than perfect.
        precision = result['aggregate']['baseline']['review']['precision']
        self.assertIsNone(precision['value'])

    def test_reported_cost_total_is_finite_or_unknown(self):
        def costs(*reported):
            rows = [{'kind': 'feature', 'review': None, 'outcome': 'PASS', 'cost_usd': cost} for cost in reported]
            return agent_eval.arm_summary(rows)['cost_usd']
        normal = costs(0.25, None, 0.5)
        self.assertEqual((normal['reported_total'], normal['reported_total_status'], normal['reported_trials'],
                          normal['trials']), (0.75, 'reported', 2, 3))
        unreported = costs(None, None)
        self.assertEqual((unreported['reported_total'], unreported['reported_total_status'],
                          unreported['reported_trials']), (None, 'none-reported', 0))
        # Two individually valid reports whose sum overflows are null with status overflow, never Infinity.
        overflow = costs(1e308, 1e308)
        self.assertEqual((overflow['reported_total'], overflow['reported_total_status'],
                          overflow['reported_trials'], overflow['trials']), (None, 'overflow', 2, 2))
        json.dumps(overflow, allow_nan=False)

    def test_finite_number_check_survives_huge_integers(self):
        for value in (0, 7, -3, 0.25, 1e308, 2 ** 53, 10 ** 300):
            self.assertIs(agent_eval.is_finite_number(value), True, value)
        for value in (True, False, float('inf'), float('-inf'), float('nan'), '1', None):
            self.assertIs(agent_eval.is_finite_number(value), False, value)
        for value in (10 ** 400, -(10 ** 400)):
            # Not representable as a finite float: answered False, never an OverflowError.
            self.assertIs(agent_eval.is_finite_number(value), False, value)


class AdapterLifecycle(EvalCase):
    def test_malformed_or_failed_adapter_output_is_unavailable(self):
        good = RESPONSES_A['feature-clamp']
        body = json.dumps(good)

        def envelope(**changes):
            return dict({'status': 'success', 'observed_model': 'fake-observed', 'cost_usd': None,
                         'response': good}, **changes)
        variants = [
            ('empty stdout', {'stdout': ''}),
            ('not JSON', {'stdout': 'all tests passed'}),
            ('two documents', {'stdout': json.dumps(envelope()) + json.dumps(envelope())}),
            ('duplicate key', {'stdout': '{"status": "success", "status": "success", "observed_model": null, '
                                        '"cost_usd": null, "response": ' + body + '}'}),
            ('NaN cost', {'stdout': '{"status": "success", "observed_model": null, "cost_usd": NaN, '
                                    '"response": ' + body + '}'}),
            ('infinite cost', {'stdout': '{"status": "success", "observed_model": null, "cost_usd": Infinity, '
                                         '"response": ' + body + '}'}),
            ('string cost', {'envelope': envelope(cost_usd='0.1')}),
            ('negative cost', {'envelope': envelope(cost_usd=-1)}),
            ('boolean cost', {'envelope': envelope(cost_usd=True)}),
            ('non-string model', {'envelope': envelope(observed_model=5)}),
            ('unknown status', {'envelope': envelope(status='ok')}),
            ('response not an object', {'envelope': envelope(response=[])}),
            ('unknown field', {'envelope': dict(envelope(), tokens=10)}),
            ('missing field', {'envelope': {k: v for k, v in envelope().items() if k != 'cost_usd'}}),
            ('envelope not an object', {'envelope': [envelope()]}),
            ('reported unavailable', {'envelope': envelope(status='unavailable', observed_model='fake-observed-down')}),
            ('nonzero exit', answer(good, exit=3)),
            ('signalled', answer(good, self_signal=True)),
        ]
        run = self.against_baseline('feature-clamp', [step for _, step in variants])
        for (label, _), row in zip(variants, run.rows('candidate')):
            with self.subTest(variant=label):
                self.assertEqual(row['outcome'], 'UNAVAILABLE')
                self.assertTrue(row['reasons'])
        rows = dict(zip([label for label, _ in variants], run.rows('candidate')))
        self.assertEqual(rows['reported unavailable']['observed_model'], 'fake-observed-down')
        self.assertIn('adapter-signalled', rows['signalled']['reasons'])
        self.assertEqual(run.result['aggregate']['candidate']['counts'],
                         {'PASS': 0, 'FAIL': 0, 'UNAVAILABLE': len(variants)})
        self.assertEqual((run.code, run.result['outcome']), (3, 'INCOMPLETE'))
        self.assertIn('unavailable-trials', run.result['reasons'])
        self.assertNotIn('candidate-failed-acceptance', run.result['reasons'])
        self.assertEqual(run.result['regressions_undetermined'], ['feature-clamp'])

    def test_nonzero_exit_with_success_json_is_unavailable(self):
        run = self.against_baseline('feature-clamp', answer(RESPONSES_A['feature-clamp'], exit=3))
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'UNAVAILABLE')
        self.assertEqual(row['adapter']['exit_code'], 3)
        self.assertEqual((run.code, run.result['outcome']), (3, 'INCOMPLETE'))

    def test_missing_executable_is_unavailable(self):
        lab = Lab(self)
        files = lab.prepare(build_plan(steps(RESPONSES_A), steps(RESPONSES_A)),
                            executable=str(lab.root / 'no-such-adapter'))
        run = evaluate(files, tasks=['feature-clamp', 'support-missing-runtime'])
        self.assertEqual((run.code, run.result['outcome']), (3, 'INCOMPLETE'))
        self.assertEqual(run.result['adapter']['executable_error'], 'executable-not-found')
        self.assertIsNone(run.result['adapter']['resolved_executable'])
        for row in run.result['results']:
            self.assertEqual((row['outcome'], row['reasons']), ('UNAVAILABLE', ['executable-not-found']))
        self.assertEqual(launches(files['trace']), 0)

    def test_timeout_is_unavailable_and_bounded(self):
        timeout = 3.0
        run = self.against_baseline('feature-clamp', answer(RESPONSES_A['feature-clamp'], sleep=60), timeout=timeout)
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'UNAVAILABLE')
        self.assertIn('adapter-timed-out', row['reasons'])
        self.assertTrue(row['adapter']['timed_out'])
        self.assertLess(row['trial_duration_seconds'], timeout + agent_eval.evidence.TERM_GRACE_SECONDS + 10)

    def test_lingering_descendant_is_unavailable_and_only_owned_group_is_signalled(self):
        step = answer(RESPONSES_A['feature-clamp'], descendants=[[60, False], [60, True]])
        run = self.against_baseline('feature-clamp', step, timeout=3.0)
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'UNAVAILABLE')
        self.assertIn('adapter-descendants-alive', row['reasons'])
        self.assertTrue(row['adapter']['descendants_outlived_deadline'])
        pids = read_pids(run.files['trace'] / 'pids')
        owned = [pid for pid, escaped in pids if not escaped]
        foreign = [pid for pid, escaped in pids if escaped]
        self.assertEqual((len(owned), len(foreign)), (1, 1))
        self.assertTrue(wait_until(lambda: not process_running(owned[0])), 'owned descendant survived cleanup')
        # A process in another session is outside the owned group and must not be signalled.
        self.assertTrue(process_running(foreign[0]))

    def test_descendant_exiting_within_deadline_passes(self):
        step = answer(RESPONSES_A['feature-clamp'], descendants=[[0.5, False]])
        run = self.against_baseline('feature-clamp', step, timeout=20.0)
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'PASS', row['reasons'])
        self.assertFalse(row['adapter']['descendants_outlived_deadline'])
        self.assertTrue(row['adapter']['group_empty'])
        (pid, _), = read_pids(run.files['trace'] / 'pids')
        self.assertFalse(process_running(pid))
        self.assertEqual(run.code, 0)


class WorkspaceScope(EvalCase):
    def test_unsafe_response_paths_fail(self):
        correct = edit(NUMBERS_PATH, NUMBERS_A)
        variants = [
            ('parent traversal', [correct, edit('../escape.py', 'x = 1\n')]),
            ('absolute path', [correct, edit('/agent-eval-escape.py', 'x = 1\n')]),
            ('git metadata', [correct, edit('.git/config', '[core]\n')]),
            ('backslash', [edit('pkg\\numbers.py', NUMBERS_A)]),
            ('dot segment', [edit('./pkg/numbers.py', NUMBERS_A)]),
            ('empty segment', [edit('pkg//numbers.py', NUMBERS_A)]),
            ('duplicate path', [correct, correct]),
            ('protected file in response', [correct, edit('pkg/__init__.py', '')]),
            ('unlisted new file', [correct, edit('notes.txt', 'scratch\n')]),
            ('case variant', [edit('PKG/numbers.py', NUMBERS_A)]),
            ('no files', []),
            ('unknown entry field', [dict(correct, mode='0755')]),
            ('non-text content', [edit(NUMBERS_PATH, None)]),
        ]
        run = self.against_baseline('feature-clamp', [answer(response(files=items)) for _, items in variants])
        for (label, _), row in zip(variants, run.rows('candidate')):
            with self.subTest(variant=label):
                self.assertEqual(row['outcome'], 'FAIL')
                self.assertEqual(row['behavior']['total'], 0, 'an invalid response must not be graded')

    def test_direct_protected_file_mutation_fails(self):
        step = answer(RESPONSES_A['feature-clamp'], actions=[{'op': 'append', 'path': 'pkg/__init__.py',
                                                              'content': 'EDITED = True\n'}])
        run = self.against_baseline('feature-clamp', step)
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'FAIL')
        self.assertEqual(row['scope']['protected_changed_by_provider'], ['pkg/__init__.py'])

    def test_prompt_and_protected_tampering_fail(self):
        tampering = [('prompt edited', {'op': 'append', 'path': agent_eval.PROMPT_NAME, 'content': 'done\n'}),
                     ('protected deleted', {'op': 'remove', 'path': 'pkg/__init__.py'}),
                     ('protected made executable', {'op': 'chmod_x', 'path': 'pkg/__init__.py'})]
        run = self.against_baseline('feature-clamp', [answer(RESPONSES_A['feature-clamp'], actions=[action])
                                                      for _, action in tampering])
        for (label, _), row in zip(tampering, run.rows('candidate')):
            with self.subTest(variant=label):
                self.assertEqual(row['outcome'], 'FAIL')
                self.assertTrue(row['scope']['protected_changed_by_provider'])
        # A read-only review task: editing the reviewed file in place is a scope violation.
        review = self.against_baseline('review-clean-floor', answer(response(), actions=[
            {'op': 'append', 'path': RATIO_PATH, 'content': '# reviewed\n'}]))
        row, = review.rows('candidate')
        self.assertEqual(row['outcome'], 'FAIL')
        self.assertEqual(row['scope']['protected_changed_by_provider'], [RATIO_PATH])

    def test_symlinked_protected_parent_fails(self):
        def plan(files):
            swap = {'op': 'swap_dir_for_symlink', 'path': 'pkg', 'target': str(files['dir'] / 'outside-pkg')}
            return build_plan({'feature-clamp': answer(RESPONSES_A['feature-clamp'])},
                              {'feature-clamp': answer(RESPONSES_A['feature-clamp'], actions=[swap])})
        lab = Lab(self)
        run = lab.run(plan, tasks=['feature-clamp'])
        self.assertEqual(run.outcomes('baseline'), ['PASS'], 'positive control')
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'FAIL')
        self.assertIn('pkg/__init__.py', row['scope']['protected_changed_by_provider'])
        # Workspace cleanup removed the link without following it.
        self.assertTrue((run.files['dir'] / 'outside-pkg/__init__.py').is_file())

    def test_extra_workspace_entries_fail(self):
        # Protocol: changing any file outside the allowed list, in the workspace or in the
        # response, fails the task; creating unlisted entries is such a change.
        def plan(files):
            created = [('unlisted file', {'op': 'write', 'path': 'notes.txt', 'content': 'scratch\n'}),
                       ('unlisted directory', {'op': 'mkdir', 'path': 'scratch'}),
                       ('symlink to allowed file', {'op': 'symlink', 'path': 'linked.py', 'target': NUMBERS_PATH}),
                       ('symlink outside', {'op': 'symlink', 'path': 'outside', 'target': str(files['dir'])})]
            self.created = [label for label, _ in created]
            return build_plan({'feature-clamp': answer(RESPONSES_A['feature-clamp'])},
                              {'feature-clamp': [answer(RESPONSES_A['feature-clamp'], actions=[action])
                                                 for _, action in created]})
        run = Lab(self).run(plan, tasks=['feature-clamp'], trials=4)
        self.assertEqual(run.outcomes('baseline'), ['PASS'] * 4, 'positive control')
        for label, row in zip(self.created, run.rows('candidate')):
            with self.subTest(variant=label):
                self.assertEqual(row['outcome'], 'FAIL', row['scope'])

    def test_harmless_allowed_modification_passes(self):
        step = answer(RESPONSES_A['feature-clamp'], actions=[{'op': 'write', 'path': NUMBERS_PATH,
                                                              'content': '# scratch notes\n'}])
        run = self.against_baseline('feature-clamp', step)
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'PASS', row['reasons'])
        self.assertEqual(row['scope']['allowed_changed_in_workspace'], [NUMBERS_PATH])
        self.assertEqual(row['scope']['protected_changed_by_provider'], [])

    def test_workspace_edits_are_not_graded(self):
        # The correct code is written only in the workspace; the returned response is untouched.
        step = answer(response(files=[edit(NUMBERS_PATH, fixture('feature-clamp', NUMBERS_PATH))]),
                      actions=[{'op': 'write', 'path': NUMBERS_PATH, 'content': NUMBERS_A}])
        run = self.against_baseline('feature-clamp', step)
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'FAIL')
        self.assertEqual(row['scope']['allowed_changed_in_workspace'], [NUMBERS_PATH])
        self.assertLess(row['behavior']['passed'], row['behavior']['total'])

    def test_produced_code_tampering_during_grading_fails(self):
        run = self.against_baseline('feature-clamp', answer(response(files=[edit(NUMBERS_PATH, NUMBERS_TAMPER)])))
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'FAIL')
        self.assertEqual(row['scope']['protected_changed_by_grading'], ['pkg/__init__.py'])

    def test_entries_added_or_self_modified_during_grading_fail(self):
        variants = [('entry added', NUMBERS_ADDS_ENTRY, 'grading_extra_entries', ['pkg/cache.txt'],
                     'scope-entry-added-during-grading'),
                    ('graded file rewritten', NUMBERS_SELF_EDIT, 'protected_changed_by_grading', [NUMBERS_PATH],
                     'scope-protected-file-changed-during-grading')]
        run = self.against_baseline('feature-clamp', [answer(response(files=[edit(NUMBERS_PATH, code)]))
                                                      for _, code, _, _, _ in variants])
        for (label, _, key, entries, reason), row in zip(variants, run.rows('candidate')):
            with self.subTest(variant=label):
                self.assertEqual((row['outcome'], row['reasons']), ('FAIL', [reason]))
                self.assertEqual(row['scope'][key], entries)
                # The behavior itself was correct: only the grading-time change fails it.
                self.assertGreater(row['behavior']['total'], 0)
                self.assertEqual(row['behavior']['passed'], row['behavior']['total'])

    def test_scope_violation_stays_fail_when_provider_is_unavailable(self):
        unavailable = {'status': 'unavailable', 'observed_model': None, 'cost_usd': None, 'response': {}}
        protected_edit = {'op': 'append', 'path': 'pkg/__init__.py', 'content': 'EDITED = True\n'}
        variants = [('protected edit, nonzero exit',
                     answer(RESPONSES_A['feature-clamp'], exit=3, actions=[protected_edit]),
                     'scope-protected-file-changed', 'adapter-nonzero-exit'),
                    ('added entry, reported unavailable',
                     {'envelope': unavailable, 'actions': [{'op': 'mkdir', 'path': 'scratch'}]},
                     'scope-workspace-entry-added', 'adapter-reported-unavailable')]
        run = self.against_baseline('feature-clamp', [step for _, step, _, _ in variants])
        for (label, _, violation, missing), row in zip(variants, run.rows('candidate')):
            with self.subTest(variant=label):
                self.assertEqual(row['outcome'], 'FAIL', row['reasons'])
                self.assertIn(violation, row['reasons'])
                self.assertIn(missing, row['unavailable_reasons'])
                self.assertEqual(row['behavior']['total'], 0, 'unavailable output must not be graded')
        self.assertEqual((run.code, run.result['outcome']), (1, 'FAIL'))
        self.assertIn('candidate-failed-acceptance', run.result['reasons'])


class EvaluationInputs(EvalCase):
    def test_unsafe_corpus_paths_rejected_before_use(self):
        lab = Lab(self)
        tasks, _ = agent_eval.load_corpus(write_corpus(lab.root / 'control', CORPUS))
        self.assertEqual([task['id'] for task in tasks], TASK_IDS)
        unsafe = ('../escape.py', 'pkg/../../escape.py', '.git/config', 'pkg/.Git/hooks/post-checkout',
                  '/escape.py', 'pkg\\escape.py', 'pkg/./escape.py', agent_eval.PROMPT_NAME)
        for index, rel in enumerate(unsafe):
            with self.subTest(path=rel):
                data = copy.deepcopy(CORPUS)
                task_named(data, 'feature-clamp')['files'][rel] = 'escaped = True\n'
                with self.assertRaises(agent_eval.Invalid) as raised:
                    agent_eval.load_corpus(write_corpus(lab.root / f'unsafe-{index}', data))
                self.assertEqual(raised.exception.code, 'corpus-file-path')

    def test_malformed_corpus_rejected_without_evaluation(self):
        def change(task_id, **fields):
            return lambda data: task_named(data, task_id).update(fields)

        def edit_files(task_id, rel, content):
            return lambda data: task_named(data, task_id)['files'].__setitem__(rel, content)

        def drop(task_id, key):
            return lambda data: task_named(data, task_id).pop(key)

        def probe(**fields):
            return lambda data: task_named(data, 'support-missing-runtime')['evidence']['probes'][1].update(fields)
        cases = [
            ('kind does not match grader', change('bug-page-count', kind='feature'), 'corpus-task-grader'),
            ('unknown kind', change('feature-clamp', kind='benchmark'), 'corpus-task-grader'),
            ('unknown grader', change('feature-clamp', grader='gold-grader'), 'corpus-task-grader'),
            ('grader not text', change('feature-clamp', grader=['clamp-feature']), 'corpus-task-grader'),
            ('extra task metadata', change('feature-clamp', gold='return value'), 'corpus-task-schema'),
            ('missing statement', drop('feature-clamp', 'statement'), 'corpus-task-schema'),
            ('bad task id', change('feature-clamp', id='Feature_Clamp'), 'corpus-task-id'),
            ('allowed paths widened', change('feature-clamp', allowed_paths=[NUMBERS_PATH, 'pkg/__init__.py']),
             'corpus-allowed-paths'),
            ('allowed paths duplicated', change('feature-clamp', allowed_paths=[NUMBERS_PATH, NUMBERS_PATH]),
             'corpus-allowed-paths'),
            ('allowed paths not a list', change('feature-clamp', allowed_paths=NUMBERS_PATH), 'corpus-allowed-paths'),
            ('read-only task given writes', change('review-clean-floor', allowed_paths=[RATIO_PATH]),
             'corpus-allowed-paths'),
            ('fixture missing', lambda data: task_named(data, 'feature-clamp')['files'].pop(NUMBERS_PATH),
             'corpus-fixture-missing'),
            ('file content not text', edit_files('feature-clamp', 'pkg/__init__.py', 0), 'corpus-file-content'),
            ('case-colliding files', edit_files('feature-clamp', 'PKG/__init__.py', ''), 'corpus-file-path'),
            ('file shadows directory', edit_files('feature-clamp', 'pkg', ''), 'corpus-file-path'),
            ('evidence exit altered', probe(exit_code=0), 'corpus-evidence-mismatch'),
            ('evidence unknown field', probe(note='x'), 'corpus-evidence-schema'),
            ('evidence on code task', change('feature-clamp', evidence={}), 'corpus-evidence-unexpected'),
            ('duplicate task id', change('review-clean-floor', id='review-defective-floor'), 'corpus-duplicate-task'),
            ('wrong schema', lambda data: data.update(schema='verified-handoff/agent-eval-corpus/v0'), 'corpus-schema'),
            ('extra top-level key', lambda data: data.update(graders={}), 'corpus-schema'),
            ('description not text', lambda data: data.update(description=1), 'corpus-schema'),
            ('no tasks', lambda data: data.update(tasks=[]), 'corpus-schema'),
        ]
        text = json.dumps(CORPUS)
        raw = [('duplicate JSON key', '{"schema": "x", ' + text[1:], 'corpus-unreadable'),
               ('non-finite number', text[:-1] + ', "weight": NaN}', 'corpus-unreadable'),
               ('not JSON', 'corpus', 'corpus-unreadable')]
        lab = Lab(self)
        files = lab.prepare(build_plan(steps(RESPONSES_A), steps(RESPONSES_A)))
        for index, (label, mutate, reason) in enumerate(cases + raw):
            with self.subTest(case=label):
                if isinstance(mutate, str):
                    corpus = write_corpus(lab.root / f'corpus-{index}', mutate)
                else:
                    data = copy.deepcopy(CORPUS)
                    mutate(data)
                    corpus = write_corpus(lab.root / f'corpus-{index}', data)
                out = lab.root / f'out-{index}'
                run = evaluate(files, corpus=corpus, out=out)
                self.assertEqual(run.code, 2, run.stdout)
                self.assertEqual(run.usage_reasons(), [reason])
                self.assertFalse(out.exists())
        link = lab.root / 'corpus-link.json'
        link.symlink_to(write_corpus(lab.root / 'corpus-target', CORPUS))
        run = evaluate(files, corpus=link, out=lab.root / 'out-link')
        self.assertEqual((run.code, run.usage_reasons()), (2, ['corpus-symlink']))
        self.assertEqual(launches(files['trace']), 0)

    def test_valid_corpus_copy_is_accepted(self):
        lab = Lab(self)
        corpus = write_corpus(lab.root / 'corpus', CORPUS)
        run = evaluate(lab.prepare(build_plan(steps(RESPONSES_A), steps(RESPONSES_B))),
                       corpus=corpus, tasks=['feature-clamp'])
        self.assertEqual((run.code, run.result['outcome']), (0, 'PASS'))
        self.assertEqual((run.result['harness']['corpus'], run.result['harness']['corpus_sha256']),
                         (str(corpus), sha256(corpus)))

    def test_unknown_task_and_invalid_options_rejected(self):
        lab = Lab(self)
        files = lab.prepare(build_plan(steps(RESPONSES_A), steps(RESPONSES_A)))
        cases = [('unknown task', {'tasks': ['feature-clamp', 'does-not-exist']}, 'unknown-task'),
                 ('zero trials', {'trials': 0}, 'invalid-trials'),
                 ('too many trials', {'trials': agent_eval.MAX_TRIALS + 1}, 'invalid-trials'),
                 ('zero timeout', {'timeout': 0}, 'invalid-timeout'),
                 ('NaN timeout', {'timeout': 'nan'}, 'invalid-timeout'),
                 ('infinite timeout', {'timeout': 'inf'}, 'invalid-timeout')]
        for index, (label, options, reason) in enumerate(cases):
            with self.subTest(case=label):
                out = lab.root / f'out-{index}'
                run = evaluate(files, out=out, **options)
                self.assertEqual((run.code, run.usage_reasons()), (2, [reason]))
                self.assertFalse(out.exists())
        self.assertEqual(launches(files['trace']), 0)

    def test_invalid_adapter_or_instructions_rejected(self):
        lab = Lab(self)
        files = lab.prepare(build_plan(steps(RESPONSES_A), steps(RESPONSES_A)))
        config = json.loads(files['adapter'].read_text())

        def adapter_file(name, **changes):
            path = lab.root / f'{name}.json'
            path.write_text(json.dumps(dict(config, **changes)))
            return path
        link = lab.root / 'adapter-link.json'
        link.symlink_to(files['adapter'])
        candidate_link = lab.root / 'candidate-link.md'
        candidate_link.symlink_to(files['candidate'])
        cases = [
            ('placeholder missing', {'adapter': adapter_file('no-placeholder', argv=[a for a in config['argv']
                                                                                 if a != '{prompt_file}'])},
             'adapter-placeholder-missing'),
            ('unknown adapter field', {'adapter': adapter_file('extra', model_alias='x')}, 'adapter-schema'),
            ('requested model not text', {'adapter': adapter_file('model', requested_model=5)}, 'adapter-schema'),
            ('argv too short', {'adapter': adapter_file('short', argv=[sys.executable])}, 'adapter-argv-invalid'),
            ('adapter config symlink', {'adapter': link}, 'adapter-symlink'),
            ('instructions symlink', {'candidate': candidate_link}, 'instructions-unreadable'),
            ('instructions missing', {'baseline': lab.root / 'missing.md'}, 'instructions-unreadable'),
            ('instructions directory', {'baseline': lab.root}, 'instructions-unreadable'),
        ]
        for index, (label, overrides, reason) in enumerate(cases):
            with self.subTest(case=label):
                out = lab.root / f'out-{index}'
                run = evaluate(dict(files, **overrides), out=out, tasks=['feature-clamp'])
                self.assertEqual((run.code, run.usage_reasons()), (2, [reason]))
                self.assertFalse(out.exists())
        self.assertEqual(launches(files['trace']), 0)

    def test_unsafe_output_directories_rejected(self):
        lab = Lab(self)
        files = lab.prepare(build_plan(steps(RESPONSES_A), steps(RESPONSES_A)))
        corpus = write_corpus(lab.root / 'corpus', CORPUS)
        existing = lab.root / 'existing'
        existing.mkdir()
        inside_skill = agent_eval.SKILL_ROOT / 'agent-eval-test-output'
        self.assertFalse(inside_skill.exists())
        self.addCleanup(lambda: inside_skill.rmdir() if inside_skill.is_dir() else None)
        link = lab.root / 'link-to-corpus'
        link.symlink_to(corpus.parent, target_is_directory=True)
        cases = [('existing directory', existing, None, 'out-dir-exists'),
                 ('inside skill source', inside_skill, None, 'out-dir-inside-source'),
                 ('inside corpus directory', corpus.parent / 'out', corpus, 'out-dir-inside-source'),
                 ('symlinked parent into corpus', link / 'out', corpus, 'out-dir-inside-source'),
                 ('dot-dot name', lab.root / 'sub' / '..', None, 'out-dir-unsafe'),
                 ('missing parent', lab.root / 'missing' / 'out', None, 'out-dir-uncreatable')]
        for label, out, corpus_arg, reason in cases:
            with self.subTest(case=label):
                run = evaluate(files, out=out, corpus=corpus_arg, tasks=['feature-clamp'])
                self.assertEqual((run.code, run.usage_reasons()), (2, [reason]))
        self.assertFalse(inside_skill.exists())
        self.assertFalse((corpus.parent / 'out').exists())
        self.assertEqual(launches(files['trace']), 0)

    def test_source_tampering_during_run_is_incomplete(self):
        lab = Lab(self)
        corpus = write_corpus(lab.root / 'corpus', CORPUS)

        def plan(files):
            tamper = [{'op': 'append', 'path': str(files['candidate']), 'content': 'late edit\n'},
                      {'op': 'append', 'path': str(corpus), 'content': '\n'}]
            return build_plan({'feature-clamp': answer(RESPONSES_A['feature-clamp'])},
                              {'feature-clamp': answer(RESPONSES_A['feature-clamp'], actions=tamper)})
        run = lab.run(plan, tasks=['feature-clamp'], corpus=corpus)
        self.assertEqual(run.outcomes('candidate'), ['PASS'])
        self.assertEqual((run.code, run.result['outcome']), (3, 'INCOMPLETE'))
        self.assertEqual(run.result['source_changes'], ['candidate', 'corpus'])
        self.assertIn('source-changed:candidate', run.result['reasons'])
        self.assertIn('source-changed:corpus', run.result['reasons'])


class AdapterInputs(EvalCase):
    def test_declared_input_files_identify_the_payload_and_omission_is_unknown(self):
        lab = Lab(self)
        plan = build_plan(steps(RESPONSES_A), steps(RESPONSES_B))
        relative = declare_inputs(lab.prepare(plan), ['fake_adapter.py'])
        absolute = lab.prepare(plan)
        declare_inputs(absolute, [str(absolute['script'])])
        for label, files in (('relative', relative), ('absolute', absolute)):
            with self.subTest(declared=label):
                run = evaluate(files, tasks=['feature-clamp'])
                self.assertIsNotNone(run.result, run.stderr)
                self.assertEqual((run.code, run.result['outcome']), (0, 'PASS'), run.stdout + run.stderr)
                adapter = run.result['adapter']
                self.assertEqual(adapter['payload_identity'], 'declared-input-files')
                item, = adapter['input_files']
                self.assertEqual(item['path'], str(files['script'].resolve()))
                self.assertTrue(item['identity'].endswith(':' + sha256(files['script'])), item)
                self.assertEqual(adapter['config_sha256'], sha256(files['adapter']))
                self.assertEqual(run.result['source_changes'], [])
        # A four-field config stays valid; its payload identity is recorded as unknown.
        legacy = evaluate(lab.prepare(plan), tasks=['feature-clamp'])
        self.assertEqual((legacy.code, legacy.result['outcome']), (0, 'PASS'))
        self.assertEqual((legacy.result['adapter']['payload_identity'], legacy.result['adapter']['input_files']),
                         ('unknown', []))

    def test_invalid_input_files_rejected_before_launch(self):
        lab = Lab(self)
        files = lab.prepare(build_plan(steps(RESPONSES_A), steps(RESPONSES_A)))
        (files['dir'] / 'linked_adapter.py').symlink_to(files['script'])
        config = json.loads(files['adapter'].read_text(encoding='utf-8'))
        cases = [('symlink', ['linked_adapter.py'], 'adapter-input-file-symlink'),
                 ('duplicate via absolute path', ['fake_adapter.py', str(files['script'])],
                  'adapter-input-file-duplicate'),
                 ('missing', ['missing_wrapper.py'], 'adapter-input-file-missing'),
                 ('directory', ['trace'], 'adapter-input-file-not-regular'),
                 ('empty list', [], 'adapter-input-files-invalid'),
                 ('not a list', 'fake_adapter.py', 'adapter-input-files-invalid'),
                 ('null', None, 'adapter-input-files-invalid'),
                 ('too many', ['fake_adapter.py'] * (agent_eval.MAX_ADAPTER_INPUTS + 1),
                  'adapter-input-files-invalid'),
                 ('entry not text', [5], 'adapter-input-file-invalid')]
        for index, (label, inputs, reason) in enumerate(cases):
            with self.subTest(case=label):
                adapter = files['dir'] / f'adapter-{index}.json'
                adapter.write_text(json.dumps(dict(config, input_files=inputs)), encoding='utf-8')
                out = lab.root / f'out-{index}'
                run = evaluate(dict(files, adapter=adapter), out=out, tasks=['feature-clamp'])
                self.assertEqual((run.code, run.usage_reasons()), (2, [reason]))
                self.assertFalse(out.exists())
        self.assertEqual(launches(files['trace']), 0)

    def test_payload_changed_after_baseline_blocks_the_candidate_launch(self):
        def plan(files):
            drift = {'op': 'append', 'path': str(files['script']), 'content': '# payload drift\n'}
            return build_plan({'feature-clamp': answer(RESPONSES_A['feature-clamp'], actions=[drift])},
                              {'feature-clamp': answer(RESPONSES_B['feature-clamp'])})
        lab = Lab(self)
        files = declare_inputs(lab.prepare(plan), ['fake_adapter.py'])
        run = evaluate(files, tasks=['feature-clamp'])
        self.assertIsNotNone(run.result, run.stderr)
        self.assertEqual(run.outcomes('baseline'), ['PASS'], 'positive control')
        row, = run.rows('candidate')
        self.assertEqual((row['outcome'], row['reasons']), ('UNAVAILABLE', ['adapter-input-changed']))
        self.assertFalse(row['adapter']['launched'])
        self.assertEqual(launches(files['trace']), 1)
        result = run.result
        self.assertEqual((run.code, result['outcome']), (3, 'INCOMPLETE'))
        self.assertEqual(result['source_changes'], ['adapter-input-0'])
        self.assertIn('source-changed:adapter-input-0', result['reasons'])
        self.assertNotIn('candidate-failed-acceptance', result['reasons'])
        self.assertEqual((result['regressions'], result['regressions_undetermined']), ([], ['feature-clamp']))
        # Control: undeclared, the same drift is not observed and the payload identity is unknown.
        undeclared = Lab(self).run(plan, tasks=['feature-clamp'])
        self.assertEqual(undeclared.outcomes('candidate'), ['PASS'])
        self.assertEqual((undeclared.result['adapter']['payload_identity'], undeclared.result['source_changes']),
                         ('unknown', []))

    def alias_lab(self, *, retarget: bool, config_in_alias: bool) -> dict:
        """Lab with v1/ and v2/ holding identical bytes and a test-owned `current` -> v1 link.

        With `retarget`, the baseline step repoints `current` at v2 after its own launch;
        v1 stays present and unchanged, so only the alias binding moves.
        """
        def plan(files):
            current = files['dir'] / 'current'
            moves = [{'op': 'remove', 'path': str(current)},
                     {'op': 'symlink', 'path': str(current), 'target': str(files['dir'] / 'v2')}]
            extra = {'actions': moves} if retarget else {}
            return build_plan({'feature-clamp': answer(RESPONSES_A['feature-clamp'], **extra)},
                              {'feature-clamp': answer(RESPONSES_B['feature-clamp'])})
        files = Lab(self).prepare(plan)
        for version in ('v1', 'v2'):
            (files['dir'] / version).mkdir()
            (files['dir'] / version / 'payload.py').write_text('# adapter payload\n', encoding='utf-8')
        (files['dir'] / 'current').symlink_to(files['dir'] / 'v1', target_is_directory=True)
        if not config_in_alias:
            return declare_inputs(files, ['current/payload.py'])
        config = json.loads(files['adapter'].read_text(encoding='utf-8'))
        text = json.dumps(dict(config, input_files=['payload.py']))
        for version in ('v1', 'v2'):
            (files['dir'] / version / 'adapter.json').write_text(text, encoding='utf-8')
        return dict(files, adapter=files['dir'] / 'current' / 'adapter.json')

    def assertCandidateBlocked(self, run: Run, reasons: set[str]) -> dict:
        self.assertIsNotNone(run.result, run.stderr)
        baseline, = run.rows('baseline')
        self.assertEqual(baseline['outcome'], 'PASS', 'positive control')
        self.assertTrue(baseline['adapter']['launched'])
        row, = run.rows('candidate')
        self.assertEqual(row['outcome'], 'UNAVAILABLE', row['reasons'])
        self.assertTrue(row['reasons'] and set(row['reasons']) <= reasons, row['reasons'])
        self.assertFalse(row['adapter']['launched'])
        self.assertEqual(launches(run.files['trace']), 1)
        self.assertEqual((files_dir := run.files['dir'] / 'current').resolve(), (files_dir.parent / 'v2').resolve())
        self.assertEqual(sha256(files_dir.parent / 'v1' / 'payload.py'), sha256(files_dir.parent / 'v2' / 'payload.py'))
        result = run.result
        self.assertEqual((run.code, result['outcome']), (3, 'INCOMPLETE'))
        self.assertNotIn('candidate-failed-acceptance', result['reasons'])
        self.assertEqual((result['regressions'], result['regressions_undetermined']), ([], ['feature-clamp']))
        return row

    def assertStableAliasPasses(self, files: dict) -> Run:
        run = evaluate(files, tasks=['feature-clamp'])
        self.assertIsNotNone(run.result, run.stderr)
        self.assertEqual((run.code, run.result['outcome'], run.result['source_changes']), (0, 'PASS', []),
                         run.stdout + run.stderr)
        self.assertEqual(launches(files['trace']), 2)
        return run

    def test_input_directory_alias_retargeted_after_baseline_blocks_the_candidate_launch(self):
        files = self.alias_lab(retarget=True, config_in_alias=False)
        v1 = files['dir'] / 'v1' / 'payload.py'
        v1_before = sha256(v1)
        run = evaluate(files, tasks=['feature-clamp'])
        row = self.assertCandidateBlocked(run, {'adapter-input-alias-changed'})
        self.assertEqual(row['reasons'], ['adapter-input-alias-changed'])
        self.assertEqual(sha256(v1), v1_before)
        result = run.result
        self.assertEqual(result['source_changes'], ['adapter-input-0-alias'])
        self.assertIn('source-changed:adapter-input-0-alias', result['reasons'])
        item, = result['adapter']['input_files']
        self.assertEqual((item['lexical_path'], item['path']),
                         (str(files['dir'] / 'current' / 'payload.py'), str(v1)))
        # Control: the same alias left in place is accepted.
        stable = self.alias_lab(retarget=False, config_in_alias=False)
        control = self.assertStableAliasPasses(stable)
        item, = control.result['adapter']['input_files']
        self.assertEqual(item['path'], str(stable['dir'] / 'v1' / 'payload.py'))

    def test_config_directory_alias_retargeted_after_baseline_blocks_the_candidate_launch(self):
        files = self.alias_lab(retarget=True, config_in_alias=True)
        v1_config, v2_config = (files['dir'] / version / 'adapter.json' for version in ('v1', 'v2'))
        self.assertEqual(sha256(v1_config), sha256(v2_config))
        run = evaluate(files, tasks=['feature-clamp'])
        row = self.assertCandidateBlocked(run, {'adapter-config-alias-changed', 'adapter-input-alias-changed'})
        self.assertIn('adapter-config-alias-changed', row['reasons'])
        result = run.result
        self.assertIn('adapter-config-alias', result['source_changes'])
        self.assertLessEqual(set(result['source_changes']), {'adapter-config-alias', 'adapter-input-0-alias'})
        self.assertIn('source-changed:adapter-config-alias', result['reasons'])
        # Identical config bytes: this is an alias-binding change, not a content change.
        self.assertNotIn('adapter', result['source_changes'])
        self.assertEqual((result['adapter']['config'], result['adapter']['config_resolved']),
                         (str(files['adapter']), str(v1_config)))
        # Control: a stable parent alias is accepted.
        stable = self.alias_lab(retarget=False, config_in_alias=True)
        control = self.assertStableAliasPasses(stable)
        self.assertEqual(control.result['adapter']['config_resolved'], str(stable['dir'] / 'v1' / 'adapter.json'))
        # A final-file symlink input is still rejected through the stable parent alias.
        v1 = stable['dir'] / 'v1'
        (v1 / 'link.py').symlink_to(v1 / 'payload.py')
        config = json.loads((v1 / 'adapter.json').read_text(encoding='utf-8'))
        (v1 / 'adapter-link.json').write_text(json.dumps(dict(config, input_files=['link.py'])), encoding='utf-8')
        out = stable['dir'] / 'out-link'
        linked = evaluate(dict(stable, adapter=stable['dir'] / 'current' / 'adapter-link.json'), out=out,
                          tasks=['feature-clamp'])
        self.assertEqual((linked.code, linked.usage_reasons()), (2, ['adapter-input-file-symlink']))
        self.assertFalse(out.exists())
        self.assertEqual(launches(stable['trace']), 2)


if __name__ == '__main__':
    unittest.main()
