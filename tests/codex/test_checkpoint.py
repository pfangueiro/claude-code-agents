"""Behavioral checks for the working-state checkpoint helper.

The helper replaces the old stash/pop/branch-switch recipe in commands/checkpoint.md,
which changed the caller's working tree and could consume an unrelated stash (AR-001).
Every check runs in a disposable Git fixture: it proves the snapshot captures the full
working state, that the caller's branch/index/worktree/stashes are preserved on both a
successful and a refused save, that unsafe and unsupported states are refused before any
object or ref is written, and that the helper runs from the generated installed bundles
by absolute path independent of the project cwd.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'codex'))
import framework as f  # noqa: E402

HELPER = ROOT / '.claude/skills/verified-handoff/scripts/checkpoint.py'
REF = 'refs/checkpoint/'


def hermetic_env(home: Path) -> dict[str, str]:
    """A Git environment with no global/system config, so fixtures never read the host."""
    return {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(home),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'LC_ALL': 'C'}


class CheckpointTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='checkpoint-')
        self.base = Path(self.tmp.name).resolve()
        self.env = hermetic_env(self.base / 'home')
        (self.base / 'home').mkdir()
        self.repo = self.base / 'repo'
        self.repo.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    # -- fixture helpers -----------------------------------------------------

    def git(self, *args, repo=None, check=True):
        repo = repo or self.repo
        proc = subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                               '-c', 'user.email=fixture@example.invalid', *args],
                              env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and proc.returncode != 0:
            raise AssertionError(f'git {args} failed: {proc.stderr.decode()}')
        return proc.stdout.decode().strip()

    def helper(self, *args, cwd=None, repo=None):
        repo = repo or self.repo
        proc = subprocess.run([sys.executable, str(HELPER), *args, '--repo', str(repo)],
                              env=self.env, cwd=str(cwd or self.base),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        return proc

    def init_repo(self):
        self.git('init', '-q', '-b', 'main')
        (self.repo / '.gitignore').write_text('*.log\n')
        (self.repo / 'tracked.txt').write_text('committed\n')
        (self.repo / 'keep').mkdir()
        (self.repo / 'keep/removed.txt').write_text('to-delete\n')
        self.git('add', '-A')
        self.git('commit', '-qm', 'init')

    def working_changes(self):
        (self.repo / 'tracked.txt').write_text('modified\n')          # unstaged modification
        (self.repo / 'untracked.txt').write_text('new\n')             # untracked
        (self.repo / 'ignored.log').write_text('secret\n')            # ignored
        (self.repo / 'keep/removed.txt').unlink()                     # deletion
        (self.repo / 'staged.txt').write_text('staged\n')
        self.git('add', 'staged.txt')                                 # staged addition

    def snapshot_state(self):
        """Caller state that a checkpoint must never touch."""
        head = self.git('symbolic-ref', '-q', 'HEAD', check=False)
        index = (self.repo / '.git/index').read_bytes() if (self.repo / '.git/index').exists() else b''
        worktree = {}
        for path in sorted(self.repo.rglob('*')):
            if path.is_file() and '.git' not in path.relative_to(self.repo).parts:
                worktree[path.relative_to(self.repo).as_posix()] = path.read_bytes()
        stash = self.git('rev-parse', '-q', '--verify', 'refs/stash', check=False)
        return head, index, worktree, stash

    def assert_state_unchanged(self, before):
        self.assertEqual(self.snapshot_state(), before)


class CheckpointBehavior(CheckpointTestCase):
    def test_save_preserves_branch_index_worktree_and_stash(self):
        self.init_repo()
        self.working_changes()
        before = self.snapshot_state()
        proc = self.helper('save', 'before-refactor')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_state_unchanged(before)
        self.assertTrue(self.git('rev-parse', '-q', '--verify', REF + 'before-refactor', check=False))

    def test_snapshot_captures_all_change_classes_and_excludes_ignored(self):
        self.init_repo()
        self.working_changes()
        self.assertEqual(self.helper('save', 'snap').returncode, 0)
        files = set(self.git('ls-tree', '-r', '--name-only', REF + 'snap').splitlines())
        self.assertEqual(files, {'.gitignore', 'tracked.txt', 'untracked.txt', 'staged.txt'})
        self.assertEqual(self.git('show', REF + 'snap:tracked.txt'), 'modified')
        self.assertEqual(self.git('show', REF + 'snap:staged.txt'), 'staged')
        self.assertNotIn('ignored.log', files)      # ignored excluded (documented)
        self.assertNotIn('keep/removed.txt', files)  # deletion captured as absence

    def test_spaces_in_paths_are_snapshotted(self):
        self.init_repo()
        (self.repo / 'a file.txt').write_text('spaced\n')
        self.assertEqual(self.helper('save', 'spaces').returncode, 0)
        self.assertIn('a file.txt', self.git('ls-tree', '-r', '--name-only', REF + 'spaces').splitlines())

    def test_preexisting_stash_identity_is_preserved(self):
        self.init_repo()
        (self.repo / 'tracked.txt').write_text('stash-me\n')
        self.git('stash', 'push', '-q', '-m', 'unrelated-work')
        stash_sha = self.git('rev-parse', 'refs/stash')
        stash_log = (self.repo / '.git/logs/refs/stash').read_bytes()
        (self.repo / 'tracked.txt').write_text('post-stash change\n')
        before = self.snapshot_state()
        self.assertEqual(self.helper('save', 'after-stash').returncode, 0)
        self.assert_state_unchanged(before)
        self.assertEqual(self.git('rev-parse', 'refs/stash'), stash_sha)
        self.assertEqual((self.repo / '.git/logs/refs/stash').read_bytes(), stash_log)

    def test_save_refuses_existing_checkpoint_and_leaves_state(self):
        self.init_repo()
        self.working_changes()
        self.assertEqual(self.helper('save', 'dup').returncode, 0)
        first = self.git('rev-parse', REF + 'dup')
        before = self.snapshot_state()
        proc = self.helper('save', 'dup')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('checkpoint-exists', proc.stderr)
        self.assertEqual(self.git('rev-parse', REF + 'dup'), first)  # ref untouched
        self.assert_state_unchanged(before)

    def test_refuses_unsafe_names(self):
        self.init_repo()
        for name in ('bad name', '../evil', 'has..dots', 'trailing.lock', 'dot.'):
            proc = self.helper('save', name)
            with self.subTest(name=name):
                self.assertEqual(proc.returncode, 3)
                self.assertIn('invalid-name', proc.stderr)
        # A leading-dash token is rejected by argument parsing before it can reach git
        # (argparse treats it as an option); it must never create a checkpoint.
        dash = self.helper('save', '-leading-dash')
        self.assertNotEqual(dash.returncode, 0)
        self.assertEqual(self.git('for-each-ref', REF), '')

    def test_refuses_unborn_head(self):
        self.git('init', '-q', '-b', 'main')
        (self.repo / 'f.txt').write_text('x\n')
        proc = self.helper('save', 'first')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('unborn-head', proc.stderr)

    def test_refuses_index_flags(self):
        self.init_repo()
        self.git('update-index', '--skip-worktree', 'tracked.txt')
        before = self.snapshot_state()
        proc = self.helper('save', 'flagged')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('index-flags-unsupported', proc.stderr)
        self.assert_state_unchanged(before)

    def test_refuses_submodule_gitlink(self):
        self.init_repo()
        head = self.git('rev-parse', 'HEAD')
        self.git('update-index', '--add', '--cacheinfo', f'160000,{head},vendored')
        proc = self.helper('save', 'withsub')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('submodules-unsupported', proc.stderr)

    def test_refuses_content_filter(self):
        self.init_repo()
        (self.repo / '.gitattributes').write_text('*.dat filter=secret\n')
        (self.repo / 'x.dat').write_text('payload\n')
        self.git('add', '-A')
        self.git('commit', '-qm', 'filtered')
        self.git('config', 'filter.secret.clean', 'cat')  # helper refuses before running it
        proc = self.helper('save', 'filtered')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('content-filters-unsupported', proc.stderr)

    def test_refuses_untracked_content_filter_before_running_it(self):
        # SAFETY-IR01: `git add -A` also consumes non-ignored untracked files, so a
        # configured clean filter mapped onto an UNTRACKED target (via an untracked
        # .gitattributes) would run during the snapshot. The preflight must scan the
        # full add -A candidate set, not just cached paths, and refuse before any
        # callback, object or ref write.
        self.init_repo()
        (self.repo / '.gitattributes').write_text('*.dat filter=poison\n')  # untracked
        (self.repo / 'poison.dat').write_text('owner bytes\n')              # untracked target
        marker = self.repo / 'FILTER_RAN'
        prog = self.base / 'poison_filter.py'
        prog.write_text('import sys\nfrom pathlib import Path\n'
                        f'Path({str(marker)!r}).write_text("ran")\n'
                        'sys.stdout.buffer.write(sys.stdin.buffer.read())\n')
        self.git('config', 'filter.poison.clean', shlex.join([sys.executable, str(prog)]))
        before = self.snapshot_state()
        proc = self.helper('save', 'untracked-filter')
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertIn('content-filters-unsupported', proc.stderr)
        self.assertFalse(marker.exists(), 'clean filter must not run as a snapshot side effect')
        self.assertEqual(self.git('for-each-ref', REF), '')  # no ref written
        self.assert_state_unchanged(before)

    def test_unconfigured_filter_driver_still_snapshots(self):
        # Positive control for the broadened scan: a configured driver that no path's
        # filter attribute references cannot run anything, so the snapshot proceeds and
        # captures the untracked candidate.
        self.init_repo()
        (self.repo / '.gitattributes').write_text('*.dat filter=absent\n')
        (self.repo / 'x.dat').write_text('payload\n')          # attribute -> unconfigured driver
        self.git('config', 'filter.secret.clean', 'cat')       # a different, configured driver
        proc = self.helper('save', 'unref')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('x.dat', self.git('ls-tree', '-r', '--name-only', REF + 'unref').splitlines())

    def test_refuses_untracked_nested_repository(self):
        # SAFETY-IR02: an untracked embedded Git repository is turned into a mode 160000
        # gitlink by `git add -A`, silently dropping its current (committed, dirty and
        # untracked) bytes. Detect it during preflight and refuse before any mutation.
        self.init_repo()
        nested = self.repo / 'nested'
        nested.mkdir()
        sub = ['git', '-C', str(nested), '-c', 'user.name=F', '-c', 'user.email=f@e.invalid']
        subprocess.run([*sub, 'init', '-q', '-b', 'main'], env=self.env, check=True)
        (nested / 'tracked.txt').write_text('v1\n')
        subprocess.run([*sub, 'add', '-A'], env=self.env, check=True)
        subprocess.run([*sub, 'commit', '-qm', 'nested'], env=self.env, check=True)
        (nested / 'tracked.txt').write_text('dirty\n')          # nested dirty working byte
        (nested / 'local-new.txt').write_text('new\n')          # nested untracked byte
        before = self.snapshot_state()
        proc = self.helper('save', 'withnested')
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertIn('nested-repo-unsupported', proc.stderr)
        self.assertEqual(self.git('for-each-ref', REF), '')
        self.assert_state_unchanged(before)

    def test_ordinary_untracked_directory_is_snapshotted(self):
        # Control that nested-repo detection does not over-refuse: an ordinary untracked
        # directory (no embedded .git) is still captured file-by-file.
        self.init_repo()
        (self.repo / 'docs').mkdir()
        (self.repo / 'docs/readme.md').write_text('hello\n')
        self.assertEqual(self.helper('save', 'withdir').returncode, 0)
        files = set(self.git('ls-tree', '-r', '--name-only', REF + 'withdir').splitlines())
        self.assertIn('docs/readme.md', files)

    def test_refuses_conflict_in_progress(self):
        self.init_repo()
        self.git('checkout', '-q', '-b', 'side')
        (self.repo / 'tracked.txt').write_text('side change\n')
        self.git('commit', '-qam', 'side')
        self.git('checkout', '-q', 'main')
        (self.repo / 'tracked.txt').write_text('main change\n')
        self.git('commit', '-qam', 'main')
        merge = self.git('merge', 'side', check=False)  # expected to conflict
        self.assertTrue(self.git('ls-files', '-u'))     # unmerged entries present
        proc = self.helper('save', 'midmerge')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('conflict-in-progress', proc.stderr)

    def _install_hook(self, name, hooks_dir=None):
        hooks_dir = hooks_dir or (self.repo / '.git/hooks')
        hooks_dir.mkdir(parents=True, exist_ok=True)
        marker = self.repo / 'HOOK_RAN'
        hook = hooks_dir / name
        hook.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 0\n')
        hook.chmod(0o755)
        return marker

    def test_refuses_active_reference_transaction_hook_without_running_it(self):
        self.init_repo()
        self.working_changes()
        marker = self._install_hook('reference-transaction')
        before = self.snapshot_state()
        proc = self.helper('save', 'hooked')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('active-hooks:reference-transaction', proc.stderr)
        self.assertFalse(marker.exists(), 'hook must not be executed as a probe')
        self.assertEqual(self.git('for-each-ref', REF), '')  # no ref written
        self.assert_state_unchanged(before)

    def test_refuses_post_index_change_hook_and_honors_hookspath(self):
        self.init_repo()
        self.working_changes()
        custom = self.repo / 'custom-hooks'
        self.git('config', 'core.hooksPath', str(custom))
        marker = self._install_hook('post-index-change', hooks_dir=custom)
        proc = self.helper('save', 'hooked2')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('active-hooks:post-index-change', proc.stderr)
        self.assertFalse(marker.exists())

    def test_list_and_diff(self):
        self.init_repo()
        self.working_changes()
        self.assertEqual(self.helper('save', 'cp1').returncode, 0)
        listing = self.helper('list')
        self.assertEqual(listing.returncode, 0)
        self.assertIn('cp1', listing.stdout)
        (self.repo / 'tracked.txt').write_text('changed-again\n')
        diff = self.helper('diff', 'cp1')
        self.assertEqual(diff.returncode, 0, diff.stderr)
        self.assertIn('tracked.txt', diff.stdout)
        self.assertIn('changed-again', diff.stdout)
        missing = self.helper('diff', 'nope')
        self.assertEqual(missing.returncode, 3)
        self.assertIn('checkpoint-missing', missing.stderr)

    def test_cwd_independent_absolute_invocation(self):
        self.init_repo()
        self.working_changes()
        elsewhere = self.base / 'unrelated'
        elsewhere.mkdir()
        before = self.snapshot_state()
        proc = self.helper('save', 'fromelsewhere', cwd=elsewhere)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.git('rev-parse', '-q', '--verify', REF + 'fromelsewhere', check=False))
        self.assert_state_unchanged(before)

    def test_not_a_git_checkout_is_refused(self):
        proc = self.helper('save', 'x', repo=self.base / 'home')
        self.assertEqual(proc.returncode, 3)
        self.assertIn('not-a-git-checkout', proc.stderr)


class CheckpointInstalledBundles(CheckpointTestCase):
    """The helper must work when invoked by its absolute installed path, not cwd-relative."""

    def run_bundled(self, script: Path):
        self.init_repo()
        self.working_changes()
        index_before = (self.repo / '.git/index').read_bytes()
        proc = subprocess.run([sys.executable, str(script), 'save', 'bundled', '--repo', str(self.repo)],
                              env=self.env, cwd=str(self.base / 'home'),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.git('rev-parse', '-q', '--verify', REF + 'bundled', check=False))
        self.assertEqual((self.repo / '.git/index').read_bytes(), index_before)

    def test_executes_from_codex_bundle(self):
        bundle = self.base / 'codex-home'
        f.install(bundle)
        script = bundle / '.agents/skills/sdlc-verified-handoff/scripts/checkpoint.py'
        self.assertTrue(script.is_file(), 'Codex export must copy checkpoint.py verbatim')
        self.run_bundled(script)

    def test_executes_from_claude_user_install(self):
        # Mirror install.sh's `cp -r` of each skill dir into ~/.claude/skills.
        home_skill = self.base / 'claude-home/.claude/skills/verified-handoff'
        shutil.copytree(ROOT / '.claude/skills/verified-handoff', home_skill,
                        ignore=shutil.ignore_patterns('__pycache__'))
        self.run_bundled(home_skill / 'scripts/checkpoint.py')


class CheckpointCommandWiring(unittest.TestCase):
    def test_command_drops_destructive_recipe_and_targets_installed_helper(self):
        text = (ROOT / '.claude/commands/checkpoint.md').read_text()
        for banned in ('git stash pop', 'git stash push', 'checkout -b', 'git checkout -', 'git add -A'):
            self.assertNotIn(banned, text, f'destructive recipe still present: {banned}')
        self.assertIn('verified-handoff/scripts/checkpoint.py', text)
        self.assertIn('~/.claude/skills/verified-handoff/scripts/checkpoint.py', text)

    def test_codex_export_resolves_helper_relative_to_skill(self):
        skill = f.build()['.agents/skills/sdlc-checkpoint/SKILL.md'].decode()
        self.assertIn('../sdlc-verified-handoff/scripts/checkpoint.py', skill)
        self.assertNotIn('.claude/skills/', skill)
        self.assertNotIn('git stash pop', skill)


if __name__ == '__main__':
    unittest.main()
