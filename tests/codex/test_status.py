"""framework-status is read-only: it classifies states and never mutates the targets.

Disposable project/home directories are resolved so the macOS /var symlink does not
trip the Codex checker's symlink-root guard. Every assertion that proves the command
touches nothing compares a full before/after tree (files and directories, so a stray
lock or created directory would be caught)."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'codex'))
import framework

STATUS_SCRIPT = ROOT / 'scripts/framework-status.py'


def load_status():
    spec = importlib.util.spec_from_file_location('framework_status', STATUS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_delivery_module():
    spec = importlib.util.spec_from_file_location('install_delivery', ROOT / 'scripts/install-delivery.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob('*'))}


class StatusBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='codex-status-')
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / 'project'
        self.home = self.base / 'claude-home'
        self.project.mkdir()
        self.home.mkdir()
        self.status = load_status()

    def tearDown(self):
        self.tmp.cleanup()

    def collect(self, **kwargs):
        params = dict(user=False, project=self.project, claude_home=self.home)
        params.update(kwargs)
        return self.status.collect(**params)

    def integration(self, report, name):
        return next(item for item in report['integrations'] if item['integration'] == name)

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(STATUS_SCRIPT), *args],
                              capture_output=True, text=True, env=env, timeout=120)


class ClassifiesStates(StatusBase):
    def test_not_installed_is_reported_and_exits_zero(self):
        report = self.collect()
        self.assertEqual(self.integration(report, 'codex')['state'], 'not_installed')
        self.assertEqual(self.integration(report, 'claude_delivery')['state'], 'not_installed')
        self.assertFalse(self.integration(report, 'claude_framework')['present'])
        self.assertEqual(self.status.exit_code(report), 0)

    def test_clean_codex_install_is_clean_and_untouched(self):
        framework.install(self.project, hooks=True)
        before = tree(self.project)
        report = self.collect()
        codex = self.integration(report, 'codex')
        self.assertEqual(codex['state'], 'clean')
        self.assertTrue(codex['hooks_configured'])
        self.assertEqual(codex['hook_trust'], 'UNKNOWN')
        self.assertEqual(codex['installed_source_sha'], self.status.repository_sha())
        self.assertEqual(self.status.exit_code(report), 0)
        self.assertEqual(tree(self.project), before)  # read-only: no lock, no writes

    def test_drift_detected_without_mutation(self):
        framework.install(self.project)
        before = tree(self.project)
        real_build = framework.build

        def changed():
            files = real_build()
            files['.codex/agents/api-backend.toml'] += b'# source advanced\n'
            return files

        with patch.object(framework, 'build', changed):
            report = self.collect()
        self.assertEqual(self.integration(report, 'codex')['state'], 'drift')
        self.assertEqual(self.status.exit_code(report), 1)
        self.assertEqual(tree(self.project), before)

    def test_tampered_owned_file_is_error(self):
        framework.install(self.project)
        target = self.project / '.codex/agents/api-backend.toml'
        target.write_bytes(target.read_bytes() + b'# owner tamper\n')
        before = tree(self.project)
        report = self.collect()
        self.assertEqual(self.integration(report, 'codex')['state'], 'error')
        self.assertEqual(self.status.exit_code(report), 2)
        self.assertEqual(tree(self.project), before)

    def test_corrupt_manifest_is_error(self):
        framework.install(self.project)
        (self.project / '.codex/framework/manifest.json').write_text('{not valid')
        report = self.collect()
        self.assertEqual(self.integration(report, 'codex')['state'], 'error')


class ClaudeTargets(StatusBase):
    def test_delivery_clean_and_framework_marker_read(self):
        delivery = install_delivery_module()
        delivery.run(self.home, ROOT)
        (self.home / '.framework-version').write_text(
            'version=3.2.0\nsha=abcdef1\nahead=0\ninstalled_at=2026-10-17T00:00:00Z\n')
        before = tree(self.home)
        report = self.collect()
        deliv = self.integration(report, 'claude_delivery')
        marker = self.integration(report, 'claude_framework')
        self.assertEqual(deliv['state'], 'clean')
        self.assertEqual(marker['version'], '3.2.0')
        self.assertEqual(marker['installed_source_sha'], 'abcdef1')
        self.assertEqual(marker['integrity'], 'not_checked')
        self.assertEqual(tree(self.home), before)

    def test_symlink_framework_marker_not_followed(self):
        secret = self.base / 'secret'
        secret.write_text('version=leak\n')
        (self.home / '.framework-version').symlink_to(secret)
        marker = self.integration(self.collect(), 'claude_framework')
        self.assertFalse(marker['present'])


class CliContract(StatusBase):
    def test_json_shape_and_mcp_unknown(self):
        result = self.run_cli('--json', '--project', str(self.project), '--claude-home', str(self.home))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['mcp']['connectivity'], 'UNKNOWN')
        self.assertEqual(set(report['native_cli']), {'codex', 'claude'})
        self.assertTrue(all(isinstance(v, bool) for v in report['native_cli'].values()))
        self.assertIsInstance(report['repository']['sha'], str)

    def test_default_user_scope_is_read_only_against_disposable_home(self):
        fake_home = self.base / 'user-home'
        fake_home.mkdir()
        env = dict(os.environ, HOME=str(fake_home), CODEX_HOME=str(fake_home / '.codex'))
        before = tree(fake_home)
        result = self.run_cli('--claude-home', str(self.home), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('codex: not_installed', result.stdout)
        self.assertEqual(tree(fake_home), before)

    def test_drift_exit_code_one_via_cli(self):
        framework.install(self.project)
        # A missing owned file leaves a pending restore the checker reports as drift.
        (self.project / '.agents/skills/sdlc-tdd/SKILL.md').unlink()
        result = self.run_cli('--project', str(self.project), '--claude-home', str(self.home))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('codex: drift', result.stdout)


if __name__ == '__main__':
    unittest.main()
