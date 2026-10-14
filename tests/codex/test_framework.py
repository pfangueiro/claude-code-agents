"""Acceptance checks operate only in temporary projects and simulated homes."""
import json
from pathlib import Path
import subprocess
import os
import re
import shutil
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'codex'))
import framework as f
import hook


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class FrameworkAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='codex-acceptance-')
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_inventory_and_loadable_formats(self):
        f.install(self.root)
        inv = f.source_inventory()
        skills = list((self.root / '.agents/skills').glob('*/SKILL.md'))
        self.assertEqual(len(skills), len(inv['skills']) + len(inv['commands']) + len(inv['agents']))
        self.assertEqual(len(skills), 55)
        self.assertEqual(sum(not p.parent.name.startswith('sdlc-agent-') for p in skills), 42)
        self.assertEqual({p.parent.name for p in skills if p.parent.name.startswith('sdlc-agent-')},
                         {'sdlc-agent-' + name for name in inv['agents']})
        self.assertFalse(any(p.parent.name.endswith('README') for p in skills))
        for path in skills:
            meta, body = f.frontmatter(path)
            self.assertEqual(meta['name'], path.parent.name)
            self.assertEqual(set(meta), {'name', 'description'})
            self.assertTrue(body.strip())
        agents = list((self.root / '.codex/agents').glob('*.toml'))
        self.assertEqual({p.stem for p in agents}, set(inv['agents']))
        for path in agents:
            role = tomllib.loads(path.read_text())
            self.assertEqual(role['name'], path.stem)
            self.assertTrue(role['developer_instructions'])
            self.assertNotIn('model', role)
            self.assertNotIn('tools', role)
        for name in ('commit-pr', 'create-jira', 'new-feature'):
            policy = yaml.safe_load((self.root / f'.agents/skills/sdlc-{name}/agents/openai.yaml').read_text())
            self.assertFalse(policy['policy']['allow_implicit_invocation'])
        explicit = {p.parents[1].name for p in (self.root / '.agents/skills').glob('*/agents/openai.yaml')}
        self.assertEqual(explicit, {'sdlc-commit-pr', 'sdlc-create-jira', 'sdlc-new-feature'})
        self.assertEqual(len(skills) - len(explicit), 52)
        tomllib.loads((self.root / '.codex/framework/mcp.example.toml').read_text())
        # The footer fragment is one mergeable field of unique native IDs verified against the
        # Codex CLI footer item list; cost/credit estimates and unknown IDs are rejected.
        footer = tomllib.loads((self.root / '.codex/framework/statusline.example.toml').read_text())
        self.assertEqual(set(footer), {'tui'})
        self.assertEqual(set(footer['tui']), {'status_line'})
        items = footer['tui']['status_line']
        self.assertTrue(items and all(isinstance(item, str) for item in items))
        self.assertEqual(len(items), len(set(items)))
        self.assertEqual(items[0], 'thread-title')
        native = {'thread-title', 'model-with-reasoning', 'context-remaining', 'used-tokens',
                  'five-hour-limit', 'weekly-limit', 'git-branch', 'current-dir',
                  'context-window-size', 'total-input-tokens', 'total-output-tokens', 'codex-version'}
        self.assertLessEqual(set(items), native)
        self.assertFalse([item for item in items if re.search('cost|credit', item)])

    def test_idempotence_dry_run_and_personal_preservation(self):
        personal = {'.codex/config.toml': b'model = "personal"\n[tui]\nstatus_line = ["model"]\n',
                    '.codex/auth.json': b'{"private":true}',
                    '.agents/skills/personal/SKILL.md': b'personal', '.claude/settings.json': b'{"owned":"claude"}',
                    'AGENTS.md': b'Owner instructions without trailing newline'}
        for name, data in personal.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        before = snapshot(self.root)
        f.install(self.root, dry_run=True)
        self.assertEqual(snapshot(self.root), before)
        f.install(self.root)
        installed = snapshot(self.root)
        self.assertEqual(f.install(self.root), [])
        self.assertEqual(snapshot(self.root), installed)
        f.install(self.root, check=True)
        f.install(self.root, uninstall=True)
        self.assertEqual(snapshot(self.root), before)

    def test_foreign_collision_changes_nothing(self):
        p = self.root / '.agents/skills/sdlc-tdd/SKILL.md'
        p.parent.mkdir(parents=True)
        p.write_bytes(b'personal tdd')
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, 'foreign'):
            f.install(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_dry_run_does_not_create_destination(self):
        destination = self.root / 'not-created'
        f.install(destination, dry_run=True)
        self.assertFalse(destination.exists())

    @unittest.skipUnless(shutil.which('codex'), 'Codex CLI not installed; native discovery not verified')
    def test_native_cli_loads_implicit_skills_and_managed_instructions(self):
        project, home = self.root / 'project', self.root / 'home'
        project.mkdir()
        (home / '.codex').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
        f.install(project)
        (home / '.codex/config.toml').write_text('[projects.' + json.dumps(str(project)) + ']\ntrust_level = "trusted"\n')
        env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / '.codex'))
        result = subprocess.run(['codex', '-C', str(project), 'debug', 'prompt-input', 'Inspect available workflows'],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = json.dumps(json.loads(result.stdout))
        inv = f.source_inventory()
        names = {'sdlc-' + n for n in inv['skills'] + inv['commands']} | {'sdlc-agent-' + n for n in inv['agents']}
        expected = names - {'sdlc-commit-pr', 'sdlc-create-jira', 'sdlc-new-feature'}
        self.assertEqual({n for n in names if n in text}, expected)
        self.assertIn('SDLC framework for Codex', text)
        self.assertIn('SDLC | <short task>', text)

    def test_modified_owned_file_survives_update_and_uninstall(self):
        f.install(self.root)
        p = self.root / '.codex/agents/api-backend.toml'
        p.write_bytes(p.read_bytes() + b'# owner customization\n')
        before = snapshot(self.root)
        for options in ({}, {'uninstall': True}, {'check': True}):
            with self.assertRaisesRegex(ValueError, 'modified'):
                f.install(self.root, **options)
            self.assertEqual(snapshot(self.root), before)

    def test_missing_owned_file_can_be_repaired(self):
        f.install(self.root)
        p = self.root / '.agents/skills/sdlc-tdd/SKILL.md'
        original = p.read_bytes()
        p.unlink()
        with self.assertRaisesRegex(ValueError, 'drift'):
            f.install(self.root, check=True)
        f.install(self.root)
        self.assertEqual(p.read_bytes(), original)

    def test_foreign_and_modified_instruction_blocks_rejected(self):
        p = self.root / 'AGENTS.md'
        p.write_bytes(f.instructions())
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, 'foreign'):
            f.install(self.root)
        self.assertEqual(snapshot(self.root), before)
        p.unlink()
        f.install(self.root)
        p.write_bytes(p.read_bytes().replace(b'Inherit model', b'Override model'))
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, 'modified'):
            f.install(self.root, uninstall=True)
        self.assertEqual(snapshot(self.root), before)

    def test_instruction_edits_outside_block_preserved(self):
        f.install(self.root)
        p = self.root / 'AGENTS.md'
        p.write_bytes(b'New personal prefix\n' + p.read_bytes() + b'Personal suffix\n')
        f.install(self.root)
        f.install(self.root, uninstall=True)
        self.assertEqual(p.read_bytes(), b'New personal prefix\nPersonal suffix\n')

    def test_symlink_root_parent_and_file_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        target = self.root / 'project'
        target.mkdir()
        (target / '.agents').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            f.install(target)
        self.assertEqual(snapshot(outside), {})
        (target / '.agents').unlink()
        alias = self.root / 'alias'
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            f.install(alias)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            f.install(alias / 'nested-project')
        self.assertFalse((target / 'nested-project').exists())
        (target / 'AGENTS.md').symlink_to(outside / 'notes')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            f.install(target)
        self.assertFalse((outside / 'notes').exists())

    def test_manifest_traversal_and_corruption_rejected(self):
        f.install(self.root)
        p = self.root / f.MANIFEST
        valid = json.loads(p.read_bytes())
        for name in ('../../escape', '/tmp/escape', '.codex/../../escape', '.codex/config.toml'):
            corrupt = dict(valid, files={name: '0' * 64})
            p.write_text(json.dumps(corrupt))
            before = snapshot(self.root)
            with self.assertRaises(ValueError):
                f.install(self.root, uninstall=True)
            self.assertEqual(snapshot(self.root), before)

    def test_update_prunes_only_owned_removed_resource(self):
        f.install(self.root)
        p = self.root / '.agents/skills/sdlc-tdd/owner-notes.txt'
        p.write_text('personal extension')
        real = f.build
        def reduced():
            files = real()
            files.pop('.agents/skills/sdlc-tdd/references/framework/runtime.md')
            return files
        with patch.object(f, 'build', reduced):
            f.install(self.root)
        self.assertFalse((p.parent / 'references/framework/runtime.md').exists())
        self.assertEqual(p.read_text(), 'personal extension')

    def test_io_failure_rolls_back_files_and_manifest(self):
        f.install(self.root)
        before = snapshot(self.root)
        real_build, real_write = f.build, f.atomic_write
        def changed():
            files = real_build()
            for key in ('.codex/agents/api-backend.toml', '.codex/agents/code-quality.toml'):
                files[key] += b'# updated\n'
            return files
        called = 0
        def fail_once(path, data):
            nonlocal called
            called += 1
            if called == 2:
                raise OSError('simulated disk write error')
            return real_write(path, data)
        with patch.object(f, 'build', changed), patch.object(f, 'atomic_write', fail_once):
            with self.assertRaises(OSError):
                f.install(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_user_scope_and_optional_hooks(self):
        (self.root / 'AGENTS.md').write_bytes(b'project-like owner file')
        f.install(self.root, user=True, hooks=True)
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), b'project-like owner file')
        self.assertTrue((self.root / '.codex/AGENTS.md').is_file())
        config = json.loads((self.root / '.codex/hooks.json').read_bytes())
        self.assertNotIn('Notification', config['hooks'])
        self.assertEqual(config['hooks']['SessionEnd'][0]['hooks'][0]['timeout'], 3)
        self.assertEqual(f.install(self.root, user=True), [])
        f.install(self.root, user=True, uninstall=True)
        self.assertEqual(snapshot(self.root), {'AGENTS.md': b'project-like owner file'})

    def test_installed_hook_stdio_contract_and_private_logging(self):
        f.install(self.root, hooks=True)
        script = self.root / '.codex/framework/hook.py'
        event = {'hook_event_name': 'PreToolUse', 'tool_name': 'apply_patch', 'cwd': str(self.root),
                 'session_id': 'test-session', 'tool_input': {'command':
                 '*** Begin Patch\n*** Update File: .env\n+PRIVATE_TEST_MARKER\n*** End Patch'}}
        result = subprocess.run([sys.executable, str(script)], input=json.dumps(event),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertNotIn('PRIVATE_TEST_MARKER', (script.parent / 'events.jsonl').read_text())
        malformed = subprocess.run([sys.executable, str(script)], input='not-json',
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(malformed.returncode, 2)
        self.assertEqual(malformed.stdout, '')

    def test_packaged_resources_retain_executable_behavior(self):
        f.install(self.root)
        script = self.root / '.agents/skills/sdlc-deployment-runbook/scripts/health_check.py'
        result = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('reading-strategies',):
            self.assertTrue((self.root / f'.agents/skills/sdlc-deep-read/references/{name}.md').is_file())

    def test_exported_delivery_resources_execute_from_installed_bundles(self):
        f.install(self.root)
        skills = self.root / '.agents/skills'
        project, evidence = self.root / 'fixture', self.root / 'evidence'
        project.mkdir()
        evidence.mkdir()
        (project / 'go.mod').write_text('module example.invalid/fixture\n\ngo 1.22\n')
        (project / 'x_test.go').write_text('package fixture\n')
        context = subprocess.run([sys.executable, str(skills / 'sdlc-repo-context/scripts/repo_context.py'),
                                  '--cwd', str(project)], capture_output=True, text=True, timeout=60)
        self.assertEqual(context.returncode, 0, context.stderr)
        report = json.loads(context.stdout)
        self.assertEqual((report['source']['kind'], report['languages']), ('archive-or-unversioned', ['go']))
        self.assertTrue(all(c['executed'] is False for c in report['commandCandidates']))
        script = skills / 'sdlc-verified-handoff/scripts/evidence.py'
        command = [sys.executable, '-c', 'print("checked")']
        run = subprocess.run([sys.executable, str(script), 'run', '--cwd', str(project), '--out-dir',
                              str(evidence / 'smoke'), '--label', 'smoke', '--source-only', 'fixture tree',
                              '--', *command], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        manifest = evidence / 'manifest.json'
        manifest.write_text(json.dumps({'checks': [{'label': 'smoke', 'cwd': str(project), 'sourceOnly': 'fixture tree',
                                                    'command': {'executable': command[0], 'args': command[1:]},
                                                    'resultFile': 'smoke/result.json'}]}))
        verify = subprocess.run([sys.executable, str(script), 'verify', '--manifest', str(manifest)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        for name in ('delivery', 'repo-context', 'verified-handoff'):
            bundle = skills / f'sdlc-{name}'
            self.assertFalse((bundle / 'agents/openai.yaml').exists(), f'{name} must stay implicit')
            text = (bundle / 'SKILL.md').read_text()
            for resource in re.findall(r'\b((?:scripts|references)/[\w./-]+\.(?:py|md))\b', text):
                self.assertTrue((bundle / resource).is_file(), f'{name}: missing {resource}')

    def test_publication_contract_has_one_provider_neutral_source(self):
        # A Codex-only override diverged from the canonical command once; both editions
        # must export the same exact-result publication sequence.
        inv = f.source_inventory()
        _, body = f.frontmatter(ROOT / '.claude/commands/commit-pr.md')
        self.assertIn(f.adapt(body, inv), f.build()['.agents/skills/sdlc-commit-pr/SKILL.md'].decode())

    def test_generated_bundles_do_not_leak_claude_invocations_or_paths(self):
        inv = f.source_inventory()
        names = '|'.join(re.escape(n) for n in inv['skills'] + inv['commands'])
        slash = re.compile(rf'(?<![\w:/.$-])/(?:{names})\b')
        for path, data in f.build().items():
            if not path.endswith(('/SKILL.md', '.toml')):
                continue
            text = data.decode()
            with self.subTest(path=path):
                self.assertNotIn('$ARGUMENTS', text)
                self.assertNotIn('.claude/skills/', text)
                self.assertIsNone(slash.search(text))

    def test_generated_skill_invocations_resolve(self):
        import re
        files = f.build()
        known = {Path(p).parent.name for p in files if p.endswith('/SKILL.md')}
        inv = f.source_inventory()
        source_names = set(inv['skills'] + inv['commands'] + inv['agents'])
        for path, data in files.items():
            if not path.endswith(('/SKILL.md', '.toml')):
                continue
            for invocation in re.findall(r'\$([a-z][a-z0-9-]*)', data.decode()):
                # Shell variables, JSON Schema $ref and Prometheus labels are not skills.
                if invocation == 'sdlc-agent-' or (not invocation.startswith('sdlc-') and invocation not in source_names):
                    continue
                self.assertIn(invocation, known, f'{path}: unresolved skill ${invocation}')


class HookAcceptance(unittest.TestCase):
    def event(self, command):
        return {'hook_event_name': 'PreToolUse', 'tool_name': 'apply_patch', 'tool_input': {'command': command}}

    def decision(self, command):
        return hook.inspect_event(self.event(command)).get('hookSpecificOutput', {}).get('permissionDecision')

    def test_patch_sensitive_add_update_delete_move_and_multiple_files(self):
        for directive in ('Add File: .env', 'Update File: secrets/token.txt', 'Delete File: private.pem',
                          'Update File: safe.txt\n*** Move to: .env.production',
                          'Update File: safe.txt\n*** Update File: .aws/credentials',
                          'Update File: .codex/auth.json', 'Update File: Secrets/token.txt'):
            with self.subTest(directive=directive):
                self.assertEqual(self.decision('*** Begin Patch\n*** ' + directive + '\n*** End Patch'), 'deny')

    def test_ordinary_patch_is_allowed_and_malformed_is_denied(self):
        self.assertIsNone(self.decision('*** Begin Patch\n*** Update File: src/main.py\n@@\n-old\n+new\n*** End Patch'))
        self.assertEqual(self.decision('unrecognized patch'), 'deny')
        self.assertEqual(self.decision('*** Begin Patch\n*** End Patch'), 'deny')

    def test_symlink_destination_cannot_hide_sensitive_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / '.env').write_text('dummy')
            (root / 'innocent.txt').symlink_to(root / '.env')
            event = self.event('*** Begin Patch\n*** Update File: innocent.txt\n*** End Patch')
            event['cwd'] = str(root)
            self.assertEqual(hook.inspect_event(event)['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_logging_excludes_tool_arguments_and_unsupported_costs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(hook, 'STATE', Path(directory)):
            event = self.event('*** Begin Patch\n*** Update File: .env\n+PRIVATE_TEST_MARKER\n*** End Patch')
            event.update(session_id='session-test', turn_id='turn-test')
            hook.log_event(event, hook.inspect_event(event))
            data = (Path(directory) / 'events.jsonl').read_text()
            self.assertNotIn('PRIVATE_TEST_MARKER', data)
            self.assertNotIn('cost', data)
            self.assertTrue(json.loads(data)['blocked'])


if __name__ == '__main__':
    unittest.main()
