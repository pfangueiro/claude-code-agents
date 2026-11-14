"""Behavioural tests for the controller ledger: real SQLite, a real temporary Git
repository, real executables and competing processes. Every policy, plan and authority
is first accepted by the controller_inputs boundary. No model, provider or network calls."""
import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / '.claude' / 'skills' / 'delivery' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import controller_effects as fx  # noqa: E402
import controller_inputs as ci  # noqa: E402
import controller_ledger as cl  # noqa: E402
import controller_routing as cr  # noqa: E402

R0, R1, R2, R3 = ('0' * 40, '1' * 40, '2' * 40, '3' * 40)
T1, T2 = ('a' * 40, 'c' * 40)
_PRELUDE = r'''
import sys
sys.path.insert(0, sys.argv[1])
import controller_ledger as mod
'''
HOLDER = _PRELUDE + r'''
import json
with mod.ControllerLock(sys.argv[2], sys.argv[3], json.loads(sys.argv[4])) as led:
    if len(sys.argv) > 5:
        attempt = led.claim(sys.argv[5], 'alpha')
        led.record_launch(attempt['id'], {'pid': 4242})
    print('held', led.fence, flush=True)
    sys.stdin.readline()
'''
CONTENDER = _PRELUDE + r'''
try:
    with mod.ControllerLock(sys.argv[2], sys.argv[3]) as led:
        print('ok', led.fence)
except mod.LedgerError as err:
    print(err.code)
'''
CHILD = r'''
import sys
if sys.stdin.readline().strip() == 'go':
    open(sys.argv[1], 'w').close()
'''


def task(tid, deps=(), scope=None, resources=()):
    return {'id': tid, 'objective': 'Do the work', 'kind': 'feature', 'depends_on': list(deps),
            'write_scope': list(scope or ['src/' + tid]), 'resources': list(resources),
            'checks': ['unit'], 'acceptance': ['works']}


def task_row(led, tid):
    return next(row for row in led.status()['tasks'] if row['id'] == tid)


def fingerprint(directory):
    out = {}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            info = os.stat(path)
            out[name] = (info.st_size, info.st_mtime_ns, hashlib.sha256(Path(path).read_bytes()).hexdigest())
    return out


@unittest.skipUnless(shutil.which('git'), 'git is required')
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='ledger-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, 'repo')
        self.git('init', '-q', self.repo)
        Path(self.repo, 'AGENTS.md').write_text('rules\n')
        self.git('-C', self.repo, 'add', '-A')
        self.git('-C', self.repo, 'commit', '-q', '-m', 'init')
        self.base = self.git('-C', self.repo, 'rev-parse', 'HEAD')
        self.common = self.common_of(self.repo)
        self.state = os.path.join(self.tmp, 'state')
        self.tool = os.path.join(self.tmp, 'tool')
        Path(self.tool).write_text('#!/bin/sh\nexit 0\n')
        os.chmod(self.tool, 0o755)
        self.ident = {'runtime': ci.runtime_digest(SCRIPTS),
                      'rules': ci.rules_digest(self.repo, self.base, ['AGENTS.md'])}

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        done = subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                              env=env, check=True, capture_output=True, text=True)
        return done.stdout.strip()

    def common_of(self, worktree):
        return os.path.realpath(os.path.join(worktree, self.git('-C', worktree, 'rev-parse', '--git-common-dir')))

    def profile(self, pid, roles=('implement', 'review'), provider='claude'):
        config = os.path.join(self.tmp, 'cfg-' + pid)
        os.makedirs(config, mode=0o700, exist_ok=True)
        return {'id': pid, 'provider': provider, 'executable': self.tool, 'config_dir': config,
                'roles': list(roles)}

    def reviewers(self):
        """Two Claude profiles plus a configured Codex review profile. Simulated policy state:
        the executable is the fixture tool and no native Codex is ever run."""
        return [self.profile('alpha'), self.profile('beta'), self.profile('codex', ('review',), 'codex')]

    def raw_policy(self, **over):
        limits = {'max_attempts': 3, 'attempt_seconds': 100, 'max_total_seconds': 10000,
                  'max_no_progress': 3, 'max_cost_usd': None}
        limits.update(over.pop('limits', {}))
        base = {
            'version': 1, 'repository': self.repo,
            'profiles': [self.profile('alpha'), self.profile('beta')],
            'auto_route': False, 'execution_enabled': True, 'background_enabled': False,
            'max_parallel': 2, 'review_reserve': 1, 'limits': limits,
            'allowed_checks': {'unit': [self.tool, 'run']}, 'effects': ['commit', 'integrate'],
            'delivery': None, 'instruction_paths': ['AGENTS.md'],
        }
        base.update(over)
        return base

    def policy(self, **over):
        return ci.validate_policy(self.raw_policy(**over))

    @staticmethod
    def delivery():
        return {'remote': 'origin', 'remote_url': 'https://github.com/example-org/example-repo.git',
                'github_repo': 'example-org/example-repo', 'base_branch': 'main',
                'branch_prefix': 'sdlc/', 'required_checks': ['build'], 'merge_method': 'squash'}

    def raw_plan(self, tasks, pid='p1', objective='Ship it'):
        return {'version': 1, 'id': pid, 'objective': objective, 'input_revision': 'r1',
                'base_sha': self.base, 'tasks': tasks}

    def raw_authority(self, plan, effects=('commit',), authorizer='Owner',
                      approved_at='2026-01-01T00:00:00Z'):
        return {'version': 1, 'plan_digest': ci.canonical_digest(plan), 'effects': list(effects),
                'authorizer': authorizer, 'approved_at': approved_at}

    def fresh_authority(self, led, pid='p1', effects=('commit',)):
        """A new owner declaration, approved now, for the saved unchanged plan."""
        stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        return self.raw_authority(led.plan(pid)['body'], effects, approved_at=stamp)

    def submit(self, led, tasks, pid='p1', effects=('commit',)):
        """Submit, then bind every dependency-free task at the plan origin so it can be claimed."""
        plan = ci.validate_plan(self.raw_plan(tasks, pid), led.policy)
        authority = ci.validate_authority(self.raw_authority(plan, effects), led.policy, plan)
        plan_digest = led.submit(plan, authority, dict(self.ident))
        for item in tasks:
            if not item['depends_on']:
                self.bind(led, item['id'])
        return plan_digest

    def workspace(self, tid, number=1):
        return {'path': os.path.join(self.state, cl.WORKSPACE_DIR, f'{tid}-{number}'),
                'cleanup_id': f'ws-{tid}-{number}'}

    def proof(self, base, *results):
        """Simulated positive engine checkpoint facts: ledger state only, not a Git proof."""
        return {'checkpoint': base, 'confirmed': True,
                'ancestors': {sha: True for sha in (self.base, *results)}}

    def is_ancestor(self, older, newer):
        try:
            self.git('-C', self.repo, 'merge-base', '--is-ancestor', older, newer)
        except subprocess.CalledProcessError:
            return False
        return True

    def observed(self, base, *results):
        """Checkpoint facts as the engine would observe them, from the real fixture repository."""
        return {'checkpoint': base, 'confirmed': True,
                'ancestors': {sha: self.is_ancestor(sha, base) for sha in (self.base, *results)}}

    def commit(self, name):
        """A real commit on top of the fixture repository; returns its full id."""
        target = Path(self.repo, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(name + '\n')
        self.git('-C', self.repo, 'add', '-A')
        self.git('-C', self.repo, 'commit', '-q', '-m', name)
        return self.git('-C', self.repo, 'rev-parse', 'HEAD')

    def bind(self, led, tid, base=None, deps=None, number=1):
        base, deps = base or self.base, dict(deps or {})
        return led.bind_execution(tid, base, deps, self.workspace(tid, number),
                                  self.proof(base, *deps.values()))

    def gate(self, led, result, base=None):
        return {'result': result, 'base': base or self.base, 'policy': led.policy_digest, **led.identity}

    def accept(self, led, tid, result, base=None, implementer='alpha', reviewer='beta'):
        """Drive one bound task through every gate to accepted (ledger state only)."""
        led.finish_attempt(self.released(led, tid, implementer)['id'], 'success', True, result=result)
        gate = self.gate(led, result, base)
        self.check(led, tid, gate)
        review = self.released(led, tid, reviewer, 'review')
        led.finish_attempt(review['id'], 'success', True)
        led.record_review(tid, review['id'], 'approve', gate)
        led.transition(tid, 'reviewed', 'accepted', gate)
        return gate

    def init(self, **over):
        cl.initialize(self.state, self.policy(**over), self.common, dict(self.ident)).close()

    def lock(self):
        return cl.ControllerLock(self.common, self.state, dict(self.ident))

    def code(self, call, *args, **kwargs):
        with self.assertRaises(cl.LedgerError) as caught:
            call(*args, **kwargs)
        return caught.exception.code

    def operator(self, state):
        led = cl.Ledger.open(self.state)
        try:
            led.set_control(state)
        finally:
            led.close()

    def spawn(self, script, *args):
        proc = subprocess.Popen([sys.executable, '-c', script, str(SCRIPTS), *args], text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(proc.communicate)
        self.addCleanup(proc.kill)
        return proc

    def holder(self, *extra):
        proc = self.spawn(HOLDER, self.common, self.state, json.dumps(self.ident), *extra)
        line = proc.stdout.readline().split()
        if line[:1] != ['held']:
            self.fail('holder did not start: ' + proc.stderr.read())
        return proc, int(line[1])

    def contend(self, common, state):
        return self.spawn(CONTENDER, common, state).communicate(timeout=60)[0].strip()

    def held_child(self, marker):
        """A real child that does its work only when told to go."""
        proc = subprocess.Popen([sys.executable, '-c', CHILD, marker], text=True, stdin=subprocess.PIPE)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        return proc

    def release(self, led, attempt):
        """Ledger state only: reserved -> launched -> released. The retained identity is this
        test process's own pid; no provider or native execution is claimed."""
        led.record_launch(attempt['id'], {'pid': os.getpid()})
        return led.authorize_release(attempt['id'])

    def released(self, led, task_id, profile, role='implement'):
        return self.release(led, led.claim(task_id, profile, role))

    @staticmethod
    def receipt(result):
        """A simulated closed receipt reference: digests of fixture bytes, not of a real run."""
        return {'schema': cl.RECEIPT_SCHEMA,
                'receipt_sha256': hashlib.sha256(b'receipt ' + result.encode()).hexdigest(),
                'lifecycle_sha256': hashlib.sha256(b'lifecycle ' + result.encode()).hexdigest(),
                'input_sha': result}

    def run_check(self, led, tid, name='unit'):
        """Ledger state only: a reserved, launched, released and cleanly finished local check
        attempt charged zero seconds. No check command is executed."""
        attempt = self.release(led, led.claim_check(tid, name))
        return led.finish_attempt(attempt['id'], 'success', True, used_seconds=0)

    def check(self, led, tid, gate, status='PASS', name='unit', finalize=True, attempt=None):
        """Record one explicit check outcome on a simulated check attempt, then aggregate."""
        attempt = attempt or self.run_check(led, tid, name)
        led.record_check_outcome(tid, name, status, gate, self.receipt(gate['result']), attempt['id'])
        return led.finalize_checks(tid, gate) if finalize else attempt

    def plan_ws(self, pid='p1', number=1):
        """Registration arguments of a plan-owned integration workspace inside the state."""
        return {'path': os.path.join(self.state, cl.WORKSPACE_DIR, f'plan-{pid}-{number}'),
                'cleanup_id': f'ws-plan-{pid}-{number}', 'branch': f'sdlc/{pid}-integration-{number}',
                'base_sha': self.base}

    def ws_spec(self, ws, kind, head=None):
        """The journal envelope the engine records: top metadata plus the real adapter mapping."""
        if kind == 'worktree.create':
            inner = fx.WorktreeCreateSpec(repo=self.repo, common_dir=self.common, branch=ws['branch'],
                                          path=ws['path'], base_sha=ws['base_sha'])
        else:
            inner = fx.WorktreeRemoveSpec(repo=self.repo, common_dir=self.common,
                                          cleanup_root=os.path.join(self.state, cl.WORKSPACE_DIR),
                                          path=ws['path'], branch=ws['branch'],
                                          expected_head=head or ws['base_sha'])
        return {**ws, 'fx': fx.spec_to_mapping(inner)}

    def integrate_spec(self, ws, expected, result):
        """The integrate journal envelope with the real IntegrateSpec mapping (fast-forward)."""
        inner = fx.IntegrateSpec(repo=self.repo, common_dir=self.common, integration_worktree=ws['path'],
                                 target_branch=ws['branch'], expected_base=expected, task_branch='sdlc/task',
                                 task_result=result, strategy=fx.FAST_FORWARD, message='')
        return {'expected_base': expected, 'result': result, 'branch': ws['branch'],
                'fx': fx.spec_to_mapping(inner)}

    def seen_ws(self, ws, head, contributions, real=False):
        """Workspace facts as the engine would report them. Head, branch and path are
        simulated positive state; with ``real`` the ancestry is observed from the fixture
        repository. Neither is a native observation of a worktree."""
        return {'confirmed': True, 'head': head, 'branch': ws['branch'], 'path': ws['path'],
                'ancestors': {sha: self.is_ancestor(sha, head) if real else True
                              for sha in (self.base, *contributions.values())}}

    def open_plan(self, led, pid='p1', number=1):
        """State-unit: register the plan workspace, journal a simulated confirmed creation and
        record the initial checkpoint. No worktree is created. Returns the creation effect."""
        ws = self.plan_ws(pid, number)
        led.register_plan_workspace(pid, **ws)
        created = led.plan_effect_intent(pid, 'worktree.create', self.ws_spec(ws, 'worktree.create'))
        led.effect_result(created, 'done')
        led.record_checkpoint(pid, None, self.base, {}, created, self.seen_ws(ws, self.base, {}))
        return created

    def integrate(self, led, tid, head=None, pid='p1', number=1, real=False):
        """State-unit: journal one simulated confirmed integration of the accepted task on the
        current checkpoint and record the checkpoint it yields. ``head`` defaults to the task
        result (a fast-forward). No merge runs here. Returns the integration effect."""
        ws, current, result = self.plan_ws(pid, number), led.checkpoint(pid), led.task(tid)['result']
        effect = led.effect_intent(tid, 'integrate', self.integrate_spec(ws, current['sha'], result))
        led.effect_result(effect, 'done')
        head, contributions = head or result, {**current['contributions'], tid: result}
        led.record_checkpoint(pid, current['sha'], head, contributions, effect,
                              self.seen_ws(ws, head, contributions, real))
        return effect

    def facts(self, result, contributions, effects, real=False):
        """Integration facts as the engine would report them. Simulated positive state by
        default; with ``real`` the ancestry is observed from the fixture repository. Neither
        is a native integration proof."""
        return {'checkpoint': result, 'confirmed': True, 'owned': True,
                'ancestors': {sha: self.is_ancestor(sha, result) if real else True
                              for sha in (self.base, *contributions.values())},
                'integrations': dict(effects)}

    def derive(self, led, result, contributions, effects, checks=('unit',), number=1, pid='p1',
               real=False):
        return led.create_candidate(pid, result, dict(contributions), list(checks),
                                    self.workspace('cand-' + pid, number),
                                    self.facts(result, contributions, effects, real))

    def accept_candidate(self, led, view, reviewer='codex'):
        """Drive a derived candidate through its own checks and a fresh review to accepted
        (ledger state only). The default reviewer is the simulated configured Codex profile;
        no native Codex review is claimed."""
        gate = self.gate(led, view['result'])
        for name in view['checks']:
            self.check(led, view['id'], gate, name=name)
        review = self.released(led, view['id'], reviewer, 'review')
        led.finish_attempt(review['id'], 'success', True)
        led.record_review(view['id'], review['id'], 'approve', gate)
        led.transition(view['id'], 'reviewed', 'accepted', gate)
        return gate

    @staticmethod
    def lane(led, tid, role, check=None):
        return next(row for row in led.status()['dispatch']
                    if (row['task_id'], row['role'], row['check']) == (tid, role, check))

    @staticmethod
    def obs(category='success', ended=None):
        """A routing observation from the real normalizer, ended in the recent past."""
        ended = int(time.time()) - 60 if ended is None else ended
        return cr.observation_from_outcome('claude', category, None, ended, ended)


class StateFileTests(Base):
    def test_init_is_private_and_reinit_preserves_policy_and_counters(self):
        self.init()
        modes = [stat.S_IMODE(os.stat(os.path.join(self.state, name)).st_mode)
                 for name in ('', cl.POLICY_FILE, cl.LEDGER_FILE)]
        self.assertEqual(modes, [0o700, 0o600, 0o600])
        with self.lock() as led:
            self.submit(led, [task('a')])
            led.finish_attempt(led.claim('a', 'alpha')['id'], 'failure', True)
        snapshot = Path(self.state, cl.POLICY_FILE).read_bytes()

        self.init()
        self.assertEqual(self.code(cl.initialize, self.state, self.policy(max_parallel=3), self.common,
                                   self.ident), 'policy_changed')
        changed = dict(self.ident, runtime='f' * 64)
        self.assertEqual(self.code(cl.initialize, self.state, self.policy(), self.common, changed),
                         'identity_changed')
        self.assertEqual(self.code(cl.initialize, self.state, self.policy(), self.common,
                                   {'runtime': 'rt-1', 'rules': 'rules-1'}), 'identity')
        self.assertEqual(Path(self.state, cl.POLICY_FILE).read_bytes(), snapshot)
        led = cl.Ledger.open(self.state, readonly=True)
        self.addCleanup(led.close)
        row = task_row(led, 'a')
        self.assertEqual((row['attempts'], row['failures'], row['no_progress']), (1, 1, 1))
        self.assertEqual(led.status()['charged_seconds'], 100)

    def test_readonly_status_writes_nothing_and_leaves_no_sidecars(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a')])
        before = (fingerprint(self.state), fingerprint(self.common))
        led = cl.Ledger.open(self.state, readonly=True)
        self.assertEqual(led.status()['control'], 'running')
        self.assertEqual(led.owned_work()['attempts'], [])
        self.assertEqual(self.code(led.set_control, 'stopped'), 'readonly')
        self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'readonly')
        self.assertEqual(sorted(os.listdir(self.state)), [cl.LEDGER_FILE, cl.POLICY_FILE])
        led.close()
        self.assertEqual((fingerprint(self.state), fingerprint(self.common)), before)
        self.assertEqual(self.git('-C', self.repo, 'status', '--porcelain'), '')

    def test_unsafe_locations_and_unvalidated_policies_are_refused(self):
        real = os.path.join(self.tmp, 'real')
        os.mkdir(real)
        os.symlink(real, os.path.join(self.tmp, 'link'))
        attempts = {
            'symlink': os.path.join(self.tmp, 'link', 'state'),
            'inside_repository': os.path.join(self.repo, 'state'),
            'path': 'relative/state',
        }
        for expected, state in attempts.items():
            self.assertEqual(self.code(cl.initialize, state, self.policy(), self.common, self.ident), expected)
        linked = os.path.join(self.tmp, 'wt')
        self.git('-C', self.repo, 'worktree', 'add', '-q', '-b', 'wt', linked)
        self.assertEqual(self.code(cl.initialize, os.path.join(linked, 'state'), self.policy(), self.common,
                                   self.ident), 'inside_repository')

        capped = self.raw_policy(limits={'max_cost_usd': 5})
        boundary_invalid = dict(self.raw_policy(), allowed_checks=['unit'])
        for bad in (capped, boundary_invalid):
            self.assertEqual(self.code(cl.initialize, self.state, bad, self.common, self.ident), 'policy_invalid')
        alias = os.path.join(self.tmp, 'cfg-alias')
        os.symlink(self.profile('alpha')['config_dir'], alias)
        unfrozen = self.raw_policy(profiles=[dict(self.profile('alpha'), config_dir=alias)],
                                   max_parallel=1, review_reserve=0)
        self.assertEqual(self.code(cl.initialize, self.state, unfrozen, self.common, self.ident),
                         'policy_not_frozen')
        other = os.path.join(self.tmp, 'other-repo')
        self.git('init', '-q', other)
        self.assertEqual(self.code(cl.initialize, self.state, self.policy(), self.common_of(other), self.ident),
                         'repository_mismatch')
        self.assertFalse(os.path.exists(os.path.join(self.common, cl.BINDING_FILE)))
        self.assertFalse(os.path.exists(self.state))

    def test_insecure_corrupt_and_unsupported_state_is_refused(self):
        self.init()
        ledger = os.path.join(self.state, cl.LEDGER_FILE)
        policy_file = os.path.join(self.state, cl.POLICY_FILE)
        for path, loose, tight in ((self.state, 0o755, 0o700), (ledger, 0o644, 0o600), (policy_file, 0o640, 0o600)):
            os.chmod(path, loose)
            self.assertEqual(self.code(cl.Ledger.open, self.state, readonly=True), 'insecure')
            os.chmod(path, tight)

        db = sqlite3.connect(ledger)
        db.execute(f'PRAGMA user_version={cl.SCHEMA_VERSION + 1}')
        db.close()
        self.assertEqual(self.code(cl.Ledger.open, self.state), 'unsupported_schema')
        self.assertEqual(self.code(cl.initialize, self.state, self.policy(), self.common, self.ident),
                         'unsupported_schema')
        db = sqlite3.connect(ledger)
        db.execute(f'PRAGMA user_version={cl.SCHEMA_VERSION}')
        db.close()
        cl.Ledger.open(self.state).close()

        original = Path(policy_file).read_bytes()
        self.assertIn(b'"max_parallel":2', original)
        Path(policy_file).write_bytes(original.replace(b'"max_parallel":2', b'"max_parallel":8'))
        self.assertEqual(self.code(cl.Ledger.open, self.state), 'corrupt')
        Path(policy_file).write_bytes(original)
        Path(ledger).write_bytes(b'not a database' * 20)
        self.assertEqual(self.code(cl.Ledger.open, self.state), 'corrupt')


class BoundaryTests(Base):
    """Cross-module: objects the input boundary accepts are the objects the store takes."""

    def test_unicode_plan_approved_at_the_boundary_submits(self):
        self.init()
        with self.lock() as led:
            tasks = [dict(task('a'), objective='Vérifier le café ☕')]
            plan = ci.validate_plan(self.raw_plan(tasks, objective='Corriger la régression'), led.policy)
            authority = ci.validate_authority(self.raw_authority(plan, authorizer='Zoë'), led.policy, plan)
            self.assertEqual(cl.digest(plan), ci.canonical_digest(plan))
            self.assertEqual(led.submit(plan, authority, dict(self.ident)), ci.canonical_digest(plan))
            self.assertEqual(led.submit(plan, authority, dict(self.ident)), authority['plan_digest'])
            self.assertEqual(task_row(led, 'a')['state'], 'pending')
        raw = sqlite3.connect(os.path.join(self.state, cl.LEDGER_FILE))
        self.addCleanup(raw.close)
        body, stored = raw.execute('SELECT body, authority FROM plans').fetchone()
        self.assertEqual(body, ci.canonical_json(plan))
        self.assertIn('régression', body)
        self.assertEqual(json.loads(stored)['authorizer'], 'Zoë')

    def test_submit_refuses_what_the_boundary_refuses(self):
        self.init()
        with self.lock() as led:
            plan = self.raw_plan([task('x')], pid='px')
            forged = dict(self.raw_authority(plan), plan_digest='0' * 64)
            self.assertEqual(self.code(led.submit, plan, forged, self.ident), 'authority_mismatch')
            partial = {'plan_digest': ci.canonical_digest(plan), 'effects': [], 'authorizer': 'Owner',
                       'approved_at': 'now'}
            self.assertEqual(self.code(led.submit, plan, partial, self.ident), 'authority_invalid')
            widened = self.raw_authority(plan, effects=('push',))
            self.assertEqual(self.code(led.submit, plan, widened, self.ident), 'effect_unauthorized')
            self.assertEqual(self.code(led.submit, self.raw_plan([], pid='px'), forged, self.ident), 'plan_invalid')
            unlisted = self.raw_plan([dict(task('x'), checks=['lint'])], pid='px')
            self.assertEqual(self.code(led.submit, unlisted, self.raw_authority(unlisted), self.ident),
                             'plan_invalid')
            other = dict(self.ident, rules='e' * 64)
            self.assertEqual(self.code(led.submit, plan, self.raw_authority(plan), other), 'identity_changed')
            self.assertEqual(led.status()['tasks'], [])
            self.submit(led, [task('x')], pid='px')
            self.assertEqual(self.code(self.submit, led, [task('x'), task('y')], 'px'), 'plan_changed')
            self.assertEqual(self.code(self.submit, led, [task('x')], 'py'), 'task_ids')
            self.assertEqual(self.code(led.observe, 'alpha', {'load': float('nan')}), 'metadata')

    def test_default_profile_is_frozen_and_a_new_environment_is_refused(self):
        home = os.path.join(self.tmp, 'home')
        default, other = os.path.join(home, '.claude'), os.path.join(self.tmp, 'other-account')
        os.makedirs(default, mode=0o700)
        os.makedirs(other, mode=0o700)
        raw = self.raw_policy(profiles=[dict(self.profile('main'), config_dir=None)],
                              max_parallel=1, review_reserve=0)
        with mock.patch.dict(os.environ, {'HOME': home}):
            os.environ.pop('CLAUDE_CONFIG_DIR', None)
            frozen = ci.validate_policy(raw)
            self.assertEqual(frozen['profiles'][0]['config_dir'], default)
            self.assertEqual(self.code(cl.initialize, self.state, raw, self.common, self.ident),
                             'policy_not_frozen')
            cl.initialize(self.state, frozen, self.common, dict(self.ident)).close()

            os.environ['CLAUDE_CONFIG_DIR'] = other
            moved = ci.validate_policy(raw)
            self.assertEqual(moved['profiles'][0]['config_dir'], other)
            self.assertEqual(self.code(cl.initialize, self.state, moved, self.common, self.ident),
                             'policy_changed')
            led = cl.initialize(self.state, frozen, self.common, dict(self.ident))
            self.addCleanup(led.close)
            self.assertEqual(led.policy['profiles'][0]['config_dir'], default)
            with self.lock() as owner:
                self.submit(owner, [task('a')])
                self.assertEqual(owner.claim('a', 'main')['profile_id'], 'main')


class AuthorityTests(Base):
    def test_competing_processes_and_state_dirs_get_one_authority(self):
        self.init()
        linked = os.path.join(self.tmp, 'wt')
        self.git('-C', self.repo, 'worktree', 'add', '-q', '-b', 'wt', linked)
        linked_common = self.common_of(linked)
        other_state = os.path.join(self.tmp, 'state2')

        proc, fence = self.holder()
        self.assertEqual(self.contend(self.common, self.state), 'locked')
        self.assertEqual(self.contend(linked_common, self.state), 'locked')
        self.assertEqual(self.code(self.lock().__enter__), 'locked')
        self.assertEqual(self.code(cl.initialize, other_state, self.policy(), linked_common, self.ident), 'locked')
        proc.stdin.write('\n')
        proc.stdin.flush()
        proc.wait(timeout=60)

        self.assertEqual(self.contend(linked_common, self.state), f'ok {fence + 1}')
        self.assertEqual(self.code(cl.initialize, other_state, self.policy(), self.common, self.ident),
                         'bound_elsewhere')
        self.assertEqual(self.contend(self.common, other_state), 'bound_elsewhere')
        self.assertFalse(os.path.exists(other_state))
        self.assertEqual(self.git('-C', self.repo, 'status', '--porcelain'), '')

    def test_killed_controller_leaves_attempt_reserved_across_restarts(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
        proc, fence = self.holder('a')
        proc.kill()
        proc.wait(timeout=60)

        with self.lock() as led:
            self.assertEqual(led.fence, fence + 1)
            attempt = led.status()['attempts'][0]
            self.assertEqual((attempt['state'], attempt['fence'], attempt['launch'], attempt['released_at']),
                             ('launched', fence, {'pid': 4242}, None))
            self.assertEqual(self.code(led.claim, 'a', 'beta'), 'task_state')
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'task_state')
            held = led.finish_attempt(attempt['id'], 'success', reconciled=False)
            self.assertEqual(held['state'], 'unknown')
            self.assertEqual(self.code(led.authorize_release, attempt['id']), 'conflict')
        with self.lock() as led:
            self.assertEqual(led.status()['attempts'][0]['state'], 'unknown')
            self.assertEqual(task_row(led, 'a')['state'], 'implementing')
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'task_state')
            self.assertEqual(led.status()['charged_seconds'], 100)
            self.assertEqual(led.owned_work()['attempts'][0]['launch'], {'pid': 4242})
            led.finish_attempt(attempt['id'], 'failure', reconciled=True)
            self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True, R1), 'conflict')
            led.claim('a', 'alpha')
            self.assertEqual(task_row(led, 'a')['attempts'], 2)

    def test_superseded_writer_is_fenced_out(self):
        self.init()
        with self.lock() as stale:
            self.submit(stale, [task('a'), task('b')])
            os.unlink(os.path.join(self.common, cl.LOCK_FILE))  # foreign cleanup of the lock
            with self.lock() as current:
                self.assertEqual(current.fence, stale.fence + 1)
                self.assertEqual(self.code(stale.claim, 'a', 'alpha'), 'lease_lost')
                self.assertEqual(self.code(stale.effect_intent, 'a', 'task.commit', {}), 'lease_lost')
                self.assertEqual(self.code(stale.observe, 'alpha', self.obs()), 'lease_lost')
                self.assertEqual(self.code(stale.helper), 'lease_lost')
                attempt = current.claim('a', 'alpha')
                self.assertEqual(self.code(stale.finish_attempt, attempt['id'], 'failure', True), 'lease_lost')
                self.assertEqual(task_row(current, 'a')['state'], 'implementing')

    def test_live_lock_with_a_superseded_fence_is_still_refused(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a')])
            raw = sqlite3.connect(os.path.join(self.state, cl.LEDGER_FILE))
            raw.execute('UPDATE controller SET fence = fence + 1')
            raw.commit()
            raw.close()
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'stale_fence')
            self.assertEqual(led.status()['attempts'], [])

    def test_helper_cannot_write_once_owner_lease_is_gone_even_before_takeover(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            helper = led.helper()
            self.addCleanup(helper.close)
            self.assertEqual(helper.fence, led.fence)
            first = helper.claim('a', 'alpha')
            fence = led.fence

        reader = cl.Ledger.open(self.state, readonly=True)
        self.addCleanup(reader.close)
        self.assertEqual(reader.status()['fence'], fence)  # no takeover: the integer still matches
        self.assertEqual(self.code(helper.claim, 'b', 'beta'), 'lease_lost')
        self.assertEqual(self.code(helper.finish_attempt, first['id'], 'failure', True), 'lease_lost')
        self.assertEqual(self.code(helper.helper), 'lease_lost')

        borrowed = cl.Ledger.open(self.state)
        self.addCleanup(borrowed.close)
        with self.assertRaises(AttributeError):
            borrowed.fence = fence
        self.assertIsNone(borrowed.fence)
        self.assertEqual(self.code(borrowed.claim, 'b', 'beta'), 'lease_required')
        self.assertEqual(self.code(borrowed.helper), 'lease_required')
        self.assertEqual([row['state'] for row in reader.status()['attempts']], ['reserved'])
        self.assertEqual(borrowed.set_control('paused'), 'paused')  # operator needs no lease
        self.assertEqual(borrowed.status()['control'], 'paused')

    @unittest.skipUnless(hasattr(os, 'fork'), 'fork is required')
    def test_forked_child_does_not_inherit_the_lease(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a')])
            read_end, write_end = os.pipe()
            pid = os.fork()
            if pid == 0:
                outcome = 'wrote'
                try:
                    led.claim('a', 'alpha')
                except cl.LedgerError as err:
                    outcome = err.code
                except BaseException:
                    outcome = 'error'
                finally:
                    os.write(write_end, outcome.encode())
                    os._exit(0)
            os.close(write_end)
            os.waitpid(pid, 0)
            reported = os.read(read_end, 64)
            os.close(read_end)
            self.assertEqual(reported, b'lease_lost')
            self.assertEqual(led.status()['attempts'], [])
            self.assertEqual(led.claim('a', 'alpha')['state'], 'reserved')


class ClaimTests(Base):
    def test_dependencies_resources_and_parent_scopes_block_claims(self):
        self.init(profiles=[self.profile('alpha'), self.profile('beta'), self.profile('gamma')], max_parallel=3)
        with self.lock() as led:
            self.submit(led, [task('a', scope=['src/app'], resources=['db']), task('b', scope=['src/app/models']),
                              task('c', scope=['docs'], resources=['db']), task('d', deps=['a']),
                              task('e', scope=['src/application'])])
            self.assertEqual(self.code(led.claim, 'd', 'alpha'), 'dependencies')
            self.assertEqual(self.code(led.claim, 'a', 'alpha', 'audit'), 'profile_role')
            led.claim('a', 'alpha')
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'scope_conflict')
            self.assertEqual(self.code(led.claim, 'c', 'beta'), 'resource_conflict')
            self.assertEqual(self.code(led.claim, 'a', 'beta'), 'task_state')
            self.assertEqual(led.claim('e', 'alpha')['state'], 'reserved')  # sibling prefix, same profile
            self.assertEqual(self.code(led.claim, 'e', 'beta'), 'task_state')

    def run_parallel_claims(self, led, names):
        results, barrier = [], threading.Barrier(len(names))

        def worker(name):
            helper = led.helper()
            try:
                barrier.wait()
                helper.claim('t-' + name, name)
                results.append('ok')
            except cl.LedgerError as err:
                results.append(err.code)
            finally:
                helper.close()

        threads = [threading.Thread(target=worker, args=(name,)) for name in names]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return sorted(results)

    def test_concurrent_claims_never_exceed_capacity(self):
        names = [f'p{i}' for i in range(6)]
        self.init(profiles=[self.profile(name) for name in names], max_parallel=2)
        with self.lock() as led:
            self.submit(led, [task('t-' + name) for name in names])
            self.assertEqual(self.run_parallel_claims(led, names), ['capacity'] * 4 + ['ok'] * 2)
            self.assertEqual(len(led.status()['attempts']), 2)
            self.assertEqual(led.status()['charged_seconds'], 200)

    def test_concurrent_claims_for_one_delivery_honor_its_cap(self):
        names = [f'p{i}' for i in range(6)]
        self.init(profiles=[self.profile(name) for name in names + ['spare']], max_parallel=8,
                  limits={'max_total_seconds': 250})
        with self.lock() as led:
            self.submit(led, [task('t-' + name) for name in names])
            self.submit(led, [task('solo')], pid='p2')
            self.assertEqual(self.run_parallel_claims(led, names), ['ok'] * 2 + ['time_budget'] * 4)
            self.assertEqual(led.claim('solo', 'spare')['state'], 'reserved')
            self.assertEqual([(b['plan_id'], b['held_seconds']) for b in led.status()['budgets']],
                             [('p1', 200), ('p2', 100)])

    def test_each_delivery_has_its_own_budget_and_history_is_kept(self):
        self.init(limits={'max_total_seconds': 150})
        with self.lock() as led:
            self.submit(led, [task('a')], pid='p1')
            self.submit(led, [task('b')], pid='p2')
            led.finish_attempt(led.claim('a', 'alpha')['id'], 'failure', True, used_seconds=60)
            second = led.claim('b', 'beta')  # plan 2 keeps its approved budget
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'time_budget')  # plan 1: 60 + 100 > 150
            led.finish_attempt(second['id'], 'success', False)  # unknown: reservation stays charged
        with self.lock() as led:
            status = led.status()
            self.assertEqual(status['budgets'], [
                {'plan_id': 'p1', 'used_seconds': 60, 'held_seconds': 0, 'charged_seconds': 60,
                 'limit_seconds': 150},
                {'plan_id': 'p2', 'used_seconds': 0, 'held_seconds': 100, 'charged_seconds': 100,
                 'limit_seconds': 150}])
            self.assertEqual(status['charged_seconds'], 160)
            self.assertEqual([a['used_seconds'] for a in status['attempts']], [60, None])
            led.finish_attempt(second['id'], 'failure', True, used_seconds=100)
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'time_budget')

    def test_review_reserve_keeps_a_slot_for_checked_work(self):
        self.init(profiles=[self.profile('alpha'), self.profile('beta'), self.profile('gamma')])
        with self.lock() as led:
            self.submit(led, [task('a'), task('b'), task('c')])
            led.finish_attempt(self.released(led, 'a', 'alpha')['id'], 'success', True, result=R1)
            self.check(led, 'a', self.gate(led, R1))
            led.claim('b', 'alpha')
            self.assertEqual(self.code(led.claim, 'c', 'beta'), 'capacity')
            self.assertEqual(led.claim('a', 'beta', 'review')['role'], 'review')

    def make_checked(self, led, task_id, profile, result):
        led.finish_attempt(self.released(led, task_id, profile)['id'], 'success', True, result=result)
        self.check(led, task_id, self.gate(led, result))
        self.assertEqual(task_row(led, task_id)['state'], 'checked')

    def test_one_profile_runs_concurrent_sessions_up_to_max_parallel(self):
        self.init(profiles=[self.profile('solo')], max_parallel=2, review_reserve=0)
        with self.lock() as led:
            self.submit(led, [task('a'), task('b'), task('c')])
            first, second = led.claim('a', 'solo'), led.claim('b', 'solo')
            self.assertNotEqual(first['id'], second['id'])
            self.assertEqual([(row['profile_id'], row['state']) for row in (first, second)],
                             [('solo', 'reserved')] * 2)
            self.assertEqual(self.code(led.claim, 'c', 'solo'), 'capacity')  # the global cap holds
            self.assertEqual(self.code(led.claim, 'a', 'solo'), 'task_state')  # one attempt per task
            self.assertEqual(led.status()['charged_seconds'], 200)
            self.assertEqual(len(led.status()['attempts']), 2)
            led.finish_attempt(first['id'], 'failure', True)
            self.assertEqual(led.claim('c', 'solo')['state'], 'reserved')  # only a freed slot is reused

    def test_one_profile_with_max_parallel_one_stays_sequential(self):
        self.init(profiles=[self.profile('solo')], max_parallel=1, review_reserve=0)
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            first = led.claim('a', 'solo')
            self.assertEqual(self.code(led.claim, 'b', 'solo'), 'capacity')
            self.assertEqual(len(led.status()['attempts']), 1)
            led.finish_attempt(first['id'], 'success', False)  # unknown still holds the only slot
            self.assertEqual(self.code(led.claim, 'b', 'solo'), 'capacity')
            led.finish_attempt(first['id'], 'failure', True)
            self.assertEqual(led.claim('b', 'solo')['state'], 'reserved')

    def test_one_profile_still_honors_write_scope_exclusion(self):
        self.init(profiles=[self.profile('solo')], max_parallel=3, review_reserve=0)
        with self.lock() as led:
            self.submit(led, [task('a', scope=['src/app']), task('b', scope=['src/app/models']),
                              task('c', scope=['docs'])])
            led.claim('a', 'solo')
            self.assertEqual(self.code(led.claim, 'b', 'solo'), 'scope_conflict')
            self.assertEqual(led.claim('c', 'solo')['state'], 'reserved')  # disjoint scope runs alongside
            self.assertEqual(task_row(led, 'b')['state'], 'pending')

    def test_one_profile_implements_and_reviews_at_once_within_the_reserve(self):
        self.init(profiles=[self.profile('solo')], max_parallel=2, review_reserve=1)
        with self.lock() as led:
            self.submit(led, [task('a'), task('b'), task('c')])
            self.make_checked(led, 'a', 'solo', R1)
            led.claim('b', 'solo')
            self.assertEqual(self.code(led.claim, 'c', 'solo'), 'capacity')  # slot kept for the review
            review = led.claim('a', 'solo', 'review')
            self.assertEqual((review['role'], review['profile_id'], review['state']),
                             ('review', 'solo', 'reserved'))
            self.assertEqual(self.code(led.claim, 'a', 'solo', 'review'), 'task_busy')
            self.assertEqual(self.code(led.claim, 'c', 'solo'), 'capacity')  # both slots are in use
            self.release(led, review)
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('a', review['id'], 'approve', self.gate(led, R1))
            self.assertEqual(task_row(led, 'a')['state'], 'reviewed')
            self.assertEqual(led.claim('c', 'solo')['state'], 'reserved')

    def test_declared_resources_exclude_active_reviewers_in_both_directions(self):
        self.init(profiles=[self.profile('solo')], max_parallel=3, review_reserve=0)
        with self.lock() as led:
            self.submit(led, [task('a', scope=['src/a'], resources=['db']),
                              task('c', scope=['docs'], resources=['db']), task('d', scope=['src/d'])])
            self.make_checked(led, 'a', 'solo', R1)
            implementer = led.claim('c', 'solo')
            self.assertEqual(self.code(led.claim, 'a', 'solo', 'review'), 'resource_conflict')
            led.finish_attempt(implementer['id'], 'failure', True)
            review = led.claim('a', 'solo', 'review')
            self.assertEqual(self.code(led.claim, 'c', 'solo'), 'resource_conflict')  # reviewer holds db
            self.assertEqual(task_row(led, 'c')['state'], 'pending')
            self.assertEqual(led.claim('d', 'solo')['state'], 'reserved')  # no declared resource shared
            self.release(led, review)
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('a', review['id'], 'approve', self.gate(led, R1))
            self.assertEqual(led.claim('c', 'solo')['state'], 'reserved')

    def test_single_profile_implements_then_reviews_through_separate_gates(self):
        self.init(profiles=[self.profile('solo')], max_parallel=1, review_reserve=0)
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            attempt = led.claim('a', 'solo')
            self.assertEqual(self.code(led.record_launch, attempt['id'], {'note': 'no pid'}), 'launch_identity')
            led.record_launch(attempt['id'], {'pid': 7})
            self.assertEqual(self.code(led.record_launch, attempt['id'], {'pid': 8}), 'conflict')
            self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True, R1), 'not_released')
            led.authorize_release(attempt['id'])
            self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True), 'result_required')
            led.finish_attempt(attempt['id'], 'success', True, result=R1)
            self.assertEqual(task_row(led, 'a')['state'], 'implemented')
            self.assertEqual(self.code(led.transition, 'a', 'implemented', 'accepted', self.gate(led, R1)),
                             'transition')

            self.assertEqual(self.code(led.claim_check, 'a', 'lint'), 'check_not_allowed')
            run = self.release(led, led.claim_check('a', 'unit'))
            self.assertEqual(self.code(led.claim, 'b', 'solo'), 'capacity')  # a running check holds the slot
            led.finish_attempt(run['id'], 'success', True, used_seconds=0)
            record = led.record_check_outcome
            self.assertEqual(self.code(record, 'a', 'unit', 'PASS', self.gate(led, R0), self.receipt(R0),
                                       run['id']), 'stale_identity')
            self.assertEqual(self.code(record, 'a', 'lint', 'PASS', self.gate(led, R1), self.receipt(R1),
                                       run['id']), 'check_not_allowed')
            self.check(led, 'a', self.gate(led, R1), attempt=run)
            self.assertEqual(task_row(led, 'a')['state'], 'checked')
            self.assertEqual(self.code(led.transition, 'a', 'reviewed', 'accepted', self.gate(led, R1)), 'gates')

            self.assertEqual(self.code(led.record_review, 'a', attempt['id'], 'approve', self.gate(led, R1)),
                             'review_attempt')
            review = self.released(led, 'a', 'solo', 'review')
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('a', review['id'], 'approve', self.gate(led, R1))
            self.assertEqual(task_row(led, 'a')['state'], 'reviewed')

            stale = dict(self.gate(led, R1), rules='e' * 64)
            self.assertEqual(self.code(led.transition, 'a', 'reviewed', 'accepted', stale), 'stale_identity')
            led.transition('a', 'reviewed', 'accepted', self.gate(led, R1))
            self.assertEqual(self.code(led.transition, 'a', 'reviewed', 'accepted', self.gate(led, R1)), 'conflict')
            led.transition('a', 'accepted', 'published', self.gate(led, R1))
            self.assertEqual(led.claim('b', 'solo')['role'], 'implement')

            kinds = [event['kind'] for event in led.events()]
            for kind in ('submit', 'claim', 'launch', 'release', 'finish', 'check', 'review', 'transition'):
                self.assertIn(kind, kinds)
        raw = sqlite3.connect(os.path.join(self.state, cl.LEDGER_FILE))
        self.addCleanup(raw.close)
        for statement in ('DELETE FROM events', "UPDATE events SET kind = 'x'", 'DELETE FROM attempts',
                          'DELETE FROM evidence'):
            with self.assertRaises(sqlite3.DatabaseError):
                raw.execute(statement)

    def test_gates_take_exact_types_and_full_identities_only(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a')])
            attempt = led.claim('a', 'alpha')
            for bad in ('false', 'true', 0, 1, None):
                self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', bad, R1), 'strict_type')
            for bad in (-1, -0.5, True, float('nan'), float('inf'), '5', 10 ** 12, 10 ** 400):
                self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'failure', True, None, bad),
                                 'used_seconds')
            for bad in ('r1', R1[:39], 'A' * 40, '', 5):
                self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True, bad),
                                 'result_identity')
            status = led.status()
            self.assertEqual((status['attempts'][0]['state'], status['charged_seconds']), ('reserved', 100))
            self.assertEqual(task_row(led, 'a')['failures'], 0)

            self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True, R1), 'not_released')
            self.release(led, attempt)
            done = led.finish_attempt(attempt['id'], 'success', True, R1, used_seconds=0.2)
            self.assertEqual((done['used_seconds'], led.status()['charged_seconds']), (1, 1))
            good = self.gate(led, R1)
            run, receipt, record = self.run_check(led, 'a'), self.receipt(R1), led.record_check_outcome
            for bad in ('pass', 'true', True, 1, None):
                self.assertEqual(self.code(record, 'a', 'unit', bad, good, receipt, run['id']), 'check_status')
            partial = {key: value for key, value in good.items() if key != 'rules'}
            for bad in (partial, dict(good, extra='x'), dict(good, result=None), list(good), None):
                self.assertEqual(self.code(record, 'a', 'unit', 'PASS', bad, receipt, run['id']),
                                 'stale_identity')
            self.assertEqual(led.status()['evidence'], [])
            self.assertEqual(task_row(led, 'a')['state'], 'implemented')
            self.check(led, 'a', good, attempt=run)
            self.assertEqual(task_row(led, 'a')['state'], 'checked')
            self.assertEqual(self.code(led.transition, 'a', 'reviewed', 'accepted', good), 'gates')

    def test_stop_and_pause_are_durable_operator_controls(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            running = self.released(led, 'a', 'alpha')
            self.operator('paused')
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'control_paused')
            led.finish_attempt(running['id'], 'success', True, result=R1)  # pause drains
            self.assertEqual(self.code(led.claim_check, 'a', 'unit'), 'control_paused')  # no new launch
            self.operator('stopped')
            self.assertEqual(led.control(), 'stopped')
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'control_stopped')
            self.assertEqual(self.code(led.effect_intent, 'a', 'task.commit', {'ref': 'x'}), 'control_stopped')
            self.assertEqual(self.code(self.submit, led, [task('c')], 'p2'), 'control_stopped')
        reader = cl.Ledger.open(self.state, readonly=True)
        self.assertEqual(reader.status()['control'], 'stopped')
        reader.close()
        self.init()
        with self.lock() as led:
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'control_stopped')
            self.assertEqual(self.code(led.set_control, 'resume'), 'control')
            led.set_control('running')
            self.assertEqual(led.claim('b', 'beta')['state'], 'reserved')
            self.assertEqual([e['ref'] for e in led.events() if e['kind'] == 'control'],
                             ['paused', 'stopped', 'running'])

    def test_attempt_and_time_counters_survive_retry_and_restart(self):
        limits = {'max_attempts': 2, 'max_total_seconds': 250, 'max_no_progress': 9}
        self.init(limits=limits)
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            led.finish_attempt(led.claim('a', 'alpha')['id'], 'failure', True, used_seconds=40)
            self.assertEqual(led.status()['charged_seconds'], 40)
        with self.lock() as led:
            led.finish_attempt(led.claim('a', 'alpha')['id'], 'failure', True)
            self.assertEqual(led.status()['charged_seconds'], 140)
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'attempts_exhausted')
            overrun = led.finish_attempt(led.claim('b', 'beta')['id'], 'failure', True, used_seconds=999)
            self.assertEqual((overrun['reserved_seconds'], overrun['used_seconds']), (100, 999))
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'time_budget')
        self.init(limits=limits)
        with self.lock() as led:
            row = task_row(led, 'a')
            self.assertEqual((row['attempts'], row['failures'], row['no_progress']), (2, 2, 2))
            self.assertEqual(led.status()['budgets'][0]['used_seconds'], 1139)
            self.assertEqual(self.code(led.claim, 'a', 'beta'), 'attempts_exhausted')


class ProgressTests(Base):
    def checked(self, led, profile, result):
        led.finish_attempt(self.released(led, 'a', profile)['id'], 'success', True, result=result)
        self.check(led, 'a', self.gate(led, result))

    def test_verified_progress_clears_the_streak_but_not_history(self):
        self.init(limits={'max_attempts': 6, 'max_no_progress': 2})
        with self.lock() as led:
            self.submit(led, [task('a')])
            led.finish_attempt(led.claim('a', 'alpha')['id'], 'failure', True)
            self.assertEqual(self.code(led.note_progress, 'a', T1, 'nothing verified'), 'progress_unverified')
            self.checked(led, 'alpha', R1)
            self.assertEqual(task_row(led, 'a')['no_progress'], 1)  # a result alone resets nothing
            for bad in ('tree', T1[:12], None):
                self.assertEqual(self.code(led.note_progress, 'a', bad, 'reason'), 'fingerprint')
            self.assertEqual(self.code(led.note_progress, 'a', T1, '  '), 'reason')
            self.assertTrue(led.note_progress('a', T1, 'unit passed on a new scoped tree'))
            row = task_row(led, 'a')
            self.assertEqual((row['failures'], row['no_progress'], row['progress']), (1, 0, T1))

            led.finish_attempt(led.claim('a', 'beta', 'review')['id'], 'failure', True)  # process failure
            row = task_row(led, 'a')
            # Every launch is counted: two implementations, the local check and the review.
            self.assertEqual((row['failures'], row['no_progress'], row['attempts']), (2, 1, 4))
            retry = led.claim('a', 'beta', 'review')  # one failure after real progress is not exhaustion
            led.finish_attempt(retry['id'], 'failure', True)
            self.assertEqual(self.code(led.claim, 'a', 'beta', 'review'), 'no_progress_limit')
            self.assertFalse(led.note_progress('a', T2, 'same result claimed again'))
            self.assertFalse(led.note_progress('a', T1, 'same tree claimed again'))
        with self.lock() as led:  # a restart alone never resets the streak
            row = task_row(led, 'a')
            self.assertEqual((row['failures'], row['no_progress'], row['progress']), (3, 2, T1))
            self.assertEqual(self.code(led.claim, 'a', 'beta', 'review'), 'no_progress_limit')
            marks = led.status()['progress']
            self.assertEqual([(m['fingerprint'], m['result'], m['cleared']) for m in marks], [(T1, R1, 1)])
            noted = [e['data'] for e in led.events() if e['kind'] == 'progress']
            self.assertEqual(noted, [{'fingerprint': T1, 'result': R1, 'cleared': 1,
                                      'reason': 'unit passed on a new scoped tree'}])

    def test_empty_commit_churn_and_failed_checks_are_not_progress(self):
        self.init(limits={'max_attempts': 6, 'max_no_progress': 3})
        with self.lock() as led:
            self.submit(led, [task('a')])
            self.checked(led, 'alpha', R1)
            self.assertTrue(led.note_progress('a', T1, 'first verified tree'))
            review = self.released(led, 'a', 'beta', 'review')
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('a', review['id'], 'reject', self.gate(led, R1))
            self.assertEqual(self.code(led.note_progress, 'a', T2, 'rejected work'), 'progress_unverified')

            self.checked(led, 'alpha', R2)  # new commit id, identical tree
            self.assertFalse(led.note_progress('a', T1, 'empty commit'))
            self.assertEqual(task_row(led, 'a')['no_progress'], 1)
            self.assertEqual([e['kind'] for e in led.events() if e['kind'].startswith('progress')],
                             ['progress', 'progress_repeat'])

            review = self.released(led, 'a', 'beta', 'review')
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('a', review['id'], 'reject', self.gate(led, R2))
            led.finish_attempt(self.released(led, 'a', 'alpha')['id'], 'success', True, result=R3)
            self.check(led, 'a', self.gate(led, R3), 'FAIL')
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['failures'], row['no_progress'], row['result']),
                             ('pending', 3, 3, None))
            self.assertEqual(self.code(led.note_progress, 'a', T2, 'failing check'), 'progress_unverified')
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'no_progress_limit')
            self.assertEqual(len(led.status()['evidence']), 5)


class StopTests(Base):
    def setUp(self):
        super().setUp()
        self.init()
        self.marker = os.path.join(self.tmp, 'child-ran')

    def test_stop_between_claim_and_spawn_leaves_nothing_to_launch(self):
        with self.lock() as led:
            self.submit(led, [task('a')])
            attempt = led.claim('a', 'alpha')
            self.operator('stopped')
            self.assertEqual(led.control(), 'stopped')  # the engine checks before spawning
            self.assertEqual(self.code(led.authorize_release, attempt['id']), 'conflict')
            self.assertEqual([a['id'] for a in led.owned_work()['attempts']], [attempt['id']])
            self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True, R1), 'not_released')
            led.finish_attempt(attempt['id'], 'cancelled', True, used_seconds=0,
                               attribution='operator', reason='stop')  # cleanup is allowed
            self.assertEqual(led.owned_work()['attempts'], [])
            self.assertEqual(led.status()['charged_seconds'], 0)

    def test_stop_between_spawn_and_release_keeps_identity_and_denies_release(self):
        with self.lock() as led:
            self.submit(led, [task('a')])
            attempt = led.claim('a', 'alpha')
            child = self.held_child(self.marker)
            self.operator('stopped')  # STOP lands after the spawn, before the metadata write

            launched = led.record_launch(attempt['id'], {'pid': child.pid, 'argv0': 'child'})
            self.assertEqual((launched['state'], launched['released_at']), ('launched', None))
            self.assertEqual(self.code(led.authorize_release, attempt['id']), 'control_stopped')
            self.assertEqual(self.code(led.authorize_release, attempt['id']), 'control_stopped')
            owned = led.owned_work()
            self.assertEqual(owned['control'], 'stopped')
            self.assertEqual([(a['launch']['pid'], a['released_at']) for a in owned['attempts']],
                             [(child.pid, None)])
            self.assertEqual([e['kind'] for e in led.events() if e['kind'].startswith('release')],
                             ['release_denied', 'release_denied'])

            child.kill()  # owned cleanup of the tracked, never-released child
            child.wait(timeout=60)
            self.assertFalse(os.path.exists(self.marker))
            led.finish_attempt(attempt['id'], 'cancelled', True, used_seconds=1,
                               attribution='operator', reason='stop')
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['failures'], row['no_progress']), ('pending', 0, 0))
            self.assertEqual(led.owned_work()['attempts'], [])
        with self.lock() as led:
            self.assertEqual(led.control(), 'stopped')
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'control_stopped')

    def test_release_is_a_separate_grant_and_stop_does_not_roll_back_released_work(self):
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            held = led.claim('a', 'alpha')
            child = self.held_child(self.marker)
            led.record_launch(held['id'], {'pid': child.pid})
            self.assertIsNone(led.status()['attempts'][0]['released_at'])  # metadata is not a release

            self.operator('paused')
            self.assertEqual(self.code(led.authorize_release, held['id']), 'control_paused')
            self.operator('running')
            self.assertIsNotNone(led.authorize_release(held['id'])['released_at'])
            self.assertEqual(self.code(led.authorize_release, held['id']), 'conflict')
            child.stdin.write('go\n')
            child.stdin.flush()

            self.operator('stopped')  # bounded: released work is in flight, not undone
            owned = led.owned_work()['attempts']
            self.assertEqual([(a['id'], a['state'], a['launch']) for a in owned],
                             [(held['id'], 'launched', {'pid': child.pid})])
            self.assertIsNotNone(owned[0]['released_at'])
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'control_stopped')
            self.assertEqual(child.wait(timeout=60), 0)
            self.assertTrue(os.path.exists(self.marker))
            led.finish_attempt(held['id'], 'success', True, result=R1, used_seconds=2)
            self.assertEqual(task_row(led, 'a')['state'], 'implemented')
            self.assertEqual(led.owned_work()['attempts'], [])

    def test_stop_before_release_blocks_success_but_never_cleanup(self):
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            launched, reserved = led.claim('a', 'alpha'), led.claim('b', 'beta')
            led.record_launch(launched['id'], {'pid': os.getpid()})
            self.operator('stopped')  # STOP lands between launch and release

            self.assertEqual(self.code(led.authorize_release, launched['id']), 'control_stopped')
            self.assertEqual(self.code(led.finish_attempt, launched['id'], 'success', True, R1), 'not_released')
            self.assertEqual(task_row(led, 'a')['state'], 'implementing')
            self.assertEqual([(a['id'], a['state'], a['released_at']) for a in led.owned_work()['attempts']],
                             [(launched['id'], 'launched', None), (reserved['id'], 'reserved', None)])
            closed = led.finish_attempt(launched['id'], 'cancelled', True, used_seconds=0,
                                        attribution='operator', reason='stop')
            self.assertEqual((closed['state'], closed['outcome'], closed['released_at']),
                             ('finished', 'cancelled', None))

            # Metadata written after STOP retains ownership for cleanup and grants nothing.
            kept = led.record_launch(reserved['id'], {'pid': os.getpid(), 'argv0': 'late'})
            self.assertEqual((kept['state'], kept['released_at']), ('launched', None))
            self.assertEqual(self.code(led.authorize_release, reserved['id']), 'control_stopped')
            self.assertEqual(self.code(led.finish_attempt, reserved['id'], 'success', True, R2), 'not_released')
            self.assertEqual(led.finish_attempt(reserved['id'], 'success', False)['state'], 'unknown')
            self.assertEqual([(a['id'], a['state'], a['launch'], a['released_at'])
                              for a in led.owned_work()['attempts']],
                             [(reserved['id'], 'unknown', {'pid': os.getpid(), 'argv0': 'late'}, None)])
            self.assertEqual(self.code(led.finish_attempt, reserved['id'], 'success', True, R2), 'not_released')
            led.finish_attempt(reserved['id'], 'failure', True, used_seconds=0)

            self.assertEqual(led.owned_work()['attempts'], [])
            self.assertEqual([(row['state'], row['result']) for row in led.status()['tasks']],
                             [('pending', None)] * 2)
            self.assertEqual([e['kind'] for e in led.events() if e['kind'].startswith('release')],
                             ['release_denied', 'release_denied'])
            self.assertEqual([e['data']['outcome'] for e in led.events() if e['kind'] == 'finish'],
                             ['cancelled', 'failure'])
            self.assertEqual(led.status()['evidence'], [])

    def test_a_stop_is_never_replaced_by_a_pause_decided_on_an_earlier_read(self):
        stale = cl.Ledger.open(self.state)
        self.addCleanup(stale.close)
        self.assertEqual(stale.control(), 'running')  # the pre-read a pause was decided on
        self.operator('stopped')  # STOP lands on another connection first
        self.assertEqual(self.code(stale.set_control, 'paused'), 'control_stopped')
        self.assertEqual(stale.control(), 'stopped')
        with self.lock() as led:  # a restarted controller never resumes on its own
            self.assertEqual(led.control(), 'stopped')
            self.assertEqual(self.code(led.set_control, 'paused'), 'control_stopped')
            self.assertEqual([e['ref'] for e in led.events() if e['kind'] == 'control'], ['stopped'])
        self.assertEqual(stale.set_control('stopped'), 'stopped')
        self.assertEqual(stale.set_control('running'), 'running')  # only an explicit resume clears it
        self.assertEqual(stale.set_control('paused'), 'paused')

        def racer(state, outcomes, barrier):
            connection = cl.Ledger.open(self.state)
            try:
                barrier.wait()
                outcomes.append(connection.set_control(state))
            except cl.LedgerError as err:
                outcomes.append(err.code)
            finally:
                connection.close()

        for _ in range(5):  # whichever of two racing connections commits first, STOP stays
            self.operator('running')
            outcomes, barrier = [], threading.Barrier(2)
            threads = [threading.Thread(target=racer, args=(state, outcomes, barrier))
                       for state in ('paused', 'stopped')]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(stale.control(), 'stopped')
            self.assertIn(sorted(outcomes), (['control_stopped', 'stopped'], ['paused', 'stopped']))


class AdmissionTests(Base):
    """Success is admitted only for an attempt that is launched, retains a positive launch
    identity and was released by authorize_release. The pids recorded here are this test
    process's own: ledger state only, no provider or native execution is claimed."""

    def test_reserved_or_unreleased_implementation_cannot_succeed_or_be_accepted(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a')])
            attempt = led.claim('a', 'alpha')
            good = self.gate(led, R1)
            self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True, R1), 'not_released')
            self.assertEqual(led.status()['attempts'][0]['state'], 'reserved')
            led.record_launch(attempt['id'], {'pid': os.getpid()})
            self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True, R1), 'not_released')

            row = led.status()['attempts'][0]
            self.assertEqual((row['state'], row['released_at'], row['outcome'], row['result']),
                             ('launched', None, None, None))
            self.assertEqual((task_row(led, 'a')['state'], task_row(led, 'a')['result']), ('implementing', None))
            self.assertEqual(self.code(led.claim_check, 'a', 'unit'), 'task_state')
            self.assertEqual(self.code(led.transition, 'a', 'reviewed', 'accepted', good), 'stale_identity')
            self.assertEqual(led.status()['evidence'], [])
            self.assertEqual(led.status()['charged_seconds'], 100)
            self.assertEqual([e['kind'] for e in led.events() if e['kind'] in ('finish', 'release')], [])

            led.authorize_release(attempt['id'])
            done = led.finish_attempt(attempt['id'], 'success', True, R1)
            self.assertEqual((done['state'], done['outcome'], done['launch']),
                             ('finished', 'success', {'pid': os.getpid()}))
            self.assertIsNotNone(done['released_at'])
            self.assertEqual(task_row(led, 'a')['state'], 'implemented')

    def test_reserved_or_unreleased_review_cannot_succeed_or_approve(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a')])
            implementer = self.released(led, 'a', 'alpha')
            led.finish_attempt(implementer['id'], 'success', True, result=R1)
            good = self.gate(led, R1)
            self.check(led, 'a', good)

            review = led.claim('a', 'beta', 'review')
            self.assertEqual(self.code(led.finish_attempt, review['id'], 'success', True), 'not_released')
            self.assertEqual(self.code(led.record_review, 'a', review['id'], 'approve', good), 'review_attempt')
            led.record_launch(review['id'], {'pid': os.getpid()})
            self.assertEqual(self.code(led.finish_attempt, review['id'], 'success', True), 'not_released')
            self.assertEqual(self.code(led.record_review, 'a', review['id'], 'approve', good), 'review_attempt')
            self.assertEqual(self.code(led.transition, 'a', 'reviewed', 'accepted', good), 'gates')
            self.assertEqual(task_row(led, 'a')['state'], 'checked')
            self.assertEqual([e['kind'] for e in led.status()['evidence']], ['check'])

            # Cleanup of the never-released review needs no release; success stays refused.
            self.assertEqual(led.finish_attempt(review['id'], 'success', False)['state'], 'unknown')
            self.assertEqual(self.code(led.finish_attempt, review['id'], 'success', True), 'not_released')
            led.finish_attempt(review['id'], 'failure', True)
            self.assertEqual(self.code(led.record_review, 'a', review['id'], 'approve', good), 'review_attempt')
            self.assertEqual(task_row(led, 'a')['state'], 'checked')

            final = self.released(led, 'a', 'beta', 'review')  # the final review is a fresh attempt
            self.assertGreater(final['id'], review['id'])
            led.finish_attempt(final['id'], 'success', True)
            self.assertEqual(self.code(led.record_review, 'a', review['id'], 'approve', good), 'review_attempt')
            led.record_review('a', final['id'], 'approve', good)
            led.transition('a', 'reviewed', 'accepted', good)
            self.assertEqual(task_row(led, 'a')['state'], 'accepted')

            attempts = led.status()['attempts']
            self.assertEqual([(a['role'], a['outcome'], a['released_at'] is not None) for a in attempts],
                             [('implement', 'success', True), ('check', 'success', True),
                              ('review', 'failure', False), ('review', 'success', True)])
            self.assertEqual([a['launch'] for a in attempts], [{'pid': os.getpid()}] * 4)
            self.assertEqual([e['ref'] for e in led.events() if e['kind'] == 'release'],
                             [str(implementer['id']), str(attempts[1]['id']), str(final['id'])])


class EffectTests(Base):
    def test_catalog_kinds_map_to_owner_effects_and_the_frozen_target(self):
        self.init(effects=['commit', 'integrate', 'push', 'pr', 'merge'], delivery=self.delivery(),
                  profiles=self.reviewers())
        branch = {'branch': 'sdlc/p1/a'}
        with self.lock() as led:
            self.submit(led, [task('a')], effects=('commit', 'integrate', 'push', 'pr'))
            self.submit(led, [task('z')], pid='p2', effects=())
            for kind in ('commit', 'pr', 'merge', 'deploy', 'worktree.prune', ['push']):
                self.assertEqual(self.code(led.effect_intent, 'a', kind, dict(branch)), 'effect_unauthorized')
            self.assertEqual(self.code(led.effect_intent, 'a', 'pr.merge', dict(branch)), 'effect_unauthorized')
            self.assertEqual(self.code(led.effect_intent, 'z', 'push', dict(branch)), 'effect_unauthorized')
            self.assertEqual(self.code(led.effect_intent, 'a', 'push', 'refs/heads/x'), 'effect_unauthorized')
            wrong = ({}, {'branch': 'main'}, {'branch': 'sdlc/'}, {'branch': 'feature/x'},
                     dict(branch, github_repo='other-org/other'),
                     dict(branch, remote_url='https://github.com/other-org/other.git'),
                     dict(branch, base_branch='release'), dict(branch, target={}))
            for spec in wrong:
                self.assertEqual(self.code(led.effect_intent, 'a', 'push', spec), 'effect_target')
            self.assertEqual(led.status()['effects'], [])

            commit = led.effect_intent('a', 'task.commit', {'message': 'work'})
            led.effect_result(commit, 'done', {'sha': R1})
            self.assertEqual(self.code(led.effect_intent, 'a', 'integrate', {}), 'task_state')
            self.assertEqual(self.code(led.effect_intent, 'a', 'push', dict(branch, remote='origin')),
                             'candidate_required')
            # Simulated state: the accepted task is integrated and a derived candidate accepted.
            self.accept(led, 'a', R1)
            opened = self.open_plan(led)
            merged = self.integrate(led, 'a', R2)
            view = self.derive(led, R2, {'a': R1}, {'a': merged})
            self.accept_candidate(led, view)
            cid, publish = view['id'], dict(branch, result=R2)
            first = led.effect_intent(cid, 'push', dict(publish, remote='origin'))
            self.assertEqual(led.status()['effects'][-1]['spec'],
                             {'branch': 'sdlc/p1/a', 'remote': 'origin', 'result': R2,
                              'target': self.delivery()})
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(publish)), 'effect_unresolved')
            led.effect_result(first, 'unknown')
            seen = self.obs()
            self.assertTrue(led.observe('alpha', seen)['admitted'])
            # Untyped metadata proves no availability and is not stored.
            self.assertEqual(self.code(led.observe, 'alpha', {'available': True, 'note': 'ok'}), 'metadata')
            self.assertEqual(self.code(led.observe, 'alpha', {'nested': {'x': 1}}), 'metadata')
            intents = [e['data'] for e in led.events() if e['kind'] == 'effect_intent' and 'task' in e['data']]
            self.assertEqual(intents, [{'task': 'a', 'kind': 'task.commit', 'effect': 'commit'},
                                       {'task': 'a', 'kind': 'integrate', 'effect': 'integrate'},
                                       {'task': cid, 'kind': 'push', 'effect': 'push'}])
        with self.lock() as led:
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(publish)), 'effect_unresolved')
            self.assertEqual(self.code(led.effect_reconcile, first, 'done', {}), 'outcome')
            led.effect_reconcile(first, 'failed', {'remote': 'ref absent'})
            self.assertEqual(self.code(led.effect_result, first, 'done'), 'conflict')
            second = led.effect_intent(cid, 'push', dict(publish))
            led.effect_result(second, 'done', {'sha': R2})
            pull = led.effect_intent(cid, 'pr.create', dict(publish))
            status = led.status()
            self.assertEqual([(e['id'], e['kind'], e['state']) for e in status['effects']],
                             [(commit, 'task.commit', 'done'), (opened, 'worktree.create', 'done'),
                              (merged, 'integrate', 'done'),
                              (first, 'push', 'failed'), (second, 'push', 'done'),
                              (pull, 'pr.create', 'intent')])
            self.assertEqual(status['observations'][0]['data'], seen)
            self.assertEqual([e['id'] for e in led.owned_work()['effects']], [pull])

    def test_worktree_effects_stay_inside_the_state_workspace_and_cleanup_survives_stop(self):
        self.init()
        root = os.path.join(self.state, cl.WORKSPACE_DIR)
        spec = {'path': os.path.join(root, 'a-1'), 'cleanup_id': 'ws-a-1'}
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')], effects=())
            self.assertEqual(self.code(led.effect_intent, 'a', 'push', {'branch': 'sdlc/x'}), 'effect_unauthorized')
            self.assertEqual(self.code(led.effect_intent, 'a', 'task.commit', {}), 'effect_unauthorized')
            outside = (os.path.join(self.repo, 'wt'), os.path.join(self.tmp, 'elsewhere'), root,
                       os.path.join(root, '..', 'escape'), os.path.join('workspaces', 'a-1'))
            for path in outside:
                self.assertEqual(self.code(led.effect_intent, 'a', 'worktree.create', dict(spec, path=path)),
                                 'effect_workspace')
            self.assertEqual(self.code(led.effect_intent, 'a', 'worktree.create', {'path': spec['path']}),
                             'effect_workspace')
            self.assertEqual(self.code(led.effect_intent, 'a', 'worktree.remove', dict(spec)), 'effect_unauthorized')

            created = led.effect_intent('a', 'worktree.create', dict(spec))
            self.assertEqual(led.status()['effects'][0]['spec'],
                             dict(spec, write_scope=['src/a'], execution_base=self.base))
            led.effect_result(created, 'done')
            self.assertEqual(self.code(led.effect_intent, 'a', 'worktree.remove', dict(spec, cleanup_id='other')),
                             'effect_unauthorized')
            self.assertEqual(self.code(led.effect_intent, 'b', 'worktree.remove', dict(spec)), 'effect_unauthorized')

            self.operator('stopped')
            self.assertEqual(self.code(led.effect_intent, 'b', 'worktree.create',
                                       {'path': os.path.join(root, 'b-1'), 'cleanup_id': 'ws-b-1'}),
                             'control_stopped')
            self.assertEqual(led.owned_work()['workspaces'], [
                {'effect_id': created, 'task_id': 'a', 'plan_id': 'p1', 'owner': 'task', 'state': 'done',
                 'path': spec['path'], 'cleanup_id': 'ws-a-1'}])
            removed = led.effect_intent('a', 'worktree.remove', dict(spec))  # owned cleanup under STOP
            led.effect_result(removed, 'done')
            self.assertEqual(led.owned_work()['workspaces'], [])
            kinds = [e['data']['kind'] for e in led.events() if e['kind'] == 'effect_intent']
            self.assertEqual(kinds, ['worktree.create', 'worktree.remove'])


class ContextTests(Base):
    """Context epochs: strict initialize, hold on mismatch, explicit reconcile and readmission.
    Identities and results here are ledger state; no provider or native execution is claimed."""

    KEPT = ('tasks', 'attempts', 'evidence', 'budgets', 'charged_seconds')

    def test_runtime_upgrade_holds_execution_until_an_explicit_reconcile(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b'), task('c')])
            gate = self.accept(led, 'a', R1)
            in_flight = led.claim('b', 'beta')
        upgraded = dict(self.ident, runtime='f' * 64)
        self.assertEqual(self.code(cl.initialize, self.state, self.policy(), self.common, upgraded),
                         'identity_changed')  # strict: initialize never reconfigures
        with cl.ControllerLock(self.common, self.state, upgraded) as led:
            self.assertEqual((led.identity, led.epoch, led.context()['hold']), (self.ident, 1, True))
            self.assertEqual(self.code(led.claim, 'c', 'alpha'), 'context_hold')
            self.assertEqual(self.code(led.transition, 'a', 'accepted', 'published', gate), 'context_hold')
            self.assertEqual(self.code(led.effect_intent, 'a', 'task.commit', {}), 'context_hold')
            self.assertEqual(self.code(led.reconcile_context, self.policy(), upgraded, 'operator'),
                             'control_required')
            self.operator('stopped')
            self.assertEqual(self.code(led.reconcile_context, self.policy(), upgraded, 'operator'),
                             'owned_work')
            led.finish_attempt(in_flight['id'], 'cancelled', True, used_seconds=7,
                               attribution='operator', reason='context_hold')  # cleanup under hold
            before = led.status()
            helper = led.helper()
            self.addCleanup(helper.close)

            self.assertEqual(led.reconcile_context(self.policy(), upgraded, 'operator'),
                             {'epoch': 2, 'changed': True, 'stale_plans': ['p1']})
            self.assertEqual(led.reconcile_context(self.policy(), upgraded, 'operator'),
                             {'epoch': 2, 'changed': False, 'stale_plans': []})
            after = led.status()
            self.assertEqual((led.identity, led.policy_digest, after['epoch'], after['control']),
                             (upgraded, before['policy_digest'], 2, 'stopped'))
            for key in self.KEPT:
                self.assertEqual(after[key], before[key], key)
            self.assertEqual([(c['epoch'], c['identity'], c['actor']) for c in led.contexts()],
                             [(1, self.ident, 'initialize'), (2, upgraded, 'operator')])
            self.assertEqual(sorted(os.listdir(self.state)), [cl.LEDGER_FILE, cl.POLICY_FILE])
            self.assertEqual(self.code(helper.claim, 'c', 'alpha'), 'context_changed')
            self.assertEqual(helper.status()['epoch'], 2)

            self.assertEqual(self.code(led.claim, 'c', 'alpha'), 'control_stopped')  # STOP is never cleared
            led.set_control('running')
            self.assertFalse(led.context()['hold'])
            self.assertEqual(self.code(led.claim, 'c', 'alpha'), 'plan_stale')
            self.assertEqual(self.code(led.transition, 'a', 'accepted', 'published', self.gate(led, R1)),
                             'plan_stale')
            self.assertTrue(led.plan('p1')['stale'])
            self.assertIsNone(led.task('a')['gate'])
        with self.lock() as led:  # the superseded runtime is now the one that is held
            self.assertTrue(led.context()['hold'])
            self.assertEqual(self.code(led.claim, 'c', 'alpha'), 'context_hold')

    def test_changed_policy_reconcile_keeps_history_and_old_acceptance_cannot_publish(self):
        self.init(effects=['commit'])
        original = self.policy(effects=['commit'])
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            old_gate = self.accept(led, 'a', R1)
            led.finish_attempt(led.claim('b', 'alpha')['id'], 'failure', True, used_seconds=30)
            old_digest, before = led.policy_digest, led.status()
            self.assertEqual(before['budgets'][0]['used_seconds'], 230)
            wider = self.policy(profiles=[self.profile('alpha'), self.profile('beta'), self.profile('gamma')],
                                effects=['commit', 'integrate'])
            self.operator('stopped')
            capped = self.raw_policy(limits={'max_cost_usd': 5})
            self.assertEqual(self.code(led.reconcile_context, capped, self.ident, 'Owner'), 'policy_invalid')
            self.assertEqual(self.code(led.reconcile_context, wider, {'runtime': 'x', 'rules': 'y'}, 'Owner'),
                             'identity')
            self.assertEqual(self.code(led.reconcile_context, wider, self.ident, '  '), 'actor')
            self.assertEqual(led.epoch, 1)

            out = led.reconcile_context(wider, dict(self.ident), 'Owner')
            self.assertEqual((out['epoch'], out['stale_plans'], led.control()), (2, ['p1'], 'stopped'))
            self.assertEqual(led.policy, wider)
            self.assertNotEqual(led.policy_digest, old_digest)
            epoch_file = f'policy-{led.policy_digest}.json'
            self.assertEqual(sorted(os.listdir(self.state)),
                             sorted([cl.LEDGER_FILE, cl.POLICY_FILE, epoch_file]))
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.state, epoch_file)).st_mode), 0o600)
            self.assertEqual(hashlib.sha256(Path(self.state, cl.POLICY_FILE).read_bytes()).hexdigest(),
                             old_digest)  # the earlier epoch's policy is preserved, not overwritten
            self.assertEqual((led.context(1)['policy'], led.context()['policy']), (original, wider))
            after = led.status()
            for key in self.KEPT:
                self.assertEqual(after[key], before[key], key)

            led.set_control('running')
            for gate in (old_gate, self.gate(led, R1)):
                self.assertEqual(self.code(led.transition, 'a', 'accepted', 'published', gate), 'plan_stale')
            self.assertEqual(self.code(led.claim, 'b', 'alpha'), 'plan_stale')
            for kind in ('task.commit', 'integrate'):
                self.assertEqual(self.code(led.effect_intent, 'a', kind, {}), 'plan_stale')

            plan = led.plan('p1')['body']
            self.assertEqual(self.code(led.readmit_plan, 'p1', self.raw_authority(plan), self.ident),
                             'authority_stale')  # the earlier declaration is never replayed
            forged = dict(self.fresh_authority(led), plan_digest='0' * 64)
            self.assertEqual(self.code(led.readmit_plan, 'p1', forged, self.ident), 'authority_mismatch')
            fresh = self.fresh_authority(led)
            self.assertEqual(self.code(led.readmit_plan, 'p1', fresh, dict(self.ident, rules='e' * 64)),
                             'identity_changed')
            self.assertEqual(self.code(led.readmit_plan, 'nope', fresh, self.ident), 'unknown_plan')
            self.assertEqual(led.readmit_plan('p1', fresh, dict(self.ident)),
                             {'status': 'readmitted', 'plan': 'p1', 'epoch': 2,
                              'tasks': {'a': 'implemented', 'b': 'pending'}})
            self.assertEqual(self.code(led.readmit_plan, 'p1', fresh, self.ident), 'plan_current')

            # The wider current policy adds nothing to the grant the plan was readmitted with.
            self.assertEqual(self.code(led.effect_intent, 'a', 'integrate', {}), 'effect_unauthorized')
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['result']), ('implemented', R1))
            row = task_row(led, 'b')
            self.assertEqual((row['attempts'], row['failures'], row['no_progress']), (1, 1, 1))
            self.assertEqual(led.status()['budgets'][0]['used_seconds'], 230)

            # The preserved result needs a fresh binding, fresh checks and a fresh review.
            new_gate = self.gate(led, R1)
            self.assertEqual(self.code(led.claim_check, 'a', 'unit'), 'binding_required')
            self.assertEqual(self.code(led.claim, 'b', 'alpha'), 'binding_required')
            self.assertEqual(self.code(led.bind_execution, 'a', R2, {}, self.workspace('a'), self.proof(R2)),
                             'binding_conflict')
            self.bind(led, 'a')
            self.assertEqual(self.code(led.transition, 'a', 'reviewed', 'accepted', new_gate), 'gates')
            self.check(led, 'a', new_gate)
            old_review = next(a['id'] for a in before['attempts'] if a['role'] == 'review')
            self.assertEqual(self.code(led.record_review, 'a', old_review, 'approve', new_gate),
                             'review_attempt')
            self.assertEqual(self.code(led.transition, 'a', 'reviewed', 'accepted', new_gate), 'gates')
            review = self.released(led, 'a', 'gamma', 'review')  # a profile only the new policy has
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('a', review['id'], 'approve', new_gate)
            led.transition('a', 'reviewed', 'accepted', new_gate)
            led.transition('a', 'accepted', 'published', new_gate)

            self.assertEqual([entry['epoch'] for entry in led.plan('p1')['admissions']], [1, 2])
            self.assertEqual([(e['kind'], e['epoch']) for e in led.status()['evidence']],
                             [('check', 1), ('review', 1), ('check', 2), ('review', 2)])
            kinds = [event['kind'] for event in led.events()]
            for kind in ('context_reconcile', 'readmit'):
                self.assertIn(kind, kinds)

    def test_readmission_holds_while_old_workspaces_remain(self):
        self.init()
        spec = self.workspace('a')
        with self.lock() as led:
            self.submit(led, [task('a')], effects=())
            led.effect_result(led.effect_intent('a', 'worktree.create', dict(spec)), 'done')
            self.operator('stopped')
            led.reconcile_context(self.policy(max_parallel=1, review_reserve=0), dict(self.ident), 'Owner')
            fresh = self.fresh_authority(led, effects=())

            held = led.readmit_plan('p1', fresh, dict(self.ident))
            self.assertEqual((held['status'], [w['path'] for w in held['workspaces']]), ('hold', [spec['path']]))
            self.assertTrue(led.plan('p1')['stale'])
            self.assertEqual(led.task('a')['binding']['workspace'], spec)  # nothing erased or overwritten

            led.effect_result(led.effect_intent('a', 'worktree.remove', dict(spec)), 'done')  # owned cleanup
            self.assertEqual(led.readmit_plan('p1', fresh, dict(self.ident))['tasks'], {'a': 'pending'})
            view = led.task('a')
            self.assertEqual((view['binding'], [b['state'] for b in view['bindings']], view['stale']),
                             (None, ['invalidated'], False))
            self.assertEqual(led.control(), 'stopped')  # readmission never resumes
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'control_stopped')
            kinds = [event['kind'] for event in led.events()]
            self.assertEqual([kind for kind in kinds if kind.startswith('readmit')], ['readmit_hold', 'readmit'])

    def test_interrupted_reconcile_never_points_at_an_unwritten_policy(self):
        self.init()
        changed = self.policy(max_parallel=1, review_reserve=0)
        self.operator('stopped')
        with self.lock() as led:
            with mock.patch.object(cl.Ledger, '_event', side_effect=RuntimeError('crash before commit')):
                with self.assertRaises(RuntimeError):
                    led.reconcile_context(changed, dict(self.ident), 'Owner')
            self.assertEqual((led.epoch, led.policy['max_parallel']), (1, 2))
        orphan = [name for name in os.listdir(self.state) if name not in (cl.LEDGER_FILE, cl.POLICY_FILE)]
        self.assertEqual(len(orphan), 1)  # durable before the commit that would have named it
        reader = cl.Ledger.open(self.state, readonly=True)
        self.assertEqual((reader.epoch, reader.policy['max_parallel']), (1, 2))
        reader.close()

        path = Path(self.state, orphan[0])
        good = path.read_bytes()
        with self.lock() as led:
            path.write_bytes(good.replace(b'"max_parallel":1', b'"max_parallel":9'))
            self.assertEqual(self.code(led.reconcile_context, changed, dict(self.ident), 'Owner'), 'corrupt')
            self.assertEqual(led.epoch, 1)
            path.write_bytes(good)
            self.assertEqual(led.reconcile_context(changed, dict(self.ident), 'Owner')['epoch'], 2)
            self.assertEqual(path.read_bytes(), good)
        reader = cl.Ledger.open(self.state, readonly=True)
        self.addCleanup(reader.close)
        self.assertEqual((reader.epoch, reader.policy, reader.control()), (2, changed, 'stopped'))

    def test_an_older_proposal_store_is_refused_and_left_untouched(self):
        self.init()
        db = sqlite3.connect(os.path.join(self.state, cl.LEDGER_FILE))
        db.execute(f'PRAGMA user_version={cl.SCHEMA_VERSION - 1}')
        db.close()
        before = fingerprint(self.state)
        self.assertEqual(self.code(cl.Ledger.open, self.state), 'unsupported_schema')
        self.assertEqual(self.code(cl.initialize, self.state, self.policy(), self.common, self.ident),
                         'unsupported_schema')
        self.assertEqual(self.code(self.lock().__enter__), 'unsupported_schema')
        self.assertEqual(fingerprint(self.state), before)  # never reset or migrated


class BindingTests(Base):
    """Plan origin versus task base. Checkpoint facts are either simulated positive engine
    observations or computed from the real fixture repository; the ledger itself runs no Git."""

    def test_dependent_task_starts_from_the_exact_confirmed_dependency_result(self):
        self.init()
        result_a = self.commit('src/a/work.txt')
        with self.lock() as led:
            self.submit(led, [task('a'), task('b', deps=['a'])])
            self.assertEqual(self.code(led.claim, 'b', 'alpha'), 'dependencies')
            self.accept(led, 'a', result_a)
            self.assertEqual(self.code(led.claim, 'b', 'alpha'), 'binding_required')

            ws, deps = self.workspace('b'), {'a': result_a}
            proof = self.observed(result_a, result_a)
            self.assertEqual(proof['ancestors'], {self.base: True, result_a: True})
            elsewhere = {'path': os.path.join(self.tmp, 'elsewhere'), 'cleanup_id': 'x'}
            refusals = [
                ('binding_base', (result_a[:12], deps, ws, proof)),
                ('binding_dependencies', (result_a, {}, ws, proof)),
                ('binding_dependencies', (result_a, {'a': 'HEAD'}, ws, proof)),
                ('dependency_stale', (result_a, {'a': R1}, ws, self.proof(result_a, R1))),
                ('binding_workspace', (result_a, deps, elsewhere, proof)),
                ('binding_workspace', (result_a, deps, dict(ws, branch='main'), proof)),
                ('checkpoint_evidence', (result_a, deps, ws, 'ancestry verified by the worker')),
                ('checkpoint_unproven', (result_a, deps, ws, dict(proof, confirmed=False))),
                ('checkpoint_unproven', (result_a, deps, ws, dict(proof, ancestors={self.base: True}))),
                ('checkpoint_unproven', (result_a, deps, ws,
                                         dict(proof, ancestors={self.base: True, result_a: None}))),
                ('checkpoint_unproven', (result_a, deps, ws,
                                         dict(proof, ancestors={self.base: True, result_a: 1}))),
                # Real Git: the dependency result is not contained in the plan origin.
                ('checkpoint_unproven', (self.base, deps, ws, self.observed(self.base, result_a))),
            ]
            for expected, args in refusals:
                self.assertEqual(self.code(led.bind_execution, 'b', *args), expected, args)
            self.assertIsNone(led.task('b')['binding'])

            bound = led.bind_execution('b', result_a, deps, ws, proof)
            self.assertEqual((bound['execution_base'], bound['dependencies'], bound['workspace'], bound['epoch']),
                             (result_a, deps, ws, 1))
            self.assertEqual((led.task('b')['plan_base'], led.plan('p1')['base_sha']), (self.base, self.base))
            attempt = self.released(led, 'b', 'alpha')
            self.assertEqual(self.code(led.bind_execution, 'b', result_a, deps, self.workspace('b', 2), proof),
                             'binding_conflict')  # a claimed task's binding cannot change
            self.assertEqual(self.code(led.invalidate_binding, 'b', 'rebase'), 'binding_locked')

            result_b = self.commit('src/b/work.txt')
            led.finish_attempt(attempt['id'], 'success', True, result=result_b)
            run = self.run_check(led, 'b')
            self.assertEqual(self.code(led.record_check_outcome, 'b', 'unit', 'PASS', self.gate(led, result_b),
                                       self.receipt(result_b), run['id']),
                             'stale_identity')  # the plan origin is not this task's base
            gate = self.gate(led, result_b, result_a)
            self.assertEqual(led.task('b')['gate'], gate)
            self.assertEqual(sorted(gate), ['base', 'policy', 'result', 'rules', 'runtime'])
            self.check(led, 'b', gate, attempt=run)
            review = self.released(led, 'b', 'beta', 'review')
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('b', review['id'], 'approve', gate)
            led.transition('b', 'reviewed', 'accepted', gate)
            self.assertEqual(task_row(led, 'b')['state'], 'accepted')
            self.assertEqual([e['ref'] for e in led.events() if e['kind'] == 'bind'], ['a', 'b'])

    def test_binding_is_stable_across_restart_and_changes_only_by_explicit_invalidation(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            first = led.task('a')['binding']
            self.assertEqual((first['execution_base'], first['state']), (self.base, 'active'))
        moved = self.commit('src/other.txt')
        with self.lock() as led:  # restart
            self.assertEqual(self.bind(led, 'a')['id'], first['id'])
            self.assertEqual(len(led.task('a')['bindings']), 1)
            self.assertEqual(self.code(led.bind_execution, 'a', moved, {}, self.workspace('a'),
                                       self.observed(moved)), 'binding_conflict')  # no hidden rebase
            self.assertEqual(self.code(self.bind, led, 'a', number=2), 'binding_conflict')
            led.invalidate_binding('b', 'workspace to be reassigned')
            self.assertEqual(self.code(led.bind_execution, 'b', self.base, {}, self.workspace('a'),
                                       self.proof(self.base)), 'workspace_conflict')

            attempt = led.claim('a', 'alpha')
            self.assertEqual(self.code(led.invalidate_binding, 'a', 'rebase'), 'binding_locked')
            led.finish_attempt(attempt['id'], 'failure', True)
            self.assertEqual(self.bind(led, 'a')['id'], first['id'])  # a retry keeps its base
            self.assertEqual(self.code(led.invalidate_binding, 'a', ' '), 'reason')
            led.invalidate_binding('a', 'integration checkpoint moved')
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'binding_required')
            self.assertEqual(self.code(led.effect_intent, 'a', 'worktree.create', self.workspace('a', 2)),
                             'binding_required')

            rebound = led.bind_execution('a', moved, {}, self.workspace('a', 2), self.observed(moved))
            self.assertEqual([(b['id'], b['state'], b['execution_base']) for b in led.task('a')['bindings']],
                             [(first['id'], 'invalidated', self.base), (rebound['id'], 'active', moved)])
            self.assertEqual(self.code(led.effect_intent, 'a', 'worktree.create', self.workspace('a')),
                             'effect_workspace')
            led.effect_intent('a', 'worktree.create', self.workspace('a', 2))
            self.assertEqual(led.status()['effects'][0]['spec']['execution_base'], moved)
            led.finish_attempt(self.released(led, 'a', 'alpha')['id'], 'success', True, result=R1)
            run = self.run_check(led, 'a')
            self.assertEqual(self.code(led.record_check_outcome, 'a', 'unit', 'PASS', self.gate(led, R1),
                                       self.receipt(R1), run['id']), 'stale_identity')
            self.check(led, 'a', self.gate(led, R1, moved), attempt=run)

            led.invalidate_binding('a', 'result discarded by the operator')
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['result'], row['attempts'], row['failures']),
                             ('pending', None, 3, 1))  # two implementations and the local check
        raw = sqlite3.connect(os.path.join(self.state, cl.LEDGER_FILE))
        self.addCleanup(raw.close)
        for statement in ("UPDATE bindings SET execution_base = 'x'", 'DELETE FROM bindings',
                          "UPDATE plans SET base_sha = 'x'", 'DELETE FROM plans',
                          "UPDATE contexts SET actor = 'x'", 'DELETE FROM contexts'):
            with self.assertRaises(sqlite3.DatabaseError):
                raw.execute(statement)

    def test_a_changed_dependency_result_blocks_dependent_acceptance(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b', deps=['a'])])
            self.accept(led, 'a', R1)
            self.bind(led, 'b', R1, {'a': R1})
            led.finish_attempt(self.released(led, 'b', 'alpha')['id'], 'success', True, result=R2)
            gate = self.gate(led, R2, R1)
            self.check(led, 'b', gate)
            review = self.released(led, 'b', 'beta', 'review')
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('b', review['id'], 'approve', gate)

            led.invalidate_binding('a', 'dependency result withdrawn')
            self.assertEqual(self.code(led.transition, 'b', 'reviewed', 'accepted', gate), 'dependencies')
            self.bind(led, 'a')
            self.accept(led, 'a', R3)
            self.assertEqual(self.code(led.transition, 'b', 'reviewed', 'accepted', gate), 'dependency_stale')
            self.assertEqual(task_row(led, 'b')['state'], 'reviewed')

            led.invalidate_binding('b', 'rebuild on the new dependency result')
            self.bind(led, 'b', R3, {'a': R3})
            self.assertEqual(led.claim('b', 'alpha')['state'], 'reserved')


class AttributionTests(Base):
    """Outcome attribution and the two budgets. Every close here is simulated ledger state:
    no provider ran and no quota, auth or outage was observed from a real account."""

    def test_unavailable_profiles_do_not_burn_the_semantic_budget_but_dispatch_is_bounded(self):
        names = ['p1', 'p2', 'p3', 'p4']
        self.init(profiles=[self.profile(name) for name in names], max_parallel=2, review_reserve=0,
                  limits={'max_attempts': 2, 'max_no_progress': 2})
        causes = [('availability', 'quota', 'rate_limited'), ('availability', 'auth', 'auth_required'),
                  ('availability', 'permission_denied', 'permission_denied'),
                  ('availability', 'outage', 'outage')]
        with self.lock() as led:
            self.submit(led, [task('a')])
            for name, (attribution, reason, category) in zip(names, causes):
                closed = led.finish_attempt(led.claim('a', name)['id'], 'failure', True, used_seconds=5,
                                            attribution=attribution, reason=reason, category=category)
                self.assertEqual((closed['attribution'], closed['reason'], closed['category']),
                                 (attribution, reason, category))
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['attempts'], row['failures'], row['no_progress']),
                             ('pending', 4, 0, 0))
            lane = self.lane(led, 'a', 'implement')
            self.assertEqual((lane['dispatched'], lane['semantic'], lane['semantic_limit'],
                              lane['dispatch_limit']), (4, 0, 2, 10))  # 2 * (1 + 4 profiles)
            self.assertEqual(led.status()['charged_seconds'], 20)  # the time is still charged

            # Real work is still possible, and an actual wrong result does count.
            led.finish_attempt(self.released(led, 'a', 'p1')['id'], 'failure', True,
                               attribution='semantic', reason='wrong_result', category='failed')
            row = task_row(led, 'a')
            self.assertEqual((row['failures'], row['no_progress']), (1, 1))
            for _ in range(5):  # STOP cleanup is not a code failure, but every launch is counted
                led.finish_attempt(led.claim('a', 'p2')['id'], 'cancelled', True, used_seconds=0,
                                   attribution='operator', reason='stop')
            self.assertEqual(self.code(led.claim, 'a', 'p3'), 'dispatch_exhausted')
        with self.lock() as led:  # a restart resets neither budget
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['attempts'], row['failures'], row['no_progress']),
                             ('pending', 10, 1, 1))
            lane = self.lane(led, 'a', 'implement')
            self.assertEqual((lane['dispatched'], lane['semantic']), (10, 1))
            self.assertEqual(led.status()['charged_seconds'], 120)
            self.assertEqual(self.code(led.claim, 'a', 'p3'), 'dispatch_exhausted')
            reasons = [a['reason'] for a in led.status()['attempts']]
            self.assertEqual(reasons, ['quota', 'auth', 'permission_denied', 'outage', 'wrong_result']
                             + ['stop'] * 5)

    def test_availability_retries_stay_inside_the_time_budget_and_unknown_keeps_its_reservation(self):
        self.init(limits={'max_total_seconds': 250})
        with self.lock() as led:
            self.submit(led, [task('a')])
            led.finish_attempt(led.claim('a', 'alpha')['id'], 'failure', True,
                               attribution='availability', reason='quota')  # charged its reservation
            held = led.claim('a', 'beta')
            led.record_launch(held['id'], {'pid': os.getpid()})
            unknown = led.finish_attempt(held['id'], 'failure', False, attribution='availability',
                                         reason='outage')
            self.assertEqual((unknown['state'], unknown['attribution']), ('unknown', None))
            self.assertEqual(led.status()['charged_seconds'], 200)  # full reservation while unknown
            self.assertEqual(self.code(led.claim, 'a', 'alpha'), 'task_state')
            led.finish_attempt(held['id'], 'failure', True, used_seconds=30, attribution='execution',
                               reason='lost')
            self.assertEqual(led.status()['charged_seconds'], 130)
            led.finish_attempt(led.claim('a', 'alpha')['id'], 'failure', True,
                               attribution='availability', reason='auth')
            self.assertEqual(self.code(led.claim, 'a', 'beta'), 'time_budget')  # 230 + 100 > 250
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['attempts'], row['failures'], row['no_progress']),
                             ('pending', 3, 0, 0))

    def test_attribution_takes_fixed_values_and_success_has_no_shortcut(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a')])
            attempt = led.claim('a', 'alpha')
            refused = [dict(attribution='quota'), dict(attribution='availability'),
                       dict(attribution='availability', reason='no credit left on the account'),
                       dict(reason='quota'), dict(attribution='semantic', category='rate_limited'),
                       dict(category='auth_required'), dict(category='Bearer abc'),
                       dict(attribution=['availability'], reason='quota')]
            for kwargs in refused:
                self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'failure', True, **kwargs),
                                 'attribution', kwargs)
            for kwargs in ({}, dict(attribution='semantic')):  # a cancelled attempt is no code defect
                self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'cancelled', True, **kwargs),
                                 'attribution')
            self.release(led, attempt)
            for kwargs in (dict(attribution='availability', reason='quota'), dict(attribution='semantic'),
                           dict(category='rate_limited')):
                self.assertEqual(self.code(led.finish_attempt, attempt['id'], 'success', True, R1, **kwargs),
                                 'attribution', kwargs)
            row = led.status()['attempts'][0]
            self.assertEqual((row['state'], row['outcome'], row['attribution']), ('launched', None, None))
            self.assertEqual(task_row(led, 'a')['failures'], 0)
            done = led.finish_attempt(attempt['id'], 'success', True, R1, category='success')
            self.assertEqual((done['outcome'], done['attribution'], done['reason'], done['category']),
                             ('success', None, None, 'success'))
        self.assertEqual(set(cl.PROVIDER_CATEGORIES), set(cr.CATEGORIES))

    def test_semantic_defects_count_and_an_unavailable_reviewer_leaves_checked_work_alone(self):
        self.init(limits={'max_attempts': 2})
        with self.lock() as led:
            self.submit(led, [task('a')])
            led.finish_attempt(self.released(led, 'a', 'alpha')['id'], 'failure', True,
                               attribution='semantic', reason='wrong_result')
            self.assertEqual((task_row(led, 'a')['failures'], task_row(led, 'a')['no_progress']), (1, 1))
            led.finish_attempt(self.released(led, 'a', 'alpha')['id'], 'success', True, result=R1)
            gate = self.gate(led, R1)
            self.check(led, 'a', gate)
            review = led.claim('a', 'beta', 'review')
            led.finish_attempt(review['id'], 'failure', True, used_seconds=1, attribution='availability',
                               reason='auth', category='auth_required')
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['result'], row['failures'], row['no_progress']),
                             ('checked', R1, 1, 1))
            lane = self.lane(led, 'a', 'review')
            self.assertEqual((lane['dispatched'], lane['semantic'], lane['semantic_limit'],
                              lane['dispatch_limit']), (1, 0, 2, 6))
            lane = self.lane(led, 'a', 'implement')
            self.assertEqual((lane['dispatched'], lane['semantic']), (2, 2))
            self.assertEqual(self.code(led.record_review, 'a', review['id'], 'approve', gate), 'review_attempt')
            again = self.released(led, 'a', 'beta', 'review')
            led.finish_attempt(again['id'], 'success', True)
            led.record_review('a', again['id'], 'approve', gate)
            self.assertEqual(task_row(led, 'a')['state'], 'reviewed')


class CheckTests(Base):
    """Local checks as reserved owned attempts with explicit outcomes. The attempts are
    simulated launch and release state and the receipts are fixture references: no check
    command, provider or native execution is claimed."""

    def test_running_check_holds_resources_capacity_and_budget_across_restart(self):
        self.init(max_parallel=2, review_reserve=0)
        with self.lock() as led:
            self.submit(led, [task('a', resources=['db']), task('b', scope=['docs'], resources=['db']),
                              task('c'), task('d')])
            led.finish_attempt(self.released(led, 'a', 'alpha')['id'], 'success', True, result=R1,
                               used_seconds=10)
            self.assertEqual(self.code(led.claim_check, 'a', 'lint'), 'check_not_allowed')
            running = led.claim_check('a', 'unit')
            self.assertEqual((running['role'], running['profile_id'], running['check_name'],
                              running['result'], running['state']), ('check', None, 'unit', R1, 'reserved'))
            self.assertEqual(self.code(led.claim_check, 'a', 'unit'), 'task_busy')
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'resource_conflict')
            led.claim('c', 'beta')
            self.assertEqual(self.code(led.claim, 'd', 'alpha'), 'capacity')
            self.assertEqual(led.status()['charged_seconds'], 210)
            led.record_launch(running['id'], {'pid': os.getpid()})
        with self.lock() as led:  # restart: the reservation is durable
            owned = led.owned_work()['attempts'][0]
            self.assertEqual((owned['id'], owned['role'], owned['check_name'], owned['state'],
                              owned['released_at']), (running['id'], 'check', 'unit', 'launched', None))
            self.assertEqual(self.code(led.claim, 'b', 'beta'), 'resource_conflict')
            self.assertEqual(self.code(led.claim, 'd', 'alpha'), 'capacity')
            self.assertEqual(self.code(led.invalidate_binding, 'a', 'rebase'), 'binding_locked')
            self.operator('stopped')  # STOP cleanup is the same as for any attempt
            self.assertEqual(self.code(led.authorize_release, running['id']), 'control_stopped')
            self.assertEqual(self.code(led.finish_attempt, running['id'], 'success', True), 'not_released')
            self.assertEqual(self.code(led.finish_attempt, running['id'], 'failure', True), 'attribution')
            led.finish_attempt(running['id'], 'cancelled', True, used_seconds=3, attribution='operator',
                               reason='stop')
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['result'], row['failures'], row['no_progress']),
                             ('implemented', R1, 0, 0))
            self.assertEqual(led.status()['charged_seconds'], 113)
            lane = self.lane(led, 'a', 'check', 'unit')
            self.assertEqual((lane['dispatched'], lane['semantic'], lane['semantic_limit'],
                              lane['dispatch_limit']), (1, 0, 3, 6))
            led.set_control('running')
            self.assertEqual(led.claim('b', 'beta')['state'], 'reserved')  # the resource is free again

    def test_only_a_released_check_attempt_with_a_matching_receipt_can_gate(self):
        self.init()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')])
            implementer = self.released(led, 'a', 'alpha')
            led.finish_attempt(implementer['id'], 'success', True, result=R1)
            led.finish_attempt(self.released(led, 'b', 'beta')['id'], 'success', True, result=R2)
            gate, receipt, record = self.gate(led, R1), self.receipt(R1), led.record_check_outcome
            foreign = self.run_check(led, 'b')
            unreleased = led.claim_check('a', 'unit')
            self.assertEqual(self.code(record, 'a', 'unit', 'PASS', gate, receipt, None), 'check_attempt')
            self.assertEqual(self.code(record, 'a', 'unit', 'PASS', gate, receipt, 9999), 'unknown_attempt')
            for attempt_id in (implementer['id'], foreign['id'], unreleased['id']):
                self.assertEqual(self.code(record, 'a', 'unit', 'PASS', gate, receipt, attempt_id),
                                 'check_attempt')
            led.finish_attempt(unreleased['id'], 'failure', True, used_seconds=0, attribution='execution',
                               reason='launch_failed')
            for status in ('PASS', 'FAIL'):  # a check that never ran has no verdict
                self.assertEqual(self.code(record, 'a', 'unit', status, gate, receipt, unreleased['id']),
                                 'check_attempt')
            record('a', 'unit', 'INCOMPLETE', gate, None, unreleased['id'])
            self.assertEqual(led.finalize_checks('a', gate),
                             {'status': 'INCOMPLETE', 'checks': {'unit': 'INCOMPLETE'}, 'missing': [],
                              'collection_pending': False, 'state': 'implemented'})

            run = self.run_check(led, 'a')
            for bad in ('pass', 'SKIPPED', True, 1, None):
                self.assertEqual(self.code(record, 'a', 'unit', bad, gate, receipt, run['id']), 'check_status')
            malformed = (None, {}, dict(receipt, schema='other/v1'), dict(receipt, receipt_sha256='abc'),
                         dict(receipt, lifecycle_sha256=None), dict(receipt, input_sha='HEAD'),
                         dict(receipt, exit_code=0))
            for bad in malformed:
                self.assertEqual(self.code(record, 'a', 'unit', 'PASS', gate, bad, run['id']), 'receipt')
            for wrong in (R2, R0):  # a receipt for another input cannot gate this result
                self.assertEqual(self.code(record, 'a', 'unit', 'PASS', gate, dict(receipt, input_sha=wrong),
                                           run['id']), 'receipt_mismatch')
            self.assertEqual([e['status'] for e in led.status()['evidence']], ['INCOMPLETE'])
            self.assertEqual(task_row(led, 'a')['state'], 'implemented')

            record('a', 'unit', 'PASS', gate, receipt, run['id'])
            self.assertEqual(self.code(record, 'a', 'unit', 'PASS', gate, receipt, run['id']),
                             'check_attempt')  # one attempt backs one outcome
            self.assertEqual(self.code(led.claim_check, 'a', 'unit'), 'check_settled')
            self.assertEqual(led.finalize_checks('a', gate)['status'], 'PASS')
            self.assertEqual(task_row(led, 'a')['state'], 'checked')
            evidence = led.status()['evidence'][-1]
            self.assertEqual((evidence['status'], evidence['passed'], evidence['attempt_id'],
                              evidence['receipt']), ('PASS', 1, run['id'], receipt))

    def test_every_declared_check_is_retained_before_the_aggregate(self):
        names = ['unit', 'lint', 'types']
        self.init(allowed_checks={name: [self.tool, name] for name in names})
        with self.lock() as led:
            self.submit(led, [dict(task('a'), checks=names)])
            led.finish_attempt(self.released(led, 'a', 'alpha')['id'], 'success', True, result=R1)
            gate = self.gate(led, R1)
            first = self.check(led, 'a', gate, 'FAIL', 'unit')
            self.assertEqual(first, {'status': 'FAIL',  # a known FAIL outranks the missing rows
                                     'checks': {'unit': 'FAIL', 'lint': None, 'types': None},
                                     'missing': ['lint', 'types'], 'collection_pending': True,
                                     'state': 'implemented'})
            row = task_row(led, 'a')  # the result is kept while the other results are collected
            self.assertEqual((row['state'], row['result'], row['failures']), ('implemented', R1, 0))
            self.assertEqual(led.checks('a')['aggregate'], 'FAIL')
            self.assertEqual(self.code(led.claim_check, 'a', 'unit'), 'check_settled')
            # Retention control: a later independent check is still claimed and recorded.
            later = self.check(led, 'a', gate, 'PASS', 'lint')
            self.assertEqual((later['status'], later['checks']['lint'], later['missing'],
                              later['collection_pending'], later['state']),
                             ('FAIL', 'PASS', ['types'], True, 'implemented'))
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['result'], row['failures']), ('implemented', R1, 0))
            stuck = led.claim_check('a', 'types')
            led.finish_attempt(stuck['id'], 'cancelled', True, used_seconds=0, attribution='execution',
                               reason='timeout')
            led.record_check_outcome('a', 'types', 'INCOMPLETE', gate, None, stuck['id'])
            self.assertEqual(led.finalize_checks('a', gate),
                             {'status': 'FAIL',
                              'checks': {'unit': 'FAIL', 'lint': 'PASS', 'types': 'INCOMPLETE'},
                              'missing': [], 'collection_pending': False, 'state': 'pending'})
            row = task_row(led, 'a')
            self.assertEqual((row['state'], row['result'], row['failures'], row['no_progress']),
                             ('pending', None, 1, 1))
            kept = [(e['name'], e['status'], e['identity']['result']) for e in led.status()['evidence']]
            self.assertEqual(kept, [('unit', 'FAIL', R1), ('lint', 'PASS', R1), ('types', 'INCOMPLETE', R1)])
            final = [e['data'] for e in led.events() if e['kind'] == 'checks_final'][-1]
            self.assertEqual((final['aggregate'], final['result']), ('FAIL', R1))
            self.assertEqual(self.code(led.finalize_checks, 'a', gate), 'task_state')

            led.finish_attempt(self.released(led, 'a', 'alpha')['id'], 'success', True, result=R2)
            gate = self.gate(led, R2)
            fresh = led.finalize_checks('a', gate)  # old rows do not carry over; missing only
            self.assertEqual((fresh['status'], fresh['missing'], fresh['collection_pending'], fresh['state']),
                             ('INCOMPLETE', names, False, 'implemented'))
            for name in ('unit', 'lint'):
                self.check(led, 'a', gate, 'PASS', name, finalize=False)
            held = self.check(led, 'a', gate, 'INCOMPLETE', 'types')
            self.assertEqual((held['status'], held['state']), ('INCOMPLETE', 'implemented'))
            self.assertEqual(self.code(led.claim, 'a', 'beta', 'review'), 'task_state')
            row = task_row(led, 'a')  # INCOMPLETE holds the result and is not a semantic failure
            self.assertEqual((row['result'], row['failures'], row['no_progress']), (R2, 1, 1))
            self.assertEqual(self.check(led, 'a', gate, 'PASS', 'types')['status'], 'PASS')
            view = led.checks('a')
            self.assertEqual((view['aggregate'], [item['status'] for item in view['checks']]),
                             ('PASS', ['PASS'] * 3))
            self.assertEqual(task_row(led, 'a')['state'], 'checked')
            review = self.released(led, 'a', 'beta', 'review')  # a fresh review only after all PASS
            led.finish_attempt(review['id'], 'success', True)
            led.record_review('a', review['id'], 'approve', gate)
            led.transition('a', 'reviewed', 'accepted', gate)
            self.assertEqual(len(led.status()['evidence']), 8)

    def test_check_attempts_are_bounded_and_never_stand_in_for_native_work(self):
        self.init(limits={'max_attempts': 1})
        with self.lock() as led:
            self.submit(led, [task('a'), task('b'), task('c')])
            self.assertEqual(self.code(led.claim, 'a', 'alpha', 'check'), 'profile_role')
            for tid, result in (('a', R1), ('b', R2), ('c', R3)):
                led.finish_attempt(self.released(led, tid, 'alpha')['id'], 'success', True, result=result)
            gate = self.gate(led, R1)
            run = self.run_check(led, 'a')
            self.assertEqual(task_row(led, 'a')['state'], 'implemented')  # a finished process is no verdict
            self.assertEqual(self.code(led.record_review, 'a', run['id'], 'approve', gate), 'task_state')
            self.assertEqual(self.check(led, 'a', gate, attempt=run)['status'], 'PASS')
            self.assertEqual(self.code(led.record_review, 'a', run['id'], 'approve', gate), 'review_attempt')
            self.assertEqual(task_row(led, 'a')['state'], 'checked')

            for reason in ('outage', 'transport'):
                led.finish_attempt(led.claim_check('b', 'unit')['id'], 'failure', True, used_seconds=0,
                                   attribution='availability', reason=reason)
            self.assertEqual(self.code(led.claim_check, 'b', 'unit'), 'dispatch_exhausted')
            lane = self.lane(led, 'b', 'check', 'unit')
            self.assertEqual((lane['dispatched'], lane['semantic'], lane['semantic_limit'],
                              lane['dispatch_limit']), (2, 0, 1, 2))
            row = task_row(led, 'b')
            self.assertEqual((row['state'], row['result'], row['failures'], row['no_progress']),
                             ('implemented', R2, 0, 0))

            self.assertEqual(self.check(led, 'c', self.gate(led, R3), 'INCOMPLETE')['status'], 'INCOMPLETE')
            self.assertEqual(self.code(led.claim_check, 'c', 'unit'), 'attempts_exhausted')
            row = task_row(led, 'c')
            self.assertEqual((row['state'], row['result'], row['failures']), ('implemented', R3, 0))


class CandidateTests(Base):
    """Derived publication candidates. Launches, receipts and integration journal entries are
    simulated ledger state (state-unit), not native proof; the commits and their ancestry are
    real objects of the fixture repository. Nothing is pushed and no remote is contacted."""

    EFFECTS = ('commit', 'integrate', 'push', 'pr', 'merge')
    CHECKS = ['unit', 'lint']

    def over(self, **more):
        more.setdefault('profiles', self.reviewers())
        return dict(effects=list(self.EFFECTS), delivery=self.delivery(),
                    allowed_checks={name: [self.tool, name] for name in self.CHECKS}, **more)

    def start(self, **more):
        self.init(**self.over(**more))

    def task_accepted(self, led, tid, result, base, name):
        led.finish_attempt(self.released(led, tid, 'alpha')['id'], 'success', True, result=result)
        gate = self.gate(led, result, base)
        self.check(led, tid, gate, name=name)
        review = self.released(led, tid, 'beta', 'review')
        led.finish_attempt(review['id'], 'success', True)
        led.record_review(tid, review['id'], 'approve', gate)
        led.transition(tid, 'reviewed', 'accepted', gate)

    def build(self, led, effects=EFFECTS):
        """Two accepted, locally integrated tasks built on real commits. Returns the exact
        contributions, their integration journal ids and a real integrated commit."""
        self.submit(led, [task('a'), dict(task('b', deps=['a']), checks=['lint'])], effects=effects)
        first = self.commit('src/a/work.txt')
        self.task_accepted(led, 'a', first, self.base, 'unit')
        self.bind(led, 'b', first, {'a': first})
        second = self.commit('src/b/work.txt')
        self.task_accepted(led, 'b', second, first, 'lint')
        contributions = {'a': first, 'b': second}
        self.open_plan(led)
        integrated = self.commit('integrated.txt')
        journal = {'a': self.integrate(led, 'a', real=True),
                   'b': self.integrate(led, 'b', integrated, real=True)}
        return contributions, journal, integrated

    def reintegrate(self, led, journal, name):
        """State-unit: journal the accepted result of b once more onto a new real commit, so the
        checkpoint moves while the contributions stay. Returns the new head and journal."""
        head = self.commit(name)
        return head, dict(journal, b=self.integrate(led, 'b', head, real=True))

    def test_accepted_tasks_publish_only_through_a_checked_and_reviewed_candidate(self):
        self.start()
        with self.lock() as led:
            contributions, journal, integrated = self.build(led)
            publish = {'branch': 'sdlc/p1', 'result': integrated}
            for tid, result in contributions.items():  # an accepted task is not a publication
                self.assertEqual(self.code(led.effect_intent, tid, 'push', dict(publish, result=result)),
                                 'candidate_required')
            forged = self.raw_plan([dict(task('x'), kind='candidate')], pid='px')
            self.assertEqual(self.code(led.submit, forged, self.raw_authority(forged), self.ident),
                             'plan_invalid')  # the internal kind is refused at the public boundary

            facts = self.facts(integrated, contributions, journal, real=True)
            self.assertEqual(facts['ancestors'],
                             {self.base: True, contributions['a']: True, contributions['b']: True})
            view = self.derive(led, integrated, contributions, journal, self.CHECKS, real=True)
            cid = view['id']
            self.assertEqual((view['stage'], view['revision'], view['origin'], view['result'],
                              view['checks'], view['current'], view['publishable']),
                             ('checking', 1, self.base, integrated, self.CHECKS, True, False))
            self.assertEqual(view['contributions'],
                             {tid: {'result': sha, 'binding': led.task(tid)['binding']['id']}
                              for tid, sha in contributions.items()})
            again = self.derive(led, integrated, contributions, journal, ['lint', 'unit'], real=True)
            self.assertEqual((again['id'], len(led.candidates('p1'))), (cid, 1))  # same inputs, same id
            self.assertEqual(led.task(cid)['spec']['kind'], 'candidate')
            self.assertEqual([row['id'] for row in led.status()['tasks']], ['a', 'b'])

            # No derived implementation: the candidate is never claimed, bound or committed.
            self.assertEqual(self.code(led.claim, cid, 'alpha'), 'candidate_derived')
            self.assertEqual(self.code(led.bind_execution, cid, self.base, dict(contributions),
                                       self.workspace('cand-p1'),
                                       self.proof(self.base, *contributions.values())), 'candidate_derived')
            for kind in ('task.commit', 'integrate'):
                self.assertEqual(self.code(led.effect_intent, cid, kind, {}), 'candidate_derived')
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(publish)), 'candidate_unaccepted')

            gate = self.gate(led, integrated)  # base is the plan origin, head the integrated result
            self.assertEqual(led.candidate(cid)['gate'], gate)
            self.assertEqual(led.finalize_checks(cid, gate)['missing'], self.CHECKS)  # nothing carries over
            partial = self.check(led, cid, gate, name='unit')
            self.assertEqual((partial['status'], partial['missing']), ('INCOMPLETE', ['lint']))
            self.assertEqual(self.code(led.claim, cid, 'beta', 'review'), 'task_state')
            self.assertEqual(self.check(led, cid, gate, name='lint')['status'], 'PASS')
            self.assertEqual(led.candidate(cid)['stage'], 'reviewing')

            earlier = [a['id'] for a in led.status()['attempts'] if a['role'] == 'review']
            self.assertEqual(len(earlier), 2)
            for attempt_id in earlier:  # a task review never stands in for the whole-result review
                self.assertEqual(self.code(led.record_review, cid, attempt_id, 'approve', gate),
                                 'review_attempt')
            review = self.released(led, cid, 'codex', 'review')  # simulated configured Codex review
            led.finish_attempt(review['id'], 'success', True)
            narrow = self.gate(led, integrated, contributions['a'])  # not the plan origin
            self.assertEqual(self.code(led.record_review, cid, review['id'], 'approve', narrow),
                             'stale_identity')
            led.record_review(cid, review['id'], 'approve', gate)
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(publish)), 'candidate_unaccepted')
            led.transition(cid, 'reviewed', 'accepted', gate)
            view = led.candidate(cid)
            self.assertEqual((view['stage'], view['publishable']), ('accepted', True))

            pushed = led.effect_intent(cid, 'push', dict(publish))
            self.assertEqual(led.status()['effects'][-1]['spec'], dict(publish, target=self.delivery()))
            led.effect_result(pushed, 'done', {'sha': integrated})
            self.assertEqual(self.code(led.effect_intent, 'b', 'push', dict(publish)), 'candidate_required')
            self.assertEqual([a['role'] for a in led.status()['attempts'] if a['task_id'] == cid],
                             ['check', 'check', 'review'])  # no implementation was ever recorded
            led.transition(cid, 'accepted', 'published', gate)
            self.assertEqual(led.candidate(cid)['stage'], 'published')
            self.assertIn('candidate', [event['kind'] for event in led.events()])

    def test_a_changed_contribution_or_integrated_result_holds_and_supersedes_the_candidate(self):
        self.start()
        with self.lock() as led:
            contributions, journal, integrated = self.build(led)
            first = self.derive(led, integrated, contributions, journal, self.CHECKS, real=True)
            gate = self.accept_candidate(led, first)
            cid, publish = first['id'], {'branch': 'sdlc/p1', 'result': integrated}
            kept = [e['id'] for e in led.status()['evidence'] if e['task_id'] == cid]
            self.assertEqual(len(kept), 3)

            led.invalidate_binding('b', 'contributing result withdrawn')
            view = led.candidate(cid)
            self.assertEqual((view['state'], view['hold'], view['stage'], view['current'],
                              view['publishable'], view['gate']),
                             ('accepted', 'contribution_state', 'stale', False, False, None))
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(publish)), 'candidate_stale')
            self.assertEqual(self.code(led.transition, cid, 'accepted', 'published', gate),
                             'candidate_stale')

            self.bind(led, 'b', contributions['a'], {'a': contributions['a']}, number=2)
            redone = self.commit('src/b/redo.txt')
            self.task_accepted(led, 'b', redone, contributions['a'], 'lint')
            self.assertEqual(led.candidate(cid)['hold'], 'contribution_result')
            changed, newer = dict(contributions, b=redone), self.commit('integrated-2.txt')
            # The earlier journal entry integrated the earlier result of b.
            self.assertEqual(self.code(self.derive, led, newer, changed, journal, self.CHECKS, 2,
                                       real=True), 'integration_unproven')
            self.assertEqual(self.code(self.derive, led, integrated, contributions, journal, self.CHECKS,
                                       real=True), 'contribution_stale')
            current = dict(journal, b=self.integrate(led, 'b', newer, real=True))
            second = self.derive(led, newer, changed, current, self.CHECKS, 2, real=True)
            self.assertEqual((second['revision'], second['stage']), (2, 'checking'))
            old = led.candidate(cid)
            self.assertEqual((old['state'], old['hold'], old['stage']),
                             ('superseded', 'superseded', 'superseded'))
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(publish)), 'candidate_stale')
            self.assertEqual(self.code(led.claim_check, cid, 'unit'), 'candidate_stale')
            self.assertEqual([e['id'] for e in led.status()['evidence'] if e['task_id'] == cid], kept)

            # The same contributions integrated to another SHA are another candidate.
            latest, again = self.reintegrate(led, current, 'integrated-3.txt')
            third = self.derive(led, latest, changed, again, self.CHECKS, 3, real=True)
            self.assertEqual([item['stage'] for item in led.candidates('p1')],
                             ['superseded', 'superseded', 'checking'])
            self.assertEqual(self.code(led.claim_check, second['id'], 'unit'), 'candidate_stale')
            plan = led.plan('p1')
            self.assertEqual([item['id'] for item in plan['candidates']], [cid, second['id'], third['id']])
            self.assertEqual([item['id'] for item in plan['tasks']], ['a', 'b'])

    def test_a_new_context_holds_the_candidate_until_the_plan_is_rebuilt(self):
        self.start()
        with self.lock() as led:
            contributions, journal, integrated = self.build(led)
            view = self.derive(led, integrated, contributions, journal, self.CHECKS, real=True)
            self.accept_candidate(led, view)
            cid, publish = view['id'], {'branch': 'sdlc/p1', 'result': integrated}
            evidence = [e for e in led.status()['evidence'] if e['task_id'] == cid]
            self.operator('stopped')
            led.reconcile_context(self.policy(**self.over(max_parallel=3)), dict(self.ident), 'Owner')
            led.set_control('running')
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(publish)), 'plan_stale')
            self.assertEqual(led.candidate(cid)['hold'], 'context')

            fresh = self.fresh_authority(led, effects=self.EFFECTS)
            held = led.readmit_plan('p1', fresh, dict(self.ident))  # the plan workspace is still owned
            self.assertEqual((held['status'], [w['owner'] for w in held['workspaces']]), ('hold', ['plan']))
            gone = led.plan_effect_intent('p1', 'worktree.remove',
                                          self.ws_spec(self.plan_ws(), 'worktree.remove', integrated))
            led.effect_result(gone, 'done')
            self.assertEqual(led.readmit_plan('p1', fresh, dict(self.ident))['tasks'],
                             {'a': 'implemented', 'b': 'implemented'})
            after = led.candidate(cid)
            self.assertEqual((after['state'], after['hold'], after['stage'], after['publishable']),
                             ('superseded', 'context', 'superseded', False))
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(publish)), 'candidate_stale')
            self.assertEqual(self.code(self.derive, led, integrated, contributions, journal, self.CHECKS, 2,
                                       real=True), 'contribution_stale')  # the tasks are re-accepted first
            self.assertEqual([e for e in led.status()['evidence'] if e['task_id'] == cid], evidence)

    def test_publication_needs_the_frozen_result_branch_target_and_saved_authority(self):
        self.start()
        with self.lock() as led:
            contributions, journal, integrated = self.build(led, effects=('commit', 'integrate', 'push'))
            view = self.derive(led, integrated, contributions, journal, self.CHECKS, real=True)
            self.accept_candidate(led, view)
            cid, good = view['id'], {'branch': 'sdlc/p1', 'result': integrated}
            refusals = [
                ('candidate_mismatch', 'push', {'branch': 'sdlc/p1'}),  # names no result
                ('candidate_mismatch', 'push', dict(good, result=contributions['b'])),
                ('effect_target', 'push', dict(good, branch='main')),
                ('effect_target', 'push', dict(good, base_branch='release')),
                ('effect_target', 'push', dict(good, github_repo='other-org/other')),
                # The current policy allows these; the authority saved with the plan does not.
                ('effect_unauthorized', 'pr.create', dict(good)),
                ('effect_unauthorized', 'pr.merge', dict(good)),
            ]
            for expected, kind, spec in refusals:
                self.assertEqual(self.code(led.effect_intent, cid, kind, spec), expected, (kind, spec))
            self.assertEqual([e for e in led.status()['effects'] if e['task_id'] == cid], [])
            pushed = led.effect_intent(cid, 'push', dict(good))
            led.effect_result(pushed, 'done', {'sha': integrated})
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(good, branch='sdlc/other')),
                             'candidate_mismatch')  # one candidate, one branch

            newer, again = self.reintegrate(led, journal, 'integrated-2.txt')
            second = self.derive(led, newer, contributions, again, self.CHECKS, 2, real=True)
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(good)), 'candidate_stale')
            self.assertEqual(self.code(led.effect_intent, second['id'], 'push', dict(good, result=newer)),
                             'candidate_unaccepted')
            self.accept_candidate(led, second)
            self.assertEqual(self.code(led.effect_intent, second['id'], 'push', dict(good)),
                             'candidate_mismatch')  # the superseded result
            led.effect_intent(second['id'], 'push', dict(good, result=newer))
            pushes = [(e['task_id'], e['state']) for e in led.status()['effects'] if e['kind'] == 'push']
            self.assertEqual(pushes, [(cid, 'done'), (second['id'], 'intent')])  # nothing is rolled back

    def test_candidate_revisions_are_bounded_and_spent_budgets_are_retained(self):
        self.start(limits={'max_attempts': 2})
        with self.lock() as led:
            contributions, journal, integrated = self.build(led)
            first = self.derive(led, integrated, contributions, journal, self.CHECKS, real=True)
            cid, gate = first['id'], self.gate(led, integrated)
            before = led.status()['budgets'][0]['charged_seconds']
            run = self.release(led, led.claim_check(cid, 'unit'))
            led.finish_attempt(run['id'], 'success', True, used_seconds=7)
            failed = self.check(led, cid, gate, 'FAIL', 'unit', attempt=run)
            self.assertEqual((failed['status'], failed['missing'], failed['collection_pending'],
                              failed['state']), ('FAIL', ['lint'], True, 'implemented'))
            self.assertEqual(self.check(led, cid, gate, name='lint')['state'], 'pending')
            view = led.candidate(cid)  # tasks that passed alone failed together
            self.assertEqual((view['stage'], view['hold'], view['failures']), ('failed', 'withdrawn', 1))
            self.assertEqual(self.code(led.claim, cid, 'alpha'), 'candidate_derived')  # never repaired in place
            self.assertEqual(self.code(led.claim_check, cid, 'unit'), 'candidate_stale')
            again = self.derive(led, integrated, contributions, journal, self.CHECKS, real=True)
            self.assertEqual((again['id'], again['stage']), (cid, 'failed'))  # no fresh id, no reset

            newer, journal = self.reintegrate(led, journal, 'integrated-2.txt')
            second = self.derive(led, newer, contributions, journal, self.CHECKS, 2, real=True)
            self.assertEqual(second['revision'], 2)
            latest, journal = self.reintegrate(led, journal, 'integrated-3.txt')
            self.assertEqual(self.code(self.derive, led, latest, contributions, journal, self.CHECKS, 3,
                                       real=True), 'candidate_revisions')
            # The checkpoint moved past the second candidate, which no new revision may replace.
            self.assertEqual([item['stage'] for item in led.candidates()], ['superseded', 'stale'])
            lane = self.lane(led, cid, 'check', 'unit')
            self.assertEqual((lane['dispatched'], lane['semantic']), (1, 1))
            self.assertEqual(led.status()['budgets'][0]['charged_seconds'], before + 7)
            self.assertEqual([(e['name'], e['status']) for e in led.status()['evidence']
                              if e['task_id'] == cid], [('unit', 'FAIL'), ('lint', 'PASS')])
            self.assertEqual(led.candidate(cid)['failures'], 1)
        with self.lock() as led:  # a restart resets nothing
            latest, journal = self.reintegrate(led, journal, 'integrated-4.txt')
            self.assertEqual(self.code(self.derive, led, latest, contributions, journal, self.CHECKS, 3,
                                       real=True), 'candidate_revisions')
            self.assertEqual(len(led.candidates('p1')), 2)
            self.assertEqual(led.status()['budgets'][0]['charged_seconds'], before + 7)

    def test_only_strict_engine_facts_about_the_whole_plan_create_a_candidate(self):
        self.start()
        with self.lock() as led:
            contributions, journal, integrated = self.build(led)
            good = self.facts(integrated, contributions, journal, real=True)
            workspace = self.workspace('cand-p1')
            args = (integrated, dict(contributions), list(self.CHECKS), workspace, good)

            def swap(index, value):
                return args[:index] + (value,) + args[index + 1:]

            elsewhere = {'path': os.path.join(self.tmp, 'elsewhere'), 'cleanup_id': 'x'}
            wrong = dict(contributions, b=R1)
            refusals = [
                ('candidate_result', swap(0, 'HEAD')),
                ('candidate_contributions', swap(1, {'a': contributions['a']})),  # not the whole plan
                ('candidate_contributions', swap(1, dict(contributions, c=R1))),
                ('candidate_checks', swap(2, ['unit'])),  # not the union
                ('candidate_checks', swap(2, ['unit', 'lint', 'lint'])),
                ('candidate_workspace', swap(3, elsewhere)),
                ('integration_evidence', swap(4, 'integrated and verified by the worker')),
                ('integration_evidence', swap(4, {k: v for k, v in good.items() if k != 'owned'})),
                ('integration_unproven', swap(4, dict(good, confirmed=1))),
                ('integration_unproven', swap(4, dict(good, owned=False))),
                ('integration_unproven', swap(4, dict(good, checkpoint=contributions['b']))),
                ('integration_unproven', swap(4, dict(good, ancestors={self.base: True}))),
                ('integration_unproven', swap(4, dict(good, integrations={'a': journal['a']}))),
                ('integration_unproven', swap(4, dict(good, integrations=dict(journal, b=True)))),
                ('integration_unproven', swap(4, dict(good, integrations=dict(journal, b=journal['a'])))),
                # Real Git: the plan origin does not contain the contributing results.
                ('integration_unproven', (self.base, dict(contributions), list(self.CHECKS), workspace,
                                          self.facts(self.base, contributions, journal, real=True))),
                ('contribution_stale', (integrated, wrong, list(self.CHECKS), workspace,
                                        self.facts(integrated, wrong, journal))),
            ]
            for expected, bad in refusals:
                self.assertEqual(self.code(led.create_candidate, 'p1', *bad), expected, bad)
            self.assertEqual(self.code(led.create_candidate, 'nope', *args), 'unknown_plan')
            unresolved = led.effect_intent('a', 'integrate', self.integrate_spec(
                self.plan_ws(), integrated, contributions['a']))
            cited = swap(4, dict(good, integrations=dict(journal, a=unresolved)))
            self.assertEqual(self.code(led.create_candidate, 'p1', *cited), 'integration_unproven')
            led.effect_result(unresolved, 'failed')
            self.assertEqual(self.code(led.create_candidate, 'p1', *cited), 'integration_unproven')
            self.assertEqual(led.candidates(), [])
            self.assertEqual(self.code(led.candidate, 'nope'), 'unknown_candidate')

            cid = led.create_candidate('p1', *args)['id']
            self.assertEqual(self.code(led.create_candidate, 'p1', *swap(3, self.workspace('cand-p1', 2))),
                             'candidate_conflict')
            # A real commit the recorded checkpoint never reached is not a candidate.
            ahead = self.commit('integrated-2.txt')
            unrecorded = (ahead, dict(contributions), list(self.CHECKS), self.workspace('cand-p1', 2),
                          self.facts(ahead, contributions, journal, real=True))
            self.assertEqual(self.code(led.create_candidate, 'p1', *unrecorded), 'checkpoint_stale')

            held = led.claim_check(cid, 'unit')
            led.record_launch(held['id'], {'pid': os.getpid()})
            newer, again = self.reintegrate(led, journal, 'integrated-3.txt')
            later = (newer, dict(contributions), list(self.CHECKS), self.workspace('cand-p1', 2),
                     self.facts(newer, contributions, again, real=True))
            superseded_step = later[:4] + (self.facts(newer, contributions, journal, real=True),)
            self.assertEqual(self.code(led.create_candidate, 'p1', *superseded_step), 'integration_unproven')
            self.assertEqual(self.code(led.create_candidate, 'p1', *later), 'candidate_busy')
            self.assertEqual(self.code(led.authorize_release, held['id']), 'candidate_stale')  # checkpoint moved
            denied = [e['data']['reason'] for e in led.events() if e['kind'] == 'release_denied']
            self.assertEqual(denied, ['candidate_stale'])
            self.assertEqual(led.candidate(cid)['hold'], 'checkpoint')
            led.finish_attempt(held['id'], 'cancelled', True, used_seconds=0, attribution='operator',
                               reason='cancelled')
            self.assertEqual(led.owned_work()['attempts'], [])

            owned = self.plan_ws()
            for taken in (self.workspace('a'), {'path': owned['path'], 'cleanup_id': owned['cleanup_id']}):
                self.assertEqual(self.code(led.create_candidate, 'p1', *(later[:3] + (taken,) + later[4:])),
                                 'workspace_conflict', taken)
            self.assertEqual((led.candidate(cid)['state'], len(led.candidates())),
                             ('implemented', 1))  # rolled back: not superseded

            self.operator('stopped')
            self.assertEqual(self.code(led.create_candidate, 'p1', *later), 'control_stopped')
            self.assertEqual(led.create_candidate('p1', *args)['id'], cid)  # an identical call is restart-safe


class PlanWorkspaceTests(Base):
    """Plan-owned integration workspace and checkpoints. Unless a test says otherwise the
    journal outcomes are simulated completed state (state-unit) and the observations are
    simulated engine facts, not native proof; the ledger itself runs no Git."""

    GRANT = ('commit', 'integrate')

    def observe_ws(self, ws, contributions):
        """Every fact read from the real linked worktree, as the engine would query Git."""
        head = self.git('-C', ws['path'], 'rev-parse', 'HEAD')
        return {'confirmed': self.git('-C', ws['path'], 'status', '--porcelain') == '', 'head': head,
                'branch': self.git('-C', ws['path'], 'symbolic-ref', '--short', 'HEAD'),
                'path': self.git('-C', ws['path'], 'rev-parse', '--show-toplevel'),
                'ancestors': {sha: self.is_ancestor(sha, head)
                              for sha in (self.base, *contributions.values())}}

    def test_fx_fields_are_the_adapter_spec_fields(self):
        for kind, fields in cl._FX_FIELDS.items():
            self.assertEqual(fields, {item.name for item in dataclasses.fields(fx.SPEC_TYPES[kind])}, kind)

    def test_registration_creation_and_checkpoint_are_idempotent_across_crash_and_restart(self):
        self.init()
        ws = self.plan_ws()
        spec = self.ws_spec(ws, 'worktree.create')
        with self.lock() as led:
            self.submit(led, [task('a'), task('b', scope=['docs'])], effects=self.GRANT)
            self.assertEqual((led.plan_workspace('p1'), led.checkpoint('p1')), (None, None))
            self.assertEqual(self.code(led.plan_effect_intent, 'p1', 'worktree.create', spec),
                             'plan_workspace_required')
            view = led.register_plan_workspace('p1', **ws)
            keys = ('plan_id', 'epoch', 'path', 'cleanup_id', 'branch', 'base_sha', 'write_scope', 'state')
            self.assertEqual({key: view[key] for key in keys},
                             {'plan_id': 'p1', 'epoch': 1, **ws, 'write_scope': ['src/a', 'docs'],
                              'state': 'registered'})
            self.assertEqual(led.owned_work()['workspaces'], [])  # a name is owned; nothing exists yet
        with self.lock() as led:  # crash after the registration
            self.assertEqual(led.register_plan_workspace('p1', **ws)['id'], view['id'])
            changes = (dict(path=self.plan_ws('p1', 2)['path']), dict(cleanup_id='other'),
                       dict(branch='sdlc/other'), dict(base_sha=R1))
            for change in changes:
                self.assertEqual(self.code(led.register_plan_workspace, 'p1', **dict(ws, **change)),
                                 'plan_workspace_conflict', change)
            created = led.plan_effect_intent('p1', 'worktree.create', spec)
        with self.lock() as led:  # crash between the intent and its outcome
            self.assertEqual(led.plan_workspace('p1')['state'], 'creating')
            self.assertEqual(self.code(led.plan_effect_intent, 'p1', 'worktree.create', spec),
                             'effect_unresolved')  # exactly one reconcilable intent, never a second
            owned = led.owned_work()
            self.assertEqual([(e['id'], e['task_id'], e['plan_id'], e['owner'], e['kind'])
                              for e in owned['effects']], [(created, None, 'p1', 'plan', 'worktree.create')])
            initial = ('p1', None, self.base, {}, created, self.seen_ws(ws, self.base, {}))
            self.assertEqual(self.code(led.record_checkpoint, *initial), 'plan_workspace_state')
            led.effect_reconcile(created, 'done', {'observed': 'confirmed'})
            first = led.record_checkpoint(*initial)
            self.assertEqual((first['sha'], first['contributions'], first['effect_id'], first['expected'],
                              first['workspace']['state']), (self.base, {}, created, None, 'created'))
        with self.lock() as led:  # crash after the checkpoint: the replay changes nothing
            self.assertEqual(led.record_checkpoint(*initial)['id'], first['id'])
            self.assertEqual(len(led.status()['checkpoints']), 1)
            self.assertEqual(self.code(led.plan_effect_intent, 'p1', 'worktree.create', spec),
                             'plan_workspace_state')
            listed = [(w['effect_id'], w['owner'], w['plan_id'], w['task_id'], w['branch'], w['head'])
                      for w in led.owned_work()['workspaces']]
            self.assertEqual(listed, [(created, 'plan', 'p1', None, ws['branch'], self.base)])
            self.assertEqual(led.plan('p1')['workspace']['id'], view['id'])
            self.assertEqual(led.plan('p1')['checkpoint']['id'], first['id'])

    def test_only_the_registered_identity_inside_the_owner_state_is_owned_by_the_plan(self):
        self.init()
        ws, root, create = self.plan_ws(), os.path.join(self.state, cl.WORKSPACE_DIR), 'worktree.create'
        with self.lock() as led:
            self.submit(led, [task('a')], effects=self.GRANT)
            self.submit(led, [task('z')], pid='p2')
            self.submit(led, [task('q')], pid='p3', effects=self.GRANT)
            self.assertEqual(led.integration_branch_prefix(), 'sdlc/')
            refused = [
                ('unknown_plan', 'nope', ws),
                ('effect_unauthorized', 'p2', self.plan_ws('p2')),  # no integrate grant
                ('plan_workspace', 'p1', dict(ws, path=os.path.join(self.repo, 'wt'))),
                ('plan_workspace', 'p1', dict(ws, path=root)),
                ('plan_workspace', 'p1', dict(ws, cleanup_id='not a safe id')),
                ('plan_workspace_branch', 'p1', dict(ws, branch='main')),
                ('plan_workspace_branch', 'p1', dict(ws, branch='sdlc/')),
                ('plan_workspace_branch', 'p1', dict(ws, branch='sdlc/../main')),
                ('plan_workspace_base', 'p1', dict(ws, base_sha='HEAD')),
                ('plan_workspace_base', 'p1', dict(ws, base_sha=R1)),  # not the plan origin
                ('workspace_conflict', 'p1', dict(ws, **self.workspace('a'))),  # bound to a task
            ]
            for expected, pid, kwargs in refused:
                self.assertEqual(self.code(led.register_plan_workspace, pid, **kwargs), expected, kwargs)
            self.assertEqual(led.status()['plan_workspaces'], [])
            view = led.register_plan_workspace('p1', **ws)

            other = self.plan_ws('p3')
            for clash in ('path', 'cleanup_id', 'branch'):
                self.assertEqual(self.code(led.register_plan_workspace, 'p3', **dict(other, **{clash: ws[clash]})),
                                 'workspace_conflict', clash)
            mine = {'path': ws['path'], 'cleanup_id': ws['cleanup_id']}
            led.invalidate_binding('q', 'rebind onto the plan workspace')
            self.assertEqual(self.code(led.bind_execution, 'q', self.base, {}, dict(mine),
                                       self.proof(self.base)), 'workspace_conflict')
            self.assertEqual(self.code(led.effect_intent, 'a', create, dict(mine)), 'effect_workspace')

            good = self.ws_spec(ws, create)

            def inner(**change):
                return dict(good, fx=dict(good['fx'], **change))

            bad = [
                ('effect_unauthorized', 'task.commit', good),
                ('effect_unauthorized', 'integrate', good),
                ('effect_unauthorized', 'push', good),
                ('effect_unauthorized', create, 'spec'),
                ('effect_spec', create, {key: value for key, value in good.items() if key != 'fx'}),
                ('effect_spec', create, inner(checks_passed=True)),
                ('effect_spec', create, dict(good, fx={k: v for k, v in good['fx'].items() if k != 'repo'})),
                ('effect_workspace', create, dict(good, branch='sdlc/other')),
                ('effect_workspace', create, dict(good, path=self.plan_ws('p1', 2)['path'])),
                ('effect_workspace', create, dict(good, cleanup_id='other')),
                ('effect_workspace', create, dict(good, base_sha=R1)),
                ('effect_workspace', create, inner(branch='main')),
                ('effect_workspace', create, inner(path=os.path.join(self.repo, 'wt'))),
                ('effect_workspace', create, inner(base_sha=R1)),
                ('effect_workspace', create, inner(common_dir=os.path.join(self.tmp, 'other', '.git'))),
                ('plan_workspace_state', 'worktree.remove', self.ws_spec(ws, 'worktree.remove')),
            ]
            for expected, kind, spec in bad:
                self.assertEqual(self.code(led.plan_effect_intent, 'p1', kind, spec), expected, (kind, spec))
            self.operator('stopped')
            self.assertEqual(self.code(led.plan_effect_intent, 'p1', create, good), 'control_stopped')
            self.assertEqual(self.code(led.register_plan_workspace, 'p3', **other), 'control_stopped')
            self.operator('running')
            self.assertEqual(led.status()['effects'], [])

            created = led.plan_effect_intent('p1', create, good)
            row = led.status()['effects'][0]
            self.assertEqual((row['task_id'], row['plan_id'], row['owner'], row['spec']),
                             (None, 'p1', 'plan', dict(good, write_scope=['src/a'], workspace=view['id'],
                                                        epoch=1)))
            led.effect_result(created, 'done')
            led.record_checkpoint('p1', None, self.base, {}, created, self.seen_ws(ws, self.base, {}))
            # A task never removes the plan workspace, whatever it names.
            self.assertEqual(self.code(led.effect_intent, 'a', 'worktree.remove', dict(mine)),
                             'effect_unauthorized')
            self.assertEqual(self.code(led.plan_effect_intent, 'p3', 'worktree.remove',
                                       self.ws_spec(ws, 'worktree.remove')), 'effect_unauthorized')
            intents = [e['data'] for e in led.events() if e['kind'] == 'effect_intent']
            self.assertEqual(intents, [{'plan': 'p1', 'kind': create, 'effect': None}])
        raw = sqlite3.connect(os.path.join(self.state, cl.LEDGER_FILE))
        self.addCleanup(raw.close)
        columns = 'plan_id, owner, kind, spec, state, fence, at'
        statements = (
            # An effect has a true owner: no task-owned row without a task, no fake task on a
            # plan-owned row and no plan-owned kind beyond the two worktree effects.
            f"INSERT INTO effects({columns}) VALUES ('p1', 'task', 'worktree.create', '{{}}', 'intent', 1, 'x')",
            f"INSERT INTO effects({columns}) VALUES ('p1', 'plan', 'push', '{{}}', 'intent', 1, 'x')",
            f"INSERT INTO effects(task_id, {columns}) "
            "VALUES ('a', 'p1', 'plan', 'worktree.create', '{}', 'intent', 1, 'x')",
            "UPDATE plan_workspaces SET branch = 'main'", 'DELETE FROM plan_workspaces',
            "UPDATE checkpoints SET sha = 'x'", 'DELETE FROM checkpoints')
        for statement in statements:
            with self.assertRaises(sqlite3.DatabaseError, msg=statement):
                raw.execute(statement)

    def test_checkpoints_advance_only_by_compare_and_set_on_a_confirmed_owned_effect(self):
        self.init()
        ws = self.plan_ws()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')], effects=self.GRANT)
            self.submit(led, [task('z')], pid='p2', effects=self.GRANT)
            self.assertEqual(self.code(led.effect_intent, 'a', 'integrate', {}), 'task_state')
            first, second = self.commit('src/a/work.txt'), self.commit('src/b/work.txt')
            self.accept(led, 'a', first)
            self.accept(led, 'b', second)
            spec = self.integrate_spec(ws, self.base, first)
            self.assertEqual(self.code(led.effect_intent, 'a', 'integrate', spec), 'checkpoint_required')
            created = self.open_plan(led)
            origin = led.checkpoint('p1')

            def inner(**change):
                return dict(spec, fx=dict(spec['fx'], **change))

            unsafe = [
                ('effect_spec', {}),
                ('effect_spec', inner(checks_passed=True)),
                ('stale_identity', dict(spec, expected_base=first)),
                ('stale_identity', dict(spec, result=second)),
                ('stale_identity', dict(spec, branch='main')),
                ('stale_identity', inner(target_branch='main')),
                ('stale_identity', inner(integration_worktree=self.workspace('a')['path'])),
                ('stale_identity', inner(expected_base=second)),
                ('stale_identity', inner(task_result=second)),
                ('stale_identity', inner(common_dir=os.path.join(self.tmp, 'other', '.git'))),
            ]
            for expected, bad in unsafe:
                self.assertEqual(self.code(led.effect_intent, 'a', 'integrate', bad), expected, bad)
            merged = led.effect_intent('a', 'integrate', spec)
            behind = self.integrate_spec(ws, self.base, second)
            self.assertEqual(self.code(led.effect_intent, 'b', 'integrate', behind), 'effect_unresolved')

            record, step = led.record_checkpoint, {'a': first}
            seen = self.seen_ws(ws, first, step, real=True)
            self.assertEqual(seen['ancestors'], {self.base: True, first: True})
            good = ('p1', self.base, first, step, merged, seen)
            self.assertEqual(self.code(record, *good), 'checkpoint_effect')  # an intent is not an outcome
            led.effect_result(merged, 'done')
            self.assertEqual(self.code(led.effect_intent, 'b', 'integrate', behind), 'checkpoint_pending')
            self.assertEqual(led.plan_workspace('p1')['unrecorded'], [merged])

            def swap(index, value):
                return good[:index] + (value,) + good[index + 1:]

            both = {'a': first, 'b': second}
            refused = [
                ('unknown_plan', swap(0, 'nope')),
                ('plan_workspace_required', swap(0, 'p2')),
                ('checkpoint_sha', swap(1, 'HEAD')),
                ('checkpoint_sha', swap(2, 'HEAD')),
                ('checkpoint_stale', swap(1, None)),
                ('checkpoint_stale', swap(1, first)),
                ('checkpoint_contributions', swap(3, {'a': 'HEAD'})),
                ('checkpoint_contributions', ('p1', self.base, first, {}, merged, self.seen_ws(ws, first, {}))),
                ('checkpoint_contributions', ('p1', self.base, first, both, merged,
                                              self.seen_ws(ws, first, both))),  # b was never integrated
                ('checkpoint_effect', swap(4, True)),
                ('checkpoint_effect', swap(4, str(merged))),
                ('checkpoint_effect', swap(4, 9999)),  # unknown
                # The creation already yielded the immutable origin checkpoint: reusing it with
                # other facts conflicts with that checkpoint before any step is considered.
                ('checkpoint_conflict', swap(4, created)),
                ('checkpoint_evidence', swap(5, 'exit 0')),
                ('checkpoint_evidence', swap(5, dict(seen, exit_code=0))),
                ('checkpoint_evidence', swap(5, {key: value for key, value in seen.items() if key != 'path'})),
                ('checkpoint_unproven', swap(5, dict(seen, confirmed=1))),
                ('checkpoint_unproven', swap(5, dict(seen, head=second))),
                ('checkpoint_unproven', swap(5, dict(seen, branch='main'))),
                ('checkpoint_unproven', swap(5, dict(seen, path=self.repo))),
                ('checkpoint_unproven', swap(5, dict(seen, ancestors={self.base: True}))),
                ('checkpoint_unproven', swap(5, dict(seen, ancestors={self.base: True, first: 1}))),
                # Real Git: the plan origin does not contain the integrated result.
                ('checkpoint_unproven', ('p1', self.base, self.base, step, merged,
                                         self.seen_ws(ws, self.base, step, real=True))),
            ]
            def retained():
                return (led.checkpoint('p1'), led.status()['checkpoints'],
                        [event['data'] for event in led.events() if event['kind'] == 'checkpoint'])

            untouched = retained()
            self.assertEqual(len(untouched[1]), 1)
            for expected, bad in refused:
                self.assertEqual(self.code(record, *bad), expected, bad)
                self.assertEqual(retained(), untouched, bad)  # a refusal records nothing
            self.assertEqual(led.checkpoint('p1')['id'], origin['id'])

            one = record(*good)
            self.assertEqual((one['sha'], one['contributions'], one['effect_id'], one['expected'],
                              one['previous']), (first, step, merged, self.base, origin['id']))
            self.assertEqual(record(*good)['id'], one['id'])  # the same effect and facts: idempotent
            replays = (('p1', self.base, second, step, merged, self.seen_ws(ws, second, step)),
                       ('p1', first, first, step, merged, seen))
            settled = retained()
            self.assertEqual([c['id'] for c in settled[1]], [origin['id'], one['id']])
            for replay in replays:
                self.assertEqual(self.code(record, *replay), 'checkpoint_conflict', replay)
                self.assertEqual(retained(), settled, replay)  # the recorded checkpoint is immutable
            self.assertEqual(self.code(led.effect_intent, 'b', 'integrate', behind), 'stale_identity')

            other = led.effect_intent('b', 'integrate', self.integrate_spec(ws, first, second))
            led.effect_result(other, 'done')
            two = record('p1', first, second, both, other, self.seen_ws(ws, second, both, real=True))
            self.assertEqual(led.checkpoint('p1')['id'], two['id'])
            self.assertEqual([(c['sha'], c['previous']) for c in led.status()['checkpoints']],
                             [(self.base, None), (first, origin['id']), (second, one['id'])])

            # A contribution withdrawn before its checkpoint is never recorded.
            again = led.effect_intent('a', 'integrate', self.integrate_spec(ws, second, first))
            led.effect_result(again, 'done')
            led.invalidate_binding('a', 'withdrawn before the checkpoint')
            self.assertEqual(self.code(record, 'p1', second, R1, both, again, self.seen_ws(ws, R1, both)),
                             'checkpoint_effect')
            self.assertEqual(led.plan_workspace('p1')['unrecorded'], [again])
            self.assertEqual(led.checkpoint('p1')['id'], two['id'])
            self.assertIn('checkpoint', [event['kind'] for event in led.events()])

    def test_facts_observed_from_a_real_worktree_advance_the_checkpoint_and_derive_a_candidate(self):
        """Real Git stands in for the adapter and every observation is read from the real
        linked worktree. The journal outcomes, launches and receipts stay simulated state."""
        self.init()
        ws = self.plan_ws()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')], effects=self.GRANT)
            first, second = self.commit('src/a/work.txt'), self.commit('src/b/work.txt')
            self.accept(led, 'a', first)
            self.accept(led, 'b', second)
            led.register_plan_workspace('p1', **ws)
            created = led.plan_effect_intent('p1', 'worktree.create', self.ws_spec(ws, 'worktree.create'))
            os.makedirs(os.path.dirname(ws['path']), mode=0o700, exist_ok=True)
            self.git('-C', self.repo, 'worktree', 'add', '-q', '-b', ws['branch'], ws['path'], self.base)
            led.effect_result(created, 'done')
            origin = self.observe_ws(ws, {})
            self.assertEqual((origin['confirmed'], origin['head'], origin['branch'], origin['path']),
                             (True, self.base, ws['branch'], ws['path']))
            led.record_checkpoint('p1', None, self.base, {}, created, origin)

            contributions, journal = {}, {}
            for tid, result in (('a', first), ('b', second)):
                before = led.checkpoint('p1')['sha']
                journal[tid] = led.effect_intent(tid, 'integrate', self.integrate_spec(ws, before, result))
                self.git('-C', ws['path'], 'merge', '-q', '--ff-only', result)
                led.effect_result(journal[tid], 'done')
                contributions[tid] = result
                seen = self.observe_ws(ws, contributions)
                led.record_checkpoint('p1', before, seen['head'], dict(contributions), journal[tid], seen)
            head = led.checkpoint('p1')
            self.assertEqual((head['sha'], head['contributions'], head['workspace']['unrecorded']),
                             (second, contributions, []))

            # Simulated positive facts about another commit do not move the registry.
            self.assertEqual(self.code(self.derive, led, first, contributions, journal), 'checkpoint_stale')
            view = self.derive(led, second, contributions, journal, real=True)
            self.assertEqual((view['stage'], view['origin'], view['result']), ('checking', self.base, second))
            self.accept_candidate(led, view, reviewer='beta')  # one Claude profile set, no publication grant
            done = led.candidate(view['id'])
            self.assertEqual((done['stage'], done['current'], done['publishable'], done['publication_hold']),
                             ('accepted', True, False, 'codex_unavailable'))

    def test_plan_owned_cleanup_survives_stop_and_context_drift_and_blocks_readmission(self):
        self.init()
        ws = self.plan_ws()
        with self.lock() as led:
            self.submit(led, [task('a'), task('b')], effects=self.GRANT)
            self.open_plan(led)
            remove = self.ws_spec(ws, 'worktree.remove')
            running = led.claim('a', 'alpha')
            self.assertEqual(self.code(led.plan_effect_intent, 'p1', 'worktree.remove', remove),
                             'plan_workspace_busy')
            self.operator('stopped')
            self.assertEqual(self.code(led.plan_effect_intent, 'p1', 'worktree.remove', remove),
                             'plan_workspace_busy')  # STOP alone never removes a workspace in use
            led.finish_attempt(running['id'], 'cancelled', True, used_seconds=0, attribution='operator',
                               reason='stop')
            foreign = [
                ('effect_unauthorized', dict(remove, cleanup_id='other')),
                ('effect_workspace', dict(remove, branch='main')),
                ('effect_workspace', dict(remove, fx=dict(remove['fx'], cleanup_root=self.tmp))),
                ('effect_workspace', dict(remove, fx=dict(remove['fx'], expected_head='HEAD'))),
            ]
            for expected, bad in foreign:
                self.assertEqual(self.code(led.plan_effect_intent, 'p1', 'worktree.remove', bad), expected, bad)
            mine = {'path': ws['path'], 'cleanup_id': ws['cleanup_id']}
            self.assertEqual(self.code(led.effect_intent, 'a', 'worktree.remove', mine), 'effect_unauthorized')

            led.reconcile_context(self.policy(max_parallel=1, review_reserve=0), dict(self.ident), 'Owner')
            fresh = self.fresh_authority(led, effects=self.GRANT)
            held = led.readmit_plan('p1', fresh, dict(self.ident))
            self.assertEqual((held['status'], [(w['owner'], w['path'], w['epoch']) for w in held['workspaces']]),
                             ('hold', [('plan', ws['path'], 1)]))
            self.assertIsNone(led.plan_workspace('p1'))  # none in the current context
            earlier = led.plan_workspace('p1', epoch=1)
            self.assertEqual((earlier['state'], earlier['current']), ('created', False))
            self.assertEqual(self.code(led.register_plan_workspace, 'p1', **self.plan_ws('p1', 2)),
                             'control_stopped')

            removed = led.plan_effect_intent('p1', 'worktree.remove', remove)  # owned cleanup: STOP and drift
            self.assertEqual(self.code(led.plan_effect_intent, 'p1', 'worktree.remove', remove),
                             'effect_unresolved')
            led.effect_result(removed, 'done')
            self.assertEqual(led.owned_work()['workspaces'], [])
            self.assertEqual(led.plan_workspace('p1', epoch=1)['state'], 'removed')
            self.assertEqual(led.readmit_plan('p1', fresh, dict(self.ident))['status'], 'readmitted')
            self.assertEqual(led.control(), 'stopped')

            led.set_control('running')
            self.assertEqual(self.code(led.register_plan_workspace, 'p1', **ws), 'workspace_conflict')
            ws2 = self.plan_ws('p1', 2)
            second = led.register_plan_workspace('p1', **ws2)
            self.assertEqual((second['epoch'], second['state'], led.checkpoint('p1')), (2, 'registered', None))

            # A failed creation is retried, never adopted; a confirmed removal is final.
            spec = self.ws_spec(ws2, 'worktree.create')
            failed = led.plan_effect_intent('p1', 'worktree.create', spec)
            led.effect_result(failed, 'failed')
            self.assertEqual(led.plan_workspace('p1')['state'], 'failed')
            self.assertEqual([w['effect_id'] for w in led.owned_work()['workspaces']], [failed])
            retried = led.plan_effect_intent('p1', 'worktree.create', spec)
            led.effect_result(retried, 'done')
            gone = led.plan_effect_intent('p1', 'worktree.remove', self.ws_spec(ws2, 'worktree.remove'))
            led.effect_result(gone, 'done')
            self.assertEqual(self.code(led.plan_effect_intent, 'p1', 'worktree.create', spec),
                             'plan_workspace_state')
            self.assertEqual(led.owned_work()['workspaces'], [])


class GovernanceTests(Base):
    """Publication governance. The Codex profile is simulated configured policy state and its
    review a simulated released attempt: no native Codex ran and nothing is published."""

    EFFECTS = ('commit', 'integrate', 'push')
    PUBLISH = {'branch': 'sdlc/p1', 'result': R2}

    def start(self, **over):
        self.init(effects=list(self.EFFECTS), delivery=self.delivery(), **over)

    def ready(self, led):
        """State-unit: one accepted, integrated task and its derived candidate."""
        self.submit(led, [task('a')], effects=self.EFFECTS)
        self.accept(led, 'a', R1)
        self.open_plan(led)
        merged = self.integrate(led, 'a', R2)
        return self.derive(led, R2, {'a': R1}, {'a': merged})

    def test_a_claude_review_accepts_locally_but_never_publishes(self):
        self.start(profiles=self.reviewers())
        with self.lock() as led:
            view = self.ready(led)
            cid = view['id']
            gate = self.accept_candidate(led, view, reviewer='beta')
            held = led.candidate(cid)
            self.assertEqual((held['stage'], held['current'], held['publishable'], held['publication_hold']),
                             ('accepted', True, False, 'codex_review_required'))
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(self.PUBLISH)),
                             'codex_review_required')
            self.assertEqual(self.code(led.transition, cid, 'accepted', 'published', gate),
                             'codex_review_required')
            self.assertEqual(self.code(led.effect_intent, 'a', 'push', dict(self.PUBLISH, result=R1)),
                             'candidate_required')  # an accepted task is still no publication
            self.assertEqual([e for e in led.status()['effects'] if e['kind'] == 'push'], [])
            self.assertEqual(led.status()['governance'],
                             {'publication_review': 'codex', 'reviewers': ['codex'],
                              'role_override': 'attended_handoff'})

    def test_without_a_configured_codex_reviewer_publication_is_a_named_incomplete(self):
        self.start()
        with self.lock() as led:
            view = self.ready(led)
            self.accept_candidate(led, view, reviewer='beta')
            held = led.candidate(view['id'])
            self.assertEqual((held['stage'], held['publishable'], held['publication_hold']),
                             ('accepted', False, 'codex_unavailable'))
            self.assertEqual(self.code(led.effect_intent, view['id'], 'push', dict(self.PUBLISH)),
                             'codex_unavailable')  # no Claude fallback
            self.assertEqual(led.status()['governance']['reviewers'], [])

    def test_a_configured_codex_review_of_the_candidate_covers_publication(self):
        self.start(profiles=self.reviewers())
        with self.lock() as led:
            view = self.ready(led)
            cid, gate = view['id'], self.gate(led, R2)
            for name in view['checks']:
                self.check(led, cid, gate, name=name)
            unavailable = led.claim(cid, 'codex', 'review')
            led.finish_attempt(unavailable['id'], 'failure', True, used_seconds=0, attribution='availability',
                               reason='quota', category='rate_limited')
            self.assertEqual(self.code(led.record_review, cid, unavailable['id'], 'approve', gate),
                             'review_attempt')  # an unavailable Codex approves nothing
            review = self.released(led, cid, 'codex', 'review')
            led.finish_attempt(review['id'], 'success', True, category='success')
            led.record_review(cid, review['id'], 'approve', gate)
            self.assertEqual(self.code(led.effect_intent, cid, 'push', dict(self.PUBLISH)),
                             'candidate_unaccepted')
            led.transition(cid, 'reviewed', 'accepted', gate)
            ready = led.candidate(cid)
            self.assertEqual((ready['publishable'], ready['publication_hold']), (True, None))
            pushed = led.effect_intent(cid, 'push', dict(self.PUBLISH))
            led.effect_result(pushed, 'done', {'sha': R2})
            led.transition(cid, 'accepted', 'published', gate)
            reviews = [(e['name'], e['passed']) for e in led.status()['evidence']
                       if e['task_id'] == cid and e['kind'] == 'review']
            self.assertEqual(reviews, [('codex', 1)])  # one review serves review and decision


class ObservationTests(Base):
    """Routing observations come from the real normalizer with fixture times; nothing here
    observed a real account, quota or credential."""

    @staticmethod
    def seen(category, ended, captured=None):
        return cr.observation_from_outcome('claude', category, None,
                                           ended if captured is None else captured, ended)

    def test_late_or_ordinary_outcomes_never_clear_a_hold(self):
        self.init()
        base = int(time.time()) - 1000
        refresh = cr.observation_from_operator_refresh
        with self.lock() as led:
            def current():
                return led.status()['observations'][0]['data']

            self.assertEqual(led.observe('alpha', self.seen('success', base + 50))['reason'], 'admitted')
            hold = self.seen('auth_required', base + 200)
            self.assertTrue(led.observe('alpha', hold)['admitted'])
            late = led.observe('alpha', self.seen('success', base + 100, base + 500))
            self.assertEqual((late['admitted'], late['reason']), (False, 'stale'))
            self.assertEqual(led.observe('alpha', self.seen('success', base + 300))['reason'], 'hold_sticky')
            self.assertEqual(led.observe('alpha', refresh('claude', base + 200))['reason'], 'hold_sticky')
            self.assertEqual(led.observe('alpha', refresh('claude', base + 150))['reason'], 'stale')
            self.assertEqual(current(), hold)

            renewed = refresh('claude', base + 400)  # only an explicit newer refresh clears the hold
            self.assertTrue(led.observe('alpha', renewed)['admitted'])
            self.assertEqual(current(), renewed)
            self.assertEqual(led.observe('alpha', self.seen('success', base + 350, base + 600))['reason'],
                             'stale')
            self.assertTrue(led.observe('alpha', self.seen('success', base + 450))['admitted'])
            self.assertEqual(current()['availability'], 'available')

            # Equal evidence time: the known hold wins, and the hold then stays.
            self.assertEqual(led.observe('alpha', self.seen('permission_denied', base + 450))['reason'],
                             'admitted')
            self.assertEqual(led.observe('alpha', self.seen('success', base + 450))['reason'], 'hold_sticky')
            led.observe('beta', self.seen('rate_limited', base + 10))
            self.assertEqual(led.observe('beta', self.seen('success', base + 10))['reason'],
                             'tie_conservative')
            self.assertEqual(led.observe('beta', self.seen('success', base + 11))['reason'], 'admitted')

            history = led.observation_history('alpha')
            self.assertEqual([row['reason'] for row in history],
                             ['admitted', 'admitted', 'stale', 'hold_sticky', 'hold_sticky', 'stale',
                              'admitted', 'stale', 'admitted', 'admitted', 'hold_sticky'])
            self.assertEqual((history[2]['admitted'], history[2]['data']['captured_at']),
                             (False, base + 500))  # the raw late outcome is retained
            self.assertEqual(len(led.observation_history()), 14)
        with self.lock() as led:
            latest = {row['profile_id']: row['data']['availability'] for row in led.status()['observations']}
            self.assertEqual(latest, {'alpha': 'permission_hold', 'beta': 'available'})

    def test_only_strict_typed_observations_are_stored(self):
        self.init()
        now = int(time.time())
        good = self.seen('success', now - 10, now - 5)
        refused = [
            dict(good, ended_at=True), dict(good, ended_at=float('inf')), dict(good, ended_at=-1),
            dict(good, ended_at=str(now)), dict(good, ended_at=now), dict(good, captured_at=now + 3600),
            dict(good, captured_at=10 ** 20), dict(good, provider='codex'), dict(good, schema='other/v1'),
            dict(good, source='worker'), dict(good, availability='auth_hold'),
            dict(good, category='auth_required'), dict(good, retry_at=now + 5),
            dict(good, note='token sk-live'), dict(good, quota_status='Rejected: see the logs'),
            dict(good, quota_utilization=-1), dict(good, quota_seen=1.5),
            {key: value for key, value in good.items() if key != 'ended_at'}, list(good), None,
        ]
        with self.lock() as led:
            for item in refused:
                self.assertEqual(self.code(led.observe, 'alpha', item), 'metadata', item)
            self.assertEqual(self.code(led.observe, 'nobody', good), 'profile_role')
            self.assertEqual(led.observation_history(), [])
            self.assertEqual(led.status()['observations'], [])
            stored = led.observe('alpha', good)
            self.assertEqual((stored['admitted'], stored['reason']), (True, 'admitted'))
            self.assertEqual(led.status()['observations'][0]['data'], good)


if __name__ == '__main__':
    unittest.main()
