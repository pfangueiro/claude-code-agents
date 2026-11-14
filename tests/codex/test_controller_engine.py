"""Black-box acceptance tests for the persistent controller engine (controller_engine.py).

Written BEFORE the engine exists: with no engine every scenario fails RED on the operator
contract (`run`/`recover` report runtime_missing); nothing is skipped. The public surface
exercised is only the operator CLI (init, digest, submit, run --once, status --json, stop,
resume, recover, reconcile) plus read-only Ledger views. Everything else is real and
disposable: a copied runtime under a private temp root, Git repositories with a local bare
remote, the SQLite ledger and owned subprocesses. Providers are synthetic native-protocol
executables (tests/controller/fixtures/fake_native_cli.py) with private temp config dirs;
no real Claude/Codex, account or network is touched and no assertion is a quality claim.

Engine data contract assumed (handed to the engine author):
- every native prompt starts with SDLC_ASSIGNMENT / one JSON envelope line /
  END_SDLC_ASSIGNMENT (keys: see fake_native_cli.ENVELOPE_KEYS); a whole-result review
  carries base_sha = plan origin and result_sha = the integrated candidate;
- reviews answer with one fenced sdlc-verdict block (controller_providers parser);
- `run --once` drives admitted work until no further progress is possible; PASS (exit 0)
  means every admitted plan passed its gates including the whole-result gate;
- the whole-result candidate is integrated locally by merge or fast-forward, never a
  squash, so every accepted task result is a Git ancestor of it;
- check receipts and raw logs referenced from the ledger live under --state.

Fixture control the engine needs no knowledge of: fake workers publish their own pid, OS
start identity and token under <config_dir>/log/live and SIGKILL THEMSELVES on
<config_dir>/control/crash-<token> or terminate-all (see fake_native_cli). The engine must
only leave a profile config_dir untouched.

Teardown never kills by argv, name or bare pid. It signals only the test's own unreaped
`run` Popen groups, triggers fixture self-termination, runs operator `stop` + `recover`, and
then proves settlement read-only (fixture markers gone by pid + start identity; ledger
owned_work empty; no retained controller_process bootstrap identity still 'owned' or
'unknown'). Anything unproven keeps the temp root as evidence and FAILS the test.
"""
import contextlib
import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / '.claude' / 'skills'
SCRIPTS = SKILLS / 'delivery' / 'scripts'
FAKE_CLI = ROOT / 'tests' / 'controller' / 'fixtures' / 'fake_native_cli.py'
DONE = ('accepted', 'published')
EXTERNAL_KINDS = ('push', 'pr.create', 'pr.merge')
FORBIDDEN_FLAGS = ('--model', '-m', '--permission-mode', '--dangerously-skip-permissions',
                   '--allowedTools', '--sandbox', '-s', '--full-auto', '--ask-for-approval',
                   '--dangerously-bypass-approvals-and-sandbox', '--resume', '-c', '--config')
PASS_TIMEOUT = 900
DIAG_RUNS, DIAG_ROWS, DIAG_TAIL = 4, 12, 1500  # bounds of the failure-only diagnosis
# Allowlisted status fields only: no environment, prompt, launch identity or receipt body.
DIAG_KEYS = {'tasks': ('id', 'state', 'result', 'failures', 'hold', 'reason'),
             'attempts': ('id', 'task_id', 'role', 'profile_id', 'state', 'outcome', 'attribution', 'reason'),
             'effects': ('id', 'task_id', 'kind', 'state', 'reason'),
             'evidence': ('task_id', 'kind', 'status', 'passed', 'reasons')}
DIAG_PLAN_KEYS = ('id', 'state', 'stale', 'hold', 'outcome', 'reason')
ALPHA = 'def value():\n    return 1 + 1\n'
BETA = 'def value():\n    return 3\n'
GAMMA = 'import alpha\n\n\ndef value():\n    return alpha.value() * 10\n'

CHECK_SCRIPT = '''#!{python} -I
import importlib, json, os, re, subprocess, sys, time
sys.dont_write_bytecode = True

def head():
    env = {{k: v for k, v in os.environ.items() if not k.startswith('GIT_')}}
    done = subprocess.run([{git!r}, 'rev-parse', 'HEAD'], capture_output=True, text=True,
                          env=env, check=False)
    return done.stdout.strip() or None

def files():
    found = sorted(n for n in os.listdir('.') if n.endswith('.py'))
    if os.path.isdir('plugins'):
        found += sorted('plugins/' + n for n in os.listdir('plugins') if n.endswith('.py'))
    return found

def module(name, expected):
    sys.path.insert(0, os.getcwd())
    try:
        value = importlib.import_module(name).value()
    except Exception as err:
        return False, type(err).__name__
    return value == int(expected), 'value=%r' % (value,)

def plugins():
    names = []
    for path in (p for p in files() if p.startswith('plugins/')):
        match = re.search(r"^NAME = '([^']*)'", open(path).read(), re.M)
        names.append(match.group(1) if match else None)
    return bool(names) and None not in names and len(set(names)) == len(names), 'names=%r' % names

ok, detail = module(*sys.argv[2:4]) if sys.argv[1] == 'module' else plugins()
record = {{'check': ' '.join(sys.argv[1:]), 'cwd': os.getcwd(), 'head': head(), 'files': files(),
          'ok': ok, 'detail': detail, 'pid': os.getpid(), 'ns': time.time_ns()}}
with open({log!r}, 'a') as handle:
    handle.write(json.dumps(record) + '\\n')
print(detail)
sys.exit(0 if ok else 1)
'''


def _module(name, directory):
    """Import a public module (read-only Ledger views, controller_process identity checks, the
    fixture's process_state) without writing bytecode into the source tree."""
    if name not in sys.modules:
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(directory))
        try:
            importlib.import_module(name)
        finally:
            sys.path.remove(str(directory))
            sys.dont_write_bytecode = previous
    return sys.modules[name]


def task(task_id, scope, checks, deps=()):
    return {'id': task_id, 'objective': f'Implement {task_id} as described by its acceptance.',
            'kind': 'feature', 'depends_on': list(deps), 'write_scope': list(scope),
            'resources': [], 'checks': list(checks),
            'acceptance': [f'{task_id} behaves as its declared checks require']}


class Diagnosis:
    """Assertion message rendered by unittest only after the assertion has already failed, so
    it adds no work and no failure mode to a passing run and changes no acceptance."""

    def __init__(self, headline, render):
        self.headline, self.render = headline, render

    def __str__(self):
        return f'{self.headline}\n{self.render()}'


class ControllerHarness(unittest.TestCase):
    """Disposable environment, operator CLI, evidence readers and safe cleanup shared by the
    controller acceptance modules. It declares no scenario."""

    maxDiff = None

    # ---- disposable environment -----------------------------------------------------

    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix='ctl-accept-')))
        self.procs, self.profiles, self.run_log = [], [], []
        self.state, self.policy_path = self.root / 'state', None
        self.addCleanup(self._cleanup)
        for name in ('home', 'tmp', 'bin', 'pathbin', 'accounts', 'logs'):
            (self.root / name).mkdir()
        git = shutil.which('git')
        self.assertIsNotNone(git, 'git is required')
        (self.root / 'pathbin' / 'git').symlink_to(os.path.realpath(git))
        self.env = {'PATH': f"{self.root / 'pathbin'}:/usr/bin:/bin", 'HOME': str(self.root / 'home'),
                    'TMPDIR': str(self.root / 'tmp'), 'LANG': 'C.UTF-8', 'LC_ALL': 'C'}
        self.git_env = dict(self.env, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.runtime = self._copy_runtime()
        self.repo, self.origin = self.root / 'repo', self.root / 'origin.git'
        self._make_repo()
        self.check_log = self.root / 'logs' / 'checks.jsonl'
        self.checker = self.root / 'bin' / 'behavior-check'
        self.checker.write_text(CHECK_SCRIPT.format(python=sys.executable, git=str(self.root / 'pathbin' / 'git'),
                                                    log=str(self.check_log)))
        self.checker.chmod(0o700)

    def _copy_runtime(self):
        """A disposable copy keeps the known layout runtime_digest requires; the framework
        source is never written (no bytecode, no edits)."""
        skills = self.root / 'runtime' / 'skills'
        ignore = shutil.ignore_patterns('__pycache__', '*.pyc')
        for bundle in ('delivery', 'verified-handoff'):
            shutil.copytree(SKILLS / bundle, skills / bundle, ignore=ignore)
        return skills / 'delivery' / 'scripts'

    def git(self, *args, cwd=None, check=True):
        done = subprocess.run(['git', '-C', str(cwd or self.repo), *args], env=self.git_env,
                              capture_output=True, text=True, timeout=60, check=False)
        if check and done.returncode:
            self.fail(f'git {args[0]} failed: {done.stderr.strip()}')
        return done.stdout.strip() if check else done.returncode

    def _make_repo(self):
        self.repo.mkdir()
        self.git('init', '-q', '-b', 'main')
        for key, value in (('user.name', 'Fixture Owner'), ('user.email', 'owner@fixture.invalid'),
                           ('commit.gpgsign', 'false')):
            self.git('config', key, value)
        (self.repo / 'README.md').write_text('fixture\n')
        (self.repo / '.gitignore').write_text('__pycache__/\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'fixture origin')
        self.git('init', '-q', '--bare', str(self.origin), cwd=self.root)
        self.git('remote', 'add', 'origin', str(self.origin))
        self.git('push', '-q', 'origin', 'main')
        self.origin_sha = self.git('rev-parse', 'main')
        self.source_before = self._source_snapshot()

    def _source_snapshot(self):
        return {'main': self.git('rev-parse', 'refs/heads/main'), 'head': self.git('symbolic-ref', 'HEAD'),
                'status': self.git('status', '--porcelain=v1', '--untracked-files=all'),
                'remote': self.git('for-each-ref', '--format=%(refname) %(objectname)', cwd=self.origin)}

    def profile(self, profile_id, provider, behavior, roles=('implement', 'review')):
        home = self.root / 'accounts' / profile_id
        for sub in ('log', 'control'):
            (home / sub).mkdir(parents=True)
        home.chmod(0o700)
        (home / 'behavior.json').write_text(json.dumps(behavior))
        wrapper = self.root / 'bin' / f'{provider}-{profile_id}'
        wrapper.write_text('#!/bin/sh\nexec ' + ' '.join(shlex.quote(part) for part in (
            sys.executable, '-I', str(FAKE_CLI), '--fake-provider', provider, '--fake-home', str(home)))
            + ' "$@"\n')
        wrapper.chmod(0o700)
        entry = {'id': profile_id, 'provider': provider, 'executable': str(wrapper),
                 'config_dir': str(home), 'roles': list(roles)}
        self.profiles.append(entry)
        return entry

    def check_argv(self, *args):
        return [str(self.checker), *args]

    def _private_json(self, path, data):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(data, handle)
        return path

    def setup_controller(self, checks, max_parallel=1, auto_route=False, max_attempts=3, instruction_paths=()):
        policy = {'version': 1, 'repository': str(self.repo), 'profiles': self.profiles,
                  'auto_route': auto_route, 'execution_enabled': True, 'background_enabled': False,
                  'max_parallel': max_parallel, 'review_reserve': 0,
                  'limits': {'max_attempts': max_attempts, 'attempt_seconds': 600,
                             'max_total_seconds': 14400, 'max_no_progress': 3, 'max_cost_usd': None},
                  'allowed_checks': checks, 'effects': ['commit', 'integrate'], 'delivery': None,
                  'instruction_paths': list(instruction_paths)}
        self.policy_path = self._private_json(self.root / 'policy.json', policy)
        self.accounts_before = self._accounts_snapshot()
        self.expect_cli(0, 'init', '--policy', str(self.policy_path))

    def submit(self, plan_id, tasks):
        plan = {'version': 1, 'id': plan_id, 'objective': f'Deliver {plan_id}.',
                'input_revision': 'fixture-r1', 'base_sha': self.origin_sha, 'tasks': tasks}
        plan_path = self.root / f'plan-{plan_id}.json'
        plan_path.write_text(json.dumps(plan))
        digest = self.cli('digest', '--plan', str(plan_path), '--policy', str(self.policy_path),
                          state=False).stdout.strip()
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        authority = self._private_json(self.root / f'authority-{plan_id}.json', {
            'version': 1, 'plan_digest': digest, 'effects': ['commit', 'integrate'],
            'authorizer': 'acceptance-fixture', 'approved_at': now})
        self.expect_cli(0, 'submit', '--plan', str(plan_path), '--authority', str(authority))
        return plan

    # ---- operator CLI ------------------------------------------------------------------

    def _argv(self, *args, state=True):
        tail = ['--state', str(self.state)] if state else []
        return [sys.executable, '-I', '-B', str(self.runtime / 'controller.py'), *args, *tail]

    def cli(self, *args, state=True, timeout=120):
        return subprocess.run(self._argv(*args, state=state), env=self.env, cwd=self.root,
                              capture_output=True, text=True, timeout=timeout, check=False)

    def expect_cli(self, code, *args, timeout=120):
        done = self.cli(*args, timeout=timeout)
        self._engine_present(done.stderr)
        self.assertEqual(done.returncode, code, f'{args[0]}: {done.stderr.strip()[-2000:]}')
        return done

    def _engine_present(self, stderr):
        if 'runtime_missing' in stderr or 'runtime_unavailable' in stderr:
            self.fail('controller_engine.py is absent or unloadable, so no work ran '
                      f'(expected RED before the engine exists): {stderr.strip()[-400:]}')

    def status(self):
        done = self.cli('status', '--json')
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def ledger(self, view):
        ledger = _module('controller_ledger', SCRIPTS).Ledger.open(str(self.state), readonly=True)
        try:
            return view(ledger)
        finally:
            ledger.close()

    def run_once(self):
        done = self.cli('run', '--once', timeout=PASS_TIMEOUT)
        self.run_log.append({'code': done.returncode, 'stderr': done.stderr[-DIAG_TAIL:],
                             'stdout': done.stdout[-DIAG_TAIL:]})
        self._engine_present(done.stderr)
        return done

    def drive(self, max_passes=12):
        """Repeat `run --once` until every task is done with PASS or two passes change nothing."""
        codes, previous, still = [], None, 0
        for _ in range(max_passes):
            codes.append(self.run_once().returncode)
            report = self.status()['status']
            tasks = report['tasks']
            if codes[-1] == 0 and tasks and all(t['state'] in DONE for t in tasks):
                break
            mark = (tuple((t['id'], t['state'], t['result']) for t in tasks), len(report['attempts']),
                    len(report['effects']), len(report['evidence']))
            still = still + 1 if mark == previous else 0
            previous = mark
            if still >= 2:
                break
        return codes, self.status()

    # ---- failure diagnostics (messages only; no assertion depends on them) --------------

    def explain(self, headline, report=None):
        return Diagnosis(headline, lambda: self.diagnosis(report))

    @staticmethod
    def _brief(row, keys):
        if not isinstance(row, dict):
            return {}
        brief = {key: row[key] for key in keys if key in row}
        result = row.get('result')
        if isinstance(result, dict) and 'reason' in result:
            brief['result_reason'] = result['reason']
        return brief

    @staticmethod
    def _bounded(value):
        return json.dumps(value, default=str, sort_keys=True)[:DIAG_TAIL]

    def diagnosis(self, report=None):
        """Bounded context for a failed scenario assertion: exit code and output tails of the
        last `run --once` calls (the engine states its holds there), then allowlisted task,
        attempt, effect, evidence and plan fields, the checks run and the review verdicts."""
        first = max(len(self.run_log) - DIAG_RUNS, 0)
        lines = [f"run {first + offset}: exit {run['code']}; stderr tail {run['stderr']!r}; "
                 f"stdout tail {run['stdout']!r}" for offset, run in enumerate(self.run_log[first:])]
        report = report if isinstance(report, dict) else {}
        status = report.get('status') if isinstance(report.get('status'), dict) else {}
        for section, keys in DIAG_KEYS.items():
            rows = status.get(section) or []
            lines.append(f'{section} ({len(rows)}): '
                         + self._bounded([self._brief(row, keys) for row in rows[-DIAG_ROWS:]]))
        plans = report.get('plans') or []
        lines.append(f'plans ({len(plans)}): '
                     + self._bounded([self._brief(row, DIAG_PLAN_KEYS) for row in plans[-DIAG_ROWS:]]))
        owned = report.get('owned_work') if isinstance(report.get('owned_work'), dict) else {}
        lines.append(f"control {status.get('control')!r}; owned_work "
                     + self._bounded({key: len(rows) for key, rows in owned.items() if isinstance(rows, list)}))
        checks = [{key: row.get(key) for key in ('check', 'ok', 'detail', 'head', 'files')}
                  for row in self.checks_run()[-DIAG_ROWS:]]
        lines.append(f'checks run (last {DIAG_ROWS}): ' + self._bounded(checks))
        reviews = [{key: row.get(key) for key in ('task_id', 'verdict', 'files', 'range_ok')}
                   for row in self.events('end') if row.get('role') == 'review'][-DIAG_ROWS:]
        lines.append(f'reviews (last {DIAG_ROWS}): ' + self._bounded(reviews))
        return '\n'.join(lines)

    def start_run(self):
        index = len(self.procs)
        out = open(self.root / 'logs' / f'run-{index}.err', 'w')
        proc = subprocess.Popen(self._argv('run', '--once'), env=self.env, cwd=self.root,
                                stdout=subprocess.DEVNULL, stderr=out, start_new_session=True)
        out.close()
        self.procs.append(proc)
        return proc

    def proc_err(self, proc):
        return (self.root / 'logs' / f'run-{self.procs.index(proc)}.err').read_text()[-2000:]

    def wait_for(self, predicate, timeout, what, proc=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            if proc is not None and proc.poll() is not None:
                self._engine_present(self.proc_err(proc))
                value = predicate()
                if value:
                    return value
                self.fail(f'run exited ({proc.returncode}) before {what}: {self.proc_err(proc)}')
            time.sleep(0.1)
        self.fail(f'timed out after {timeout}s waiting for {what}')

    def ready(self, profile_id, task_id):
        path = self.root / 'accounts' / profile_id / 'log' / f'ready-{task_id}.json'
        return json.loads(path.read_text()) if path.exists() else None

    def go(self, profile_id, task_id):
        (self.root / 'accounts' / profile_id / 'control' / f'go-{task_id}').touch()

    # ---- fixture worker identity (fixture-only; the engine never sees it) --------------

    @staticmethod
    def worker_state(marker):
        """'running' | 'gone' | 'unknown' from a fake worker's own pid + OS start identity."""
        return _module('fake_native_cli', FAKE_CLI.parent).process_state(marker)

    def crash_worker(self, profile_id, marker):
        """Publish the identified worker's private crash trigger; the worker SIGKILLs itself.
        The test never signals a process it did not spawn."""
        (self.root / 'accounts' / profile_id / 'control' / f"crash-{marker['token']}").touch()

    def fixture_markers(self):
        markers = []
        for entry in self.profiles:
            live = Path(entry['config_dir']) / 'log' / 'live'
            if not live.is_dir():
                continue
            for path in sorted(live.glob('*.json')):
                try:
                    markers.append(json.loads(path.read_text()))
                except FileNotFoundError:
                    continue  # the worker exited normally and removed its own marker
                except ValueError:
                    markers.append({'pid': None, 'start': None, 'marker': str(path)})
        return markers

    # ---- evidence readers ---------------------------------------------------------------

    def events(self, kind=None):
        rows = []
        for entry in self.profiles:
            log = Path(entry['config_dir']) / 'log' / 'events.jsonl'
            if log.exists():
                rows += [dict(json.loads(line), profile=entry['id'])
                         for line in log.read_text().splitlines() if line.strip()]
        rows.sort(key=lambda row: row['ns'])
        return [row for row in rows if kind is None or row['event'] == kind]

    def checks_run(self):
        if not self.check_log.exists():
            return []
        return [json.loads(line) for line in self.check_log.read_text().splitlines() if line.strip()]

    def tree_has(self, sha, *paths):
        return all(self.git('cat-file', '-e', f'{sha}:{path}', check=False) == 0 for path in paths)

    def is_ancestor(self, older, newer):
        return self.git('merge-base', '--is-ancestor', older, newer, check=False) == 0

    def state_digests(self):
        found = set()
        for directory, _, names in os.walk(self.state):
            for name in names:
                path = os.path.join(directory, name)
                if os.path.isfile(path) and not os.path.islink(path) and os.path.getsize(path) < 1 << 24:
                    with open(path, 'rb') as handle:
                        found.add(hashlib.sha256(handle.read()).hexdigest())
        return found

    def state_contains(self, needle):
        for directory, _, names in os.walk(self.state):
            for name in names:
                path = os.path.join(directory, name)
                if os.path.isfile(path) and not os.path.islink(path) and os.path.getsize(path) < 1 << 24:
                    with open(path, 'rb') as handle:
                        if needle.encode() in handle.read():
                            return True
        return False

    def _accounts_snapshot(self):
        snapshot = {}
        for entry in self.profiles:
            home = Path(entry['config_dir'])
            for path in sorted(home.rglob('*')):
                relative = path.relative_to(home)
                if relative.parts[0] in ('log', 'control'):
                    continue
                snapshot[f"{entry['id']}/{relative}"] = (
                    hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'dir')
        return snapshot

    # ---- shared assertions --------------------------------------------------------------

    def assert_native_turns(self):
        starts = self.events('start')
        self.assertEqual(self.events('unrecognized'), [], 'unrecognized native invocation')
        for row in starts:
            self.assertIsNone(row['problem'], f"prompt broke the assignment contract: {row['problem']}")
            self.assertFalse(set(row['argv']) & set(FORBIDDEN_FLAGS),
                             f"native model/permission flags overridden: {row['argv']}")
            config = next(p['config_dir'] for p in self.profiles if p['id'] == row['profile'])
            self.assertEqual(row['config_env'], config, 'profile account directory not selected')
        sessions = [row['session'] for row in starts]
        self.assertEqual(len(sessions), len(set(sessions)), 'a native session was reused')

    def assert_owner_boundaries(self, report):
        self.assertEqual(self._source_snapshot(), self.source_before,
                         'personal base branch, HEAD, worktree or remote changed')
        self.assertEqual(self._accounts_snapshot(), self.accounts_before, 'account settings changed')
        effects = report['status']['effects']
        self.assertEqual([e for e in effects if e['kind'] in EXTERNAL_KINDS], [],
                         'external publication without a grant')
        self.assertNotIn('published', [t['state'] for t in report['status']['tasks']])

    def assert_check_receipts(self, report, task_id, result):
        rows = [row for row in report['status']['evidence']
                if row['task_id'] == task_id and row['kind'] == 'check' and row['status'] == 'PASS'
                and row['receipt'] and row['receipt']['input_sha'] == result]
        self.assertTrue(rows, f'no PASS check evidence bound to {task_id} result {result}')
        digests = self.state_digests()
        for row in rows:
            for key in ('receipt_sha256', 'lifecycle_sha256'):
                self.assertIn(row['receipt'][key], digests, f'{task_id} {key} names no retained file')

    def reviews(self, predicate=lambda row: True):
        return [row for row in self.events('end') if row['role'] == 'review' and predicate(row)]

    # ---- cleanup -------------------------------------------------------------------------

    def _cleanup(self):
        """Settle only what this test can positively identify, then delete the temp root;
        otherwise keep it as evidence and FAIL. Nothing is killed by argv, name or bare pid."""
        problems = self._stop_own_runs()
        for entry in self.profiles:
            (Path(entry['config_dir']) / 'control' / 'terminate-all').touch()
        problems += self._settle_fixture_workers(30)
        problems += self._settle_engine_attempts(60)
        if problems:
            self.fail(f'owned work not proven settled; temp root kept for evidence at {self.root}: '
                      + '; '.join(problems))
        shutil.rmtree(self.root, ignore_errors=True)

    def _stop_own_runs(self):
        """Each `run` Popen is a session leader this process has not reaped, so its group id
        cannot have been reused when signalled."""
        problems = []
        for proc in self.procs:
            if proc.poll() is None:
                # A leader that exited after poll() leaves a zombie-only group: nothing to signal.
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                problems.append(f'own run {proc.pid} did not exit after SIGKILL')
        return problems

    def _settle_fixture_workers(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            pending = [(marker, self.worker_state(marker)) for marker in self.fixture_markers()]
            pending = [(marker, state) for marker, state in pending if state != 'gone']
            if not pending or time.monotonic() >= deadline:
                return [f"fixture worker {marker.get('pid')} not proven gone ({state})"
                        for marker, state in pending]
            time.sleep(0.2)

    def _settle_engine_attempts(self, timeout):
        """Operator STOP + recover let the engine settle its own attempts; settlement is then
        proven read-only. Without init nothing was ever claimed or launched."""
        if self.policy_path is None or not self.state.is_dir():
            return []
        self.cli('stop', timeout=60)
        deadline = time.monotonic() + timeout
        while True:
            recovered = self.cli('recover', timeout=300)
            problems = self._engine_problems()
            if not problems:
                return []
            if time.monotonic() >= deadline:
                return problems + [f'recover ({recovered.returncode}): {recovered.stderr.strip()[-400:]}']
            time.sleep(1)

    def _engine_problems(self):
        done = self.cli('status', '--json', timeout=60)
        if done.returncode:
            return [f'status unreadable: {done.stderr.strip()[-400:]}']
        try:
            report = json.loads(done.stdout)
        except ValueError:
            return ['status --json printed no JSON']
        work = report['owned_work']
        problems = [f"ledger attempt {item['id']} unsettled ({item.get('state')})" for item in work['attempts']]
        problems += [f"ledger effect {item['id']} unsettled ({item.get('state')})" for item in work['effects']]
        process = _module('controller_process', SCRIPTS)
        for attempt in report['status']['attempts']:
            identity = self._process_identity(attempt.get('launch'), process.IDENTITY_KEYS)
            verdict = None if identity is None else process.identify(identity)
            if verdict not in (None, 'not-owned'):
                problems.append(f"attempt {attempt['id']} bootstrap {identity['pid']} is {verdict}")
        return problems

    @staticmethod
    def _process_identity(launch, keys):
        """The shared helper's bootstrap identity when the engine retained it (flat or under
        'identity'); None when the launch row holds no such identity."""
        nested = launch.get('identity') if isinstance(launch, dict) else None
        for candidate in (launch, nested):
            if isinstance(candidate, dict) and keys <= set(candidate):
                return {key: candidate[key] for key in keys}
        return None


class ControllerEngineAcceptance(ControllerHarness):
    # ---- scenario 1 ----------------------------------------------------------------------

    def test_parallel_disjoint_tasks_dependency_and_whole_result_gate(self):
        self.profile('solo', 'claude', {
            'recipes': {'A': {'alpha.py': ALPHA}, 'B': {'beta.py': BETA}, 'C': {'gamma.py': GAMMA}},
            'barrier': {'tasks': ['A', 'B'], 'timeout': 120}})
        self.setup_controller({'alpha': self.check_argv('module', 'alpha', '2'),
                               'beta': self.check_argv('module', 'beta', '3'),
                               'gamma': self.check_argv('module', 'gamma', '20')}, max_parallel=2)
        self.submit('parallel', [task('A', ['alpha.py'], ['alpha']), task('B', ['beta.py'], ['beta']),
                                 task('C', ['gamma.py'], ['gamma'], deps=['A'])])
        codes, report = self.drive()
        tasks = {t['id']: t for t in report['status']['tasks']}
        self.assertEqual({tid: t['state'] for tid, t in tasks.items()},
                         dict.fromkeys('ABC', 'accepted'), self.explain(f'run outcomes {codes}', report))
        self.assertEqual(codes[-1], 0, self.explain('final run did not report PASS', report))
        self.assertTrue(report['requests'] and all(r['status'] == 'admitted' for r in report['requests']))
        self.assert_native_turns()

        barrier = [row['barrier'] for row in self.events('end') if 'barrier' in row]
        self.assertTrue(any(b['met'] and len(set(b['peers'].values())) == 2 for b in barrier),
                        f'A and B implementers were never live at the same time: {barrier}')
        live, peak = 0, 0
        for row in self.events():
            if row['event'] in ('start', 'end'):
                live += 1 if row['event'] == 'start' else -1
                peak = max(peak, live)
        self.assertLessEqual(peak, 2, 'global max_parallel exceeded by native sessions')

        implements = [row for row in self.events('start') if row['role'] == 'implement']
        cwds = {row['task_id']: row['cwd'] for row in implements}
        self.assertEqual(len(set(cwds.values())), 3, f'tasks shared a worktree: {cwds}')
        for cwd in cwds.values():
            self.assertFalse(cwd == str(self.repo) or cwd.startswith(str(self.repo) + os.sep),
                             'a worker ran inside the personal checkout')
        for row in implements:
            self.assertEqual(row['head'], row['envelope']['base_sha'], 'assigned base is not the worktree HEAD')

        bindings = {tid: self.ledger(lambda ledger, tid=tid: ledger.task(tid))['binding'] for tid in 'ABC'}
        c_base = bindings['C']['execution_base']
        self.assertTrue(self.is_ancestor(tasks['A']['result'], c_base), 'C base lacks accepted A result')
        self.assertTrue(self.is_ancestor(self.origin_sha, c_base))
        last_c = [row for row in implements if row['task_id'] == 'C'][-1]['envelope']
        self.assertEqual((last_c['base_sha'], last_c['dependencies']), (c_base, {'A': tasks['A']['result']}))

        producers = {row['pid'] for row in implements}
        for tid in 'ABC':
            own = self.reviews(lambda r, tid=tid: r['task_id'] == tid
                               and r['envelope']['result_sha'] == tasks[tid]['result'])
            self.assertTrue(own, f'no fresh review of {tid} result')
            self.assertEqual(own[-1]['envelope']['base_sha'], bindings[tid]['execution_base'])
            self.assertEqual(own[-1]['verdict'], 'PASS')
            self.assertNotIn(own[-1]['pid'], producers, 'reviewer reused the producer process')
            self.assert_check_receipts(report, tid, tasks[tid]['result'])

        whole = self.reviews(lambda r: r['envelope']['base_sha'] == self.origin_sha
                             and self.tree_has(r['envelope']['result_sha'], 'alpha.py', 'beta.py', 'gamma.py'))
        self.assertTrue(whole, 'no whole-result review bound to plan origin..integrated candidate')
        candidate = whole[-1]['envelope']['result_sha']
        self.assertEqual(whole[-1]['verdict'], 'PASS')
        self.assertTrue(whole[-1]['range_ok'], 'whole review range is not origin..candidate ancestry')
        for tid in 'ABC':
            # Declared contract: local merge or fast-forward integration, never a squash.
            self.assertTrue(self.is_ancestor(tasks[tid]['result'], candidate),
                            f"accepted {tid} result {tasks[tid]['result']} is not an ancestor of "
                            f'the integrated candidate {candidate}')
        last_task_review = max(r['ns'] for r in self.reviews(lambda r: r['task_id'] in ('A', 'B', 'C')
                                                             and r is not whole[-1]))
        self.assertGreater(whole[-1]['ns'], last_task_review - 1, 'whole review predates task reviews')
        on_candidate = {row['check'] for row in self.checks_run() if row['head'] == candidate and row['ok']}
        self.assertEqual(on_candidate, {'module alpha 2', 'module beta 3', 'module gamma 20'},
                         'whole-plan checks did not all pass on the integrated candidate')
        self.assert_owner_boundaries(report)

    # ---- scenario 2 ----------------------------------------------------------------------

    def test_crash_restart_settles_owned_work_before_retry(self):
        self.profile('solo', 'claude', {'recipes': {'T': {'tee.py': 'def value():\n    return 7\n'}},
                                        'hold': {'tasks': ['T'], 'once': True, 'timeout': 300}})
        self.setup_controller({'tee': self.check_argv('module', 'tee', '7')})
        self.submit('crash', [task('T', ['tee.py'], ['tee'])])
        proc = self.start_run()
        held = self.wait_for(lambda: self.ready('solo', 'T'), 180, 'the implementer to start', proc)
        launched = [a for a in self.status()['status']['attempts'] if a['role'] == 'implement']
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0]['state'], 'launched', 'live worker has no retained launch identity')

        os.killpg(proc.pid, signal.SIGKILL)  # the test's own unreaped run: its group id is not reused
        proc.wait(timeout=30)
        self.assertEqual(self.worker_state(held), 'running', 'worker did not outlive the controller crash')
        self.crash_worker('solo', held)  # unexpected worker failure: the worker SIGKILLs itself
        self.wait_for(lambda: self.worker_state(held) == 'gone', 30, 'the identified worker to terminate itself')
        interrupted = self.status()['status']['attempts'][0]
        self.assertNotEqual(interrupted['outcome'], 'success', 'interruption relabelled as success')

        self.expect_cli(0, 'recover', timeout=PASS_TIMEOUT)
        settled = self.status()
        self.assertEqual(settled['owned_work']['attempts'], [], 'recover left the crashed attempt unsettled')
        first = settled['status']['attempts'][0]
        self.assertEqual(first['state'], 'finished')
        self.assertNotEqual(first['outcome'], 'success', 'interruption relabelled as success')
        self.assertNotEqual(first['attribution'], 'semantic', 'a crash counted as a code failure')
        self.assertTrue((Path(held['cwd']) / held['partial']).exists(), 'partial work was discarded')
        self.assertTrue(self.state_contains(held['session']), 'raw log of the interrupted attempt lost')
        before_retry = time.time_ns()

        codes, report = self.drive()
        tasks = {t['id']: t for t in report['status']['tasks']}
        self.assertEqual(tasks['T']['state'], 'accepted', self.explain(f'run outcomes {codes}', report))
        self.assertEqual(codes[-1], 0)
        self.assertEqual(tasks['T']['failures'], 0)
        attempts = [a for a in report['status']['attempts'] if a['role'] == 'implement']
        self.assertEqual(attempts[0]['outcome'], first['outcome'], 'settled interruption was rewritten')
        self.assertEqual(sum(a['outcome'] == 'success' for a in attempts), 1)
        retries = [r for r in self.events('start') if r['role'] == 'implement' and r['ns'] > before_retry]
        self.assertTrue(retries, 'no retry after recovery')
        for row in retries:
            self.assertEqual(row['alive_peers'] if 'alive_peers' in row else [], [])
        for row in self.events('end'):
            if row['role'] == 'implement':
                self.assertEqual(row.get('alive_peers', []), [], 'duplicate concurrent implementer')
        commits = [e for e in report['status']['effects'] if e['kind'] == 'task.commit' and e['state'] == 'done']
        self.assertEqual(len(commits), 1, 'duplicate or missing task commit')
        self.assertEqual(report['owned_work']['effects'], [])
        review = self.reviews(lambda r: r['task_id'] == 'T' and r['envelope']['result_sha'] == tasks['T']['result'])
        self.assertTrue(review and review[-1]['verdict'] == 'PASS', 'required review skipped after restart')
        self.assertTrue(any(e['task_id'] == 'T' and e['kind'] == 'review' and e['passed'] == 1
                            for e in report['status']['evidence']))
        self.assert_check_receipts(report, 'T', tasks['T']['result'])
        self.assert_native_turns()
        self.assert_owner_boundaries(report)

    # ---- scenario 3 ----------------------------------------------------------------------

    def test_individually_passing_tasks_with_wrong_integration_are_not_accepted(self):
        self.profile('solo', 'claude', {'review_rule': 'unique_plugins', 'recipes': {
            'P': {'plugins/p.py': "NAME = 'shared'\n"}, 'Q': {'plugins/q.py': "NAME = 'shared'\n"}}})
        self.setup_controller({'plugins': self.check_argv('plugins')}, max_attempts=2)
        self.submit('combined', [task('P', ['plugins/p.py'], ['plugins']),
                                 task('Q', ['plugins/q.py'], ['plugins'])])
        codes, report = self.drive()
        self.assertNotEqual(codes[-1], 0,
                            self.explain('a known-defective integrated candidate ended PASS', report))
        self.assert_native_turns()
        for tid, own, other in (('P', 'plugins/p.py', 'plugins/q.py'), ('Q', 'plugins/q.py', 'plugins/p.py')):
            passed = self.reviews(lambda r, tid=tid: r['task_id'] == tid and r['verdict'] == 'PASS'
                                  and own in r['files'] and other not in r['files'])
            self.assertTrue(passed, f'{tid} never passed its own task-level review')
            self.assertTrue(any(e['task_id'] == tid and e['kind'] == 'check' and e['status'] == 'PASS'
                                for e in report['status']['evidence']), f'{tid} task checks never passed')
        combined = self.reviews(lambda r: 'plugins/p.py' in r['files'] and 'plugins/q.py' in r['files'])
        for row in combined:
            self.assertEqual(row['envelope']['base_sha'], self.origin_sha, 'whole review not bound to plan origin')
            self.assertEqual(row['verdict'], 'FAIL')
        failed_checks = [c for c in self.checks_run() if not c['ok']
                         and {'plugins/p.py', 'plugins/q.py'} <= set(c['files'])]
        self.assertTrue(combined or failed_checks, self.explain(
            f'no whole-result gate examined the combined result (run outcomes {codes})', report))
        peak, live = 0, 0
        for row in self.events():
            if row['event'] in ('start', 'end'):
                live += 1 if row['event'] == 'start' else -1
                peak = max(peak, live)
        self.assertEqual(peak, 1, 'default single account was not sequential')
        self.assert_owner_boundaries(report)

    # ---- scenario 4 ----------------------------------------------------------------------

    def test_unavailable_profiles_route_to_next_useful_profile(self):
        self.profile('quota', 'claude', {'mode': 'quota'})
        self.profile('auth', 'claude', {'mode': 'auth'})
        self.profile('useful', 'codex', {'recipes': {'T': {'tee.py': 'def value():\n    return 7\n'}},
                                         'hold': {'tasks': ['T'], 'timeout': 300}})
        self.setup_controller({}, auto_route=True)
        self.submit('routing', [task('T', ['tee.py'], [])])
        proc = self.start_run()
        self.wait_for(lambda: self.ready('useful', 'T'), 300, 'the useful profile to launch', proc)
        self.expect_cli(0, 'stop')
        at_stop = len(self.status()['status']['attempts'])
        self.go('useful', 'T')
        proc.wait(timeout=PASS_TIMEOUT)
        self._engine_present(self.proc_err(proc))

        starts = [r for r in self.events('start') if r['role'] == 'implement']
        self.assertEqual(starts[0]['profile'], 'quota', 'first profile in owner order was not tried first')
        self.assertIn('useful', [r['profile'] for r in starts])
        for row in self.events('end'):
            if row['profile'] in ('quota', 'auth'):
                self.assertIn(row['outcome'], ('quota_rejected', 'auth_failed'))
        report = self.status()
        status = report['status']
        tried = {r['profile'] for r in starts}
        observed = {o['profile_id']: o['data'] for o in status['observations']}
        self.assertEqual(observed['quota']['availability'], 'rate_limited')
        self.assertIsNone(observed['quota']['retry_at'], 'a quota reset time was invented')
        if 'auth' in tried:
            self.assertEqual(observed['auth']['availability'], 'auth_hold')
        for attempt in status['attempts']:
            self.assertNotEqual(attempt['attribution'], 'semantic', 'availability counted as code failure')
            if attempt['profile_id'] in ('quota', 'auth'):
                self.assertEqual((attempt['state'], attempt['attribution']), ('finished', 'availability'))
        self.assertEqual(status['tasks'][0]['failures'], 0)
        self.assertEqual(status['control'], 'stopped')
        self.assertEqual(len(status['attempts']), at_stop, 'a new attempt was claimed after STOP')
        self.assertEqual(self.reviews(), [], 'review launched after STOP')
        turns = len(self.events('start'))
        self.run_once()
        self.assertEqual(len(self.events('start')), turns, 'STOP did not survive a restart')
        self.assertEqual(self.status()['status']['control'], 'stopped')
        self.assert_native_turns()
        self.assert_owner_boundaries(report)

    # ---- scenario 5 ----------------------------------------------------------------------

    def test_persistent_stop_and_runtime_change_hold_until_explicit_reconcile(self):
        self.profile('solo', 'claude', {'recipes': {'S': {'ess.py': 'def value():\n    return 5\n'}},
                                        'hold': {'tasks': ['S'], 'once': True, 'timeout': 300}})
        self.setup_controller({'ess': self.check_argv('module', 'ess', '5')})
        self.submit('stopped', [task('S', ['ess.py'], ['ess'])])
        proc = self.start_run()
        self.wait_for(lambda: self.ready('solo', 'S'), 180, 'the implementer to start', proc)
        self.expect_cli(0, 'stop')
        self.go('solo', 'S')
        proc.wait(timeout=PASS_TIMEOUT)
        self._engine_present(self.proc_err(proc))

        def frozen():
            report = self.status()
            status = report['status']
            return report, len(self.events('start')), [(a['id'], a['state'], a['outcome']) for a in status['attempts']]

        report, turns, attempts = frozen()
        status = report['status']
        self.assertEqual(status['control'], 'stopped')
        self.assertEqual(turns, 1)
        self.assertEqual([a['role'] for a in status['attempts']], ['implement'], 'claims after STOP')
        self.assertTrue({e['kind'] for e in status['effects']} <= {'worktree.create', 'worktree.remove'},
                        'a mutation effect ran after STOP')
        self.assertEqual(report['owned_work']['attempts'], [], 'STOP drain left attempts unsettled')
        self.run_once()
        self.assertEqual(frozen()[1:], (turns, attempts), 'restart under STOP launched or rewrote work')

        contract = self.runtime.parent / 'references' / 'task-contract.md'
        contract.write_bytes(contract.read_bytes() + b'\n')
        held = self.status()
        self.assertEqual(held['identity_check']['runtime'], 'differs')
        before = held['status']
        self.expect_cli(0, 'recover', timeout=PASS_TIMEOUT)
        self.assertNotEqual(self.run_once().returncode, 0, 'run accepted a changed runtime')
        self.expect_cli(0, 'resume')
        self.assertNotEqual(self.run_once().returncode, 0, 'run accepted a changed runtime')
        self.assertEqual(frozen()[1:], (turns, attempts), 'context hold launched or rewrote work')
        self.expect_cli(1, 'reconcile', '--actor', 'fixture-owner')
        self.assertEqual(self.status()['status']['epoch'], before['epoch'], 'reconcile ran without STOP')

        self.expect_cli(0, 'stop')
        self.expect_cli(0, 'reconcile', '--actor', 'fixture-owner')
        after = self.status()
        self.assertEqual(after['status']['epoch'], before['epoch'] + 1)
        self.assertEqual(after['status']['policy_digest'], before['policy_digest'])
        self.assertEqual(after['status']['control'], 'stopped', 'reconcile cleared STOP')
        self.assertEqual(after['status']['charged_seconds'], before['charged_seconds'], 'charged time lost')
        self.assertEqual(after['status']['attempts'], before['attempts'], 'attempt history changed')
        self.assertEqual(after['identity_check']['runtime'], 'match')
        self.assertTrue(all(p['stale'] for p in after['plans']))
        contexts = self.ledger(lambda ledger: ledger.contexts())
        self.assertEqual([c['epoch'] for c in contexts], [1, 2], 'context history not append-only')
        self.run_once()
        self.assertEqual(frozen()[1:], (turns, attempts), 'work started under STOP after reconcile')
        self.expect_cli(0, 'resume')
        self.run_once()
        self.assertEqual(frozen()[1], turns, 'stale plan ran without an explicit readmit')
        self.expect_cli(0, 'stop')
        self.assert_owner_boundaries(self.status())


if __name__ == '__main__':
    unittest.main()
