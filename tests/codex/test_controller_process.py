"""Behavioral checks of the shared owned-command lifecycle helper.

Every command is a disposable local Python helper under a private temporary root; no
provider, model, network or native CLI is contacted. Waits are bounded polls on durable
state or ready markers, and tearDown stops and settles every owned attempt it created.
"""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True  # loading the module must not write bytecode into the repository

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / '.claude/skills/delivery/scripts/controller_process.py'


def load_module():
    spec = importlib.util.spec_from_file_location('delivery_controller_process', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


cp = load_module()
PY = os.path.realpath(sys.executable)

ECHO = '''import os, sys
data = sys.stdin.buffer.read()
sys.stdout.buffer.write(b'out:' + data)
sys.stderr.write('tmp=' + os.environ.get('TMPDIR', '') + ' git=' + os.environ.get('GIT_DIR', 'unset'))
'''

MARKER = '''import os, sys, time
with open(sys.argv[1], 'a') as handle:
    print(os.getpid(), file=handle)
if len(sys.argv) > 2:
    deadline = time.monotonic() + 30
    while not os.path.exists(sys.argv[2]) and time.monotonic() < deadline:
        time.sleep(0.05)
'''

SLEEPER = '''import signal, sys, time
if 'ignore-term' in sys.argv:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(sys.argv[1], 'w').close()
time.sleep(120)
'''

BACKGROUND = '''import subprocess, sys
child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(120)'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
with open(sys.argv[1], 'w') as handle:
    handle.write(str(child.pid))
sys.exit(int(sys.argv[2]))
'''

CONTROLLER = '''import importlib.util, json, os, signal, sys
spec = importlib.util.spec_from_file_location('controller_process_child', sys.argv[1])
cp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cp
spec.loader.exec_module(cp)
args = json.loads(sys.argv[2])
command = cp.CommandSpec(tuple(args['argv']), args['cwd'], b'', args['id'])
attempt = cp.prepare(args['root'], command, 30)
pending = cp.spawn(attempt)
fd = os.open(args['identity'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, json.dumps(pending.identity).encode())
os.fsync(fd)
os.close(fd)
if args['mode'] == 'release':
    pending.release()
    os._exit(0)
os.kill(os.getpid(), signal.SIGKILL)
'''


def write_private(path: Path, data: bytes) -> None:
    if os.path.lexists(path):
        os.unlink(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)


def tree_state(path: Path) -> dict:
    state = {}
    for current, dirs, files in os.walk(path):
        for name in dirs + files:
            full = os.path.join(current, name)
            info = os.lstat(full)
            state[full] = (info.st_size, info.st_mtime_ns, info.st_mode)
    return state


FAKE_PID = 4_000_000  # bounded pid for inert records whose bootId never matches this boot


def journal_line(kind: str, **fields) -> bytes:
    return json.dumps({'event': kind, 'at': 'x', **fields}).encode() + b'\n'


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class LifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cp._executable_binding(PY)
        except cp.ProcessError as err:
            raise unittest.SkipTest(f'interpreter is not a safe bound executable: {err.code}')
        if cp.boot_identity() is None:
            raise unittest.SkipTest('host boot identity unavailable')

    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix='cp-test-')))
        self.root = self.base / 'attempts'
        self.root.mkdir(mode=0o700)
        os.chmod(self.root, 0o700)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.helpers = self.base / 'helpers'
        self.helpers.mkdir()
        self.handles, self.pendings, self.sleepers = [], [], []

    def tearDown(self):
        for pending in self.pendings:
            pending.abort()
        for entry in sorted(self.root.iterdir()):
            if entry.is_dir() and not entry.is_symlink():
                self.settle(entry)
        for proc in self.sleepers:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
        shutil.rmtree(self.base, ignore_errors=True)

    def settle(self, attempt: Path) -> None:
        try:
            if cp.recover(attempt).state not in cp.ACTIVE_STATES:
                return
            cp.request_stop(attempt)
        except cp.ProcessError:
            return
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            for handle in self.handles:
                with contextlib.suppress(cp.ProcessError):
                    handle.poll()  # reap bootstraps this process spawned
            if cp.recover(attempt).state not in cp.ACTIVE_STATES:
                return
            time.sleep(0.1)

    # ------------------------------------------------------------ helpers

    def helper(self, name: str, source: str) -> str:
        path = self.helpers / name
        path.write_text(source)
        return str(path)

    def command(self, attempt_id, args, stdin=b'', selectors=None):
        return cp.CommandSpec((PY, '-I', *args), str(self.project), stdin, attempt_id, selectors or {})

    def prepare(self, attempt_id, args, timeout=30.0, stdin=b'', selectors=None, **options):
        return cp.prepare(str(self.root), self.command(attempt_id, args, stdin, selectors),
                          timeout, **options)

    def spawn(self, attempt):
        pending = cp.spawn(attempt)
        self.pendings.append(pending)
        return pending

    def launch(self, attempt_id, args, **options):
        attempt = self.prepare(attempt_id, args, **options)
        owned = self.spawn(attempt).release()
        self.handles.append(owned)
        return attempt, owned

    def wait_state(self, target, states, timeout=20.0):
        deadline = time.monotonic() + timeout
        while True:
            recovery = target.poll() if isinstance(target, cp.OwnedProcess) else cp.recover(target)
            if recovery.state in states:
                return recovery
            if time.monotonic() >= deadline:
                self.fail(f'attempt stayed {recovery.state} ({recovery.reason}); wanted {sorted(states)}')
            time.sleep(0.05)

    def wait_path(self, path: Path, timeout=20.0) -> None:
        deadline = time.monotonic() + timeout
        while not path.exists():
            if time.monotonic() >= deadline:
                self.fail(f'{path.name} never appeared')
            time.sleep(0.05)

    def racing_exit(self, attempt: Path, owned, go: Path):
        """Patch classification so the command ends, and its bootstrap publishes the exit
        record and exits unreaped, only after the caller's first reap and before classifying."""
        real_classify, published = cp._classify, []

        def classify(dir_fd, attempt_path):
            if not published:
                published.append(True)
                go.touch()
                deadline = time.monotonic() + 20
                while not ((attempt / 'exit.json').exists()
                           and cp.identify(owned.identity) == 'not-owned'):
                    if time.monotonic() >= deadline:
                        self.fail('bootstrap never published its exit record and exited')
                    time.sleep(0.05)
            return real_classify(dir_fd, attempt_path)
        return mock.patch.object(cp, '_classify', side_effect=classify)

    def assert_code(self, code, func, *args, **kwargs):
        with self.assertRaises(cp.ProcessError) as ctx:
            func(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)

    def run_controller(self, attempt_id, argv, mode):
        identity_file = self.base / f'{attempt_id}.identity.json'
        args = {'root': str(self.root), 'id': attempt_id, 'argv': [PY, '-I', *argv],
                'cwd': str(self.project), 'identity': str(identity_file), 'mode': mode}
        result = subprocess.run([sys.executable, '-I', '-B', '-c', CONTROLLER, str(MODULE_PATH),
                                 json.dumps(args)], capture_output=True, timeout=60)
        return result, json.loads(identity_file.read_text()), self.root / attempt_id

    def fake_spawned(self, attempt_id, lines, release=True):
        """An inert spawned attempt whose recorded bootstrap is provably not this boot's."""
        attempt = self.prepare(attempt_id, ['-c', 'pass'])
        intent_sha = hashlib.sha256((attempt / 'intent.json').read_bytes()).hexdigest()
        identity = {'attemptId': attempt_id, 'intentSha256': intent_sha, 'pid': FAKE_PID,
                    'pgid': FAKE_PID, 'bootId': 'other-boot', 'processStart': 'lstart:never',
                    'token': secrets.token_hex(16)}
        write_private(attempt / 'spawn.lock', b'')
        write_private(attempt / 'spawn.json', json.dumps(
            {'schema': cp.SCHEMA_SPAWN, 'identity': identity, 'spawnedAt': 'x'}).encode())
        if release:
            write_private(attempt / 'release.json', b'{}')
        write_private(attempt / 'journal.jsonl', b''.join(lines))
        return attempt

    # ------------------------------------------------------------ tests

    def test_clean_completion_records_raw_log_hashes(self):
        script = self.helper('echo.py', ECHO)
        tmp = self.base / 'tmp'
        tmp.mkdir()
        with mock.patch.dict(os.environ, {'GIT_DIR': str(self.base / 'elsewhere')}):
            attempt, owned = self.launch('clean-1', [script], stdin=b'payload',
                                         selectors={'TMPDIR': str(tmp)}, linger_seconds=0.2)
        self.wait_state(owned, {'exited'})
        record = owned.finalize()
        self.assertIs(record['executionSuccess'], True)
        self.assertEqual((record['termination'], record['exitCode'], record['signalsSent']),
                         ('exited', 0, []))
        self.assertEqual((record['groupEmpty'], record['reasons']), (True, []))
        self.assertEqual(record['membersAtExit'], 0)
        self.assertEqual(record['schema'], 'sdlc-controller/process-lifecycle/v3')
        expected_out = b'out:payload'
        self.assertEqual(record['logs']['stdout'],
                         {'path': str(attempt / 'stdout.log'), 'size': len(expected_out),
                          'sha256': hashlib.sha256(expected_out).hexdigest()})
        self.assertEqual((attempt / 'stderr.log').read_text(), f'tmp={tmp} git=unset')
        self.assertEqual(os.stat(attempt / 'stdout.log').st_mode & 0o777, 0o600)
        status = cp.read_status(attempt)
        self.assertEqual((status['state'], status['record']), ('finalized', record))
        self.assertFalse(status['relaunchSafe'])
        self.assert_code('already-finalized', cp.finalize, attempt)

    def test_release_gate_launches_nothing_before_release(self):
        marker = self.base / 'ran.txt'
        attempt = self.prepare('gate-1', [self.helper('marker.py', MARKER), str(marker)])
        pending = self.spawn(attempt)
        self.assertEqual(cp.recover(attempt).state, 'awaiting-release')
        self.assertEqual(cp.identify(pending.identity), 'owned')
        time.sleep(0.3)
        self.assertFalse(marker.exists())
        pending.abort()
        recovery = self.wait_state(attempt, {'not-launched'})
        self.assertEqual((recovery.relaunch_safe, recovery.reason), (True, 'never-released'))
        self.assertFalse(marker.exists())
        self.assert_code('release-channel-closed', pending.release)
        self.assert_code('attempt-already-spawned', cp.spawn, attempt)

    def test_parent_death_before_release_launches_nothing(self):
        marker = self.base / 'ran.txt'
        result, identity, attempt = self.run_controller(
            'orphan-1', [self.helper('marker.py', MARKER), str(marker)], 'die')
        self.assertEqual(result.returncode, -signal.SIGKILL)
        recovery = self.wait_state(attempt, {'not-launched'})
        self.assertTrue(recovery.relaunch_safe)
        self.assertEqual(cp.identify(identity), 'not-owned')
        self.assertFalse(marker.exists())

    def test_spawn_without_identity_record_is_relaunch_safe(self):
        attempt = self.prepare('lockonly-1', ['-c', 'pass'])
        write_private(attempt / 'spawn.lock', b'')
        self.assertEqual(cp.recover(attempt), cp.Recovery('not-launched', True, None, 'spawn-incomplete'))

    def test_restart_attaches_to_live_command_without_duplicate(self):
        marker, go = self.base / 'runs.txt', self.base / 'go'
        result, identity, attempt = self.run_controller(
            'restart-1', [self.helper('marker.py', MARKER), str(marker), str(go)], 'release')
        self.assertEqual(result.returncode, 0, result.stderr)
        owned = cp.OwnedProcess.attach(attempt)
        self.handles.append(owned)
        self.assertEqual(owned.identity, identity)
        self.wait_path(marker)
        self.assertEqual(owned.poll().state, 'running')
        self.assert_code('attempt-already-spawned', cp.spawn, attempt)
        go.touch()
        self.wait_state(owned, {'exited'})
        record = owned.finalize()
        self.assertIs(record['executionSuccess'], True, record['reasons'])
        self.assertEqual(len(marker.read_text().split()), 1)

    def test_stop_is_durable_and_prompt(self):
        ready = self.base / 'ready'
        attempt, owned = self.launch('stop-1', [self.helper('sleeper.py', SLEEPER), str(ready)],
                                     term_grace_seconds=1.0)
        self.wait_path(ready)
        started = time.monotonic()
        self.assertEqual(owned.request_stop(), 'owned')
        self.assertEqual(os.stat(attempt / 'stop.request').st_mode & 0o777, 0o600)
        self.wait_state(owned, {'exited'}, timeout=15)
        self.assertLess(time.monotonic() - started, 6.0)
        record = owned.finalize()
        self.assertEqual((record['termination'], record['stopSource']), ('stopped', 'file'))
        self.assertEqual(record['signalsSent'][0], 'SIGTERM')
        self.assertIs(record['executionSuccess'], False)
        self.assertIn('termination-stopped', record['reasons'])

    def test_timeout_escalates_to_kill_of_own_group(self):
        ready = self.base / 'ready'
        _attempt, owned = self.launch(
            'timeout-1', [self.helper('sleeper.py', SLEEPER), str(ready), 'ignore-term'],
            timeout=1.0, term_grace_seconds=0.5)
        self.wait_path(ready)
        self.wait_state(owned, {'exited'}, timeout=15)
        record = owned.finalize()
        self.assertEqual(record['termination'], 'timeout')
        self.assertEqual(record['signalsSent'], ['SIGTERM', 'SIGKILL'])
        self.assertIs(record['forced'], True)
        self.assertIs(record['executionSuccess'], False)

    def test_redirected_background_child_never_passes(self):
        script = self.helper('background.py', BACKGROUND)
        for exit_code in ('0', '3'):
            with self.subTest(exit_code=exit_code):
                pid_file = self.base / f'child-{exit_code}.pid'
                attempt, owned = self.launch(f'bg-{exit_code}', [script, str(pid_file), exit_code],
                                             linger_seconds=0.5, term_grace_seconds=2.0)
                self.wait_state(owned, {'exited'})
                record = owned.finalize()
                self.assertEqual(record['exitCode'], int(exit_code))
                self.assertIs(record['lingering'], True)
                self.assertIn('SIGTERM', record['signalsSent'])
                self.assertIn('lingering-descendants', record['reasons'])
                self.assertIs(record['executionSuccess'], False)
                self.assertFalse(cp.recover(attempt).relaunch_safe)
                child = int(pid_file.read_text())
                deadline = time.monotonic() + 10
                while alive(child) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(alive(child))

    def test_identity_mismatch_leaves_unrelated_process_untouched(self):
        ready, token = self.base / 'ready', secrets.token_hex(16)
        sleeper = subprocess.Popen([PY, '-I', self.helper('sleeper.py', SLEEPER), str(ready), token],
                                   start_new_session=True)
        self.sleepers.append(sleeper)
        self.wait_path(ready)
        genuine = {'attemptId': 'probe', 'intentSha256': '0' * 64, 'pid': sleeper.pid,
                   'pgid': sleeper.pid, 'bootId': cp.boot_identity(),
                   'processStart': cp.process_start(sleeper.pid), 'token': token}
        self.assertEqual(cp.identify(genuine), 'owned')  # positive control
        for key, value, expected in (('token', secrets.token_hex(16), 'not-owned'),
                                     ('processStart', 'lstart:never', 'not-owned'),
                                     ('bootId', 'other-boot', 'not-owned'),
                                     ('pgid', sleeper.pid + 1, 'unknown')):
            with self.subTest(key=key):
                self.assertEqual(cp.identify({**genuine, key: value}), expected)
        attempt = self.prepare('foreign-1', ['-c', 'pass'])
        intent_sha = hashlib.sha256((attempt / 'intent.json').read_bytes()).hexdigest()
        identity = {**genuine, 'attemptId': 'foreign-1', 'intentSha256': intent_sha,
                    'token': secrets.token_hex(16)}
        write_private(attempt / 'spawn.lock', b'')
        write_private(attempt / 'spawn.json', json.dumps(
            {'schema': cp.SCHEMA_SPAWN, 'identity': identity, 'spawnedAt': 'x'}).encode())
        write_private(attempt / 'release.json', b'{}')
        write_private(attempt / 'journal.jsonl',
                      journal_line('bootstrap-started', pid=sleeper.pid) + journal_line('launching'))
        self.assertEqual(cp.recover(attempt).state, 'lost')
        self.assertEqual(cp.request_stop(attempt), 'not-owned')
        record = cp.finalize(attempt)
        self.assertEqual((record['termination'], record['groupEmpty']), ('lost', False))
        self.assertIs(record['executionSuccess'], False)
        self.assertIsNone(sleeper.poll())

    def test_profile_and_stdin_tamper_refused_before_launch(self):
        marker, profile = self.base / 'ran.txt', self.base / 'profile'
        profile.mkdir()
        script = self.helper('marker.py', MARKER)
        stdin_attempt = self.prepare('stdin-1', [script, str(marker)], stdin=b'genuine')
        write_private(stdin_attempt / 'stdin.bin', b'evil')
        profile_attempt = self.prepare('profile-1', [script, str(marker)],
                                       bindings={'profile': str(profile)})
        os.rename(profile, self.base / 'profile-old')
        profile.mkdir()
        for attempt, reason in ((stdin_attempt, 'stdin-tampered'),
                                (profile_attempt, 'config-binding-changed')):
            with self.subTest(reason=reason):
                owned = self.spawn(attempt).release()
                self.handles.append(owned)
                recovery = self.wait_state(owned, {'not-launched'})
                self.assertEqual((recovery.relaunch_safe, recovery.reason), (True, reason))
        self.assertFalse(marker.exists())

    def test_symlinked_paths_refused_and_outside_file_unchanged(self):
        link = self.base / 'root-link'
        os.symlink(self.root, link)
        self.assert_code('root-not-canonical', cp.prepare, str(link),
                         self.command('linked-1', ['-c', 'pass']), 30)
        attempt = self.prepare('real-1', ['-c', 'pass'])
        os.symlink(attempt, self.root / 'alias-1')
        self.assert_code('attempt-not-found', cp.read_status, self.root / 'alias-1')
        victim, marker = self.base / 'victim.txt', self.base / 'ran.txt'
        victim.write_bytes(b'original')
        log_attempt = self.prepare('log-1', [self.helper('marker.py', MARKER), str(marker)])
        pending = self.spawn(log_attempt)
        os.symlink(victim, log_attempt / 'stdout.log')
        owned = pending.release()
        self.handles.append(owned)
        recovery = self.wait_state(owned, {'not-launched'})
        self.assertEqual(recovery.reason, 'log-unsafe')
        self.assertEqual(victim.read_bytes(), b'original')
        self.assertFalse(marker.exists())

    def test_torn_journal_after_release_is_unknown(self):
        attempt = self.prepare('torn-1', ['-c', 'pass'], stdin=b'genuine')
        write_private(attempt / 'stdin.bin', b'evil')
        owned = self.spawn(attempt).release()
        self.handles.append(owned)
        self.wait_state(owned, {'not-launched'})
        with open(attempt / 'journal.jsonl', 'ab') as handle:
            handle.write(b'{"event": "laun')
        recovery = cp.recover(attempt)
        self.assertEqual((recovery.state, recovery.relaunch_safe, recovery.reason),
                         ('unknown', False, 'journal-torn'))
        self.assert_code('attempt-unknown', cp.finalize, attempt)

    def test_write_all_continues_short_writes_and_rejects_zero(self):
        read_fd, write_fd = os.pipe()
        real_write = os.write
        try:
            with mock.patch.object(cp.os, 'write',
                                   side_effect=lambda fd, data: real_write(fd, bytes(data[:3]))):
                cp._write_all(write_fd, b'0123456789')
            self.assertEqual(os.read(read_fd, 100), b'0123456789')
            with mock.patch.object(cp.os, 'write', return_value=0):
                with self.assertRaises(OSError):
                    cp._write_all(write_fd, b'x')
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_malformed_completion_records_refused(self):
        script = self.helper('marker.py', MARKER)
        attempt, owned = self.launch('done-1', [script, str(self.base / 'one.txt')])
        self.wait_state(owned, {'exited'})
        exit_record = json.loads((attempt / 'exit.json').read_bytes())
        write_private(attempt / 'exit.json', json.dumps({**exit_record, 'exitCode': False}).encode())
        self.assertEqual(cp.recover(attempt).reason, 'exit-record-invalid')
        self.assert_code('attempt-corrupt', cp.finalize, attempt)

        attempt, owned = self.launch('done-2', [script, str(self.base / 'two.txt')])
        self.wait_state(owned, {'exited'})
        record = owned.finalize()
        original = (attempt / 'lifecycle.json').read_bytes()
        huge = json.dumps({**record, 'durationSeconds': 'HUGE'}).replace('"HUGE"', '1e400')
        missing = {key: value for key, value in record.items() if key != 'groupEmpty'}
        mutations = (
            (json.dumps({**record, 'exitCode': False}), 'record-types-invalid'),
            (json.dumps({**record, 'unresolvedDescendants': True}), 'record-types-invalid'),
            (json.dumps({**record, 'attemptId': ''}), 'record-attempt-mismatch'),
            (json.dumps({**record, 'identity': {}}), 'record-identity-invalid'),
            (json.dumps({**record, 'forced': True}), 'record-reasons-inconsistent'),
            (json.dumps(missing), 'record-fields'),
            (huge, 'record-malformed'),
            (json.dumps({**record, 'durationSeconds': 10 ** 400}), 'record-types-invalid'),
            (json.dumps({**record, 'durationSeconds': True}), 'record-types-invalid'),
            (json.dumps({**record, 'membersAtExit': True}), 'record-types-invalid'),
            (json.dumps({**record, 'membersAtExit': 10 ** 400}), 'record-types-invalid'),
            (json.dumps({**record, 'membersAtExit': 1}), 'record-reasons-inconsistent'),
            (json.dumps({**record, 'membersAtExit': None}), 'record-reasons-inconsistent'),
            (json.dumps({**record, 'durationSeconds': record['durationSeconds'] + 1}),
             'record-exit-mismatch'),
        )
        for text, reason in mutations:
            with self.subTest(reason=reason):
                write_private(attempt / 'lifecycle.json', text.encode())
                status = cp.read_status(attempt)
                self.assertEqual((status['state'], status['reason'], status['record']),
                                 ('corrupt', reason, None))
        write_private(attempt / 'lifecycle.json', original)
        self.assertEqual(cp.read_status(attempt)['state'], 'finalized')
        with open(attempt / 'stdout.log', 'ab') as handle:
            handle.write(b'x')
        self.assertEqual(cp.read_status(attempt)['reason'], 'log-tampered')

    def test_read_status_creates_nothing(self):
        script = self.helper('marker.py', MARKER)
        prepared = self.prepare('status-1', [script, str(self.base / 'one.txt')])
        finished, owned = self.launch('status-2', [script, str(self.base / 'two.txt')])
        self.wait_state(owned, {'exited'})
        owned.finalize()
        before = (tree_state(self.root), tree_state(MODULE_PATH.parent))
        self.assertEqual(cp.read_status(prepared)['state'], 'prepared')
        self.assertEqual(cp.read_status(finished)['state'], 'finalized')
        result = subprocess.run([sys.executable, '-I', str(MODULE_PATH), '--status', str(finished)],
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'], 'finalized')
        self.assertEqual((tree_state(self.root), tree_state(MODULE_PATH.parent)), before)

    def test_prepare_refuses_unsafe_inputs(self):
        self.assert_code('env-selector-not-allowed', cp.prepare, str(self.root),
                         self.command('env-1', ['-c', 'pass'], selectors={'ANTHROPIC_API_KEY': str(self.base)}), 30)
        self.assert_code('executable-not-absolute', cp.prepare, str(self.root),
                         cp.CommandSpec(('python3', '-c', 'pass'), str(self.project), b'', 'rel-1'), 30)
        for bad in (float('nan'), True, 0):
            with self.subTest(timeout=bad):
                self.assert_code('invalid-timeout', self.prepare, 'timeout-x', ['-c', 'pass'], timeout=bad)
        inner = self.project / 'attempts'
        inner.mkdir(mode=0o700)
        self.assert_code('attempts-root-overlaps-cwd', cp.prepare, str(inner),
                         self.command('inner-1', ['-c', 'pass']), 30)
        self.prepare('dup-1', ['-c', 'pass'])
        self.assert_code('attempt-exists', self.prepare, 'dup-1', ['-c', 'pass'])
        os.chmod(self.root, 0o770)
        try:
            self.assert_code('root-not-private', self.prepare, 'shared-1', ['-c', 'pass'])
        finally:
            os.chmod(self.root, 0o700)

    def test_env_selector_directory_swap_refused_without_explicit_binding(self):
        marker = self.base / 'ran.txt'
        script = self.helper('marker.py', MARKER)
        swapped = []
        for idx, (key, swap) in enumerate((('CLAUDE_CONFIG_DIR', 'symlink'),
                                           ('CODEX_HOME', 'replace'), ('TMPDIR', 'symlink'))):
            selected = self.base / f'selected-{idx}'
            selected.mkdir()
            attempt = self.prepare(f'sel-{idx}', [script, str(marker)], selectors={key: str(selected)})
            intent = json.loads((attempt / 'intent.json').read_bytes())
            info = os.stat(selected)
            self.assertEqual(intent['environment']['selectors'][key],
                             {'path': str(selected), 'device': info.st_dev, 'inode': info.st_ino})
            self.assertEqual(intent['bindings'], {})  # no caller-supplied duplicate binding
            os.rename(selected, self.base / f'selected-{idx}-old')
            if swap == 'symlink':
                other = self.base / f'selected-{idx}-other'
                other.mkdir()
                os.symlink(other, selected)
            else:
                selected.mkdir()
            swapped.append(attempt)
        for attempt in swapped:
            with self.subTest(attempt=attempt.name):
                owned = self.spawn(attempt).release()
                self.handles.append(owned)
                recovery = self.wait_state(owned, {'not-launched'})
                self.assertEqual((recovery.relaunch_safe, recovery.reason),
                                 (True, 'selector-binding-changed'))
        self.assertFalse(marker.exists())
        control_marker, profile = self.base / 'control.txt', self.base / 'profile-ok'
        profile.mkdir()
        _attempt, owned = self.launch('sel-ok', [script, str(control_marker)],
                                      selectors={'CLAUDE_CONFIG_DIR': str(profile)})
        self.wait_state(owned, {'exited'})
        self.assertTrue(control_marker.exists())  # positive control: an unchanged selector runs
        self.assertIs(owned.finalize()['executionSuccess'], True)

    def test_journal_records_must_match_native_sequence(self):
        bootstrap = journal_line('bootstrap-started', pid=FAKE_PID)
        aborted = journal_line('aborted', reason='stdin-tampered')
        launching = journal_line('launching')
        started = journal_line('command-started', pid=FAKE_PID + 1)
        corrupt_cases = {
            'no-reason': [bootstrap, journal_line('aborted')],
            'unknown-reason': [bootstrap, journal_line('aborted', reason='mystery')],
            'typed-reason': [bootstrap, journal_line('aborted', reason=7)],
            'extra-field': [bootstrap, journal_line('aborted', reason='stdin-tampered', note='x')],
            'missing-at': [bootstrap, json.dumps({'event': 'aborted',
                                                  'reason': 'stdin-tampered'}).encode() + b'\n'],
            'no-bootstrap': [aborted],
            'bootstrap-pid-mismatch': [journal_line('bootstrap-started', pid=FAKE_PID + 7), aborted],
            'bootstrap-pid-huge': [journal_line('bootstrap-started', pid=10 ** 400), aborted],
            'bootstrap-pid-bool': [journal_line('bootstrap-started', pid=True), aborted],
            'double-abort': [bootstrap, aborted, aborted],
            'started-then-aborted': [bootstrap, started, aborted],
            'launched-then-aborted': [bootstrap, launching, started, aborted],
            'command-pid-is-bootstrap': [bootstrap, launching,
                                         journal_line('command-started', pid=FAKE_PID)],
        }
        with mock.patch.object(cp, '_group_empty', return_value=True):
            control = self.fake_spawned('jr-ok', [bootstrap, aborted])
            self.assertEqual(cp.recover(control),
                             cp.Recovery('not-launched', True, 'not-owned', 'stdin-tampered'))
            for idx, (name, lines) in enumerate(corrupt_cases.items()):
                with self.subTest(case=name):
                    attempt = self.fake_spawned(f'jr-{idx}', lines)
                    self.assertEqual(cp.recover(attempt),
                                     cp.Recovery('corrupt', False, 'not-owned', 'journal-corrupt'))
                    self.assert_code('attempt-corrupt', cp.finalize, attempt)
            for idx, lines in enumerate(([bootstrap, launching], [bootstrap, launching, started])):
                with self.subTest(launched=idx):
                    recovery = cp.recover(self.fake_spawned(f'jl-{idx}', lines))
                    self.assertEqual((recovery.state, recovery.relaunch_safe), ('lost', False))
            unreleased = self.fake_spawned('jr-unreleased', [bootstrap, launching], release=False)
            self.assertEqual(cp.recover(unreleased),
                             cp.Recovery('corrupt', False, 'not-owned', 'launch-without-release'))

    def test_exit_settlement_fields_must_be_consistent(self):
        script = self.helper('marker.py', MARKER)
        attempt, owned = self.launch('settle-1', [script, str(self.base / 'one.txt')])
        self.wait_state(owned, {'exited'})
        exit_path, journal_path = attempt / 'exit.json', attempt / 'journal.jsonl'
        clean = json.loads(exit_path.read_bytes())
        self.assertEqual((clean['membersAtRecord'], clean['signalsSent'], clean['forced']),
                         (0, [], False))
        forced = {'signalsSent': ['SIGTERM', 'SIGKILL'], 'forced': True, 'lingering': True}
        invalid = {
            'members-none-unforced': {'membersAtRecord': None},
            'members-none-unforced-unavailable': {'membersAtRecord': None,
                                                  'groupObservation': 'unavailable'},
            'members-one-unforced': {'membersAtRecord': 1},
            'members-true': {'membersAtRecord': True},
            'members-false': {'membersAtRecord': False},
            'members-huge': {**forced, 'membersAtRecord': 10 ** 400},
            'members-over-max': {**forced, 'membersAtRecord': cp.MAX_COUNT + 1},
            'members-none-observed-ok': {**forced, 'membersAtRecord': None},
            'kill-without-term': {'membersAtRecord': 1, 'signalsSent': ['SIGKILL'], 'forced': True,
                                  'lingering': True},
            'term-without-cause': {'signalsSent': ['SIGTERM'], 'forced': True},
            'lingering-unsignalled': {'lingering': True},
            'stop-source-on-exit': {'stopSource': 'file'},
            'code-and-signal': {'signal': 'SIGTERM'},
            'exited-without-status': {**forced, 'exitCode': None},
            'duration-huge-int': {'durationSeconds': 10 ** 400},
            'duration-bool': {'durationSeconds': True},
            'command-pid-huge': {'commandPid': 10 ** 400},
            'escaped-pid-huge': {'escaped': [{'pid': 10 ** 400, 'start': None}]},
        }
        for name, change in invalid.items():
            with self.subTest(case=name):
                write_private(exit_path, json.dumps({**clean, **change}).encode())
                status = cp.read_status(attempt)
                self.assertEqual((status['state'], status['reason']), ('corrupt', 'exit-record-invalid'))
                self.assert_code('attempt-corrupt', cp.finalize, attempt)
        for literal in ('NaN', 'Infinity', '-Infinity', '1e400'):
            with self.subTest(literal=literal):
                text = json.dumps({**clean, 'durationSeconds': 'X'}).replace('"X"', literal)
                write_private(exit_path, text.encode())
                self.assertEqual(cp.recover(attempt).reason, 'record-malformed')
        write_private(exit_path, json.dumps(clean).encode())
        self.assertEqual(cp.recover(attempt).state, 'exited')  # valid zero-member control
        native = journal_path.read_bytes()
        lines = native.splitlines(keepends=True)
        for name, data in (('pid', b''.join(lines[:-1]) + journal_line('command-started', pid=FAKE_PID)),
                           ('aborted', lines[0] + journal_line('aborted', reason='stdin-tampered'))):
            with self.subTest(journal=name):
                write_private(journal_path, data)
                self.assertEqual(cp.recover(attempt).reason, 'exit-journal-mismatch')
        write_private(journal_path, native)
        nonempty = {**clean, **forced, 'membersAtRecord': 1}
        write_private(exit_path, json.dumps(nonempty).encode())
        self.assertEqual(cp.recover(attempt).state, 'exited')  # valid forced settlement
        record = owned.finalize()  # the owning handle reaps its bootstrap before settling
        self.assertEqual((record['membersAtExit'], record['groupEmpty']), (1, True))
        for reason in ('forced', 'exit-group-not-proven-empty'):
            self.assertIn(reason, record['reasons'])
        self.assertIs(record['executionSuccess'], False)
        self.assertEqual(cp.read_status(attempt)['record'], record)
        write_private(exit_path, json.dumps(
            {**nonempty, 'durationSeconds': nonempty['durationSeconds'] + 1}).encode())
        self.assertEqual(cp.read_status(attempt)['reason'], 'record-exit-mismatch')
        os.unlink(exit_path)
        self.assertEqual(cp.read_status(attempt)['reason'], 'record-exit-mismatch')
        write_private(exit_path, json.dumps(nonempty).encode())
        self.assertEqual(cp.read_status(attempt)['state'], 'finalized')

        attempt, owned = self.launch('settle-2', [script, str(self.base / 'two.txt')])
        self.wait_state(owned, {'exited'})
        exit_path = attempt / 'exit.json'
        unobserved = {**json.loads(exit_path.read_bytes()), **forced, 'membersAtRecord': None,
                      'groupObservation': 'unavailable'}
        write_private(exit_path, json.dumps(unobserved).encode())
        self.assertEqual(cp.recover(attempt).state, 'exited')
        record = owned.finalize()
        self.assertEqual((record['membersAtExit'], record['groupEmpty']), (None, True))
        for reason in ('exit-group-not-proven-empty', 'group-observation-unavailable'):
            self.assertIn(reason, record['reasons'])
        self.assertIs(record['executionSuccess'], False)

    def test_owned_finalize_reaps_exit_published_after_first_reap(self):
        script = self.helper('marker.py', MARKER)
        marker, go = self.base / 'race-1.txt', self.base / 'race-1.go'
        attempt, owned = self.launch('race-1', [script, str(marker), str(go)])
        self.wait_path(marker)
        self.assertEqual(owned.poll().state, 'running')  # bootstrap alive, no exit record yet
        with self.racing_exit(attempt, owned, go):
            record = owned.finalize()
        self.assertEqual((record['termination'], record['membersAtExit'], record['groupEmpty']),
                         ('exited', 0, True))
        self.assertEqual(record['reasons'], [])
        self.assertIs(record['executionSuccess'], True)

        # Control: module finalize cannot reap this process's bootstrap; its zombie keeps the
        # group non-empty, so the record conservatively refuses success.
        marker, go = self.base / 'race-2.txt', self.base / 'race-2.go'
        attempt, owned = self.launch('race-2', [script, str(marker), str(go)])
        self.wait_path(marker)
        with self.racing_exit(attempt, owned, go):
            record = cp.finalize(attempt)
        self.assertEqual((record['termination'], record['membersAtExit'], record['groupEmpty']),
                         ('exited', 0, False))
        self.assertIn('group-not-proven-empty', record['reasons'])
        self.assertIs(record['executionSuccess'], False)
        owned.poll()  # reap the zombie this process still holds

    def test_record_carries_actual_command_pid_not_bootstrap(self):
        marker = self.base / 'pid.txt'
        attempt, owned = self.launch('cmdpid-1', [self.helper('marker.py', MARKER), str(marker)])
        self.wait_state(owned, {'exited'})
        record = owned.finalize()
        actual = int(marker.read_text().split()[0])  # the command reported its own os.getpid()
        raw_exit = json.loads((attempt / 'exit.json').read_bytes())
        events = [json.loads(line) for line in (attempt / 'journal.jsonl').read_bytes().splitlines()]
        started = [event['pid'] for event in events if event['event'] == 'command-started']
        self.assertEqual(record['commandPid'], actual)
        self.assertNotEqual(record['commandPid'], record['identity']['pid'])
        self.assertEqual(record['identity'], owned.identity)  # bootstrap anchor retained
        self.assertEqual(started, [actual])
        self.assertEqual((raw_exit['commandPid'], raw_exit['commandStart']),
                         (record['commandPid'], record['commandStart']))
        self.assertTrue(record['commandStart'] is None or record['commandStart'].startswith(
            ('ticks:', 'lstart:')))
        self.assertIs(record['executionSuccess'], True)
        self.assertEqual(cp.read_status(attempt)['record'], record)

        original = (attempt / 'lifecycle.json').read_bytes()
        missing = {key: value for key, value in record.items() if key != 'commandPid'}
        bootstrap_pid = record['identity']['pid']
        mutations = (
            (missing, 'record-fields'),
            ({**record, 'commandPid': True}, 'record-types-invalid'),
            ({**record, 'commandPid': 1}, 'record-types-invalid'),
            ({**record, 'commandPid': 10 ** 400}, 'record-types-invalid'),
            ({**record, 'commandPid': str(actual)}, 'record-types-invalid'),
            ({**record, 'commandStart': 7}, 'record-types-invalid'),
            ({**record, 'commandStart': ''}, 'record-types-invalid'),
            ({**record, 'commandPid': None}, 'record-command-inconsistent'),
            ({**record, 'commandPid': None, 'commandStart': None}, 'record-command-inconsistent'),
            ({**record, 'commandPid': bootstrap_pid}, 'record-command-inconsistent'),
            ({**record, 'commandPid': actual + 1}, 'record-exit-mismatch'),
            ({**record, 'commandStart': 'lstart:never'}, 'record-exit-mismatch'),
            ({**record, 'schema': 'sdlc-controller/process-lifecycle/v2'}, 'record-fields'),
        )
        before = tree_state(attempt)
        for value, reason in mutations:
            with self.subTest(reason=reason, keys=sorted(set(value) ^ set(record))):
                write_private(attempt / 'lifecycle.json', json.dumps(value).encode())
                status = cp.read_status(attempt)
                self.assertEqual((status['state'], status['reason'], status['record']),
                                 ('corrupt', reason, None))
        self.assertEqual(set(tree_state(attempt)), set(before))  # read_status created nothing
        write_private(attempt / 'lifecycle.json', original)
        self.assertEqual(cp.read_status(attempt)['record'], record)

        journal_path = attempt / 'journal.jsonl'
        native = journal_path.read_bytes()
        lines = native.splitlines(keepends=True)
        write_private(journal_path, b''.join(lines[:-1]) + journal_line('command-started', pid=actual + 1))
        self.assertEqual(cp.read_status(attempt)['reason'], 'record-journal-mismatch')
        write_private(journal_path, b''.join(lines[:-1]))
        self.assertEqual(cp.read_status(attempt)['reason'], 'record-journal-mismatch')
        write_private(journal_path, native)
        status = cp.read_status(attempt)
        self.assertEqual((status['state'], status['record']), ('finalized', record))
        self.assertEqual(record['logs']['stdout'], {'path': str(attempt / 'stdout.log'), 'size': 0,
                                                    'sha256': hashlib.sha256(b'').hexdigest()})
        self.assertEqual(raw_exit, json.loads((attempt / 'exit.json').read_bytes()))

    def test_unlaunched_and_lost_records_have_null_command_pid(self):
        pending = self.spawn(self.prepare('cmdpid-nl', ['-c', 'pass']))
        pending.abort()
        self.wait_state(pending.attempt, {'not-launched'})
        record = cp.finalize(pending.attempt)
        self.assertEqual((record['termination'], record['commandPid'], record['commandStart']),
                         ('not-launched', None, None))
        bootstrap = journal_line('bootstrap-started', pid=FAKE_PID)
        lost = self.fake_spawned('cmdpid-lost', [bootstrap, journal_line('launching'),
                                                 journal_line('command-started', pid=FAKE_PID + 1)])
        with mock.patch.object(cp, '_group_empty', return_value=True):
            record = cp.finalize(lost)
        self.assertEqual((record['termination'], record['commandPid'], record['commandStart']),
                         ('lost', None, None))
        self.assertEqual(record['identity']['pid'], FAKE_PID)  # anchor identity kept
        self.assertEqual(cp.read_status(lost)['state'], 'finalized')
        write_private(lost / 'lifecycle.json', json.dumps(
            {**record, 'commandPid': FAKE_PID + 1}).encode())
        self.assertEqual(cp.read_status(lost)['reason'], 'record-command-inconsistent')

    def test_huge_and_non_finite_numbers_classified_not_raised(self):
        options = (('timeout', 'invalid-timeout'), ('term_grace_seconds', 'invalid-term-grace'),
                   ('linger_seconds', 'invalid-linger'))
        for value in (10 ** 400, float('inf'), float('nan'), True, -1):
            for option, code in options:
                with self.subTest(option=option, value=repr(value)[:12]):
                    self.assert_code(code, self.prepare, 'num-x', ['-c', 'pass'], **{option: value})
        attempt = self.prepare('num-1', ['-c', 'pass'])
        intent_path = attempt / 'intent.json'
        original = json.loads(intent_path.read_bytes())
        literals = (('1' + '0' * 400, 'intent-invalid'), ('true', 'intent-invalid'),
                    ('NaN', 'record-malformed'), ('Infinity', 'record-malformed'),
                    ('1e400', 'record-malformed'))
        for key in ('timeoutSeconds', 'termGraceSeconds', 'lingerSeconds', 'releaseTimeoutSeconds'):
            for literal, reason in literals:
                with self.subTest(key=key, literal=literal[:8]):
                    text = json.dumps({**original, key: 'X'}).replace('"X"', literal)
                    write_private(intent_path, text.encode())
                    status = cp.read_status(attempt)
                    self.assertEqual((status['state'], status['reason']), ('corrupt', reason))
        write_private(intent_path, json.dumps(original).encode())
        self.assertEqual(cp.recover(attempt).state, 'prepared')  # positive control
        intent_sha = hashlib.sha256(intent_path.read_bytes()).hexdigest()
        identity = {'attemptId': 'num-1', 'intentSha256': intent_sha, 'pid': 10 ** 400,
                    'pgid': 10 ** 400, 'bootId': cp.boot_identity(), 'processStart': 'lstart:x',
                    'token': secrets.token_hex(16)}
        write_private(attempt / 'spawn.lock', b'')
        write_private(attempt / 'spawn.json', json.dumps(
            {'schema': cp.SCHEMA_SPAWN, 'identity': identity, 'spawnedAt': 'x'}).encode())
        status = cp.read_status(attempt)
        self.assertEqual((status['state'], status['reason']), ('corrupt', 'identity-invalid'))
        self.assert_code('identity-invalid', cp.request_stop, attempt)


if __name__ == '__main__':
    unittest.main()
