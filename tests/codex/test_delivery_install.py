"""Incremental Claude delivery installer checks in disposable source and home layouts.

No test reads or writes a real user home, settings or credentials. Set
DELIVERY_INSTALLER to a staged installer path to test a copy before materialization.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = Path(os.environ.get('DELIVERY_INSTALLER') or ROOT / 'scripts/install-delivery.py')
_spec = importlib.util.spec_from_file_location('install_delivery', INSTALLER)
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)

OLD_COMMAND = b'---\ndescription: previously shipped publication command\n---\n\nCommit, then test.\n'
NEW_COMMAND = b'---\ndescription: neutral publication command\n---\n\nCommit, check, review, publish.\n'
PERSONAL = {'settings.json': b'{"model": "personal"}\n', 'CLAUDE.md': b'Personal instructions\n',
            'skills/personal/SKILL.md': b'personal skill', 'commands/mine.md': b'personal command',
            'rules/personal.md': b'personal rule', 'hooks/guard.sh': b'#!/bin/sh\n'}


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in root.rglob('*') if not p.is_symlink()}


class DeliveryInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='delivery-install-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.source = self.tmp / 'source'
        self.home = self.tmp / 'home/.claude'
        self.home.mkdir(parents=True)
        self.write(self.source, {'.claude/commands/commit-pr.md': OLD_COMMAND, 'README.md': b'fixture\n'})
        self.git('init', '-q')
        self.baseline = self.commit('baseline')
        self.write(self.source, {
            '.claude/commands/commit-pr.md': NEW_COMMAND,
            '.claude/rules/delivery.md': b'Route implementation outcomes through delivery.\n',
            '.claude/skills/delivery/SKILL.md': b'---\nname: delivery\ndescription: d\n---\nbody\n',
            '.claude/skills/delivery/references/task-contract.md': b'contract\n',
            '.claude/skills/repo-context/SKILL.md': b'---\nname: repo-context\ndescription: r\n---\n',
            '.claude/skills/repo-context/scripts/repo_context.py': b'print("context")\n',
            '.claude/skills/verified-handoff/SKILL.md': b'---\nname: verified-handoff\ndescription: v\n---\n',
            '.claude/skills/verified-handoff/scripts/evidence.py': b'print("evidence")\n',
            '.claude/skills/unrelated/SKILL.md': b'not managed by the delivery installer\n',
        })
        self.head = self.commit('delivery')

    def write(self, root, files):
        for rel, data in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def git(self, *args):
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.tmp), 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_CONFIG_GLOBAL': os.devnull}
        return subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=Fixture', '-c',
                               'user.email=fixture@example.invalid', *args],
                              env=env, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def install(self, **options):
        return installer.run(self.home, self.source, **options)[0]

    def personalize(self):
        self.write(self.home, PERSONAL)
        return snapshot(self.home)

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(INSTALLER), '--source', str(self.source), *args],
                              env=env or dict(os.environ, CLAUDE_CONFIG_DIR=str(self.home)),
                              capture_output=True, text=True, timeout=60)

    def test_install_is_scoped_idempotent_and_preserves_personal_files(self):
        before = self.personalize()
        changes = self.install()
        self.assertIn('commands/commit-pr.md', changes)
        self.assertEqual((self.home / 'commands/commit-pr.md').read_bytes(), NEW_COMMAND)
        self.assertFalse((self.home / 'skills/unrelated').exists())
        installed = snapshot(self.home)
        for rel, data in before.items():
            self.assertEqual(installed[rel], data, rel)
        for rel in set(installed) - set(before):
            self.assertTrue(installer.allowed(rel) or installer.allowed_dir(rel)
                            or rel.startswith(installer.STATE_DIR), rel)
        manifest = json.loads((self.home / installer.MANIFEST).read_text())
        self.assertEqual((manifest['source_sha'], manifest['source_dirty']), (self.head, False))
        self.assertEqual(self.install(), [])
        self.assertEqual(snapshot(self.home), installed)
        self.install(check=True)

    def test_dry_run_and_check_have_no_effects(self):
        before = self.personalize()
        self.assertTrue(self.install(dry_run=True))
        with self.assertRaisesRegex(installer.InstallError, 'drift'):
            self.install(check=True)
        for args, code in ((('--dry-run',), 0), (('--check',), 1)):
            result = self.cli(*args)
            self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(snapshot(self.home), before)

    def test_update_and_uninstall_restore_adopted_baseline_and_personal_files(self):
        self.write(self.home, {'commands/commit-pr.md': OLD_COMMAND})
        before = self.personalize()
        with self.assertRaisesRegex(installer.InstallError, 'foreign'):
            self.install()
        self.assertEqual(snapshot(self.home), before)
        self.install(baseline=self.baseline)
        self.assertEqual((self.home / 'commands/commit-pr.md').read_bytes(), NEW_COMMAND)
        (self.source / '.claude/skills/delivery/references/task-contract.md').unlink()
        self.write(self.source, {'.claude/skills/delivery/SKILL.md': b'updated body\n'})
        self.commit('update')
        changes = self.install()
        self.assertEqual(set(changes), {'skills/delivery/SKILL.md', 'skills/delivery/references/task-contract.md',
                                        installer.MANIFEST})
        self.assertFalse((self.home / 'skills/delivery/references/task-contract.md').exists())
        self.install(uninstall=True)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual((self.home / 'commands/commit-pr.md').read_bytes(), OLD_COMMAND)

    def test_uninstall_without_adoption_leaves_no_created_directories(self):
        before = snapshot(self.home)
        self.install()
        self.install(uninstall=True)
        self.assertEqual(snapshot(self.home), before)

    def test_baseline_must_be_full_commit_and_match_exact_bytes(self):
        self.write(self.home, {'commands/commit-pr.md': OLD_COMMAND + b'owner edit\n'})
        before = self.personalize()
        for baseline, message in ((self.baseline, 'foreign'), (self.baseline[:12], 'full'),
                                  ('f' * 40, 'not a commit'), (self.git('rev-parse', 'HEAD^{tree}'), 'not a commit')):
            with self.subTest(baseline=baseline), self.assertRaisesRegex(installer.InstallError, message):
                self.install(baseline=baseline)
            self.assertEqual(snapshot(self.home), before)
        self.write(self.home, {'skills/delivery/SKILL.md': b'personal delivery skill'})
        (self.home / 'commands/commit-pr.md').write_bytes(OLD_COMMAND)
        before = snapshot(self.home)
        with self.assertRaisesRegex(installer.InstallError, 'foreign.*skills/delivery/SKILL.md'):
            self.install(baseline=self.baseline)
        self.assertEqual(snapshot(self.home), before)

    def test_modified_managed_file_is_never_overwritten_or_removed(self):
        self.install()
        path = self.home / 'rules/delivery.md'
        path.write_bytes(path.read_bytes() + b'owner customization\n')
        before = snapshot(self.home)
        for options in ({}, {'uninstall': True}, {'check': True}, {'dry_run': True}):
            with self.subTest(options=options), self.assertRaisesRegex(installer.InstallError, 'modified'):
                self.install(**options)
            self.assertEqual(snapshot(self.home), before)

    def test_symlinked_destinations_and_ancestors_refused_before_writes(self):
        outside = self.tmp / 'outside'
        outside.mkdir()
        (self.home / 'skills').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(installer.InstallError, 'symlink'):
            self.install()
        self.assertEqual(snapshot(outside), {})
        self.assertFalse((self.home / 'commands').exists())
        (self.home / 'skills').unlink()
        alias = self.tmp / 'alias'
        alias.symlink_to(self.home, target_is_directory=True)
        with self.assertRaisesRegex(installer.InstallError, 'symlink'):
            installer.run(alias, self.source)
        with self.assertRaisesRegex(installer.InstallError, 'symlink'):
            installer.resolve_home(alias)
        (self.home / 'rules').mkdir()
        (self.home / 'rules/delivery.md').symlink_to(outside / 'rule.md')
        with self.assertRaisesRegex(installer.InstallError, 'symlink'):
            self.install()
        self.assertFalse((outside / 'rule.md').exists())
        self.assertEqual({p.name for p in self.home.iterdir()}, {'rules'})

    def test_caught_io_failure_rolls_back_install_and_update(self):
        before = self.personalize()
        real = installer.atomic_write
        for phase in ('install', 'update'):
            calls = 0

            def fail_third(path, data):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError('simulated disk write error')
                return real(path, data)
            with self.subTest(phase=phase), patch.object(installer, 'atomic_write', fail_third):
                with self.assertRaises(OSError):
                    self.install()
                self.assertEqual(snapshot(self.home), before)
                self.assertFalse((self.home / installer.LOCK).exists())
            if phase == 'install':
                self.install()
                self.write(self.source, {'.claude/rules/delivery.md': b'changed rule\n',
                                         '.claude/commands/commit-pr.md': b'changed command\n'})
                self.commit('change')
                before = snapshot(self.home)

    def test_dirty_source_is_reported_and_refused_for_real_installation(self):
        self.write(self.source, {'.claude/skills/repo-context/scripts/repo_context.py': b'print("uncommitted")\n'})
        before = snapshot(self.home)
        changes, origin = installer.run(self.home, self.source, dry_run=True)
        self.assertTrue(changes)
        self.assertEqual(origin, {'sha': self.head, 'dirty': True})
        with self.assertRaisesRegex(installer.InstallError, 'uncommitted'):
            self.install()
        self.write(self.source, {'.claude/skills/delivery/untracked.md': b'new\n'})
        self.assertTrue(installer.provenance(self.source)['dirty'])
        self.assertEqual(snapshot(self.home), before)

    def test_held_lock_and_corrupt_manifest_refuse_without_changes(self):
        (self.home / installer.LOCK).write_text('held')
        before = snapshot(self.home)
        with self.assertRaisesRegex(installer.InstallError, 'another install'):
            self.install()
        self.assertEqual(snapshot(self.home), before)
        (self.home / installer.LOCK).unlink()
        self.personalize()
        self.install()
        manifest = self.home / installer.MANIFEST
        valid = json.loads(manifest.read_text())
        for rel in ('settings.json', '../escape', 'skills/personal/SKILL.md', 'skills/delivery/../../CLAUDE.md'):
            manifest.write_text(json.dumps(dict(valid, files={rel: '0' * 64})))
            before = snapshot(self.home)
            with self.subTest(rel=rel), self.assertRaises(installer.InstallError):
                self.install(uninstall=True)
            self.assertEqual(snapshot(self.home), before)

    def test_cli_target_selection(self):
        fake_home = self.tmp / 'user'
        fake_home.mkdir()
        env = dict(os.environ, HOME=str(fake_home), CLAUDE_CONFIG_DIR=str(self.home))
        result = self.cli(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.head, result.stdout)
        self.assertTrue((self.home / 'rules/delivery.md').is_file())
        self.assertEqual(list(fake_home.iterdir()), [])
        missing = self.cli('--claude-home', str(self.tmp / 'missing-profile'))
        self.assertEqual(missing.returncode, 1)
        self.assertIn('does not exist', missing.stderr)
        self.assertFalse((self.tmp / 'missing-profile').exists())


class InstalledDeliveryResources(unittest.TestCase):
    """Install the real delivery resources from a committed copy and run them in place."""

    def test_installed_resources_execute_from_claude_home(self):
        with tempfile.TemporaryDirectory(prefix='delivery-real-') as directory:
            root = Path(directory).resolve()
            source, home = root / 'source', root / 'home/.claude'
            home.mkdir(parents=True)
            for rel in [f'.claude/skills/{name}' for name in installer.SKILLS]:
                shutil.copytree(ROOT / rel, source / rel, ignore=shutil.ignore_patterns('__pycache__'))
            for rel in installer.SINGLE_FILES:
                (source / '.claude' / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / '.claude' / rel, source / '.claude' / rel)
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(root),
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'LC_ALL': 'C'}
            git = ['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid']
            subprocess.run(['git', 'init', '-q', str(source)], env=env, check=True)
            subprocess.run(git + ['add', '-A'], env=env, check=True)
            subprocess.run(git + ['commit', '-q', '-m', 'resources'], env=env, check=True)
            installer.run(home, source)
            context = subprocess.run([sys.executable, str(home / 'skills/repo-context/scripts/repo_context.py'),
                                      '--cwd', str(source)], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(context.returncode, 0, context.stderr)
            report = json.loads(context.stdout)
            self.assertEqual(report['source']['gitRoot'], str(source))
            self.assertFalse(report['source']['dirty'])
            evidence = subprocess.run([sys.executable, str(home / 'skills/verified-handoff/scripts/evidence.py'),
                                       '--help'], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(evidence.returncode, 0, evidence.stderr)
            for name in installer.SKILLS:
                self.assertEqual((home / f'skills/{name}/SKILL.md').read_bytes(),
                                 (ROOT / f'.claude/skills/{name}/SKILL.md').read_bytes())


if __name__ == '__main__':
    unittest.main()
