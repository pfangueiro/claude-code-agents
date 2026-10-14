"""Real-subprocess tests for the repo-context and verified-handoff skill resources.

Every fixture is a disposable repository, archive or directory under a temporary
directory with an isolated Git configuration. Fragile properties (pre-launch refusal,
signals, timeouts, process-group cleanup, never executing candidates) are proved by
running real child processes, not by asserting on handcrafted receipts.

Set DELIVERY_RESOURCE_SCRIPTS to a directory holding evidence.py and repo_context.py
to test staged copies; by default the skill sources in this repository are used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_override = os.environ.get('DELIVERY_RESOURCE_SCRIPTS')
EVIDENCE = Path(_override, 'evidence.py') if _override \
    else REPO / '.claude/skills/verified-handoff/scripts/evidence.py'
REPO_CONTEXT = Path(_override, 'repo_context.py') if _override \
    else REPO / '.claude/skills/repo-context/scripts/repo_context.py'
SENTINEL = 'UNTRUSTED-SENTINEL-7f3a'


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='delivery-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        home = self.tmp / 'home'
        home.mkdir()
        gitconfig = home / 'gitconfig'
        gitconfig.write_text('[user]\n\tname = Fixture User\n\temail = fixture@example.invalid\n'
                             '[init]\n\tdefaultBranch = main\n')
        self.env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(home),
                    'GIT_CONFIG_GLOBAL': str(gitconfig), 'GIT_CONFIG_NOSYSTEM': '1',
                    'LC_ALL': 'C'}
        self.evidence_root = self.tmp / 'evidence'
        self.evidence_root.mkdir()

    def git(self, cwd: Path, *args: str) -> str:
        proc = subprocess.run(['git', '-C', str(cwd), *args], env=self.env,
                              capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    def make_repo(self, files: dict[str, str], name: str = 'project') -> tuple[Path, str]:
        root = self.tmp / name
        root.mkdir()
        self.git(root, 'init', '-q')
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.git(root, 'add', '-A')
        self.git(root, 'commit', '-q', '-m', 'fixture')
        return root, self.git(root, 'rev-parse', 'HEAD')


class EvidenceTests(Sandbox):
    def run_evidence(self, cwd: Path, label: str, command: list[str], *, sha: str | None = None,
                     source: str | None = None, timeout: float | None = None,
                     out_dir: Path | None = None) -> tuple[int, dict | None, Path]:
        out = out_dir or self.evidence_root / label
        args = [sys.executable, str(EVIDENCE), 'run', '--cwd', str(cwd), '--out-dir', str(out),
                '--label', label]
        args += ['--expected-sha', sha] if sha else ['--source-only', source]
        if timeout is not None:
            args += ['--timeout', str(timeout)]
        proc = subprocess.run(args + ['--', *command], env=self.env, capture_output=True,
                              text=True, timeout=120)
        result = out / 'result.json'
        receipt = json.loads(result.read_text()) if result.is_file() else None
        return proc.returncode, receipt, out

    def manifest(self, checks: list[dict]) -> Path:
        path = self.evidence_root / 'manifest.json'
        path.write_text(json.dumps({'checks': checks}))
        return path

    def check_entry(self, label: str, cwd: Path, command: list[str], *, sha=None, source=None):
        entry = {'label': label, 'cwd': str(cwd),
                 'command': {'executable': command[0], 'args': command[1:]},
                 'resultFile': f'{label}/result.json'}
        entry.update({'expectedSha': sha} if sha else {'sourceOnly': source})
        return entry

    def verify(self, manifest: Path) -> tuple[int, dict, str]:
        proc = subprocess.run([sys.executable, str(EVIDENCE), 'verify', '--manifest', str(manifest)],
                              env=self.env, capture_output=True, text=True, timeout=60)
        return proc.returncode, json.loads(proc.stdout), proc.stdout + proc.stderr

    def py(self, code: str) -> list[str]:
        return [sys.executable, '-c', code]

    # -- committed runs

    def test_valid_run_passes_and_verifies(self):
        root, sha = self.make_repo({'app.txt': 'v1\n'})
        command = self.py('print("hello"); import sys; print("warn", file=sys.stderr)')
        code, receipt, out = self.run_evidence(root, 'ok', command, sha=sha)
        self.assertEqual(code, 0)
        self.assertEqual(receipt['gate'], {'outcome': 'pass', 'reasons': []})
        self.assertEqual(receipt['child']['exitCode'], 0)
        self.assertIsNone(receipt['child']['signal'])
        self.assertEqual(receipt['input']['before']['head'], sha)
        self.assertEqual(receipt['input']['after']['head'], sha)
        self.assertEqual(receipt['command']['args'], command[1:])
        self.assertEqual((out / 'stdout.log').read_text(), 'hello\n')
        self.assertNotIn('environment', json.dumps(receipt).lower().replace(
            'environment is inherited', ''))
        self.assertFalse((out / '.result.json.tmp').exists())
        code, report, _ = self.verify(self.manifest([self.check_entry('ok', root, command, sha=sha)]))
        self.assertEqual((code, report['checks'][0]['status']), (0, 'verified'))

    def test_nonzero_exit_fails_gate_and_verify(self):
        root, sha = self.make_repo({'a': '1'})
        command = self.py('raise SystemExit(3)')
        code, receipt, _ = self.run_evidence(root, 'nonzero', command, sha=sha)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['child']['exitCode'], 3)
        self.assertIn('child-nonzero-exit', receipt['gate']['reasons'])
        code, report, _ = self.verify(self.manifest([self.check_entry('nonzero', root, command, sha=sha)]))
        self.assertEqual(code, 1)
        self.assertIn('child-nonzero-exit', report['checks'][0]['reasons'])

    def test_signalled_child_is_recorded(self):
        root, sha = self.make_repo({'a': '1'})
        command = self.py('import os, signal; os.kill(os.getpid(), signal.SIGTERM)')
        code, receipt, _ = self.run_evidence(root, 'signal', command, sha=sha)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['child']['signal'], 'SIGTERM')
        self.assertIsNone(receipt['child']['exitCode'])
        self.assertIn('child-signalled', receipt['gate']['reasons'])

    def test_missing_executable_is_not_launched(self):
        root, sha = self.make_repo({'a': '1'})
        code, receipt, out = self.run_evidence(root, 'missing', ['no-such-tool-xyz', '--x'], sha=sha)
        self.assertEqual(code, 3)
        self.assertEqual(receipt['gate'], {'outcome': 'refused', 'reasons': ['executable-not-found']})
        self.assertFalse(receipt['child']['launched'])
        self.assertFalse((out / 'stdout.log').exists())

    def test_stale_sha_refused_before_launch(self):
        root, old = self.make_repo({'a': '1'})
        (root / 'a').write_text('2')
        self.git(root, 'commit', '-qam', 'second')
        marker = self.tmp / 'launched-stale'
        code, receipt, _ = self.run_evidence(
            root, 'stale', self.py(f'open({str(marker)!r}, "w").close()'), sha=old)
        self.assertEqual(code, 3)
        self.assertEqual(receipt['gate']['reasons'], ['head-mismatch'])
        self.assertFalse(marker.exists())

    def test_dirty_input_refused_before_launch(self):
        root, sha = self.make_repo({'a': '1'})
        marker = self.tmp / 'launched-dirty'
        command = self.py(f'open({str(marker)!r}, "w").close()')
        (root / 'a').write_text('edited')
        code, receipt, _ = self.run_evidence(root, 'dirty-tracked', command, sha=sha)
        self.assertEqual((code, receipt['gate']['reasons']), (3, ['dirty-input']))
        self.git(root, 'checkout', '--', 'a')
        (root / 'stray.txt').write_text('untracked')
        code, receipt, _ = self.run_evidence(root, 'dirty-untracked', command, sha=sha)
        self.assertEqual((code, receipt['gate']['reasons']), (3, ['dirty-input']))
        self.assertFalse(marker.exists())

    def test_tracked_mutation_rejects_despite_exit_zero(self):
        root, sha = self.make_repo({'src.txt': 'original\n'})
        command = self.py('open("src.txt", "a").write("changed\\n")')
        code, receipt, _ = self.run_evidence(root, 'mutate', command, sha=sha)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['child']['exitCode'], 0)
        self.assertIn('tracked-input-changed', receipt['gate']['reasons'])
        code, report, _ = self.verify(self.manifest([self.check_entry('mutate', root, command, sha=sha)]))
        self.assertEqual(code, 1)
        self.assertIn('input-mutated', report['checks'][0]['reasons'])

    def test_head_change_rejects_despite_exit_zero(self):
        root, sha = self.make_repo({'a': '1'})
        command = ['git', 'commit', '-q', '--allow-empty', '-m', 'during run']
        code, receipt, _ = self.run_evidence(root, 'head-move', command, sha=sha)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['child']['exitCode'], 0)
        self.assertIn('head-changed', receipt['gate']['reasons'])

    def test_out_dir_inside_input_and_existing_out_dir_refused(self):
        root, sha = self.make_repo({'a': '1'})
        code, receipt, _ = self.run_evidence(root, 'inside', self.py('pass'), sha=sha,
                                             out_dir=root / 'evidence-out')
        self.assertEqual((code, receipt['gate']['reasons']), (3, ['out-dir-inside-input']))
        existing = self.evidence_root / 'exists'
        existing.mkdir()
        code, _, _ = self.run_evidence(root, 'exists', self.py('pass'), sha=sha, out_dir=existing)
        self.assertEqual(code, 2)

    def test_identity_flags_are_mutually_exclusive_and_required(self):
        root, sha = self.make_repo({'a': '1'})
        base = [sys.executable, str(EVIDENCE), 'run', '--cwd', str(root), '--label', 'x']
        both = base + ['--out-dir', str(self.evidence_root / 'both'), '--expected-sha', sha,
                       '--source-only', 'archive', '--', 'true']
        neither = base + ['--out-dir', str(self.evidence_root / 'neither'), '--', 'true']
        for argv in (both, neither):
            proc = subprocess.run(argv, env=self.env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.evidence_root / 'both').exists())

    # -- source-only runs

    def make_archive_tree(self) -> Path:
        staging = self.tmp / 'staging'
        (staging / 'pkg').mkdir(parents=True)
        (staging / 'pkg' / 'mod.py').write_text('VALUE = 1\n')
        archive = self.tmp / 'release.tar.gz'
        with tarfile.open(archive, 'w:gz') as handle:
            handle.add(staging / 'pkg', arcname='pkg')
        extracted = self.tmp / 'extracted'
        extracted.mkdir()
        with tarfile.open(archive) as handle:
            handle.extractall(extracted, filter='data')
        return extracted

    def test_source_only_archive_run_and_verify(self):
        tree = self.make_archive_tree()
        description = 'release.tar.gz fixture archive'
        command = self.py('import sys; sys.path.insert(0, "pkg"); import mod; print(mod.VALUE)')
        code, receipt, _ = self.run_evidence(tree, 'archive', command, source=description)
        self.assertEqual(code, 0, receipt)
        self.assertEqual(receipt['mode'], 'source-only')
        self.assertIsNone(receipt['expectedSha'])
        code, report, _ = self.verify(self.manifest(
            [self.check_entry('archive', tree, command, source=description)]))
        self.assertEqual(code, 0, report)

    def test_source_only_mutation_fails(self):
        tree = self.make_archive_tree()
        command = self.py('open("pkg/mod.py", "a").write("VALUE = 2\\n")')
        code, receipt, _ = self.run_evidence(tree, 'archive-mut', command, source='fixture')
        self.assertEqual(code, 1)
        self.assertIn('source-input-changed', receipt['gate']['reasons'])

    # -- verify

    def test_verify_pending_wrong_command_and_altered_log(self):
        root, sha = self.make_repo({'a': '1'})
        good = self.py('print("x")')
        self.run_evidence(root, 'done', good, sha=sha)
        self.run_evidence(root, 'altered', good, sha=sha)
        with open(self.evidence_root / 'altered' / 'stdout.log', 'a') as handle:
            handle.write('forged\n')
        manifest = self.manifest([
            self.check_entry('done', root, self.py('print("different")'), sha=sha),
            self.check_entry('altered', root, good, sha=sha),
            self.check_entry('later', root, good, sha=sha),
        ])
        code, report, _ = self.verify(manifest)
        self.assertEqual(code, 1)
        by_label = {c['label']: c for c in report['checks']}
        self.assertIn('wrong-command', by_label['done']['reasons'])
        self.assertEqual(by_label['altered']['reasons'], ['stdout-log-altered'])
        self.assertEqual(by_label['later']['status'], 'pending')

    def test_verify_pending_only(self):
        root, sha = self.make_repo({'a': '1'})
        code, report, _ = self.verify(self.manifest([self.check_entry('todo', root, ['true'], sha=sha)]))
        self.assertEqual((code, report['outcome']), (3, 'pending'))

    def test_verify_rejects_symlink_directory_and_aliased_logs(self):
        root, sha = self.make_repo({'a': '1'})
        command = self.py('print("x")')
        cases = {}
        for label in ('symlink', 'directory', 'aliased'):
            self.run_evidence(root, label, command, sha=sha)
            cases[label] = self.evidence_root / label
        decoy = self.tmp / 'decoy.log'
        shutil.copy(cases['symlink'] / 'stdout.log', decoy)
        (cases['symlink'] / 'stdout.log').unlink()
        (cases['symlink'] / 'stdout.log').symlink_to(decoy)
        (cases['directory'] / 'stderr.log').unlink()
        (cases['directory'] / 'stderr.log').mkdir()
        os.link(cases['aliased'] / 'stdout.log', self.tmp / 'second-name.log')
        code, report, _ = self.verify(self.manifest(
            [self.check_entry(label, root, command, sha=sha) for label in cases]))
        self.assertEqual(code, 1)
        by_label = {c['label']: c['reasons'] for c in report['checks']}
        self.assertIn('stdout-log-symlink', by_label['symlink'])
        self.assertIn('stderr-log-directory', by_label['directory'])
        self.assertIn('stdout-log-aliased', by_label['aliased'])

    def test_verify_rejects_symlinked_receipt(self):
        root, sha = self.make_repo({'a': '1'})
        command = self.py('print("x")')
        self.run_evidence(root, 'real', command, sha=sha)
        linked = self.evidence_root / 'linked'
        linked.mkdir()
        (linked / 'result.json').symlink_to(self.evidence_root / 'real' / 'result.json')
        code, report, _ = self.verify(self.manifest([self.check_entry('linked', root, command, sha=sha)]))
        self.assertEqual(code, 1)
        self.assertEqual(report['checks'][0]['reasons'], ['receipt-symlink'])

    def test_malformed_manifest_and_receipt_are_not_echoed(self):
        manifest = self.evidence_root / 'manifest.json'
        manifest.write_text(json.dumps({'checks': [{'label': SENTINEL + ' <x>', 'cwd': '.',
                                                    'command': {}, 'resultFile': 'r'}]}))
        code, report, output = self.verify(manifest)
        self.assertEqual((code, report['reason']), (2, 'invalid-label'))
        self.assertNotIn(SENTINEL, output)
        root, sha = self.make_repo({'a': '1'})
        (self.evidence_root / 'bad').mkdir()
        (self.evidence_root / 'bad' / 'result.json').write_text(SENTINEL + '{not json')
        code, report, output = self.verify(self.manifest([self.check_entry('bad', root, ['true'], sha=sha)]))
        self.assertEqual(report['checks'][0]['reasons'], ['receipt-unparseable'])
        self.assertNotIn(SENTINEL, output)
        proc = subprocess.run([sys.executable, str(EVIDENCE), 'run', '--label', SENTINEL],
                              env=self.env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn(SENTINEL, proc.stdout + proc.stderr)

    # -- process lifetime

    def test_timeout_terminates_run_group(self):
        root, sha = self.make_repo({'a': '1'})
        started = time.monotonic()
        code, receipt, _ = self.run_evidence(root, 'timeout', ['sleep', '30'], sha=sha, timeout=1)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(code, 1)
        child = receipt['child']
        self.assertTrue(child['timedOut'])
        self.assertEqual(child['signalsSent'][0], 'SIGTERM')
        self.assertEqual(child['signal'], 'SIGTERM')
        self.assertTrue(child['groupEmptyAtReceipt'])
        self.assertIn('timed-out', receipt['gate']['reasons'])

    def test_timeout_escalates_to_sigkill_when_term_ignored(self):
        root, sha = self.make_repo({'a': '1'})
        command = ['sh', '-c', 'trap "" TERM; sleep 30']
        code, receipt, _ = self.run_evidence(root, 'stubborn', command, sha=sha, timeout=1)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['child']['signalsSent'], ['SIGTERM', 'SIGKILL'])
        self.assertEqual(receipt['child']['signal'], 'SIGKILL')
        self.assertTrue(receipt['child']['groupEmptyAtReceipt'])

    def test_owned_descendant_outliving_leader_prevents_pass(self):
        root, sha = self.make_repo({'a': '1'})
        code, receipt, out = self.run_evidence(
            root, 'descendant', ['sh', '-c', 'sleep 30 & echo "$!"'], sha=sha, timeout=1.5)
        self.assertEqual(code, 1)
        child = receipt['child']
        self.assertEqual(child['exitCode'], 0)
        self.assertTrue(child['descendantsObservedAfterExit'])
        self.assertTrue(child['descendantsOutlivedDeadline'])
        self.assertTrue(child['groupEmptyAtReceipt'])
        self.assertIn('descendants-alive', receipt['gate']['reasons'])
        descendant = int((out / 'stdout.log').read_text().split()[0])
        with self.assertRaises(ProcessLookupError):
            os.kill(descendant, 0)

    def test_short_lived_descendant_is_awaited(self):
        root, sha = self.make_repo({'a': '1'})
        command = ['sh', '-c', '(sleep 0.3; echo late) & echo early']
        code, receipt, out = self.run_evidence(root, 'awaited', command, sha=sha, timeout=10)
        self.assertEqual(code, 0, receipt['gate'])
        self.assertTrue(receipt['child']['descendantsObservedAfterExit'])
        self.assertEqual((out / 'stdout.log').read_text().split(), ['early', 'late'])


class RepoContextTests(Sandbox):
    def discover(self, cwd: Path, env: dict | None = None) -> dict:
        proc = subprocess.run([sys.executable, str(REPO_CONTEXT), '--cwd', str(cwd)],
                              env=env or self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def trap_path(self) -> tuple[dict, Path]:
        """PATH whose package-manager/toolchain shims record any invocation."""
        bin_dir = self.tmp / 'trap-bin'
        bin_dir.mkdir()
        marker = self.tmp / 'executed'
        for tool in ('npm', 'pnpm', 'yarn', 'go', 'make', 'tox', 'nox', 'pytest'):
            shim = bin_dir / tool
            shim.write_text(f'#!/bin/sh\necho "{tool}" >> "{marker}"\n')
            shim.chmod(0o755)
        return dict(self.env, PATH=f'{bin_dir}{os.pathsep}{self.env["PATH"]}'), marker

    def mixed_repo(self) -> tuple[Path, str]:
        touch = 'touch SCRIPT_RAN'
        return self.make_repo({
            'AGENTS.md': 'Use the documented commands.\n',
            'package.json': json.dumps({'name': 'web', 'packageManager': 'pnpm@9.1.0',
                                        'engines': {'node': '>=20'},
                                        'scripts': {'test': touch, 'build': touch}}),
            'pnpm-lock.yaml': 'lockfileVersion: 9\n',
            'tools/package.json': json.dumps({'name': 'tools', 'scripts': {'test:unit': touch}}),
            'tools/package-lock.json': '{}',
            'pyproject.toml': '[project]\nname = "svc"\nrequires-python = ">=3.11"\n'
                              '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
            'tests/test_x.py': 'def test_x():\n    assert True\n',
            'services/worker/go.mod': 'module example.invalid/worker\n\ngo 1.22\n',
            'services/worker/main.go': 'package main\n\nfunc main() {}\n',
            'services/worker/main_test.go': 'package main\n',
            'services/worker/AGENTS.md': 'Worker notes.\n',
            'Makefile': 'test:\n\ttouch MAKE_RAN\n',
            '.github/workflows/ci.yml': 'name: ci\n',
        })

    def test_mixed_repo_discovery(self):
        root, sha = self.mixed_repo()
        report = self.discover(root)
        self.assertEqual(report['source']['kind'], 'git')
        self.assertEqual(report['source']['head'], sha)
        self.assertFalse(report['source']['dirty'])
        self.assertIsNone(report['source']['defaultBranch'])
        self.assertEqual(report['languages'], ['go', 'node', 'python'])
        self.assertTrue(report['mixed'])
        nodes = {n['manifest']: n for n in report['ecosystems']['node']}
        self.assertEqual(nodes['package.json']['packageManager'], 'pnpm@9.1.0')
        self.assertIsNone(nodes['tools/package.json']['packageManager'])
        self.assertEqual(nodes['tools/package.json']['lockfiles'], ['package-lock.json'])
        candidates = {c['basis']: c for c in report['commandCandidates']}
        self.assertEqual(candidates['package.json scripts.test']['argv'], ['pnpm', 'run', 'test'])
        blocked = candidates['package.json scripts.test:unit']
        self.assertIsNone(blocked['argv'])
        self.assertEqual(blocked['blockedBy'], 'package-manager-not-declared')
        self.assertEqual(candidates['go.mod with _test.go files'],
                         {'cwd': 'services/worker', 'argv': ['go', 'test', './...'],
                          'basis': 'go.mod with _test.go files', 'blockedBy': None,
                          'executed': False})
        self.assertIn('pytest configuration declared', candidates)
        self.assertTrue(all(c['executed'] is False for c in report['commandCandidates']))
        go = report['ecosystems']['go'][0]
        self.assertEqual((go['module'], go['toolchain']), ('example.invalid/worker', {'go': '1.22'}))
        self.assertEqual(report['ci']['files'], ['.github/workflows/ci.yml'])
        self.assertIsNone(report['ci']['gates'])
        self.assertIn('package-manager-not-declared', {u['reason'] for u in report['unknowns']})

    def test_candidates_are_never_executed_and_discovery_is_read_only(self):
        root, _ = self.mixed_repo()
        env, marker = self.trap_path()
        before = self.git(root, 'status', '--porcelain', '--ignored')
        self.discover(root, env)
        self.assertFalse(marker.exists())
        self.assertFalse((root / 'SCRIPT_RAN').exists())
        self.assertFalse((root / 'MAKE_RAN').exists())
        self.assertEqual(self.git(root, 'status', '--porcelain', '--ignored'), before)

    def test_nested_cwd_reports_owning_root_and_instruction_scopes(self):
        root, _ = self.mixed_repo()
        (root / 'services' / 'worker' / 'scratch.txt').write_text('dirty')
        report = self.discover(root / 'services' / 'worker')
        self.assertEqual(report['source']['gitRoot'], str(root))
        self.assertTrue(report['source']['dirty'])
        self.assertEqual(report['source']['untrackedFiles'], 1)
        scopes = {i['path']: i['scope'] for i in report['instructions']}
        self.assertEqual(scopes['AGENTS.md'], 'ancestor-or-cwd')
        self.assertEqual(scopes['services/worker/AGENTS.md'], 'ancestor-or-cwd')
        self.assertTrue(any('uncommitted' in step for step in report['executionStillNeeded']))

    def test_malformed_declarations_are_explicit_unknowns_without_echo(self):
        root, _ = self.make_repo({
            'package.json': '{"name": "' + SENTINEL + '", broken',
            'pyproject.toml': '[project\nname = "' + SENTINEL + '"\n',
            'mod/go.mod': '// ' + SENTINEL + '\ngo 1.22\n',
            'web/package.json': json.dumps({'packageManager': SENTINEL + ' ; rm -rf x',
                                            'scripts': {'test': 'x'}}),
        })
        proc = subprocess.run([sys.executable, str(REPO_CONTEXT), '--cwd', str(root)],
                              env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn(SENTINEL, proc.stdout + proc.stderr)
        unknowns = {(u['path'], u['reason']) for u in json.loads(proc.stdout)['unknowns']}
        self.assertIn(('package.json', 'invalid-json'), unknowns)
        self.assertIn(('pyproject.toml', 'invalid-toml'), unknowns)
        self.assertIn(('mod/go.mod', 'invalid-go-mod'), unknowns)
        self.assertIn(('web/package.json', 'invalid-packageManager'), unknowns)

    def test_archive_tree_is_explicitly_unversioned(self):
        tree = self.tmp / 'unpacked'
        (tree / 'src').mkdir(parents=True)
        (tree / 'go.mod').write_text('module example.invalid/tool\n\ngo 1.21\n')
        (tree / 'src' / 'x_test.go').write_text('package src\n')
        report = self.discover(tree)
        self.assertEqual(report['source']['kind'], 'archive-or-unversioned')
        self.assertIsNone(report['source']['head'])
        self.assertEqual(report['languages'], ['go'])
        self.assertTrue(any('source description' in s for s in report['executionStillNeeded']))

    def test_symlinked_manifest_is_not_followed(self):
        outside = self.tmp / 'outside.json'
        outside.write_text(json.dumps({'name': SENTINEL}))
        root, _ = self.make_repo({'README.md': 'x\n'})
        (root / 'package.json').symlink_to(outside)
        report = self.discover(root)
        self.assertIn({'path': 'package.json', 'reason': 'symlink-not-followed'}, report['unknowns'])
        self.assertNotIn(SENTINEL, json.dumps(report))


if __name__ == '__main__':
    unittest.main()
