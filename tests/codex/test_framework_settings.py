"""Framework readiness/settings helper: classification, write discipline and prompts.

Every case runs in a disposable home (HOME is patched; temporary roots are resolved so the
macOS /var symlink does not trip the helper's own symlink guards). Nothing contacts a
provider, starts a process or touches the real home.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location('framework_settings', ROOT / '.claude/lib/framework_settings.py')
fs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fs)

DELIVERY_FILES = {
    'skills/delivery/SKILL.md': b'delivery\n',
    'skills/verified-handoff/SKILL.md': b'handoff\n',
    'rules/delivery.md': b'rule\n',
    'commands/commit-pr.md': b'command\n',
}
CODEX_FILES = {
    '.agents/skills/sdlc-delivery/SKILL.md': b'skill\n',
    '.codex/agents/reviewer.toml': b'name = "reviewer"\n',
    '.codex/framework/hook.py': b'# hook\n',
}
HOOKS_FILE = b'{"hooks": {}}\n'
MANAGED_BLOCK = f'{fs.INSTRUCTION_BEGIN}\nmanaged guidance\n{fs.INSTRUCTION_END}\n'.encode()
PERSONAL_PREFIX = b'# My own notes\n\n'
PERSONAL_SUFFIX = b'\nKeep this line.\n'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TTYStream(io.StringIO):
    def isatty(self) -> bool:
        return True


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fw-settings-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir(mode=0o755)
        self.home.chmod(0o755)
        self.claude = self.home / '.claude'
        self.work = self.root / 'work'
        self.work.mkdir()
        self.prefs = self.home / '.config/sdlc/framework-preferences.json'
        environment = patch.dict(os.environ, {'HOME': str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        for name in ('CI', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME'):
            os.environ.pop(name, None)
        for target, value in ((fs.shutil, ('which', None)), (fs, ('IS_MACOS', True))):
            name, replacement = value
            patcher = (patch.object(target, name, return_value=replacement) if name == 'which'
                       else patch.object(target, name, replacement))
            patcher.start()
            self.addCleanup(patcher.stop)

    # -- fixtures --------------------------------------------------------
    def write(self, path: Path, data: bytes, mode: int = 0o644) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def private_config_dir(self) -> Path:
        directory = self.home / '.config/sdlc'
        directory.mkdir(parents=True, exist_ok=True)
        (self.home / '.config').chmod(0o700)
        directory.chmod(0o700)
        return directory

    def marker(self, *lines: str) -> None:
        self.write(self.claude / '.framework-version', ('\n'.join(lines) + '\n').encode())

    def install_delivery(self, files=None, record=None) -> None:
        files = DELIVERY_FILES if files is None else files
        for rel, data in files.items():
            self.write(self.claude / rel, data)
        owned = {rel: sha(data) for rel, data in files.items()} if record is None else record
        manifest = {'version': 1, 'source_sha': 'a' * 40, 'files': owned, 'adopted': {}, 'dirs': []}
        self.write(self.claude / '.sdlc-delivery/manifest.json', json.dumps(manifest).encode())

    def install_codex(self, root: Path, *, user=True, hooks=False, record=None, agents=None) -> None:
        """A coherent miniature install: owned files, the hook file when selected, one managed block."""
        files = {**CODEX_FILES, **({'.codex/hooks.json': HOOKS_FILE} if hooks else {})}
        for rel, data in files.items():
            self.write(root / rel, data)
        owned = {rel: sha(data) for rel, data in files.items()} if record is None else record
        instructions = PERSONAL_PREFIX + MANAGED_BLOCK + PERSONAL_SUFFIX if agents is None else agents
        self.write(root / ('.codex/AGENTS.md' if user else 'AGENTS.md'), instructions)
        manifest = {'version': 1, 'source_sha': 'b' * 40, 'files': owned, 'instructions': sha(MANAGED_BLOCK),
                    'hooks': hooks, 'user': user}
        self.write(root / '.codex/framework/manifest.json', json.dumps(manifest).encode())

    def write_prefs(self, payload, mode=0o600) -> bytes:
        self.private_config_dir()
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.write(self.prefs, data, mode)
        return data

    # -- running -----------------------------------------------------------
    def run_cli(self, *argv, interactive=False, answers=None, cwd=None):
        out, err, asked = io.StringIO(), io.StringIO(), []

        def ask(prompt):
            asked.append(prompt)
            if answers is None:
                raise AssertionError(f'unexpected prompt: {prompt}')
            return answers(prompt)

        with contextlib.redirect_stderr(io.StringIO()):
            code = fs._run(list(argv), interactive=interactive, ask=ask, out=out, err=err, cwd=cwd or self.work)
        return code, out.getvalue(), err.getvalue(), asked

    def status(self, *argv, cwd=None):
        code, out, _, _ = self.run_cli('status', '--json', *argv, cwd=cwd)
        return code, json.loads(out)

    @staticmethod
    def component(report, component_id):
        return next(item for item in report['components'] if item['id'] == component_id)

    @staticmethod
    def extra(report, feature_id):
        return next(item for item in report['extras'] if item['id'] == feature_id)

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


class StatusClassification(Base):
    def test_nothing_installed_is_not_installed_and_writes_nothing(self):
        before = self.snapshot()
        code, report = self.status()
        self.assertEqual(code, 0)
        self.assertEqual(report['headline']['state'], 'not_installed')
        self.assertEqual({item['state'] for item in report['components']}, {'not_installed'})
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.prefs.exists())

    def test_broad_claude_install_is_never_reported_ready(self):
        self.marker('version=2.0.0', 'sha=abc1234', 'analytics=disabled', 'watchdog=disabled',
                    'notifications=disabled')
        self.install_delivery()
        code, report = self.status()
        self.assertEqual(code, 0)
        self.assertEqual(self.component(report, 'claude_framework')['state'], 'not_checked')
        self.assertEqual(self.component(report, 'claude_delivery')['state'], 'ready')
        self.assertEqual(report['headline']['state'], 'not_checked')
        self.assertEqual(report['headline']['label'], 'Installed - not fully checked')

    def test_verified_delivery_alone_is_ready_but_not_compared_with_source(self):
        self.install_delivery()
        code, report = self.status()
        delivery = self.component(report, 'claude_delivery')
        self.assertEqual((code, report['headline']['state']), (0, 'ready'))
        self.assertEqual(delivery['check'], 'installed-manifest')
        self.assertEqual(delivery['source_comparison'], 'not_checked')
        self.assertEqual(delivery['owned_files'], len(DELIVERY_FILES))
        self.assertEqual(report['source']['comparison'], 'not_checked')

    def test_tampered_and_missing_owned_files_need_attention(self):
        self.install_delivery()
        (self.claude / 'rules/delivery.md').write_bytes(b'edited\n')
        (self.claude / 'commands/commit-pr.md').unlink()
        code, report = self.status()
        delivery = self.component(report, 'claude_delivery')
        self.assertEqual(code, 1)
        self.assertEqual(delivery['state'], 'needs_attention')
        self.assertIn('rules/delivery.md: changed since install', delivery['problems'])
        self.assertIn('commands/commit-pr.md: missing', delivery['problems'])
        code, text, _, _ = self.run_cli('status')
        self.assertEqual(code, 1)
        self.assertTrue(text.startswith('Needs attention'))
        self.assertIn('rules/delivery.md', text)

    def test_namespace_escape_refuses_the_whole_record(self):
        outside = self.write(self.home / 'outside.txt', b'outside\n')
        settings = self.write(self.claude / 'settings.json', b'{}\n')
        cases = {'traversal': '../outside.txt', 'native-config': 'settings.json', 'absolute': str(outside)}
        for name, rel in cases.items():
            with self.subTest(name):
                data = outside.read_bytes() if rel != 'settings.json' else settings.read_bytes()
                record = {**{key: sha(value) for key, value in DELIVERY_FILES.items()}, rel: sha(data)}
                self.install_delivery(record=record)
                _, report = self.status()
                delivery = self.component(report, 'claude_delivery')
                self.assertEqual(delivery['state'], 'needs_attention')
                self.assertIn('outside the managed files', delivery['summary'])
                self.assertEqual(delivery['problems'], [])
        codex_record = {**{rel: sha(data) for rel, data in CODEX_FILES.items()}, '.codex/config.toml': 'd' * 64}
        self.install_codex(self.home, record=codex_record)
        _, report = self.status()
        self.assertIn('outside the managed files', self.component(report, 'codex')['summary'])

    def test_symlinked_owned_file_and_parent_are_refused(self):
        self.install_delivery()
        target = self.claude / 'rules/delivery.md'
        real = self.write(self.root / 'real.md', DELIVERY_FILES['rules/delivery.md'])
        target.unlink()
        target.symlink_to(real)
        _, report = self.status()
        problems = self.component(report, 'claude_delivery')['problems']
        self.assertTrue(any(item.startswith('rules/delivery.md') and 'symlink' in item for item in problems))
        target.unlink()
        self.write(target, DELIVERY_FILES['rules/delivery.md'])
        skill_dir = self.claude / 'skills/delivery'
        moved = self.root / 'moved-skill'
        skill_dir.rename(moved)
        skill_dir.symlink_to(moved, target_is_directory=True)
        _, report = self.status()
        problems = self.component(report, 'claude_delivery')['problems']
        self.assertTrue(any(item.startswith('skills/delivery/SKILL.md') and 'symlink' in item for item in problems))

    def test_codex_scope_is_preserved(self):
        project = self.work / 'project'
        self.install_codex(project, user=True)
        code, report = self.status('--project', str(project))
        codex = self.component(report, 'codex')
        self.assertEqual((code, codex['state'], codex['scope']), (1, 'needs_attention', 'project'))
        self.assertIn('user install', codex['summary'])
        self.install_codex(project, user=False)
        _, report = self.status('--project', str(project))
        self.assertEqual(self.component(report, 'codex')['state'], 'ready')
        _, report = self.status()
        codex = self.component(report, 'codex')
        self.assertEqual((codex['scope'], codex['state']), ('user', 'not_installed'))

    def test_codex_hooks_installed_never_claims_trust(self):
        self.install_codex(self.home, hooks=True)
        _, report = self.status()
        self.assertEqual(self.component(report, 'codex')['state'], 'ready')
        hooks = self.extra(report, 'codex.hooks')
        self.assertEqual(hooks['state'], 'on')
        self.assertIn('/hooks', hooks['detail'])
        self.assertIn('not checked', hooks['detail'])

    def test_install_selections_are_tri_state(self):
        self.marker('version=2.0.0', 'analytics=enabled', 'watchdog=disabled')
        _, report = self.status()
        states = {fid: self.extra(report, fid)['state']
                  for fid in ('claude.analytics', 'claude.watchdog', 'claude.notifications', 'claude.post_edit_lint')}
        self.assertEqual(states, {'claude.analytics': 'on', 'claude.watchdog': 'off',
                                  'claude.notifications': 'unknown', 'claude.post_edit_lint': 'core'})
        self.marker('analytics=enabled', 'analytics=disabled', 'watchdog=yes', 'notifications=disabled')
        _, report = self.status()
        self.assertEqual(self.extra(report, 'claude.analytics')['state'], 'unknown')
        self.assertEqual(self.extra(report, 'claude.watchdog')['state'], 'unknown')
        self.assertEqual(self.extra(report, 'claude.notifications')['state'], 'off')

    def test_watchdog_selected_off_macos_is_unavailable(self):
        self.marker('watchdog=enabled')
        with patch.object(fs, 'IS_MACOS', False):
            _, report = self.status()
        self.assertEqual(self.extra(report, 'claude.watchdog')['state'], 'unavailable')

    def test_host_only_items_are_never_passed(self):
        self.marker('version=2.0.0')
        self.install_delivery()
        self.install_codex(self.home, hooks=True)
        with patch.object(fs.shutil, 'which', return_value='/usr/local/bin/tool'):
            _, report = self.status()
            _, text, _, _ = self.run_cli('status')
        self.assertTrue(report['native_cli']['claude'] and report['native_cli']['codex'])
        self.assertEqual({item['state'] for item in report['host_only']}, {'unknown'})
        self.assertEqual({item['id'] for item in report['host_only']}, {'ai_login', 'model_execution', 'mcp', 'footer'})
        self.assertIn('Not checked here: AI sign-in', text)

    def test_model_policy_reports_only_activation(self):
        directory = self.private_config_dir()
        _, report = self.status()
        self.assertEqual(self.extra(report, 'model_policy')['state'], 'off')
        policy = directory / 'model-policy.json'
        body = {'version': 1, 'active': True, 'bindings': {'a': {'model': 'owner-secret-model'}}}
        self.write(policy, json.dumps(body).encode(), 0o600)
        before = self.snapshot()
        code, report = self.status()
        _, text, _, _ = self.run_cli('status', '--detail', 'full')
        self.assertEqual((code, self.extra(report, 'model_policy')['state']), (0, 'not_checked'))
        self.assertTrue(self.extra(report, 'model_policy')['configured_active'])
        self.assertNotIn('owner-secret-model', json.dumps(report) + text)
        self.assertEqual(self.snapshot(), before)
        cases = {'inactive': (json.dumps({'version': 1, 'active': False}).encode(), 0o600, 'off'),
                 'bool-version': (json.dumps({'version': True, 'active': True}).encode(), 0o600, 'needs_attention'),
                 'shared-mode': (json.dumps({'version': 1, 'active': True}).encode(), 0o644, 'needs_attention'),
                 'not-json': (b'{', 0o600, 'needs_attention')}
        for name, (data, mode, expected) in cases.items():
            with self.subTest(name):
                self.write(policy, data, mode)
                code, report = self.status()
                self.assertEqual(self.extra(report, 'model_policy')['state'], expected)
                self.assertEqual(code, 1 if expected == 'needs_attention' else 0)
        policy.unlink()
        real = self.write(self.root / 'policy.json', json.dumps({'version': 1, 'active': True}).encode(), 0o600)
        policy.symlink_to(real)
        _, report = self.status()
        self.assertEqual(self.extra(report, 'model_policy')['state'], 'needs_attention')

    def test_lint_registry_presence_only(self):
        self.install_codex(self.home, hooks=True)
        registry = self.home / '.codex/framework/lint-projects.json'
        _, report = self.status()
        self.assertEqual(self.extra(report, 'codex.approved_lint')['state'], 'off')
        self.write(registry, b'{"version": 1, "projects": []}', 0o600)
        _, report = self.status()
        self.assertEqual(self.extra(report, 'codex.approved_lint')['state'], 'not_checked')
        self.assertTrue(self.extra(report, 'codex.approved_lint')['registry_present'])
        self.assertEqual(self.component(report, 'codex')['state'], 'ready')
        self.install_codex(self.home, hooks=False)
        _, report = self.status()
        self.assertEqual(self.extra(report, 'codex.approved_lint')['state'], 'needs_setup')
        registry.chmod(0o666)
        _, report = self.status()
        self.assertEqual(self.extra(report, 'codex.approved_lint')['state'], 'needs_attention')
        registry.unlink()
        registry.symlink_to(self.write(self.root / 'registry.json', b'{}', 0o600))
        _, report = self.status()
        self.assertEqual(self.extra(report, 'codex.approved_lint')['state'], 'needs_attention')

    def test_controller_binding_presence(self):
        repo = self.work / 'repo'
        (repo / '.git').mkdir(parents=True)
        _, report = self.status(cwd=repo)
        self.assertEqual(self.extra(report, 'controller')['state'], 'off')
        self.write(repo / '.git/sdlc-controller.binding', b'opaque\n')
        _, report = self.status(cwd=repo)
        controller = self.extra(report, 'controller')
        self.assertEqual((controller['state'], controller['binding_present']), ('not_checked', True))
        worktree = self.work / 'linked'
        self.write(worktree / '.git', b'gitdir: ../repo/.git/worktrees/linked\n')
        self.write(repo / '.git/worktrees/linked/commondir', b'../..\n')
        _, report = self.status(cwd=worktree)
        controller = self.extra(report, 'controller')
        self.assertEqual((controller['state'], controller['binding_present']), ('not_checked', True))
        outside = self.root / 'no-repo'
        outside.mkdir()
        _, report = self.status(cwd=outside)
        self.assertEqual(self.extra(report, 'controller')['state'], 'not_checked')

    def test_source_locator_is_reported_as_data_only(self):
        source = self.root / 'source'
        sentinel = self.root / 'executed'
        self.write(source / 'install.sh', f'#!/bin/sh\ntouch {sentinel}\n'.encode(), 0o755)
        self.write(source / 'framework_settings.py', f'open({str(sentinel)!r}, "w")\n'.encode())
        self.write(self.claude / '.framework-path', f'{source}\n'.encode())
        _, report = self.status()
        self.assertEqual(report['source']['origin'], 'locator')
        self.assertEqual(report['source']['path'], str(source))
        self.assertTrue(report['source']['found'])
        self.assertEqual(report['source']['comparison'], 'not_checked')
        self.assertFalse(sentinel.exists())
        _, report = self.status('--source', str(self.work))
        self.assertEqual((report['source']['origin'], report['source']['path']), ('argument', str(self.work)))
        self.write(self.claude / '.framework-path', b'relative/path\x07\n')
        _, report = self.status()
        self.assertIsNone(report['source']['path'])
        self.assertIn('ignored', report['source']['detail'])


class Preferences(Base):
    def test_status_and_settings_views_write_nothing(self):
        self.marker('version=2.0.0', 'analytics=enabled', 'watchdog=disabled', 'notifications=disabled')
        self.install_delivery()
        before = self.snapshot()
        for argv in (('status',), ('status', '--json'), ('status', '--detail', 'full'), ('settings',),
                     ('settings', '--json'), ()):
            with self.subTest(argv):
                code, _, _, asked = self.run_cli(*argv, interactive=True)
                self.assertEqual(code, 0)
                self.assertEqual(asked, [])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.prefs.parent.exists())

    def test_display_preference_save_and_reload(self):
        code, _, _, _ = self.run_cli('settings', '--set-detail', 'full')
        self.assertEqual(code, 0)
        self.assertEqual(stat.S_IMODE(self.prefs.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.prefs.parent.stat().st_mode), 0o700)
        self.assertEqual(json.loads(self.prefs.read_bytes()),
                         {'version': 1, 'display': {'detail': 'full', 'reminders': 'changes-only'},
                          'reviewed': {}, 'catalog_reviewed': 0})
        more = f'More: {fs.default_invocation()} status --detail full'
        _, text, _, _ = self.run_cli('status')
        self.assertIn('Source folder:', text)
        self.assertNotIn(more, text)
        saved = self.prefs.read_bytes()
        _, text, _, _ = self.run_cli('status', '--detail', 'concise')
        self.assertIn(more, text)
        self.assertEqual(self.prefs.read_bytes(), saved)
        _, out, _, _ = self.run_cli('settings', '--json')
        view = json.loads(out)['preferences']
        self.assertEqual((view['state'], view['display']['detail'], view['grants_permission']), ('saved', 'full', False))

    def test_reviews_remember_enabled_and_disabled_without_inferring(self):
        self.marker('analytics=enabled', 'watchdog=disabled', 'notifications=enabled')
        code, _, _, _ = self.run_cli('settings', '--acknowledge', 'claude.analytics', '--acknowledge', 'claude.watchdog')
        self.assertEqual(code, 0)
        saved = json.loads(self.prefs.read_bytes())
        self.assertEqual(saved['reviewed'], {'claude.analytics': 'enabled', 'claude.watchdog': 'disabled'})
        _, report = self.status()
        self.assertEqual(report['reminders'], [])
        self.assertNotIn('claude.notifications', report['preferences']['reviewed'])
        self.marker('analytics=disabled', 'watchdog=disabled', 'notifications=disabled')
        _, report = self.status()
        self.assertEqual(len(report['reminders']), 1)
        self.assertIn('analytics', report['reminders'][0])
        self.assertIn('reviewed it as enabled', report['reminders'][0])
        self.run_cli('settings', '--set-reminders', 'off')
        _, report = self.status()
        self.assertEqual(report['reminders'], [])
        code, _, _, _ = self.run_cli('settings', '--forget', 'claude.analytics')
        self.assertEqual(json.loads(self.prefs.read_bytes())['reviewed'], {'claude.watchdog': 'disabled'})

    def test_acknowledge_refuses_unknown_state_and_all_records_only_clear_states(self):
        self.marker('analytics=enabled', 'watchdog=disabled')
        code, _, err, _ = self.run_cli('settings', '--acknowledge', 'claude.notifications')
        self.assertEqual(code, 2)
        self.assertIn('cannot be remembered', err)
        self.assertFalse(self.prefs.exists())
        code, _, _, _ = self.run_cli('settings', '--acknowledge-all')
        self.assertEqual(code, 0)
        saved = json.loads(self.prefs.read_bytes())
        self.assertEqual(saved['reviewed'], {'claude.analytics': 'enabled', 'claude.watchdog': 'disabled',
                                             'model_policy': 'disabled'})
        self.assertEqual(saved['catalog_reviewed'], fs.CATALOG_VERSION)

    def test_malformed_preferences_are_refused_and_left_untouched(self):
        valid = fs.default_preferences()
        cases = {
            'bool-version': {**valid, 'version': True},
            'string-version': {**valid, 'version': '1'},
            'future-version': {**valid, 'version': 2},
            'unknown-key': {**valid, 'account': 'someone'},
            'missing-key': {key: value for key, value in valid.items() if key != 'reviewed'},
            'bad-enum': {**valid, 'display': {'detail': 'loud', 'reminders': 'changes-only'}},
            'bad-review': {**valid, 'reviewed': {'claude.analytics': 'off'}},
            'unknown-feature': {**valid, 'reviewed': {'claude.model': 'enabled'}},
            'bool-catalog': {**valid, 'catalog_reviewed': True},
            'list': [valid],
            'duplicate-key': b'{"version": 1, "version": 1, "display": {"detail": "concise", "reminders": '
                             b'"changes-only"}, "reviewed": {}, "catalog_reviewed": 0}',
            'non-finite': b'{"version": 1, "display": {"detail": "concise", "reminders": "changes-only"}, '
                          b'"reviewed": {}, "catalog_reviewed": NaN}',
            'not-json': b'{nope',
        }
        for name, payload in cases.items():
            with self.subTest(name):
                data = self.write_prefs(payload)
                code, report = self.status()
                self.assertEqual(code, 1)
                self.assertEqual(report['preferences']['state'], 'refused')
                self.assertEqual(report['headline']['state'], 'needs_attention')
                code, _, _, _ = self.run_cli('settings', '--set-detail', 'full')
                self.assertEqual(code, 2)
                self.assertEqual(self.prefs.read_bytes(), data)

    def test_unsafe_preference_paths_are_refused(self):
        data = self.write_prefs(fs.default_preferences(), mode=0o644)
        code, report = self.status()
        self.assertEqual((code, report['preferences']['state']), (1, 'refused'))
        self.assertEqual(self.run_cli('settings', '--set-detail', 'full')[0], 2)
        self.assertEqual(self.prefs.read_bytes(), data)
        self.prefs.unlink()
        real = self.write(self.root / 'real-prefs.json', json.dumps(fs.default_preferences()).encode(), 0o600)
        self.prefs.symlink_to(real)
        self.assertEqual(self.status()[1]['preferences']['state'], 'refused')
        self.assertEqual(self.run_cli('settings', '--set-detail', 'full')[0], 2)
        self.assertEqual(json.loads(real.read_bytes())['display']['detail'], 'concise')
        self.prefs.unlink()
        directory = self.prefs.parent
        directory.rmdir()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir(mode=0o700)
        directory.symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(self.run_cli('settings', '--set-detail', 'full')[0], 2)
        self.assertEqual(list(elsewhere.iterdir()), [])
        directory.unlink()
        directory.mkdir()
        directory.chmod(0o770)
        self.assertEqual(self.run_cli('settings', '--set-detail', 'full')[0], 2)
        self.assertFalse(self.prefs.exists())

    def test_save_refuses_stale_bytes(self):
        data = self.write_prefs(fs.default_preferences())
        changed = {**fs.default_preferences(), 'display': {'detail': 'full', 'reminders': 'off'}}
        with self.assertRaises(fs.RefusedError):
            fs.save_preferences(self.prefs, changed, None)
        self.assertEqual(self.prefs.read_bytes(), data)

    def test_save_detects_a_concurrent_writer_before_replacing(self):
        racer = json.dumps(fs.default_preferences()).encode()
        real_fsync = os.fsync
        calls = []

        def racing_fsync(fd):
            if not calls:
                calls.append(fd)
                self.write(self.prefs, racer, 0o600)
            return real_fsync(fd)

        changed = {**fs.default_preferences(), 'display': {'detail': 'full', 'reminders': 'off'}}
        with patch.object(fs.os, 'fsync', side_effect=racing_fsync):
            with self.assertRaises(fs.RefusedError):
                fs.save_preferences(self.prefs, changed, None)
        self.assertEqual(self.prefs.read_bytes(), racer)
        self.assertEqual([path.name for path in self.prefs.parent.iterdir()], ['framework-preferences.json'])

    def test_review_never_prompts_without_an_interactive_terminal(self):
        self.marker('analytics=enabled')
        code, _, err, asked = self.run_cli('settings', '--review', interactive=False)
        self.assertEqual((code, asked), (2, []))
        self.assertIn('interactive terminal', err)
        code, _, _, asked = self.run_cli('settings', '--review', '--json', interactive=True)
        self.assertEqual((code, asked), (2, []))
        code, _, _, asked = self.run_cli('status', '--json', interactive=True)
        self.assertEqual((code, asked), (0, []))
        self.assertFalse(self.prefs.exists())

    def test_main_detects_headless_and_ci_runs(self):
        self.marker('analytics=enabled')
        with patch('builtins.input', side_effect=AssertionError('prompted')), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with patch.object(fs, '_is_interactive', return_value=False):
                self.assertEqual(fs.main(['settings', '--review']), 2)
            with patch.object(fs.sys, 'stdin', TTYStream()), patch.object(fs.sys, 'stdout', TTYStream()):
                os.environ['CI'] = 'true'
                self.assertFalse(fs._is_interactive())
                del os.environ['CI']
                self.assertTrue(fs._is_interactive())
        self.assertFalse(self.prefs.exists())

    def test_guided_review_saves_only_after_confirmation(self):
        self.marker('analytics=enabled', 'watchdog=disabled', 'notifications=enabled')

        def answers(save):
            def respond(prompt):
                lowered = prompt.lower()
                if 'save' in lowered:
                    return save
                if 'detail' in lowered:
                    return 'full'
                return 'y' if 'analytics' in lowered or 'watchdog' in lowered else ''
            return respond

        code, out, _, asked = self.run_cli('settings', '--review', interactive=True, answers=answers('n'))
        self.assertEqual(code, 0)
        self.assertIn('Not saved', out)
        self.assertFalse(self.prefs.exists())
        self.assertFalse(any('Codex' in prompt for prompt in asked))
        code, _, _, _ = self.run_cli('settings', '--review', interactive=True, answers=answers('y'))
        self.assertEqual(code, 0)
        saved = json.loads(self.prefs.read_bytes())
        self.assertEqual(saved['reviewed'], {'claude.analytics': 'enabled', 'claude.watchdog': 'disabled'})
        self.assertEqual(saved['display'], {'detail': 'full', 'reminders': 'changes-only'})
        self.assertEqual(saved['catalog_reviewed'], fs.CATALOG_VERSION)
        code, out, _, asked = self.run_cli('settings', '--review', interactive=True,
                                           answers=lambda prompt: (_ for _ in ()).throw(EOFError()))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.prefs.read_bytes()), saved)

    def test_unrelated_native_config_and_account_data_are_preserved(self):
        directory = self.private_config_dir()
        self.marker('version=2.0.0', 'analytics=enabled', 'watchdog=disabled', 'notifications=disabled')
        self.write(self.claude / 'settings.json', b'{"permissions": {"allow": ["Bash(ls)"]}, "model": "owner-choice"}\n')
        self.write(self.home / '.codex/config.toml', b'model = "owner-choice"\n')
        self.write(self.home / '.codex/auth.json', b'{"token": "not-a-real-token"}\n', 0o600)
        self.write(directory / 'model-policy.json',
                   json.dumps({'version': 1, 'active': True, 'bindings': {'a': {'model': 'owner-choice'}}}).encode(),
                   0o600)
        self.write(directory / 'accounts.json', b'{"profiles": ["owner-profile"]}\n', 0o600)
        before = self.snapshot()
        outputs = []
        for argv in (('settings', '--set-detail', 'full'), ('settings', '--acknowledge-all'), ('status',),
                     ('settings', '--json')):
            code, out, err, _ = self.run_cli(*argv)
            self.assertEqual(code, 0, err)
            outputs.append(out)
        after = self.snapshot()
        preferences_key = str(self.prefs.relative_to(self.root))
        self.assertEqual(set(after) - set(before), {preferences_key})
        self.assertEqual({key: after[key] for key in before}, before)
        saved = self.prefs.read_text()
        for secret in ('owner-choice', 'not-a-real-token', 'owner-profile', 'Bash(ls)'):
            self.assertNotIn(secret, saved)
            self.assertNotIn(secret, ''.join(outputs))


class OwnedSurfaces(Base):
    def test_private_and_runtime_paths_are_never_read_as_owned_payloads(self):
        manifest = self.home / '.codex/framework/manifest.json'
        registry = self.write(self.home / '.codex/framework/lint-projects.json', b'{"private-project": 1}\n', 0o600)
        self.write(self.home / '.codex/framework/sessions/events.jsonl', b'{}\n')
        shipped = {rel: sha(data) for rel, data in CODEX_FILES.items()}
        real_read = fs.read_regular
        reads = []

        def spy(path, limit):
            reads.append(Path(path))
            return real_read(path, limit)

        cases = ('.codex/framework/lint-projects.json', '.codex/framework/sessions/events.jsonl',
                 '.codex/framework/manifest.json', '.codex/agents/nested/role.toml', '.codex/config.toml')
        for rel in cases:
            with self.subTest(rel):
                self.install_codex(self.home, record={**shipped, rel: 'e' * 64})
                reads.clear()
                with patch.object(fs, 'read_regular', side_effect=spy):
                    code, report = self.status()
                codex = self.component(report, 'codex')
                self.assertEqual((code, codex['state']), (1, 'needs_attention'))
                self.assertIn('outside the managed files', codex['summary'])
                self.assertNotIn(self.home / rel, [path for path in reads if path != manifest])
                self.assertNotIn(registry, reads)
        self.install_codex(self.home)
        _, report = self.status()
        self.assertEqual(self.component(report, 'codex')['state'], 'ready')

    def test_codex_ready_requires_its_managed_instruction_block(self):
        project = self.work / 'project'
        for user, root, args in ((True, self.home, ()), (False, project, ('--project', str(project)))):
            rel = '.codex/AGENTS.md' if user else 'AGENTS.md'
            personal = b'mine\n' + MANAGED_BLOCK + b'also mine\n'
            with self.subTest(user=user, case='valid-with-personal-text'):
                self.install_codex(root, user=user, agents=personal)
                code, report = self.status(*args)
                codex = self.component(report, 'codex')
                self.assertEqual((code, codex['state']), (0, 'ready'))
                self.assertIn('managed instruction block', codex['summary'])
                self.assertEqual((root / rel).read_bytes(), personal)
            broken = {
                'block-removed': PERSONAL_PREFIX + PERSONAL_SUFFIX,
                'block-edited': PERSONAL_PREFIX + MANAGED_BLOCK.replace(b'managed guidance', b'edited guidance'),
                'duplicated': MANAGED_BLOCK + MANAGED_BLOCK,
                'reversed': f'{fs.INSTRUCTION_END}\nmanaged guidance\n{fs.INSTRUCTION_BEGIN}\n'.encode(),
            }
            for case, data in broken.items():
                with self.subTest(user=user, case=case):
                    self.install_codex(root, user=user, agents=data)
                    code, report = self.status(*args)
                    codex = self.component(report, 'codex')
                    self.assertEqual((code, codex['state']), (1, 'needs_attention'))
                    self.assertTrue(any(problem.startswith(f'{rel}:') for problem in codex['problems']))
            with self.subTest(user=user, case='missing-file'):
                self.install_codex(root, user=user)
                (root / rel).unlink()
                code, report = self.status(*args)
                problems = self.component(report, 'codex')['problems']
                self.assertEqual(code, 1)
                self.assertTrue(any(problem.startswith(f'{rel}: missing') for problem in problems))
            with self.subTest(user=user, case='symlink'):
                self.install_codex(root, user=user)
                real = self.write(self.root / f'agents-{user}.md', (root / rel).read_bytes())
                (root / rel).unlink()
                (root / rel).symlink_to(real)
                code, report = self.status(*args)
                problems = self.component(report, 'codex')['problems']
                self.assertEqual(code, 1)
                self.assertTrue(any(problem.startswith(f'{rel}:') and 'symlink' in problem for problem in problems))
                (root / rel).unlink()

    def test_selected_hooks_need_a_verified_hook_definition(self):
        shipped = {rel: sha(data) for rel, data in CODEX_FILES.items()}
        self.install_codex(self.home, hooks=True, record=shipped)
        _, report = self.status()
        self.assertEqual(self.component(report, 'codex')['state'], 'needs_attention')
        self.assertIn('hook choice', self.component(report, 'codex')['summary'])
        self.assertEqual(self.extra(report, 'codex.hooks')['state'], 'unknown')
        self.install_codex(self.home, hooks=False, record={**shipped, '.codex/hooks.json': sha(HOOKS_FILE)})
        _, report = self.status()
        self.assertIn('hook choice', self.component(report, 'codex')['summary'])
        self.install_codex(self.home, hooks=True)
        (self.home / '.codex/hooks.json').unlink()
        code, report = self.status()
        codex = self.component(report, 'codex')
        self.assertEqual((code, codex['state']), (1, 'needs_attention'))
        self.assertIn('.codex/hooks.json: missing', codex['problems'])
        self.assertEqual(self.extra(report, 'codex.hooks')['state'], 'unknown')
        self.install_codex(self.home, hooks=True)
        code, report = self.status()
        self.assertEqual((code, self.component(report, 'codex')['state']), (0, 'ready'))
        self.assertEqual(self.extra(report, 'codex.hooks')['state'], 'on')


class PresenceIsNotOperation(Base):
    def test_private_policy_parse_errors_never_echo_contents(self):
        directory = self.private_config_dir()
        sentinel = 'owner-private-alias-5c1d'
        body = f'{{"version": 1, "active": true, "bindings": {{"{sentinel}": {{}}, "{sentinel}": {{}}}}}}'.encode()
        policy = self.write(directory / 'model-policy.json', body, 0o600)
        outputs = []
        for argv in (('status', '--json'), ('status', '--detail', 'full'), ('settings',), ('settings', '--json')):
            code, out, err, _ = self.run_cli(*argv)
            self.assertEqual(code, 1)
            outputs.append(out + err)
        _, report = self.status()
        self.assertEqual(self.extra(report, 'model_policy')['state'], 'needs_attention')
        self.assertNotIn(sentinel, ''.join(outputs))
        self.assertFalse(self.prefs.exists())
        self.assertEqual(policy.read_bytes(), body)
        self.write(policy, json.dumps({'version': 1, 'active': True, 'bindings': {sentinel: {}}}).encode(), 0o600)
        code, out, err, _ = self.run_cli('status', '--json')
        self.assertEqual(self.extra(json.loads(out), 'model_policy')['state'], 'not_checked')
        self.assertNotIn(sentinel, out + err)

    def test_presence_alone_is_never_reported_on(self):
        self.install_codex(self.home, hooks=True)
        self.write(self.home / '.codex/framework/lint-projects.json', b'{"version": 1, "projects": []}', 0o600)
        repo = self.work / 'repo'
        self.write(repo / '.git/sdlc-controller.binding', b'opaque\n')
        directory = self.private_config_dir()
        self.write(directory / 'model-policy.json', json.dumps({'version': 1, 'active': True}).encode(), 0o600)
        _, report = self.status(cwd=repo)
        lint, controller, policy = (self.extra(report, feature_id)
                                    for feature_id in ('codex.approved_lint', 'controller', 'model_policy'))
        self.assertEqual({lint['state'], controller['state'], policy['state']}, {'not_checked'})
        self.assertTrue(lint['registry_present'] and controller['binding_present'] and policy['configured_active'])
        _, text, _, _ = self.run_cli('status', cwd=repo)
        for short in ('Codex lint', 'controller', 'model policy'):
            self.assertIn(f'{short} Not checked', text)
            self.assertNotIn(f'{short} On', text)


class ReminderCatalog(Base):
    def test_individual_reviews_and_display_saves_never_announce_new_extras(self):
        self.marker('analytics=enabled', 'watchdog=disabled')
        self.assertEqual(self.run_cli('settings', '--set-detail', 'full')[0], 0)
        _, report = self.status()
        self.assertEqual(report['reminders'], [])
        self.assertEqual(self.run_cli('settings', '--acknowledge', 'claude.analytics')[0], 0)
        self.assertEqual(json.loads(self.prefs.read_bytes())['catalog_reviewed'], 0)
        _, report = self.status()
        self.assertEqual(report['reminders'], [])

    def test_new_extras_notice_only_after_an_older_completed_review(self):
        self.marker('analytics=enabled')
        self.assertEqual(self.run_cli('settings', '--acknowledge-all')[0], 0)
        self.assertEqual(json.loads(self.prefs.read_bytes())['catalog_reviewed'], fs.CATALOG_VERSION)
        _, report = self.status()
        self.assertEqual(report['reminders'], [])
        with patch.object(fs, 'CATALOG_VERSION', fs.CATALOG_VERSION + 1):
            _, report = self.status()
            self.assertEqual(len(report['reminders']), 1)
            self.assertIn('New optional extras', report['reminders'][0])
            self.assertIn(f'{fs.default_invocation()} settings', report['reminders'][0])
            self.write_prefs({**json.loads(self.prefs.read_bytes()), 'catalog_reviewed': 0})
            _, report = self.status()
            self.assertEqual(report['reminders'], [])
            self.assertEqual(self.run_cli('settings', '--set-reminders', 'off')[0], 0)
            self.write_prefs({**json.loads(self.prefs.read_bytes()), 'catalog_reviewed': 1})
            _, report = self.status()
            self.assertEqual(report['reminders'], [])


def load_canonical_installer():
    """The real delivery installer module, loaded only for its manifest reader (nothing is run)."""
    spec = importlib.util.spec_from_file_location('install_delivery', ROOT / 'scripts/install-delivery.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADOPTED_ORIGINAL = b'adopted-original-sentinel\n' * 50000


class InstallRecordSize(Base):
    def adopted_manifest_bytes(self) -> tuple[bytes, str]:
        """A canonical-shaped delivery manifest whose adopted original pushes it past 1 MiB."""
        for rel, data in DELIVERY_FILES.items():
            self.write(self.claude / rel, data)
        encoded = base64.b64encode(ADOPTED_ORIGINAL).decode()
        manifest = {'version': 1, 'source_sha': 'a' * 40,
                    'files': {rel: sha(data) for rel, data in DELIVERY_FILES.items()},
                    'adopted': {'rules/delivery.md': {'baseline': 'c' * 40, 'original': encoded}},
                    'dirs': ['commands', 'rules', 'skills', 'skills/delivery', 'skills/verified-handoff']}
        return (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(), encoded

    def test_large_adopted_delivery_manifest_is_verified_without_exposing_originals(self):
        data, encoded = self.adopted_manifest_bytes()
        self.assertGreater(len(data), 1 << 20)
        self.write(self.claude / fs.DELIVERY_MANIFEST, data)
        canonical = load_canonical_installer().load_manifest(self.claude)
        self.assertEqual(canonical['adopted']['rules/delivery.md']['original'], encoded)
        before = self.snapshot()
        code, report = self.status()
        delivery = self.component(report, 'claude_delivery')
        self.assertEqual((code, delivery['state']), (0, 'ready'))
        self.assertEqual(delivery['owned_files'], len(DELIVERY_FILES))
        self.assertEqual(delivery['problems'], [])
        code, text, err, _ = self.run_cli('status', '--detail', 'full')
        self.assertEqual(code, 0)
        for output in (json.dumps(report), text, err):
            self.assertNotIn(encoded[:64], output)
            self.assertNotIn('adopted-original-sentinel', output)
        self.assertEqual(self.snapshot(), before)

    def test_install_record_over_its_own_cap_is_refused(self):
        data, _ = self.adopted_manifest_bytes()
        self.assertLess(len(data), fs.MAX_INSTALL_RECORD_BYTES)
        padded = data + b' ' * (fs.MAX_INSTALL_RECORD_BYTES + 1 - len(data))
        self.write(self.claude / fs.DELIVERY_MANIFEST, padded)
        before = self.snapshot()
        code, report = self.status()
        delivery = self.component(report, 'claude_delivery')
        self.assertEqual((code, delivery['state']), (1, 'needs_attention'))
        self.assertIn('larger than expected', delivery['summary'])
        self.assertEqual(self.snapshot(), before)

    def test_preferences_keep_their_one_mebibyte_cap(self):
        self.assertEqual(fs.MAX_JSON_BYTES, 1 << 20)
        self.assertGreater(fs.MAX_INSTALL_RECORD_BYTES, fs.MAX_JSON_BYTES)
        valid = json.dumps(fs.default_preferences()).encode()
        data = self.write_prefs(valid + b' ' * (fs.MAX_JSON_BYTES + 1 - len(valid)))
        code, report = self.status()
        self.assertEqual((code, report['preferences']['state']), (1, 'refused'))
        self.assertEqual(self.run_cli('settings', '--set-detail', 'full')[0], 2)
        self.assertEqual(self.prefs.read_bytes(), data)
        with self.assertRaises(fs.RefusedError):
            fs.parse_json(valid + b' ' * fs.MAX_JSON_BYTES)


class ScopeAndInvocation(Base):
    def test_other_profile_folders_are_named_not_silently_checked(self):
        other = self.root / 'other-profile'
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(other), 'CODEX_HOME': str(self.root / 'other-codex')}):
            _, report = self.status()
            self.assertEqual(len(report['scope_notes']), 2)
            self.assertNotIn(str(self.root), json.dumps(report['scope_notes']))
            _, text, _, _ = self.run_cli('status')
            self.assertIn('CLAUDE_CONFIG_DIR', text)
            _, report = self.status('--claude-home', str(other), '--project', str(self.work))
            self.assertEqual(report['scope_notes'], [])
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.claude)}):
            self.assertEqual(self.status()[1]['scope_notes'], [])

    def test_hints_use_the_given_invocation(self):
        out, err = io.StringIO(), io.StringIO()
        code = fs._run(['settings'], interactive=False, ask=lambda prompt: '', out=out, err=err, cwd=self.work,
                       invocation='./framework')
        self.assertEqual(code, 0)
        self.assertIn('./framework settings --set-detail', out.getvalue())
        _, text, _, _ = self.run_cli('status')
        self.assertIn(f'More: {fs.default_invocation()} status --detail full', text)
        self.assertNotIn('More: framework status', text)


if __name__ == '__main__':
    unittest.main()
