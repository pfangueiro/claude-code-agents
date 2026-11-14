"""Controller check execution against real disposable Git checkouts and subprocesses.

Uses the existing verified-handoff v1 recorder and validator through the in-process
supervisor seam. No provider terminal, native client or network call.
"""
import hashlib
import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / '.claude/skills/delivery/scripts'
EVIDENCE = ROOT / '.claude/skills/verified-handoff/scripts/evidence.py'
sys.path.insert(0, str(SCRIPTS))
import controller_checks as checks  # noqa: E402
import controller_process  # noqa: E402

PARENT_EXITS = ('import subprocess, sys\n'
                'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],'
                ' stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n')


def git(repo, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(['git', '-C', str(repo), *args], env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def tree_snapshot(root: Path) -> dict:
    snapshot = {}
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        snapshot[str(path.relative_to(root))] = (info.st_mode, info.st_size, info.st_mtime_ns, digest)
    return snapshot


class ControllerCheckCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='controller-checks-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(os.path.realpath(tmp.name))
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        (self.repo / 'module.py').write_text('VALUE = 1\n')
        git(self.repo, 'init', '-q')
        git(self.repo, 'add', 'module.py')
        git(self.repo, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'fixture')
        self.sha = git(self.repo, 'rev-parse', 'HEAD')
        self.artifacts = self.base / 'artifacts'
        self.artifacts.mkdir()
        os.chmod(self.artifacts, 0o700)
        self.marker = self.base / 'marker'
        self.calls = []
        self.counter = 0

    def spec(self, check_id, code=None, argv=None, sha=None, timeout=60):
        self.counter += 1
        return checks.CheckSpec(check_id=check_id, attempt_id=f'{check_id}-{self.counter}',
                                argv=argv or (sys.executable, '-c', code), cwd=str(self.repo),
                                expected_sha=sha or self.sha, evidence_path=str(EVIDENCE),
                                timeout_seconds=timeout)

    def declare(self, *specs):
        return checks.predeclare_checks(specs, str(self.artifacts), allowed_argv=[s.argv for s in specs])

    def callbacks(self, release=True, stop=None, on_spawn=None):
        def record_spawn(identity, path):
            self.calls.append(('spawn', identity['attemptId'], path))

        def authorize():
            self.calls.append(('authorize',))
            return release
        return {'on_spawn': on_spawn or record_spawn, 'authorize_release': authorize,
                'should_stop': stop or (lambda: False)}

    def run_one(self, prepared, **kwargs):
        return checks.run_check(prepared, **self.callbacks(**kwargs))


class Predeclaration(ControllerCheckCase):
    def test_manifest_is_exact_and_written_before_any_run(self):
        (prepared,) = self.declare(self.spec('unit', "print('ok')"))
        attempt = Path(prepared.attempt_dir)
        manifest = json.loads((attempt / checks.MANIFEST).read_text())
        self.assertEqual(manifest['checks'][0]['expectedSha'], self.sha)
        self.assertEqual(manifest['checks'][0]['command'],
                         {'executable': sys.executable, 'args': ['-c', "print('ok')"]})
        self.assertEqual(sorted(p.name for p in attempt.iterdir()), [checks.INTENT, checks.MANIFEST])
        self.assertEqual((attempt / checks.MANIFEST).stat().st_mode & 0o777, 0o600)
        outcome = self.run_one(prepared)
        self.assertEqual(outcome.status, 'PASS', outcome.reasons)
        self.assertEqual(outcome.input_sha, self.sha)
        self.assertTrue(Path(outcome.receipt).is_file())
        self.assertEqual(self.calls[0][0], 'spawn')
        self.assertEqual(self.calls[1], ('authorize',))

    def test_invalid_declarations_create_nothing(self):
        good = self.spec('good', 'pass')
        cases = [
            ('argv-not-allowlisted', lambda: checks.predeclare_checks([good], str(self.artifacts), [])),
            ('invalid-expected-sha', lambda: self.declare(good, self.spec('bad', 'pass', sha='abc'))),
            ('duplicate-check', lambda: self.declare(good, good)),
        ]
        for code, action in cases:
            with self.subTest(code=code):
                with self.assertRaises(checks.CheckError) as caught:
                    action()
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(list(self.artifacts.iterdir()), [])

    def test_artifact_root_must_be_private_canonical_and_outside_input(self):
        spec = self.spec('unit', 'pass')
        os.chmod(self.artifacts, 0o755)
        with self.assertRaises(checks.CheckError):
            checks.predeclare_checks([spec], str(self.artifacts), [spec.argv])
        os.chmod(self.artifacts, 0o700)
        link = self.base / 'link'
        link.symlink_to(self.artifacts)
        with self.assertRaises(checks.CheckError):
            checks.predeclare_checks([spec], str(link), [spec.argv])
        inside = self.repo / 'art'
        inside.mkdir(mode=0o700)
        with self.assertRaises(checks.CheckError) as caught:
            checks.predeclare_checks([spec], str(inside), [spec.argv])
        self.assertEqual(caught.exception.code, 'artifact-root-overlaps-input')

    def test_empty_check_set_is_never_a_pass(self):
        self.assertEqual(self.declare(), ())
        self.assertEqual(checks.aggregate(checks.run_checks((), **self.callbacks())),
                         ('INCOMPLETE', ('no-checks-declared',)))


class Outcomes(ControllerCheckCase):
    def test_nonzero_exit_is_fail(self):
        (prepared,) = self.declare(self.spec('unit', 'raise SystemExit(3)'))
        outcome = self.run_one(prepared)
        self.assertEqual((outcome.status, outcome.reasons), ('FAIL', ('check-nonzero-exit',)))

    def test_missing_executable_is_incomplete(self):
        (prepared,) = self.declare(self.spec('unit', argv=(str(self.base / 'absent-tool'),)))
        outcome = self.run_one(prepared)
        self.assertEqual(outcome.status, 'INCOMPLETE')
        self.assertIn('refused-executable-not-found', outcome.reasons)
        self.assertIsNone(outcome.process)

    def test_tracked_mutation_is_not_pass(self):
        (prepared,) = self.declare(self.spec('unit', "open('module.py', 'a').write('X = 2\\n')"))
        outcome = self.run_one(prepared)
        self.assertEqual(outcome.status, 'INCOMPLETE')
        self.assertIn('input-mutated', outcome.reasons)

    def test_wrong_sha_is_refused_before_launch(self):
        code = f'open({str(self.marker)!r}, "w").close()'
        (prepared,) = self.declare(self.spec('unit', code, sha='0' * 40))
        outcome = self.run_one(prepared)
        self.assertEqual(outcome.status, 'INCOMPLETE')
        self.assertIn('refused-head-mismatch', outcome.reasons)
        self.assertIsNone(outcome.process)
        self.assertFalse(self.marker.exists())

    def test_all_checks_collected_and_known_fail_dominates(self):
        prepared = self.declare(self.spec('passing', 'pass'), self.spec('failing', 'raise SystemExit(1)'),
                                self.spec('missing', argv=(str(self.base / 'absent-tool'),)))
        outcomes = checks.run_checks(prepared, **self.callbacks())
        self.assertEqual([o.status for o in outcomes], ['PASS', 'FAIL', 'INCOMPLETE'])
        self.assertEqual(checks.aggregate(outcomes)[0], 'FAIL')

    def test_missing_only_is_incomplete(self):
        prepared = self.declare(self.spec('passing', 'pass'),
                                self.spec('missing', argv=(str(self.base / 'absent-tool'),)))
        outcomes = checks.run_checks(prepared, **self.callbacks())
        self.assertEqual(checks.aggregate(outcomes), ('INCOMPLETE', ('missing:INCOMPLETE',)))

    def test_attempt_runs_once(self):
        (prepared,) = self.declare(self.spec('unit', 'pass'))
        self.assertEqual(self.run_one(prepared).status, 'PASS')
        again = self.run_one(prepared)
        self.assertEqual((again.status, again.reasons), ('INCOMPLETE', ('attempt-already-run',)))


class Control(ControllerCheckCase):
    def test_release_is_gated_by_callback(self):
        (prepared,) = self.declare(self.spec('unit', f'open({str(self.marker)!r}, "w").close()'))
        outcome = self.run_one(prepared, release=False)
        self.assertEqual(outcome.status, 'INCOMPLETE')
        self.assertIn('refused-release-not-authorized', outcome.reasons)
        self.assertEqual([call[0] for call in self.calls], ['spawn', 'authorize'])
        time.sleep(0.5)
        self.assertFalse(self.marker.exists())
        self.assertNotIn(controller_process.recover(outcome.process).state,
                         controller_process.ACTIVE_STATES)

    def test_spawn_callback_failure_aborts_held_process(self):
        def broken(_identity, _path):
            raise RuntimeError('ledger unavailable')
        (prepared,) = self.declare(self.spec('unit', f'open({str(self.marker)!r}, "w").close()'))
        outcome = self.run_one(prepared, on_spawn=broken)
        self.assertEqual(outcome.status, 'INCOMPLETE')
        self.assertIn('refused-release-callback-failed', outcome.reasons)
        time.sleep(0.5)
        self.assertFalse(self.marker.exists())

    def test_durable_stop_while_running_is_incomplete(self):
        code = f'open({str(self.marker)!r}, "w").close()\nimport time\ntime.sleep(30)'
        (prepared,) = self.declare(self.spec('unit', code))
        started = time.monotonic()
        outcome = self.run_one(prepared, stop=self.marker.exists)
        self.assertLess(time.monotonic() - started, 25)
        self.assertEqual(outcome.status, 'INCOMPLETE')
        record = controller_process.read_status(outcome.process)['record']
        self.assertEqual(record['termination'], 'stopped')

    def test_parent_exit_with_redirected_child_is_not_pass(self):
        (prepared,) = self.declare(self.spec('unit', PARENT_EXITS))
        outcome = self.run_one(prepared)
        self.assertEqual(outcome.status, 'INCOMPLETE')
        record = controller_process.read_status(outcome.process)['record']
        self.assertTrue(record['forced'])


class Recovery(ControllerCheckCase):
    def passed(self):
        (prepared,) = self.declare(self.spec('unit', "print('ok')"))
        outcome = self.run_one(prepared)
        self.assertEqual(outcome.status, 'PASS', outcome.reasons)
        return prepared, outcome

    def test_inspection_is_read_only_and_missing_receipt_never_passes(self):
        prepared, _ = self.passed()
        before = tree_snapshot(self.artifacts)
        self.assertEqual(checks.inspect_check(prepared).status, 'PASS')
        self.assertEqual(tree_snapshot(self.artifacts), before)
        Path(prepared.attempt_dir, checks.RECEIPT_DIR, checks.RESULT).unlink()
        before = tree_snapshot(self.artifacts)
        outcome = checks.inspect_check(prepared)
        self.assertEqual(outcome.status, 'INCOMPLETE')
        self.assertIn('receipt-missing', outcome.reasons)
        self.assertIsNotNone(outcome.process)
        self.assertEqual(tree_snapshot(self.artifacts), before)

    def test_raw_log_tampering_is_rejected(self):
        prepared, outcome = self.passed()
        with open(Path(outcome.receipt).parent / 'stdout.log', 'ab') as handle:
            handle.write(b'forged\n')
        inspected = checks.inspect_check(prepared)
        self.assertEqual(inspected.status, 'INCOMPLETE')
        self.assertIn('stdout-log-altered', inspected.reasons)

    def test_helper_log_tampering_is_rejected(self):
        prepared, outcome = self.passed()
        with open(Path(outcome.process) / 'stdout.log', 'ab') as handle:
            handle.write(b'forged\n')
        inspected = checks.inspect_check(prepared)
        self.assertEqual(inspected.status, 'INCOMPLETE')
        self.assertIn('process-corrupt', inspected.reasons)

    def test_receipt_argv_and_manifest_tampering_are_rejected(self):
        prepared, outcome = self.passed()
        receipt_path = Path(outcome.receipt)
        receipt = json.loads(receipt_path.read_text())
        receipt['command']['args'] = ['-c', 'pass']
        receipt_path.write_text(json.dumps(receipt))
        self.assertIn('wrong-command', checks.inspect_check(prepared).reasons)
        manifest = Path(prepared.attempt_dir, checks.MANIFEST)
        manifest.write_text(manifest.read_text().replace(self.sha, '1' * 40))
        tampered = checks.inspect_check(prepared)
        self.assertEqual((tampered.status, tampered.reasons), ('INCOMPLETE', ('manifest-changed',)))


class Contracts(unittest.TestCase):
    RECORD = {'schema': controller_process.SCHEMA_RECORD_V3,
              'identity': {'pid': 100}, 'lingering': False, 'groupEmpty': True, 'membersAtExit': 0,
              'groupObservation': 'ok', 'escapedDescendants': 0, 'unresolvedDescendants': 0,
              'termination': 'exited', 'signalsSent': [], 'exitCode': 0, 'signal': None}

    def test_child_mapping_requires_actual_command_identity(self):
        for extra, code in (({}, 'command-identity-missing'),
                            ({'commandPid': 100, 'commandStart': 'x'}, 'command-identity-invalid')):
            with self.subTest(code=code), self.assertRaises(checks.CheckError) as caught:
                checks.child_from_record({**self.RECORD, **extra})
            self.assertEqual(caught.exception.code, code)
        child = checks.child_from_record({**self.RECORD, 'commandPid': 200, 'commandStart': 'x'})
        self.assertEqual((child['pid'], child['groupEmptyAtReceipt']), (200, True))

    def test_group_clean_uses_escaped_settlement_predicate(self):
        base = {**self.RECORD, 'commandPid': 200, 'commandStart': 'x'}
        gone = {'pid': 300, 'start': 'lstart:a', 'status': 'gone', 'proof': 'esrch', 'currentStart': None}
        unknown = {**gone, 'status': 'unknown', 'proof': 'query-failed'}
        settlement = {'observationComplete': True, 'bootId': 'boot-a', 'observedAt': 'x',
                      'identities': [gone], 'settled': 1, 'live': 0, 'unknown': 0}
        settled = {**base, 'schema': controller_process.SCHEMA_RECORD,
                   'identity': {'pid': 100, 'bootId': 'boot-a'}, 'escapedDescendants': 1,
                   'escapedOverflow': False, 'escapedSettlement': settlement}
        reused = {'pid': 300, 'start': 'lstart:a', 'status': 'reused', 'proof': 'start-differs',
                  'currentStart': 'lstart:b'}
        live = {'pid': 300, 'start': 'lstart:b', 'status': 'live', 'proof': 'start-matches',
                'currentStart': 'lstart:b'}
        foreign = {**live, 'status': 'reused', 'proof': 'start-differs', 'currentStart': 'lstart:c'}
        two = {**settled, 'escapedDescendants': 2}
        empty = {**settlement, 'identities': [], 'settled': 0}
        cases = (
            ('v4-reused-pid-second-live', {**two, 'unresolvedDescendants': 1, 'escapedSettlement': {
                **settlement, 'identities': [reused, live], 'settled': 1, 'live': 1}}, False),
            ('v4-reused-pid-foreign-now', {**two, 'escapedSettlement': {
                **settlement, 'identities': [reused, foreign], 'settled': 2}}, True),
            ('v4-capture-from-other-boot', {**settled, 'escapedDescendants': 0,
                                            'escapedSettlement': {**empty, 'bootId': 'boot-b'}}, False),
            ('v4-incomplete-observation', {**settled, 'groupObservation': 'unavailable',
                                           'escapedDescendants': 0, 'escapedSettlement': {
                                               **empty, 'observationComplete': False}}, False),
            ('legacy-none', base, True),
            ('legacy-historical', {**base, 'escapedDescendants': 27}, False),
            ('v4-settled', settled, True),
            ('v4-unknown-counted-settled',
             {**settled, 'escapedSettlement': {**settlement, 'identities': [unknown]}}, False),
            ('v4-unknown', {**settled, 'unresolvedDescendants': 1, 'escapedSettlement': {
                **settlement, 'identities': [unknown], 'settled': 0, 'unknown': 1}}, False),
            ('v4-truncated', {**settled, 'escapedOverflow': True}, False),
            ('unknown-schema', {**settled, 'schema': 'sdlc-controller/process-lifecycle/v2'}, False),
        )
        for name, record, expected in cases:
            with self.subTest(case=name):
                self.assertIs(controller_process.escaped_settled(record), expected)
                self.assertIs(checks.child_from_record(record)['groupEmptyAtReceipt'], expected)

    def test_no_nested_recorder_or_provider_terminal(self):
        source = (SCRIPTS / 'controller_checks.py').read_text()
        self.assertNotIn('import subprocess', source)
        self.assertNotIn('Popen', source)
        self.assertIsNone(re.search(r'(?i)\b(claude|codex)\b', source))

    def test_evidence_seam_is_keyword_only_and_defaults_to_native(self):
        spec = importlib.util.spec_from_file_location('evidence_seam_probe', EVIDENCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        seam = inspect.signature(module.run_check).parameters['supervisor']
        self.assertIs(seam.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(seam.default)


if __name__ == '__main__':
    unittest.main()
