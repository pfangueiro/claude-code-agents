"""Installed controller exports from the real installers, exercised in one disposable HOME.

scripts/install-delivery.py installs the portable delivery resources into an explicit
disposable Claude home from a committed disposable copy of this checkout's delivery skills.
codex/framework.py installs the Codex edition into the same disposable home through its
user-scope install API (``install(home, user=True)``, what ``--user`` calls with
``Path.home()``), so the parent process HOME is never changed. The installed controller then
runs from BOTH known runtime layouts: Claude ``skills/delivery`` beside ``verified-handoff``
and Codex ``.agents/skills/sdlc-delivery`` beside ``sdlc-verified-handoff``.

No provider, network, real home, real account directory or real configuration is used.
Profiles name fixture executables that leave a marker if anything ever launches them, and
execution stays disabled. Account files in the fixture are placeholders, never credentials.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / 'scripts/install-delivery.py'
SOURCE_SCRIPTS = ROOT / '.claude/skills/delivery/scripts'
SOURCE_EVIDENCE = ROOT / '.claude/skills/verified-handoff/scripts/evidence.py'
GIT = shutil.which('git')
SYSTEM_PATH = ('/usr/bin', '/bin')
DELIVERY_SKILLS = ('delivery', 'repo-context', 'verified-handoff')
DELIVERY_FILES = ('rules/delivery.md', 'commands/commit-pr.md')
UPDATE_MARK = b'\n<!-- fixture update -->\n'
CODEX_UPDATED = '.agents/skills/sdlc-repo-context/SKILL.md'

_spec = importlib.util.spec_from_file_location('sdlc_codex_framework_exports', ROOT / 'codex/framework.py')
framework = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(framework)

CLAUDE_PERSONAL = {
    '.claude/settings.json': b'{"model": "fixture-personal", "hooks": {}}\n',
    '.claude/CLAUDE.md': b'Fixture personal instructions\n',
    '.claude/skills/personal-notes/SKILL.md': b'---\nname: personal-notes\ndescription: p\n---\n',
    '.claude/hooks/guard.sh': b'#!/bin/sh\nexit 0\n',
    '.claude/.credentials.json': b'{"fixture": "placeholder, not a credential"}\n',
}
CODEX_PERSONAL = {
    '.codex/config.toml': b'model = "fixture-model"\napproval_policy = "on-request"\n',
    '.codex/auth.json': b'{"fixture": "placeholder, not a credential"}\n',
    '.agents/skills/personal-skill/SKILL.md': b'---\nname: personal-skill\ndescription: p\n---\n',
}
OWNER_AGENTS = b'# Owner instructions\nKeep these rules outside the managed block.\n'

# Child probe: status must not load the engine; recover lazily loads it from the installed
# scripts/ directory, and the check runner it imports must accept the sibling evidence.py of
# THIS export (correct bundle name, safe mode, keyword-only supervisor seam).
PROBE = r'''
import contextlib, hashlib, io, json, sys
from pathlib import Path
scripts, state = sys.argv[1:3]
sys.path.insert(0, scripts)
import controller
with contextlib.redirect_stdout(io.StringIO()):
    status = controller.main(['status', '--state', state, '--json'])
loaded = sorted(name for name in ('controller_engine', 'controller_checks', 'controller_providers')
                if name in sys.modules)
recover = controller.main(['recover', '--state', state])
skill = Path(scripts).parent
evidence = skill.parent / controller.inputs.RUNTIME_LAYOUTS[skill.name][1] / 'scripts' / 'evidence.py'
checks = sys.modules['controller_checks']
module = checks._load_evidence(str(evidence), hashlib.sha256(evidence.read_bytes()).hexdigest())
print(json.dumps({
    'status': status, 'loaded_before_recover': loaded, 'recover': recover,
    'modules': {name: str(Path(m.__file__).resolve()) for name, m in sys.modules.items()
                if name.startswith('controller') and getattr(m, '__file__', None)},
    'evidence': str(evidence), 'evidence_seam': callable(getattr(module, 'run_check', None)),
}))
'''


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
    os.chmod(path, 0o600)


def entry(path):
    info = path.lstat()
    data = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
    return stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), data


def tree(base):
    if not base.exists():
        return {}
    return {str(path): entry(path) for path in [base, *sorted(base.rglob('*'))]}


def outside_block(data):
    """AGENTS.md bytes outside the single managed Codex block."""
    begin, end = framework.BEGIN.encode(), framework.END.encode()
    if begin not in data:
        return data
    low, high = data.index(begin), data.index(end) + len(end)
    if data[high:high + 1] == b'\n':
        high += 1
    return data[:low] + data[high:]


def runtime_names():
    names = sorted(p.name for p in SOURCE_SCRIPTS.iterdir() if p.is_file() and p.suffix == '.py'
                   and (p.name.startswith('controller') or p.name == 'sdlc_controller.py'))
    if 'controller.py' not in names or 'controller_engine.py' not in names:
        raise AssertionError(f'controller runtime not found in {SOURCE_SCRIPTS}')
    return names


@unittest.skipUnless(GIT, 'git is required')
class ControllerExports(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='controller-exports-')).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = self.private_dir('home')
        path = os.pathsep.join(dict.fromkeys([os.path.dirname(GIT), *SYSTEM_PATH]))
        self.env = {'PATH': path, 'HOME': str(self.home), 'TMPDIR': str(self.private_dir('tmp')),
                    'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        for name in ('owner', 'state', 'accounts', 'bin', 'markers'):
            self.private_dir(name)
        self.markers = self.root / 'markers'

    # ---- fixture ---------------------------------------------------------------------

    def private_dir(self, rel):
        path = self.root / rel
        path.mkdir(mode=0o700, parents=True)
        os.chmod(path, 0o700)
        return path

    def git(self, repo, *args):
        return subprocess.run([GIT, '-C', str(repo), *args], env=self.env, check=True,
                              capture_output=True, text=True, timeout=60).stdout.strip()

    def git_init(self, repo):
        repo.mkdir(parents=True, exist_ok=True)
        self.git(repo, 'init', '-q')
        for key, value in (('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid'),
                           ('commit.gpgsign', 'false')):
            self.git(repo, 'config', '--local', key, value)
        self.git(repo, 'add', '-A')
        self.git(repo, 'commit', '-q', '-m', 'fixture')
        return self.git(repo, 'rev-parse', 'HEAD')

    def personalize(self):
        for rel, data in {**CLAUDE_PERSONAL, **CODEX_PERSONAL, '.codex/AGENTS.md': OWNER_AGENTS}.items():
            (self.home / rel).parent.mkdir(parents=True, exist_ok=True)
            write_private(self.home / rel, data)

    def claude_source(self):
        """Committed disposable copy of this checkout's delivery resources (working-tree bytes)."""
        source = self.root / 'source'
        for name in DELIVERY_SKILLS:
            shutil.copytree(ROOT / '.claude/skills' / name, source / '.claude/skills' / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for rel in DELIVERY_FILES:
            (source / '.claude' / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / '.claude' / rel, source / '.claude' / rel)
        return source, self.git_init(source)

    def layouts(self):
        specs = (('claude', self.home / '.claude/skills', 'delivery', 'verified-handoff'),
                 ('codex', self.home / '.agents/skills', 'sdlc-delivery', 'sdlc-verified-handoff'))
        layouts = []
        for name, skills, delivery, handoff in specs:
            layout = SimpleNamespace(
                name=name, scripts=skills / delivery / 'scripts',
                evidence=skills / handoff / 'scripts/evidence.py',
                repo=self.root / 'work' / f'repo-{name}', state=self.root / 'state' / name,
                policy=self.root / 'owner' / f'policy-{name}.json',
                account=self.private_dir(f'accounts/{name}-1'), provider=self.root / 'bin' / f'fake-{name}')
            layout.binding = layout.repo / '.git/sdlc-controller.binding'
            layout.provider.write_text(f'#!/bin/sh\n: > {shlex.quote(str(self.markers / name))}\nexit 97\n')
            layout.provider.chmod(0o700)
            (layout.repo / 'src').mkdir(parents=True)
            (layout.repo / 'AGENTS.md').write_text('Follow the fixture rules.\n')
            (layout.repo / 'src/app.txt').write_text('app\n')
            layout.head = self.git_init(layout.repo)
            layouts.append(layout)
        return layouts

    def policy(self, layout):
        return {'version': 1, 'repository': str(layout.repo),
                'profiles': [{'id': f'{layout.name}-1', 'provider': layout.name,
                              'executable': str(layout.provider), 'config_dir': str(layout.account),
                              'roles': ['implement', 'review']}],
                'auto_route': False, 'execution_enabled': False, 'background_enabled': False,
                'max_parallel': 1, 'review_reserve': 0,
                'limits': {'max_attempts': 1, 'attempt_seconds': 60, 'max_total_seconds': 600,
                           'max_no_progress': 1, 'max_cost_usd': None},
                'allowed_checks': {'unit': [sys.executable, '-c', 'pass']},
                'effects': [], 'delivery': None, 'instruction_paths': ['AGENTS.md']}

    # ---- commands --------------------------------------------------------------------

    def run_ok(self, argv):
        result = subprocess.run(argv, env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def install_claude(self, *extra):
        return self.run_ok([sys.executable, '-I', '-B', str(INSTALLER), '--claude-home',
                            str(self.home / '.claude'), '--source', str(self.source), *extra])

    def cli(self, layout, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(layout.scripts / 'controller.py'),
                               *map(str, args)], env=self.env, capture_output=True, text=True,
                              timeout=120)

    def status(self, layout):
        result = self.cli(layout, 'status', '--state', layout.state, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS: status read (read-only; nothing was changed)', result.stderr)
        return json.loads(result.stdout)

    def manifests(self):
        claude = json.loads((self.home / '.claude/.sdlc-delivery/manifest.json').read_text())
        codex = json.loads((self.home / framework.MANIFEST).read_text())
        return claude, codex

    # ---- observations ----------------------------------------------------------------

    def preserved(self, layouts):
        """Everything the installers must never touch: personal config, foreign skills,
        placeholder account data, owner policy, controller state, bindings, accounts."""
        entries = {rel: entry(self.home / rel) for rel in {**CLAUDE_PERSONAL, **CODEX_PERSONAL}}
        entries['AGENTS.md outside block'] = outside_block((self.home / '.codex/AGENTS.md').read_bytes())
        for name in ('owner', 'state', 'accounts', 'bin', 'markers'):
            entries.update(tree(self.root / name))
        for layout in layouts:
            entries[str(layout.binding)] = entry(layout.binding) if layout.binding.exists() else None
        return entries

    def inventory(self):
        claude, codex = self.manifests()
        return (sorted(claude['files']), sorted(codex['files']),
                sorted(p.name for p in (self.home / '.agents/skills').iterdir()),
                sorted(p.name for p in (self.home / '.claude/skills').iterdir()))

    def assert_nothing_started(self, layouts):
        self.assertEqual(sorted(p.name for p in self.markers.iterdir()), [], 'a provider was launched')
        for layout in layouts:
            self.assertEqual(list(layout.account.iterdir()), [], 'account directory was written')

    def assert_exports(self, layouts):
        """Both exports carry the exact runtime bytes, and each manifest hashes what is installed."""
        names = runtime_names()
        for layout in layouts:
            installed = sorted(p.name for p in layout.scripts.iterdir() if p.suffix == '.py')
            self.assertEqual(installed, names, layout.name)
            for name in names:
                self.assertEqual((layout.scripts / name).read_bytes(), (SOURCE_SCRIPTS / name).read_bytes(),
                                 f'{layout.name}: {name}')
            self.assertEqual(layout.evidence.read_bytes(), SOURCE_EVIDENCE.read_bytes(), layout.name)
        claude, codex = self.manifests()
        self.assertEqual(claude['source_sha'], self.source_head)
        self.assertFalse(claude['consumed_source_dirty'])
        self.assertTrue(codex['user'])
        self.assertFalse(codex['hooks'])
        self.assertRegex(codex['source_sha'], '^[0-9a-f]{40}$')
        for base, files, prefix in ((self.home / '.claude', claude['files'], 'skills/delivery/scripts/'),
                                    (self.home, codex['files'], '.agents/skills/sdlc-delivery/scripts/')):
            for rel, checksum in files.items():
                self.assertEqual(sha256(base / rel), checksum, rel)
            self.assertTrue({prefix + name for name in names} <= set(files), prefix)

    def exercise(self, layout):
        """help, init, status, run (INCOMPLETE), STOP and lazy engine recovery from one export."""
        shown = self.cli(layout, '--help')
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn('Nothing starts automatically', shown.stdout)
        self.assertIn('INCOMPLETE exit 2', shown.stdout)
        write_private(layout.policy, json.dumps(self.policy(layout)).encode())
        init = self.cli(layout, 'init', '--state', layout.state, '--policy', layout.policy)
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertIn(f'worktree: clean at {layout.head}', init.stdout)
        self.assertIn(f'(committed instruction blobs at {layout.head})', init.stdout)
        layout.runtime_digest = re.search(r'^runtime_digest: ([0-9a-f]{64})$', init.stdout, re.M)[1]
        binding = json.loads(layout.binding.read_text())
        self.assertEqual(binding['state_dir'], str(layout.state))
        report = self.status(layout)
        self.assertEqual(report['identity_check'], {'runtime': 'match', 'rules': 'match', 'reason': None})
        self.assertFalse(report['policy']['execution_enabled'])
        self.assertEqual(report['status']['control'], 'running')
        self.assertEqual((report['plans'], report['requests']), ([], []))
        for key in ('attempts', 'effects', 'workspaces'):
            self.assertEqual(report['owned_work'][key], [], key)
        run = self.cli(layout, 'run', '--once', '--state', layout.state)
        self.assertEqual(run.returncode, 2, run.stderr)  # nothing executed: never PASS
        self.assertIn('INCOMPLETE', run.stderr)
        self.assertNotIn('PASS:', run.stderr)
        stop = self.cli(layout, 'stop', '--state', layout.state)
        self.assertEqual(stop.returncode, 0, stop.stderr)
        probe = subprocess.run([sys.executable, '-I', '-B', '-c', PROBE, str(layout.scripts), str(layout.state)],
                               env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        seen = json.loads(probe.stdout)
        self.assertEqual((seen['status'], seen['recover']), (0, 0), probe.stderr)
        self.assertEqual(seen['loaded_before_recover'], [], 'engine was not loaded lazily')
        self.assertTrue({'controller', 'controller_engine', 'controller_checks'} <= set(seen['modules']))
        for name, path in seen['modules'].items():
            self.assertEqual(Path(path).parent, layout.scripts, f'{layout.name}: {name} from {path}')
        self.assertEqual(seen['evidence'], str(layout.evidence))
        self.assertTrue(seen['evidence_seam'])
        after = self.status(layout)
        self.assertEqual(after['status']['control'], 'stopped')
        self.assertEqual(after['identity_check']['runtime'], 'match')
        self.assertEqual(stat.S_IMODE(layout.policy.stat().st_mode), 0o600)

    def assert_sibling_binding(self, layouts):
        """Each export's runtime identity binds its OWN sibling evidence.py, never the other's."""
        self.assertNotEqual(layouts[0].runtime_digest, layouts[1].runtime_digest)
        for changed in layouts:
            original = changed.evidence.read_bytes()
            try:
                changed.evidence.write_bytes(original + b'\n# fixture drift\n')
                for layout in layouts:
                    check = self.status(layout)['identity_check']
                    expected = 'differs' if layout is changed else 'match'
                    self.assertEqual((check['runtime'], check['rules']), (expected, 'match'),
                                     f'{changed.name} drift seen by {layout.name}')
            finally:
                changed.evidence.write_bytes(original)
        for layout in layouts:
            self.assertEqual(self.status(layout)['identity_check']['runtime'], 'match', layout.name)

    def update_both(self):
        """Real updates of a non-runtime managed resource through both installers."""
        skill = self.source / '.claude/skills/repo-context/SKILL.md'
        skill.write_bytes(skill.read_bytes() + UPDATE_MARK)
        self.git(self.source, 'commit', '-q', '-am', 'fixture update')
        self.source_head = self.git(self.source, 'rev-parse', 'HEAD')
        changed = self.install_claude().stdout
        self.assertIn('skills/repo-context/SKILL.md', changed)
        self.assertNotIn('skills/delivery/scripts/', changed)
        real_build = framework.build

        def updated_build():
            files = real_build()
            files[CODEX_UPDATED] += UPDATE_MARK
            return files
        with patch.object(framework, 'build', updated_build):
            self.assertIn(CODEX_UPDATED, framework.install(self.home, user=True))
        self.assertTrue((self.home / CODEX_UPDATED).read_bytes().endswith(UPDATE_MARK))
        self.assertIn(CODEX_UPDATED, framework.install(self.home, user=True))

    def assert_no_autostart_or_config_change(self):
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ['.agents', '.claude', '.codex'])
        self.assertEqual(sorted(p.name for p in (self.home / '.codex').iterdir()),
                         ['AGENTS.md', 'agents', 'auth.json', 'config.toml', 'framework'])
        self.assertEqual(sorted(p.name for p in (self.home / '.claude').iterdir()),
                         ['.credentials.json', '.sdlc-delivery', 'CLAUDE.md', 'commands', 'hooks',
                          'rules', 'settings.json', 'skills'])
        self.assertEqual(sorted(p.name for p in (self.home / '.claude/hooks').iterdir()), ['guard.sh'])
        self.assertFalse(self.manifests()[1]['hooks'])
        agents = (self.home / '.codex/AGENTS.md').read_bytes()
        self.assertEqual(agents.count(framework.BEGIN.encode()), 1)
        self.assertEqual(outside_block(agents), OWNER_AGENTS)

    # ---- scenario --------------------------------------------------------------------

    def test_both_installed_exports_run_controller_and_preserve_owner_data(self):
        self.personalize()
        self.source, self.source_head = self.claude_source()
        layouts = self.layouts()
        before = self.preserved(layouts)
        self.install_claude()
        framework.install(self.home, user=True)
        # Installing creates no state, binding, policy, account data, service or hook.
        self.assertEqual(self.preserved(layouts), before)
        self.assertEqual(list((self.root / 'state').iterdir()), [])
        self.assertEqual(list((self.root / 'owner').iterdir()), [])
        self.assert_no_autostart_or_config_change()
        self.assert_exports(layouts)
        for layout in layouts:
            with self.subTest(layout=layout.name):
                self.exercise(layout)
        self.assert_sibling_binding(layouts)
        self.assert_nothing_started(layouts)
        preserved, inventory = self.preserved(layouts), self.inventory()
        self.update_both()
        self.assertEqual(self.preserved(layouts), preserved)
        self.assertEqual(self.inventory(), inventory)
        self.install_claude('--check')
        self.assertEqual(framework.install(self.home, user=True, check=True), [])
        self.assert_exports(layouts)
        self.assert_no_autostart_or_config_change()
        for layout in layouts:
            report = self.status(layout)
            self.assertEqual(report['identity_check'], {'runtime': 'match', 'rules': 'match', 'reason': None})
            self.assertEqual(report['status']['control'], 'stopped', 'reinstall must not clear STOP')
            self.assertEqual(report['plans'], [])
        self.assert_nothing_started(layouts)


if __name__ == '__main__':
    unittest.main()
