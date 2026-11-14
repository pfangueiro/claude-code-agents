"""Behavioral checks for the delivery controller's fixed effect catalogue.

Everything runs offline: disposable Git repositories, a local bare remote, an isolated HOME
and Git identity, and a fake ``gh`` subprocess that keeps durable JSON state so a provider
write that succeeds before the caller sees an acknowledgement can be modelled. No real
provider, network or personal configuration is touched.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / '.claude/skills/delivery/scripts/controller_effects.py'
_SPEC = importlib.util.spec_from_file_location('controller_effects', MODULE_PATH)
fx = importlib.util.module_from_spec(_SPEC)
sys.modules['controller_effects'] = fx
_SPEC.loader.exec_module(fx)

GIT = shutil.which('git')
ALL = frozenset(fx.KINDS)
FORBIDDEN_FLAGS = {'--admin', '--auto', '--delete-branch', '--rebase', '--force', '--no-verify',
                   '-n', '--force-with-lease', '--amend'}
# Flags with no legitimate use in any Git call here, whatever the subcommand.
GIT_ALWAYS_FORBIDDEN = FORBIDDEN_FLAGS - {'-n'}


def git_subcommand(argv):
    """(subcommand, its arguments, global -c values) of a literal git argv."""
    config, idx = [], 1
    while idx < len(argv):
        token = argv[idx]
        if token in ('-c', '-C'):
            if token == '-c':
                config.append(argv[idx + 1])
            idx += 2
        elif token.startswith('-'):
            idx += 1
        else:
            return token, list(argv[idx + 1:]), config
    return None, [], config


def git_forbidden_options(argv):
    """Options in a git argv that skip/redirect hooks or force, by actual Git semantics:
    ``-n`` means ``--no-verify`` only for ``git commit`` (a count for rev-list, --no-stat for
    merge); ``--no-verify`` and ``-c core.hooksPath`` bypass hooks for any subcommand."""
    subcommand, rest, config = git_subcommand(argv)
    found = [item for item in config if item.lower().startswith('core.hookspath')]
    found += sorted(GIT_ALWAYS_FORBIDDEN & set(rest))
    if subcommand == 'commit':
        found += [token for token in rest if re.fullmatch(r'-[A-Za-z]*n[A-Za-z]*', token)]
    return found


class PorcelainControl(unittest.TestCase):
    """Read-only control for the hook-bypass oracle itself (no Git process needed)."""
    PREFIX = ('/usr/bin/git', *fx._GIT_FIXED, '-C', '/repo')

    def test_hook_bypass_oracle_follows_git_option_semantics(self):
        sha = 'a' * 40
        for argv in ((*self.PREFIX, 'rev-list', '--parents', '-n', '1', sha),
                     (*self.PREFIX, 'merge', '--no-ff', '--no-edit', '-F', '/m', sha),
                     (*self.PREFIX, 'commit', '--quiet', '-F', '/m')):
            self.assertEqual(git_forbidden_options(argv), [], argv)
        for argv in ((*self.PREFIX, 'commit', '-n', '-F', '/m'), (*self.PREFIX, 'commit', '-qn', '-F', '/m'),
                     (*self.PREFIX, 'commit', '--no-verify', '-F', '/m'),
                     (*self.PREFIX, 'merge', '--no-verify', sha),
                     ('/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-C', '/repo', 'merge', sha),
                     (*self.PREFIX, 'push', '--force', 'origin', sha)):
            self.assertNotEqual(git_forbidden_options(argv), [], argv)


def git_version() -> tuple[int, int]:
    if GIT is None:
        return (0, 0)
    out = subprocess.run([GIT, 'version'], capture_output=True, text=True).stdout
    match = re.search(r'(\d+)\.(\d+)', out)
    return (int(match[1]), int(match[2])) if match else (0, 0)


GIT_OK = git_version() >= fx.MIN_GIT_VERSION

FAKE_GH = r'''
import json, os, sys, time

STATE = os.environ['FAKE_GH_STATE']


def load():
    with open(STATE, encoding='utf-8') as handle:
        return json.load(handle)


def save(state):
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        json.dump(state, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, STATE)


def option(args, name):
    return args[args.index(name) + 1] if name in args else None


def project(record, args):
    if not isinstance(record, dict):
        return record
    return {field: record.get(field) for field in option(args, '--json').split(',')}


def find_pr(state, number):
    return next((pr for pr in state['prs'] if pr['number'] == number), None)


def fail(message, code=1):
    print(message, file=sys.stderr)
    return code


def split_api(args):
    """(flags, fields, endpoint) of a gh api argv; None for an unmodelled flag."""
    flags, fields, endpoint, idx = {}, {}, None, 1
    while idx < len(args):
        token = args[idx]
        if token in ('--hostname', '--method') and idx + 1 < len(args):
            flags[token] = args[idx + 1]
            idx += 2
        elif token in ('-f', '-F') and idx + 1 < len(args):
            key, _, value = args[idx + 1].partition('=')
            fields[key] = (token, value)
            idx += 2
        elif endpoint is None and not token.startswith('-'):
            endpoint = token
            idx += 1
        else:
            return None
    return flags, fields, endpoint


def target(state, args):
    """(host, owner/name) of --repo; a host-less value resolves to the CLI default host."""
    parts = (option(args, '--repo') or '').split('/')
    return (parts[0] if len(parts) == 3 else state['default_host']), '/'.join(parts[-2:])


def graphql(state, flags, fields):
    query = fields.get('query', ('', ''))[1]
    if flags.get('--method', 'POST') != 'POST' or not query.startswith('query(') or 'mutation' in query:
        return fail('only fixed read-only queries are modelled')
    if state.get('graphql_fault'):
        return fail('HTTP 502: Bad Gateway')
    if state.get('graphql_response') is not None:
        print(json.dumps(state['graphql_response']))
        return 0
    owner, repo, number = fields.get('owner'), fields.get('repo'), fields.get('number')
    if (owner is None or repo is None or number is None or number[0] != '-F'
            or '%s/%s' % (owner[1], repo[1]) != state['repo']):
        return fail('Could not resolve to a Repository')
    pr = find_pr(state, int(number[1]))
    if pr is None:
        return fail('Could not resolve to a PullRequest')
    node = {'number': pr['number'], 'baseRefName': pr['baseRefName'], 'headRefOid': pr['headRefOid'],
            'isMergeQueueEnabled': False, 'isInMergeQueue': False}
    node.update(state.get('queue_fields') or {})
    for key in state.get('queue_absent') or []:
        node.pop(key, None)
    print(json.dumps({'data': {'repository': {'nameWithOwner': state['repo'], 'pullRequest': node}}}))
    return 0


def main(args):
    state = load()
    state['calls'].append(args)
    save(state)
    if args == ['--version']:
        print('gh version 2.62.0 (fake)')
        return 0
    if args == ['pr', 'merge', '--help']:
        print('Usage: gh pr merge [<number>] [flags]')
        if state.get('match_head_supported', True):
            print('      --match-head-commit SHA   Commit SHA that the pull request head must match')
        return 0
    if args[:1] == ['api']:
        parsed = split_api(args)
        if parsed is None:
            return fail('unmodelled api flag')
        flags, fields, endpoint = parsed
        host = flags.get('--hostname', state['default_host'])
        if host != state['host']:
            # Models the CLI default host (for example a sole enterprise host) being used.
            return fail('HTTP 401: Bad credentials (https://%s/api)' % host)
        if endpoint == 'graphql':
            return graphql(state, flags, fields)
        if flags.get('--method') != 'GET' or fields or endpoint is None:
            return fail('only GET is modelled')
        root = 'repos/' + state['repo'] + '/'
        rest = endpoint[len(root):] if endpoint.startswith(root) else ''
        if rest.startswith('branches/') and rest.endswith('/protection'):
            rule = (state.get('protection') or {}).get(rest[len('branches/'):-len('/protection')])
            if state.get('protection_fault'):
                return fail('HTTP 503: Service Unavailable')
            if rule is not None:
                print(json.dumps(rule))
                return 0
            return fail('{"message":"Branch not protected"}')
        if rest.startswith('git/ref/heads/'):
            branch = rest[len('git/ref/heads/'):]
            sha = state['branches'].get(branch)
            if sha is not None:
                print(json.dumps({'ref': 'refs/heads/' + branch, 'object': {'sha': sha, 'type': 'commit'}}))
                return 0
        for prefix, table in (('compare/', 'compare'), ('commits/', 'commits')):
            key = rest[len(prefix):]
            if rest.startswith(prefix) and key in state.get(table, {}):
                print(json.dumps(state[table][key]))
                return 0
        return fail('{"message":"Not Found"}')
    host, repo = target(state, args)
    if host != state['host']:
        return fail('HTTP 401: Bad credentials (https://%s/api)' % host)
    if repo != state['repo']:
        return fail('unknown repository')
    if args[:2] == ['pr', 'list']:
        # Malformed fixture rows are returned as-is; gh pages internally up to --limit (default 30).
        prs = [pr for pr in state['prs'] if not isinstance(pr, dict) or 'headRefName' not in pr
               or (pr.get('headRefName') == option(args, '--head')
                   and pr.get('baseRefName') == option(args, '--base'))]
        print(json.dumps([project(pr, args) for pr in prs[:int(option(args, '--limit') or 30)]]))
        return 0
    if args[:2] == ['pr', 'create']:
        head = option(args, '--head')
        with open(option(args, '--body-file'), encoding='utf-8') as handle:
            body = handle.read()
        number = len(state['prs']) + 1
        state['prs'].append({'number': number, 'state': 'OPEN', 'headRefName': head,
                             'baseRefName': option(args, '--base'), 'headRefOid': state['branches'][head],
                             'isCrossRepository': False, 'mergeCommit': None, 'autoMergeRequest': None,
                             'title': option(args, '--title'), 'body': body,
                             'url': 'https://%s/%s/pull/%d' % (state['host'], state['repo'], number)})
        save(state)
        fault = state.get('fault_create')
        if fault == 'crash_after':
            return fail('connection reset by peer')
        if fault == 'hang_after':
            time.sleep(30)
        print(state['prs'][-1]['url'])
        return 0
    if args[:2] in (['pr', 'view'], ['pr', 'checks'], ['pr', 'merge']):
        pr = find_pr(state, int(args[2]))
        if pr is None:
            return fail('no pull requests found')
        if args[1] == 'view':
            print(json.dumps(project(pr, args)))
            return 0
        if args[1] == 'checks':
            checks = [c for c in state['checks'].get(str(pr['number']), [])
                      if c['required'] or '--required' not in args]
            if not checks:
                return fail('no required checks reported')
            print(json.dumps([project(c, args) for c in checks]))
            buckets = {c['bucket'] for c in checks}
            return 1 if buckets & {'fail', 'cancel'} else 8 if 'pending' in buckets else 0
        if option(args, '--match-head-commit') != pr['headRefOid']:
            return fail('head branch was modified')
        fault = state.get('fault_merge')
        if fault == 'base_race':
            # A foreign base push after the controller's last read; the server merges anyway.
            state['branches'][pr['baseRefName']] = 'd' * 40
            state['commits']['c' * 40]['parents'] = [{'sha': 'd' * 40}, {'sha': pr['headRefOid']}]
        if fault == 'queue':
            pr['autoMergeRequest'] = {'mergeMethod': 'MERGE'}
            save(state)
            print('added to merge queue')
            return 0
        pr['state'] = 'MERGED'
        pr['mergeCommit'] = {'oid': 'c' * 40}
        save(state)
        if fault == 'crash_after':
            return fail('stream error')
        return 0
    return fail('unmodelled command')


sys.exit(main(sys.argv[1:]))
'''


class EffectsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='controller-effects-')
        # A cleanup (not tearDown), so later cleanups such as stopping a planted command run first.
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(os.path.realpath(self.tmp.name))
        home = self.base / 'home'
        home.mkdir()
        gitconfig = home / '.gitconfig'
        gitconfig.write_text('[user]\n\tname = Fixture Owner\n\temail = owner@example.invalid\n'
                             '[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n')
        self.marker = self.base / 'hook-marker'
        self.env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(home),
                    'GIT_CONFIG_GLOBAL': str(gitconfig), 'GIT_CONFIG_NOSYSTEM': '1', 'LC_ALL': 'C',
                    'HOOK_MARKER': str(self.marker), 'FAKE_GH_STATE': str(self.base / 'gh-state.json')}
        self.evidence = self.base / 'evidence'
        self.evidence.mkdir(mode=0o700)
        self.evidence.chmod(0o700)
        self.toolchain = self.make_toolchain()

    def make_toolchain(self, **overrides):
        values = dict(git=GIT, environment=self.env, timeout_seconds=60, evidence_root=str(self.evidence))
        values.update(overrides)
        return fx.Toolchain(**values)

    def observe(self, kind, spec, toolchain=None):
        return fx.observe(kind, spec, toolchain=toolchain or self.toolchain)

    def execute(self, kind, spec, toolchain=None, authorized=ALL):
        return fx.execute(kind, spec, toolchain=toolchain or self.toolchain, authorized_kinds=authorized)

    def plant_running_command(self, kind, cwd):
        """Crash model: an owned, still-running mutation attempt left by an earlier call."""
        call_dir = self.evidence / f'20261114T000000Z-execute-{kind}-1-{"0" * 16}'
        call_dir.mkdir(mode=0o700)
        call_dir.chmod(0o700)
        commands = call_dir / 'commands'
        commands.mkdir(mode=0o700)
        commands.chmod(0o700)
        command = fx._process.CommandSpec(argv=(shutil.which('sleep'), '30'), cwd=cwd, stdin=b'',
                                          attempt_id='0001-mutation')
        attempt = fx._process.prepare(str(commands), command, 60)
        owned = fx._process.spawn(attempt, environment=self.env).release()
        self.addCleanup(self.stop_planted, owned)
        self.wait_state(owned, {'running'})
        return owned

    def wait_state(self, owned, states, seconds=20.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            state = owned.poll().state
            if state in states:
                return state
            time.sleep(0.05)
        self.fail(f'attempt never reached {sorted(states)}')

    def stop_planted(self, owned):
        if owned.poll().state not in fx._process.ACTIVE_STATES:
            return
        owned.request_stop()
        deadline = time.monotonic() + 20
        while owned.poll().state in fx._process.ACTIVE_STATES and time.monotonic() < deadline:
            time.sleep(0.05)


@unittest.skipUnless(GIT_OK, 'git >= 2.38 required')
class GitEffectsCase(EffectsCase):
    def setUp(self):
        super().setUp()
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.git(self.repo, 'init', '-q', '-b', 'main')
        (self.repo / 'README.md').write_text('base\n')
        (self.repo / '.gitignore').write_text('*.log\n')
        self.git(self.repo, 'add', '-A')
        self.git(self.repo, 'commit', '-qm', 'chore: init')
        self.base_sha = self.rev('main')
        self.common_dir = os.path.realpath(self.repo / '.git')
        self.worktrees = self.base / 'worktrees'
        self.worktrees.mkdir()

    def git(self, cwd, *args, check=True):
        proc = subprocess.run([GIT, '-C', str(cwd), *args], env=self.env, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise AssertionError(f'git {args} failed: {proc.stderr}')
        return proc.stdout.strip()

    def rev(self, ref, cwd=None):
        return self.git(cwd or self.repo, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}', check=False)

    def install_hook(self, name, body):
        hook = Path(self.common_dir) / 'hooks' / name
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(body)
        hook.chmod(0o755)

    def create_worktree(self, name, base=None):
        path = str(self.worktrees / name)
        spec = fx.WorktreeCreateSpec(repo=str(self.repo), common_dir=self.common_dir, branch=f'task/{name}',
                                     path=path, base_sha=base or self.base_sha)
        outcome = self.execute(fx.WORKTREE_CREATE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        return path, f'task/{name}'

    def commit_in(self, worktree, rel, text, message='feat: task change'):
        target = Path(worktree) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        self.git(worktree, 'add', '--', rel)
        self.git(worktree, 'commit', '-qm', message)
        return self.rev('HEAD', worktree)


class WorktreeCreate(GitEffectsCase):
    def spec(self, name, branch):
        return fx.WorktreeCreateSpec(repo=str(self.repo), common_dir=self.common_dir, branch=branch,
                                     path=str(self.worktrees / name), base_sha=self.base_sha)

    def test_create_once_then_observed_and_never_repeated(self):
        spec = self.spec('a', 'task/a')
        self.assertEqual(self.observe(fx.WORKTREE_CREATE, spec).state, fx.NOT_APPLIED)
        outcome = self.execute(fx.WORKTREE_CREATE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED)
        self.assertTrue(outcome.mutation_attempted)
        self.assertEqual(self.observe(fx.WORKTREE_CREATE, spec).state, fx.CONFIRMED)
        self.assertEqual(self.rev('task/a'), self.base_sha)
        again = self.execute(fx.WORKTREE_CREATE, spec)
        self.assertEqual((again.status, again.reason), (fx.REFUSED, 'already-applied'))
        self.assertFalse(again.mutation_attempted)

    def test_registered_but_missing_or_replaced_worktree_is_never_confirmed(self):
        path, branch = self.create_worktree('gone')
        spec = self.spec('gone', branch)
        self.assertEqual(self.observe(fx.WORKTREE_CREATE, spec).state, fx.CONFIRMED)
        moved = self.base / 'moved-gone'
        os.rename(path, moved)
        self.git(self.base, 'init', '-q', path)
        observation = self.observe(fx.WORKTREE_CREATE, spec)
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'worktree-binding-mismatch'))
        shutil.rmtree(path)
        os.symlink(moved, path)
        calls_before = sorted(os.listdir(self.evidence))
        # A symlinked worktree path is refused by validation before any observation or command.
        for attempt in (lambda: self.observe(fx.WORKTREE_CREATE, spec),
                        lambda: self.execute(fx.WORKTREE_CREATE, spec)):
            with self.assertRaises(fx.SpecError) as caught:
                attempt()
            self.assertEqual(caught.exception.code, 'non-canonical-path:path')
        self.assertEqual(sorted(os.listdir(self.evidence)), calls_before)
        self.assertEqual(os.readlink(path), str(moved))
        self.assertTrue((moved / 'README.md').exists())
        self.assertIn(f'worktree {path}', self.git(self.repo, 'worktree', 'list', '--porcelain'))
        self.assertEqual(self.rev(branch), self.base_sha)
        os.unlink(path)
        observation = self.observe(fx.WORKTREE_CREATE, spec)
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'worktree-registration-prunable'))
        outcome = self.execute(fx.WORKTREE_CREATE, spec)
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'conflict:worktree-registration-prunable'))
        self.assertFalse(outcome.mutation_attempted)
        self.assertFalse(os.path.lexists(path))
        self.assertIn(f'worktree {path}', self.git(self.repo, 'worktree', 'list', '--porcelain'))
        self.assertTrue((moved / 'README.md').exists())
        self.assertEqual(self.rev(branch), self.base_sha)

    def test_existing_branch_is_a_conflict_and_untouched(self):
        other = self.commit_in(self.create_worktree('seed')[0], 'x.txt', 'x\n')
        self.git(self.repo, 'branch', 'task/b', other)
        spec = self.spec('b', 'task/b')
        observation = self.observe(fx.WORKTREE_CREATE, spec)
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'branch-exists'))
        outcome = self.execute(fx.WORKTREE_CREATE, spec)
        self.assertEqual(outcome.status, fx.REFUSED)
        self.assertFalse(outcome.mutation_attempted)
        self.assertFalse((self.worktrees / 'b').exists())
        self.assertEqual(self.rev('task/b'), other)

    def test_repository_binding_is_exact(self):
        spec = fx.WorktreeCreateSpec(repo=str(self.repo), common_dir=str(self.base / 'home'), branch='task/c',
                                     path=str(self.worktrees / 'c'), base_sha=self.base_sha)
        observation = self.observe(fx.WORKTREE_CREATE, spec)
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'repo-binding-mismatch'))
        self.assertEqual(self.execute(fx.WORKTREE_CREATE, spec).status, fx.REFUSED)
        self.assertEqual(self.rev('task/c'), '')

    def test_inherited_git_selectors_do_not_redirect(self):
        decoy = self.base / 'decoy'
        decoy.mkdir()
        self.git(decoy, 'init', '-q')
        env = {**self.env, 'GIT_DIR': str(decoy / '.git'), 'GIT_WORK_TREE': str(decoy),
               'GIT_INDEX_FILE': str(decoy / 'index')}
        toolchain = self.make_toolchain(environment=env)
        outcome = self.execute(fx.WORKTREE_CREATE, self.spec('d', 'task/d'), toolchain=toolchain)
        self.assertEqual(outcome.status, fx.COMPLETED)
        self.assertEqual(self.rev('task/d'), self.base_sha)
        self.assertEqual(self.git(decoy, 'branch', '--list'), '')

    def test_evidence_root_inside_repository_is_refused(self):
        inside = self.repo / '.controller-evidence'
        inside.mkdir(mode=0o700)
        inside.chmod(0o700)
        with self.assertRaises(fx.ToolchainError) as caught:
            fx.observe(fx.WORKTREE_CREATE, self.spec('e', 'task/e'),
                       toolchain=self.make_toolchain(evidence_root=str(inside)))
        self.assertEqual(caught.exception.code, 'evidence-root-inside-repository')
        self.assertEqual(list(inside.iterdir()), [])


class TaskCommit(GitEffectsCase):
    def spec(self, worktree, branch, owned, message='feat(src): add new file\n\nBody line.\n'):
        return fx.TaskCommitSpec(repo=str(self.repo), common_dir=self.common_dir, worktree=worktree, branch=branch,
                                 expected_parent=self.base_sha, owned_paths=owned, message=message)

    def test_commits_only_owned_paths_with_normal_hooks(self):
        self.install_hook('pre-commit', '#!/bin/sh\necho ran >> "$HOOK_MARKER"\n')
        worktree, branch = self.create_worktree('owned')
        (Path(worktree) / 'src').mkdir()
        (Path(worktree) / 'src/new.txt').write_text('new\n')
        (Path(worktree) / 'README.md').write_text('changed\n')
        spec = self.spec(worktree, branch, ('src/', 'README.md'))
        outcome = self.execute(fx.TASK_COMMIT, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        observation = self.observe(fx.TASK_COMMIT, spec)
        self.assertEqual(observation.state, fx.CONFIRMED)
        self.assertEqual(observation.evidence['changed_paths'], ['README.md', 'src/new.txt'])
        self.assertTrue(self.marker.exists(), 'pre-commit hook must run')
        tip = self.rev(branch)
        self.assertEqual(self.git(self.repo, 'rev-parse', f'{tip}^'), self.base_sha)
        self.assertNotIn('co-authored-by', self.git(self.repo, 'log', '-1', '--format=%B', tip).lower())
        again = self.execute(fx.TASK_COMMIT, spec)
        self.assertEqual((again.status, again.reason), (fx.REFUSED, 'already-applied'))
        self.assertEqual(self.rev(branch), tip)

    def test_foreign_changes_refuse_and_stay_untouched(self):
        worktree, branch = self.create_worktree('foreign')
        (Path(worktree) / 'src').mkdir()
        (Path(worktree) / 'src/mine.txt').write_text('mine\n')
        (Path(worktree) / 'README.md').write_text('someone else\n')
        (Path(worktree) / 'notes.txt').write_text('unrelated\n')
        outcome = self.execute(fx.TASK_COMMIT, self.spec(worktree, branch, ('src/',)))
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'foreign-changes'))
        self.assertEqual(outcome.details['foreign_paths'], ['README.md', 'notes.txt'])
        self.assertFalse(outcome.mutation_attempted)
        self.assertEqual(self.git(worktree, 'diff', '--cached', '--name-only'), '')
        self.assertEqual((Path(worktree) / 'README.md').read_text(), 'someone else\n')
        self.assertEqual((Path(worktree) / 'notes.txt').read_text(), 'unrelated\n')
        self.assertEqual(self.rev(branch), self.base_sha)

    def test_failing_hook_keeps_work_and_is_never_success(self):
        self.install_hook('pre-commit', '#!/bin/sh\nexit 1\n')
        worktree, branch = self.create_worktree('hookfail')
        (Path(worktree) / 'README.md').write_text('work\n')
        spec = self.spec(worktree, branch, ('README.md',))
        outcome = self.execute(fx.TASK_COMMIT, spec)
        self.assertEqual(outcome.status, fx.FAILED)
        self.assertTrue(outcome.mutation_attempted)
        observation = self.observe(fx.TASK_COMMIT, spec)
        self.assertEqual(observation.state, fx.NOT_APPLIED)
        self.assertEqual(fx.settle(outcome, observation), fx.NOT_APPLIED)
        self.assertEqual((Path(worktree) / 'README.md').read_text(), 'work\n')
        self.assertEqual(self.rev(branch), self.base_sha)

    def test_timed_out_hook_is_uncertain_not_success(self):
        self.install_hook('pre-commit', '#!/bin/sh\nsleep 30\n')
        worktree, branch = self.create_worktree('slow')
        (Path(worktree) / 'README.md').write_text('slow work\n')
        toolchain = self.make_toolchain(timeout_seconds=2)
        outcome = self.execute(fx.TASK_COMMIT, self.spec(worktree, branch, ('README.md',)), toolchain=toolchain)
        self.assertEqual(outcome.status, fx.TIMED_OUT)
        self.assertTrue(outcome.commands[-1].timed_out)
        observation = self.observe(fx.TASK_COMMIT, self.spec(worktree, branch, ('README.md',)))
        self.assertNotEqual(observation.state, fx.CONFIRMED)
        self.assertEqual(fx.settle(outcome, observation), fx.UNKNOWN)
        self.assertEqual((Path(worktree) / 'README.md').read_text(), 'slow work\n')

    def test_message_policy_is_enforced_before_any_command(self):
        worktree = str(self.worktrees / 'never')
        for message in ('update stuff', 'feat: x\n\nCo-Authored-By: Bot <bot@example.invalid>\n',
                        'fix: y\n\nGenerated with Claude Code\n'):
            with self.assertRaises(fx.SpecError):
                fx.validate_spec(fx.TASK_COMMIT, self.spec(worktree, 'task/never', ('a',), message))
        for owned in (('../escape',), ('/abs',), ('.git/config',), ()):
            with self.assertRaises(fx.SpecError):
                fx.validate_spec(fx.TASK_COMMIT, self.spec(worktree, 'task/never', owned))


class Integrate(GitEffectsCase):
    def setUp(self):
        super().setUp()
        self.integration_wt = str(self.worktrees / 'integration')
        spec = fx.WorktreeCreateSpec(repo=str(self.repo), common_dir=self.common_dir, branch='integration',
                                     path=self.integration_wt, base_sha=self.base_sha)
        outcome = self.execute(fx.WORKTREE_CREATE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())

    def spec(self, branch, result, base=None, strategy=fx.FAST_FORWARD, message='', worktree=None):
        return fx.IntegrateSpec(repo=str(self.repo), common_dir=self.common_dir,
                                integration_worktree=worktree or self.integration_wt, target_branch='integration',
                                expected_base=base or self.base_sha, task_branch=branch, task_result=result,
                                strategy=strategy, message=message)

    def merge_spec(self, branch, result, base=None):
        return self.spec(branch, result, base=base, strategy=fx.MERGE_COMMIT,
                         message=f'chore(integrate): merge {branch}')

    def assert_normal_porcelain(self, outcome):
        for record in outcome.commands:
            self.assertEqual(git_forbidden_options(record.argv), [], record.argv)
            self.assertNotIn('commit-tree', record.argv)
            self.assertNotIn('update-ref', record.argv)

    def test_fast_forward_preserves_unrelated_dirty_work(self):
        worktree, branch = self.create_worktree('ff')
        result = self.commit_in(worktree, 'feature.txt', 'feature\n')
        (self.repo / 'README.md').write_text('owner dirty\n')
        (self.repo / 'scratch.txt').write_text('owner scratch\n')
        spec = self.spec(branch, result)
        outcome = self.execute(fx.INTEGRATE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.assert_normal_porcelain(outcome)
        observation = self.observe(fx.INTEGRATE, spec)
        self.assertEqual((observation.state, observation.evidence['result_sha']), (fx.CONFIRMED, result))
        self.assertEqual(self.rev('integration'), result)
        self.assertEqual((Path(self.integration_wt) / 'feature.txt').read_text(), 'feature\n')
        self.assertEqual((self.repo / 'README.md').read_text(), 'owner dirty\n')
        self.assertEqual((self.repo / 'scratch.txt').read_text(), 'owner scratch\n')
        self.assertEqual(self.execute(fx.INTEGRATE, spec).reason, 'already-applied')

    def test_integration_worktree_identity_is_exact(self):
        worktree, branch = self.create_worktree('held')
        result = self.commit_in(worktree, 'feature.txt', 'feature\n')
        spec = self.spec(branch, result, worktree=worktree)
        observation = self.observe(fx.INTEGRATE, spec)
        self.assertEqual((observation.state, observation.reason),
                         (fx.CONFLICT, 'integration-worktree-identity-mismatch'))
        outcome = self.execute(fx.INTEGRATE, spec)
        self.assertEqual((outcome.status, outcome.reason),
                         (fx.REFUSED, 'conflict:integration-worktree-identity-mismatch'))
        self.assertFalse(outcome.mutation_attempted)
        with self.assertRaises(fx.SpecError):
            fx.validate_spec(fx.INTEGRATE, self.spec(branch, result, worktree=str(self.repo)))
        self.assertEqual(self.rev('integration'), self.base_sha)

    def test_moved_target_conflicts(self):
        worktree, branch = self.create_worktree('stale')
        result = self.commit_in(worktree, 'feature.txt', 'feature\n')
        other = self.commit_in(self.create_worktree('other')[0], 'other.txt', 'other\n')
        self.git(self.integration_wt, 'merge', '-q', '--ff-only', other)
        spec = self.spec(branch, result)
        self.assertEqual(self.observe(fx.INTEGRATE, spec).state, fx.CONFLICT)
        self.assertEqual(self.execute(fx.INTEGRATE, spec).status, fx.REFUSED)
        self.assertEqual(self.rev('integration'), other)

    def test_merge_strategy_and_predicted_conflicts(self):
        first_wt, first = self.create_worktree('first')
        first_result = self.commit_in(first_wt, 'README.md', 'first\n')
        self.assertEqual(self.execute(fx.INTEGRATE, self.spec(first, first_result)).status, fx.COMPLETED)
        second_wt, second = self.create_worktree('second')
        second_result = self.commit_in(second_wt, 'second.txt', 'second\n')
        self.assertEqual(self.execute(fx.INTEGRATE, self.spec(second, second_result, base=first_result)).reason,
                         'not-fast-forward')
        merge = self.merge_spec(second, second_result, base=first_result)
        outcome = self.execute(fx.INTEGRATE, merge)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.assert_normal_porcelain(outcome)
        merged = self.rev('integration')
        self.assertEqual(outcome.details['result_sha'], merged)
        self.assertEqual(self.observe(fx.INTEGRATE, merge).state, fx.CONFIRMED)
        self.assertEqual(self.git(self.repo, 'rev-list', '--parents', '-n', '1', merged).split()[1:],
                         [first_result, second_result])
        third_wt, third = self.create_worktree('third')
        third_result = self.commit_in(third_wt, 'README.md', 'third\n')
        outcome = self.execute(fx.INTEGRATE, self.merge_spec(third, third_result, base=merged))
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'merge-conflict'))
        self.assertIn('README.md', outcome.details['conflicted_paths'])
        self.assertFalse(outcome.mutation_attempted)
        self.assertEqual(self.rev('integration'), merged)
        self.assertEqual(self.git(self.integration_wt, 'status', '--porcelain', '--ignored'), '')
        self.assertEqual(self.rev('MERGE_HEAD', self.integration_wt), '')

    def test_successful_merge_runs_normal_hooks_and_is_verified(self):
        worktree, branch = self.create_worktree('hooked')
        result = self.commit_in(worktree, 'feature.txt', 'feature\n')
        for name in ('pre-merge-commit', 'commit-msg', 'post-merge'):
            self.install_hook(name, f'#!/bin/sh\necho {name} >> "$HOOK_MARKER"\n')
        spec = self.merge_spec(branch, result)
        outcome = self.execute(fx.INTEGRATE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.assert_normal_porcelain(outcome)
        self.assertEqual(sorted(self.marker.read_text().split()), ['commit-msg', 'post-merge', 'pre-merge-commit'])
        merged = self.rev('integration')
        self.assertEqual(outcome.details['result_sha'], merged)
        self.assertEqual(self.git(self.repo, 'rev-list', '--parents', '-n', '1', merged).split()[1:],
                         [self.base_sha, result])
        observation = self.observe(fx.INTEGRATE, spec)
        self.assertEqual((observation.state, observation.reason), (fx.CONFIRMED, 'merge-committed'))
        self.assertEqual(observation.evidence['result_tree'], self.git(self.repo, 'rev-parse', f'{result}^{{tree}}'))

    def test_rejecting_hook_preserves_merge_state_and_blocks_retry(self):
        worktree, branch = self.create_worktree('rejected')
        result = self.commit_in(worktree, 'feature.txt', 'feature\n')
        self.install_hook('pre-merge-commit', '#!/bin/sh\necho rejected >> "$HOOK_MARKER"\nexit 1\n')
        spec = self.merge_spec(branch, result)
        outcome = self.execute(fx.INTEGRATE, spec)
        self.assertEqual((outcome.status, outcome.reason), (fx.FAILED, 'merge-exit-1'), outcome.as_dict())
        self.assertTrue(outcome.mutation_attempted)
        self.assertIn('MERGE_HEAD', outcome.details['operations'])
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.rev('integration'), self.base_sha)
        self.assertEqual(self.rev('MERGE_HEAD', self.integration_wt), result)
        self.assertEqual((Path(self.integration_wt) / 'feature.txt').read_text(), 'feature\n')
        observation = self.observe(fx.INTEGRATE, spec)
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'integration-worktree-blocked'))
        self.assertEqual(fx.settle(outcome, observation), fx.CONFLICT)
        again = self.execute(fx.INTEGRATE, spec)
        self.assertEqual(again.status, fx.REFUSED)
        self.assertFalse(again.mutation_attempted)
        self.assertEqual(self.rev('integration'), self.base_sha)
        self.assertEqual(self.rev('MERGE_HEAD', self.integration_wt), result)

    def test_command_running_merge_config_holds_without_running_or_changing_it(self):
        first_wt, first = self.create_worktree('drv-first')
        first_result = self.commit_in(first_wt, 'README.md', 'first\n')
        self.assertEqual(self.execute(fx.INTEGRATE, self.spec(first, first_result)).status, fx.COMPLETED)
        task_wt, task = self.create_worktree('drv-task')
        task_result = self.commit_in(task_wt, 'README.md', 'task\n')
        info = Path(self.common_dir) / 'info'
        info.mkdir(exist_ok=True)
        (info / 'attributes').write_text('README.md merge=fixture\n')
        pwned = self.base / 'pwned'
        spec = self.merge_spec(task, task_result, base=first_result)
        for key, value in (('merge.fixture.driver', f'touch {pwned}; false'),
                           ('filter.fixture.clean', f'touch {pwned}; cat'), ('merge.renormalize', 'true')):
            with self.subTest(key=key):
                self.git(self.repo, 'config', key, value)
                outcome = self.execute(fx.INTEGRATE, spec)
                self.assertEqual((outcome.status, outcome.reason),
                                 (fx.REFUSED, 'conflict:merge-prediction-driver-unsupported'))
                self.assertFalse(outcome.mutation_attempted)
                self.assertEqual(outcome.details['keys'], [key])
                self.assertFalse(any('merge-tree' in record.argv or 'merge' in record.argv
                                     for record in outcome.commands))
                self.assertEqual(self.git(self.repo, 'config', '--get', key), value)
                self.git(self.repo, 'config', '--unset', key)
        self.assertFalse(pwned.exists())
        self.assertEqual(self.rev('integration'), first_result)
        self.assertEqual(self.rev('MERGE_HEAD', self.integration_wt), '')

    def test_quarantine_is_private_and_removed_and_confirmation_needs_builtin_merge(self):
        worktree, branch = self.create_worktree('quarantine')
        result = self.commit_in(worktree, 'feature.txt', 'feature\n')
        spec = self.merge_spec(branch, result)
        outcome = self.execute(fx.INTEGRATE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        predictions = [record for record in outcome.commands if 'merge-tree' in record.argv]
        self.assertTrue(predictions)
        for record in predictions:
            intent = json.loads((Path(record.evidence_dir) / 'intent.json').read_text())
            self.assertEqual(intent['argv'], list(record.argv))
            git_dirs = [arg[len('--git-dir='):] for arg in record.argv if arg.startswith('--git-dir=')]
            self.assertEqual(len(git_dirs), 1)
            quarantine = Path(git_dirs[0])
            self.assertEqual(quarantine.parent, Path(outcome.evidence_dir))
            self.assertFalse(quarantine.exists())
            self.assertTrue(record.lifecycle_clean)
        self.assertEqual(self.observe(fx.INTEGRATE, spec).state, fx.CONFIRMED)
        self.git(self.repo, 'config', 'merge.fixture.driver', 'false')
        observation = self.observe(fx.INTEGRATE, spec)
        self.assertEqual((observation.state, observation.reason),
                         (fx.CONFLICT, 'merge-prediction-driver-unsupported'))
        self.assertEqual(self.git(self.repo, 'config', '--get', 'merge.fixture.driver'), 'false')

    # ---- observed no-op: accepted result already contained in the checkpoint

    def assert_contained(self, observation, containment, checkpoint, result):
        self.assertEqual((observation.state, observation.reason), (fx.CONFIRMED, 'already-contained'),
                         observation.as_dict())
        evidence = observation.evidence
        self.assertEqual(evidence['result_sha'], checkpoint)
        self.assertEqual(evidence['target_tip'], checkpoint)
        self.assertEqual(evidence['task_tip'], result)
        self.assertEqual(evidence['containment'], containment)
        self.assertIs(evidence['mutation_required'], False)
        self.assertEqual(evidence['target_holders'], [self.integration_wt])
        self.assertFalse(any(record.mutation for record in observation.commands))

    def assert_no_mutation(self, outcome):
        self.assertFalse(outcome.mutation_attempted)
        self.assertTrue(outcome.commands)
        for record in outcome.commands:
            self.assertFalse(record.mutation, record.argv)
            self.assertNotIn(git_subcommand(record.argv)[0],
                             ('merge', 'commit', 'update-ref', 'reset', 'checkout', 'switch'), record.argv)
        attempts = os.listdir(Path(outcome.evidence_dir) / 'commands')
        self.assertTrue(attempts)
        self.assertEqual([name for name in attempts if name.endswith('-mutation')], [])

    def advance_checkpoint(self):
        early_wt, early = self.create_worktree('early')
        early_result = self.commit_in(early_wt, 'early.txt', 'early\n')
        self.assertEqual(self.execute(fx.INTEGRATE, self.spec(early, early_result)).status, fx.COMPLETED)
        later_wt, later = self.create_worktree('later', base=early_result)
        later_result = self.commit_in(later_wt, 'later.txt', 'later\n')
        forward = self.spec(later, later_result, base=early_result)
        self.assertEqual(self.execute(fx.INTEGRATE, forward).status, fx.COMPLETED)
        self.assertEqual(self.rev('integration'), later_result)
        return early_wt, early, early_result, later, later_result

    def test_equal_result_is_an_observed_no_op_without_mutation(self):
        _, branch = self.create_worktree('noop')
        self.assertEqual(self.rev(branch), self.base_sha)
        for spec in (self.spec(branch, self.base_sha), self.merge_spec(branch, self.base_sha)):
            with self.subTest(strategy=spec.strategy):
                fx.validate_spec(fx.INTEGRATE, spec)
                observation = self.observe(fx.INTEGRATE, spec)
                self.assert_contained(observation, 'equal', self.base_sha, self.base_sha)
                self.assertEqual(fx.settle(None, observation), fx.CONFIRMED)
                outcome = self.execute(fx.INTEGRATE, spec)
                self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'already-applied'),
                                 outcome.as_dict())
                self.assertEqual(outcome.details['observed_state'], fx.CONFIRMED)
                self.assert_no_mutation(outcome)
                self.assertEqual(fx.settle(outcome, self.observe(fx.INTEGRATE, spec)), fx.CONFIRMED)
        self.assertEqual(self.rev('integration'), self.base_sha)
        self.assertEqual(self.git(self.repo, 'rev-list', '--count', 'integration'), '1')
        self.assertEqual(self.git(self.integration_wt, 'status', '--porcelain', '--ignored'), '')
        self.assertEqual(self.rev('MERGE_HEAD', self.integration_wt), '')

    def test_strict_ancestor_of_a_later_checkpoint_is_already_contained(self):
        _, early, early_result, later, later_result = self.advance_checkpoint()
        for spec in (self.spec(early, early_result, base=later_result),
                     self.merge_spec(early, early_result, base=later_result)):
            with self.subTest(strategy=spec.strategy):
                self.assert_contained(self.observe(fx.INTEGRATE, spec), 'ancestor', later_result, early_result)
                outcome = self.execute(fx.INTEGRATE, spec)
                self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'already-applied'),
                                 outcome.as_dict())
                self.assert_no_mutation(outcome)
        equal = self.spec(later, later_result, base=later_result)
        self.assert_contained(self.observe(fx.INTEGRATE, equal), 'equal', later_result, later_result)
        # The earlier forward integration still confirms through its unchanged path.
        forward = self.observe(fx.INTEGRATE, self.spec(later, later_result, base=early_result))
        self.assertEqual((forward.state, forward.reason), (fx.CONFIRMED, 'fast-forwarded'))
        self.assertEqual(self.rev('integration'), later_result)
        self.assertEqual(self.git(self.integration_wt, 'status', '--porcelain', '--ignored'), '')

    def test_contained_result_needs_the_exact_task_branch_tip(self):
        early_wt, early, early_result, later, later_result = self.advance_checkpoint()
        moved = self.commit_in(early_wt, 'early-more.txt', 'more\n')
        for branch in (later, 'task/missing', early):
            with self.subTest(branch=branch):
                spec = self.spec(branch, early_result, base=later_result)
                observation = self.observe(fx.INTEGRATE, spec)
                self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'task-result-mismatch'))
                self.assertEqual(observation.evidence['task_tip'], self.rev(branch) or None)
                self.assertNotIn('result_sha', observation.evidence)
                outcome = self.execute(fx.INTEGRATE, spec)
                self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'conflict:task-result-mismatch'))
                self.assert_no_mutation(outcome)
        self.assertEqual(self.rev(early), moved)
        self.assertEqual(self.rev('integration'), later_result)

    def test_dirty_or_locked_integration_worktree_blocks_the_no_op(self):
        _, branch = self.create_worktree('dirty-noop')
        spec = self.spec(branch, self.base_sha)
        integration = Path(self.integration_wt)
        lock = Path(self.git(self.integration_wt, 'rev-parse', '--path-format=absolute', '--git-path', 'index.lock'))
        cases = ((integration / 'untracked.txt', 'paths'), (integration / 'debug.log', 'paths'),
                 (integration / 'README.md', 'paths'), (lock, 'index_lock'))
        for path, key in cases:
            with self.subTest(path=path.name):
                original = path.read_text() if path.exists() else None
                path.write_text('foreign\n')
                observation = self.observe(fx.INTEGRATE, spec)
                self.assertEqual((observation.state, observation.reason),
                                 (fx.CONFLICT, 'integration-worktree-blocked'))
                self.assertIn(key, observation.evidence)
                outcome = self.execute(fx.INTEGRATE, spec)
                self.assertEqual((outcome.status, outcome.reason),
                                 (fx.REFUSED, 'conflict:integration-worktree-blocked'))
                self.assert_no_mutation(outcome)
                self.assertEqual(path.read_text(), 'foreign\n')
                if original is None:
                    path.unlink()
                else:
                    path.write_text(original)
        self.assert_contained(self.observe(fx.INTEGRATE, spec), 'equal', self.base_sha, self.base_sha)
        self.assertEqual(self.rev('integration'), self.base_sha)

    def test_moved_or_detached_target_is_never_a_no_op(self):
        _, branch = self.create_worktree('moved-noop')
        spec = self.spec(branch, self.base_sha)
        self.assert_contained(self.observe(fx.INTEGRATE, spec), 'equal', self.base_sha, self.base_sha)
        other = self.commit_in(self.create_worktree('mover')[0], 'mover.txt', 'mover\n')
        self.git(self.integration_wt, 'merge', '-q', '--ff-only', other)
        observation = self.observe(fx.INTEGRATE, spec)
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'target-moved'))
        outcome = self.execute(fx.INTEGRATE, spec)
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'conflict:target-moved'))
        self.assert_no_mutation(outcome)
        self.assertEqual(self.rev('integration'), other)
        # Target ref back at the checkpoint, but no longer checked out in its owned worktree.
        self.git(self.integration_wt, 'checkout', '-q', '--detach')
        self.git(self.repo, 'branch', '-f', 'integration', self.base_sha)
        observation = self.observe(fx.INTEGRATE, spec)
        self.assertEqual((observation.state, observation.reason),
                         (fx.CONFLICT, 'integration-worktree-identity-mismatch'))
        outcome = self.execute(fx.INTEGRATE, spec)
        self.assertEqual((outcome.status, outcome.reason),
                         (fx.REFUSED, 'conflict:integration-worktree-identity-mismatch'))
        self.assert_no_mutation(outcome)
        self.assertEqual(self.rev('HEAD', self.integration_wt), other)
        self.assertEqual(self.rev('integration'), self.base_sha)

    def test_no_op_identity_is_exact_and_validated_before_any_command(self):
        _, branch = self.create_worktree('ident')
        link = self.base / 'integration-link'
        os.symlink(self.integration_wt, link)
        calls_before = sorted(os.listdir(self.evidence))
        malformed = ((self.spec(branch, self.base_sha, worktree=str(link)), 'non-canonical-path:integration_worktree'),
                     (self.spec('integration', self.base_sha), 'integrate-identity-collides'),
                     (self.spec(branch, self.base_sha, message='chore: x'), 'fast-forward-takes-no-message'),
                     (self.spec(branch, self.base_sha, strategy=fx.MERGE_COMMIT), 'invalid-text:message'),
                     (self.spec(branch, 'HEAD'), 'invalid-sha:task_result'))
        for spec, code in malformed:
            for attempt in (lambda: self.observe(fx.INTEGRATE, spec), lambda: self.execute(fx.INTEGRATE, spec)):
                with self.subTest(code=code), self.assertRaises(fx.SpecError) as caught:
                    attempt()
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(sorted(os.listdir(self.evidence)), calls_before)
        mapping = fx.spec_to_mapping(self.spec(branch, self.base_sha))
        self.assertEqual(fx.spec_from_mapping(fx.INTEGRATE, json.loads(json.dumps(mapping))),
                         self.spec(branch, self.base_sha))
        for extra in ({'review_passed': True}, {'accepted': True}):
            with self.assertRaises(fx.SpecError) as caught:
                fx.spec_from_mapping(fx.INTEGRATE, {**mapping, **extra})
            self.assertEqual(caught.exception.code, 'unknown-field')
        other = self.base / 'other-repo'
        other.mkdir()
        self.git(other, 'init', '-q', '-b', 'main')
        wrong = fx.IntegrateSpec(repo=str(other), common_dir=self.common_dir, integration_worktree=self.integration_wt,
                                 target_branch='integration', expected_base=self.base_sha, task_branch=branch,
                                 task_result=self.base_sha, strategy=fx.FAST_FORWARD, message='')
        observation = self.observe(fx.INTEGRATE, wrong)
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'repo-binding-mismatch'))
        outcome = self.execute(fx.INTEGRATE, wrong)
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'conflict:repo-binding-mismatch'))
        self.assert_no_mutation(outcome)
        self.assertEqual(self.rev('integration'), self.base_sha)

    def test_unrelated_or_unknown_result_keeps_the_forward_observation(self):
        worktree, branch = self.create_worktree('fwd')
        result = self.commit_in(worktree, 'fwd.txt', 'fwd\n')
        for task_result in (result, 'f' * len(self.base_sha)):
            with self.subTest(task_result=task_result):
                observation = self.observe(fx.INTEGRATE, self.spec(branch, task_result))
                self.assertEqual((observation.state, observation.reason), (fx.NOT_APPLIED, 'target-at-base'))
                self.assertEqual(set(observation.evidence), {'target_tip', 'target_holders'})
        self.assertEqual(self.rev('integration'), self.base_sha)


class Push(GitEffectsCase):
    def setUp(self):
        super().setUp()
        self.remote = self.base / 'remote.git'
        self.git(self.base, 'init', '-q', '--bare', '-b', 'main', str(self.remote))
        self.git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        self.git(self.repo, 'push', '-q', 'origin', 'main')
        worktree, self.branch = self.create_worktree('pub')
        self.result = self.commit_in(worktree, 'pub.txt', 'pub\n')

    def spec(self, **overrides):
        values = dict(repo=str(self.repo), common_dir=self.common_dir, remote='origin', remote_url=str(self.remote),
                      local_branch=self.branch, expected_result=self.result, remote_branch=self.branch,
                      expected_remote_old=None, base_branch='main', expected_base=self.base_sha)
        values.update(overrides)
        return fx.PushSpec(**values)

    def remote_rev(self, branch):
        return self.git(self.remote, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}', check=False)

    def test_push_once_then_confirmed_without_pushing_again(self):
        spec = self.spec()
        self.assertEqual(self.observe(fx.PUSH, spec).state, fx.NOT_APPLIED)
        outcome = self.execute(fx.PUSH, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.assertEqual(self.observe(fx.PUSH, spec).state, fx.CONFIRMED)
        self.assertEqual(self.remote_rev(self.branch), self.result)
        self.assertEqual(self.git(self.repo, 'remote', 'get-url', 'origin'), str(self.remote))
        again = self.execute(fx.PUSH, spec)
        self.assertEqual((again.status, again.reason), (fx.REFUSED, 'already-applied'))
        self.assertFalse(any('push' in record.argv for record in again.commands))

    def test_success_before_ack_is_reconciled_from_remote(self):
        self.git(self.repo, 'push', '-q', 'origin', f'{self.result}:refs/heads/{self.branch}')
        spec = self.spec()
        observation = self.observe(fx.PUSH, spec)
        self.assertEqual(observation.state, fx.CONFIRMED)
        self.assertEqual(fx.settle(None, observation), fx.CONFIRMED)
        self.assertEqual(self.execute(fx.PUSH, spec).reason, 'already-applied')

    def test_mismatching_remote_target_conflicts(self):
        self.git(self.repo, 'push', '-q', 'origin', f'{self.base_sha}:refs/heads/{self.branch}')
        observation = self.observe(fx.PUSH, self.spec())
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'remote-target-mismatch'))
        self.assertEqual(self.execute(fx.PUSH, self.spec()).status, fx.REFUSED)
        self.assertEqual(self.remote_rev(self.branch), self.base_sha)

    def test_remote_base_movement_blocks(self):
        moved = self.commit_in(self.create_worktree('mover')[0], 'mover.txt', 'moved\n')
        self.git(self.repo, 'push', '-q', 'origin', f'{moved}:refs/heads/main')
        outcome = self.execute(fx.PUSH, self.spec())
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'remote-base-moved'))
        self.assertEqual(self.remote_rev(self.branch), '')

    def test_repository_config_cannot_redirect_or_run_commands(self):
        pwned = self.base / 'pwned'
        self.git(self.repo, 'config', 'remote.origin.receivepack', f'touch {pwned}; git-receive-pack')
        outcome = self.execute(fx.PUSH, self.spec())
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'conflict:repo-config-redirects-remote'))
        self.git(self.repo, 'config', '--unset', 'remote.origin.receivepack')
        decoy = self.base / 'decoy.git'
        self.git(self.base, 'init', '-q', '--bare', str(decoy))
        self.git(self.repo, 'config', '--global', f'url.{decoy}.pushInsteadOf', str(self.remote))
        observation = self.observe(fx.PUSH, self.spec())
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'remote-url-mismatch'))
        self.assertEqual(self.execute(fx.PUSH, self.spec()).status, fx.REFUSED)
        self.assertFalse(pwned.exists())
        self.assertEqual(self.remote_rev(self.branch), '')
        self.assertEqual(self.git(decoy, 'for-each-ref'), '')

    def test_unsafe_remote_urls_are_rejected(self):
        for url in ('ext::sh -c touch% /tmp/x', 'https://user:secret@example.invalid/r.git',
                    'https://token@example.invalid/r.git', '-oProxyCommand=x', 'relative/path'):
            with self.assertRaises(fx.SpecError):
                fx.validate_spec(fx.PUSH, self.spec(remote_url=url))

    def test_linked_worktrees_without_worktree_config_extension(self):
        observation = self.observe(fx.PUSH, self.spec())
        self.assertEqual(observation.state, fx.NOT_APPLIED, observation.as_dict())
        self.assertFalse(any('--worktree' in record.argv for record in observation.commands))

    def test_enabled_extension_with_absent_worktree_config_is_empty(self):
        self.git(self.repo, 'config', 'extensions.worktreeConfig', 'true')
        self.assertFalse((Path(self.common_dir) / 'config.worktree').exists())
        outcome = self.execute(fx.PUSH, self.spec())
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.assertEqual(self.observe(fx.PUSH, self.spec()).state, fx.CONFIRMED)
        self.assertEqual(self.remote_rev(self.branch), self.result)

    def test_enabled_worktree_config_is_screened(self):
        self.git(self.repo, 'config', 'extensions.worktreeConfig', 'true')
        self.git(self.repo, 'config', '--worktree', 'delivery.fixture', 'safe')
        self.assertEqual(self.observe(fx.PUSH, self.spec()).state, fx.NOT_APPLIED)
        pwned = self.base / 'pwned'
        self.git(self.repo, 'config', '--worktree', 'remote.origin.receivepack', f'touch {pwned}; git-receive-pack')
        outcome = self.execute(fx.PUSH, self.spec())
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'conflict:repo-config-redirects-remote'))
        self.assertFalse(pwned.exists())
        self.assertEqual(self.remote_rev(self.branch), '')

    def test_unsafe_or_unreadable_worktree_config_is_never_empty(self):
        self.git(self.repo, 'config', 'extensions.worktreeConfig', 'true')
        config = Path(self.common_dir) / 'config.worktree'
        elsewhere = self.base / 'elsewhere.config'
        elsewhere.write_text('[delivery]\n\tfixture = safe\n')
        config.symlink_to(elsewhere)
        observation = self.observe(fx.PUSH, self.spec())
        self.assertEqual((observation.state, observation.reason), (fx.CONFLICT, 'worktree-config-unsafe'))
        self.assertEqual(self.execute(fx.PUSH, self.spec()).status, fx.REFUSED)
        config.unlink()
        if os.geteuid() != 0:
            config.write_text('[delivery]\n\tfixture = safe\n')
            config.chmod(0)
            try:
                self.assertEqual(self.observe(fx.PUSH, self.spec()).state, fx.UNKNOWN)
                outcome = self.execute(fx.PUSH, self.spec())
                self.assertEqual(outcome.status, fx.REFUSED)
                self.assertFalse(outcome.mutation_attempted)
            finally:
                config.chmod(0o600)
        self.assertEqual(self.remote_rev(self.branch), '')


class GitHubEffectsCase(EffectsCase):
    BASE = 'b' * 40
    HEAD = 'a' * 40
    OTHER = 'd' * 40
    MERGED = 'c' * 40
    TREE = 'e' * 40

    def setUp(self):
        super().setUp()
        if GIT is None:
            self.skipTest('git required for the toolchain')
        fake = self.base / 'fake-gh'
        fake.write_text(f'#!{sys.executable} -I\n' + FAKE_GH)
        fake.chmod(0o755)
        self.state_path = Path(self.env['FAKE_GH_STATE'])
        # The CLI's default host is deliberately wrong: every call must name the target host.
        self.write_state({'repo': 'acme/widgets', 'host': 'github.com', 'default_host': 'ghe.default.example',
                          'branches': {'main': self.BASE, 'task/x': self.HEAD},
                          'prs': [], 'checks': {}, 'calls': []})
        self.toolchain = self.make_toolchain(gh=str(fake), timeout_seconds=30)

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state))

    def state(self):
        return json.loads(self.state_path.read_text())

    def update_state(self, **changes):
        state = self.state()
        state.update(changes)
        self.write_state(state)

    def calls(self, *prefix):
        return [call for call in self.state()['calls'] if call[:len(prefix)] == list(prefix)]

    def assert_calls_bound(self, host, repo):
        """Every observable provider call carries the canonical host/target explicitly."""
        for call in self.state()['calls']:
            if call in (['--version'], ['pr', 'merge', '--help']):
                continue
            if call[0] == 'api':
                self.assertEqual(call[1:3], ['--hostname', host], call)
            else:
                self.assertEqual(call[call.index('--repo') + 1], f'{host}/{repo}', call)


class PrCreate(GitHubEffectsCase):
    def spec(self, **overrides):
        values = dict(github_repo='acme/widgets', base_branch='main', expected_base_sha=self.BASE,
                      head_branch='task/x', head_sha=self.HEAD, title='feat(widgets): add x',
                      body='Summary\n\nValidation: listed in receipts.\n')
        values.update(overrides)
        return fx.PrCreateSpec(**values)

    def test_create_once_and_reuse_exact_match(self):
        spec = self.spec()
        self.assertEqual(self.observe(fx.PR_CREATE, spec).state, fx.NOT_APPLIED)
        outcome = self.execute(fx.PR_CREATE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        observation = self.observe(fx.PR_CREATE, spec)
        self.assertEqual((observation.state, observation.evidence['number']), (fx.CONFIRMED, 1))
        self.assertEqual(self.state()['prs'][0]['body'], spec.body)
        self.assertEqual(self.execute(fx.PR_CREATE, spec).reason, 'already-applied')
        self.assertEqual(len(self.state()['prs']), 1)
        self.assert_calls_bound('github.com', 'acme/widgets')

    def test_success_before_crash_is_not_duplicated(self):
        self.update_state(fault_create='crash_after')
        spec = self.spec()
        outcome = self.execute(fx.PR_CREATE, spec)
        self.assertEqual(outcome.status, fx.FAILED)
        observation = self.observe(fx.PR_CREATE, spec)
        self.assertEqual(fx.settle(outcome, observation), fx.CONFIRMED)
        self.assertEqual(self.execute(fx.PR_CREATE, spec).status, fx.REFUSED)
        self.assertEqual(len(self.state()['prs']), 1)

    def test_timeout_after_success_is_uncertain_then_confirmed(self):
        self.update_state(fault_create='hang_after')
        toolchain = self.make_toolchain(gh=self.toolchain.gh, timeout_seconds=2)
        outcome = self.execute(fx.PR_CREATE, self.spec(), toolchain=toolchain)
        self.assertEqual(outcome.status, fx.TIMED_OUT)
        record = outcome.commands[-1]
        self.assertTrue(record.timed_out)
        life = json.loads((Path(record.evidence_dir) / 'lifecycle.json').read_text())
        self.assertEqual((life['termination'], life['exitCode'], life['executionSuccess']), ('timeout', None, False))
        self.assertTrue((Path(record.evidence_dir) / 'stdout.log').is_file())
        # The stopped mutation does not block a positive observation of the provider state.
        self.assertEqual(self.observe(fx.PR_CREATE, self.spec()).state, fx.CONFIRMED)

    def test_mismatching_or_closed_prs_hold_without_creating(self):
        pr = {'number': 7, 'state': 'OPEN', 'headRefName': 'task/x', 'baseRefName': 'main',
              'headRefOid': self.OTHER, 'isCrossRepository': False,
              'url': 'https://github.com/acme/widgets/pull/7'}
        self.update_state(prs=[pr])
        self.assertEqual(self.observe(fx.PR_CREATE, self.spec()).reason, 'open-pr-head-mismatch')
        self.update_state(prs=[{**pr, 'state': 'CLOSED', 'headRefOid': self.HEAD}])
        self.assertEqual(self.observe(fx.PR_CREATE, self.spec()).reason, 'closed-pr-exists')
        self.update_state(prs=[{**pr, 'headRefOid': self.HEAD},
                               {**pr, 'number': 8, 'headRefOid': self.HEAD,
                                'url': 'https://github.com/acme/widgets/pull/8'}])
        self.assertEqual(self.observe(fx.PR_CREATE, self.spec()).reason, 'multiple-open-prs')
        self.assertEqual(self.execute(fx.PR_CREATE, self.spec()).status, fx.REFUSED)
        self.assertEqual(self.calls('pr', 'create'), [])

    def test_remote_head_or_base_mismatch_refuses(self):
        self.update_state(branches={'main': self.BASE, 'task/x': self.OTHER})
        self.assertEqual(self.execute(fx.PR_CREATE, self.spec()).reason, 'remote-head-mismatch')
        self.update_state(branches={'main': self.OTHER, 'task/x': self.HEAD})
        self.assertEqual(self.execute(fx.PR_CREATE, self.spec()).reason, 'remote-base-moved')
        self.assertEqual(self.calls('pr', 'create'), [])

    def pr_row(self, number, **overrides):
        row = {'number': number, 'state': 'OPEN', 'headRefName': 'task/x', 'baseRefName': 'main',
               'headRefOid': self.HEAD, 'isCrossRepository': False,
               'url': f'https://github.com/acme/widgets/pull/{number}'}
        row.update(overrides)
        return row

    def assert_held_without_creating(self, reason):
        observation = self.observe(fx.PR_CREATE, self.spec())
        self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, reason), observation.as_dict())
        self.assertEqual(fx.settle(None, observation), fx.UNKNOWN)
        outcome = self.execute(fx.PR_CREATE, self.spec())
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, f'unknown:{reason}'))
        self.assertFalse(outcome.mutation_attempted)

    def test_malformed_or_unbound_rows_are_unknown_not_absence_or_confirmation(self):
        self.assertEqual(self.observe(fx.PR_CREATE, self.spec()).state, fx.NOT_APPLIED)
        unnumbered = {key: value for key, value in self.pr_row(1).items() if key != 'number'}
        for prs in ([{}], [unnumbered], [self.pr_row(True)], [self.pr_row(0)], [self.pr_row(-1)],
                    [self.pr_row(1, url=None)], [self.pr_row(1, headRefOid=None)],
                    [self.pr_row(1, headRefOid='HEAD')], [self.pr_row(1, isCrossRepository='false')],
                    [self.pr_row(1, state='open')], [self.pr_row(1), ['not', 'a', 'row']]):
            with self.subTest(prs=prs):
                self.update_state(prs=prs)
                self.assert_held_without_creating('pr-list-row-malformed')
        for url in ('https://github.com/acme/other/pull/1', 'https://github.com/acme/widgets/pull/2',
                    'http://github.com/acme/widgets/pull/1', 'https://github.com/acme/widgets/pull/1?x=1'):
            with self.subTest(url=url):
                self.update_state(prs=[self.pr_row(1, url=url)])
                self.assert_held_without_creating('pr-url-not-canonical')
        self.assertEqual(self.calls('pr', 'create'), [])

    def test_truncated_listing_never_proves_absence(self):
        forks = [self.pr_row(100 + idx, isCrossRepository=True,
                             url=f'https://github.com/fork{idx}/widgets/pull/{100 + idx}') for idx in range(100)]
        self.update_state(prs=forks)
        self.assertEqual(self.observe(fx.PR_CREATE, self.spec()).state, fx.NOT_APPLIED)
        listed = self.calls('pr', 'list')[-1]
        self.assertEqual(listed[listed.index('--limit') + 1], '101')
        for later in ([self.pr_row(500)],
                      [self.pr_row(500, isCrossRepository=True, url='https://github.com/fork/widgets/pull/500'),
                       self.pr_row(501)]):
            with self.subTest(later=len(later)):
                self.update_state(prs=forks + later)
                self.assert_held_without_creating('pr-list-truncated')
        self.assertEqual(self.calls('pr', 'create'), [])

    def test_prior_command_in_flight_blocks_every_provider_query(self):
        neutral = self.base / 'neutral'
        neutral.mkdir()
        owned = self.plant_running_command(fx.PR_CREATE, str(neutral))
        observation = self.observe(fx.PR_CREATE, self.spec())
        self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'prior-command-unresolved'))
        self.assertEqual(observation.evidence['prior_commands'][0]['attempt'], str(owned.attempt))
        outcome = self.execute(fx.PR_CREATE, self.spec())
        self.assertEqual((outcome.status, outcome.reason, outcome.mutation_attempted),
                         (fx.INCOMPLETE, 'prior-command-unresolved', False))
        self.assertEqual(self.state()['calls'], [])


class PrMerge(GitHubEffectsCase):
    QUALIFIED = {'url': 'https://api.github.com/repos/acme/widgets/branches/main/protection',
                 'required_status_checks': {'strict': True, 'contexts': ['ci/test'],
                                            'checks': [{'context': 'ci/test', 'app_id': None}]},
                 'enforce_admins': {'enabled': True}}

    def setUp(self):
        super().setUp()
        self.update_state(protection={'main': self.QUALIFIED})
        self.update_state(prs=[{'number': 1, 'state': 'OPEN', 'headRefName': 'task/x', 'baseRefName': 'main',
                                'headRefOid': self.HEAD, 'isCrossRepository': False, 'mergeCommit': None,
                                'autoMergeRequest': None, 'url': 'https://github.example/acme/widgets/pull/1'}])
        self.set_checks([('ci/test', 'pass', True), ('lint-optional', 'fail', False)])
        self.update_state(compare={f'{self.BASE}...{self.HEAD}': {'status': 'ahead', 'ahead_by': 1, 'behind_by': 0,
                                                                  'base_commit': {'sha': self.BASE},
                                                                  'merge_base_commit': {'sha': self.BASE}}},
                          commits={self.HEAD: self.commit(self.HEAD, [self.BASE]),
                                   self.MERGED: self.commit(self.MERGED, [self.BASE, self.HEAD])})

    def commit(self, sha, parents):
        return {'sha': sha, 'parents': [{'sha': parent} for parent in parents],
                'commit': {'tree': {'sha': self.TREE}}}

    def set_checks(self, checks):
        self.update_state(checks={'1': [{'name': name, 'bucket': bucket, 'state': state[0] if state else bucket.upper(),
                                         'required': required} for name, bucket, required, *state in checks]})

    def spec(self, **overrides):
        values = dict(github_repo='acme/widgets', number=1, base_branch='main', expected_base_sha=self.BASE,
                      head_branch='task/x', expected_head=self.HEAD, required_checks=('ci/test',), method='merge')
        values.update(overrides)
        return fx.PrMergeSpec(**values)

    def test_merges_exact_reviewed_head_after_required_checks(self):
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        observation = self.observe(fx.PR_MERGE, self.spec())
        self.assertEqual((observation.state, observation.evidence['merge_commit']), (fx.CONFIRMED, 'c' * 40))
        merges = self.calls('pr', 'merge', '1')
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0][merges[0].index('--match-head-commit') + 1], self.HEAD)
        self.assertIn('--merge', merges[0])
        for call in self.state()['calls']:
            self.assertFalse(FORBIDDEN_FLAGS & set(call), call)
        self.assertEqual(self.execute(fx.PR_MERGE, self.spec()).reason, 'already-applied')

    def test_wrong_head_never_merges(self):
        outcome = self.execute(fx.PR_MERGE, self.spec(expected_head=self.OTHER))
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'conflict:pr-head-moved'))
        self.assertEqual(self.calls('pr', 'merge', '1'), [])

    def test_required_check_evidence_gates(self):
        cases = [([('ci/test', 'pending', True)], fx.INCOMPLETE, 'required-check-pending'),
                 ([('ci/test', 'fail', True)], fx.REFUSED, 'required-check-failed'),
                 ([('other', 'pass', True)], fx.INCOMPLETE, 'declared-check-missing'),
                 ([('ci/test', 'pass', False)], fx.INCOMPLETE, 'required-checks-unreported'),
                 # gh buckets NEUTRAL/SKIPPED as 'skipping': never treated as a pass.
                 ([('ci/test', 'skipping', True, 'NEUTRAL')], fx.INCOMPLETE, 'required-check-not-passed'),
                 ([('ci/test', 'skipping', True, 'SKIPPED')], fx.INCOMPLETE, 'required-check-not-passed')]
        for checks, status, reason in cases:
            with self.subTest(reason=reason):
                self.set_checks(checks)
                outcome = self.execute(fx.PR_MERGE, self.spec())
                self.assertEqual((outcome.status, outcome.reason), (status, reason))
                self.assertFalse(outcome.mutation_attempted)
        self.assertEqual(self.calls('pr', 'merge', '1'), [])

    def test_gh_without_match_head_support_refuses(self):
        self.update_state(match_head_supported=False)
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'gh-match-head-unsupported'))
        self.assertEqual(self.calls('pr', 'merge', '1'), [])

    def test_base_movement_refuses(self):
        self.update_state(branches={'main': self.OTHER, 'task/x': self.HEAD})
        self.assertEqual(self.execute(fx.PR_MERGE, self.spec()).reason, 'remote-base-moved')
        self.assertEqual(self.calls('pr', 'merge', '1'), [])

    def test_queued_merge_is_not_merged(self):
        self.update_state(fault_merge='queue')
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual(outcome.status, fx.COMPLETED)
        observation = self.observe(fx.PR_MERGE, self.spec())
        self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'merge-pending'))
        self.assertEqual(fx.settle(outcome, observation), fx.UNKNOWN)

    def test_merge_success_before_crash_is_reconciled(self):
        self.update_state(fault_merge='crash_after')
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual(outcome.status, fx.FAILED)
        self.assertEqual(fx.settle(outcome, self.observe(fx.PR_MERGE, self.spec())), fx.CONFIRMED)
        self.assertEqual(self.execute(fx.PR_MERGE, self.spec()).reason, 'already-applied')
        self.assertEqual(len(self.calls('pr', 'merge', '1')), 1)

    def test_head_not_containing_base_never_merges(self):
        self.update_state(compare={f'{self.BASE}...{self.HEAD}': {'status': 'diverged', 'ahead_by': 1,
                                                                  'behind_by': 2}})
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'head-not-up-to-date-with-base'))
        self.assertFalse(outcome.mutation_attempted)
        self.assertEqual(self.calls('pr', 'merge', '1'), [])

    def test_merged_identity_mismatch_is_unknown_and_never_retried(self):
        state = self.state()
        state['commits'][self.MERGED] = self.commit(self.MERGED, [self.OTHER, self.HEAD])
        self.write_state(state)
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        observation = self.observe(fx.PR_MERGE, self.spec())
        self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'merged-identity-mismatch'))
        self.assertEqual(fx.settle(outcome, observation), fx.UNKNOWN)
        again = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual((again.status, again.reason), (fx.REFUSED, 'unknown:merged-identity-mismatch'))
        self.assertEqual(len(self.calls('pr', 'merge', '1')), 1)

    def test_one_merged_payload_confirms_only_its_exact_base_and_method(self):
        self.assertEqual(self.execute(fx.PR_MERGE, self.spec()).status, fx.COMPLETED)
        self.assertEqual(self.observe(fx.PR_MERGE, self.spec()).state, fx.CONFIRMED)
        for spec in (self.spec(expected_base_sha=self.OTHER), self.spec(method='squash')):
            with self.subTest(spec=spec):
                observation = self.observe(fx.PR_MERGE, spec)
                self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'merged-identity-mismatch'))
        self.assertEqual(len(self.calls('pr', 'merge', '1')), 1)

    def test_malformed_provider_payloads_are_unknown_and_never_merged_again(self):
        self.assertEqual(self.execute(fx.PR_MERGE, self.spec()).status, fx.COMPLETED)
        merged = self.state()
        commit, pr = merged['commits'][self.MERGED], merged['prs'][0]
        for payload in ({**commit, 'parents': [{'sha': 'b'}, {'sha': self.HEAD}]}, {**commit, 'parents': []},
                        {**commit, 'parents': None}, {**commit, 'commit': {}}, {**commit, 'sha': self.OTHER}):
            with self.subTest(commit=payload):
                state = self.state()
                state['commits'][self.MERGED] = payload
                self.write_state(state)
                observation = self.observe(fx.PR_MERGE, self.spec())
                self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'merge-commit-unreadable'))
        for change in ({'number': True}, {'headRefOid': None}, {'isCrossRepository': 'false'}, {'url': None},
                       {'state': None}, {'mergeCommit': self.MERGED}):
            with self.subTest(view=change):
                state = self.state()
                state['commits'][self.MERGED] = commit
                state['prs'][0] = {**pr, **change}
                self.write_state(state)
                observation = self.observe(fx.PR_MERGE, self.spec())
                self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'pr-view-malformed'))
                again = self.execute(fx.PR_MERGE, self.spec())
                self.assertEqual((again.status, again.reason), (fx.REFUSED, 'unknown:pr-view-malformed'))
        self.assertEqual(len(self.calls('pr', 'merge', '1')), 1)

    def test_incomplete_or_mistyped_comparison_never_merges(self):
        key = f'{self.BASE}...{self.HEAD}'
        good = self.state()['compare'][key]
        unreported = (fx.INCOMPLETE, 'base-containment-unreported')
        mismatch = (fx.REFUSED, 'compare-identity-mismatch')
        cases = [({**good, 'behind_by': '0'}, unreported), ({**good, 'behind_by': False}, unreported),
                 ({**good, 'ahead_by': None}, unreported), ({**good, 'status': None}, unreported),
                 ({k: v for k, v in good.items() if k != 'merge_base_commit'}, unreported),
                 ({**good, 'base_commit': {'sha': 'b'}}, unreported),
                 ({**good, 'merge_base_commit': {'sha': self.OTHER}}, mismatch),
                 ({**good, 'base_commit': {'sha': self.OTHER}}, mismatch)]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.update_state(compare={key: payload})
                outcome = self.execute(fx.PR_MERGE, self.spec())
                self.assertEqual((outcome.status, outcome.reason), expected)
                self.assertFalse(outcome.mutation_attempted)
        self.assertEqual(self.calls('pr', 'merge', '1'), [])

    def test_full_raw_command_logs_are_retained_beyond_tails(self):
        long_url = 'https://github.example/acme/widgets/pull/1?' + 'x' * 5000
        state = self.state()
        state['prs'][0]['url'] = long_url
        self.write_state(state)
        toolchain = self.make_toolchain(gh=self.toolchain.gh, output_limit=1024)
        observation = self.observe(fx.PR_MERGE, self.spec(), toolchain=toolchain)
        self.assertEqual(observation.state, fx.NOT_APPLIED, observation.as_dict())
        view = next(record for record in observation.commands if record.argv[1:3] == ('pr', 'view'))
        self.assertLessEqual(len(view.stdout_tail), 1024)
        folder = Path(view.evidence_dir)
        self.assertEqual(folder.parent, Path(observation.evidence_dir) / 'commands')
        self.assertEqual(folder.parent.parent.parent, self.evidence)
        life = json.loads((folder / 'lifecycle.json').read_text())
        stdout_ref = life['logs']['stdout']
        self.assertEqual(Path(stdout_ref['path']).parent, folder)
        raw = Path(stdout_ref['path']).read_bytes()
        self.assertIn(long_url.encode(), raw)
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (view.stdout_bytes, view.stdout_sha256))
        self.assertEqual((stdout_ref['size'], stdout_ref['sha256']), (view.stdout_bytes, view.stdout_sha256))
        intent = json.loads((folder / 'intent.json').read_text())
        self.assertEqual(intent['argv'], list(view.argv))
        self.assertEqual(intent['stdin']['sha256'], hashlib.sha256(b'').hexdigest())
        self.assertEqual((life['exitCode'], life['identity']['pid'], life['executionSuccess']), (0, view.pid, True))
        receipt = json.loads((Path(observation.evidence_dir) / f'receipt-{folder.name}.json').read_text())
        self.assertEqual((receipt['stdout_sha256'], receipt['argv']), (view.stdout_sha256, list(view.argv)))
        for item in (folder, folder / 'stdout.log', folder / 'stderr.log', folder / 'intent.json',
                     folder / 'lifecycle.json'):
            self.assertEqual(item.stat().st_mode & 0o077, 0, item)


    def test_qualified_governance_is_read_before_merging_on_the_exact_target(self):
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.assertEqual(outcome.details['protection'],
                         {'strict': True, 'enforce_admins': True, 'status_checks': ['ci/test']})
        self.assertEqual(outcome.details['merge_queue'], {'enabled': False, 'in_queue': False})
        calls = self.state()['calls']
        merge_at = calls.index(self.calls('pr', 'merge', '1')[0])
        protection = [idx for idx, call in enumerate(calls)
                      if 'repos/acme/widgets/branches/main/protection' in call]
        queue = [idx for idx, call in enumerate(calls) if call[:4] == ['api', '--hostname', 'github.com', 'graphql']]
        self.assertTrue(protection and queue)
        self.assertLess(max(protection + queue), merge_at)
        query = calls[queue[0]]
        text = next(item for item in query if item.startswith('query='))
        self.assertIn('isMergeQueueEnabled', text)
        self.assertNotIn('mutation', text)
        self.assertNotIn('--method', query)
        for pair in (['-f', 'owner=acme'], ['-f', 'repo=widgets'], ['-F', 'number=1']):
            self.assertIn(pair[1], query)
            self.assertEqual(query[query.index(pair[1]) - 1], pair[0])
        for call in self.calls('api'):
            if call[3] != 'graphql':
                self.assertEqual(call[call.index('--method') + 1], 'GET', call)
        self.assert_calls_bound('github.com', 'acme/widgets')
        self.assertEqual(self.observe(fx.PR_MERGE, self.spec()).state, fx.CONFIRMED)

    def test_loose_missing_or_unreadable_protection_never_merges(self):
        good = self.QUALIFIED
        rules = good['required_status_checks']
        malformed = 'branch-protection-malformed'
        absent = 'branch-protection-status-checks-absent'
        cases = [({}, 'branch-protection-unreadable'),  # unprotected or ruleset-only base: 404
                 ({'develop': good}, 'branch-protection-unreadable'),
                 ({'main': []}, malformed),
                 ({'main': {**good, 'required_status_checks': {**rules, 'strict': False}}},
                  'branch-protection-not-strict'),
                 ({'main': {**good, 'required_status_checks': {**rules, 'strict': 'true'}}}, malformed),
                 ({'main': {**good, 'required_status_checks': {k: v for k, v in rules.items() if k != 'strict'}}},
                  malformed),
                 ({'main': {**good, 'required_status_checks': {**rules, 'contexts': [], 'checks': []}}},
                  'branch-protection-checks-empty'),
                 ({'main': {**good, 'required_status_checks': {**rules, 'contexts': [None]}}}, malformed),
                 ({'main': {**good, 'required_status_checks': {k: v for k, v in rules.items() if k != 'checks'}}},
                  malformed),
                 ({'main': {k: v for k, v in good.items() if k != 'required_status_checks'}}, absent),
                 ({'main': {**good, 'required_status_checks': None}}, absent),
                 ({'main': {**good, 'enforce_admins': {'enabled': False}}}, 'branch-protection-admin-bypass'),
                 ({'main': {**good, 'enforce_admins': {'enabled': None}}}, malformed),
                 ({'main': {k: v for k, v in good.items() if k != 'enforce_admins'}}, malformed)]
        for protection, reason in cases:
            with self.subTest(protection=protection):
                self.update_state(protection=protection)
                outcome = self.execute(fx.PR_MERGE, self.spec())
                self.assertEqual((outcome.status, outcome.reason, outcome.mutation_attempted),
                                 (fx.INCOMPLETE, reason, False), outcome.as_dict())
        self.update_state(protection={'main': good}, protection_fault=True)
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual((outcome.status, outcome.reason), (fx.INCOMPLETE, 'branch-protection-unreadable'))
        self.assertEqual(self.calls('pr', 'merge', '1'), [])

    def test_merge_queue_not_proven_off_never_merges(self):
        # The PR view's autoMergeRequest stays null in every case: it never proves the queue is off.
        node = {'number': 1, 'baseRefName': 'main', 'headRefOid': self.HEAD,
                'isMergeQueueEnabled': False, 'isInMergeQueue': False}
        malformed, mismatch = 'merge-queue-state-malformed', 'merge-queue-pr-identity-mismatch'
        cases = [({'queue_fields': {'isMergeQueueEnabled': True}}, 'merge-queue-enabled'),
                 ({'queue_fields': {'isInMergeQueue': True}}, 'pr-in-merge-queue'),
                 ({'queue_absent': ['isMergeQueueEnabled']}, malformed),
                 ({'queue_absent': ['isInMergeQueue']}, malformed),
                 ({'queue_fields': {'isMergeQueueEnabled': None}}, malformed),
                 ({'queue_fields': {'isMergeQueueEnabled': 'false'}}, malformed),
                 ({'queue_fields': {'isMergeQueueEnabled': 0}}, malformed),
                 ({'queue_fields': {'number': True}}, mismatch),
                 ({'queue_fields': {'baseRefName': 'develop'}}, mismatch),
                 ({'queue_fields': {'headRefOid': self.OTHER}}, mismatch),
                 ({'graphql_response': {'data': {'repository': {'nameWithOwner': 'acme/other',
                                                                'pullRequest': node}}}}, mismatch),
                 ({'graphql_response': {'data': {'repository': {'nameWithOwner': 'acme/widgets',
                                                                'pullRequest': None}}}}, malformed),
                 ({'graphql_response': {'data': None, 'errors': [{'message': 'denied'}]}}, malformed),
                 ({'graphql_response': {'data': {'repository': {'nameWithOwner': 'acme/widgets', 'pullRequest': node}},
                                        'errors': [{'message': 'partial'}]}}, malformed),
                 ({'graphql_fault': True}, 'merge-queue-state-unreadable')]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                self.update_state(**{'queue_fields': {}, 'queue_absent': [], 'graphql_response': None,
                                     'graphql_fault': False, **changes})
                outcome = self.execute(fx.PR_MERGE, self.spec())
                self.assertEqual((outcome.status, outcome.reason, outcome.mutation_attempted),
                                 (fx.INCOMPLETE, reason, False), outcome.as_dict())
        self.assertEqual(self.calls('pr', 'merge', '1'), [])

    def test_base_race_after_the_final_read_is_never_confirmed(self):
        self.update_state(fault_merge='base_race')
        outcome = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        observation = self.observe(fx.PR_MERGE, self.spec())
        self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'merged-identity-mismatch'))
        self.assertEqual(fx.settle(outcome, observation), fx.UNKNOWN)
        again = self.execute(fx.PR_MERGE, self.spec())
        self.assertEqual((again.status, again.reason), (fx.REFUSED, 'unknown:merged-identity-mismatch'))
        self.assertEqual(len(self.calls('pr', 'merge', '1')), 1)

    def test_explicit_enterprise_host_is_retained(self):
        self.update_state(host='ghe.corp.example', default_host='github.com')
        spec = self.spec(github_repo='ghe.corp.example/acme/widgets')
        outcome = self.execute(fx.PR_MERGE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.assertEqual(self.observe(fx.PR_MERGE, spec).state, fx.CONFIRMED)
        self.assert_calls_bound('ghe.corp.example', 'acme/widgets')

    def test_fake_default_host_is_wrong_so_targets_must_be_explicit(self):
        """Control: the fake really rejects a host-less call, so the bound-call checks bite."""
        def run(*args):
            return subprocess.run([self.toolchain.gh, *args], env=self.env, capture_output=True).returncode
        ref = 'repos/acme/widgets/git/ref/heads/main'
        self.assertNotEqual(run('pr', 'view', '1', '--repo', 'acme/widgets', '--json', 'number'), 0)
        self.assertEqual(run('pr', 'view', '1', '--repo', 'github.com/acme/widgets', '--json', 'number'), 0)
        self.assertNotEqual(run('api', '--method', 'GET', ref), 0)
        self.assertEqual(run('api', '--hostname', 'github.com', '--method', 'GET', ref), 0)


class AuthorityAndInputs(GitHubEffectsCase):
    def merge_spec(self):
        return fx.PrMergeSpec(github_repo='acme/widgets', number=1, base_branch='main', expected_base_sha=self.BASE,
                              head_branch='task/x', expected_head=self.HEAD, required_checks=('ci/test',),
                              method='merge')

    def test_unauthorized_kind_runs_nothing(self):
        outcome = self.execute(fx.PR_MERGE, self.merge_spec(), authorized=frozenset({fx.PR_CREATE}))
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'kind-not-authorized'))
        self.assertEqual(outcome.commands, ())
        self.assertEqual(self.state()['calls'], [])

    def test_spec_fields_cannot_grant_authority_or_inject(self):
        mapping = fx.spec_to_mapping(self.merge_spec())
        self.assertEqual(fx.spec_from_mapping(fx.PR_MERGE, json.loads(json.dumps(mapping))), self.merge_spec())
        for extra in ({'checks_passed': True}, {'admin': True}, {'gh': '/tmp/evil'}):
            with self.assertRaises(fx.SpecError):
                fx.spec_from_mapping(fx.PR_MERGE, {**mapping, **extra})
        for bad in ({'method': 'rebase'}, {'head_branch': '--upload-pack=evil'}, {'required_checks': []},
                    {'number': True}, {'expected_head': 'HEAD'}, {'github_repo': 'acme/widgets --admin'}):
            with self.assertRaises(fx.SpecError):
                fx.spec_from_mapping(fx.PR_MERGE, {**mapping, **bad})
        with self.assertRaises(fx.SpecError):
            fx.validate_spec(fx.PR_CREATE, self.merge_spec())

    def test_toolchain_requires_owner_approved_absolute_executables(self):
        for toolchain in (fx.Toolchain(git='git'), fx.Toolchain(git=GIT, gh='gh'),
                          fx.Toolchain(git=GIT, gh=str(self.base / 'missing')),
                          fx.Toolchain(git=GIT, timeout_seconds=0)):
            with self.assertRaises(fx.ToolchainError):
                fx.observe(fx.PR_MERGE, self.merge_spec(), toolchain=toolchain)
        with self.assertRaises(fx.ToolchainError):
            fx.execute(fx.PR_MERGE, self.merge_spec(), toolchain=self.toolchain, authorized_kinds='pr.merge')
        self.assertEqual(self.state()['calls'], [])

    def test_missing_or_unsafe_evidence_root_runs_nothing(self):
        shared = self.base / 'shared-evidence'
        shared.mkdir()
        shared.chmod(0o755)
        link = self.base / 'evidence-link'
        link.symlink_to(self.evidence)
        plain = self.base / 'evidence-file'
        plain.write_text('')
        plain.chmod(0o600)
        cases = {None: 'evidence-root-missing', str(self.base / 'absent'): 'evidence-root-missing',
                 str(shared): 'evidence-root-not-private', str(link): 'evidence-root-not-canonical',
                 'relative/evidence': 'evidence-root-not-canonical', str(plain): 'evidence-root-not-directory'}
        for root, code in cases.items():
            with self.subTest(root=root):
                toolchain = self.make_toolchain(gh=self.toolchain.gh, evidence_root=root)
                with self.assertRaises(fx.ToolchainError) as caught:
                    fx.observe(fx.PR_MERGE, self.merge_spec(), toolchain=toolchain)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.state()['calls'], [])

    def test_settle_never_confirms_without_observation(self):
        observation = fx.Observation(fx.PUSH, fx.NOT_APPLIED, 'remote-branch-absent', {}, ())
        completed = fx.ExecuteOutcome(fx.PUSH, fx.COMPLETED, 'push-exited-0', True, (), {})
        self.assertEqual(fx.settle(completed, observation), fx.UNKNOWN)
        failed = fx.ExecuteOutcome(fx.PUSH, fx.FAILED, 'push-exit-1', True, (), {})
        self.assertEqual(fx.settle(failed, observation), fx.NOT_APPLIED)
        incomplete = fx.ExecuteOutcome(fx.PUSH, fx.FAILED, 'unknown:command-evidence-incomplete', True, (), {},
                                       '', False)
        self.assertEqual(fx.settle(incomplete, observation), fx.UNKNOWN)
        remote = fx.Observation(fx.PR_CREATE, fx.NOT_APPLIED, 'no-pr', {}, ())
        timed_out = fx.ExecuteOutcome(fx.PR_CREATE, fx.TIMED_OUT, 'pr-create-timed-out', True, (), {})
        self.assertEqual(fx.settle(timed_out, remote), fx.UNKNOWN)


class HookStarted:
    """Cancellation that becomes set once a hook has recorded its pid (deterministic STOP)."""

    def __init__(self, path):
        self.path = path

    def is_set(self):
        return self.path.exists()


def process_gone(pid, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True  # the pid now belongs to another user, so ours is gone
        time.sleep(0.05)
    return False


class CommandLifecycle(GitEffectsCase):
    """Real hooks and their descendants against the shared owned-process lifecycle."""

    def commit_spec(self, worktree, branch):
        return fx.TaskCommitSpec(repo=str(self.repo), common_dir=self.common_dir, worktree=worktree, branch=branch,
                                 expected_parent=self.base_sha, owned_paths=('README.md',),
                                 message='feat: lifecycle change\n')

    def dirty_worktree(self, name):
        worktree, branch = self.create_worktree(name)
        (Path(worktree) / 'README.md').write_text('work\n')
        return worktree, branch, self.commit_spec(worktree, branch)

    @staticmethod
    def lifecycle(record):
        return json.loads((Path(record.evidence_dir) / 'lifecycle.json').read_text())

    def assert_no_hook_bypass(self, outcome):
        for record in outcome.commands:
            self.assertEqual(git_forbidden_options(record.argv), [], record.argv)

    def test_redirected_hook_child_is_awaited_before_the_call_settles(self):
        self.install_hook('pre-commit', '#!/bin/sh\n'
                          '(sleep 1; echo late >> "$HOOK_MARKER") </dev/null >/dev/null 2>&1 &\n'
                          'exit 1\n')
        _, branch, spec = self.dirty_worktree('child-ok')
        outcome = self.execute(fx.TASK_COMMIT, spec)
        self.assertEqual((outcome.status, outcome.reason), (fx.FAILED, 'commit-exit-1'), outcome.as_dict())
        self.assert_no_hook_bypass(outcome)
        # The child wrote after the hook and git had exited, yet before the call returned.
        self.assertEqual(self.marker.read_text(), 'late\n')
        commit = outcome.commands[-1]
        life = self.lifecycle(commit)
        self.assertEqual((life['termination'], life['exitCode'], life['lingering'], life['forced'],
                          life['groupEmpty']), ('exited', 1, False, False, True))
        self.assertTrue(commit.lifecycle_clean)
        observation = self.observe(fx.TASK_COMMIT, spec)
        self.assertEqual(observation.state, fx.NOT_APPLIED, observation.as_dict())
        self.assertEqual(fx.settle(outcome, observation), fx.NOT_APPLIED)
        self.assertEqual(self.rev(branch), self.base_sha)

    def test_lingering_hook_child_is_forced_incomplete_and_holds_absence(self):
        pid_file = Path(f'{self.marker}.pid')
        self.install_hook('pre-commit', '#!/bin/sh\n'
                          'sh -c \'echo $$ > "$HOOK_MARKER.pid"; sleep 30; echo late >> "$HOOK_MARKER"\' '
                          '</dev/null >/dev/null 2>&1 &\n'
                          'exit 1\n')
        toolchain = self.make_toolchain(linger_seconds=0.5)
        _, branch, spec = self.dirty_worktree('child-lingers')
        outcome = self.execute(fx.TASK_COMMIT, spec, toolchain=toolchain)
        self.assertEqual((outcome.status, outcome.reason), (fx.INCOMPLETE, 'commit-lifecycle-unclean'),
                         outcome.as_dict())
        self.assertTrue(outcome.mutation_attempted)
        self.assert_no_hook_bypass(outcome)
        commit = outcome.commands[-1]
        self.assertFalse(commit.succeeded)
        life = self.lifecycle(commit)
        self.assertEqual((life['termination'], life['exitCode'], life['lingering'], life['forced'],
                          life['executionSuccess']), ('exited', 1, True, True, False))
        for stream in ('stdout', 'stderr'):
            ref = life['logs'][stream]
            raw = Path(ref['path']).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (ref['size'], ref['sha256']))
        self.assertTrue(process_gone(int(pid_file.read_text())))
        self.assertFalse(self.marker.exists())
        observation = self.observe(fx.TASK_COMMIT, spec, toolchain=toolchain)
        self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'prior-mutation-unclean'))
        self.assertEqual(fx.settle(outcome, observation), fx.UNKNOWN)
        again = self.execute(fx.TASK_COMMIT, spec, toolchain=toolchain)
        self.assertEqual((again.status, again.reason), (fx.REFUSED, 'unknown:prior-mutation-unclean'))
        self.assertFalse(again.mutation_attempted)
        self.assertEqual(self.rev(branch), self.base_sha)

    def test_cancel_stops_only_the_owned_group_and_never_settles_absence(self):
        pid_file = Path(f'{self.marker}.pid')
        self.install_hook('pre-commit', '#!/bin/sh\necho $$ > "$HOOK_MARKER.pid"\nsleep 30\n')
        worktree, branch, spec = self.dirty_worktree('cancelled')
        outcome = fx.execute(fx.TASK_COMMIT, spec, toolchain=self.toolchain, authorized_kinds=ALL,
                             cancel=HookStarted(pid_file))
        self.assertEqual((outcome.status, outcome.reason), (fx.CANCELLED, 'commit-cancelled'), outcome.as_dict())
        commit = outcome.commands[-1]
        self.assertEqual((commit.cancelled, commit.stop_status, commit.termination), (True, 'owned', 'stopped'))
        self.assertEqual(self.lifecycle(commit)['stopSource'], 'file')
        self.assertTrue(process_gone(int(pid_file.read_text())))
        self.assertEqual((Path(worktree) / 'README.md').read_text(), 'work\n')
        self.assertEqual(self.rev(branch), self.base_sha)
        observation = self.observe(fx.TASK_COMMIT, spec)
        self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'prior-mutation-unclean'))
        self.assertEqual(fx.settle(outcome, observation), fx.UNKNOWN)

    def test_unresolved_prior_command_holds_observation_and_replay_until_settled(self):
        _, branch, spec = self.dirty_worktree('crash')
        owned = self.plant_running_command(fx.TASK_COMMIT, str(self.repo))
        calls_before = sorted(os.listdir(self.evidence))
        observation = self.observe(fx.TASK_COMMIT, spec)
        self.assertEqual((observation.state, observation.reason, observation.commands),
                         (fx.UNKNOWN, 'prior-command-unresolved', ()))
        held = observation.evidence['prior_commands']
        self.assertEqual([(item['attempt'], item['state'], item['identity_status'], item['mutation'])
                          for item in held], [(str(owned.attempt), 'running', 'owned', True)])
        self.assertEqual(fx.settle(None, observation), fx.UNKNOWN)
        outcome = self.execute(fx.TASK_COMMIT, spec)
        self.assertEqual((outcome.status, outcome.reason, outcome.mutation_attempted, outcome.commands),
                         (fx.INCOMPLETE, 'prior-command-unresolved', False, ()))
        self.assertEqual(sorted(os.listdir(self.evidence)), calls_before)
        self.assertEqual(self.rev(branch), self.base_sha)
        # Engine STOP through the typed reference acts only on the positively owned bootstrap.
        self.assertEqual(fx._process.request_stop(held[0]['attempt']), 'owned')
        self.wait_state(owned, {'exited'})
        inspected = {item.attempt: item for item in fx.inspect_commands(str(self.evidence))}
        self.assertEqual((inspected[str(owned.attempt)].state, inspected[str(owned.attempt)].hold), ('exited', True))
        self.assertFalse((owned.attempt / 'lifecycle.json').exists(), 'inspection must stay read-only')
        observation = self.observe(fx.TASK_COMMIT, spec)
        self.assertEqual((observation.state, observation.reason), (fx.UNKNOWN, 'prior-mutation-unclean'))
        self.assertEqual(json.loads((owned.attempt / 'lifecycle.json').read_text())['termination'], 'stopped')
        self.assertEqual(self.rev(branch), self.base_sha)


class MissingCommandEvidence(GitEffectsCase):
    """A durable claim or receipt whose helper attempt is gone is lost evidence: it holds every
    observation and replay as unknown and is never read as absence, repaired or recreated."""

    def spec(self):
        return fx.WorktreeCreateSpec(repo=str(self.repo), common_dir=self.common_dir, branch='task/lost',
                                     path=str(self.worktrees / 'lost'), base_sha=self.base_sha)

    def private_root(self, name):
        root = self.base / f'evidence-{name}'
        root.mkdir(mode=0o700)
        root.chmod(0o700)
        return self.make_toolchain(evidence_root=str(root))

    def executed_call(self, name):
        """A real worktree.create call under its own evidence root, its effect then undone by
        hand so only the retained command evidence still says that the mutation ran."""
        toolchain = self.private_root(name)
        outcome = self.execute(fx.WORKTREE_CREATE, self.spec(), toolchain=toolchain)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.git(self.repo, 'worktree', 'remove', '--force', str(self.worktrees / 'lost'))
        self.git(self.repo, 'branch', '-D', 'task/lost')
        attempt = Path(next(record.evidence_dir for record in outcome.commands if record.mutation))
        call = Path(outcome.evidence_dir)
        self.assertTrue((call / f'claim-{attempt.name}.json').is_file())
        self.assertTrue((call / f'receipt-{attempt.name}.json').is_file())
        return toolchain, call, attempt

    def assert_held_without_any_command(self, toolchain, *reasons):
        root = Path(toolchain.evidence_root)
        before = sorted(str(path) for path in root.rglob('*'))
        held = {item.reason for item in fx.inspect_commands(str(root)) if item.hold}
        self.assertTrue(set(reasons) <= held, held)
        observer, executor = mock.Mock(), mock.Mock()
        with mock.patch.dict(fx._OBSERVERS, {fx.WORKTREE_CREATE: observer}), \
                mock.patch.dict(fx._EXECUTORS, {fx.WORKTREE_CREATE: executor}):
            observation = fx.observe(fx.WORKTREE_CREATE, self.spec(), toolchain=toolchain)
            outcome = fx.execute(fx.WORKTREE_CREATE, self.spec(), toolchain=toolchain, authorized_kinds=ALL)
        observer.assert_not_called()
        executor.assert_not_called()
        self.assertEqual((observation.state, observation.reason, observation.commands),
                         (fx.UNKNOWN, 'prior-command-unresolved', ()))
        self.assertEqual(fx.settle(None, observation), fx.UNKNOWN)
        self.assertEqual((outcome.status, outcome.reason, outcome.mutation_attempted, outcome.commands),
                         (fx.INCOMPLETE, 'prior-command-unresolved', False, ()))
        # Nothing was queried, created, repaired or recreated: no new call and no new file.
        self.assertEqual(sorted(str(path) for path in root.rglob('*')), before)
        self.assertEqual(self.rev('task/lost'), '')

    def test_claim_with_missing_commands_root_holds(self):
        toolchain, call, _ = self.executed_call('root')
        shutil.rmtree(call / 'commands')
        self.assert_held_without_any_command(toolchain, 'commands-root-missing', 'command-evidence-missing')
        self.assertFalse((call / 'commands').exists())

    def test_claim_with_missing_attempt_holds(self):
        toolchain, _, attempt = self.executed_call('attempt')
        shutil.rmtree(attempt)
        self.assert_held_without_any_command(toolchain, 'command-evidence-missing')
        self.assertFalse(attempt.exists())

    def test_receipt_with_missing_attempt_holds(self):
        toolchain, call, attempt = self.executed_call('receipt')
        (call / f'claim-{attempt.name}.json').unlink()
        shutil.rmtree(attempt)
        self.assert_held_without_any_command(toolchain, 'command-evidence-missing')

    @staticmethod
    def unspawn(attempt):
        """Strip a helper attempt back to intent + stdin, so the helper reports 'prepared'."""
        for entry in attempt.iterdir():
            if entry.name in (fx._process.INTENT, fx._process.STDIN):
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        assert fx._process.read_status(str(attempt))['state'] == 'prepared'

    @staticmethod
    def failure_receipt(path, attempt, spawn_error, **fields):
        """Rewrite one receipt as the CommandRecord a failed prepare/spawn leaves (no pid)."""
        recorded = json.loads(path.read_text())
        values = dict(argv=tuple(recorded['argv']), cwd=recorded['cwd'], exit_code=None, signal=None,
                      timed_out=False, cancelled=False, duration_ms=0, stdout_tail='', stderr_tail='',
                      spawn_error=spawn_error, mutation=recorded['mutation'],
                      started_at=recorded['started_at'], ended_at=recorded['ended_at'])
        if spawn_error.startswith('spawn:'):
            values.update(evidence_dir=str(attempt), process_state='prepared')
        values.update(fields)
        failed = fx.CommandRecord(**values)
        path.write_text(json.dumps({key: value for key, value in failed.as_dict().items()
                                    if key not in ('stdout_tail', 'stderr_tail')}))

    def test_claimed_attempt_without_spawn_evidence_holds(self):
        toolchain, _, attempt = self.executed_call('unspawned')
        self.unspawn(attempt)
        self.assert_held_without_any_command(toolchain, 'claimed-attempt-unspawned')

    def test_receipt_of_a_settled_attempt_contradicts_a_prepared_helper(self):
        """A retained full receipt (pid, exited, clean lifecycle) with its claim lost and the
        helper back at 'prepared' is a contradiction: held before any observer or executor."""
        toolchain, call, attempt = self.executed_call('contradicted')
        receipt = json.loads((call / f'receipt-{attempt.name}.json').read_text())
        self.assertEqual((isinstance(receipt['pid'], int), receipt['termination'], receipt['lifecycle_clean'],
                          receipt['evidence_dir']), (True, 'exited', True, str(attempt)))
        (call / f'claim-{attempt.name}.json').unlink()
        self.unspawn(attempt)
        self.assert_held_without_any_command(toolchain, 'receipt-lifecycle-unmatched')
        self.assertEqual(fx._process.read_status(str(attempt))['state'], 'prepared')

    def test_partial_receipt_claiming_spawn_contradicts_a_prepared_helper(self):
        toolchain, call, attempt = self.executed_call('torn')
        path = call / f'receipt-{attempt.name}.json'
        receipt = json.loads(path.read_text())
        partial = {key: receipt[key] for key in ('argv', 'cwd', 'mutation', 'evidence_dir', 'pid')}
        self.assertIsInstance(partial['pid'], int)
        path.write_text(json.dumps(partial))
        (call / f'claim-{attempt.name}.json').unlink()
        self.unspawn(attempt)
        self.assert_held_without_any_command(toolchain, 'receipt-spawn-unmatched')

    def test_genuinely_unspawned_prepared_attempt_is_not_held(self):
        """Positive control: a prepared helper with no claim and either no receipt or a receipt
        whose own facts prove its run never spawned the attempt (no pid; a prepare that failed
        after publishing the intent, or a typed spawn failure raised before any spawn lock)
        stays reconcilable."""
        cases = {'spawnfail': ('spawn:attempt-not-private', {}),
                 'pathfault': ('spawn:attempt-not-private',
                               {'process_state': 'corrupt', 'process_reason': 'attempt-not-private',
                                'evidence_error': 'command-unsettled'}),
                 'prepareio': ('prepare:io-error', {}),
                 'noreceipt': (None, {})}
        for name, (spawn_error, fields) in cases.items():
            with self.subTest(name):
                toolchain, call, attempt = self.executed_call(name)
                path = call / f'receipt-{attempt.name}.json'
                (call / f'claim-{attempt.name}.json').unlink()
                self.unspawn(attempt)
                if spawn_error is None:
                    path.unlink()
                else:
                    self.failure_receipt(path, attempt, spawn_error, **fields)
                prior = fx.inspect_commands(toolchain.evidence_root)
                self.assertEqual([item for item in prior if item.hold], [])
                mine = next(item for item in prior if item.attempt == str(attempt))
                self.assertEqual((mine.state, mine.lifecycle_clean), ('prepared', True))
                self.assertEqual(self.observe(fx.WORKTREE_CREATE, self.spec(), toolchain=toolchain).state,
                                 fx.NOT_APPLIED)

    def test_untrusted_claims_and_receipts_hold(self):
        def symlinked(call, claim):
            claim.unlink()
            claim.symlink_to(call / claim.name.replace('claim-', 'receipt-'))

        def elsewhere(call, claim):
            payload = json.loads(claim.read_text())
            payload['attempt'] = str(self.base / 'elsewhere')
            claim.write_text(json.dumps(payload))

        cases = {'symlink': (symlinked, 'command-ref-malformed'),
                 'malformed': (lambda call, claim: claim.write_text('{'), 'command-ref-malformed'),
                 'mismatch': (elsewhere, 'command-ref-mismatch'),
                 'unexpected': (lambda call, claim: (call / f'{claim.name}.partial').write_text('{}'),
                                'command-ref-unexpected')}
        for name, (tamper, reason) in cases.items():
            with self.subTest(name):
                toolchain, call, attempt = self.executed_call(name)
                tamper(call, call / f'claim-{attempt.name}.json')
                self.assert_held_without_any_command(toolchain, reason)

    def test_pre_spawn_partial_call_is_not_evidence(self):
        toolchain = self.private_root('partial')
        root = Path(toolchain.evidence_root)
        bare = root / f'20261114T000000Z-execute-{fx.WORKTREE_CREATE}-1-{"0" * 16}'
        rooted = root / f'20261114T000001Z-execute-{fx.WORKTREE_CREATE}-1-{"1" * 16}'
        for path in (bare, rooted, rooted / 'commands'):
            path.mkdir(mode=0o700)
        self.assertEqual(fx.inspect_commands(str(root)), ())
        self.assertEqual(self.observe(fx.WORKTREE_CREATE, self.spec(), toolchain=toolchain).state,
                         fx.NOT_APPLIED)
        # attempt.json is written only after commands/ exists, so its root's absence is lost evidence.
        (bare / 'attempt.json').write_text('{}')
        self.assertEqual([item.reason for item in fx.inspect_commands(str(root)) if item.hold],
                         ['commands-root-missing'])

    def test_spawn_failures_that_imply_a_spawn_contradict_a_prepared_helper(self):
        """A 'prepared' helper is explained only by a receipt proving no spawn. An untyped
        error, a failure raised at or after spawn.lock, a proven earlier lock, a polled
        post-spawn state, lock evidence read as corrupt, a typed prepare code raised before
        the intent existed, or a spawn failure bound to no attempt all hold."""
        cases = {
            'untyped': ('spawn:io-error', {}, 'receipt-spawn-unmatched'),
            'earlier-lock': ('spawn:attempt-already-spawned', {}, 'receipt-spawn-unmatched'),
            'post-lock': ('spawn:bootstrap-launch-failed', {}, 'receipt-spawn-unmatched'),
            'polled-running': ('spawn:attempt-not-private', {'process_state': 'running'},
                               'receipt-spawn-unmatched'),
            'lock-evidence': ('spawn:attempt-not-private',
                              {'process_state': 'corrupt', 'process_reason': 'spawn-lock-missing'},
                              'receipt-spawn-unmatched'),
            'typed-prepare': ('prepare:executable-unavailable', {}, 'receipt-spawn-unmatched'),
            'unbound': ('spawn:attempt-not-private', {'evidence_dir': ''}, 'receipt-identity-unmatched'),
        }
        for name, (spawn_error, fields, reason) in cases.items():
            with self.subTest(name):
                toolchain, call, attempt = self.executed_call(name)
                (call / f'claim-{attempt.name}.json').unlink()
                self.unspawn(attempt)
                self.failure_receipt(call / f'receipt-{attempt.name}.json', attempt, spawn_error, **fields)
                self.assert_held_without_any_command(toolchain, reason)
                self.assertEqual(fx._process.read_status(str(attempt))['state'], 'prepared')

    def test_receipt_contradicting_the_finalized_record_holds(self):
        """Against a finalized helper record the receipt pid is the bootstrap ANCHOR
        (identity.pid, never the declared commandPid) and its lifecycle and log digests are
        the record's own; a contradicting or spawn-erasing receipt holds."""
        def command_pid(receipt, life):
            receipt['pid'] = life['commandPid']

        def erased_pid(receipt, life):
            receipt['pid'] = None

        def exit_code(receipt, life):
            receipt['exit_code'] = 1

        def digest(receipt, life):
            receipt['stdout_sha256'] = '0' * 64

        cases = {'command-pid': (command_pid, 'receipt-pid-unmatched'),
                 'erased-pid': (erased_pid, 'receipt-pid-unmatched'),
                 'exit-code': (exit_code, 'receipt-lifecycle-unmatched'),
                 'digest': (digest, 'receipt-logs-unmatched')}
        for name, (tamper, reason) in cases.items():
            with self.subTest(name):
                toolchain, call, attempt = self.executed_call(f'final-{name}')
                path = call / f'receipt-{attempt.name}.json'
                receipt = json.loads(path.read_text())
                life = json.loads((attempt / 'lifecycle.json').read_text())
                self.assertEqual(receipt['pid'], life['identity']['pid'])
                self.assertNotEqual(receipt['pid'], life['commandPid'])
                # Positive control: the untouched receipts of a real call match their records.
                self.assertEqual([item for item in fx.inspect_commands(toolchain.evidence_root) if item.hold], [])
                tamper(receipt, life)
                path.write_text(json.dumps(receipt))
                self.assert_held_without_any_command(toolchain, reason)

    def test_receipt_of_a_failed_prepare_is_not_held(self):
        toolchain, call, attempt = self.executed_call('prepare')
        (call / f'claim-{attempt.name}.json').unlink()
        shutil.rmtree(attempt)
        self.failure_receipt(call / f'receipt-{attempt.name}.json', attempt, 'prepare:io-error')
        self.assertEqual([item for item in fx.inspect_commands(toolchain.evidence_root) if item.hold], [])
        self.assertEqual(self.observe(fx.WORKTREE_CREATE, self.spec(), toolchain=toolchain).state,
                         fx.NOT_APPLIED)

    def test_failed_prepare_over_a_foreign_attempt_holds(self):
        """'attempt-exists' means a directory this call never created held the id, so its
        loss is lost evidence, never proof that nothing was prepared."""
        toolchain, call, attempt = self.executed_call('foreign')
        (call / f'claim-{attempt.name}.json').unlink()
        shutil.rmtree(attempt)
        self.failure_receipt(call / f'receipt-{attempt.name}.json', attempt, 'prepare:attempt-exists')
        self.assert_held_without_any_command(toolchain, 'command-evidence-missing')


class WorktreeRemove(GitEffectsCase):
    def spec(self, path, branch, root=None):
        return fx.WorktreeRemoveSpec(repo=str(self.repo), common_dir=self.common_dir,
                                     cleanup_root=root or str(self.worktrees), path=path, branch=branch,
                                     expected_head=self.base_sha)

    def test_dirty_or_ignored_content_is_retained(self):
        path, branch = self.create_worktree('keep')
        (Path(path) / 'draft.txt').write_text('untracked work\n')
        outcome = self.execute(fx.WORKTREE_REMOVE, self.spec(path, branch))
        self.assertEqual((outcome.status, outcome.reason), (fx.REFUSED, 'worktree-not-clean'))
        (Path(path) / 'draft.txt').unlink()
        (Path(path) / 'debug.log').write_text('ignored but local\n')
        self.assertEqual(self.execute(fx.WORKTREE_REMOVE, self.spec(path, branch)).reason, 'worktree-not-clean')
        self.assertTrue((Path(path) / 'debug.log').exists())

    def test_clean_owned_worktree_is_removed_and_branch_kept(self):
        path, branch = self.create_worktree('done')
        spec = self.spec(path, branch)
        outcome = self.execute(fx.WORKTREE_REMOVE, spec)
        self.assertEqual(outcome.status, fx.COMPLETED, outcome.as_dict())
        self.assertFalse(Path(path).exists())
        self.assertEqual(self.observe(fx.WORKTREE_REMOVE, spec).state, fx.CONFIRMED)
        self.assertEqual(self.rev(branch), self.base_sha)

    def test_outside_cleanup_scope_or_main_worktree_is_rejected(self):
        path, branch = self.create_worktree('scoped')
        with self.assertRaises(fx.SpecError):
            fx.validate_spec(fx.WORKTREE_REMOVE, self.spec(path, branch, root=str(self.base / 'elsewhere')))
        with self.assertRaises(fx.SpecError):
            fx.validate_spec(fx.WORKTREE_REMOVE, self.spec(str(self.repo), 'main', root=str(self.base)))
        self.assertTrue(Path(path).exists())


if __name__ == '__main__':
    unittest.main()
