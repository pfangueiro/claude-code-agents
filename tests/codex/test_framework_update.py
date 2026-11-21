"""Safe existing-install updater checks in disposable Git sources and homes.

Every source is a miniature committed repository and every target a temporary home. No test
reads or writes a real home, settings, credentials or account, uses the network, or runs the
real broad installer: staging checks run only a miniature committed install.sh inside the
updater's own private disposable staging home. Set FRAMEWORK_UPDATER to test a staged copy of
scripts/framework_update.py.
"""
import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import posixpath
import shlex
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
UPDATER = Path(os.environ.get('FRAMEWORK_UPDATER') or ROOT / 'scripts/framework_update.py')
_spec = importlib.util.spec_from_file_location('framework_update', UPDATER)
update = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update)

HOOK_POLICY = (
    '_hook_component() {\n'
    '    case "$1" in\n'
    '        notify.sh) echo notifications ;;\n'
    '        agent-tracker.sh|session-end.sh) echo analytics ;;\n'
    '        *) echo core ;;\n'
    '    esac\n'
    '}\n')


def installer(agents, libs, retired_libs=(), retired_skills=()):
    """A miniature install.sh carrying the literal arrays and hook policy the real one declares."""
    def array(name, items):
        return f'{name}=(\n' + ''.join(f'    "{item}"\n' for item in items) + ')\n'
    text = '#!/bin/bash\nset -e\n' + array('AGENTS', agents) + array('LIB_FILES', libs)
    if retired_libs:
        text += array('RETIRED_LIB_FILES', retired_libs)
    if retired_skills:
        text += array('RETIRED_SKILLS', retired_skills)
    return (text + HOOK_POLICY).encode()


RULE = '.claude/rules/core.md'
BASELINE = {
    'install.sh': installer(['alpha', 'retiring'], ['old.json', 'keep.json']),
    '.claude/agents/alpha.md': b'alpha v1\n',
    '.claude/agents/retiring.md': b'retiring v1\n',
    '.claude/lib/old.json': b'{"old": 1}\n',
    '.claude/lib/keep.json': b'{"keep": 1}\n',
    '.claude/lib/unmapped.json': b'{"unmapped": 1}\n',   # in the tree, NOT in LIB_FILES
    RULE: b'core rule v1\n',
    '.claude/skills/s1/SKILL.md': b'skill one v1\n',
    '.claude/skills/s1/ref/kept.md': b'kept reference\n',
    '.claude/skills/s1/ref/obsolete.md': b'obsolete reference\n',
    '.claude/skills/gone/SKILL.md': b'retired skill\n',
    'global-config/hooks/guard.sh': b'#!/bin/sh\necho guard v1\n',
    'global-config/hooks/notify.sh': b'#!/bin/sh\necho notify v1\n',
    'global-config/settings.json': b'{"template": 1}\n',
    'README.md': b'fixture\n',
}
HEAD = {
    'install.sh': installer(['alpha', 'beta', 'retiring'], ['keep.json', 'unmapped.json'],
                            retired_libs=['old.json', 'never-shipped.json'], retired_skills=['gone']),
    '.claude/agents/alpha.md': b'alpha v2\n',
    '.claude/agents/beta.md': b'beta v1\n',
    '.claude/lib/keep.json': b'{"keep": 2}\n',
    '.claude/lib/unmapped.json': b'{"unmapped": 2}\n',
    RULE: b'core rule v2\n',
    '.claude/rules/new.md': b'new rule\n',
    '.claude/skills/s1/SKILL.md': b'skill one v2\n',
    '.claude/skills/s1/ref/kept.md': b'kept reference\n',
    '.claude/skills/s2/SKILL.md': b'skill two\n',
    'global-config/hooks/guard.sh': b'#!/bin/sh\necho guard v2\n',
    'global-config/hooks/notify.sh': b'#!/bin/sh\necho notify v2\n',
    'global-config/settings.json': b'{"template": 2}\n',
    'README.md': b'fixture\n',
}
EXECUTABLE = {'global-config/hooks/guard.sh', 'global-config/hooks/notify.sh'}
# What the baseline install.sh actually wrote: its own mapping, not its whole tree.
INSTALLED_AT_BASELINE = {rel: rel for rel in (
    '.claude/agents/alpha.md', '.claude/agents/retiring.md', '.claude/lib/old.json', '.claude/lib/keep.json',
    RULE, '.claude/skills/s1/SKILL.md', '.claude/skills/s1/ref/kept.md', '.claude/skills/s1/ref/obsolete.md',
    '.claude/skills/gone/SKILL.md')}
INSTALLED_AT_BASELINE.update({'.claude/hooks/guard.sh': 'global-config/hooks/guard.sh',
                              '.claude/hooks/notify.sh': 'global-config/hooks/notify.sh'})
PERSONAL = {
    '.claude/settings.json': b'{"model": "personal", "permissions": {"allow": ["Bash(ls)"]}}\n',
    '.claude/CLAUDE.md': b'Personal instructions\n',
    '.claude/lib/personal.json': b'{"mine": true}\n',
    '.claude/rules/personal.md': b'personal rule\n',
    '.claude/skills/mine/SKILL.md': b'personal skill\n',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def shipped(rel):
    """HEAD bytes the broad --update would publish at a target path."""
    if rel.startswith('.claude/hooks/'):
        return HEAD['global-config/hooks/' + rel.rsplit('/', 1)[1]]
    return HEAD[rel]


def put(root, rel, data, mode=0o644):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.chmod(path, mode)


def tree(root):
    """Every entry below root with its kind, mode and bytes or link target; never follows links."""
    found = {}
    for directory, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(directory, name)
            info = path.lstat()
            rel = path.relative_to(root).as_posix()
            if stat.S_ISLNK(info.st_mode):
                found[rel] = ('link', os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                found[rel] = ('dir', stat.S_IMODE(info.st_mode))
            elif stat.S_ISREG(info.st_mode):
                found[rel] = ('file', stat.S_IMODE(info.st_mode), path.read_bytes())
            else:
                found[rel] = ('special', stat.S_IMODE(info.st_mode))
    return found


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='framework-update-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        user_home = self.tmp / 'user'
        user_home.mkdir()
        environment = patch.dict(os.environ, {'HOME': str(user_home)})
        environment.start()
        self.addCleanup(environment.stop)
        self.git_env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(user_home),
                        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        self.source, self.baseline, self.head = self.make_source('source')
        self.home = self.tmp / 'home'

    def git(self, *args, source=None, data=None):
        result = subprocess.run(['git', '-C', str(source or self.source), '-c', 'user.name=Fixture', '-c',
                                 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', *args],
                                env=self.git_env, input=data, capture_output=True, check=True, timeout=120)
        return result.stdout.decode().strip()

    def replace_tree(self, source, files):
        for entry in source.iterdir():
            if entry.name == '.git':
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        for repo, data in files.items():
            put(source, repo, data, 0o755 if repo in EXECUTABLE else 0o644)

    def commit(self, source, message):
        self.git('add', '-A', source=source)
        self.git('commit', '-q', '-m', message, source=source)
        return self.git('rev-parse', 'HEAD', source=source)

    def make_source(self, name):
        source = self.tmp / name
        source.mkdir()
        self.git('init', '-q', source=source)
        self.replace_tree(source, BASELINE)
        baseline = self.commit(source, 'baseline')
        self.replace_tree(source, HEAD)
        return source, baseline, self.commit(source, 'head')

    def read(self, source=None):
        with update.scrubbed_git_environment():
            return update.read_source(source or self.source)

    def marker(self, sha=None):
        sha = sha or self.git('rev-parse', '--short=7', self.baseline)
        return (f'version=3.2.0\nsha={sha}\nanalytics=disabled\nwatchdog=disabled\n'
                f'notifications=enabled\ninstalled_at=2026-01-01T00:00:00Z\n').encode()

    def install_baseline(self, marker=b''):
        """A home as the baseline install.sh left it, plus personal files. marker=None omits it."""
        if self.home.exists():
            shutil.rmtree(self.home)
        self.home.mkdir(mode=0o700)
        for rel, repo in INSTALLED_AT_BASELINE.items():
            put(self.home, rel, BASELINE[repo], 0o755 if repo in EXECUTABLE else 0o644)
        if marker is not None:
            put(self.home, update.MARKER, marker or self.marker())
        for rel, data in PERSONAL.items():
            put(self.home, rel, data)

    def plan(self, delivery=None):
        with update.scrubbed_git_environment():
            return update.plan_claude_broad(self.home, update.read_source(self.source), delivery)

    def assert_refused(self, error=update.UpdateError, delivery=None):
        before = tree(self.home)
        with self.assertRaises(error) as caught:
            self.plan(delivery)
        self.assertEqual(tree(self.home), before)
        return caught.exception


class SourceProvenance(Fixture):
    def test_clean_committed_source_reads_head_objects_without_writing(self):
        os.symlink('README.md', self.source / 'readme-link')   # tracked symlink outside consumed scopes
        self.head = self.commit(self.source, 'outside link')
        exclude = self.source / '.git/info/exclude'
        exclude.parent.mkdir(exist_ok=True)
        with exclude.open('a') as stream:
            stream.write('*.local\n')
        (self.source / 'build.local').write_bytes(b'ignored output outside consumed scopes\n')
        before = tree(self.source)
        source = self.read()
        self.assertEqual(tree(self.source), before)
        self.assertEqual(source.sha, self.head)
        self.assertEqual(source.blobs, {repo: data for repo, data in HEAD.items() if repo != 'README.md'})
        self.assertEqual(source.entries['readme-link'][0], '120000')

    def test_changed_hidden_or_extra_source_state_is_never_clean(self):
        outside = self.tmp / 'same-bytes.md'
        outside.write_bytes(HEAD[RULE])

        def edit(source):
            (source / RULE).write_bytes(b'edited\n')

        def make_executable(source):
            os.chmod(source / RULE, 0o755)

        def drop_executable(source):
            os.chmod(source / 'global-config/hooks/guard.sh', 0o644)

        def staged_only(source):
            (source / RULE).write_bytes(b'staged\n')
            self.git('add', RULE, source=source)
            (source / RULE).write_bytes(HEAD[RULE])

        def assume_unchanged(source):
            self.git('update-index', '--assume-unchanged', RULE, source=source)
            (source / RULE).write_bytes(b'hidden edit\n')

        def skip_worktree(source):
            self.git('update-index', '--skip-worktree', RULE, source=source)
            (source / RULE).write_bytes(b'hidden edit\n')

        def missing_outside_scope(source):
            (source / 'README.md').unlink()

        def same_bytes_symlink(source):
            (source / RULE).unlink()
            os.symlink(outside, source / RULE)

        def symlinked_ancestor(source):
            shutil.move(str(source / '.claude/rules'), str(self.tmp / f'{source.name}-rules'))
            os.symlink(self.tmp / f'{source.name}-rules', source / '.claude/rules')

        def untracked_outside_scope(source):
            (source / 'notes.txt').write_bytes(b'scratch\n')

        def untracked_consumed(source):
            (source / '.claude/rules/extra.md').write_bytes(b'consumed extra\n')

        def ignored_consumed(source):
            (source / '.git/info').mkdir(exist_ok=True)
            (source / '.git/info/exclude').write_text('*.local\n')
            (source / '.claude/skills/s1/notes.local').write_bytes(b'ignored but consumed\n')

        def empty_consumed_directory(source):
            (source / '.claude/skills/s1/empty').mkdir()

        def untracked_consumed_symlink(source):
            os.symlink(self.tmp, source / '.claude/skills/linked')

        cases = [edit, make_executable, drop_executable, staged_only, assume_unchanged, skip_worktree,
                 missing_outside_scope, same_bytes_symlink, symlinked_ancestor, untracked_outside_scope,
                 untracked_consumed, ignored_consumed, empty_consumed_directory, untracked_consumed_symlink]
        for mutate in cases:
            with self.subTest(mutate.__name__):
                source, _, _ = self.make_source(f'dirty-{mutate.__name__}')
                mutate(source)
                with self.assertRaises(update.UpdateError):
                    self.read(source)

    def test_committed_symlink_or_submodule_in_consumed_scope_is_refused(self):
        source, _, head = self.make_source('committed-link')
        os.symlink('core.md', source / '.claude/rules/link.md')
        self.commit(source, 'consumed symlink')
        with self.assertRaises(update.UpdateError):
            self.read(source)
        source, _, head = self.make_source('committed-gitlink')
        self.git('update-index', '--add', '--cacheinfo', f'160000,{head},.claude/vendor', source=source)
        self.git('commit', '-q', '-m', 'gitlink', source=source)
        (source / '.claude/vendor').mkdir()
        with self.assertRaises(update.UpdateError):
            self.read(source)

    def test_replace_refs_cannot_make_other_bytes_look_like_head(self):
        # Honouring the replacement would show the baseline tree as HEAD, matching index and work tree.
        source, baseline, head = self.make_source('replaced')
        self.git('replace', head, baseline, source=source)
        self.git('read-tree', baseline, source=source)
        self.replace_tree(source, BASELINE)
        with self.assertRaises(update.UpdateError):
            self.read(source)

    def test_inherited_git_selectors_and_repository_hooks_are_ignored(self):
        decoy = self.tmp / 'decoy'
        decoy.mkdir()
        self.git('init', '-q', source=decoy)
        put(decoy, 'README.md', b'decoy\n')
        self.commit(decoy, 'decoy')
        sentinel = self.tmp / 'git-program-ran'
        probe = self.tmp / 'probe.sh'
        probe.write_text(f'#!/bin/sh\necho ran >> "{sentinel}"\ncat >/dev/null\n')
        os.chmod(probe, 0o755)
        for key in ('core.fsmonitor', 'filter.probe.clean', 'filter.probe.smudge'):
            self.git('config', key, str(probe))
        (self.source / '.git/info').mkdir(exist_ok=True)
        (self.source / '.git/info/attributes').write_text('* filter=probe\n')
        injected = {'GIT_DIR': str(decoy / '.git'), 'GIT_WORK_TREE': str(decoy),
                    'GIT_INDEX_FILE': str(decoy / '.git/index'), 'GIT_OBJECT_DIRECTORY': str(decoy / '.git/objects'),
                    'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.fsmonitor', 'GIT_CONFIG_VALUE_0': str(probe),
                    'GIT_CONFIG_PARAMETERS': f"'core.fsmonitor'='{probe}'"}
        with patch.dict(os.environ, injected):
            source = self.read()
            self.assertEqual({key: os.environ.get(key) for key in injected}, injected)
        self.assertEqual(source.sha, self.head)
        self.assertEqual(source.blobs[RULE], HEAD[RULE])
        self.assertFalse(sentinel.exists())


class ClaudeBaseline(Fixture):
    def test_ownership_comes_from_the_old_install_mapping_not_its_tree(self):
        source = self.read()
        with update.scrubbed_git_environment():
            baseline = update.load_baseline(source, {'sha': self.git('rev-parse', '--short=7', self.baseline)})
        self.assertEqual(baseline.sha, self.baseline)
        self.assertEqual(baseline.blobs, {rel: BASELINE[repo] for rel, repo in INSTALLED_AT_BASELINE.items()})
        current = update.claude_mapping(source.entries, HEAD['install.sh'].decode(), include_optional_hooks=False)
        self.assertIn('.claude/lib/unmapped.json', current.files)
        self.assertNotIn('.claude/hooks/notify.sh', current.files)
        self.assertNotIn('.claude/settings.json', current.files)

    def test_missing_unknown_corrupt_or_foreign_baselines_are_incomplete(self):
        short = self.git('rev-parse', '--short=7', self.baseline)
        side = self.git('commit-tree', f'{self.head}^{{tree}}', '-m', 'side')
        blob = self.git('rev-parse', f'{self.head}:README.md')
        cases = {
            'absent marker': None,
            'no sha field': b'version=3.2.0\n',
            'unknown sha': b'version=3.2.0\nsha=unknown\n',
            'repeated sha': f'sha={short}\nsha={short}\n'.encode(),
            'malformed line': f'sha={short}\nnot a field\n'.encode(),
            'not a commit': f'sha={blob[:12]}\n'.encode(),
            'outside head history': f'sha={side[:12]}\n'.encode(),
        }
        for name, marker in cases.items():
            with self.subTest(name):
                self.install_baseline(marker)
                self.assertEqual(self.assert_refused(update.Incomplete).status, 'INCOMPLETE')

    def test_ambiguous_abbreviated_baseline_is_incomplete(self):
        # Extend HEAD's own history with empty commits until two share a 4-hex prefix, so a
        # resolver that picked any one candidate would also pass the ancestry check.
        ref = self.git('symbolic-ref', 'HEAD')
        stream = bytearray()
        for index in range(4000):
            message = f'noise {index}\n'.encode()
            stream += f'commit {ref}\ncommitter Fixture <fixture@example.invalid> 0 +0000\n'.encode()
            stream += b'data %d\n' % len(message) + message
            if index == 0:
                stream += f'from {self.head}\n'.encode()
            stream += b'\n'
        self.git('fast-import', '--quiet', data=bytes(stream))
        seen = {}
        collision = None
        for commit in self.git('rev-list', 'HEAD').split():
            if commit[:4] in seen:
                collision = commit
                break
            seen[commit[:4]] = commit
        if collision is None:
            self.fail('fixture produced no 4-hex commit prefix collision')
        source = self.read()
        with update.scrubbed_git_environment():
            self.assertEqual(update.resolve_baseline(source, {'sha': collision}), collision)
            with self.assertRaises(update.Incomplete):
                update.resolve_baseline(source, {'sha': collision[:4]})


class ClaudeBroadPlan(Fixture):
    def setUp(self):
        super().setUp()
        self.install_baseline()

    def test_forward_plan_from_proven_baseline_changes_nothing_and_keeps_personal_state(self):
        os.chmod(self.home / RULE, 0o600)
        home_before, source_before = tree(self.home), tree(self.source)
        plan = self.plan()
        self.assertEqual(tree(self.home), home_before)
        self.assertEqual(tree(self.source), source_before)
        files = [op for op in plan.ops if op.rel != update.MARKER]
        self.assertEqual({(op.action, op.rel) for op in files}, {
            ('write', '.claude/agents/alpha.md'), ('write', '.claude/agents/beta.md'),
            ('write', '.claude/lib/keep.json'), ('write', '.claude/lib/unmapped.json'),
            ('write', RULE), ('write', '.claude/rules/new.md'),
            ('write', '.claude/skills/s1/SKILL.md'), ('write', '.claude/skills/s2/SKILL.md'),
            ('write', '.claude/hooks/guard.sh'),
            ('remove', '.claude/skills/s1/ref/obsolete.md'), ('remove', '.claude/lib/old.json'),
            ('remove', '.claude/agents/retiring.md'), ('remove', '.claude/skills/gone/SKILL.md')})
        by_rel = {op.rel: op for op in files}
        for op in files:
            if op.action == 'write':
                self.assertEqual(op.data, shipped(op.rel), op.rel)
            else:
                self.assertEqual(op.before['digest'], sha256(BASELINE[INSTALLED_AT_BASELINE[op.rel]]), op.rel)
        self.assertEqual(by_rel[RULE].mode, 0o600)
        self.assertEqual(by_rel['.claude/agents/beta.md'].mode, 0o644)
        self.assertEqual(by_rel['.claude/hooks/guard.sh'].mode, 0o755)
        self.assertEqual(by_rel['.claude/agents/alpha.md'].before['digest'], sha256(BASELINE['.claude/agents/alpha.md']))
        # Optional hook bytes stay as selected; settings, CLAUDE.md and personal files are never planned.
        untouchable = set(PERSONAL) | {'.claude/hooks/notify.sh', '.claude/skills/s1/ref/kept.md'}
        self.assertFalse(untouchable & {op.rel for op in plan.ops})
        self.assertTrue(any(self.baseline in note for note in plan.notes))
        for op in plan.ops:
            if op.rel == update.MARKER:
                self.assertEqual(op.action, 'write')
                self.assertGreater(op.order, max(other.order for other in files))
                self.assertIn(b'notifications=enabled\n', op.data)
                self.assertIn(b'analytics=disabled\n', op.data)

    def test_newly_shipped_name_colliding_with_an_existing_entry_is_refused(self):
        cases = {
            'new rule equal to new source': ('.claude/rules/new.md', HEAD['.claude/rules/new.md']),
            'old tree file outside old mapping': ('.claude/lib/unmapped.json', BASELINE['.claude/lib/unmapped.json']),
            'new agent name': ('.claude/agents/beta.md', b'my own beta agent\n'),
            'new skill equal to new source': ('.claude/skills/s2/SKILL.md', HEAD['.claude/skills/s2/SKILL.md']),
            'new skill empty directory': ('.claude/skills/s2', None),
        }
        for name, (rel, data) in cases.items():
            with self.subTest(name):
                self.install_baseline()
                if data is None:
                    (self.home / rel).mkdir(parents=True)
                else:
                    put(self.home, rel, data)
                self.assert_refused()

    def test_modified_or_non_regular_owned_paths_are_refused(self):
        def edit_owned(home):
            (home / RULE).write_bytes(b'my edits to a shipped rule\n')

        def edit_obsolete(home):
            (home / '.claude/skills/s1/ref/obsolete.md').write_bytes(b'my notes in a file the update removes\n')

        def fifo_owned(home):
            (home / RULE).unlink()
            os.mkfifo(home / RULE)

        for mutate in (edit_owned, edit_obsolete, fifo_owned):
            with self.subTest(mutate.__name__):
                self.install_baseline()
                mutate(self.home)
                self.assert_refused()

    def test_extra_entries_in_a_whole_replaced_skill_are_refused(self):
        skill = '.claude/skills/s1'
        outside = self.tmp / 'outside-ref'
        outside.mkdir()
        put(outside, 'kept.md', BASELINE['.claude/skills/s1/ref/kept.md'])

        def hidden_file(home):
            put(home, f'{skill}/.personal-notes', b'hidden\n')

        def empty_directory(home):
            (home / skill / 'scratch').mkdir()

        def symlink_entry(home):
            os.symlink('../mine', home / skill / 'link')

        def symlinked_shipped_directory(home):
            shutil.rmtree(home / skill / 'ref')
            os.symlink(outside, home / skill / 'ref')

        def special_file(home):
            os.mkfifo(home / skill / 'pipe')

        for mutate in (hidden_file, empty_directory, symlink_entry, symlinked_shipped_directory, special_file):
            with self.subTest(mutate.__name__):
                self.install_baseline()
                mutate(self.home)
                outside_before = tree(outside)
                self.assert_refused()
                self.assertEqual(tree(outside), outside_before)

    def test_retired_paths_are_removed_only_with_historical_byte_proof(self):
        retained = {'.claude/lib/old.json': b'{"old": "mine now"}\n',
                    '.claude/agents/retiring.md': b'my retiring agent edits\n',
                    '.claude/lib/never-shipped.json': b'{"personal": true}\n',
                    '.claude/skills/gone/my-notes.md': b'personal file in a retired skill\n'}
        for rel, data in retained.items():
            put(self.home, rel, data)
        before = tree(self.home)
        plan = self.plan()
        self.assertEqual(tree(self.home), before)
        removals = {op.rel for op in plan.ops if op.action == 'remove'}
        self.assertEqual(removals, {'.claude/skills/s1/ref/obsolete.md'})
        self.assertFalse({op.rel for op in plan.ops} & (set(retained) | {'.claude/skills/gone/SKILL.md'}))
        for rel in ('.claude/lib/old.json', '.claude/agents/retiring.md', '.claude/lib/never-shipped.json',
                    '.claude/skills/gone'):
            self.assertTrue(any(rel in note for note in plan.notes), rel)

    def test_symlinked_target_ancestors_are_refused_without_touching_their_targets(self):
        def link_rules(home):
            shutil.move(str(home / '.claude/rules'), str(self.tmp / 'real-rules'))
            os.symlink(self.tmp / 'real-rules', home / '.claude/rules')
            return self.tmp / 'real-rules'

        def link_skill(home):
            shutil.move(str(home / '.claude/skills/s1'), str(self.tmp / 'real-s1'))
            os.symlink(self.tmp / 'real-s1', home / '.claude/skills/s1')
            return self.tmp / 'real-s1'

        def link_claude(home):
            shutil.move(str(home / '.claude'), str(self.tmp / 'real-claude'))
            os.symlink(self.tmp / 'real-claude', home / '.claude')
            return self.tmp / 'real-claude'

        for mutate in (link_rules, link_skill, link_claude):
            with self.subTest(mutate.__name__):
                self.install_baseline()
                real = mutate(self.home)
                real_before = tree(real)
                self.assert_refused()
                self.assertEqual(tree(real), real_before)
                shutil.rmtree(real)

    def test_delivery_manifest_proof_is_used_and_its_refusal_propagates(self):
        class DeliveryError(Exception):
            pass

        def delivery(files=None, error=None):
            def load_manifest(root):
                self.assertEqual(root, self.home / '.claude')
                if error:
                    raise DeliveryError(error)
                return {'files': files}
            return SimpleNamespace(load_manifest=load_manifest, InstallError=DeliveryError)

        delivered = b'new rule as the delivery installer shipped it\n'
        put(self.home, '.claude/rules/new.md', delivered)
        plan = self.plan(delivery({'rules/new.md': sha256(delivered)}))
        writes = {op.rel: op.data for op in plan.ops if op.action == 'write'}
        self.assertEqual(writes['.claude/rules/new.md'], HEAD['.claude/rules/new.md'])
        put(self.home, '.claude/rules/new.md', b'edited after delivery\n')
        self.assert_refused(delivery=delivery({'rules/new.md': sha256(delivered)}))
        self.assert_refused(delivery=delivery(error='corrupt manifest'))


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='framework-update-boundary-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / 'home'
        self.home.mkdir()

    def test_only_existing_home_shaped_directories_are_supported(self):
        self.assertEqual(update.resolve_home(self.home), self.home)
        with patch.dict(os.environ, {'HOME': str(self.home)}):
            self.assertEqual(update.resolve_home(None), self.home)
        for name in ('.claude', '.codex', '.agents'):
            (self.home / name).mkdir()
            with self.subTest(name), self.assertRaises(update.Incomplete):
                update.resolve_home(self.home / name)
        put(self.tmp, 'plain-file', b'x')
        for path in (self.tmp / 'missing', self.tmp / 'plain-file'):
            with self.subTest(path.name), self.assertRaises(update.Incomplete):
                update.resolve_home(path)

    def test_target_paths_refuse_traversal_symlinks_and_special_files(self):
        put(self.home, '.claude/rules/core.md', b'rule\n', 0o640)
        state, data = update.read_regular(self.home, '.claude/rules/core.md')
        self.assertEqual((state['digest'], state['mode'], data), (sha256(b'rule\n'), 0o640, b'rule\n'))
        self.assertEqual(update.read_regular(self.home, '.claude/rules/absent.md'), (None, None))
        os.symlink(self.home / '.claude/rules', self.home / '.claude/linked')
        os.symlink('core.md', self.home / '.claude/rules/leaf.md')
        os.mkfifo(self.home / '.claude/rules/pipe')
        for rel in ('', '/etc/passwd', '../outside', '.claude/../x', '.claude//rules',
                    '.claude/linked/core.md', '.claude/rules/leaf.md', '.claude/rules/core.md/below'):
            with self.subTest(rel), self.assertRaises(update.UpdateError):
                update.read_regular(self.home, rel)
        with self.assertRaises(update.UpdateError):
            update.read_regular(self.home, '.claude/rules/pipe')

    def test_merged_plans_refuse_conflicts_and_publish_manifests_after_files(self):
        first = update.write_op('claude', '.claude/rules/a.md', None, b'a\n', 0o644)
        same = update.Op('claude', '.claude/rules/a.md', 'write', None, b'a\n', 0o755, update.ORDER_DELIVERY_MANIFEST)
        merged = update.merge_ops([[first], [same]])
        self.assertEqual([(op.rel, op.mode, op.order) for op in merged],
                         [('.claude/rules/a.md', 0o644, update.ORDER_DELIVERY_MANIFEST)])
        other = update.write_op('claude', '.claude/rules/a.md', None, b'different\n', 0o644)
        with self.assertRaises(update.UpdateError):
            update.merge_ops([[first], [other]])
        manifests = [update.Op('claude', update.MARKER, 'write', None, b'm', 0o644, update.ORDER_CLAUDE_MARKER),
                     update.Op('codex', update.CODEX_MANIFEST, 'write', None, b'c', 0o644, update.ORDER_CODEX_MANIFEST),
                     update.Op('claude', update.DELIVERY_MANIFEST, 'write', None, b'd', 0o644,
                               update.ORDER_DELIVERY_MANIFEST)]
        files = [update.write_op('codex', '.codex/agents/z.toml', None, b'z', 0o644),
                 update.Op('claude', '.claude/lib/old.json', 'remove', None, None, None, update.ORDER_FILE)]
        ordered = [op.rel for op in update.merge_ops([manifests, files])]
        self.assertEqual(set(ordered[:2]), {op.rel for op in files})
        self.assertEqual(set(ordered[2:]), {op.rel for op in manifests})
        self.assertEqual(ordered.index(update.MARKER), len(ordered) - 1)

    def test_existing_modes_are_kept_and_new_files_take_source_modes(self):
        before = {'digest': sha256(b'x'), 'mode': 0o600, 'uid': os.getuid(), 'gid': os.getgid()}
        self.assertEqual(update.write_op('claude', 'r', before, b'y', 0o644).mode, 0o600)
        hook = update.write_op('claude', 'h', dict(before, mode=0o700), b'y', 0o755).mode
        self.assertEqual((hook & 0o700, hook & 0o066), (0o700, 0))
        self.assertEqual(update.write_op('claude', 'n', None, b'y', 0o755).mode, 0o755)

    def test_marker_fingerprint_ignores_only_the_install_timestamp(self):
        def record(stamp, sha='abc1234'):
            data = f'version=3.2.0\nsha={sha}\ninstalled_at={stamp}\nanalytics=enabled\n'.encode()
            return update.op_record(update.Op('claude', update.MARKER, 'write', None, data, 0o644,
                                              update.ORDER_CLAUDE_MARKER))
        self.assertEqual(record('2026-01-01'), record('2026-11-21'))
        self.assertNotEqual(record('2026-01-01'), record('2026-01-01', sha='def5678'))

    def test_strict_json_refuses_duplicate_keys_and_non_finite_numbers(self):
        self.assertEqual(update.strict_json(b'{"a": {"b": 1}}'), {'a': {'b': 1}})
        for data in (b'{"a": 1, "a": 2}', b'{"a": {"b": 1, "b": 1}}', b'{"a": NaN}', b'[Infinity]'):
            with self.subTest(data), self.assertRaises(ValueError):
                update.strict_json(data)


class SourceProvenanceRegressions(Fixture):
    def test_changed_tracked_symlink_target_outside_consumed_scopes_is_not_clean(self):
        os.symlink('README.md', self.source / 'readme-link')
        self.head = self.commit(self.source, 'outside link')
        self.assertEqual(self.read().sha, self.head)   # control: the committed link target is clean
        (self.source / 'readme-link').unlink()
        os.symlink('install.sh', self.source / 'readme-link')
        with self.assertRaises(update.UpdateError):
            self.read()

    def test_submodule_anywhere_is_unsupported_rather_than_clean(self):
        for present in (True, False):
            with self.subTest(checked_out=present):
                source, _, head = self.make_source(f'outside-gitlink-{present}')
                self.git('update-index', '--add', '--cacheinfo', f'160000,{head},vendor/lib', source=source)
                self.git('commit', '-q', '-m', 'gitlink outside consumed scopes', source=source)
                if present:
                    (source / 'vendor/lib').mkdir(parents=True)
                with self.assertRaises(update.Incomplete):
                    self.read(source)


# ---------------------------------------------------------------------------------------------
# Staged broad forecast, guarded transaction and plan binding against a miniature source whose
# committed install.sh really runs (only ever inside the updater's private staging home).
# ---------------------------------------------------------------------------------------------

DELIVERY_INSTALLER = (ROOT / 'scripts/install-delivery.py').read_bytes()
DELIVERY_RELS = ('.claude/skills/delivery/SKILL.md', '.claude/skills/repo-context/SKILL.md',
                 '.claude/skills/verified-handoff/SKILL.md', '.claude/rules/delivery.md',
                 '.claude/commands/commit-pr.md')
UNCHANGED = '.claude/lib/keep.json'            # owned, identical in baseline and head
KEPT_REF = '.claude/skills/s1/ref/kept.md'     # owned, identical, inside a replaced skill
NEW_SKILL = '.claude/skills/s2/SKILL.md'       # newly shipped: needs a new directory


def staged_tree(version):
    files = {
        '.claude/agents/alpha.md': f'alpha {version}\n'.encode(),
        UNCHANGED: b'{"keep": "same in both versions"}\n',
        RULE: f'core rule {version}\n'.encode(),
        '.claude/skills/s1/SKILL.md': f'skill one {version}\n'.encode(),
        KEPT_REF: b'kept reference\n',
        'global-config/hooks/guard.sh': f'#!/bin/sh\necho guard {version}\n'.encode(),
        'global-config/hooks/notify.sh': b'#!/bin/sh\necho notify\n',
        'scripts/install-delivery.py': DELIVERY_INSTALLER,
        'README.md': b'fixture\n',
    }
    files.update({rel: f'{rel} {version}\n'.encode() for rel in DELIVERY_RELS})
    return files


def fake_entries(paths):
    return {rel: ('100755' if rel in EXECUTABLE else '100644', '0' * 40) for rel in paths}


def broad_installer(mapping, log, settings_snippet='', extra_snippet=''):
    """A miniature install.sh --update body: records what it saw, then copies its own mapping."""
    lines = ['SRC="$(cd "$(dirname "$0")" && pwd -P)"', f'LOG={shlex.quote(str(log))}',
             'printf "%s\\n" "$*" >> "$LOG/argv"', 'printf "%s\\n" "$HOME" >> "$LOG/home"', 'env > "$LOG/env"',
             '(cd "$HOME" && find . -type f -o -type l) > "$LOG/inputs"',
             'if [ -f "$HOME/.claude/.sdlc-delivery/manifest.json" ]; then',
             '    cp "$HOME/.claude/.sdlc-delivery/manifest.json" "$LOG/seen-delivery-manifest"',
             'fi']
    for target, repo in sorted(mapping.items()):
        lines += [f'mkdir -p "$HOME/{posixpath.dirname(target)}"', f'cp "$SRC/{repo}" "$HOME/{target}"',
                  f'chmod {755 if repo in EXECUTABLE else 644} "$HOME/{target}"']
    lines += ['SHA="$(git -C "$SRC" rev-parse --short=7 HEAD)"',
              'SEL="$(grep -E \'^(analytics|watchdog|notifications)=\' "$HOME/.claude/.framework-version" || true)"',
              "printf 'version=3.3.0\\nsha=%s\\n%s\\ninstalled_at=2026-11-21T00:00:00Z\\n' \"$SHA\" \"$SEL\" "
              '> "$HOME/.claude/.framework-version"',
              'printf "%s\\n" "$SRC" > "$HOME/.claude/.framework-path"']
    lines += [snippet for snippet in (settings_snippet, extra_snippet) if snippet]
    return ('\n'.join(lines) + '\n').encode()


def rewrite_plan(path, document):
    path.unlink()
    update.write_private(path, (json.dumps(document, indent=2, sort_keys=True) + '\n').encode())


class StagedFixture(Fixture):
    def setUp(self):
        super().setUp()
        for key in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR'):
            os.environ.pop(key, None)
        self.log = self.tmp / 'stage-log'
        self.make_staged_source('staged')
        self.install_staged()

    def reset_log(self):
        if self.log.exists():
            shutil.rmtree(self.log)
        self.log.mkdir()

    def make_staged_source(self, name, settings_snippet='', extra_snippet=''):
        arrays = installer(['alpha'], ['keep.json'])
        base = staged_tree('v1')
        base['install.sh'] = arrays
        head = staged_tree('v2')
        head[NEW_SKILL] = b'skill two\n'
        mapping = update.claude_mapping(fake_entries([*head, 'install.sh']), arrays.decode(),
                                        include_optional_hooks=False).files
        head['install.sh'] = arrays + broad_installer(mapping, self.log, settings_snippet, extra_snippet)
        source = self.tmp / name
        source.mkdir()
        self.git('init', '-q', source=source)
        self.replace_tree(source, base)
        baseline = self.commit(source, 'baseline')
        self.replace_tree(source, head)
        self.source, self.baseline, self.head = source, baseline, self.commit(source, 'head')
        self.base_files, self.head_files, self.head_mapping = base, head, mapping
        self.reset_log()

    def install_staged(self, delivery=True):
        """A home as the baseline install.sh (and, if manifested, the delivery installer) left it."""
        if self.home.exists():
            shutil.rmtree(self.home)
        self.home.mkdir(mode=0o700)
        old = update.claude_mapping(fake_entries(self.base_files), self.base_files['install.sh'].decode(),
                                    include_optional_hooks=True).files
        for rel, repo in old.items():
            put(self.home, rel, self.base_files[repo], 0o755 if repo in EXECUTABLE else 0o644)
        put(self.home, update.MARKER, self.marker())
        for rel, data in PERSONAL.items():
            put(self.home, rel, data)
        if delivery:
            manifest = {'version': 1, 'source_sha': self.baseline, 'consumed_source_dirty': False,
                        'consumed_source_scopes': [], 'whole_tree_state': 'not-inspected',
                        'files': {rel.removeprefix('.claude/'): sha256(self.base_files[rel]) for rel in DELIVERY_RELS},
                        'adopted': {}, 'dirs': []}
            put(self.home, update.DELIVERY_MANIFEST,
                (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(), 0o600)

    def build(self, requested=None):
        with update.scrubbed_git_environment():
            return update.build_plan(self.home, self.source, requested)

    def transact(self, plan):
        with update.scrubbed_git_environment():
            return update.run_transaction(self.home, plan)

    def staged_homes(self):
        path = self.log / 'home'
        return path.read_text().splitlines() if path.exists() else []

    def live_tree(self):
        return {rel: entry for rel, entry in tree(self.home).items() if rel.split('/')[0] != update.STATE_DIR}

    def cli(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch('builtins.input', side_effect=AssertionError('prompted')):
            code = update.main([str(arg) for arg in argv])
        return code, output.getvalue()

    def assert_published(self, plan):
        for op in plan.ops:
            state, data = update.read_regular(self.home, op.rel)
            if op.action == 'remove':
                self.assertIsNone(state, op.rel)
            else:
                self.assertEqual((data, state['mode']), (op.data, op.mode), op.rel)


class StagedForecastChecks(StagedFixture):
    def test_manifested_delivery_is_staged_before_the_broad_update_in_one_private_home(self):
        before = tree(self.home)
        plan = self.build()
        self.assertEqual(tree(self.home), before)
        homes = self.staged_homes()
        self.assertEqual(len(homes), 1)
        staged_home = Path(homes[0])
        self.assertNotEqual(staged_home, self.home)
        self.assertNotIn(self.home, staged_home.parents)
        self.assertFalse(staged_home.exists())
        seen = self.log / 'seen-delivery-manifest'
        self.assertTrue(seen.exists(), 'the broad update ran without the manifested delivery update staged first')
        staged_manifest = update.strict_json(seen.read_bytes())
        self.assertEqual(staged_manifest['source_sha'], self.head)
        self.assertEqual(staged_manifest['files'], {rel.removeprefix('.claude/'): sha256(self.head_files[rel])
                                                    for rel in DELIVERY_RELS})
        # The published delivery manifest describes exactly the delivery bytes this plan publishes.
        by_rel = {op.rel: op for op in plan.ops}
        published = update.strict_json(by_rel[update.DELIVERY_MANIFEST].data)
        self.assertEqual(published['files'], {rel.removeprefix('.claude/'): sha256(by_rel[rel].data)
                                              for rel in DELIVERY_RELS})

    def test_unmanifested_claude_home_never_stages_or_adopts_delivery(self):
        self.install_staged(delivery=False)
        plan = self.build()
        self.assertIsNone(plan.delivery)
        self.assertFalse((self.log / 'seen-delivery-manifest').exists())
        self.assertNotIn(update.DELIVERY_MANIFEST, {op.rel for op in plan.ops})
        self.assertFalse(update.exists(self.home, update.DELIVERY_MANIFEST))

    def test_refused_delivery_inputs_never_reach_staging(self):
        outside = self.tmp / 'manifest-copy.json'

        def edited_delivery_file(home):
            (home / '.claude/rules/delivery.md').write_bytes(b'my delivery rule edits\n')

        def corrupt_manifest(home):
            (home / update.DELIVERY_MANIFEST).write_bytes(b'{"version": 1, "files": ')

        def symlinked_manifest(home):
            shutil.copy(home / update.DELIVERY_MANIFEST, outside)
            (home / update.DELIVERY_MANIFEST).unlink()
            os.symlink(outside, home / update.DELIVERY_MANIFEST)

        for mutate in (edited_delivery_file, corrupt_manifest, symlinked_manifest):
            with self.subTest(mutate.__name__):
                self.install_staged()
                self.reset_log()
                mutate(self.home)
                before = tree(self.home)
                with self.assertRaises(update.UpdateError):
                    self.build()
                self.assertEqual(tree(self.home), before)
                self.assertEqual(self.staged_homes(), [])

    def test_staging_copies_only_safe_inputs_with_a_minimal_environment_and_no_flags(self):
        private = {'.claude/.credentials.json': b'{"token": "CREDENTIAL-SENTINEL"}\n', '.env': b'KEY=ENV-FILE-SENTINEL\n',
                   '.claude/.env': b'KEY=ENV-FILE-SENTINEL\n', '.claude/sessions/s1.jsonl': b'{"session": 1}\n',
                   '.claude/projects/p/transcript.jsonl': b'{"transcript": 1}\n'}
        for rel, data in private.items():
            put(self.home, rel, data, 0o600)
        secrets = {'ANTHROPIC_API_KEY': 'ENV-SECRET-SENTINEL-1', 'CLAUDE_CODE_OAUTH_TOKEN': 'ENV-SECRET-SENTINEL-2'}
        with patch.dict(os.environ, secrets):
            self.build()
        inputs = {line.removeprefix('./') for line in (self.log / 'inputs').read_text().splitlines()}
        allowed = ({update.SETTINGS, update.MARKER, update.PATH_MARKER, update.DELIVERY_MANIFEST}
                   | set(DELIVERY_RELS) | set(self.head_mapping))
        self.assertLessEqual(inputs, allowed)
        self.assertLessEqual({update.SETTINGS, update.MARKER}, inputs)
        self.assertFalse(inputs & (set(private) | set(PERSONAL) - {update.SETTINGS}))
        self.assertEqual(set((self.log / 'argv').read_text().splitlines()), {'--update'})
        environment = (self.log / 'env').read_text()
        for value in secrets.values():
            self.assertNotIn(value, environment)
        names = {line.partition('=')[0] for line in environment.splitlines()}
        self.assertFalse({name for name in names if name.startswith(('ANTHROPIC', 'CLAUDE', 'CODEX'))})
        self.assertIn(f'HOME={self.staged_homes()[0]}', environment.splitlines())

    def test_unexpected_staged_output_is_refused_although_the_installer_exits_zero(self):
        self.make_staged_source('stray', extra_snippet='printf "x\\n" > "$HOME/.claude/stray.json"')
        self.install_staged()
        before = tree(self.home)
        with self.assertRaises(update.UpdateError):
            self.build()
        self.assertEqual(len(self.staged_homes()), 1)   # it ran and succeeded
        self.assertEqual(tree(self.home), before)

    def test_staged_home_alias_is_comparison_data_only_and_settings_bytes_stay_exact(self):
        template = json.dumps({'hooks': {'PreToolUse': [{'command': '%s/.claude/hooks/guard.sh'}]},
                               'model': 'personal'}, indent=4) + '\n'
        snippet = 'printf ' + shlex.quote(template) + ' "$HOME" > "$HOME/.claude/settings.json"'
        self.make_staged_source('alias', settings_snippet=snippet)
        self.install_staged()
        live = json.dumps({'model': 'personal',
                           'hooks': {'PreToolUse': [{'command': f'{self.home}/.claude/hooks/guard.sh'}]}}).encode()
        put(self.home, update.SETTINGS, live, 0o600)
        before = tree(self.home)
        plan = self.build()
        staged_home = self.staged_homes()[0]
        self.assertEqual(tree(self.home), before)
        self.assertNotIn(update.SETTINGS, {op.rel for op in plan.ops})
        self.assertEqual(plan.guards[update.SETTINGS]['digest'], sha256(live))
        self.assertNotIn(staged_home, json.dumps(update.plan_document(plan)))
        for op in plan.ops:
            if op.data is not None:
                self.assertNotIn(staged_home.encode(), op.data, op.rel)

    def test_settings_refusals_never_echo_private_keys(self):
        changed, duplicate = 'PRIVATE-CHANGED-KEY-SENTINEL', 'PRIVATE-DUPLICATE-KEY-SENTINEL'
        widened = dict(json.loads(PERSONAL[update.SETTINGS]), **{changed: True})
        cases = {
            'installer would add a private key': (
                'printf "%s\\n" ' + shlex.quote(json.dumps(widened)) + ' > "$HOME/.claude/settings.json"',
                None, changed),
            'live settings repeat a private key': (
                '', f'{{"model": "personal", "{duplicate}": 1, "{duplicate}": 2}}\n'.encode(), duplicate),
        }
        for index, (name, (snippet, live, sentinel)) in enumerate(cases.items()):
            with self.subTest(name):
                self.make_staged_source(f'settings-{index}', settings_snippet=snippet)
                self.install_staged()
                if live is not None:
                    put(self.home, update.SETTINGS, live, 0o600)
                before = tree(self.home)
                with self.assertRaises(update.UpdateError) as caught:
                    self.build()
                self.assertNotIn(sentinel, str(caught.exception))
                code, output = self.cli('plan', '--source', self.source, '--home', self.home)
                self.assertNotEqual(code, 0)
                self.assertNotIn(sentinel, output)
                self.assertEqual(tree(self.home), before)


class GuardedTransaction(StagedFixture):
    def test_forward_update_backs_up_first_then_publishes_files_before_manifests(self):
        plan = self.build()
        personal = {rel: (self.home / rel).read_bytes() for rel in PERSONAL}
        optional_hook = (self.home / '.claude/hooks/notify.sh').read_bytes()
        published, backup_ready = [], []
        real_replace = os.replace

        def recording(src, dst, *args, **kwargs):
            published.append(Path(dst).relative_to(self.home).as_posix())
            backup_ready.append(any((self.home / update.STATE_DIR / 'backups').glob('*/backup.json')))
            return real_replace(src, dst, *args, **kwargs)

        with patch('os.replace', recording):
            result = self.transact(plan)
        self.assertEqual((result['status'], result['executed']), ('PASS', True), result['error'])
        self.assertTrue(backup_ready and all(backup_ready))
        writes = {op.rel for op in plan.ops if op.action == 'write'}
        sequence = [rel for rel in published if rel in writes]
        self.assertEqual(sorted(sequence), sorted(writes))
        self.assertEqual(sequence[-1], update.MARKER)
        files = [index for index, rel in enumerate(sequence)
                 if rel not in (update.MARKER, update.PATH_MARKER, update.DELIVERY_MANIFEST)]
        self.assertGreater(sequence.index(update.DELIVERY_MANIFEST), max(files))
        self.assert_published(plan)
        self.assertEqual({rel: (self.home / rel).read_bytes() for rel in PERSONAL}, personal)
        self.assertEqual((self.home / '.claude/hooks/notify.sh').read_bytes(), optional_hook)
        backup = Path(result['backup'])
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((backup / 'backup.json').stat().st_mode), 0o600)
        entries = {entry['path']: entry for entry in update.strict_json((backup / 'backup.json').read_bytes())['entries']}
        for op in plan.ops:
            if op.before is None:
                self.assertIsNone(entries[op.rel]['copy'], op.rel)
            else:
                self.assertEqual(sha256((backup / entries[op.rel]['copy']).read_bytes()), op.before['digest'], op.rel)

    def test_failure_after_one_write_restores_only_this_updates_output(self):
        plan = self.build()
        before = self.live_tree()
        calls = []
        real_replace = os.replace

        def failing(src, dst, *args, **kwargs):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError(errno.EIO, 'injected failure', os.fspath(dst))
            return real_replace(src, dst, *args, **kwargs)

        with patch('os.replace', failing):
            result = self.transact(plan)
        self.assertEqual((result['status'], result['executed'], result['recovery']), ('FAIL', True, 'rolled-back'))
        self.assertEqual(result['unrecovered'], [])
        self.assertEqual(self.live_tree(), before)
        self.assertTrue((Path(result['backup']) / 'backup.json').is_file())

    def test_concurrent_edit_after_a_write_is_preserved_for_manual_recovery(self):
        plan = self.build()
        before = self.live_tree()
        calls = []
        real_replace = os.replace

        def racing(src, dst, *args, **kwargs):
            calls.append(dst)
            if len(calls) == 1:
                real_replace(src, dst, *args, **kwargs)
                Path(dst).write_bytes(b'another writer\n')
                return None
            if len(calls) == 2:
                raise OSError(errno.EIO, 'injected failure', os.fspath(dst))
            return real_replace(src, dst, *args, **kwargs)

        with patch('os.replace', racing):
            result = self.transact(plan)
        first = Path(calls[0]).relative_to(self.home).as_posix()
        self.assertIn(first, before)
        self.assertEqual((result['status'], result['recovery']), ('INCOMPLETE', 'manual-required'))
        self.assertTrue(any(first in problem for problem in result['unrecovered']), result['unrecovered'])
        expected = dict(before)
        expected[first] = ('file', before[first][1], b'another writer\n')
        self.assertEqual(self.live_tree(), expected)
        backup = Path(result['backup'])
        entries = {entry['path']: entry for entry in update.strict_json((backup / 'backup.json').read_bytes())['entries']}
        self.assertEqual((backup / entries[first]['copy']).read_bytes(), before[first][2])

    def test_failed_directory_creation_never_claims_or_deletes_a_concurrent_file(self):
        plan = self.build()
        before = self.live_tree()
        skill_dir = self.home / posixpath.dirname(NEW_SKILL)
        real_mkdir = os.mkdir

        def mkdir(path, *args, **kwargs):
            if Path(path) == skill_dir:
                real_mkdir(path)
                (skill_dir / 'SKILL.md').write_bytes(b'written by another process\n')
                raise OSError(errno.EACCES, 'injected mkdir failure', os.fspath(path))
            return real_mkdir(path, *args, **kwargs)

        with patch('os.mkdir', mkdir):
            result = self.transact(plan)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['unrecovered'], [])
        self.assertEqual((self.home / NEW_SKILL).read_bytes(), b'written by another process\n')
        after = {rel: entry for rel, entry in self.live_tree().items() if not rel.startswith(posixpath.dirname(NEW_SKILL))}
        self.assertEqual(after, before)

    def test_drift_between_plan_and_first_write_refuses_before_any_write(self):
        cases = {
            'unchanged owned file bytes': lambda: (self.home / UNCHANGED).write_bytes(b'{"keep": "edited"}\n'),
            'unchanged owned file mode': lambda: os.chmod(self.home / UNCHANGED, 0o600),
            'unchanged file inside a replaced skill': lambda: (self.home / KEPT_REF).write_bytes(b'edited reference\n'),
            'hidden entry in a replaced skill': lambda: put(self.home, '.claude/skills/s1/.notes', b'mine\n'),
            'empty directory in a replaced skill': lambda: (self.home / '.claude/skills/s1/scratch').mkdir(),
            'settings.json': lambda: (self.home / update.SETTINGS).write_bytes(b'{"model": "changed"}\n'),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                self.install_staged()
                self.reset_log()
                plan = self.build()
                mutate()
                before = self.live_tree()
                result = self.transact(plan)
                self.assertIn(result['status'], ('FAIL', 'INCOMPLETE'))
                self.assertIs(result['executed'], False)
                self.assertEqual(self.live_tree(), before)


class PlanBinding(StagedFixture):
    def write_plan(self):
        plans = self.tmp / 'plans'
        plans.mkdir(exist_ok=True)
        os.chmod(plans, 0o700)
        path = plans / f'plan-{len(list(plans.iterdir()))}.json'
        code, output = self.cli('plan', '--source', self.source, '--home', self.home, '--out', path)
        self.assertEqual(code, 0, output)
        return path, json.loads(output)

    def assert_not_applied(self, plan_path, before):
        code, output = self.cli('apply', '--plan', plan_path)
        document = json.loads(output)
        self.assertNotEqual(code, 0, output)
        self.assertIn(document['status'], ('FAIL', 'INCOMPLETE'))
        self.assertIs(document['executed'], False)
        self.assertEqual(tree(self.home), before)

    def test_cli_plan_is_read_only_and_never_prints_settings_or_environment(self):
        put(self.home, update.SETTINGS, b'{"model": "SETTINGS-VALUE-SENTINEL"}\n', 0o600)
        user_home = self.tmp / 'user'
        before, user_before = tree(self.home), tree(user_home)
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'ENV-SECRET-SENTINEL'}):
            code, output = self.cli('plan', '--source', self.source, '--home', self.home)
        document = json.loads(output)
        self.assertEqual((code, document['status'], document['executed']), (0, 'PLAN_READY', False))
        self.assertEqual(set(document), update.PLAN_KEYS)
        self.assertEqual(document['source'], {'path': str(self.source), 'sha': self.head})
        self.assertNotIn(update.SETTINGS, {op['path'] for op in document['operations']})
        for sentinel in ('SETTINGS-VALUE-SENTINEL', 'ENV-SECRET-SENTINEL', self.staged_homes()[0]):
            self.assertNotIn(sentinel, output)
        self.assertEqual(tree(self.home), before)
        self.assertEqual(tree(user_home), user_before)
        path, stdout_document = self.write_plan()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_bytes()), stdout_document)
        self.assertEqual(tree(self.home), before)

    def test_tampered_plan_documents_are_refused_before_any_mutation(self):
        cases = {
            'fingerprint': lambda document: document.update(fingerprint='f' * 64),
            'source sha': lambda document: document['source'].update(sha=self.baseline),
            'editions': lambda document: document.update(editions=['claude', 'codex']),
            'dropped operation': lambda document: document['operations'].pop(),
            'injected removal': lambda document: document['operations'].append(
                {'edition': 'claude', 'path': '.claude/rules/personal.md', 'action': 'remove'}),
            'target inode': lambda document: document['target'].update(inode=document['target']['inode'] + 1),
        }
        for name, tamper in cases.items():
            with self.subTest(name):
                self.install_staged()
                path, document = self.write_plan()
                tamper(document)
                rewrite_plan(path, document)
                self.assert_not_applied(path, tree(self.home))

    def test_target_drift_after_review_is_refused_before_any_mutation(self):
        def replace_home():
            moved = self.tmp / 'home-moved'
            shutil.move(str(self.home), str(moved))
            shutil.copytree(moved, self.home, symlinks=True)

        cases = {
            'planned file bytes': lambda: (self.home / RULE).write_bytes(b'edited after review\n'),
            'planned file mode': lambda: os.chmod(self.home / RULE, 0o600),
            'unchanged owned file mode': lambda: os.chmod(self.home / UNCHANGED, 0o600),
            'unchanged file inside a replaced skill': lambda: (self.home / KEPT_REF).write_bytes(b'edited\n'),
            'new hidden entry in a replaced skill': lambda: put(self.home, '.claude/skills/s1/.notes', b'mine\n'),
            'target home replaced by a copy': replace_home,
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                self.install_staged()
                path, _ = self.write_plan()
                mutate()
                self.assert_not_applied(path, tree(self.home))

    def test_reviewed_plan_applies_and_reports_the_real_result(self):
        path, _ = self.write_plan()
        plan = self.build()
        personal = {rel: (self.home / rel).read_bytes() for rel in PERSONAL}
        code, output = self.cli('apply', '--plan', path)
        document = json.loads(output)
        self.assertEqual((code, document['status'], document['executed']), (0, 'PASS', True), output)
        self.assertEqual(document['fingerprint'], plan.fingerprint)
        self.assert_published(plan)
        self.assertEqual({rel: (self.home / rel).read_bytes() for rel in PERSONAL}, personal)
        for rel in (update.LOCK, *update.FOREIGN_LOCKS):
            self.assertIsNone(update.entry_kind(self.home / rel), rel)
        self.assertTrue(Path(document['backup']).is_dir())
        code, output = self.cli('plan', '--source', self.source, '--home', self.home)
        self.assertEqual((code, json.loads(output)['operations']), (0, []))


def plan_document_fixture():
    return {'schema': update.SCHEMA, 'status': 'PLAN_READY', 'executed': False,
            'source': {'path': '/src', 'sha': 'a' * 40}, 'target': {'home': '/home/x', 'device': 1, 'inode': 2},
            'editions': ['claude'], 'fingerprint': 'b' * 64,
            'operations': [{'edition': 'claude', 'path': '.claude/rules/core.md', 'action': 'write'}],
            'notes': [], 'limits': list(update.LIMITS)}


class PlanFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='framework-update-plan-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.private = self.tmp / 'private'
        self.private.mkdir()
        os.chmod(self.private, 0o700)

    def test_plan_file_round_trips_privately_and_is_never_overwritten(self):
        path = update.write_plan_file(self.private / 'plan.json', plan_document_fixture())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(update.load_plan_file(path), plan_document_fixture())
        with self.assertRaises(update.UpdateError):
            update.write_plan_file(path, dict(plan_document_fixture(), notes=['replaced']))
        self.assertEqual(update.load_plan_file(path), plan_document_fixture())

    def test_widened_or_malformed_plan_documents_are_refused(self):
        def changed(mutate):
            document = plan_document_fixture()
            mutate(document)
            return json.dumps(document, indent=2).encode()

        def operation(**fields):
            return changed(lambda document: document['operations'][0].update(fields))

        raw = json.dumps(plan_document_fixture(), indent=2)
        cases = {
            'unknown top-level key': changed(lambda document: document.update(argv=['/bin/sh', '-c', 'true'])),
            'missing key': changed(lambda document: document.pop('limits')),
            'executed true': changed(lambda document: document.update(executed=True)),
            'boolean device': changed(lambda document: document['target'].update(device=True)),
            'boolean inode': changed(lambda document: document['target'].update(inode=False)),
            'extra target key': changed(lambda document: document['target'].update(uid=0)),
            'abbreviated source sha': changed(lambda document: document['source'].update(sha='a' * 12)),
            'uppercase fingerprint': changed(lambda document: document.update(fingerprint='B' * 64)),
            'repeated edition': changed(lambda document: document.update(editions=['claude', 'claude'])),
            'unknown edition': changed(lambda document: document.update(editions=['other'])),
            'no edition': changed(lambda document: document.update(editions=[])),
            'operation payload': operation(data='cGF5bG9hZA=='),
            'operation traversal': operation(path='.claude/../.ssh/authorized_keys'),
            'absolute operation path': operation(path='/etc/passwd'),
            'operation outside framework roots': operation(path='Library/LaunchAgents/x.plist'),
            'unknown action': operation(action='chmod'),
            'duplicate key': raw.replace('"executed": false', '"executed": false,\n  "executed": false', 1).encode(),
            'non-finite number': raw.replace('"device": 1', '"device": NaN', 1).encode(),
            'not an object': b'[]\n',
        }
        for index, (name, data) in enumerate(cases.items()):
            with self.subTest(name):
                path = self.private / f'case-{index}.json'
                update.write_private(path, data)
                with self.assertRaises(update.UpdateError):
                    update.load_plan_file(path)

    def test_symlinked_leaf_or_ancestor_and_loose_permissions_are_refused(self):
        good = update.write_plan_file(self.private / 'plan.json', plan_document_fixture())
        os.symlink(good, self.private / 'leaf-link.json')
        outside = self.tmp / 'outside.json'
        outside.write_bytes(b'keep\n')
        os.symlink(outside, self.private / 'out-link.json')
        alias = self.tmp / 'alias'
        os.symlink(self.tmp, alias)
        loose = self.tmp / 'loose'
        loose.mkdir()
        os.chmod(loose, 0o755)
        update.write_private(loose / 'plan.json', json.dumps(plan_document_fixture()).encode())
        for name, path in {'leaf symlink': self.private / 'leaf-link.json',
                           'symlinked ancestor': alias / 'private/plan.json',
                           'shared directory': loose / 'plan.json'}.items():
            with self.subTest(f'load through {name}'), self.assertRaises(update.UpdateError):
                update.load_plan_file(path)
        for name, path in {'leaf symlink': self.private / 'out-link.json',
                           'symlinked ancestor': alias / 'private/new.json',
                           'shared directory': loose / 'new.json'}.items():
            with self.subTest(f'write through {name}'), self.assertRaises(update.UpdateError):
                update.write_plan_file(path, plan_document_fixture())
        self.assertEqual(outside.read_bytes(), b'keep\n')
        self.assertFalse((self.private / 'new.json').exists())
        self.assertFalse((loose / 'new.json').exists())
        os.chmod(good, 0o644)
        with self.assertRaises(update.UpdateError):
            update.load_plan_file(good)

    def test_target_home_reached_through_a_symlink_is_refused(self):
        home = self.tmp / 'home'
        home.mkdir()
        self.assertEqual(update.resolve_home(home), home)
        os.symlink(home, self.tmp / 'home-alias')
        os.symlink(self.tmp, self.tmp / 'parent-alias')
        for raw in (self.tmp / 'home-alias', self.tmp / 'parent-alias/home'):
            with self.subTest(raw.name), self.assertRaises(update.UpdateError):
                update.resolve_home(raw)


class CooperativeLocks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='framework-update-lock-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / 'home'

    def fresh_home(self):
        if self.home.exists():
            shutil.rmtree(self.home)
        (self.home / '.claude').mkdir(parents=True)

    def test_own_and_installer_locks_are_held_then_released(self):
        self.fresh_home()
        before, notes = tree(self.home), []
        with update.held_locks(self.home, notes):
            for rel in (update.LOCK, *update.FOREIGN_LOCKS):
                self.assertIsNotNone(update.entry_kind(self.home / rel), rel)
        self.assertEqual((tree(self.home), notes), (before, []))

    def test_present_locks_refuse_and_are_never_removed(self):
        def own_lock(home):
            put(home, update.LOCK, b'1 0\n', 0o600)

        def install_lock_directory(home):
            put(home, '.claude/.install.lock.d/pid', b'1\n', 0o600)

        def delivery_lock(home):
            put(home, '.claude/.sdlc-delivery.lock', b'1\n', 0o600)

        def codex_lock(home):
            put(home, '.sdlc-codex-install.lock', b'1\n', 0o600)

        for present in (own_lock, install_lock_directory, delivery_lock, codex_lock):
            with self.subTest(present.__name__):
                self.fresh_home()
                present(self.home)
                before = tree(self.home)
                with self.assertRaises(update.Incomplete):
                    with update.held_locks(self.home, []):
                        self.fail('entered while another lock was present')
                self.assertEqual(tree(self.home), before)

    def test_lock_taken_over_while_held_is_left_in_place_and_reported(self):
        self.fresh_home()
        notes = []
        with update.held_locks(self.home, notes):
            (self.home / update.LOCK).write_bytes(b'another run\n')
        self.assertEqual((self.home / update.LOCK).read_bytes(), b'another run\n')
        self.assertTrue(notes)
        for rel in update.FOREIGN_LOCKS:
            self.assertIsNone(update.entry_kind(self.home / rel), rel)


# ---------------------------------------------------------------------------------------------
# Codex: the native planner's broad .codex/framework/ namespace is not updater ownership.
# ---------------------------------------------------------------------------------------------

CODEX_V1 = {'.codex/agents/sdlc-alpha.toml': b'name = "alpha"\nversion = 1\n',
            '.codex/framework/rules.md': b'rules v1\n',
            '.agents/skills/sdlc-one/SKILL.md': b'skill one v1\n'}
CODEX_V2 = {'.codex/agents/sdlc-alpha.toml': b'name = "alpha"\nversion = 2\n',
            '.codex/framework/rules.md': b'rules v2\n',
            '.agents/skills/sdlc-one/SKILL.md': b'skill one v2\n'}
CODEX_PRIVATE = {
    '.codex/framework/lint-projects.json': b'{"projects": {"/work/PRIVATE-REGISTRY-SENTINEL": "approved"}}\n',
    '.codex/framework/events.jsonl': b'{"event": "PRIVATE-EVENT-SENTINEL"}\n',
    '.codex/framework/runtime/session.json': b'{"session": "PRIVATE-RUNTIME-SENTINEL"}\n',
}
CODEX_PERSONAL = b'Personal Codex notes\n'


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'codex/framework.py requires PyYAML')
class CodexOwnership(Fixture):
    def setUp(self):
        super().setUp()
        os.environ.pop('CODEX_HOME', None)
        framework = (ROOT / 'codex/framework.py').read_bytes()
        framework += b'\n\ndef build():\n    return ' + repr(CODEX_V2).encode() + b'\n'
        source = self.tmp / 'codex-source'
        source.mkdir()
        self.git('init', '-q', source=source)
        put(source, 'codex/framework.py', framework)
        put(source, 'README.md', b'codex fixture\n')
        self.commit(source, 'codex')
        self.codex_source = source
        with update.scrubbed_git_environment():
            module = update.load_source_module(update.read_source(source), 'codex/framework.py', 'fixture_codex')
        self.instructions = module.instructions()

    def install_codex(self, manifested=()):
        if self.home.exists():
            shutil.rmtree(self.home)
        self.home.mkdir(mode=0o700)
        files = {}
        for rel, data in CODEX_V1.items():
            put(self.home, rel, data)
            files[rel] = sha256(data)
        for rel, data in CODEX_PRIVATE.items():
            put(self.home, rel, data, 0o600)
            if rel in manifested:
                files[rel] = sha256(data)
        put(self.home, '.codex/AGENTS.md', CODEX_PERSONAL + self.instructions)
        manifest = {'version': 1, 'source_sha': '0' * 40, 'files': files, 'instructions': sha256(self.instructions),
                    'hooks': False, 'user': True}
        put(self.home, update.CODEX_MANIFEST, (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(), 0o600)

    def plan_with_spies(self):
        """Plan the Codex edition while recording native-planner calls and every opened path."""
        planner_calls, opened = [], []
        real_loader, real_os_open, real_path_open = update.load_source_module, os.open, Path.open

        def loader(source, rel, name):
            module = real_loader(source, rel, name)
            if rel == 'codex/framework.py':
                native = module.plan_installation

                def spy(*args, **kwargs):
                    planner_calls.append(args)
                    return native(*args, **kwargs)
                module.plan_installation = spy
            return module

        def os_open(path, *args, **kwargs):
            opened.append(os.fsdecode(path))
            return real_os_open(path, *args, **kwargs)

        def path_open(path, *args, **kwargs):
            opened.append(str(path))
            return real_path_open(path, *args, **kwargs)

        try:
            with patch.object(update, 'load_source_module', loader), patch('os.open', os_open), \
                    patch.object(Path, 'open', path_open), update.scrubbed_git_environment():
                outcome = update.build_plan(self.home, self.codex_source, 'codex')
        except update.UpdateError as err:
            outcome = err
        return outcome, planner_calls, opened

    def test_shipped_manifest_plans_and_applies_only_shipped_resources(self):
        self.install_codex()
        before = tree(self.home)
        plan, calls, opened = self.plan_with_spies()
        self.assertIsInstance(plan, update.UpdatePlan)
        self.assertTrue(calls)
        self.assertEqual(tree(self.home), before)
        self.assertEqual({(op.action, op.rel) for op in plan.ops},
                         {('write', rel) for rel in CODEX_V2} | {('write', update.CODEX_MANIFEST)})
        self.assertFalse([path for path in opened if any(path.endswith(rel) for rel in CODEX_PRIVATE)])
        with update.scrubbed_git_environment():
            result = update.run_transaction(self.home, plan)
        self.assertEqual((result['status'], result['executed']), ('PASS', True), result['error'])
        for rel, data in CODEX_V2.items():
            self.assertEqual((self.home / rel).read_bytes(), data, rel)
        for rel, data in CODEX_PRIVATE.items():
            self.assertEqual((self.home / rel).read_bytes(), data, rel)
        self.assertEqual((self.home / '.codex/AGENTS.md').read_bytes(), CODEX_PERSONAL + self.instructions)
        manifest = update.strict_json((self.home / update.CODEX_MANIFEST).read_bytes())
        self.assertEqual(manifest['files'], {rel: sha256(data) for rel, data in CODEX_V2.items()})

    def test_manifested_private_approval_or_runtime_state_is_refused_before_any_read(self):
        for rel in CODEX_PRIVATE:
            with self.subTest(rel):
                self.install_codex(manifested={rel})
                before = tree(self.home)
                outcome, calls, opened = self.plan_with_spies()
                self.assertIsInstance(outcome, update.UpdateError, 'protected state was planned as framework-owned')
                self.assertEqual(calls, [], 'the native broad-namespace planner was reached')
                self.assertFalse([path for path in opened if path.endswith(rel)])
                self.assertEqual(tree(self.home), before)

    def install_codex_hooks(self, *, hooks, user=True, suffix=b''):
        """A Codex user (or project-scoped) install whose manifest owns an older hooks.json."""
        self.install_codex()
        old_hooks = b'{"description": "older SDLC hooks", "hooks": {}}\n'
        put(self.home, '.codex/hooks.json', old_hooks, 0o600)
        files = {rel: sha256(data) for rel, data in CODEX_V1.items()}
        files['.codex/hooks.json'] = sha256(old_hooks)
        manifest = {'version': 1, 'source_sha': '0' * 40, 'files': files, 'instructions': sha256(self.instructions),
                    'hooks': hooks, 'user': user}
        put(self.home, update.CODEX_MANIFEST, (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(), 0o600)
        put(self.home, '.codex/AGENTS.md', CODEX_PERSONAL + self.instructions + suffix)

    def test_manifested_hook_edition_is_kept_on_the_live_logical_home(self):
        suffix = b'\nPersonal notes after the managed block\n'
        self.install_codex_hooks(hooks=True, suffix=suffix)
        before = tree(self.home)
        plan, calls, _opened = self.plan_with_spies()
        self.assertIsInstance(plan, update.UpdatePlan, plan)
        self.assertTrue(calls)
        self.assertEqual(tree(self.home), before)
        by_rel = {op.rel: op for op in plan.ops}
        self.assertNotIn('.codex/AGENTS.md', by_rel)
        hooks_data = by_rel['.codex/hooks.json'].data
        config = update.strict_json(hooks_data)
        commands = [hook['command'] for groups in config['hooks'].values() for group in groups
                    for hook in group['hooks']]
        self.assertTrue(commands)
        for command in commands:
            self.assertIn(str(self.home / '.codex/framework/hook.py'), command)
            self.assertNotIn('sdlc-update-stage-', command)
        with update.scrubbed_git_environment():
            result = update.run_transaction(self.home, plan)
        self.assertEqual((result['status'], result['executed']), ('PASS', True), result['error'])
        self.assertEqual((self.home / '.codex/hooks.json').read_bytes(), hooks_data)
        manifest = update.strict_json((self.home / update.CODEX_MANIFEST).read_bytes())
        self.assertIs(manifest['hooks'], True)
        self.assertEqual(manifest['files']['.codex/hooks.json'], sha256(hooks_data))
        self.assertEqual((self.home / '.codex/AGENTS.md').read_bytes(), CODEX_PERSONAL + self.instructions + suffix)

    def test_project_scoped_or_contradictory_hook_manifests_are_refused(self):
        cases = {'project-scoped manifest at a global home': dict(hooks=True, user=False),
                 'hooks false but an owned hooks.json entry': dict(hooks=False)}
        for name, shape in cases.items():
            with self.subTest(name):
                self.install_codex_hooks(**shape)
                before = tree(self.home)
                outcome, calls, _opened = self.plan_with_spies()
                self.assertIsInstance(outcome, update.UpdateError,
                                      'an ambiguous or out-of-scope Codex hook install was planned')
                if not shape.get('user', True):
                    self.assertEqual(calls, [], 'the native planner was reached for a project-scoped manifest')
                self.assertEqual(tree(self.home), before)


class FinalBoundaryRegressions(StagedFixture):
    SETTINGS_SENTINEL = 'SETTINGS-SECRET-SENTINEL'

    @contextlib.contextmanager
    def source_code_spies(self):
        """Record every entry that executes source-derived code (module exec, staged installer)."""
        calls = []
        real = {name: getattr(update, name) for name in ('load_source_module', 'stage_broad_update', 'codex_forecast')}

        def spy(name):
            def wrapper(*args, **kwargs):
                source = next((arg for arg in args if isinstance(arg, update.Source)), None)
                calls.append((name, source.sha if source else None))
                return real[name](*args, **kwargs)
            return wrapper

        with contextlib.ExitStack() as stack:
            for name in real:
                stack.enter_context(patch.object(update, name, spy(name)))
            yield calls

    def operation_events(self, result):
        self.assertIsNotNone(result['operation_log'])
        log = Path(result['operation_log'])
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
        self.assertEqual(log.parent, Path(result['backup']))
        raw = log.read_bytes()
        for payload in (self.SETTINGS_SENTINEL.encode(), b'core rule v2'):
            self.assertNotIn(payload, raw)
        return [json.loads(line) for line in raw.splitlines()]

    @staticmethod
    def event_paths(events, event):
        return {record['path'] for record in events if record.get('event') == event}

    def test_saved_plan_for_an_older_clean_commit_never_runs_newer_source_code(self):
        reviewed = self.head
        plan_path, document = PlanBinding.write_plan(self)
        self.assertEqual(document['source']['sha'], reviewed)
        put(self.source, 'README.md', b'fixture advanced by a normal clean commit\n')
        advanced = self.commit(self.source, 'clean advance')
        self.assertEqual(self.read().sha, advanced)   # the advanced checkout is clean, not dirty
        self.reset_log()
        before = tree(self.home)
        with self.source_code_spies() as calls:
            code, output = self.cli('apply', '--plan', plan_path)
        result = json.loads(output)
        self.assertNotEqual(code, 0, output)
        self.assertIn(result['status'], ('FAIL', 'INCOMPLETE'))
        self.assertIs(result['executed'], False)
        self.assertEqual(calls, [], 'source code from an unreviewed commit ran before the source-binding refusal')
        self.assertEqual(self.staged_homes(), [], 'the unreviewed staged installer ran')
        self.assertEqual(tree(self.home), before)
        # Control: a plan reviewed at the advanced commit reaches source planning and applies.
        plan_path, _ = PlanBinding.write_plan(self)
        self.reset_log()
        with self.source_code_spies() as calls:
            code, output = self.cli('apply', '--plan', plan_path)
        self.assertEqual((code, json.loads(output)['status']), (0, 'PASS'), output)
        self.assertTrue(calls)
        self.assertEqual({sha for _name, sha in calls}, {advanced})

    def test_same_byte_core_hook_without_execute_bits_is_repaired_or_refused(self):
        hook = '.claude/hooks/guard.sh'
        data = self.head_files['global-config/hooks/guard.sh']
        for live_mode in (0o600, 0o640):
            with self.subTest(mode=oct(live_mode)):
                self.install_staged()
                self.reset_log()
                put(self.home, hook, data, live_mode)
                before = self.live_tree()
                try:
                    plan = self.build()
                except update.UpdateError:
                    self.assertEqual(self.live_tree(), before)   # explicit conservative refusal
                    continue
                self.assertEqual(self.live_tree(), before)
                repairs = [op for op in plan.ops if op.rel == hook]
                self.assertEqual(len(repairs), 1, 'a byte-current core hook without execute bits was left unrepaired')
                repair = repairs[0]
                self.assertEqual((repair.action, repair.data), ('write', data))
                self.assertEqual(repair.mode & 0o666, live_mode & 0o666)
                self.assertEqual(repair.mode & 0o111, 0o111)
                result = self.transact(plan)
                self.assertEqual((result['status'], result['executed']), ('PASS', True), result['error'])
                state, published = update.read_regular(self.home, hook)
                self.assertEqual((published, state['mode']), (data, repair.mode))

    def test_unchanged_flat_rule_changed_during_publication_never_passes(self):
        stable = '.claude/rules/stable.md'
        original = staged_tree
        with patch.dict(globals(), {'staged_tree': lambda version: {**original(version), stable: b'stable rule\n'}}):
            self.make_staged_source('stable-rule')
        cases = {
            'bytes': (lambda path: path.write_bytes(b'another writer edit\n'), ('file', 0o644, b'another writer edit\n')),
            'mode only': (lambda path: os.chmod(path, 0o600), ('file', 0o600, b'stable rule\n')),
        }
        for name, (mutate, external) in cases.items():
            with self.subTest(name):
                self.install_staged()
                self.reset_log()
                plan = self.build()
                self.assertNotIn(stable, {op.rel for op in plan.ops})
                before = self.live_tree()
                self.assertEqual(before[stable], ('file', 0o644, b'stable rule\n'))
                calls = []
                real_replace = os.replace

                def racing(src, dst, *args, **kwargs):
                    real_replace(src, dst, *args, **kwargs)
                    calls.append(dst)
                    if len(calls) == 1:
                        mutate(self.home / stable)

                with patch('os.replace', racing):
                    result = self.transact(plan)
                self.assertIn(result['status'], ('FAIL', 'INCOMPLETE'), 'postcheck passed with an unchanged owned file changed')
                self.assertEqual((result['recovery'], result['unrecovered']), ('rolled-back', []))
                expected = dict(before)
                expected[stable] = external
                self.assertEqual(self.live_tree(), expected)   # own writes undone, marker not current, edit kept

    def test_result_and_private_log_record_actual_outcomes_not_the_plan(self):
        put(self.home, update.SETTINGS, json.dumps({'model': 'personal', 'env': {'TOKEN': self.SETTINGS_SENTINEL}}).encode(),
            0o600)
        plan = self.build()
        planned = {op.rel for op in plan.ops}
        result = self.transact(plan)
        self.assertEqual((result['status'], result['executed']), ('PASS', True), result['error'])
        self.assertEqual({op['path'] for op in result['operations']}, planned)
        self.assertEqual({(entry['path'], entry['outcome']) for entry in result['attempts']},
                         {(rel, 'applied') for rel in planned})
        events = self.operation_events(result)
        self.assertEqual(self.event_paths(events, 'attempt'), planned)
        self.assertEqual(self.event_paths(events, 'applied'), planned)
        self.assertEqual(self.event_paths(events, 'rollback-outcome'), set())

    def test_rollback_and_conflict_outcomes_are_recorded_as_they_happened(self):
        def failing(calls, real_replace):
            def replace(src, dst, *args, **kwargs):
                calls.append(dst)
                if len(calls) == 2:
                    raise OSError(errno.EIO, 'injected failure', os.fspath(dst))
                return real_replace(src, dst, *args, **kwargs)
            return replace

        def racing(calls, real_replace):
            def replace(src, dst, *args, **kwargs):
                calls.append(dst)
                if len(calls) == 1:
                    real_replace(src, dst, *args, **kwargs)
                    Path(dst).write_bytes(b'another writer\n')
                    return None
                if len(calls) == 2:
                    raise OSError(errno.EIO, 'injected failure', os.fspath(dst))
                return real_replace(src, dst, *args, **kwargs)
            return replace

        for name, make, first_outcome in (('rolled back', failing, 'rolled-back'),
                                          ('concurrent edit kept', racing, 'left-concurrent')):
            with self.subTest(name):
                self.install_staged()
                self.reset_log()
                put(self.home, update.SETTINGS,
                    json.dumps({'model': 'personal', 'env': {'TOKEN': self.SETTINGS_SENTINEL}}).encode(), 0o600)
                plan = self.build()
                calls = []
                with patch('os.replace', make(calls, os.replace)):
                    result = self.transact(plan)
                first, second = (Path(path).relative_to(self.home).as_posix() for path in calls[:2])
                self.assertNotEqual(result['status'], 'PASS')
                outcomes = {entry['path']: entry['outcome'] for entry in result['attempts']}
                self.assertEqual(set(outcomes), {first, second})
                self.assertEqual(outcomes[first], first_outcome)
                self.assertNotIn(outcomes[second], ('applied', 'rolled-back'))
                self.assertLess(set(outcomes), {op['path'] for op in result['operations']})
                events = self.operation_events(result)
                self.assertEqual(self.event_paths(events, 'attempt'), {first, second})
                self.assertEqual(self.event_paths(events, 'applied'), {first})
                logged = {record['path']: record['outcome'] for record in events
                          if record.get('event') == 'rollback-outcome'}
                self.assertEqual(logged, outcomes)

    def test_backup_failure_after_private_artifacts_exist_reports_them_without_target_writes(self):
        plan = self.build()
        before = self.live_tree()
        real_write = update.write_private

        def failing(path, data):
            if Path(path).name == 'backup.json':
                raise OSError(errno.ENOSPC, 'injected backup failure', os.fspath(path))
            return real_write(path, data)

        with patch.object(update, 'write_private', failing):
            result = self.transact(plan)
        self.assertEqual((result['status'], result['executed'], result['attempts']), ('FAIL', False, []))
        self.assertEqual(self.live_tree(), before)
        self.assertIsNotNone(result['backup'], 'partial private backup artifacts exist but were not reported')
        backup = Path(result['backup'])
        self.assertIn(self.home / update.STATE_DIR, backup.parents)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
        self.assertTrue([entry for entry in backup.iterdir() if entry.name != update.OPERATION_LOG])
        events = self.operation_events(result)
        self.assertIn('backup-failed', {record.get('event') for record in events})
        self.assertEqual(self.event_paths(events, 'attempt'), set())

    def test_failed_terminal_pass_record_is_incomplete_and_keeps_verified_writes(self):
        plan = self.build()
        planned = {op.rel for op in plan.ops}
        real_record = update.RunLog.record
        injected = []

        def record(run_log, event, **fields):
            if event == 'end' and fields.get('status') == 'PASS':
                injected.append(event)
                raise OSError(errno.EIO, 'injected terminal log failure', os.fspath(run_log.path))
            return real_record(run_log, event, **fields)

        with patch.object(update.RunLog, 'record', record):
            result = self.transact(plan)
        self.assertEqual(injected, ['end'], 'the terminal PASS record was never attempted')
        self.assertEqual(result['status'], 'INCOMPLETE', 'PASS reported although the terminal operation record was lost')
        self.assertEqual(update.EXIT_CODES[result['status']], 2)
        self.assertIs(result['executed'], True)
        self.assert_published(plan)   # verified installed bytes stay; no rollback for a missing log line
        self.assertEqual(result['unrecovered'], [])
        self.assertEqual({(entry['path'], entry['outcome']) for entry in result['attempts']},
                         {(rel, 'applied') for rel in planned})
        self.assertGreater(len(result['notes']), len(plan.notes), 'the operation-log evidence gap was not reported')
        self.assertTrue(Path(result['backup']).is_dir())
        events = self.operation_events(result)
        self.assertEqual(self.event_paths(events, 'applied'), planned)
        self.assertEqual([record for record in events if record.get('event') == 'end' and record.get('status') == 'PASS'],
                         [], 'the log claims a complete PASS that was never written')


if __name__ == '__main__':
    unittest.main()
