"""Source-checkout entry point ./framework: dispatch, read-only status, exit codes and packaging.

Every case runs in a disposable home and working folder. Where a specific comparison result is
needed, the source checker is replaced by a miniature module outside the repository; one case
runs the real checker read-only. Nothing contacts a provider or touches the real home.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


control = load('framework_control_under_test', ROOT / 'scripts/framework_control.py')
settings = load('framework_settings_for_control', ROOT / '.claude/lib/framework_settings.py')

PRIVATE_REGISTRY = b'{"projects": ["/sentinel-owner-private-registry-entry"]}'
CHECKER = '''
def collect(*, user, project, claude_home):
    if {fail!r}:
        raise RuntimeError('checker exploded')
    return {{'repository': {{'root': 'source', 'sha': 'f' * 40}},
             'integrations': [{{'integration': 'codex', 'scope': 'user', 'state': {state!r}}},
                              {{'integration': 'claude_framework', 'present': False}}],
             'native_cli': {{}}, 'mcp': {{}}}}


def exit_code(report):
    return {code!r}
'''
UPDATER = '''
import json
import sys


def main(argv=None):
    sys.stdout.write(json.dumps(argv))
    return 3
'''


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fw-control-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir(mode=0o755)
        self.home.chmod(0o755)
        self.tools = self.root / 'tools'
        self.tools.mkdir()
        self.work = self.root / 'work'
        self.work.mkdir()
        environment = patch.dict(os.environ, {'HOME': str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        for name in ('CI', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME'):
            os.environ.pop(name, None)
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)

    def checker(self, *, state='clean', code=0, fail=False) -> None:
        path = self.tools / f'checker-{state}-{code}-{fail}.py'
        path.write_text(CHECKER.format(state=state, code=code, fail=fail))
        patcher = patch.object(control, 'SOURCE_CHECKER', path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = control.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def snapshot(self) -> dict:
        result = {}
        for directory, dirs, files in os.walk(self.root):
            for name in dirs + files:
                path = Path(directory, name)
                info = os.lstat(path)
                if stat.S_ISLNK(info.st_mode):
                    value = ('link', os.readlink(path))
                elif stat.S_ISDIR(info.st_mode):
                    value = ('dir', stat.S_IMODE(info.st_mode))
                else:
                    value = ('file', stat.S_IMODE(info.st_mode), path.read_bytes())
                result[str(path.relative_to(self.root))] = value
        return result

    def write(self, path: Path, data: bytes) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def codex_record(self, files: dict, instructions: str) -> None:
        record = {'version': 1, 'files': files, 'user': True, 'hooks': False, 'instructions': instructions}
        self.write(self.home / '.codex/framework/manifest.json', json.dumps(record).encode())

    def malicious_codex_install(self) -> None:
        """A Codex record that lists the owner-private lint approval list as if it were install-owned."""
        checksum = self.write(self.home / '.codex/framework/lint-projects.json', PRIVATE_REGISTRY)
        self.codex_record({'.codex/framework/lint-projects.json': checksum}, '0' * 64)

    def malicious_delivery_install(self) -> None:
        record = {'version': 1, 'files': {'settings.json': '0' * 64}}
        self.write(self.home / '.claude/.sdlc-delivery/manifest.json', json.dumps(record).encode())

    def broad_claude_install(self) -> None:
        self.write(self.home / '.claude/.framework-version', b'version=1.0.0\nsha=abc1234\n')

    def ready_codex_install(self) -> None:
        block = f'{settings.INSTRUCTION_BEGIN}\nmanaged\n{settings.INSTRUCTION_END}\n'.encode()
        self.write(self.home / '.codex/AGENTS.md', b'personal notes\n' + block)
        checksum = self.write(self.home / '.codex/framework/rules.md', b'rules\n')
        self.codex_record({'.codex/framework/rules.md': checksum}, hashlib.sha256(block).hexdigest())

    def reset_installs(self) -> None:
        for name in ('.codex', '.claude'):
            shutil.rmtree(self.home / name, ignore_errors=True)

    @contextlib.contextmanager
    def opens_of(self, name: str):
        """Record every open of a path ending in `name` through os.open, io.open or builtins.open."""
        seen: list[str] = []

        def spy(real):
            def opener(file, *args, **kwargs):
                if isinstance(file, (str, bytes, os.PathLike)) and os.fsdecode(file).endswith(name):
                    seen.append(os.fsdecode(file))
                return real(file, *args, **kwargs)
            return opener

        with patch('os.open', spy(os.open)), patch('io.open', spy(io.open)), patch('builtins.open', spy(open)):
            yield seen

    def comparator_spy(self):
        return patch.object(control, 'compare_with_checkout', wraps=control.compare_with_checkout)


def component(payload: dict, component_id: str) -> dict:
    return next(item for item in payload['installed']['components'] if item['id'] == component_id)


class Status(Base):
    def test_combined_status_writes_nothing_and_reports_drift_as_1(self):
        self.checker(state='drift', code=1)
        before = self.snapshot()
        code, out, _ = self.run_main('status', '--json')
        payload = json.loads(out)
        self.assertEqual((code, payload['exit_code']), (1, 1))
        self.assertEqual(payload['schema'], 'sdlc-framework-control/v1')
        self.assertEqual(payload['installed']['headline']['state'], 'not_installed')
        self.assertEqual(payload['installed']['invocation'], './framework')
        self.assertEqual(payload['installed']['source']['comparison'], 'this_checkout')
        self.assertEqual(payload['source_comparison']['state'], 'completed')
        code, text, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('Codex files (user): differs from this checkout', text)
        self.assertIn('Claude framework files: not installed', text)
        self.assertIn('./framework update --help', text)
        self.assertIn('More: ./framework status --detail full', text)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.home / '.config').exists())

    def test_exit_codes_keep_their_meaning(self):
        cases = {'clean': ({'state': 'clean', 'code': 0}, 0), 'error': ({'state': 'error', 'code': 2}, 2),
                 'checker-failed': ({'fail': True}, 2)}
        for name, (kwargs, expected) in cases.items():
            with self.subTest(name):
                self.checker(**kwargs)
                code, out, _ = self.run_main('--json')
                self.assertEqual((code, json.loads(out)['exit_code']), (expected, expected))
        code, text, _ = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn('Compared with this checkout: not completed', text)
        self.assertIn('checker exploded', text)
        with patch.object(control, 'SOURCE_CHECKER', self.tools / 'absent.py'):
            code, out, _ = self.run_main('--json')
        self.assertEqual((code, json.loads(out)['source_comparison']['state']), (2, 'incomplete'))

    def test_installed_attention_is_1_even_when_the_comparison_is_clean(self):
        self.checker()
        prefs = self.home / '.config/sdlc/framework-preferences.json'
        prefs.parent.mkdir(parents=True)
        (self.home / '.config').chmod(0o700)
        prefs.parent.chmod(0o700)
        prefs.write_text(json.dumps(settings.default_preferences()))
        prefs.chmod(0o644)
        data = prefs.read_bytes()
        code, out, _ = self.run_main('--json')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)['installed']['headline']['state'], 'needs_attention')
        self.assertEqual(prefs.read_bytes(), data)

    def test_source_option_and_unknown_options_are_usage_errors(self):
        self.checker()
        before = self.snapshot()
        self.assertEqual(self.run_main('status', '--source', str(self.root))[0], 2)
        self.assertEqual(self.run_main('--no-such-option')[0], 2)
        self.assertEqual(self.snapshot(), before)

    def test_real_checker_runs_read_only(self):
        if not shutil.which('git'):
            self.skipTest('git not available')
        caches = [ROOT / rel / '__pycache__' for rel in ('scripts', 'codex', '.claude/lib')]
        existed = {path: path.exists() for path in caches}
        before = self.snapshot()
        code, out, _ = self.run_main('--json')
        payload = json.loads(out)
        comparison = payload['source_comparison']
        self.assertEqual(comparison['state'], 'completed', comparison.get('detail'))
        states = {item['state'] for item in comparison['report']['integrations'] if 'state' in item}
        self.assertEqual(states, {'not_installed'})
        self.assertEqual(code, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({path: path.exists() for path in caches}, existed)


class ComparisonGuard(Base):
    def test_untrusted_codex_record_skips_the_source_comparison_and_never_opens_the_private_list(self):
        self.malicious_codex_install()  # the real source checker stays configured
        before = self.snapshot()
        with self.opens_of('lint-projects.json') as seen, self.comparator_spy() as comparator:
            code, out, _ = self.run_main('status', '--json')
            text_code, text, _ = self.run_main()
        comparator.assert_not_called()
        self.assertEqual(seen, [])
        payload = json.loads(out)
        self.assertEqual((code, payload['exit_code'], text_code), (2, 2, 2))
        comparison = payload['source_comparison']
        self.assertEqual((comparison['state'], comparison['exit'], comparison['blocked_by']),
                         ('incomplete', 2, ['codex']))
        self.assertNotIn('report', comparison)
        self.assertEqual(payload['installed']['headline']['state'], 'needs_attention')
        codex = component(payload, 'codex')
        self.assertEqual(codex['state'], 'needs_attention')
        self.assertIn('lint-projects.json', codex['summary'])
        self.assertIn('install record refused', text)
        self.assertIn('Compared with this checkout: not completed', text)
        self.assertIn('before they can be compared with this checkout', text)
        self.assertNotIn('sentinel-owner-private-registry-entry', out + text)
        self.assertEqual(self.snapshot(), before)

    def test_only_manifest_backed_attention_skips_the_comparison(self):
        cases = {
            'codex needs attention': (self.malicious_codex_install, 'codex', None),
            'delivery needs attention': (self.malicious_delivery_install, 'claude_delivery', None),
            'broad claude not checked': (self.broad_claude_install, 'claude_framework', 'not_checked'),
            'codex ready': (self.ready_codex_install, 'codex', 'ready'),
            'nothing installed': (lambda: None, 'codex', 'not_installed'),
        }
        self.checker()
        for name, (install, component_id, compared_state) in cases.items():
            with self.subTest(name):
                self.reset_installs()
                install()
                with self.comparator_spy() as comparator:
                    code, out, _ = self.run_main('--json')
                payload = json.loads(out)
                comparison = payload['source_comparison']
                if compared_state is None:
                    comparator.assert_not_called()
                    self.assertEqual(component(payload, component_id)['state'], 'needs_attention')
                    self.assertEqual((code, comparison['state'], comparison['blocked_by']),
                                     (2, 'incomplete', [component_id]))
                    continue
                comparator.assert_called_once()
                self.assertEqual(component(payload, component_id)['state'], compared_state)
                self.assertEqual((code, comparison['state']), (0, 'completed'))


class Dispatch(Base):
    def test_settings_saves_only_on_an_explicit_action(self):
        code, out, _ = self.run_main('settings')
        self.assertEqual(code, 0)
        self.assertIn('./framework settings --set-detail', out)
        self.assertFalse((self.home / '.config').exists())
        code, _, _ = self.run_main('settings', '--set-detail', 'full')
        self.assertEqual(code, 0)
        prefs = self.home / '.config/sdlc/framework-preferences.json'
        self.assertEqual(stat.S_IMODE(prefs.stat().st_mode), 0o600)
        self.assertEqual(json.loads(prefs.read_bytes())['display']['detail'], 'full')

    def test_update_is_dispatched_lazily_with_raw_arguments(self):
        fake = self.tools / 'updater.py'
        fake.write_text(UPDATER)
        broken = self.tools / 'broken.py'
        broken.write_text('raise RuntimeError("imported")\n')
        self.checker()
        with patch.object(control, 'UPDATER', broken):
            self.assertEqual(self.run_main('status', '--json')[0], 0)
            self.assertEqual(self.run_main('settings')[0], 0)
        with patch.object(control, 'UPDATER', fake):
            code, out, _ = self.run_main('update', 'plan', '--json', '--unknown=value')
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out), ['plan', '--json', '--unknown=value'])

    def test_missing_updater_changes_nothing(self):
        before = self.snapshot()
        with patch.object(control, 'UPDATER', self.tools / 'absent.py'):
            code, _, err = self.run_main('update', 'apply')
        self.assertEqual(code, 2)
        self.assertIn('nothing was changed', err)
        self.assertEqual(self.snapshot(), before)

    def test_help_names_every_command_and_runs_nothing(self):
        before = self.snapshot()
        for flag in ('--help', '-h'):
            with self.subTest(flag):
                code, out, _ = self.run_main(flag)
                self.assertEqual(code, 0)
                for text in ('status', 'settings', 'update', 'python3 ~/.claude/lib/framework_settings.py',
                             'python3 ~/.codex/framework/settings.py'):
                    self.assertIn(text, out)
        self.assertEqual(self.snapshot(), before)

    def test_root_launcher_loads_the_control_module(self):
        result = subprocess.run([sys.executable, str(ROOT / 'framework'), '--help'], capture_output=True,
                                text=True, cwd=self.work, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: ./framework', result.stdout)


class Packaging(unittest.TestCase):
    def test_codex_build_ships_identical_helper_bytes_inside_the_owned_allowlist(self):
        framework = load('codex_framework_for_control', ROOT / 'codex/framework.py')
        files = framework.build()
        self.assertEqual(files['.codex/framework/settings.py'],
                         (ROOT / '.claude/lib/framework_settings.py').read_bytes())
        shipped = {rel for rel in files if rel.startswith('.codex/framework/')}
        self.assertEqual(shipped, set(settings.CODEX_FRAMEWORK_FILES))
        self.assertTrue(all(settings.codex_allowed(rel) for rel in files))
        for private in ('.codex/framework/manifest.json', '.codex/framework/lint-projects.json',
                        '.codex/framework/sessions/events.jsonl', '.codex/config.toml'):
            self.assertFalse(settings.codex_allowed(private), private)

    def test_claude_installer_lib_list_ships_the_helper(self):
        text = (ROOT / 'install.sh').read_text()
        block = re.search(r'^LIB_FILES=\(\n(.*?)^\)', text, re.S | re.M)
        self.assertIsNotNone(block)
        names = re.findall(r'"([^"]+)"', block.group(1))
        self.assertIn('framework_settings.py', names)
        self.assertTrue(all((ROOT / '.claude/lib' / name).is_file() for name in names))

    def test_ci_cancels_only_superseded_pull_request_runs_and_keeps_every_gate(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/validate.yml').read_text())
        self.assertEqual(set(workflow['jobs']), {'codex-adapter', 'shell-syntax', 'validate', 'gap-tests', 'yaml-lint'})
        concurrency = workflow['concurrency']
        self.assertIn('github.event.pull_request.number', concurrency['group'])
        self.assertIn('github.sha', concurrency['group'])
        self.assertEqual(concurrency['cancel-in-progress'], "${{ github.event_name == 'pull_request' }}")


if __name__ == '__main__':
    unittest.main()
