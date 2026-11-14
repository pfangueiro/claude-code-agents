"""Offline behavioral checks of the delivery controller's native-provider adapter.

Every lifecycle test drives the shared controller_process bootstrap (through the
provider wrappers) and a local fake provider executable (a Python script following a
JSON plan) in disposable directories. No network, provider, account, credential or
model is contacted. Assertions target observable behavior: argv and environment
actually received, files and processes that do or do not appear, signals that are or
are not delivered, and the classified outcome.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / '.claude/skills/delivery/scripts/controller_providers.py'


def load_module():
    spec = importlib.util.spec_from_file_location('delivery_controller_providers', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


providers = load_module()
cp = providers.controller_process

FAKE_PROVIDER = r'''
import json, os, subprocess, sys, time
plan = json.load(open(os.environ['FAKE_PROVIDER_PLAN']))
if '--version' in sys.argv[1:]:
    print(plan.get('version_text', 'fake 0.0.0'))
    sys.exit(0)
if '--help' in sys.argv[1:]:
    print(plan.get('help_text', ''))
    sys.exit(0)
prompt = sys.stdin.buffer.read()
if plan.get('marker'):
    with open(plan['marker'], 'w') as handle:
        handle.write(str(os.getpid()))
if plan.get('record'):
    with open(plan['record'], 'w') as handle:
        json.dump({'argv': sys.argv, 'cwd': os.getcwd(), 'prompt': prompt.decode(),
                   'env': {key: os.environ.get(key) for key in plan.get('env_keys', [])}}, handle)
if plan.get('linger'):
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
if plan.get('escape'):
    child = os.fork()
    if child == 0:
        os.setsid()
        with open(plan['escape'], 'w') as handle:
            handle.write(str(os.getpid()))
        time.sleep(30)
        os._exit(0)
for line in plan.get('events', []):
    sys.stdout.write(line if isinstance(line, str) else json.dumps(line))
    sys.stdout.write('\n')
    sys.stdout.flush()
time.sleep(plan.get('sleep', 0))
sys.exit(plan.get('exit', 0))
'''

# Simulates the engine dying after spawn: either before the shared spawn record is durable
# ('crash-before-persist') or after spawn returned but before ledger/release.
CRASHING_CONTROLLER = r'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location('crashing_controller', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
process = module.controller_process
if sys.argv[3] == 'crash-before-persist':
    create_json = process._create_json
    def crash(dir_fd, name, record):
        if name == process.SPAWN:
            os._exit(0)
        return create_json(dir_fd, name, record)
    process._create_json = crash
pending = module.spawn(sys.argv[2], environment=dict(os.environ))
print(json.dumps(pending.identity), flush=True)
os._exit(0)
'''

VERDICT = {'version': 1, 'verdict': 'PASS', 'base_sha': 'a' * 40, 'result_sha': 'b' * 40,
           'findings': [], 'gaps': ['no browser check']}
FORBIDDEN_FLAG_PARTS = ('model', 'effort', 'permission', 'approval', 'sandbox', 'bypass',
                        'dangerous', 'yolo', 'full-auto', 'resume', 'continue', 'ephemeral',
                        'trust', 'skip', 'allowed', 'fallback')
PROMPT = 'Do the task.\nReport evidence.'


def claude_events(session='s-1', result=None, **terminal):
    final = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': result or 'done',
             'session_id': session, 'total_cost_usd': 0.01, 'permission_denials': [],
             'unknown_future_field': {'ignored': True}}
    final.update(terminal)
    return [
        {'type': 'system', 'subtype': 'init', 'session_id': session, 'model': 'model-under-test',
         'tools': [], 'unknown_future_field': 1},
        {'type': 'assistant', 'session_id': session,
         'message': {'content': [{'type': 'text', 'text': 'working'}]}},
        final,
    ]


def codex_events(text='finished'):
    return [
        {'type': 'thread.started', 'thread_id': 't-1'},
        {'type': 'turn.started'},
        {'type': 'item.completed', 'item': {'id': 'i0', 'type': 'agent_message', 'text': text}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 1, 'output_tokens': 1}},
    ]


def command_item(status, exit_code=None, item_type='command_execution'):
    return {'type': 'item.completed', 'item': {'id': f'c-{status}', 'type': item_type, 'command': 'make test',
                                               'aggregated_output': '', 'exit_code': exit_code,
                                               'status': status}}


CLAUDE_RATE_LIMIT_INFO = {
    'status': 'allowed', 'resetsAt': 1900000000, 'rateLimitType': 'five_hour',
    'overageStatus': 'rejected', 'overageDisabledReason': 'org_level_disabled', 'isUsingOverage': False,
    'unifiedWindows': {'five_hour': {'utilization': 0.15, 'resetsAt': 1900000000, 'status': 'allowed'},
                       'seven_day': {'utilization': 0.27, 'resetsAt': 1900600000, 'status': 'allowed'}}}


def rate_limit_event(**info):
    """Captured native shape (values anonymised); overrides replace top-level info keys."""
    return {'type': 'rate_limit_event', 'rate_limit_info': {**CLAUDE_RATE_LIMIT_INFO, **info}}


def task_event(subtype, session='s-1', **fields):
    return {'type': 'system', 'subtype': subtype, 'uuid': f'u-{subtype}', 'session_id': session, **fields}


def before_terminal(events, *inserted):
    return events[:-1] + list(inserted) + events[-1:]


def task_run_event(subtype, run_id='r1', **fields):
    """A documented task event on task t1 with an explicit run."""
    return task_event(subtype, task_id='t1', run_id=run_id, **fields)


def task_progress(run_id='r1', **fields):
    defaults = {'description': 'work', 'usage': {'total_tokens': 1, 'tool_uses': 0, 'duration_ms': 5}}
    return task_run_event('task_progress', run_id, **{**defaults, **fields})


def task_start(run_id):
    return task_run_event('task_started', run_id, description='work')


def task_done(run_id):
    return task_run_event('task_notification', run_id, status='completed', output_file='o.txt', summary='s')


UNSEEN_STATUSLESS_UPDATE = task_run_event('task_updated', patch={'description': 'x'})


def verdict_text(*verdicts):
    blocks = ''.join(f'```sdlc-verdict\n{json.dumps(v)}\n```\n' for v in verdicts)
    return 'Review complete.\n' + blocks


def jsonl(events) -> bytes:
    return ''.join((e if isinstance(e, str) else json.dumps(e)) + '\n' for e in events).encode()


def wait_until(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def journal(attempt):
    """Complete journal lines of the shared process attempt (a torn tail is skipped here)."""
    try:
        text = (providers.process_attempt(attempt) / cp.JOURNAL).read_text()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.split('\n')[:-1] if line]


def journal_kinds(attempt):
    return [event['event'] for event in journal(attempt)]


def write_private(path: Path, data: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


class Workspace:
    """A disposable root holding a work tree, an attempts root, a profile and a fake CLI."""

    def __init__(self, test: unittest.TestCase):
        self.root = Path(tempfile.mkdtemp(prefix='controller-providers-')).resolve()
        self.keep_evidence = False
        self.handles = []
        test.addCleanup(self._remove)
        # Registered after _remove, so (LIFO) it runs first: no live attempt dir is deleted.
        test.addCleanup(self._stop_owned)
        self.work = self.root / 'work'
        self.attempts = self.root / 'attempts'
        self.profile = self.root / 'profile'
        for directory in (self.work, self.attempts, self.profile):
            directory.mkdir()
        self.exe = self.root / 'bin' / 'fake-cli'
        self.exe.parent.mkdir()
        self.exe.write_text(f'#!{sys.executable}\n{FAKE_PROVIDER}')
        self.exe.chmod(0o755)
        self.plan_path = self.root / 'plan.json'
        self.counter = 0

    def plan(self, **plan) -> dict:
        self.plan_path.write_text(json.dumps(plan))
        return {**os.environ, 'FAKE_PROVIDER_PLAN': str(self.plan_path)}

    def invocation(self, provider='claude', config=True, attempt_id=None, cwd=None) -> 'providers.Invocation':
        self.counter += 1
        return providers.Invocation(provider=provider, executable=str(self.exe), cwd=str(cwd or self.work),
                                    prompt=PROMPT, attempt_id=attempt_id or f'attempt-{self.counter}',
                                    config_dir=str(self.profile) if config else None)

    def attempt(self, provider='claude', config=True, **limits) -> Path:
        options = {'timeout_seconds': 20.0, 'term_grace_seconds': 2.0, 'linger_seconds': 0.5}
        options.update(limits)
        return providers.create_attempt(self.attempts, self.invocation(provider, config), **options)

    def spawn(self, attempt, env):
        """providers.spawn, with the Pending tracked for cleanup before the workspace is removed."""
        pending = providers.spawn(attempt, environment=env)
        self.handles.append((attempt, pending))
        return pending

    def _stop_owned(self):
        """Stop and reap every test-spawned attempt before its directory is removed.

        STOP goes through the shared request_stop: only the positively owned bootstrap acts on
        it and stops its own group. Nothing is signalled here and nothing is matched by name.
        An attempt still live after the bounded wait keeps the workspace as evidence and fails.
        """
        for attempt, _ in self.handles:
            if live(providers.recover(attempt)):
                providers.request_stop(attempt)
        unresolved = []
        for attempt, pending in self.handles:
            deadline = time.monotonic() + 15.0
            recovery = providers.recover(attempt)
            while live(recovery) and time.monotonic() < deadline:
                time.sleep(0.05)
                recovery = providers.recover(attempt)
            pending.abort()  # closes an unreleased channel and reaps the bootstrap (bounded wait)
            if live(recovery):
                unresolved.append((attempt.name, recovery.state, recovery.identity_status, recovery.reason))
        if unresolved:
            self.keep_evidence = True
            raise AssertionError(f'test-owned attempts unresolved; evidence kept at {self.root}: {unresolved}')

    def _remove(self):
        if not self.keep_evidence:
            shutil.rmtree(self.root, True)


def live(recovery) -> bool:
    """Test-side view: the attempt may still change (active, or unknown without proof the
    bootstrap is gone)."""
    return recovery.state in cp.ACTIVE_STATES or (
        recovery.state == 'unknown' and recovery.identity_status != 'not-owned')


def run_to_settled(owned, expected='exited', timeout=25.0):
    """Wait (bounded) until the attempt is finalizable, then require the exact expected state.

    A transient live 'unknown' (released before the bootstrap's first journal line) is waited
    through, never accepted as settled. Independent of providers.settle().
    """
    deadline = time.monotonic() + timeout
    while True:
        recovery = owned.poll()
        if recovery.state in cp.FINALIZABLE_STATES or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    if recovery.state != expected:
        raise AssertionError(f'attempt settled as {recovery}, expected {expected!r}')
    return recovery


class StubHandle:
    """Scripted Recovery sequence for providers.settle(); the last state repeats."""

    def __init__(self, states, stop_status='owned', after_stop=None):
        self.states, self.stop_status, self.after_stop = list(states), stop_status, after_stop
        self.polls = self.stops = 0

    def poll(self):
        self.polls += 1
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def request_stop(self):
        self.stops += 1
        if self.after_stop is not None:
            self.states = list(self.after_stop)
        return self.stop_status

    def finalize(self):
        raise AssertionError('settle() must never finalize')


LIVE_UNKNOWN = cp.Recovery('unknown', False, 'owned', 'journal-missing')
RUNNING = cp.Recovery('running', False, 'owned')
EXITED = cp.Recovery('exited', False, 'not-owned')


class SettleContractTests(unittest.TestCase):
    """Deterministic controls for settle(); the real startup race runs in LifecycleTests."""

    def test_live_owned_unknown_is_polled_through_to_terminal(self):
        handle = StubHandle([LIVE_UNKNOWN, LIVE_UNKNOWN, RUNNING, EXITED])
        result = providers.settle(handle, 5.0, 1.0)
        self.assertEqual((result.settled, result.state, result.stop_status), (True, 'exited', None))
        self.assertEqual((handle.polls, handle.stops), (4, 0))

    def test_gone_unknown_or_corrupt_is_unresolved_without_stop(self):
        cases = {'release-unresolved': cp.Recovery('unknown', False, 'not-owned', 'release-unresolved'),
                 'journal-torn': cp.Recovery('unknown', False, 'not-owned', 'journal-torn'),
                 'exit-record-invalid': cp.Recovery('corrupt', False, 'not-owned', 'exit-record-invalid')}
        for reason, recovery in cases.items():
            with self.subTest(reason):
                handle = StubHandle([recovery])
                result = providers.settle(handle, 5.0, 1.0)
                self.assertFalse(result.settled)
                self.assertEqual((result.state, result.reason, result.stop_status),
                                 (recovery.state, reason, None))
                self.assertEqual((handle.polls, handle.stops), (1, 0))

    def test_deadline_requests_stop_and_drains_to_terminal(self):
        handle = StubHandle([RUNNING], after_stop=[cp.Recovery('exiting', False, 'owned'), EXITED])
        result = providers.settle(handle, 0.2, 5.0)
        self.assertEqual((result.settled, result.state, result.stop_status), (True, 'exited', 'owned'))
        self.assertEqual(handle.stops, 1)

    def test_still_live_after_drain_is_unresolved_and_bounded(self):
        for stop_status, recovery in (('owned', LIVE_UNKNOWN), ('unknown', RUNNING)):
            with self.subTest(stop_status):
                handle = StubHandle([recovery], stop_status=stop_status)
                started = time.monotonic()
                result = providers.settle(handle, 0.2, 0.3)
                self.assertLess(time.monotonic() - started, 3.0)
                self.assertFalse(result.settled)
                self.assertEqual((result.state, result.stop_status, handle.stops),
                                 (recovery.state, stop_status, 1))

    def test_invalid_budget_is_refused(self):
        for budget in (-1, float('nan'), float('inf'), True, '1'):
            with self.subTest(budget=repr(budget)), self.assertRaises(providers.ProviderError) as ctx:
                providers.settle(StubHandle([EXITED]), budget, 1.0)
            self.assertEqual(ctx.exception.code, 'invalid-settle-budget')


# ---------------------------------------------------------------- launch description

class LaunchSpecTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(self)

    def assert_no_policy_flags(self, argv):
        for arg in argv[1:]:
            lowered = arg.lower()
            self.assertFalse(any(part in lowered for part in FORBIDDEN_FLAG_PARTS), arg)
        self.assertNotIn('-m', argv)
        self.assertNotIn('-c', argv)

    def test_claude_argv_selector_and_stdin_are_exact(self):
        spec = providers.build_launch(self.ws.invocation('claude'))
        self.assertEqual(spec.argv, (str(self.ws.exe), '-p', '--output-format', 'stream-json', '--verbose'))
        self.assert_no_policy_flags(spec.argv)
        self.assertEqual(spec.stdin, PROMPT.encode())
        self.assertEqual(spec.cwd, str(self.ws.work))
        self.assertEqual(spec.selector, ('CLAUDE_CONFIG_DIR', str(self.ws.profile)))

    def test_codex_argv_selector_are_exact(self):
        spec = providers.build_launch(self.ws.invocation('codex'))
        self.assertEqual(spec.argv, (str(self.ws.exe), 'exec', '--json', '-C', str(self.ws.work), '-'))
        self.assert_no_policy_flags(spec.argv)
        self.assertEqual(spec.selector, ('CODEX_HOME', str(self.ws.profile)))

    def test_without_profile_no_selector_is_emitted(self):
        self.assertIsNone(providers.build_launch(self.ws.invocation('claude', config=False)).selector)

    def test_provider_errors_are_process_errors(self):
        self.assertTrue(issubclass(providers.ProviderError, providers.ProcessError))
        self.assertIs(providers.ProcessError, cp.ProcessError)

    def test_rejects_unsafe_or_ambiguous_inputs(self):
        link = self.ws.root / 'link'
        link.symlink_to(self.ws.work)
        base = self.ws.invocation('claude')
        cases = {
            'unknown-provider': base.__class__(**{**base.__dict__, 'provider': 'other'}),
            'executable-not-absolute': base.__class__(**{**base.__dict__, 'executable': 'fake-cli'}),
            'cwd-not-canonical': base.__class__(**{**base.__dict__, 'cwd': str(link)}),
            'config-dir-not-canonical': base.__class__(**{**base.__dict__, 'config_dir': 'profile'}),
            'invalid-attempt-id': base.__class__(**{**base.__dict__, 'attempt_id': '../x'}),
            'invalid-prompt': base.__class__(**{**base.__dict__, 'prompt': ''}),
        }
        for code, invocation in cases.items():
            with self.subTest(code=code), self.assertRaises(providers.ProviderError) as ctx:
                providers.build_launch(invocation)
            self.assertEqual(ctx.exception.code, code)


class AttemptAssociationTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(self)

    def test_association_tmpdir_and_intent_are_bound(self):
        attempt = self.ws.attempt('codex')
        association_path = attempt / providers.ASSOCIATION_FILE
        association = json.loads(association_path.read_text())
        tmp = attempt / providers.TMP_DIR
        self.assertEqual(association, {
            'schema': providers.SCHEMA_ASSOCIATION, 'attemptId': attempt.name, 'provider': 'codex',
            'executable': str(self.ws.exe), 'cwd': str(self.ws.work), 'configDir': str(self.ws.profile),
            'prompt': {'bytes': len(PROMPT.encode()), 'sha256': hashlib.sha256(PROMPT.encode()).hexdigest()},
            'tmpDir': str(tmp), 'createdAt': association['createdAt']})
        self.assertEqual(association_path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(tmp.is_dir())
        self.assertEqual(tmp.stat().st_mode & 0o077, 0)
        self.assertNotEqual(os.path.commonpath([str(tmp), str(self.ws.work)]), str(self.ws.work))
        process_path = providers.process_attempt(attempt)
        intent = json.loads((process_path / cp.INTENT).read_text())
        self.assertEqual(intent['argv'], [str(self.ws.exe), 'exec', '--json', '-C', str(self.ws.work), '-'])
        selectors = intent['environment']['selectors']
        self.assertEqual({key: binding['path'] for key, binding in selectors.items()},
                         {'CODEX_HOME': str(self.ws.profile), 'TMPDIR': str(tmp)})
        self.assertEqual(set(intent['bindings']), {'config', 'tmp'})
        self.assertEqual(selectors['CODEX_HOME'], intent['bindings']['config'])
        self.assertEqual(selectors['TMPDIR'], intent['bindings']['tmp'])
        tmp_info = tmp.stat()
        self.assertEqual((selectors['TMPDIR']['device'], selectors['TMPDIR']['inode']),
                         (tmp_info.st_dev, tmp_info.st_ino))
        self.assertEqual((process_path / cp.STDIN).read_bytes(), PROMPT.encode())
        self.assertEqual(providers.recover(attempt).state, 'prepared')

    def test_attempt_ids_are_fresh_and_attempts_never_reused(self):
        invocation = self.ws.invocation('claude', attempt_id='review-1')
        first = providers.create_attempt(self.ws.attempts, invocation, timeout_seconds=5)
        before = (first / providers.ASSOCIATION_FILE).read_bytes()
        with self.assertRaises(providers.ProviderError) as ctx:
            providers.create_attempt(self.ws.attempts, invocation, timeout_seconds=5)
        self.assertEqual(ctx.exception.code, 'attempt-exists')
        self.assertEqual((first / providers.ASSOCIATION_FILE).read_bytes(), before)

    def test_attempts_root_inside_worktree_or_repository_is_refused(self):
        inner = self.ws.work / 'attempts'
        inner.mkdir()
        with self.assertRaises(providers.ProviderError) as ctx:
            providers.create_attempt(inner, self.ws.invocation(), timeout_seconds=5)
        self.assertEqual(ctx.exception.code, 'attempts-root-overlaps-cwd')
        (self.ws.work / '.git').mkdir()
        sub = self.ws.work / 'sub'
        sub.mkdir()
        with self.assertRaises(providers.ProviderError) as ctx:
            providers.create_attempt(inner, self.ws.invocation(cwd=sub), timeout_seconds=5)
        self.assertEqual(ctx.exception.code, 'attempts-root-inside-repository')
        self.assertEqual(list(inner.iterdir()), [])

    def test_tampered_or_corrupt_association_blocks_spawn(self):
        marker = self.ws.root / 'provider-ran'
        env = self.ws.plan(events=claude_events(), marker=str(marker))
        other = self.ws.root / 'other-profile'
        other.mkdir()
        other_prompt = {'bytes': 5, 'sha256': hashlib.sha256(b'other').hexdigest()}
        mismatch = 'intent-association-mismatch'
        cases = {'config-removed': (mismatch, lambda data: json.dumps({**data, 'configDir': None})),
                 'config-reselected': (mismatch, lambda data: json.dumps({**data, 'configDir': str(other)})),
                 'prompt-replaced': (mismatch, lambda data: json.dumps({**data, 'prompt': other_prompt})),
                 'corrupt': ('association-invalid', lambda _data: '{')}
        for name, (code, mutate) in cases.items():
            with self.subTest(name):
                attempt = self.ws.attempt('claude')
                path = attempt / providers.ASSOCIATION_FILE
                path.write_text(mutate(json.loads(path.read_text())))
                with self.assertRaises(providers.ProviderError) as ctx:
                    providers.spawn(attempt, environment=env)
                self.assertEqual(ctx.exception.code, code)
                self.assertFalse((providers.process_attempt(attempt) / cp.SPAWN_LOCK).exists())
        self.assertFalse(marker.exists())

    def test_intent_selector_bindings_must_match_exactly(self):
        """Selectors are helper directory bindings: a missing, extra, re-pointed, bare-path or
        malformed selector or binding is refused, both directly and at spawn."""
        attempt = self.ws.attempt('codex')
        association = json.loads((attempt / providers.ASSOCIATION_FILE).read_text())
        intent_path = providers.process_attempt(attempt) / cp.INTENT
        intent = json.loads(intent_path.read_text())
        self.assertTrue(providers._intent_matches(association, intent))
        other = self.ws.root / 'other'
        other.mkdir()
        tmp = intent['environment']['selectors']['TMPDIR']
        cases = {
            'missing-selector': lambda s, b: s.pop('CODEX_HOME'),
            'extra-selector': lambda s, b: s.update(TEMP=dict(tmp)),
            'selector-other-path': lambda s, b: s['CODEX_HOME'].update(path=str(other)),
            'selector-bare-path': lambda s, b: s.update(TMPDIR=tmp['path']),
            'selector-extra-field': lambda s, b: s['TMPDIR'].update(mode=0),
            'selector-bool-inode': lambda s, b: s['TMPDIR'].update(inode=True),
            'selector-text-device': lambda s, b: s['TMPDIR'].update(device=str(tmp['device'])),
            'selector-other-identity': lambda s, b: s['TMPDIR'].update(inode=tmp['inode'] + 1),
            'binding-other-path': lambda s, b: b['config'].update(path=str(other)),
            'binding-missing': lambda s, b: b.pop('tmp'),
            'binding-malformed': lambda s, b: b['tmp'].pop('device'),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                changed = json.loads(json.dumps(intent))
                mutate(changed['environment']['selectors'], changed['bindings'])
                self.assertFalse(providers._intent_matches(association, changed))
        changed = json.loads(json.dumps(intent))
        changed['environment']['selectors']['CODEX_HOME']['path'] = str(other)
        write_private(intent_path, json.dumps(changed).encode())
        with self.assertRaises(providers.ProviderError) as ctx:
            providers.spawn(attempt, environment=self.ws.plan(events=codex_events()))
        self.assertEqual(ctx.exception.code, 'intent-association-mismatch')
        self.assertFalse((providers.process_attempt(attempt) / cp.SPAWN_LOCK).exists())

    def test_missing_or_unsupported_lifecycle_is_incomplete(self):
        prepared = self.ws.attempt('claude')
        outcome = providers.assess(prepared)
        self.assertEqual((outcome.category, outcome.reasons, outcome.lifecycle_state),
                         ('incomplete', ('lifecycle-prepared',), 'prepared'))
        self.assertFalse(outcome.execution_admitted)

        old_pass = {'schema': 'sdlc-controller/provider-attempt-lifecycle/v1', 'recoveryState': 'exited',
                    'outcome': {'execution_admitted': True, 'category': 'success'}}
        legacy = self.ws.attempts / 'legacy-1'
        legacy.mkdir(mode=0o700)
        write_private(legacy / 'intent.json', json.dumps(
            {'schema': 'sdlc-controller/provider-attempt-intent/v1', 'provider': 'claude'}).encode())
        write_private(legacy / 'lifecycle.json', json.dumps(old_pass).encode())
        outcome = providers.assess(legacy)
        self.assertEqual(outcome.category, 'incomplete')
        self.assertIn('association-missing', outcome.reasons)
        self.assertFalse(outcome.execution_admitted)

        replaced = self.ws.attempt('claude')
        write_private(providers.process_attempt(replaced) / cp.RECORD, json.dumps(old_pass).encode())
        outcome = providers.assess(replaced)
        self.assertEqual((outcome.category, outcome.reasons), ('incomplete', ('lifecycle-corrupt',)))
        self.assertFalse(outcome.execution_admitted)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(self)

    def test_reports_version_and_flags_without_claiming_auth(self):
        env = self.ws.plan(version_text='2.1.323 (Claude Code)',
                           help_text='-p, --print  --output-format <format>  --verbose')
        probe = providers.probe_cli('claude', str(self.ws.exe), self.ws.attempts, 'probe-1',
                                    config_dir=str(self.ws.profile), environment=env)
        self.assertEqual(probe.version, '2.1.323')
        self.assertTrue(probe.at_least_checked)
        self.assertEqual(probe.help_flags, {'--print': True, '--output-format': True, '--verbose': True})
        self.assertEqual(probe.problems, ())
        self.assertEqual((probe.authentication, probe.capacity), ('not-checked', 'not-checked'))
        for name in ('version', 'help'):
            with self.subTest(name):
                attempt = Path(probe.probe_dir) / providers.PROCESS_DIR / name
                status = cp.read_status(attempt)
                self.assertEqual(status['state'], 'finalized')
                self.assertTrue(status['record']['executionSuccess'])
                intent = json.loads((attempt / cp.INTENT).read_text())
                self.assertEqual(intent['stdin']['bytes'], 0)
                self.assertNotIn('-p', intent['argv'])

    def test_older_version_and_missing_flag_are_reported(self):
        env = self.ws.plan(version_text='codex-cli 0.150.2', help_text='--json  print events')
        probe = providers.probe_cli('codex', str(self.ws.exe), self.ws.attempts, 'probe-2', environment=env)
        self.assertFalse(probe.at_least_checked)
        self.assertEqual(probe.help_flags, {'--json': True, '--cd': False})
        self.assertIn('required-flag-missing', probe.problems)
        with self.assertRaises(providers.ProviderError) as ctx:
            providers.probe_cli('codex', str(self.ws.exe), self.ws.attempts, 'probe-2', environment=env)
        self.assertEqual(ctx.exception.code, 'probe-exists')

    def test_repeated_fast_probes_settle_and_report_version_and_flags(self):
        env = self.ws.plan(version_text='codex-cli 0.169.0', help_text='--json  --cd <DIR>')
        for index in range(4):
            with self.subTest(run=index):
                probe = providers.probe_cli('codex', str(self.ws.exe), self.ws.attempts,
                                            f'probe-fast-{index}', environment=env)
                self.assertEqual((probe.version, probe.at_least_checked, probe.problems), ('0.169.0', True, ()))
                self.assertEqual(probe.help_flags, {'--json': True, '--cd': True})
                for name in ('version', 'help'):
                    status = cp.read_status(Path(probe.probe_dir) / providers.PROCESS_DIR / name)
                    self.assertEqual(status['state'], 'finalized')
                    self.assertTrue(status['record']['executionSuccess'])


# ---------------------------------------------------------------- stream classification

class ClaudeStreamTests(unittest.TestCase):
    def parse(self, events):
        return providers.parse_stream('claude', jsonl(events))

    def test_valid_control_with_unknown_fields(self):
        parsed = self.parse(claude_events())
        self.assertEqual(parsed.category, 'success')
        self.assertEqual(parsed.reasons, ())
        self.assertEqual((parsed.session_id, parsed.observed_model), ('s-1', 'model-under-test'))
        self.assertEqual(parsed.observed_cost_usd, 0.01)

    def test_terminal_denials_block_success_despite_success_subtype(self):
        parsed = self.parse(claude_events(permission_denials=[{'tool_name': 'Bash'}]))
        self.assertEqual(parsed.category, 'permission_denied')

    def test_headless_denial_event_blocks_success(self):
        events = claude_events()
        events.insert(2, {'type': 'system', 'subtype': 'permission_denied', 'tool_name': 'Edit'})
        self.assertEqual(self.parse(events).category, 'permission_denied')

    def test_structural_defects_are_incomplete(self):
        base = claude_events()
        cases = {
            'missing-terminal': base[:2],
            'duplicate-terminal': base + [base[2]],
            'malformed-event': base[:1] + ['{"type": "assistant"'] + base[1:],
            'missing-init': base[1:],
            'session-mismatch': base[:2] + [{**base[2], 'session_id': 'other'}],
            'malformed-terminal': base[:2] + [{k: v for k, v in base[2].items() if k != 'permission_denials'}],
            'event-after-terminal': base + [{'type': 'assistant', 'message': {}}],
        }
        for code, events in cases.items():
            with self.subTest(code=code):
                parsed = self.parse(events)
                self.assertEqual(parsed.category, 'incomplete')
                self.assertIn(code, parsed.reasons)

    def test_unrecognised_shapes_only_are_never_success(self):
        parsed = self.parse([{'type': 'novel', 'status': 'ok'}])
        self.assertEqual(parsed.category, 'incomplete')

    def test_recovered_retry_is_distinguished_from_terminal_reason(self):
        events = claude_events()
        events.insert(1, {'type': 'system', 'subtype': 'api_retry', 'attempt': 1, 'error': 'rate_limit'})
        parsed = self.parse(events)
        self.assertEqual(parsed.category, 'success')
        self.assertEqual(parsed.recovered_retries, ('rate_limit',))
        self.assertIsNone(parsed.terminal_reason)

    def test_terminal_error_maps_native_retry_category(self):
        for code, category in (('authentication_failed', 'auth_required'), ('rate_limit', 'rate_limited'),
                               ('overloaded', 'unavailable'), ('novel_code', 'failed')):
            with self.subTest(code=code):
                events = claude_events(subtype='error_during_execution', is_error=True)
                events.insert(1, {'type': 'system', 'subtype': 'api_retry', 'error': code})
                parsed = self.parse(events)
                self.assertEqual(parsed.category, category)
                self.assertEqual(parsed.terminal_reason, code)
                self.assertEqual(parsed.recovered_retries, ())

    def test_actual_rate_limit_event_shape_is_retained_typed(self):
        parsed = self.parse(before_terminal(claude_events(), rate_limit_event()))
        self.assertEqual((parsed.category, parsed.reasons), ('success', ()))
        self.assertEqual(parsed.quota_snapshots, ({
            'provider': 'claude', 'eventType': 'rate_limit_event', 'eventIndex': 2, 'line': 3,
            'sessionId': None, 'rate_limit_info': CLAUDE_RATE_LIMIT_INFO, 'invalidFields': []},))
        self.assertEqual((parsed.quota_snapshots_omitted, parsed.quota_latest_status), (0, 'allowed'))

    def test_quota_lookalikes_in_content_are_never_quota(self):
        lookalike = {'rate_limit_info': {**CLAUDE_RATE_LIMIT_INFO, 'status': 'rejected'},
                     'rate_limits': {'primary': {'usedPercent': 99.0, 'resetsAt': 1900000000}}}
        events = before_terminal(
            claude_events(subtype='error_during_execution', is_error=True),
            {'type': 'assistant', 'session_id': 's-1',
             'message': {'content': [{'type': 'tool_use', 'input': lookalike}]}},
            {'type': 'user', 'session_id': 's-1',
             'message': {'content': [{'type': 'tool_result', 'content': json.dumps(lookalike)}]}},
            {'type': 'system', 'subtype': 'status', **lookalike})
        parsed = self.parse(events)
        self.assertEqual(parsed.quota_snapshots, ())
        self.assertIsNone(parsed.quota_latest_status)
        self.assertEqual(parsed.category, 'failed')

    def test_unsuccessful_terminal_with_native_rejection_is_rate_limited(self):
        events = before_terminal(claude_events(subtype='error_during_execution', is_error=True),
                                 rate_limit_event(status='rejected'))
        parsed = self.parse(events)
        self.assertEqual(parsed.category, 'rate_limited')
        self.assertIn('quota-rejected', parsed.reasons)
        self.assertIsNone(parsed.terminal_reason)

    def test_allowed_main_window_is_not_rate_limited(self):
        failed = claude_events(subtype='error_during_execution', is_error=True)
        cases = {'rejected-overage': (rate_limit_event(),),
                 'recovered-before-failure': (rate_limit_event(status='rejected'), rate_limit_event())}
        for name, inserted in cases.items():
            with self.subTest(name):
                parsed = self.parse(before_terminal(failed, *inserted))
                self.assertEqual(parsed.category, 'failed')
                self.assertNotIn('quota-rejected', parsed.reasons)
                info = parsed.quota_snapshots[-1]['rate_limit_info']
                self.assertEqual((info['status'], info['overageStatus'], info['isUsingOverage']),
                                 ('allowed', 'rejected', False))

    def test_success_after_recovered_rejection_keeps_observations(self):
        events = before_terminal(claude_events(), rate_limit_event(status='rejected'), rate_limit_event())
        parsed = self.parse(events)
        self.assertEqual((parsed.category, parsed.reasons), ('success', ()))
        self.assertEqual([s['rate_limit_info']['status'] for s in parsed.quota_snapshots],
                         ['rejected', 'allowed'])
        self.assertEqual(parsed.quota_latest_status, 'allowed')

    def test_latest_64_snapshots_are_kept_and_latest_rejection_is_visible(self):
        statuses = ['allowed'] * 69 + ['rejected']
        inserted = [rate_limit_event(status=status) for status in statuses]
        parsed = self.parse(before_terminal(claude_events(), *inserted))
        self.assertEqual((parsed.category, parsed.reasons), ('success', ()))
        self.assertEqual(len(parsed.quota_snapshots), 64)
        self.assertEqual(parsed.quota_snapshots_omitted, 6)
        self.assertEqual((parsed.quota_snapshots[0]['eventIndex'], parsed.quota_snapshots[0]['line']), (8, 9))
        self.assertEqual(parsed.quota_snapshots[-1]['eventIndex'], 2 + 69)
        self.assertEqual(parsed.quota_snapshots[-1]['rate_limit_info']['status'], 'rejected')
        self.assertEqual(parsed.quota_latest_status, 'rejected')
        failed = self.parse(before_terminal(claude_events(subtype='error_during_execution', is_error=True),
                                            *inserted))
        self.assertEqual(failed.category, 'rate_limited')

    def test_invalid_latest_status_is_unknown_not_an_earlier_value(self):
        events = before_terminal(claude_events(subtype='error_during_execution', is_error=True),
                                 rate_limit_event(status='rejected'), rate_limit_event(status=7))
        parsed = self.parse(events)
        self.assertIsNone(parsed.quota_latest_status)
        self.assertIn('status', parsed.quota_snapshots[-1]['invalidFields'])
        self.assertEqual(parsed.category, 'failed')
        self.assertNotIn('quota-rejected', parsed.reasons)

    def test_malformed_quota_numbers_are_unknown_not_zero(self):
        windows = {'five_hour': {'utilization': True, 'resetsAt': 10 ** 400, 'status': 'allowed'},
                   'seven_day': {'utilization': 0, 'resetsAt': -1}}
        events = before_terminal(claude_events(), rate_limit_event(
            resetsAt='soon', isUsingOverage='no', unifiedWindows=windows))
        snapshot = self.parse(events).quota_snapshots[0]
        info = snapshot['rate_limit_info']
        self.assertEqual((info['resetsAt'], info['isUsingOverage'], info['status']), (None, None, 'allowed'))
        self.assertEqual(info['unifiedWindows'], {
            'five_hour': {'utilization': None, 'resetsAt': None, 'status': 'allowed'},
            'seven_day': {'utilization': 0, 'resetsAt': None, 'status': None}})
        self.assertEqual(sorted(snapshot['invalidFields']), sorted([
            'resetsAt', 'isUsingOverage', 'unifiedWindows.five_hour.utilization',
            'unifiedWindows.five_hour.resetsAt', 'unifiedWindows.seven_day.resetsAt']))
        not_object = self.parse(before_terminal(claude_events(),
                                                {'type': 'rate_limit_event', 'rate_limit_info': 'x'}))
        self.assertEqual(not_object.quota_snapshots[0]['rate_limit_info'], None)
        self.assertEqual(not_object.quota_snapshots[0]['invalidFields'], ['rate_limit_info'])
        self.assertIsNone(not_object.quota_latest_status)

    def test_is_number_rejects_huge_and_non_finite_without_raising(self):
        for value in (10 ** 400, -(10 ** 400), 2 ** 53 + 1, float('inf'), float('nan'), True, None, '1'):
            with self.subTest(value=repr(value)[:24]):
                self.assertFalse(providers._is_number(value))
        for value in (0, 1, 0.15, -2.5, 2 ** 53):
            with self.subTest(value=value):
                self.assertTrue(providers._is_number(value))

    def test_invalid_cost_is_unknown_and_blocks_success(self):
        base = claude_events()
        overflow = json.dumps(base[2]).replace('"total_cost_usd": 0.01', '"total_cost_usd": 1e400')
        cases = {repr(value)[:24]: claude_events(total_cost_usd=value)
                 for value in (10 ** 400, True, -0.5, '0.01', 2 ** 60)}
        cases['float-overflow'] = base[:2] + [overflow]
        for name, events in cases.items():
            with self.subTest(name):
                parsed = self.parse(events)
                self.assertIsNone(parsed.observed_cost_usd)
                self.assertIn('invalid-cost', parsed.reasons)
                self.assertEqual(parsed.category, 'incomplete')
        zero = self.parse(claude_events(total_cost_usd=0))
        self.assertEqual((zero.category, zero.observed_cost_usd), ('success', 0.0))

    def test_empty_session_id_is_incomplete(self):
        for session in ('', '   '):
            with self.subTest(session=session):
                parsed = self.parse(claude_events(session=session))
                self.assertEqual(parsed.category, 'incomplete')
                self.assertIn('missing-session', parsed.reasons)
                self.assertIsNone(parsed.session_id)


class CodexStreamTests(unittest.TestCase):
    def parse(self, events):
        return providers.parse_stream('codex', jsonl(events))

    def test_valid_control(self):
        parsed = self.parse(codex_events('all good'))
        self.assertEqual((parsed.category, parsed.session_id, parsed.final_text), ('success', 't-1', 'all good'))
        self.assertIsNone(parsed.observed_model)
        self.assertIsNone(parsed.observed_cost_usd)
        self.assertEqual(parsed.recovered_retries, ())

    def test_turn_failed_is_failed(self):
        events = codex_events()[:-1] + [{'type': 'turn.failed', 'error': {'message': 'x'}}]
        self.assertEqual(self.parse(events).category, 'failed')

    def test_recovered_error_then_completed_is_success_with_evidence(self):
        events = codex_events()
        events.insert(2, {'type': 'error', 'message': 'stream disconnected before completion; retrying'})
        parsed = self.parse(events)
        self.assertEqual((parsed.category, parsed.reasons), ('success', ()))
        self.assertEqual(parsed.recovered_retries, ('error-event',))
        self.assertIsNone(parsed.terminal_reason)

    def test_unrecovered_error_then_turn_failed_infers_nothing_from_text(self):
        events = codex_events()[:-1] + [{'type': 'error', 'message': 'usage limit reached; log in again'},
                                        {'type': 'turn.failed', 'error': {'message': 'quota exceeded'}}]
        parsed = self.parse(events)
        self.assertEqual(parsed.category, 'failed')
        self.assertIn('error-event', parsed.reasons)
        self.assertIsNone(parsed.terminal_reason)
        self.assertEqual(parsed.recovered_retries, ())

    def test_error_without_or_after_terminal_is_incomplete(self):
        error = {'type': 'error', 'message': 'x'}
        cases = {'missing-terminal': codex_events()[:-1] + [error],
                 'event-after-terminal': codex_events() + [error]}
        for code, events in cases.items():
            with self.subTest(code=code):
                parsed = self.parse(events)
                self.assertEqual(parsed.category, 'incomplete')
                self.assertIn(code, parsed.reasons)
                self.assertIn('error-event', parsed.reasons)

    def test_declined_command_is_typed_incomplete_not_denial(self):
        parsed = self.parse(before_terminal(codex_events(), command_item('declined')))
        self.assertEqual(parsed.category, 'incomplete')
        self.assertIn('command-declined', parsed.reasons)
        self.assertNotIn('permission-denied', parsed.reasons)
        failed = self.parse(codex_events()[:-1] + [command_item('declined'),
                                                   {'type': 'turn.failed', 'error': {'message': 'x'}}])
        self.assertEqual(failed.category, 'failed')
        self.assertIn('command-declined', failed.reasons)

    def test_ordinary_failures_followed_by_completion_can_succeed(self):
        inserted = (command_item('failed', exit_code=1), command_item('completed', exit_code=0),
                    command_item('failed', item_type='file_change'),
                    command_item('failed', item_type='mcp_tool_call'))
        parsed = self.parse(before_terminal(codex_events(), *inserted))
        self.assertEqual((parsed.category, parsed.reasons), ('success', ()))

    def test_unknown_future_events_are_not_denial(self):
        inserted = ({'type': 'turn.novel', 'status': 'declined'},
                    {'type': 'item.completed', 'item': {'type': 'novel_item', 'status': 'declined'}},
                    {'type': 'item.started', 'item': {'type': 'command_execution', 'status': 'declined'}})
        parsed = self.parse(before_terminal(codex_events(), *inserted))
        self.assertEqual((parsed.category, parsed.reasons), ('success', ()))

    def test_missing_or_duplicate_terminal_is_incomplete(self):
        events = codex_events()
        for case in (events[:-1], events + [events[-1]], events[1:]):
            with self.subTest(case=len(case)):
                self.assertEqual(self.parse(case).category, 'incomplete')

    def test_empty_thread_id_is_incomplete(self):
        events = codex_events()
        events[0] = {'type': 'thread.started', 'thread_id': ''}
        parsed = self.parse(events)
        self.assertEqual(parsed.category, 'incomplete')
        self.assertIn('missing-session', parsed.reasons)
        self.assertIsNone(parsed.session_id)

    def test_unverified_quota_shapes_are_not_invented(self):
        events = codex_events()
        events.insert(3, {'type': 'event_msg', 'rate_limits': {
            'primary': {'usedPercent': 12.5, 'windowDurationMins': 300, 'resetsAt': 1900000000}}})
        events.insert(3, {'type': 'rate_limit_event', 'rate_limit_info': CLAUDE_RATE_LIMIT_INFO})
        parsed = self.parse(events)
        self.assertEqual((parsed.quota_snapshots, parsed.quota_snapshots_omitted, parsed.quota_latest_status),
                         ((), 0, None))
        self.assertEqual(parsed.category, 'success')


class ClaudeBackgroundTaskTests(unittest.TestCase):
    def parse(self, *inserted):
        return providers.parse_stream('claude', jsonl(before_terminal(claude_events(), *inserted)))

    def started(self, task_id='t1', **fields):
        return task_event('task_started', task_id=task_id, description='background work', **fields)

    def closed(self, run_id=None, status='completed'):
        run = {} if run_id is None else {'run_id': run_id}
        return task_event('task_notification', task_id='t1', status=status,
                          output_file='task-output.txt', summary='done', **run)

    def test_started_task_without_closure_never_admits(self):
        parsed = self.parse(self.started())
        self.assertEqual(parsed.category, 'incomplete')
        self.assertIn('background-task-unresolved', parsed.reasons)

    def test_closed_tasks_and_empty_snapshot_are_safe_controls(self):
        cases = {
            'no-task': (),
            'notification': (self.started(), self.closed()),
            'update-killed': (self.started(),
                              task_event('task_updated', task_id='t1', patch={'status': 'killed'})),
            'empty-snapshot': (self.started(), task_event('background_tasks_changed', tasks=[])),
            'stopped-same-run': (self.started(run_id='r1'), self.closed('r1', 'stopped')),
        }
        for name, inserted in cases.items():
            with self.subTest(name):
                parsed = self.parse(*inserted)
                self.assertEqual((parsed.category, parsed.reasons), ('success', ()))

    def test_non_terminal_or_live_snapshot_is_incomplete(self):
        live_entry = {'task_id': 't2', 'task_type': 'local_agent', 'description': 'd'}
        cases = {
            'paused': (self.started(), task_event('task_updated', task_id='t1', patch={'status': 'paused'})),
            'running-update-only': (task_event('task_updated', task_id='t1', patch={'status': 'running'}),),
            'nonempty-snapshot': (task_event('background_tasks_changed', tasks=[live_entry]),),
            'snapshot-replaces-closed': (self.started(), self.closed(),
                                         task_event('background_tasks_changed', tasks=[live_entry])),
        }
        for name, inserted in cases.items():
            with self.subTest(name):
                parsed = self.parse(*inserted)
                self.assertEqual(parsed.category, 'incomplete')
                self.assertIn('background-task-unresolved', parsed.reasons)

    def test_stale_run_terminal_does_not_clear_new_run(self):
        runs = (self.started(run_id='r1'), self.started(run_id='r2'), self.closed('r1'))
        stale = self.parse(*runs)
        self.assertEqual(stale.category, 'incomplete')
        self.assertIn('background-task-unresolved', stale.reasons)
        self.assertNotIn('task-run-conflict', stale.reasons)
        resolved = self.parse(*runs, self.closed('r2'))
        self.assertEqual((resolved.category, resolved.reasons), ('success', ()))
        conflict = self.parse(self.started(run_id='r1'), self.closed('r9'))
        self.assertEqual(conflict.category, 'incomplete')
        self.assertIn('task-run-conflict', conflict.reasons)

    def assert_unresolved(self, *inserted, conflict=False):
        parsed = self.parse(*inserted)
        self.assertEqual(parsed.category, 'incomplete')
        self.assertIn('task-run-conflict' if conflict else 'background-task-unresolved', parsed.reasons)

    def assert_admitted(self, *inserted):
        parsed = self.parse(*inserted)
        self.assertEqual((parsed.category, parsed.reasons), ('success', ()))

    def test_unseen_statusless_update_keeps_run_live_until_closed(self):
        self.assert_unresolved(UNSEEN_STATUSLESS_UPDATE)
        self.assert_unresolved(task_event('task_updated', task_id='t1', patch={}))
        self.assert_admitted(UNSEEN_STATUSLESS_UPDATE, task_done('r1'))
        self.assert_admitted(UNSEEN_STATUSLESS_UPDATE, task_event('background_tasks_changed', tasks=[]))

    def test_progress_keeps_run_live_and_malformed_progress_is_incomplete(self):
        self.assert_unresolved(task_progress())
        self.assert_unresolved(task_run_event('task_progress'))
        self.assert_unresolved(task_start('r1'), task_done('r1'), task_progress('r2'))
        self.assert_admitted(task_progress(), task_done('r1'))
        self.assert_admitted(task_start('r1'), task_done('r1'), task_progress('r1'))
        self.assert_admitted(task_progress(), task_event('background_tasks_changed', tasks=[]))
        malformed = {
            'usage-not-object': task_progress(usage=[1]),
            'description-not-text': task_run_event('task_progress', description=1),
            'last-tool-not-text': task_progress(last_tool_name=None),
            'missing-task-id': task_event('task_progress', run_id='r1'),
            'empty-run-id': task_progress(run_id=''),
        }
        for name, event in malformed.items():
            with self.subTest(name):
                parsed = self.parse(event)
                self.assertEqual(parsed.category, 'incomplete')
                self.assertIn('task-event-malformed', parsed.reasons)

    def test_replayed_start_or_terminal_cannot_erase_newer_run(self):
        replayed = (task_start('r1'), task_start('r2'), task_start('r1'), task_done('r1'))
        self.assert_unresolved(*replayed)
        self.assert_unresolved(*replayed, task_done('r1'))
        self.assert_admitted(*replayed, task_done('r2'))
        self.assert_admitted(*replayed, task_event('background_tasks_changed', tasks=[]))
        self.assert_admitted(*replayed, task_run_event('task_updated', 'r2', patch={'status': 'stopped'}))
        self.assert_unresolved(*replayed, task_event('background_tasks_changed', tasks=[{'task_id': 't1'}]))
        self.assert_unresolved(task_start('r1'), task_start('r2'), self.closed(), conflict=True)
        self.assert_unresolved(task_start('r1'), task_done('r1'), task_start('r2'), self.closed(), conflict=True)
        self.assert_unresolved(task_start('r1'), task_done('r1'), task_start('r1'), conflict=True)

    def test_snapshot_listing_live_run_does_not_fabricate_closed_history(self):
        def snapshot(*run_ids):
            entries = [{'task_id': 't1', 'task_type': 'local_agent', 'description': 'd',
                        **({} if run_id is None else {'run_id': run_id})} for run_id in run_ids]
            return task_event('background_tasks_changed', tasks=entries)

        # Regression: the sole live run listed by the snapshot may be closed by an unnamed terminal.
        self.assert_admitted(task_start('r1'), snapshot('r1'), self.closed())
        self.assert_admitted(self.started(), snapshot(None), self.closed())
        # Controls: named terminal, still-listed run, empty snapshot.
        self.assert_admitted(task_start('r1'), snapshot('r1'), task_done('r1'))
        self.assert_unresolved(task_start('r1'), snapshot('r1'))
        self.assert_admitted(task_start('r1'), snapshot('r1'), snapshot())
        # Missing run: an omitted run is genuinely closed, so an unnamed terminal stays ambiguous.
        self.assert_unresolved(task_start('r1'), snapshot('r2'), self.closed(), conflict=True)
        self.assert_admitted(task_start('r1'), snapshot('r2'), task_done('r2'))
        # New run alongside the old one: two open runs keep an unnamed terminal ambiguous.
        self.assert_unresolved(task_start('r1'), snapshot('r1', 'r2'), self.closed(), conflict=True)
        self.assert_unresolved(task_start('r1'), snapshot('r1', 'r2'), task_done('r1'))
        # Replay: real closed history survives a snapshot, and stale events cannot clear a newer run.
        self.assert_unresolved(task_start('r1'), task_done('r1'), snapshot('r1'), self.closed(), conflict=True)
        self.assert_unresolved(task_start('r1'), task_start('r2'), snapshot('r2'), task_done('r1'))
        self.assert_unresolved(task_start('r1'), task_start('r2'), snapshot('r2'), task_start('r1'),
                               conflict=True)
        self.assert_admitted(task_start('r1'), task_start('r2'), snapshot('r2'), task_progress('r1'),
                             task_done('r2'))

    def test_foreign_or_malformed_task_evidence_is_incomplete(self):
        no_uuid = {k: v for k, v in self.started().items() if k != 'uuid'}
        cases = {
            'foreign-session': ('task-foreign-session', self.started(session='other')),
            'missing-description': ('task-event-malformed', task_event('task_started', task_id='t1')),
            'missing-uuid': ('task-event-malformed', no_uuid),
            'empty-task-id': ('task-event-malformed', self.started(task_id='')),
            'empty-run-id': ('task-event-malformed', self.started(run_id='')),
            'snapshot-not-list': ('task-event-malformed',
                                  task_event('background_tasks_changed', tasks={'t1': {}})),
            'notification-missing-output': ('task-event-malformed',
                                            task_event('task_notification', task_id='t1',
                                                       status='completed', summary='s')),
            'patch-not-object': ('task-event-malformed',
                                 task_event('task_updated', task_id='t1', patch='completed')),
        }
        for name, (reason, event) in cases.items():
            with self.subTest(name):
                parsed = self.parse(event)
                self.assertEqual(parsed.category, 'incomplete')
                self.assertIn(reason, parsed.reasons)


class VerdictExtractionTests(unittest.TestCase):
    def test_structured_output_is_preferred(self):
        verdict, problem = providers.extract_review_verdict(VERDICT, verdict_text({**VERDICT, 'verdict': 'FAIL'}))
        self.assertEqual((verdict, problem), (VERDICT, None))

    def test_single_fenced_block_is_extracted(self):
        verdict, problem = providers.extract_review_verdict(None, verdict_text(VERDICT))
        self.assertEqual((verdict, problem), (VERDICT, None))

    def test_rejections(self):
        cases = {
            'verdict-absent': 'Done. Everything passes.',
            'verdict-multiple': verdict_text(VERDICT, VERDICT),
            'verdict-malformed': 'x\n```sdlc-verdict\n{"version": 1,\n```\n',
            'verdict-sha': verdict_text({**VERDICT, 'base_sha': 'main'}),
            'verdict-value': verdict_text({**VERDICT, 'verdict': 'done'}),
            'verdict-fields': verdict_text({**VERDICT, 'extra': 1}),
            'verdict-version': verdict_text({**VERDICT, 'version': True}),
            'verdict-unterminated': 'x\n```sdlc-verdict\n{}\n',
        }
        for code, text in cases.items():
            with self.subTest(code=code):
                self.assertEqual(providers.extract_review_verdict(None, text), (None, code))


# ---------------------------------------------------------------- owned lifecycle (shared runner)

@unittest.skipUnless(os.name == 'posix', 'POSIX process groups required')
class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(self)
        self.marker = self.ws.root / 'provider-ran'
        self.record = self.ws.root / 'provider-record.json'

    def launch(self, attempt, env):
        return self.ws.spawn(attempt, env).release()

    def exit_record(self, attempt):
        return json.loads((providers.process_attempt(attempt) / cp.EXIT).read_text())

    def test_claude_control_waits_for_release_then_is_admitted(self):
        env = self.ws.plan(events=claude_events(), marker=str(self.marker), record=str(self.record),
                           env_keys=['CLAUDE_CONFIG_DIR', 'GIT_DIR', 'UNRELATED', 'TMPDIR', 'HOME'])
        env.update(GIT_DIR=str(self.ws.root / 'elsewhere.git'), UNRELATED='kept',
                   HOME=str(self.ws.root / 'inherited-home'))
        attempt = self.ws.attempt('claude')
        process_path = providers.process_attempt(attempt)
        pending = self.ws.spawn(attempt, env)
        self.assertTrue(wait_until(lambda: 'bootstrap-started' in journal_kinds(attempt)))
        time.sleep(0.5)
        self.assertFalse(self.marker.exists())
        self.assertFalse((process_path / cp.STDOUT).exists())
        self.assertEqual(journal_kinds(attempt), ['bootstrap-started'])
        self.assertEqual(providers.recover(attempt).state, 'awaiting-release')
        self.assertEqual(cp.identify(pending.identity), 'owned')

        owned = pending.release()
        self.assertEqual(run_to_settled(owned).state, 'exited')
        outcome = providers.finalize(attempt, owned)
        self.assertTrue(outcome.execution_admitted, outcome.reasons)
        self.assertEqual((outcome.category, outcome.session_id, outcome.observed_model, outcome.lifecycle_state),
                         ('success', 's-1', 'model-under-test', 'finalized'))
        received = json.loads(self.record.read_text())
        self.assertEqual(received['argv'], [str(self.ws.exe), '-p', '--output-format', 'stream-json', '--verbose'])
        self.assertEqual(received['cwd'], str(self.ws.work))
        self.assertEqual(received['prompt'], PROMPT)
        self.assertEqual(received['env'], {'CLAUDE_CONFIG_DIR': str(self.ws.profile), 'GIT_DIR': None,
                                           'UNRELATED': 'kept', 'TMPDIR': str(attempt / providers.TMP_DIR),
                                           'HOME': str(self.ws.root / 'inherited-home')})
        lifecycle = cp.read_status(process_path)['record']
        self.assertTrue(lifecycle['groupEmpty'])
        self.assertFalse(lifecycle['forced'])
        self.assertTrue(lifecycle['executionSuccess'])
        self.assertEqual(set(outcome.raw_logs), {'stdout', 'stderr'})
        self.assertEqual(providers.assess(attempt).to_record(), outcome.to_record())

    def test_codex_control_yields_verdict_candidate(self):
        env = self.ws.plan(events=codex_events(verdict_text(VERDICT)), record=str(self.record),
                           env_keys=['CODEX_HOME', 'TMPDIR'])
        attempt = self.ws.attempt('codex')
        owned = self.launch(attempt, env)
        self.assertEqual(run_to_settled(owned).state, 'exited')
        outcome = providers.finalize(attempt, owned)
        self.assertTrue(outcome.execution_admitted, outcome.reasons)
        self.assertEqual((outcome.session_id, outcome.verdict_candidate), ('t-1', VERDICT))
        received = json.loads(self.record.read_text())
        self.assertEqual(received['argv'], [str(self.ws.exe), 'exec', '--json', '-C', str(self.ws.work), '-'])
        self.assertEqual(received['env'], {'CODEX_HOME': str(self.ws.profile),
                                           'TMPDIR': str(attempt / providers.TMP_DIR)})

    def test_without_profile_inherited_selector_reaches_cli(self):
        env = self.ws.plan(events=claude_events(), record=str(self.record), env_keys=['CLAUDE_CONFIG_DIR'])
        env['CLAUDE_CONFIG_DIR'] = str(self.ws.root / 'inherited-profile')
        attempt = self.ws.attempt('claude', config=False)
        owned = self.launch(attempt, env)
        run_to_settled(owned)
        providers.finalize(attempt, owned)
        self.assertEqual(json.loads(self.record.read_text())['env'],
                         {'CLAUDE_CONFIG_DIR': str(self.ws.root / 'inherited-profile')})

    def finalize_clean(self, inserted):
        """Run a Claude stream with `inserted` task events to a clean, finalized lifecycle."""
        env = self.ws.plan(events=before_terminal(claude_events(), *inserted), exit=0)
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        run_to_settled(owned)
        outcome = providers.finalize(attempt, owned)
        lifecycle = cp.read_status(providers.process_attempt(attempt))['record']
        self.assertTrue(lifecycle['executionSuccess'])
        self.assertEqual(providers.assess(attempt).to_record(), outcome.to_record())
        return outcome

    def test_clean_lifecycle_never_admits_unresolved_native_task_runs(self):
        histories = {
            'unseen-statusless-update': (UNSEEN_STATUSLESS_UPDATE,),
            'unseen-progress': (task_progress(),),
            'replayed-start-erasing-newer-run': (task_start('r1'), task_start('r2'), task_start('r1'),
                                                 task_done('r1')),
        }
        for name, inserted in histories.items():
            with self.subTest(name):
                outcome = self.finalize_clean(inserted)
                self.assertFalse(outcome.execution_admitted)
                self.assertEqual((outcome.stream_category, outcome.category), ('incomplete', 'incomplete'))
                self.assertIn('background-task-unresolved', outcome.reasons)
        control = self.finalize_clean((task_start('r1'), task_start('r2'), task_start('r1'), task_done('r1'),
                                       task_done('r2')))
        self.assertTrue(control.execution_admitted, control.reasons)

    def test_zero_exit_with_denial_is_not_admitted(self):
        env = self.ws.plan(events=claude_events(permission_denials=[{'tool_name': 'Bash'}]), exit=0)
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        run_to_settled(owned)
        outcome = providers.finalize(attempt, owned)
        self.assertFalse(outcome.execution_admitted)
        self.assertEqual(outcome.category, 'permission_denied')

    def test_zero_exit_without_terminal_is_incomplete(self):
        env = self.ws.plan(events=claude_events()[:2], exit=0)
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        run_to_settled(owned)
        outcome = providers.finalize(attempt, owned)
        self.assertFalse(outcome.execution_admitted)
        self.assertEqual(outcome.category, 'incomplete')
        self.assertIn('missing-terminal', outcome.reasons)

    def test_nonzero_exit_with_success_stream_is_not_admitted(self):
        env = self.ws.plan(events=claude_events(), exit=3)
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        run_to_settled(owned)
        outcome = providers.finalize(attempt, owned)
        self.assertEqual((outcome.stream_category, outcome.category), ('success', 'incomplete'))
        self.assertIn('nonzero-exit', outcome.reasons)
        self.assertFalse(outcome.execution_admitted)

    def test_tampering_after_finalize_is_incomplete(self):
        env = self.ws.plan(events=claude_events())
        cases = ('stdout', 'association')
        for case in cases:
            with self.subTest(case):
                attempt = self.ws.attempt('claude')
                owned = self.launch(attempt, env)
                run_to_settled(owned)
                self.assertTrue(providers.finalize(attempt, owned).execution_admitted)
                if case == 'stdout':
                    with open(providers.process_attempt(attempt) / cp.STDOUT, 'ab') as handle:
                        handle.write(b'{"type": "result"}\n')
                    expected = 'lifecycle-corrupt'
                else:
                    path = attempt / providers.ASSOCIATION_FILE
                    path.write_text(json.dumps({**json.loads(path.read_text()), 'configDir': None}))
                    expected = 'intent-association-mismatch'
                outcome = providers.assess(attempt)
                self.assertEqual((outcome.category, outcome.reasons), ('incomplete', (expected,)))
                self.assertFalse(outcome.execution_admitted)

    def test_timeout_is_forced_and_interrupted(self):
        env = self.ws.plan(events=claude_events()[:1], sleep=30)
        attempt = self.ws.attempt('claude', timeout_seconds=1.0)
        owned = self.launch(attempt, env)
        self.assertEqual(run_to_settled(owned).state, 'exited')
        outcome = providers.finalize(attempt, owned)
        exit_record = self.exit_record(attempt)
        self.assertEqual(exit_record['termination'], 'timeout')
        self.assertEqual(exit_record['signalsSent'][0], 'SIGTERM')
        self.assertTrue(exit_record['forced'])
        self.assertEqual(outcome.category, 'interrupted')
        self.assertIn('termination-timeout', outcome.reasons)
        self.assertFalse(outcome.execution_admitted)

    def test_lingering_child_is_cleaned_and_blocks_admission(self):
        env = self.ws.plan(events=claude_events(), linger=True)
        attempt = self.ws.attempt('claude', linger_seconds=0.5)
        owned = self.launch(attempt, env)
        self.assertEqual(run_to_settled(owned).state, 'exited')
        outcome = providers.finalize(attempt, owned)
        exit_record = self.exit_record(attempt)
        self.assertTrue(exit_record['lingering'])
        self.assertEqual(exit_record['termination'], 'exited')
        self.assertEqual(outcome.stream_category, 'success')
        self.assertEqual(outcome.category, 'incomplete')
        self.assertIn('lingering-descendants', outcome.reasons)
        self.assertFalse(outcome.execution_admitted)

    def test_stop_during_execution_terminates_owned_group(self):
        env = self.ws.plan(events=claude_events()[:1], sleep=30, marker=str(self.marker))
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        self.assertTrue(wait_until(self.marker.exists))
        self.assertEqual(owned.poll().state, 'running')
        started = time.monotonic()
        self.assertEqual(providers.request_stop(attempt), 'owned')
        self.assertEqual(run_to_settled(owned).state, 'exited')
        self.assertLess(time.monotonic() - started, 10.0)
        outcome = providers.finalize(attempt, owned)
        exit_record = self.exit_record(attempt)
        self.assertEqual((exit_record['termination'], exit_record['stopSource']), ('stopped', 'file'))
        self.assertEqual(outcome.category, 'interrupted')
        self.assertIn('termination-stopped', outcome.reasons)
        self.assertFalse(outcome.execution_admitted)

    def test_escaped_descendant_is_reported_incomplete(self):
        escape_file = self.ws.root / 'escaped.pid'
        env = self.ws.plan(events=claude_events(), escape=str(escape_file), sleep=1.0)

        def kill_escaped():
            if escape_file.exists():
                try:
                    os.kill(int(escape_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass  # already exited on its own
        self.addCleanup(kill_escaped)
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        self.assertEqual(run_to_settled(owned).state, 'exited')
        outcome = providers.finalize(attempt, owned)
        escaped = [item['pid'] for item in self.exit_record(attempt)['escaped']]
        self.assertIn(int(escape_file.read_text()), escaped)
        self.assertIn('escaped-descendants', outcome.reasons)
        self.assertFalse(outcome.execution_admitted)

    def run_crashing_controller(self, attempt, mode):
        env = {**os.environ, 'FAKE_PROVIDER_PLAN': str(self.ws.plan_path)}
        return subprocess.run([sys.executable, '-c', CRASHING_CONTROLLER, str(MODULE_PATH), str(attempt), mode],
                              env=env, capture_output=True, text=True, timeout=30, check=False)

    def test_parent_death_before_release_launches_nothing(self):
        self.ws.plan(events=claude_events(), marker=str(self.marker))
        attempt = self.ws.attempt('claude')
        proc = self.run_crashing_controller(attempt, 'die-before-release')
        identity = json.loads(proc.stdout)
        self.assertTrue(wait_until(lambda: cp.identify(identity) == 'not-owned'))
        kinds = journal_kinds(attempt)
        self.assertIn('aborted', kinds)
        self.assertNotIn('launching', kinds)
        aborted = [e for e in journal(attempt) if e['event'] == 'aborted']
        self.assertEqual(aborted[0]['reason'], 'release-channel-closed')
        self.assertFalse(self.marker.exists())
        self.assertFalse((providers.process_attempt(attempt) / cp.STDOUT).exists())
        recovery = providers.recover(attempt)
        self.assertEqual((recovery.state, recovery.relaunch_safe), ('not-launched', True))

    def test_crash_between_spawn_and_identity_persistence_launches_nothing(self):
        self.ws.plan(events=claude_events(), marker=str(self.marker))
        attempt = self.ws.attempt('claude')
        self.run_crashing_controller(attempt, 'crash-before-persist')
        process_path = providers.process_attempt(attempt)
        self.assertFalse((process_path / cp.SPAWN).exists())
        self.assertTrue(wait_until(lambda: 'aborted' in journal_kinds(attempt)))
        time.sleep(0.3)
        self.assertFalse(self.marker.exists())
        recovery = providers.recover(attempt)
        self.assertEqual((recovery.state, recovery.relaunch_safe), ('not-launched', True))
        with self.assertRaises(providers.ProcessError) as ctx:
            providers.spawn(attempt, environment={**os.environ})
        self.assertEqual(ctx.exception.code, 'attempt-already-spawned')

    def test_lost_supervisor_after_release_blocks_relaunch(self):
        env = self.ws.plan(events=claude_events()[:1], sleep=30, marker=str(self.marker))
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        self.assertTrue(wait_until(self.marker.exists))
        self.assertEqual(cp.identify(owned.identity), 'owned')
        os.killpg(owned.identity['pgid'], signal.SIGKILL)  # positively identified group only
        self.assertTrue(wait_until(lambda: owned.poll().state == 'lost'))
        self.assertFalse(providers.recover(attempt).relaunch_safe)
        outcome = providers.finalize(attempt, owned)
        self.assertEqual(outcome.category, 'interrupted')
        self.assertIn('termination-lost', outcome.reasons)
        self.assertFalse(outcome.execution_admitted)

    def test_reattached_controller_sees_running_attempt_and_can_stop_it(self):
        env = self.ws.plan(events=claude_events()[:1], sleep=30, marker=str(self.marker))
        attempt = self.ws.attempt('claude')
        self.launch(attempt, env)
        self.assertTrue(wait_until(self.marker.exists))
        attached = providers.attach(attempt)
        self.assertEqual(attached.poll().state, 'running')
        self.assertEqual(attached.request_stop(), 'owned')
        run_to_settled(attached, timeout=15.0)
        outcome = providers.finalize(attempt)
        self.assertEqual(outcome.category, 'interrupted')

    def test_unrelated_process_is_never_signalled(self):
        sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                   start_new_session=True)
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        self.assertTrue(wait_until(lambda: cp.process_start(sleeper.pid) is not None))
        real = {'attemptId': 'attempt-x', 'intentSha256': '0' * 64, 'pid': sleeper.pid,
                'pgid': sleeper.pid, 'bootId': cp.boot_identity(),
                'processStart': cp.process_start(sleeper.pid), 'token': 'f' * 32}
        cases = {
            'not-owned': [real,
                          {**real, 'processStart': 'lstart:Thu Jan  1 00:00:00 1970'},
                          {**real, 'bootId': 'another-boot'}],
            'unknown': [{**real, 'bootId': None}, {**real, 'token': 'short'}],
        }
        for expected, identities in cases.items():
            for identity in identities:
                with self.subTest(expected=expected, identity=identity):
                    self.assertEqual(cp.identify(identity), expected)
        prepared = self.ws.attempt('claude')
        self.assertEqual(providers.request_stop(prepared), 'not-spawned')
        time.sleep(0.2)
        self.assertIsNone(sleeper.poll())

    def test_final_record_is_written_once(self):
        env = self.ws.plan(events=claude_events())
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        run_to_settled(owned)
        first = providers.finalize(attempt, owned)
        record_path = providers.process_attempt(attempt) / cp.RECORD
        before = record_path.read_bytes()
        with self.assertRaises(providers.ProcessError) as ctx:
            providers.finalize(attempt)
        self.assertEqual(ctx.exception.code, 'already-finalized')
        self.assertEqual(record_path.read_bytes(), before)
        self.assertEqual(providers.assess(attempt), first)

    def test_finalize_refuses_active_attempt_and_foreign_handle(self):
        env = self.ws.plan(events=claude_events()[:1], sleep=30, marker=str(self.marker))
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        self.assertTrue(wait_until(self.marker.exists))
        with self.assertRaises(providers.ProcessError) as ctx:
            providers.finalize(attempt)
        self.assertEqual(ctx.exception.code, 'attempt-running')
        other = self.ws.attempt('claude')
        with self.assertRaises(providers.ProviderError) as ctx:
            providers.finalize(other, owned)
        self.assertEqual(ctx.exception.code, 'handle-mismatch')
        owned.request_stop()
        run_to_settled(owned)

    def test_fast_native_like_runs_settle_through_startup_race(self):
        """Release right after spawn, as the engine and probe do: the bootstrap may not have
        journaled yet, so early polls can be a live owned 'unknown' that must be waited through."""
        env = self.ws.plan(events=claude_events())
        for index in range(8):
            with self.subTest(run=index):
                attempt = self.ws.attempt('claude')
                owned = self.launch(attempt, env)
                result = providers.settle(owned, 25.0, 10.0)
                self.assertEqual((result.settled, result.state, result.stop_status), (True, 'exited', None))
                outcome = providers.finalize(attempt, owned)
                self.assertTrue(outcome.execution_admitted, outcome.reasons)
                self.assertEqual(outcome.category, 'success')

    def test_settle_deadline_stops_owned_group_and_is_interrupted(self):
        env = self.ws.plan(events=claude_events()[:1], sleep=30, marker=str(self.marker))
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        self.assertTrue(wait_until(self.marker.exists))
        started = time.monotonic()
        result = providers.settle(owned, 0.5, 15.0)
        self.assertEqual((result.settled, result.state, result.stop_status), (True, 'exited', 'owned'))
        self.assertLess(time.monotonic() - started, 15.0)
        outcome = providers.finalize(attempt, owned)
        exit_record = self.exit_record(attempt)
        self.assertEqual((exit_record['termination'], exit_record['stopSource']), ('stopped', 'file'))
        self.assertEqual(outcome.category, 'interrupted')
        self.assertIn('termination-stopped', outcome.reasons)
        self.assertFalse(outcome.execution_admitted)

    def test_corrupt_exit_evidence_is_unresolved_and_never_finalized(self):
        env = self.ws.plan(events=claude_events())
        attempt = self.ws.attempt('claude')
        owned = self.launch(attempt, env)
        run_to_settled(owned)
        write_private(providers.process_attempt(attempt) / cp.EXIT, b'{}')
        result = providers.settle(owned, 5.0, 1.0)
        self.assertEqual((result.settled, result.state, result.reason, result.stop_status),
                         (False, 'corrupt', 'exit-record-invalid', None))
        with self.assertRaises(providers.ProcessError) as ctx:
            providers.finalize(attempt, owned)
        self.assertEqual(ctx.exception.code, 'attempt-corrupt')
        outcome = providers.assess(attempt)
        self.assertEqual((outcome.category, outcome.reasons), ('incomplete', ('lifecycle-corrupt',)))
        self.assertFalse(outcome.execution_admitted)


if __name__ == '__main__':
    unittest.main()
