"""Operator CLI for the optional persistent delivery controller, in disposable layouts.

Each test uses a temporary Git repository, private temporary account directories, a copied
disposable installed bundle layout (skills/delivery/scripts beside skills/verified-handoff,
with the delivery resources the runtime digest binds; without controller_engine unless a
test writes a fake one), real SQLite and scripted stdin. Engine-side request consumption is exercised through the public
controller_requests consumer in a separate process that holds a real ControllerLock. No
provider, network, real home or real account directory is touched.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / '.claude/skills'
SCRIPTS = SKILLS / 'delivery/scripts'
ENGINE_FILE = 'controller_engine.py'
# Non-controller files the runtime digest requires, copied byte-for-byte into the same
# relative place of the disposable bundle (Claude layout: delivery + verified-handoff).
BUNDLE_RESOURCES = ('delivery/SKILL.md', 'delivery/references/acceptance-by-task.md',
                    'delivery/references/task-contract.md',
                    'verified-handoff/scripts/evidence.py')
GIT = shutil.which('git')
SH = shutil.which('sh') or '/bin/sh'

# Engine-side stand-in: holds a real ControllerLock with the current identity and uses the
# public consumer API. Modes: consume (default), hold (keep the lock until stdin), crash
# (admit through Ledger.submit and exit before any acknowledgement).
CONSUMER = r'''
import json, sys
runtime, state, mode = sys.argv[1:4]
sys.path.insert(0, runtime)
import controller
import controller_ledger as ledger_mod
import controller_requests as inbox
import controller_routing as routing

probe = ledger_mod.Ledger.open(state, readonly=True)
common, policy = probe.common_dir, probe.policy
probe.close()
identity, _ = controller._identity(policy)
results = []
with ledger_mod.ControllerLock(common, state, identity=identity) as ledger:
    if mode == 'hold':
        print('held', flush=True)
        sys.stdin.readline()
    elif mode == 'crash':
        pending = [v for v in inbox.list_requests(state) if v['status'] == 'pending']
        record, _sha = inbox.load_request(state, pending[0]['id'])
        ledger.submit(record['payload']['plan'], record['payload']['authority'], identity)
    else:
        def refresh(request):
            ledger.observe(request.profile_id, routing.observation_from_operator_refresh(
                request.provider, request.requested_at))
        results = inbox.consume_pending(ledger, identity, on_refresh=refresh)
    submits = sum(1 for event in ledger.events() if event['kind'] == 'submit')
print(json.dumps({'results': results, 'submits': submits}))
'''

ENGINE_BODY = '''
import json


def _write(entry):
    with open(RECORD, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry) + '\\n')


def run_controller(state_dir, *, once, background, poll_seconds):
    _write({'call': 'run_controller', 'state': state_dir, 'once': once,
            'background': background, 'poll_seconds': poll_seconds})
    return 0
'''

RECOVER_BODY = '''

def recover_owned(state_dir):
    _write({'call': 'recover_owned', 'state': state_dir})
    return 0
'''

# Needs CLEANUP_RESULT defined in the prefix; records the call only (CLI wiring, not cleanup).
CLEANUP_BODY = '''

def cleanup_workspaces(state_dir, plan_id, actor):
    _write({'call': 'cleanup_workspaces', 'state': state_dir, 'plan_id': plan_id,
            'actor': actor})
    return CLEANUP_RESULT
'''


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(data if isinstance(data, str) else json.dumps(data))
    os.chmod(path, 0o600)


def utc_now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def runtime_sources():
    """Every shipped controller runtime file (the set the runtime digest binds), never a
    controller_engine: tests that need one write a fake into the copy."""
    names = sorted(p.name for p in SCRIPTS.iterdir() if p.is_file() and p.name != ENGINE_FILE
                   and (p.name == 'sdlc_controller.py'
                        or (p.name.startswith('controller') and p.name.endswith('.py'))))
    if 'controller.py' not in names:
        raise AssertionError(f'controller.py not found in {SCRIPTS}')
    return names


def install_bundle(skills_root):
    """Copy a valid disposable installed layout under ``skills_root``; return its scripts/."""
    runtime = skills_root / 'delivery/scripts'
    runtime.mkdir(parents=True)
    for name in runtime_sources():
        shutil.copy2(SCRIPTS / name, runtime / name)
    for rel in BUNDLE_RESOURCES:
        target = skills_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SKILLS / rel, target)
    return runtime


@unittest.skipUnless(GIT, 'git is required')
class ControllerCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='controller-cli-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        home = self.tmp / 'home'
        home.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('GIT_', 'CLAUDE_', 'CODEX_'))}
        self.env.update(HOME=str(home), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        LC_ALL='C')
        self.runtime = install_bundle(self.tmp / 'skills')
        self.repo = self.tmp / 'repo'
        (self.repo / 'src').mkdir(parents=True)
        (self.repo / 'AGENTS.md').write_text('Follow the rules.\n')
        (self.repo / 'src/app.txt').write_text('app\n')
        self.git('init', '-q')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'baseline')
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.claude_dir = self.tmp / 'accounts/claude-a'
        self.codex_dir = self.tmp / 'accounts/codex-b'
        self.claude_dir.mkdir(parents=True)
        self.codex_dir.mkdir(parents=True)
        self.owner = self.tmp / 'owner'
        self.owner.mkdir(mode=0o700)
        self.state = self.tmp / 'state'
        self.binding = self.repo / '.git/sdlc-controller.binding'
        self.policy_path = self.owner / 'policy.json'

    def git(self, *args):
        return subprocess.run([GIT, '-C', str(self.repo), '-c', 'user.name=Test', '-c',
                               'user.email=test@example.invalid', *args], env=self.env,
                              check=True, capture_output=True, text=True).stdout

    def cli(self, *args, stdin=''):
        return subprocess.run([sys.executable, '-I', '-B', str(self.runtime / 'controller.py'),
                               *map(str, args)], input=stdin, capture_output=True, text=True,
                              env=self.env, timeout=120)

    def consumer_command(self, mode):
        return [sys.executable, '-I', '-B', '-c', CONSUMER, str(self.runtime), str(self.state), mode]

    def consume(self, mode='consume'):
        result = subprocess.run(self.consumer_command(mode), capture_output=True, text=True,
                                env=self.env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def policy(self, **limits):
        return {
            'version': 1, 'repository': str(self.repo),
            'profiles': [{'id': 'claude-1', 'provider': 'claude', 'executable': sys.executable,
                          'config_dir': str(self.claude_dir), 'roles': ['implement', 'review']}],
            'auto_route': False, 'execution_enabled': False, 'background_enabled': False,
            'max_parallel': 1, 'review_reserve': 0,
            'limits': {'max_attempts': 3, 'attempt_seconds': 600, 'max_total_seconds': 3600,
                       'max_no_progress': 2, 'max_cost_usd': None, **limits},
            'allowed_checks': {'unit': [sys.executable, '-c', 'pass']},
            'effects': ['commit'], 'delivery': None, 'instruction_paths': ['AGENTS.md']}

    def init_state(self):
        write_private(self.policy_path, self.policy())
        result = self.cli('init', '--state', self.state, '--policy', self.policy_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def status(self):
        result = self.cli('status', '--state', self.state, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def fingerprint(self):
        paths = sorted(p for p in self.state.rglob('*') if p.is_file()) + [self.binding]
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

    def snapshot(self):
        entries = {}
        for path in [self.state, *sorted(self.state.rglob('*')), self.binding]:
            info = path.lstat()
            data = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
            entries[str(path)] = (info.st_mode, info.st_mtime_ns, info.st_size, data)
        return entries

    def plan(self, plan_id='plan-1', task_id='task-1'):
        return {'version': 1, 'id': plan_id, 'objective': 'Adjust app text',
                'input_revision': 'r1', 'base_sha': self.head,
                'tasks': [{'id': task_id, 'objective': 'Edit app', 'kind': 'feature',
                           'depends_on': [], 'write_scope': ['src/'], 'resources': [],
                           'checks': ['unit'], 'acceptance': ['app text updated']}]}

    def plan_digest(self, plan_path):
        digest = self.cli('digest', '--plan', plan_path, '--policy', self.policy_path)
        self.assertEqual(digest.returncode, 0, digest.stderr)
        return digest.stdout.strip()

    def write_authority(self, path, plan_digest, approved_at='2025-01-01T00:00:00Z'):
        write_private(path, {'version': 1, 'plan_digest': plan_digest, 'effects': ['commit'],
                             'authorizer': 'owner', 'approved_at': approved_at})

    def prepare(self, plan_id='plan-1'):
        plan_path = self.owner / f'{plan_id}.json'
        authority_path = self.owner / f'{plan_id}-authority.json'
        write_private(plan_path, self.plan(plan_id))
        plan_digest = self.plan_digest(plan_path)
        self.write_authority(authority_path, plan_digest)
        return plan_path, authority_path, plan_digest

    def submit(self, plan_path, authority_path):
        return self.cli('submit', '--state', self.state, '--plan', plan_path,
                        '--authority', authority_path)

    def tasks(self):
        return [(t['id'], t['state']) for t in self.status()['status']['tasks']]

    def admit_plan(self):
        self.init_state()
        plan_path, authority_path, _ = self.prepare()
        self.assertEqual(self.submit(plan_path, authority_path).returncode, 0)
        self.assertEqual([r['status'] for r in self.consume()['results']], ['admitted'])

    def cleanup(self, plan_id='plan-1', actor='owner'):
        return self.cli('cleanup-workspaces', '--state', self.state, '--plan-id', plan_id,
                        '--actor', actor)

    def request_states(self):
        return [(r['action'], r['status'], r['code']) for r in self.status()['requests']]

    def single_answers(self, confirm='create'):
        return '\n'.join([
            '', '', sys.executable, str(self.claude_dir), '',  # profile 1 with defaults
            'n',                                             # no other profile
            '', '',                                          # auto_route n, max_parallel 1
            '', '', '', '',                                  # default limits
            '',                                              # no checks
            'AGENTS.md', '',                                 # instruction paths
            '', '', '',                                      # commit, integrate, external: n
            '', '',                                          # execution, background: n
            confirm]) + '\n'

    def multi_answers(self):
        return '\n'.join([
            '', '', sys.executable, str(self.claude_dir), '',
            'y', 'codex', '', SH, str(self.codex_dir), '',   # codex defaults to review only
            'n', 'y', '2', '1',
            '', '', '', '',
            'unit', json.dumps([sys.executable, '-c', 'pass']), '',
            'AGENTS.md', '',
            'y', 'y', '',
            '', '',
            'create']) + '\n'

    # ---- setup, init, status, control ------------------------------------------------

    def test_help_says_optional_and_no_autostart(self):
        result = self.cli('--help')
        self.assertEqual(result.returncode, 0)
        text = result.stdout.lower()
        self.assertIn('optional', text)
        self.assertIn('nothing starts automatically', text)
        self.assertIn('queue', text)

    def test_init_and_status_are_read_only_on_repeat(self):
        self.assertIn('created', self.init_state().stdout)
        before = self.fingerprint()
        data = self.status()
        self.assertEqual(data['status']['control'], 'running')
        self.assertEqual(data['identity_check']['runtime'], 'match')
        self.assertEqual(data['identity_check']['rules'], 'match')
        self.assertEqual((data['plans'], data['requests']), ([], []))
        self.assertEqual(self.cli('status', '--state', self.state).returncode, 0)
        self.assertFalse((self.state / 'requests').exists())
        again = self.cli('init', '--state', self.state, '--policy', self.policy_path)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('verified unchanged', again.stdout)
        self.assertEqual(before, self.fingerprint())

    def test_init_refuses_changed_policy_and_keeps_snapshot(self):
        self.init_state()
        before = self.fingerprint()
        write_private(self.policy_path, self.policy(max_attempts=4))
        result = self.cli('init', '--state', self.state, '--policy', self.policy_path)
        self.assertEqual(result.returncode, 1)
        self.assertIn('policy_changed', result.stderr)
        self.assertIn('reconcile', result.stderr)
        self.assertEqual(before, self.fingerprint())

    def test_init_refuses_dirty_instructions(self):
        (self.repo / 'AGENTS.md').write_text('Uncommitted rules.\n')
        write_private(self.policy_path, self.policy())
        result = self.cli('init', '--state', self.state, '--policy', self.policy_path)
        self.assertEqual(result.returncode, 1)
        self.assertIn('dirty_instructions', result.stderr)
        self.assertFalse(self.state.exists())

    def test_status_without_state_is_incomplete(self):
        result = self.cli('status', '--state', self.state)
        self.assertEqual(result.returncode, 2)
        self.assertIn('INCOMPLETE', result.stderr)

    def test_setup_abort_writes_nothing(self):
        result = self.cli('setup', '--repo', self.repo, '--state', self.state,
                          stdin=self.single_answers(confirm='no'))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('nothing was written', result.stderr)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.binding.exists())

    def test_setup_creates_one_profile_policy(self):
        result = self.cli('setup', '--repo', self.repo, '--state', self.state,
                          stdin=self.single_answers())
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = self.status()['policy']
        self.assertEqual([(p['provider'], p['roles'], p['config_dir']) for p in policy['profiles']],
                         [('claude', ['implement', 'review'], str(self.claude_dir))])
        self.assertIsNone(policy['limits']['max_cost_usd'])
        self.assertEqual((policy['effects'], policy['delivery']), ([], None))
        self.assertFalse(policy['execution_enabled'] or policy['background_enabled'])

    def test_setup_multi_profile_and_rerun_preserves(self):
        result = self.cli('setup', '--repo', self.repo, '--state', self.state,
                          stdin=self.multi_answers())
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = self.status()['policy']
        self.assertEqual([(p['id'], p['roles']) for p in policy['profiles']],
                         [('claude-1', ['implement', 'review']), ('codex-2', ['review'])])
        self.assertEqual((policy['max_parallel'], policy['review_reserve']), (2, 1))
        self.assertEqual(policy['effects'], ['commit', 'integrate'])
        self.assertEqual(policy['allowed_checks'], {'unit': [sys.executable, '-c', 'pass']})
        before = self.fingerprint()
        rerun = self.cli('setup', '--repo', self.repo, '--state', self.state)
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertIn('preserved', rerun.stderr)
        self.assertEqual(before, self.fingerprint())

    def test_stop_is_durable_and_resume_is_explicit(self):
        self.init_state()
        self.assertEqual(self.cli('stop', '--state', self.state).returncode, 0)
        self.assertEqual(self.status()['status']['control'], 'stopped')
        paused = self.cli('pause', '--state', self.state)
        self.assertEqual(paused.returncode, 1)
        self.assertEqual(self.status()['status']['control'], 'stopped')
        self.assertEqual(self.cli('resume', '--state', self.state).returncode, 0)
        self.assertEqual(self.status()['status']['control'], 'running')

    # ---- submit queues; the engine admits ---------------------------------------------

    def test_submit_validates_authority_then_queues_without_admitting(self):
        self.init_state()
        plan_path, authority_path, plan_digest = self.prepare()
        good = authority_path.read_text()
        self.write_authority(authority_path, '0' * 64)
        self.assertIn('plan_digest', self.submit(plan_path, authority_path).stderr)
        write_private(authority_path, good)
        os.chmod(authority_path, 0o644)
        self.assertEqual(self.submit(plan_path, authority_path).returncode, 1)
        self.assertFalse((self.state / 'requests').exists())
        os.chmod(authority_path, 0o600)
        queued = self.submit(plan_path, authority_path)
        self.assertEqual(queued.returncode, 0, queued.stderr)
        self.assertIn(f'plan_digest: {plan_digest}', queued.stdout)
        self.assertIn('request: submit-', queued.stdout)
        self.assertIn('not admitted', queued.stderr)
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.request_states(), [('submit', 'pending', None)])
        again = self.submit(plan_path, authority_path)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('already queued', again.stderr)
        self.assertEqual(len(self.status()['requests']), 1)
        consumed = self.consume()
        self.assertEqual([r['status'] for r in consumed['results']], ['admitted'])
        self.assertEqual(self.tasks(), [('task-1', 'pending')])
        self.assertEqual(self.request_states(), [('submit', 'admitted', 'admitted')])
        after = self.submit(plan_path, authority_path)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertIn('already admitted', after.stderr)

    def test_submit_queues_while_another_process_holds_the_lock(self):
        self.init_state()
        plan_path, authority_path, _ = self.prepare()
        holder = subprocess.Popen(self.consumer_command('hold'), stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  env=self.env)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), 'held')
        locked = self.cli('init', '--state', self.state, '--policy', self.policy_path)
        self.assertEqual(locked.returncode, 2)
        self.assertIn('locked', locked.stderr)
        queued = self.submit(plan_path, authority_path)
        self.assertEqual(queued.returncode, 0, queued.stderr)
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.request_states(), [('submit', 'pending', None)])
        out, err = holder.communicate('\n', timeout=120)
        self.assertEqual(holder.returncode, 0, err)
        self.assertEqual(json.loads(out.splitlines()[-1])['submits'], 0)
        first = self.consume()
        self.assertEqual(([r['status'] for r in first['results']], first['submits']),
                         (['admitted'], 1))
        second = self.consume()
        self.assertEqual((second['results'], second['submits']), ([], 1))
        self.assertEqual(self.tasks(), [('task-1', 'pending')])

    def test_crash_after_admission_before_ack_reconciles_idempotently(self):
        self.init_state()
        plan_path, authority_path, plan_digest = self.prepare()
        self.assertEqual(self.submit(plan_path, authority_path).returncode, 0)
        crashed = self.consume('crash')
        self.assertEqual(crashed['submits'], 1)
        self.assertEqual(self.request_states(), [('submit', 'pending', None)])
        self.assertEqual(self.tasks(), [('task-1', 'pending')])
        consumed = self.consume()
        self.assertEqual(([r['status'] for r in consumed['results']], consumed['submits']),
                         (['admitted'], 1))
        ack = self.status()['requests'][0]['ack']
        self.assertEqual((ack['result']['plan_digest'], ack['result']['reconciled']),
                         (plan_digest, True))
        self.assertEqual(self.tasks(), [('task-1', 'pending')])

    def test_stop_keeps_requests_pending_and_is_preserved(self):
        self.init_state()
        plan_path, authority_path, _ = self.prepare()
        self.assertEqual(self.cli('stop', '--state', self.state).returncode, 0)
        queued = self.submit(plan_path, authority_path)
        self.assertEqual(queued.returncode, 0, queued.stderr)
        self.assertIn('stays pending', queued.stderr)
        held = self.consume()
        self.assertEqual([(r['status'], r['code']) for r in held['results']],
                         [('pending', 'control_stopped')])
        self.assertEqual(self.status()['status']['control'], 'stopped')
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.request_states(), [('submit', 'pending', None)])
        self.assertEqual(self.cli('pause', '--state', self.state).returncode, 1)
        self.assertEqual(self.cli('resume', '--state', self.state).returncode, 0)
        self.assertEqual([r['status'] for r in self.consume()['results']], ['admitted'])

    def test_status_with_requests_is_read_only(self):
        self.init_state()
        plan_path, authority_path, _ = self.prepare()
        self.assertEqual(self.submit(plan_path, authority_path).returncode, 0)
        before = self.snapshot()
        self.assertEqual(self.cli('status', '--state', self.state, '--json').returncode, 0)
        text = self.cli('status', '--state', self.state)
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn('requests: pending=1', text.stdout)
        self.assertEqual(before, self.snapshot())

    # ---- context reconciliation and readmission --------------------------------------

    def test_stale_context_request_is_not_executed_and_reconcile_is_explicit(self):
        self.init_state()
        plan_path, authority_path, _ = self.prepare()
        first = self.submit(plan_path, authority_path)
        self.assertEqual(first.returncode, 0, first.stderr)
        running = self.cli('reconcile', '--state', self.state, '--actor', 'owner')
        self.assertEqual(running.returncode, 1)
        self.assertIn('control_required', running.stderr)
        self.assertEqual(self.status()['status']['epoch'], 1)
        self.assertEqual(self.cli('stop', '--state', self.state).returncode, 0)
        unchanged = self.cli('reconcile', '--state', self.state, '--actor', 'owner')
        self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
        self.assertIn('unchanged', unchanged.stdout)
        changed_path = self.owner / 'policy-2.json'
        write_private(changed_path, self.policy(max_attempts=4))
        before = changed_path.read_bytes()
        changed = self.cli('reconcile', '--state', self.state, '--policy', changed_path,
                           '--actor', 'owner')
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertIn('epoch: 2 (appended)', changed.stdout)
        self.assertEqual(changed_path.read_bytes(), before)
        data = self.status()
        self.assertEqual((data['status']['epoch'], data['status']['control']), (2, 'stopped'))
        self.assertEqual(data['policy']['limits']['max_attempts'], 4)
        self.assertEqual(self.cli('resume', '--state', self.state).returncode, 0)
        stale = self.consume()
        self.assertEqual([(r['status'], r['code']) for r in stale['results']],
                         [('incomplete', 'context_stale')])
        self.assertEqual((stale['submits'], self.tasks()), (0, []))
        again = self.submit(plan_path, authority_path)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertNotEqual(first.stdout.splitlines()[0], again.stdout.splitlines()[0])
        self.assertEqual([r['status'] for r in self.consume()['results']], ['admitted'])
        self.assertEqual(self.tasks(), [('task-1', 'pending')])

    def test_readmit_needs_new_declaration_and_keeps_history(self):
        self.init_state()
        plan_path, authority_path, plan_digest = self.prepare()
        self.assertEqual(self.submit(plan_path, authority_path).returncode, 0)
        self.assertEqual([r['status'] for r in self.consume()['results']], ['admitted'])
        self.assertEqual(self.cli('stop', '--state', self.state).returncode, 0)
        changed_path = self.owner / 'policy-2.json'
        write_private(changed_path, self.policy(max_attempts=4))
        reconciled = self.cli('reconcile', '--state', self.state, '--policy', changed_path,
                              '--actor', 'owner')
        self.assertEqual(reconciled.returncode, 0, reconciled.stderr)
        self.assertIn('stale_plans: plan-1', reconciled.stdout)
        self.assertEqual([p['stale'] for p in self.status()['plans']], [True])
        text = self.cli('status', '--state', self.state).stdout
        self.assertIn('readmit needed): plan-1', text)
        self.assertIn('pending(stale plan)=1', text)
        resubmit = self.submit(plan_path, authority_path)
        self.assertEqual(resubmit.returncode, 1)
        self.assertIn('plan_stale', resubmit.stderr)
        old = self.cli('readmit', '--state', self.state, '--plan-id', 'plan-1',
                       '--authority', authority_path, '--actor', 'owner')
        self.assertEqual(old.returncode, 1)
        self.assertIn('authority_stale', old.stderr)
        fresh_path = self.owner / 'plan-1-authority-2.json'
        self.write_authority(fresh_path, plan_digest, utc_now())
        readmitted = self.cli('readmit', '--state', self.state, '--plan-id', 'plan-1',
                              '--authority', fresh_path, '--actor', 'owner')
        self.assertEqual(readmitted.returncode, 0, readmitted.stderr)
        data = self.status()
        self.assertEqual([p['stale'] for p in data['plans']], [False])
        self.assertEqual(data['status']['control'], 'stopped')
        self.assertEqual([(t['id'], t['state'], t['failures']) for t in data['status']['tasks']],
                         [('task-1', 'pending', 0)])
        repeat = self.cli('readmit', '--state', self.state, '--plan-id', 'plan-1',
                          '--authority', fresh_path, '--actor', 'owner')
        self.assertEqual(repeat.returncode, 1)
        self.assertIn('plan_current', repeat.stderr)

    # ---- profile refresh ---------------------------------------------------------------

    def test_refresh_profile_queues_explicit_unknown_refresh(self):
        self.init_state()
        unknown = self.cli('refresh-profile', '--state', self.state, '--profile', 'other',
                           '--actor', 'owner')
        self.assertEqual(unknown.returncode, 1)
        secret = self.cli('refresh-profile', '--state', self.state, '--profile', 'claude-1',
                          '--actor', 'token=abcdef1234567890')
        self.assertEqual(secret.returncode, 1)
        self.assertNotIn('abcdef1234567890', secret.stdout + secret.stderr)
        queued = self.cli('refresh-profile', '--state', self.state, '--profile', 'claude-1',
                          '--actor', 'owner')
        self.assertEqual(queued.returncode, 0, queued.stderr)
        self.assertIn('does not log in', queued.stderr)
        self.assertIn('stays unknown', queued.stderr)
        self.assertEqual(self.request_states(), [('refresh_profile', 'pending', None)])
        consumed = self.consume()
        self.assertEqual([r['status'] for r in consumed['results']], ['observed'])
        observations = self.status()['status']['observations']
        self.assertEqual([(o['profile_id'], o['data']['source'], o['data']['availability'])
                          for o in observations], [('claude-1', 'operator_refresh', 'unknown')])

    # ---- engine entrypoints ------------------------------------------------------------

    def test_run_without_engine_is_incomplete(self):
        self.init_state()
        result = self.cli('run', '--state', self.state, '--once')
        self.assertEqual(result.returncode, 2)
        self.assertIn('INCOMPLETE', result.stderr)
        self.assertIn('controller_engine', result.stderr)
        self.assertEqual(self.cli('run', '--state', self.state, '--background').returncode, 1)
        self.assertEqual(self.cli('run', '--state', self.state, '--poll-seconds', '0').returncode, 1)
        recover = self.cli('recover', '--state', self.state)
        self.assertEqual(recover.returncode, 2)
        self.assertIn('controller_engine', recover.stderr)

    def test_recover_works_under_drift_and_run_needs_current_context(self):
        self.init_state()
        record = self.owner / 'engine-calls.jsonl'
        engine = self.runtime / ENGINE_FILE
        prefix = f'RECORD = {str(record)!r}\n'
        engine.write_text(prefix + ENGINE_BODY)
        missing = self.cli('recover', '--state', self.state)
        self.assertEqual(missing.returncode, 2)
        self.assertIn('recover_owned', missing.stderr)
        engine.write_text(prefix + ENGINE_BODY + RECOVER_BODY)
        self.assertEqual(self.cli('stop', '--state', self.state).returncode, 0)
        recovered = self.cli('recover', '--state', self.state)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(self.status()['status']['control'], 'stopped')
        self.assertEqual(self.status()['identity_check']['runtime'], 'differs')
        self.assertEqual(self.cli('resume', '--state', self.state).returncode, 0)
        drifted = self.cli('run', '--state', self.state, '--once')
        self.assertEqual(drifted.returncode, 1)
        self.assertIn('identity_changed', drifted.stderr)
        self.assertEqual(self.cli('stop', '--state', self.state).returncode, 0)
        reconciled = self.cli('reconcile', '--state', self.state, '--actor', 'owner')
        self.assertEqual(reconciled.returncode, 0, reconciled.stderr)
        self.assertIn('appended', reconciled.stdout)
        self.assertEqual(self.cli('resume', '--state', self.state).returncode, 0)
        ran = self.cli('run', '--state', self.state, '--once')
        self.assertEqual(ran.returncode, 0, ran.stderr)
        calls = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual(calls, [
            {'call': 'recover_owned', 'state': str(self.state)},
            {'call': 'run_controller', 'state': str(self.state), 'once': True,
             'background': False, 'poll_seconds': 5.0}])

    # ---- explicit workspace cleanup (CLI wiring; real cleanup is engine-tested) ---------

    def test_cleanup_workspaces_help_is_explicit_and_recover_deletes_nothing(self):
        helped = self.cli('cleanup-workspaces', '--help')
        self.assertEqual(helped.returncode, 0, helped.stderr)
        text = ' '.join(helped.stdout.lower().split())
        for phrase in ('deletes', 'clean', 'one plan', 'branches', 'kept', 'dirty', 'held',
                       'stop', 'never resumes'):
            self.assertIn(phrase, text)
        recover = ' '.join(self.cli('recover', '--help').stdout.lower().split())
        self.assertIn('deletes no workspace', recover)
        self.assertIn('cleanup-workspaces', ' '.join(self.cli('--help').stdout.split()))

    def test_cleanup_workspaces_refuses_before_the_engine_and_changes_nothing(self):
        self.admit_plan()
        running = self.cleanup()
        self.assertEqual(running.returncode, 1, running.stderr)
        self.assertIn('control_required', running.stderr)
        self.assertEqual(self.cli('stop', '--state', self.state).returncode, 0)
        before = self.fingerprint()
        for actor in ('', '   ', 'token=abcdef1234567890'):
            refused = self.cleanup(actor=actor)
            self.assertEqual(refused.returncode, 1, refused.stderr)
            self.assertIn('actor', refused.stderr)
            self.assertNotIn('abcdef1234567890', refused.stdout + refused.stderr)
        bad_id = self.cleanup(plan_id='../plan-1')
        self.assertEqual(bad_id.returncode, 1, bad_id.stderr)
        self.assertIn('plan_id', bad_id.stderr)
        unknown = self.cleanup(plan_id='plan-9')
        self.assertEqual(unknown.returncode, 1, unknown.stderr)
        self.assertIn('unknown_plan', unknown.stderr)
        missing = self.cleanup()
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertIn('controller_engine', missing.stderr)
        self.assertIn('nothing ran', missing.stderr)
        self.assertEqual(before, self.fingerprint())
        self.assertEqual(self.status()['status']['control'], 'stopped')

    def test_cleanup_workspaces_calls_engine_under_drift_without_resuming(self):
        """A fake engine only records the call: this proves CLI wiring, not cleanup."""
        self.admit_plan()
        self.assertEqual(self.cli('stop', '--state', self.state).returncode, 0)
        record = self.owner / 'engine-calls.jsonl'
        engine = self.runtime / ENGINE_FILE
        prefix = f'RECORD = {str(record)!r}\n'
        engine.write_text(prefix + ENGINE_BODY)
        absent = self.cleanup()
        self.assertEqual(absent.returncode, 2, absent.stderr)
        self.assertIn('cleanup_workspaces', absent.stderr)
        engine.write_text(prefix + 'CLEANUP_RESULT = None\n' + ENGINE_BODY + CLEANUP_BODY)
        odd = self.cleanup()
        self.assertEqual(odd.returncode, 2, odd.stderr)
        self.assertIn('no recognized outcome', odd.stderr)
        engine.write_text(prefix + 'CLEANUP_RESULT = 0\n' + ENGINE_BODY + CLEANUP_BODY)
        done = self.cleanup()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('branches', done.stderr)
        data = self.status()
        self.assertEqual((data['status']['control'], data['status']['epoch']), ('stopped', 1))
        self.assertEqual(data['identity_check']['runtime'], 'differs')
        calls = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual(calls, [{'call': 'cleanup_workspaces', 'state': str(self.state),
                                  'plan_id': 'plan-1', 'actor': 'owner'}] * 2)


if __name__ == '__main__':
    unittest.main()
