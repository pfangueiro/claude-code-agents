"""Tests for the persistent-delivery controller input boundary (controller_inputs.py).

Everything runs in disposable private directories with isolated HOME and Git config;
nothing contacts a provider or the network.
"""
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.claude' / 'skills' / 'delivery' / 'scripts'))
import controller_inputs as ci  # noqa: E402


def _now_stamp(delta=dt.timedelta(hours=-1)):
    return (dt.datetime.now(dt.timezone.utc) + delta).strftime('%Y-%m-%dT%H:%M:%SZ')


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix='ctl-inputs-')))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / 'home'
        self.home.mkdir(mode=0o700)
        self.default_cfg = self.home / '.claude'
        self.default_cfg.mkdir(mode=0o700)
        patcher = mock.patch.dict(os.environ, {'HOME': str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME'):
            os.environ.pop(name, None)
        self.git_env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.git_env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                            GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                            GIT_COMMITTER_NAME='Test',
                            GIT_COMMITTER_EMAIL='test@example.invalid')
        self.private = self.tmp / 'private'
        self.private.mkdir(mode=0o700)
        self.bin = self.tmp / 'bin'
        self.bin.mkdir(mode=0o700)
        self.claude = self.executable(self.bin / 'claude')
        self.codex = self.executable(self.bin / 'codex')
        self.check = self.executable(self.bin / 'check')
        self.cfg = self.tmp / 'cfg-a'
        self.cfg.mkdir(mode=0o700)
        self.repo = self.tmp / 'repo'
        self.repo.mkdir(mode=0o700)
        self.git('init', '-q')
        (self.repo / 'AGENTS.md').write_text('rules v1\n')
        (self.repo / 'docs').mkdir()
        (self.repo / 'docs' / 'guide.md').write_text('guide\n')
        self.base = self.commit('init')

    def executable(self, path):
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o755)
        return path

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], env=self.git_env,
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def write_private(self, name, data, mode=0o600, directory=None):
        path = (directory or self.private) / name
        payload = data if isinstance(data, str) else json.dumps(data)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, 'w') as handle:
            handle.write(payload)
        os.chmod(path, mode)
        return path

    def policy(self, **changes):
        data = {
            'version': 1, 'repository': str(self.repo),
            'profiles': [{'id': 'main', 'provider': 'claude', 'executable': str(self.claude),
                          'config_dir': None, 'roles': ['implement', 'review']}],
            'auto_route': False, 'execution_enabled': False, 'background_enabled': False,
            'max_parallel': 1, 'review_reserve': 0,
            'limits': {'max_attempts': 3, 'attempt_seconds': 600, 'max_total_seconds': 3600,
                       'max_no_progress': 2, 'max_cost_usd': None},
            'allowed_checks': {'unit': [str(self.check), 'run', '--all']},
            'effects': ['commit', 'integrate'], 'delivery': None,
            'instruction_paths': ['AGENTS.md'],
        }
        data.update(changes)
        return data

    def plan(self, tasks=None):
        return {
            'version': 1, 'id': 'plan-1', 'objective': 'Ship it', 'input_revision': 'r1',
            'base_sha': self.base,
            'tasks': tasks if tasks is not None else [self.task('t1'),
                                                      self.task('t2', deps=['t1'],
                                                                scope=['src/a.py'])],
        }

    @staticmethod
    def task(task_id, deps=(), scope=('src/',), kind='feature', checks=('unit',)):
        return {'id': task_id, 'objective': 'Do work', 'kind': kind, 'depends_on': list(deps),
                'write_scope': list(scope), 'resources': ['db:main'], 'checks': list(checks),
                'acceptance': ['observable result']}

    def assertCode(self, code, func, *args):
        with self.assertRaises(ci.InputError) as ctx:
            func(*args)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))


class PolicyTests(Fixture):
    def test_single_account_round_trip(self):
        policy = self.policy()
        frozen = ci.read_policy(self.write_private('policy.json', policy))
        profile = dict(policy['profiles'][0], config_dir=str(self.default_cfg))
        self.assertEqual(frozen, dict(policy, profiles=[profile]))
        self.assertIsNone(policy['profiles'][0]['config_dir'])

    def test_distinct_config_dirs_allow_two_profiles(self):
        profiles = [self.policy()['profiles'][0],
                    {'id': 'second', 'provider': 'codex', 'executable': str(self.codex),
                     'config_dir': str(self.cfg), 'roles': ['review']}]
        ci.validate_policy(self.policy(profiles=profiles, max_parallel=2, review_reserve=1))

    def test_config_dir_aliases_rejected(self):
        link = self.tmp / 'cfg-link'
        link.symlink_to(self.cfg)
        base = {'provider': 'codex', 'executable': str(self.codex), 'roles': ['implement']}
        profiles = [dict(base, id='a', config_dir=str(self.cfg)),
                    dict(base, id='b', config_dir=str(link))]
        self.assertCode('schema', ci.validate_policy, self.policy(profiles=profiles))
        default_alias = [self.policy()['profiles'][0],
                         {'id': 'alt', 'provider': 'claude', 'executable': str(self.claude),
                          'config_dir': str(self.home / '.claude'), 'roles': ['review']}]
        self.assertCode('schema', ci.validate_policy, self.policy(profiles=default_alias))
        os.environ['CLAUDE_CONFIG_DIR'] = str(self.cfg)
        env_alias = [self.policy()['profiles'][0],
                     dict(default_alias[1], config_dir=str(self.cfg))]
        self.assertCode('schema', ci.validate_policy, self.policy(profiles=env_alias))

    def test_config_dir_must_not_be_home_or_repo(self):
        for directory in (self.home, self.repo / 'docs'):
            profile = dict(self.policy()['profiles'][0], config_dir=str(directory))
            self.assertCode('unauthorized', ci.validate_policy, self.policy(profiles=[profile]))

    def test_duplicate_ids_and_roles(self):
        profile = self.policy()['profiles'][0]
        twin = dict(profile, provider='codex', executable=str(self.codex))
        self.assertCode('schema', ci.validate_policy, self.policy(profiles=[profile, twin]))
        doubled = dict(profile, roles=['implement', 'implement'])
        self.assertCode('schema', ci.validate_policy, self.policy(profiles=[doubled]))

    def test_closed_schema_and_exact_types(self):
        missing = self.policy()
        del missing['effects']
        profile_extra = dict(self.policy()['profiles'][0], model='x')
        limits = dict(self.policy()['limits'], attempt_seconds=0)
        cases = [missing, self.policy(extra=1), self.policy(profiles=[profile_extra]),
                 self.policy(max_parallel=True), self.policy(version=True),
                 self.policy(review_reserve=1), self.policy(auto_route=1),
                 self.policy(limits=limits), self.policy(effects=['deploy']),
                 self.policy(effects=['commit', 'commit']),
                 self.policy(profiles=[dict(profile_extra, provider='other')])]
        for case in cases:
            self.assertCode('schema', ci.validate_policy, case)
        self.assertCode('unsupported', ci.validate_policy, self.policy(version=2))

    def test_cost_cap_is_unimplemented_and_every_non_null_value_refused(self):
        sentinel = 'sk-ant-api03-' + 'B' * 40
        for cap in (1.5, 0, -1, 10 ** 400, -(10 ** 400), float('nan'), float('inf'),
                    float('-inf'), True, False, '5', sentinel, [], {}):
            limits = dict(self.policy()['limits'], max_cost_usd=cap)
            with self.assertRaises(ci.InputError) as ctx:
                ci.validate_policy(self.policy(limits=limits))
            self.assertEqual(ctx.exception.code, 'unsupported', repr(cap)[:40])
            for leaked in ('sk-ant', 'BBBB', '1.5', '0000', 'nan', 'inf'):
                self.assertNotIn(leaked, str(ctx.exception))
        self.assertIsNone(ci.validate_policy(self.policy())['limits']['max_cost_usd'])
        for key in ('max_attempts', 'attempt_seconds', 'max_total_seconds', 'max_no_progress'):
            for value in (10 ** 400, -(10 ** 400), float('nan'), float('inf'), True):
                limits = dict(self.policy()['limits'], **{key: value})
                self.assertCode('schema', ci.validate_policy, self.policy(limits=limits))
        for value in (10 ** 400, float('inf'), True):
            self.assertCode('schema', ci.validate_policy, self.policy(max_parallel=value))
        text = json.dumps(self.policy()).replace('"max_cost_usd": null', '"max_cost_usd": 1e999')
        self.assertCode('schema', ci.read_policy, self.write_private('inf.json', text))
        nan = json.dumps(self.policy()).replace('"max_cost_usd": null', '"max_cost_usd": NaN')
        self.assertCode('schema', ci.read_policy, self.write_private('nan.json', nan))

    def test_duplicate_json_keys_rejected(self):
        text = json.dumps(self.policy())[:-1] + ', "version": 1}'
        self.assertCode('schema', ci.read_policy, self.write_private('dup.json', text))

    def test_unsafe_instruction_paths(self):
        for bad in ('../x', '/abs', '-opt', 'a//b', './a', '.git/config', 'a\nb', 'docs/',
                    ':x', 'a\\b'):
            self.assertCode('path', ci.validate_policy, self.policy(instruction_paths=[bad]))

    def test_check_argv_credentials_and_executables(self):
        for arg in ('--token=abc', 'ghp_abcdef123', 'https://u:p@host/x', '--api-key=abc',
                    '--client-secret=abc', 'GITHUB_TOKEN=abc', 'Authorization: Bearer abcdefgh1234',
                    'AKIAABCDEFGHIJKLMNOP', 'sk-ant-api03-abcdefghijklmnopqrstuvwx'):
            checks = {'unit': [str(self.check), arg]}
            self.assertCode('unauthorized', ci.validate_policy, self.policy(allowed_checks=checks))
        for exe in ('check', str(self.bin / 'missing'), str(self.bin / '..' / 'bin' / 'check')):
            self.assertCode('path', ci.validate_policy, self.policy(allowed_checks={'unit': [exe]}))
        self.assertCode('schema', ci.validate_policy, self.policy(allowed_checks={'bad id': [
            str(self.check)]}))

    def test_ordinary_names_with_credential_words_are_accepted(self):
        ordinary = ('tests.test_token_rotation', 'tests/test_password_reset.py',
                    'tests.test_rotation', 'secrets/fixtures/', 'test_api_key_rotation',
                    '--token-file=tokens.txt', '--passwordless', 'docs/authorization.md')
        policy = ci.validate_policy(self.policy(allowed_checks={
            'unit': [str(self.check), *ordinary, '--token']}))
        self.assertEqual(policy['allowed_checks']['unit'][1:-1], list(ordinary))

    def test_separated_credential_option_is_refused_without_echoing_the_value(self):
        checks = {'unit': [str(self.check), '--password', 'hunter2-value']}
        with self.assertRaises(ci.InputError) as ctx:
            ci.validate_policy(self.policy(allowed_checks=checks))
        self.assertEqual(ctx.exception.code, 'unauthorized')
        self.assertNotIn('hunter2', str(ctx.exception))
        with self.assertRaises(ci.InputError) as ctx:
            ci.validate_policy(self.policy(allowed_checks={'unit': [str(self.check), '--token=s3cr3t-value']}))
        self.assertNotIn('s3cr3t', str(ctx.exception))

    def test_provider_executable_inside_repo_rejected(self):
        inner = self.executable(self.repo / 'tool.sh')
        profile = dict(self.policy()['profiles'][0], executable=str(inner))
        self.assertCode('unauthorized', ci.validate_policy, self.policy(profiles=[profile]))

    def test_repository_must_be_canonical_root(self):
        self.assertCode('path', ci.validate_policy, self.policy(repository=str(self.repo / 'docs')))
        self.assertCode('git', ci.validate_policy, self.policy(repository=str(self.cfg)))

    def test_inherited_git_selectors_ignored(self):
        os.environ['GIT_DIR'] = str(self.tmp / 'nowhere')
        os.environ['GIT_WORK_TREE'] = str(self.cfg)
        self.assertEqual(ci.canonical_repo(self.repo)['root'], str(self.repo))

    def test_policy_inside_repository_rejected(self):
        path = self.write_private('policy.json', self.policy(), directory=self.repo)
        self.assertCode('unauthorized', ci.read_policy, path)


class PrivateFileTests(Fixture):
    def test_valid_private_file(self):
        path = self.write_private('ok.json', '{}')
        self.assertEqual(ci.private_file(path), path)

    def test_refusals(self):
        loose = self.write_private('loose.json', '{}', mode=0o644)
        link = self.private / 'link.json'
        link.symlink_to(self.write_private('target.json', '{}'))
        linked_dir = self.tmp / 'private-link'
        linked_dir.symlink_to(self.private)
        shared = self.tmp / 'shared'
        shared.mkdir()
        shared.chmod(0o770)
        in_shared = self.write_private('x.json', '{}', directory=shared)
        hard = self.write_private('hard.json', '{}')
        os.link(hard, self.private / 'hard2.json')
        for path in (loose, link, linked_dir / 'target.json', in_shared, hard, self.private,
                     self.private / 'missing.json'):
            self.assertCode('file', ci.private_file, path)
        self.assertCode('path', ci.private_file, 'relative.json')
        self.assertCode('file', ci.read_policy, self.write_private('p.json', self.policy(), 0o640))


class PlanTests(Fixture):
    def setUp(self):
        super().setUp()
        self.policy_v = ci.validate_policy(self.policy())

    def test_valid_plan_with_parent_child_scopes(self):
        plan = self.plan()
        self.assertEqual(ci.validate_plan(plan, self.policy_v), plan)
        path = self.tmp / 'plan.json'
        path.write_text(json.dumps(plan))
        self.assertEqual(ci.read_plan(path, self.policy_v), plan)

    def test_dependency_errors(self):
        cases = [[self.task('t1', deps=['ghost'])],
                 [self.task('t1', deps=['t2']), self.task('t2', deps=['t1'])],
                 [self.task('t1', deps=['t1'])]]
        for tasks in cases:
            self.assertCode('dependency', ci.validate_plan, self.plan(tasks), self.policy_v)

    def test_schema_errors(self):
        widened = dict(self.task('t1'), effects=['push'])
        bad_sha = dict(self.plan(), base_sha='abc123')
        cases = [self.plan([self.task('t1'), self.task('t1')]), self.plan([widened]),
                 self.plan([dict(self.task('t1'), profile='main')]), bad_sha,
                 self.plan([self.task('t1', scope=())]), self.plan([]),
                 self.plan([dict(self.task('t1'), acceptance=[])])]
        for plan in cases:
            self.assertCode('schema', ci.validate_plan, plan, self.policy_v)
        ci.validate_plan(self.plan([self.task('t1', scope=(), kind='investigation')]),
                         self.policy_v)

    def test_unauthorized_check_and_unsafe_scope(self):
        self.assertCode('unauthorized', ci.validate_plan,
                        self.plan([self.task('t1', checks=['deploy'])]), self.policy_v)
        for bad in ('../x', '.git/hooks/', '/etc/'):
            self.assertCode('path', ci.validate_plan, self.plan([self.task('t1', scope=[bad])]),
                            self.policy_v)

    def test_plan_symlink_refused(self):
        real = self.tmp / 'plan.json'
        real.write_text(json.dumps(self.plan()))
        link = self.tmp / 'plan-link.json'
        link.symlink_to(real)
        self.assertCode('file', ci.read_plan, link, self.policy_v)

    @staticmethod
    def open_fds():
        return len(os.listdir('/dev/fd'))

    @unittest.skipUnless(hasattr(os, 'mkfifo') and os.path.isdir('/dev/fd'), 'needs FIFOs and /dev/fd')
    def test_non_regular_plan_is_a_file_refusal_without_hang_or_fd_leak(self):
        directory = self.tmp / 'plan-dir'
        directory.mkdir()
        fifo = self.tmp / 'plan.fifo'
        os.mkfifo(fifo)  # no writer: a blocking open or read would hang here
        before = self.open_fds()
        for path in (directory, fifo, directory, fifo):
            with self.assertRaises(ci.InputError) as ctx:
                ci.read_plan(path, self.policy_v)
            self.assertEqual(ctx.exception.code, 'file', str(ctx.exception))
            self.assertIn('regular file', str(ctx.exception))
            self.assertNotIn(str(self.tmp), str(ctx.exception))
        self.assertEqual(before, self.open_fds())

    def test_plan_size_limit_and_encoding_boundaries(self):
        path = self.tmp / 'plan.json'
        path.write_text(json.dumps(self.plan()))
        size = path.stat().st_size
        with mock.patch.object(ci, 'MAX_FILE_BYTES', size):
            self.assertEqual(ci.read_plan(path, self.policy_v), self.plan())
        with mock.patch.object(ci, 'MAX_FILE_BYTES', size - 1):
            self.assertCode('file', ci.read_plan, path, self.policy_v)
        bad = self.tmp / 'bad-utf8.json'
        bad.write_bytes(b'{"id": "\xff"}')
        self.assertCode('schema', ci.read_plan, bad, self.policy_v)

    def test_scopes(self):
        self.assertTrue(ci.scopes_conflict(['src/'], ['src/a.py']))
        self.assertTrue(ci.scopes_conflict('src/a/', ['src/']))
        self.assertTrue(ci.scopes_conflict(['docs'], ['docs/']))
        self.assertFalse(ci.scopes_conflict(['src/a.py'], ['src/b.py']))
        self.assertFalse(ci.scopes_conflict(['src/'], ['srcx/']))
        self.assertFalse(ci.scopes_conflict([], ['src/']))
        self.assertTrue(ci.scope_allows('src/a/b.py', ['src/']))
        self.assertTrue(ci.scope_allows('src/a.py', 'src/a.py'))
        self.assertFalse(ci.scope_allows('srcx/a.py', ['src/']))
        self.assertFalse(ci.scope_allows('src/../etc/x', ['src/']))
        self.assertFalse(ci.scope_allows('src/', ['src/']))
        self.assertCode('path', ci.scope_allows, 'a', ['../'])


class AuthorityTests(Fixture):
    def setUp(self):
        super().setUp()
        self.policy_v = ci.validate_policy(self.policy())
        self.plan_v = ci.validate_plan(self.plan(), self.policy_v)

    def authority(self, **changes):
        data = {'version': 1, 'plan_digest': ci.canonical_digest(self.plan_v),
                'effects': ['commit'], 'authorizer': 'Owner', 'approved_at': _now_stamp()}
        data.update(changes)
        return data

    def read(self, data, name='authority.json', directory=None):
        path = self.write_private(name, data, directory=directory)
        return ci.read_authority(path, self.policy_v, self.plan_v)

    def test_valid_authority(self):
        data = self.authority()
        self.assertEqual(self.read(data), data)

    def test_refusals(self):
        self.assertCode('digest', self.read, self.authority(plan_digest='0' * 64))
        self.assertCode('unauthorized', self.read, self.authority(effects=['push']), 'a2.json')
        for idx, stamp in enumerate((_now_stamp(dt.timedelta(days=1)),
                                     '2026-01-01T00:00:00+01:00', '2026-13-01T00:00:00Z')):
            self.assertCode('schema', self.read, self.authority(approved_at=stamp), f'b{idx}.json')
        self.assertCode('schema', self.read, self.authority(extra=True), 'c.json')
        self.assertCode('unauthorized', self.read, self.authority(), 'in-repo.json', self.repo)


class DigestTests(Fixture):
    def test_canonical_digest_is_order_stable_and_change_sensitive(self):
        self.assertEqual(ci.canonical_digest({'a': 1, 'b': [1, 2]}),
                         ci.canonical_digest({'b': [1, 2], 'a': 1}))
        self.assertNotEqual(ci.canonical_digest({'a': 1}), ci.canonical_digest({'a': 2}))
        self.assertCode('schema', ci.canonical_digest, {'a': float('inf')})

    def test_rules_digest(self):
        first = ci.rules_digest(self.repo, self.base, ['AGENTS.md'])
        self.assertEqual(first, ci.rules_digest(str(self.repo), self.base, ['AGENTS.md']))
        (self.repo / 'AGENTS.md').write_text('uncommitted\n')
        self.assertEqual(first, ci.rules_digest(self.repo, self.base, ['AGENTS.md']))
        changed = self.commit('change')
        self.assertNotEqual(first, ci.rules_digest(self.repo, changed, ['AGENTS.md']))
        self.assertNotEqual(first, ci.rules_digest(self.repo, self.base,
                                                   ['AGENTS.md', 'docs/guide.md']))
        self.assertCode('git', ci.rules_digest, self.repo, self.base, ['missing.md'])
        self.assertCode('path', ci.rules_digest, self.repo, self.base, ['docs/'])
        self.assertCode('git', ci.rules_digest, self.repo, self.base, ['docs'])
        self.assertCode('git', ci.rules_digest, self.repo, 'f' * 40, ['AGENTS.md'])
        self.assertCode('schema', ci.rules_digest, self.repo, 'HEAD', ['AGENTS.md'])



RUNTIME_FILES = {
    'delivery': {'SKILL.md': b'procedure\n', 'references/acceptance-by-task.md': b'acceptance\n',
                 'references/task-contract.md': b'contract\n',
                 'references/repository-measurements.md': b'optional\n',
                 'scripts/controller_a.py': b'a = 1\n', 'scripts/unrelated.py': b'x\n'},
    'handoff': {'SKILL.md': b'handoff\n', 'scripts/evidence.py': b'receipt = 1\n'},
}
REQUIRED = ('delivery/SKILL.md', 'delivery/references/acceptance-by-task.md',
            'delivery/references/task-contract.md', 'verified-handoff/scripts/evidence.py')


class RuntimeDigestTests(Fixture):
    def layout(self, delivery='delivery', handoff='verified-handoff', root='skills'):
        """A minimal installed layout holding every required resource."""
        skills = self.tmp / root
        for name, files in ((delivery, RUNTIME_FILES['delivery']), (handoff, RUNTIME_FILES['handoff'])):
            for rel, data in files.items():
                path = skills / name / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        return skills / delivery / 'scripts'

    def test_version_and_controller_selection(self):
        self.assertEqual(ci.RUNTIME_DIGEST_VERSION, 'sdlc-runtime-v2')
        scripts = self.layout()
        first = ci.runtime_digest(scripts)
        self.assertRegex(first, r'^[0-9a-f]{64}$')
        self.assertEqual(first, ci.runtime_digest(str(scripts)))
        (scripts / 'unrelated.py').write_text('y\n')
        self.assertEqual(first, ci.runtime_digest(scripts))
        (scripts / 'sdlc_controller.py').write_text('main\n')
        second = ci.runtime_digest(scripts)
        self.assertNotEqual(first, second)
        (scripts / 'controller_a.py').write_text('a = 2\n')
        self.assertNotEqual(second, ci.runtime_digest(scripts))
        (scripts / 'controller_link.py').symlink_to(scripts / 'controller_a.py')
        self.assertCode('file', ci.runtime_digest, scripts)

    def test_no_controller_files_refused(self):
        scripts = self.layout()
        (scripts / 'controller_a.py').unlink()
        self.assertCode('file', ci.runtime_digest, scripts)

    def test_each_loaded_resource_is_bound_and_restored_bytes_restore_the_digest(self):
        scripts = self.layout()
        skills = scripts.parent.parent
        first = ci.runtime_digest(scripts)
        for rel in REQUIRED:
            path = skills / rel
            original = path.read_bytes()
            path.write_bytes(original + b'# changed\n')
            self.assertNotEqual(first, ci.runtime_digest(scripts), rel)
            path.write_bytes(original)
            self.assertEqual(first, ci.runtime_digest(scripts), rel)

    def test_unloaded_documents_are_not_bound(self):
        scripts = self.layout()
        skills = scripts.parent.parent
        first = ci.runtime_digest(scripts)
        (skills / 'delivery/references/repository-measurements.md').write_bytes(b'edited\n')
        (skills / 'verified-handoff/SKILL.md').write_bytes(b'edited\n')
        (skills / 'delivery/references/extra.md').write_bytes(b'new\n')
        (skills / 'other-skill').mkdir()
        (skills / 'other-skill/SKILL.md').write_bytes(b'foreign\n')
        self.assertEqual(first, ci.runtime_digest(scripts))

    def test_missing_aliased_or_wrong_edition_resource_refused(self):
        for idx, rel in enumerate(REQUIRED):
            scripts = self.layout(root=f'missing-{idx}')
            (scripts.parent.parent / rel).unlink()
            self.assertCode('file', ci.runtime_digest, scripts)
        scripts = self.layout(root='linked-file')
        evidence = scripts.parent.parent / 'verified-handoff/scripts/evidence.py'
        copy = self.tmp / 'evidence-copy.py'
        copy.write_bytes(evidence.read_bytes())
        evidence.unlink()
        evidence.symlink_to(copy)
        self.assertCode('file', ci.runtime_digest, scripts)
        scripts = self.layout(root='linked-dir')
        foreign = self.layout(root='foreign').parent.parent / 'verified-handoff'
        shutil.rmtree(scripts.parent.parent / 'verified-handoff')
        (scripts.parent.parent / 'verified-handoff').symlink_to(foreign, target_is_directory=True)
        self.assertCode('file', ci.runtime_digest, scripts)
        scripts = self.layout(root='not-regular')
        evidence = scripts.parent.parent / 'verified-handoff/scripts/evidence.py'
        evidence.unlink()
        evidence.mkdir()
        self.assertCode('file', ci.runtime_digest, scripts)
        mixed = self.layout(delivery='sdlc-delivery', handoff='verified-handoff', root='mixed')
        self.assertCode('file', ci.runtime_digest, mixed)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'needs FIFOs')
    def test_fifo_resource_or_controller_refused_without_hang(self):
        scripts = self.layout(root='fifo-resource')
        evidence = scripts.parent.parent / 'verified-handoff/scripts/evidence.py'
        evidence.unlink()
        os.mkfifo(evidence)
        self.assertCode('file', ci.runtime_digest, scripts)
        scripts = self.layout(root='fifo-controller')
        os.mkfifo(scripts / 'controller_pipe.py')
        self.assertCode('file', ci.runtime_digest, scripts)

    def test_both_installed_layouts_and_edition_is_bound(self):
        claude = ci.runtime_digest(self.layout(root='claude-home/skills'))
        codex = ci.runtime_digest(self.layout(delivery='sdlc-delivery', handoff='sdlc-verified-handoff',
                                              root='project/.agents/skills'))
        self.assertRegex(codex, r'^[0-9a-f]{64}$')
        self.assertNotEqual(claude, codex)

    def test_unknown_or_noncanonical_layout_refused(self):
        plain = self.tmp / 'runtime'
        plain.mkdir()
        (plain / 'controller_a.py').write_text('a = 1\n')
        self.assertCode('path', ci.runtime_digest, plain)
        self.assertCode('path', ci.runtime_digest, self.layout(delivery='other-skill', root='other'))
        link = self.tmp / 'scripts-link'
        link.symlink_to(self.layout(), target_is_directory=True)
        self.assertCode('path', ci.runtime_digest, link)
        self.assertCode('path', ci.runtime_digest, 'relative/scripts')

    def test_hashing_never_executes_resources(self):
        scripts = self.layout()
        marker = self.tmp / 'executed'
        payload = f'open({str(marker)!r}, "w").close()\n'.encode()
        for path in (scripts / 'controller_a.py',
                     scripts.parent.parent / 'verified-handoff/scripts/evidence.py'):
            path.write_bytes(payload)
            path.chmod(0o755)
        ci.runtime_digest(scripts)
        self.assertFalse(marker.exists())

    def test_shipped_source_layout_has_every_required_resource(self):
        shipped = ROOT / '.claude' / 'skills' / 'delivery' / 'scripts'
        self.assertRegex(ci.runtime_digest(shipped), r'^[0-9a-f]{64}$')


class FrozenProfileTests(Fixture):
    def test_default_profile_is_materialized_and_env_cannot_reselect(self):
        frozen = ci.validate_policy(self.policy())
        self.assertEqual(frozen['profiles'][0]['config_dir'], str(self.default_cfg))
        self.assertEqual(ci.validate_policy(frozen), frozen)
        os.environ['CLAUDE_CONFIG_DIR'] = str(self.cfg)
        self.assertEqual(ci.validate_policy(frozen), frozen)  # the frozen policy ignores the env
        moved = ci.validate_policy(self.policy())
        self.assertEqual(moved['profiles'][0]['config_dir'], str(self.cfg))
        self.assertNotEqual(ci.canonical_digest(moved), ci.canonical_digest(frozen))

    def test_default_goes_through_the_explicit_path_checks(self):
        refused = ((self.repo / 'docs', 'unauthorized'), (self.home, 'unauthorized'),
                   (self.tmp / 'absent', 'path'), ('relative/dir', 'path'))
        for directory, code in refused:
            os.environ['CLAUDE_CONFIG_DIR'] = str(directory)
            self.assertCode(code, ci.validate_policy, self.policy())
        del os.environ['CLAUDE_CONFIG_DIR']
        shutil.rmtree(self.default_cfg)
        self.assertCode('path', ci.validate_policy, self.policy())

    def test_explicit_config_dir_is_canonicalized(self):
        link = self.tmp / 'cfg-link'
        link.symlink_to(self.cfg)
        profile = dict(self.policy()['profiles'][0], config_dir=str(link))
        frozen = ci.validate_policy(self.policy(profiles=[profile]))
        self.assertEqual(frozen['profiles'][0]['config_dir'], str(self.cfg))


class DeliveryTests(Fixture):
    @staticmethod
    def delivery(**changes):
        data = {'remote': 'origin', 'remote_url': 'https://github.com/example-org/example-repo.git',
                'github_repo': 'example-org/example-repo', 'base_branch': 'main',
                'branch_prefix': 'sdlc/', 'required_checks': ['build'], 'merge_method': 'squash'}
        data.update(changes)
        return data

    def test_null_target_disables_external_effects(self):
        for effect in ci.EXTERNAL_EFFECTS:
            self.assertCode('unauthorized', ci.validate_policy, self.policy(effects=['commit', effect]))
        full = self.policy(effects=['commit', 'push', 'pr', 'merge'], delivery=self.delivery())
        self.assertEqual(ci.validate_policy(full)['delivery'], self.delivery())
        ci.validate_policy(self.policy(effects=['push'], delivery=self.delivery(required_checks=[])))
        ci.validate_policy(self.policy(delivery=self.delivery(
            remote_url='git@github.com:example-org/example-repo.git')))

    def test_target_fields_are_closed_and_strict(self):
        extra = dict(self.delivery(), token_env='X')
        bad = [self.delivery(merge_method='rebase'), self.delivery(branch_prefix='sdlc'),
               self.delivery(base_branch='sdlc/main'), self.delivery(base_branch='a..b'),
               self.delivery(remote_url='file:///srv/repo'), self.delivery(remote_url='/srv/repo'),
               self.delivery(remote_url='--upload-pack=x'), self.delivery(github_repo='a/b/c'),
               self.delivery(remote='-o'), self.delivery(required_checks=['build', 'build']),
               self.delivery(required_checks='build'), extra, 'origin']
        for value in bad:
            self.assertCode('schema', ci.validate_policy, self.policy(effects=['push'], delivery=value))
        merge = self.policy(effects=['merge'], delivery=self.delivery(required_checks=[]))
        self.assertCode('schema', ci.validate_policy, merge)
        leaked = self.delivery(remote_url='https://user:pass@github.com/example-org/example-repo.git')
        self.assertCode('unauthorized', ci.validate_policy, self.policy(effects=['push'], delivery=leaked))

    def test_external_authority_needs_a_target(self):
        plan = ci.validate_plan(self.plan(), ci.validate_policy(self.policy()))
        loose = dict(self.policy(), effects=['push'])  # deliberately not validated: no target
        authority = {'version': 1, 'plan_digest': ci.canonical_digest(plan), 'effects': ['push'],
                     'authorizer': 'Owner', 'approved_at': _now_stamp()}
        self.assertCode('unauthorized', ci.validate_authority, authority, loose, plan)
        bound = ci.validate_policy(self.policy(effects=['push'], delivery=self.delivery()))
        self.assertEqual(ci.validate_authority(authority, bound, plan), authority)

    def test_effect_specs_are_bound_to_the_frozen_target(self):
        target = self.delivery()
        spec = {'branch': 'sdlc/plan-1/t1', 'github_repo': 'example-org/example-repo'}
        self.assertEqual(ci.check_delivery_spec('push', spec, target), dict(spec, target=target))
        for changed in ({'github_repo': 'other-org/other'}, {'remote': 'fork'},
                        {'remote_url': 'https://github.com/other-org/other.git'},
                        {'base_branch': 'release'}, {'branch': 'main'}, {'branch': 'feature/x'},
                        {'target': {}}):
            self.assertCode('unauthorized', ci.check_delivery_spec, 'pr', dict(spec, **changed), target)
        self.assertCode('unauthorized', ci.check_delivery_spec, 'push', spec, None)
        self.assertCode('unauthorized', ci.check_delivery_spec, 'merge', spec,
                        self.delivery(required_checks=[]))
        for malformed in ({}, {'branch': 'sdlc/'}, {'branch': 5}, 'sdlc/x'):
            self.assertCode('schema', ci.check_delivery_spec, 'push', malformed, target)
        self.assertCode('schema', ci.check_delivery_spec, 'commit', spec, target)
        self.assertEqual(ci.EFFECT_CATALOG, {'task.commit': 'commit', 'integrate': 'integrate',
                                             'push': 'push', 'pr.create': 'pr', 'pr.merge': 'merge'})


class CanonicalJsonTests(Fixture):
    def test_canonical_json_is_sorted_compact_literal_utf8(self):
        self.assertEqual(ci.canonical_json({'b': 'régression', 'a': [1, None]}),
                         '{"a":[1,null],"b":"régression"}')
        self.assertEqual(ci.canonical_digest({'b': 'é'}),
                         ci.canonical_digest(json.loads('{"b": "\\u00e9"}')))
        for bad in ({'a': float('nan')}, {'a': '\udc80'}, {'a': object()}):
            self.assertCode('schema', ci.canonical_json, bad)


if __name__ == '__main__':
    unittest.main()
