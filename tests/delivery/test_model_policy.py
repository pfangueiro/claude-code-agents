"""Executable tests for the opt-in model policy helper (delivery scripts/model_policy.py).

Disposable HOME and files only: no provider, network, account or real configuration is used,
and every CLI call runs from an unrelated working directory. Expected decisions come from a
hand-written table, not from the selector's code. Evaluation artifacts here are hand-written
agent-eval-result/v2 fixtures for parser and decision testing only; they say nothing about
agent efficacy (a real offline artifact is exercised in tests/codex/test_delivery_install.py).

Set MODEL_POLICY_SCRIPT to test a staged copy; by default the repository source is used.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get('MODEL_POLICY_SCRIPT')
              or REPO / '.claude/skills/delivery/scripts/model_policy.py')
EXAMPLE = REPO / '.claude/skills/delivery/references/model-policy.example.json'
EVAL_SCHEMA = 'verified-handoff/agent-eval-result/v2'
GIT_SHA = 'a' * 40
# Neutral identifiers: nothing here ranks models by name.
MODELS = {'route-a': 'vendor-model-a-2026-01', 'route-b': 'vendor-model-b-2026-01',
          'small': 'vendor-model-c-2026-01', 'next': 'vendor-model-a-2026-07',
          'old': 'vendor-model-z-2025-01', 'codex': 'vendor-model-d-2026-01'}
CLAUDE_KEYS = ('route-a', 'route-b', 'small', 'next', 'old')


def stamp(offset_seconds: float = 0) -> str:
    moment = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_seconds)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def claude_stream(model, *, served=None, usage=None, with_usage=True, terminal=True,
                  text='done') -> str:
    """Native Claude stream-json field shape with synthetic values. The init event names the
    configured model, each assistant message names the model that authored it, and the terminal
    result keys modelUsage by model. ``served`` lists the authoring model per assistant message
    (None omits the field, default one message by ``model``); ``usage`` lists the modelUsage
    keys (default the served models); ``with_usage=False`` omits modelUsage."""
    served = [model] if served is None else served
    events = [{'type': 'system', 'subtype': 'init', 'session_id': 'session-1', 'model': model}]
    for name in served:
        message = {'content': [{'type': 'text', 'text': text}]}
        if name is not None:
            message['model'] = name
        events.append({'type': 'assistant', 'message': message, 'session_id': 'session-1'})
    if terminal:
        result = {'type': 'result', 'subtype': 'success', 'is_error': False,
                  'session_id': 'session-1', 'permission_denials': [], 'result': text}
        if with_usage:
            keys = [name for name in served if name is not None] if usage is None else usage
            result['modelUsage'] = {name: {'inputTokens': 1, 'outputTokens': 1} for name in keys}
        events.append(result)
    return ''.join(json.dumps(event) + '\n' for event in events)


def load_module():
    """Import the helper for its pure API without writing bytecode beside it."""
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location('model_policy_under_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


class PolicyFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='model-policy-')).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        os.chmod(self.root, 0o700)
        self.home = self.private_dir(self.root / 'home')
        self.work = self.private_dir(self.root / 'work')
        self.cwd = self.private_dir(self.root / 'unrelated-cwd')
        self.env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.home),
                    'LC_ALL': 'C'}
        self.policy_file = self.home / '.config' / 'sdlc' / 'model-policy.json'

    # ---- files ------------------------------------------------------------------------

    @staticmethod
    def private_dir(path: Path) -> Path:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    def write_private(self, path: Path, data) -> Path:
        self.private_dir(path.parent)
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        if path.is_symlink() or path.exists():
            path.unlink()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
        os.chmod(path, 0o600)
        return path

    def write_policy(self, policy) -> Path:
        return self.write_private(self.policy_file, policy)

    def reset_policy_location(self):
        config = self.home / '.config'
        if config.is_symlink():
            config.unlink()
        elif config.exists():
            shutil.rmtree(config)

    def tree(self) -> dict:
        return {str(path): (path.lstat().st_mode,
                            path.read_bytes() if path.is_file() and not path.is_symlink() else None)
                for path in sorted(self.root.rglob('*'))}

    # ---- fixtures ---------------------------------------------------------------------

    def evaluation(self, name, model, *, outcome='PASS', rows=None, raw=None) -> dict:
        path = self.private_dir(self.work / 'evaluations' / name) / 'result.json'
        if raw is None:
            if rows is None:
                rows = [{'arm': arm, 'task': 'feature-clamp', 'outcome': 'PASS',
                         'observed_model': model} for arm in ('baseline', 'candidate')]
            raw = json.dumps({'schema': EVAL_SCHEMA, 'outcome': outcome, 'reasons': [],
                              'results': rows}).encode()
        path.write_bytes(raw)
        return {'path': str(path), 'sha256': sha256(raw), 'model': model}

    def binding(self, key, *, provider='claude', effort='high', status='approved',
                capabilities=('code',), evaluation=True) -> dict:
        model = MODELS[key]
        return {'provider': provider, 'model': model, 'effort': effort, 'pinned': True,
                'capabilities': list(capabilities), 'status': status,
                'evaluation': self.evaluation(key, model) if evaluation else None,
                'approval': {'by': 'owner', 'at': stamp(-3600)} if status == 'approved' else None}

    def standard_policy(self, **changes) -> dict:
        policy = {
            'version': 1, 'active': True, 'evidence_max_age_seconds': 3600,
            'bindings': {
                'route-a': self.binding('route-a', capabilities=('code', 'long-context')),
                'route-b': self.binding('route-b', effort=None),
                'small': self.binding('small', effort='low'),
                'next': self.binding('next', status='candidate'),
                'old': self.binding('old', status='revoked', evaluation=False),
                'codex': self.binding('codex', provider='codex', effort=None),
            },
            'routes': {'claude': {'routine': ['small'], 'complex': ['route-a', 'route-b'],
                                  'critical': ['route-a']},
                       'codex': {'complex': ['codex']}},
        }
        policy.update(changes)
        return policy

    def request(self, **changes) -> Path:
        data = {'version': 1, 'task_id': 'task-1', 'source': {'kind': 'git-sha', 'value': GIT_SHA},
                'declared_by': 'coordinator', 'provider': 'claude', 'role': 'implement',
                'risk': 'complex', 'surface': 'claude-cli', 'capabilities': ['code']}
        data.update(changes)
        return self.write_private(self.work / 'request.json', data)

    @staticmethod
    def support(overrides=None, keys=CLAUDE_KEYS) -> dict:
        models = {MODELS[key]: {'available': True, 'resolves_to': MODELS[key],
                                'efforts': ['low', 'high']} for key in keys}
        for key, entry in (overrides or {}).items():
            if entry is None:
                models.pop(MODELS[key])
            else:
                models[MODELS[key]].update(entry)
        return models

    def capabilities(self, models=None, **changes) -> Path:
        data = {'version': 1, 'provider': 'claude', 'surface': 'claude-cli',
                'observed_at': stamp(-60), 'observed_by': 'host-probe-fixture',
                'client_version': 'fixture-1.0', 'model_control': 'per-invocation',
                'effort_control': 'per-invocation',
                'models': self.support() if models is None else models}
        data.update(changes)
        return self.write_private(self.work / 'capabilities.json', data)

    # ---- CLI --------------------------------------------------------------------------

    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *map(str, args)],
                              cwd=self.cwd, env=self.env, capture_output=True, text=True,
                              timeout=120)
        self.assertNotIn('Traceback', proc.stderr)
        data = json.loads(proc.stdout) if proc.stdout.strip() else None
        return proc.returncode, data, proc.stdout

    def select(self, request=None, capabilities=None, *, with_capabilities=True):
        args = ['select', '--request', request or self.request()]
        if with_capabilities:
            args += ['--capabilities', capabilities or self.capabilities()]
        code, data, _ = self.run_cli(*args)
        return code, data

    def assertSelected(self, data, code, binding, *, fallback=False):
        self.assertEqual((code, data['decision']), (0, 'PLAN_READY'), data)
        self.assertEqual(data['selected']['binding'], binding)
        self.assertEqual(data['selected']['model'], MODELS[binding])
        self.assertEqual(data['selected']['fallback'], fallback)
        self.assertEqual('fallback-candidate' in data['reasons'], fallback)
        self.assertFalse(data['executed'])

    def assertIncomplete(self, data, code, reason):
        self.assertEqual((code, data['decision']), (3, 'INCOMPLETE'), data)
        self.assertIsNone(data['selected'])
        self.assertIn(reason, data['reasons'])

    @staticmethod
    def skipped(data) -> dict:
        return {item['binding']: item['reasons'] for item in data['considered'] if not item['eligible']}


class DecisionTable(PolicyFixture):
    def test_hand_written_decision_table(self):
        self.write_policy(self.standard_policy())
        unavailable = {'available': False}
        # (case, request changes, evidence changes, support overrides,
        #  expected binding or None for INCOMPLETE, expected fallback, expected skipped reasons)
        cases = [
            ('complex selects the first approved entry', {}, {}, {}, 'route-a', False, {}),
            ('routine uses the routine route', {'risk': 'routine'}, {}, {}, 'small', False, {}),
            ('critical uses the critical route', {'risk': 'critical'}, {}, {}, 'route-a', False, {}),
            ('unavailable first entry falls back within the class', {}, {},
             {'route-a': unavailable}, 'route-b', True, {'route-a': ['model-unavailable']}),
            ('complex never borrows the routine route', {}, {},
             {'route-a': unavailable, 'route-b': unavailable}, None, None,
             {'route-a': ['model-unavailable'], 'route-b': ['model-unavailable']}),
            ('unknown availability is not available', {}, {}, {'route-a': {'available': None}},
             'route-b', True, {'route-a': ['availability-unknown']}),
            ('a model absent from evidence is unknown', {}, {}, {'route-a': None}, 'route-b', True,
             {'route-a': ['model-support-unknown', 'effort-support-unknown']}),
            ('an alias resolving elsewhere is a mismatch', {}, {},
             {'route-a': {'resolves_to': 'vendor-model-a-latest'}}, 'route-b', True,
             {'route-a': ['model-alias-mismatch']}),
            ('unknown resolution', {}, {}, {'route-a': {'resolves_to': None}}, 'route-b', True,
             {'route-a': ['model-resolution-unknown']}),
            ('unsupported effort', {}, {}, {'route-a': {'efforts': ['low']}}, 'route-b', True,
             {'route-a': ['effort-unsupported']}),
            ('unknown effort support', {}, {}, {'route-a': {'efforts': None}}, 'route-b', True,
             {'route-a': ['effort-support-unknown']}),
            ('a surface without effort control leaves the inherit-effort binding', {},
             {'effort_control': 'unsupported'}, {}, 'route-b', True,
             {'route-a': ['effort-control-unsupported']}),
            ('routine has no inherit-effort fallback', {'risk': 'routine'},
             {'effort_control': 'unsupported'}, {}, None, None,
             {'small': ['effort-control-unsupported']}),
            ('required capability met by the first entry', {'capabilities': ['code', 'long-context']},
             {}, {}, 'route-a', False, {}),
            ('required capability blocks the fallback', {'capabilities': ['code', 'long-context']},
             {}, {'route-a': unavailable}, None, None,
             {'route-a': ['model-unavailable'], 'route-b': ['capability-missing']}),
        ]
        for name, request_changes, evidence_changes, overrides, binding, fallback, skipped in cases:
            with self.subTest(case=name):
                code, data = self.select(self.request(**request_changes),
                                         self.capabilities(self.support(overrides), **evidence_changes))
                self.assertEqual(self.skipped(data), skipped)
                if binding is None:
                    self.assertIncomplete(data, code, 'no-eligible-candidate')
                else:
                    self.assertSelected(data, code, binding, fallback=fallback)
                    self.assertEqual(data['selected']['evaluation_sha256'],
                                     sha256(Path(self.work / 'evaluations' / binding /
                                                 'result.json').read_bytes()))

    def test_surfaces_that_cannot_honour_a_selection_are_incomplete(self):
        self.write_policy(self.standard_policy())
        code, data = self.select(self.request(surface='claude-agent'),
                                 self.capabilities(surface='claude-agent', model_control='role-default'))
        self.assertIncomplete(data, code, 'surface-role-default')
        codex = self.support(keys=('codex',))
        code, data = self.select(self.request(provider='codex', surface='codex-fork'),
                                 self.capabilities(codex, provider='codex', surface='codex-fork',
                                                   model_control='inherit-only'))
        self.assertIncomplete(data, code, 'surface-inherit-only')
        code, data = self.select(self.request(provider='codex', surface='codex-spawn'),
                                 self.capabilities(codex, provider='codex', surface='codex-spawn'))
        self.assertSelected(data, code, 'codex')  # positive control on a supported surface
        code, data = self.select(self.request(), self.capabilities(surface='claude-agent'))
        self.assertIncomplete(data, code, 'evidence-surface-mismatch')
        code, data = self.select(self.request(surface='delivery-controller'), with_capabilities=False)
        self.assertIncomplete(data, code, 'controller-unsupported')

    def test_capability_evidence_must_be_fresh(self):
        self.write_policy(self.standard_policy())
        code, data = self.select(self.request(), self.capabilities(observed_at=stamp(-7200)))
        self.assertIncomplete(data, code, 'evidence-stale')
        code, data = self.select(self.request(), self.capabilities(observed_at=stamp(3600)))
        self.assertIncomplete(data, code, 'evidence-future')
        code, data = self.select(self.request(), self.capabilities(observed_at=stamp(60)))
        self.assertSelected(data, code, 'route-a')  # within the allowed clock skew
        code, data = self.select(self.request(), with_capabilities=False)
        self.assertIncomplete(data, code, 'capabilities-missing')

    def test_candidates_and_revoked_bindings_never_route_and_upgrade_needs_approval(self):
        policy = self.standard_policy()
        policy['routes']['claude']['complex'] = ['next', 'old', 'route-a']
        self.write_policy(policy)
        code, data = self.select()
        self.assertSelected(data, code, 'route-a', fallback=True)
        self.assertEqual(self.skipped(data), {'next': ['binding-candidate'], 'old': ['binding-revoked']})
        policy['routes']['claude']['complex'] = ['next']
        self.write_policy(policy)
        code, data = self.select()
        self.assertIncomplete(data, code, 'no-eligible-candidate')  # a passing evaluation is not approval
        code, report, _ = self.run_cli('status')
        self.assertEqual(code, 0)
        self.assertEqual(report['bindings']['next']['evaluation_check'], 'verified')
        self.assertFalse(report['bindings']['next']['approved_and_evaluated'])
        policy['bindings']['next'] = dict(policy['bindings']['next'], status='approved',
                                          approval={'by': 'owner', 'at': stamp(-10)})
        self.write_policy(policy)
        code, data = self.select()
        self.assertSelected(data, code, 'next')
        self.assertEqual(data['selected']['evaluation_sha256'],
                         policy['bindings']['next']['evaluation']['sha256'])

    def test_rollback_only_to_a_still_approved_binding_and_records_stay_unchanged(self):
        policy = self.standard_policy()
        policy['bindings']['next'] = dict(policy['bindings']['next'], status='approved',
                                          approval={'by': 'owner', 'at': stamp(-10)})
        policy['routes']['claude']['complex'] = ['next', 'route-a']
        self.write_policy(policy)
        code, upgraded, stdout = self.run_cli('select', '--request', self.request(),
                                              '--capabilities', self.capabilities())
        self.assertEqual((code, upgraded['selected']['binding']), (0, 'next'))
        retained = self.work / 'selection-next.json'
        retained.write_text(stdout)
        before = retained.read_bytes()
        policy['routes']['claude']['complex'] = ['route-a']
        self.write_policy(policy)
        code, rolled_back = self.select()
        self.assertSelected(rolled_back, code, 'route-a')
        self.assertNotEqual(rolled_back['policy']['sha256'], upgraded['policy']['sha256'])
        policy['bindings']['route-a'] = dict(policy['bindings']['route-a'], status='revoked')
        self.write_policy(policy)
        code, data = self.select()
        self.assertIncomplete(data, code, 'no-eligible-candidate')
        self.assertEqual(self.skipped(data), {'route-a': ['binding-revoked']})
        self.assertEqual(retained.read_bytes(), before)

    def test_evaluation_artifact_must_match_digest_outcome_and_observed_model(self):
        model = MODELS['route-a']

        def rows(observed, candidate='PASS'):
            return [{'arm': 'baseline', 'task': 't', 'outcome': 'PASS', 'observed_model': observed},
                    {'arm': 'candidate', 'task': 't', 'outcome': candidate, 'observed_model': observed}]

        changed = self.evaluation('changed', model)
        Path(changed['path']).write_bytes(Path(changed['path']).read_bytes() + b'\n')
        missing = self.evaluation('missing', model)
        Path(missing['path']).unlink()
        real = self.evaluation('real', model)
        linked = self.private_dir(self.work / 'evaluations' / 'linked') / 'result.json'
        linked.symlink_to(real['path'])
        v1 = json.dumps({'schema': 'verified-handoff/agent-eval-result/v1', 'outcome': 'PASS',
                         'results': rows(model)}).encode()
        cases = [
            ('evaluation-digest-mismatch', changed),
            ('evaluation-unavailable', missing),
            ('evaluation-unavailable', dict(real, path=str(linked))),
            ('evaluation-not-pass', self.evaluation('fail', model, outcome='FAIL')),
            ('evaluation-model-mismatch', self.evaluation('other', model, rows=rows('vendor-model-q'))),
            ('evaluation-model-unknown', self.evaluation('unknown', model, rows=rows(None))),
            ('evaluation-empty', self.evaluation('empty', model, rows=[])),
            ('evaluation-candidate-not-pass', self.evaluation('cand', model, rows=rows(model, 'FAIL'))),
            ('evaluation-unsupported-schema', self.evaluation('v1', model, raw=v1)),
            ('evaluation-malformed', self.evaluation('dup', model, raw=b'{"schema": 1, "schema": 2}')),
        ]
        self.write_policy(self.standard_policy())
        code, data = self.select()
        self.assertSelected(data, code, 'route-a')  # positive control with a qualifying artifact
        for reason, evaluation in cases:
            with self.subTest(reason=reason, path=evaluation['path']):
                policy = self.standard_policy()
                policy['bindings']['route-a']['evaluation'] = evaluation
                self.write_policy(policy)
                code, data = self.select()
                self.assertSelected(data, code, 'route-b', fallback=True)
                self.assertEqual(self.skipped(data), {'route-a': [reason]})


class InheritanceAndSafety(PolicyFixture):
    def test_missing_or_inactive_policy_inherits_without_a_claim(self):
        before = self.tree()
        code, data = self.select()
        self.assertEqual((code, data['decision'], data['reasons']), (0, 'INHERIT', ['policy-missing']))
        self.assertIsNone(data['selected'])
        self.assertIsNone(data['request'])
        self.assertIsNone(data['policy']['sha256'])
        self.assertFalse(data['executed'])
        bad = self.write_private(self.work / 'bad-request.json', b'{not json')
        code, data = self.select(bad)
        self.assertEqual((code, data['decision']), (0, 'INHERIT'))
        self.write_policy(self.standard_policy(active=False))
        code, data = self.select()
        self.assertEqual((code, data['decision'], data['reasons']), (0, 'INHERIT', ['policy-inactive']))
        self.assertRegex(data['policy']['sha256'], '^[0-9a-f]{64}$')
        code, report, _ = self.run_cli('status')
        self.assertEqual((code, report['policy']['state']), (0, 'inactive'))
        self.assertFalse((self.home / '.config/sdlc').exists() and
                         sorted(p.name for p in (self.home / '.config/sdlc').iterdir()) != ['model-policy.json'])
        proc = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--help'], cwd=self.cwd,
                              env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('INHERIT', proc.stdout)
        self.assertEqual({k: v for k, v in self.tree().items() if 'model-policy.json' not in k
                          and 'request.json' not in k and 'capabilities.json' not in k
                          and 'evaluations' not in k and str(self.home / '.config') not in k},
                         {k: v for k, v in before.items()})

    def test_no_command_accepts_a_policy_path(self):
        """Authority boundary: the parser itself refuses a policy path on every command, so a
        worker-written active policy can never be pointed at."""
        worker = self.write_private(self.work / 'worker-model-policy.json', self.standard_policy())
        request, capabilities = self.request(), self.capabilities()
        flag = f'--policy={worker}'
        commands = {
            'top level': [flag, 'status'],
            'status': ['status', flag],
            'select': ['select', '--request', request, '--capabilities', capabilities, flag],
            'verify': ['verify', '--selection', request, '--request', request, '--stream', request,
                       flag],
        }
        for name, argv in commands.items():
            with self.subTest(command=name):
                proc = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *map(str, argv)],
                                      cwd=self.cwd, env=self.env, capture_output=True, text=True,
                                      timeout=60)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertEqual(proc.stdout, '')
                self.assertIn('unrecognized arguments: --policy=', proc.stderr)
        # Positive control: the same request without the flag still sees no owner policy.
        code, data = self.select(request, capabilities)
        self.assertEqual((code, data['decision'], data['reasons']), (0, 'INHERIT', ['policy-missing']))
        self.assertIsNone(data['selected'])

    def test_shipped_example_is_a_valid_inactive_policy(self):
        self.write_policy(EXAMPLE.read_bytes())
        code, report, _ = self.run_cli('status')
        self.assertEqual((code, report['policy']['state']), (0, 'inactive'), report)
        self.assertEqual(report['bindings']['claude-a-next']['status'], 'candidate')
        code, data = self.select()
        self.assertEqual((code, data['decision'], data['reasons']), (0, 'INHERIT', ['policy-inactive']))

    def test_malformed_or_unsafe_present_policy_is_incomplete_never_inherited(self):
        good = self.standard_policy()
        text = json.dumps(good)

        def changed(**top):
            return dict(json.loads(text), **top)

        def binding_changed(key, **fields):
            policy = json.loads(text)
            policy['bindings'][key].update(fields)
            return policy

        def routes_changed(routes):
            return changed(routes=routes)

        evaluation = good['bindings']['route-a']['evaluation']
        contents = {
            'duplicate key': text.replace('"version": 1', '"version": 1, "version": 1', 1).encode(),
            'non-finite number': text.replace('"evidence_max_age_seconds": 3600',
                                              '"evidence_max_age_seconds": NaN', 1).encode(),
            'oversize': text.encode() + b' ' * (300 << 10),
            'not UTF-8': b'\xff\xfe' + text.encode(),
            'version true': changed(version=True),
            'unsupported version': changed(version=2),
            'boolean age': changed(evidence_max_age_seconds=True),
            'unknown key': changed(extra=1),
            'control character in model': binding_changed('route-a', model='vendor\u0007model'),
            'string pinned': binding_changed('route-a', pinned='true'),
            'approved without approval': binding_changed('route-a', approval=None),
            'candidate carrying approval': binding_changed('next', approval={'by': 'owner', 'at': stamp(-10)}),
            'evaluation model differs': binding_changed('route-a', evaluation=dict(evaluation,
                                                                                   model='vendor-model-q')),
            'route to an unknown binding': routes_changed({'claude': {'complex': ['missing']}}),
            'route across providers': routes_changed({'codex': {'complex': ['route-a']}}),
            'unknown risk class': routes_changed({'claude': {'trivial': ['small']}}),
        }
        self.write_policy(good)
        code, data = self.select()
        self.assertSelected(data, code, 'route-a')  # positive control
        for name, content in contents.items():
            with self.subTest(content=name):
                self.write_policy(content)
                self.assert_policy_invalid()

        def mode_0644():
            os.chmod(self.write_policy(good), 0o644)

        def symlinked_file():
            real = self.write_private(self.work / 'real-policy.json', good)
            self.private_dir(self.policy_file.parent)
            self.policy_file.symlink_to(real)

        def symlinked_ancestor():
            elsewhere = self.root / 'elsewhere' / '.config'
            self.write_private(elsewhere / 'sdlc' / 'model-policy.json', good)
            (self.home / '.config').symlink_to(elsewhere, target_is_directory=True)

        def fifo():
            self.private_dir(self.policy_file.parent)
            os.mkfifo(self.policy_file, 0o600)

        def directory():
            self.private_dir(self.policy_file)

        for setup in (mode_0644, symlinked_file, symlinked_ancestor, fifo, directory):
            with self.subTest(filesystem=setup.__name__):
                self.reset_policy_location()
                shutil.rmtree(self.root / 'elsewhere', ignore_errors=True)
                setup()
                self.assert_policy_invalid()

    def assert_policy_invalid(self):
        code, data = self.select()
        self.assertIncomplete(data, code, 'policy-invalid')
        self.assertEqual(data['policy']['state'], 'invalid')
        code, report, _ = self.run_cli('status')
        self.assertEqual((code, report['policy']['state'], report['bindings']), (3, 'invalid', None))

    def test_invalid_coordinator_and_host_inputs_are_incomplete(self):
        self.write_policy(self.standard_policy())
        requests = {'version true': {'version': True}, 'surface of another provider': {'surface': 'codex-cli'},
                    'unknown risk': {'risk': 'trivial'}, 'unknown key': {'extra': 1},
                    'uppercase capability': {'capabilities': ['Code']},
                    'bad source digest': {'source': {'kind': 'sha256', 'value': GIT_SHA}}}
        for name, changes in requests.items():
            with self.subTest(request=name):
                code, data = self.select(self.request(**changes))
                self.assertIncomplete(data, code, 'request-invalid')
        loose = self.request()
        os.chmod(loose, 0o644)
        code, data = self.select(loose)
        self.assertIncomplete(data, code, 'request-invalid')
        loose = self.capabilities()
        os.chmod(loose, 0o644)
        code, data = self.select(self.request(), loose)
        self.assertIncomplete(data, code, 'capabilities-invalid')
        model = MODELS['route-a']
        evidence = {'integer availability': self.support({'route-a': {'available': 1}}),
                    'unknown control': None, 'duplicate key': None}
        for name, models in evidence.items():
            with self.subTest(capabilities=name):
                if name == 'unknown control':
                    path = self.capabilities(model_control='auto')
                elif name == 'duplicate key':
                    raw = json.dumps({'version': 1}).replace('"version": 1', '"version": 1, "version": 1')
                    path = self.write_private(self.work / 'capabilities.json', raw.encode())
                else:
                    path = self.capabilities(models)
                code, data = self.select(self.request(), path)
                self.assertIncomplete(data, code, 'capabilities-invalid')
        self.assertTrue(model)


class PureDecision(unittest.TestCase):
    def test_age_boundary_is_owner_data_and_evaluation_reasons_block(self):
        module = load_module()
        observed = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        binding = {'provider': 'claude', 'model': 'vendor-model-x', 'effort': None, 'pinned': False,
                   'capabilities': ['code'], 'status': 'approved',
                   'evaluation': {'path': '/unused/result.json', 'sha256': '0' * 64,
                                  'model': 'vendor-model-x'},
                   'approval': {'by': 'owner', 'at': '2025-12-01T00:00:00Z'}}
        policy = {'version': 1, 'active': True, 'evidence_max_age_seconds': 600,
                  'bindings': {'x': binding}, 'routes': {'claude': {'complex': ['x']}}}
        request = {'version': 1, 'task_id': 't', 'source': {'kind': 'git-sha', 'value': GIT_SHA},
                   'declared_by': 'coordinator', 'provider': 'claude', 'role': 'review',
                   'risk': 'complex', 'surface': 'claude-cli', 'capabilities': ['code']}
        evidence = {'version': 1, 'provider': 'claude', 'surface': 'claude-cli',
                    'observed_at': '2026-01-01T00:00:00.000000Z', 'observed_by': 'probe',
                    'client_version': None, 'model_control': 'per-invocation',
                    'effort_control': 'unsupported',
                    'models': {'vendor-model-x': {'available': True, 'resolves_to': 'vendor-model-x',
                                                  'efforts': None}}}
        at_limit = module.decide(policy, request, evidence, observed + dt.timedelta(seconds=600), {'x': None})
        self.assertEqual((at_limit['decision'], at_limit['selected']['binding']), ('PLAN_READY', 'x'))
        self.assertFalse(at_limit['selected']['version_pinned'])
        over = module.decide(policy, request, evidence, observed + dt.timedelta(seconds=601), {'x': None})
        self.assertEqual((over['decision'], over['reasons']), ('INCOMPLETE', ['evidence-stale']))
        unchecked = module.decide(policy, request, evidence, observed, {})
        self.assertEqual(unchecked['considered'][0]['reasons'], ['evaluation-unchecked'])
        failed = module.decide(policy, request, evidence, observed, {'x': 'evaluation-not-pass'})
        self.assertEqual((failed['decision'], failed['considered'][0]['reasons']),
                         ('INCOMPLETE', ['evaluation-not-pass']))


class RunVerification(PolicyFixture):
    def plan(self, policy=None, request=None, capabilities=None):
        self.write_policy(policy or self.standard_policy())
        request = request or self.request()
        capabilities = capabilities or self.capabilities()
        code, data, stdout = self.run_cli('select', '--request', request, '--capabilities', capabilities)
        selection = self.work / 'selection.json'
        selection.write_text(stdout)
        return code, data, selection, request, capabilities

    def observation(self, selection, **changes) -> Path:
        data = {'version': 1, 'selection_sha256': sha256(selection.read_bytes()), 'provider': 'claude',
                'surface': 'claude-cli', 'observed_by': 'host-harness-fixture',
                'observed_model': MODELS['route-a'], 'observed_effort': 'high', 'terminal': 'success'}
        data.update(changes)
        path = self.work / 'observation.json'
        path.write_text(json.dumps(data))
        return path

    def stream(self, text) -> Path:
        path = self.work / 'events.jsonl'
        path.write_text(text)
        return path

    def verify(self, selection, request, capabilities, *, observation=None, stream=None):
        args = ['verify', '--selection', selection, '--request', request, '--capabilities', capabilities]
        args += ['--observation', observation] if observation is not None else ['--stream', stream]
        code, data, _ = self.run_cli(*args)
        return code, data

    def test_matching_host_observation_passes_and_keeps_requested_and_observed_apart(self):
        _, planned, selection, request, capabilities = self.plan()
        self.assertEqual(planned['decision'], 'PLAN_READY')
        observation = self.observation(selection)
        # A host observation is a caller-trusted retained artifact, not a private input: unlike
        # the request and capability evidence it carries no mode requirement.
        os.chmod(observation, 0o644)
        before = self.tree()
        code, data = self.verify(selection, request, capabilities, observation=observation)
        self.assertEqual((code, data['outcome'], data['reasons']), (0, 'PASS', []), data)
        self.assertEqual(data['requested'], {'model': MODELS['route-a'], 'effort': 'high'})
        self.assertEqual((data['observed']['source'], data['observed']['model']),
                         ('host-observation', MODELS['route-a']))
        self.assertEqual((data['binding'], data['fallback_used']), ('route-a', False))
        self.assertEqual(self.tree(), before)  # verify writes nothing

    def test_mismatched_unknown_unbound_and_unfinished_runs(self):
        _, _, selection, request, capabilities = self.plan()
        cases = [('observed-model-mismatch', {'observed_model': MODELS['route-b']}, 1, 'FAIL'),
                 ('observed-effort-mismatch', {'observed_effort': 'low'}, 1, 'FAIL'),
                 ('observed-model-unknown', {'observed_model': None}, 3, 'INCOMPLETE'),
                 ('observed-effort-unknown', {'observed_effort': None}, 3, 'INCOMPLETE'),
                 ('terminal-not-success', {'terminal': 'failed'}, 3, 'INCOMPLETE'),
                 ('observation-not-bound', {'selection_sha256': '0' * 64}, 3, 'INCOMPLETE'),
                 ('observation-surface-mismatch', {'surface': 'claude-agent'}, 3, 'INCOMPLETE')]
        for reason, changes, exit_code, outcome in cases:
            with self.subTest(reason=reason):
                code, data = self.verify(selection, request, capabilities,
                                         observation=self.observation(selection, **changes))
                self.assertEqual((code, data['outcome']), (exit_code, outcome), data)
                self.assertIn(reason, data['reasons'])

    def test_native_claude_stream_is_parsed_and_prose_is_not_evidence(self):
        _, _, selection, request, capabilities = self.plan()
        code, data = self.verify(selection, request, capabilities,
                                 stream=self.stream(claude_stream(MODELS['route-a'])))
        self.assertEqual((code, data['outcome'], data['reasons']), (3, 'INCOMPLETE', ['observed-effort-unknown']))
        self.assertEqual((data['observed']['source'], data['observed']['model'], data['observed']['terminal']),
                         ('native-stream', MODELS['route-a'], 'success'))
        self.assertEqual((data['observed']['configured_model'], data['observed']['executed_models'],
                          data['observed']['usage_models'], data['observed']['effort']),
                         (MODELS['route-a'], [MODELS['route-a']], [MODELS['route-a']], None))
        claim = claude_stream('vendor-model-q-2026', text=f'I ran as {MODELS["route-a"]} as requested.')
        code, data = self.verify(selection, request, capabilities, stream=self.stream(claim))
        self.assertEqual((code, data['outcome']), (1, 'FAIL'))
        self.assertIn('observed-model-mismatch', data['reasons'])
        code, data = self.verify(selection, request, capabilities,
                                 stream=self.stream(claude_stream(MODELS['route-a'], terminal=False)))
        self.assertIn('terminal-not-success', data['reasons'])
        self.assertEqual(code, 3)
        fallback_capabilities = self.capabilities(self.support({'route-a': {'available': False}}))
        _, planned, selection, request, capabilities = self.plan(capabilities=fallback_capabilities)
        self.assertEqual(planned['selected']['binding'], 'route-b')
        code, data = self.verify(selection, request, capabilities,
                                 stream=self.stream(claude_stream(MODELS['route-b'])))
        self.assertEqual((code, data['outcome'], data['fallback_used']), (0, 'PASS', True), data)

    def test_native_stream_identity_is_the_served_model_not_the_configured_one(self):
        unavailable = self.capabilities(self.support({'route-a': {'available': False}}))
        _, planned, selection, request, capabilities = self.plan(capabilities=unavailable)
        # route-b requests no effort, so every reason below is about model identity alone.
        self.assertEqual((planned['selected']['binding'], planned['selected']['effort']), ('route-b', None))
        wanted, other, third = MODELS['route-b'], MODELS['route-a'], MODELS['small']
        # (case, stream, exit, outcome, exact reasons, observed model, configured, executed, usage)
        cases = [
            ('served and accounted as requested', claude_stream(wanted),
             0, 'PASS', [], wanted, wanted, [wanted], [wanted]),
            ('served as requested without modelUsage', claude_stream(wanted, with_usage=False),
             0, 'PASS', [], wanted, wanted, [wanted], None),
            ('configured as requested but served by a fallback', claude_stream(wanted, served=[other]),
             1, 'FAIL', ['observed-model-mismatch', 'configured-model-differs'],
             other, wanted, [other], [other]),
            ('served by the requested model and another', claude_stream(wanted, served=[wanted, other]),
             1, 'FAIL', ['observed-model-mixed', 'configured-model-differs'],
             None, wanted, sorted([wanted, other]), sorted([wanted, other])),
            ('bare init and success', claude_stream(wanted, served=[], with_usage=False),
             3, 'INCOMPLETE', ['observed-model-unknown'], None, wanted, [], None),
            ('modelUsage without any assistant message', claude_stream(wanted, served=[], usage=[wanted]),
             3, 'INCOMPLETE', ['observed-model-unknown'], None, wanted, [], [wanted]),
            ('assistant message without a model field', claude_stream(wanted, served=[None], usage=[wanted]),
             3, 'INCOMPLETE', ['observed-model-unrecognized', 'observed-model-unknown'],
             None, wanted, [], [wanted]),
            ('assistant model that is not an identifier',
             claude_stream(wanted, served=['vendor model b'], usage=[wanted]),
             3, 'INCOMPLETE', ['observed-model-unrecognized', 'observed-model-unknown'],
             None, wanted, [], [wanted]),
            ('requested model beside an unrecognized one',
             claude_stream(wanted, served=[wanted, '<placeholder>'], usage=[wanted]),
             3, 'INCOMPLETE', ['observed-model-unrecognized', 'observed-model-unknown'],
             None, wanted, [wanted], [wanted]),
            ('modelUsage lists an additional model', claude_stream(wanted, usage=[wanted, third]),
             3, 'INCOMPLETE', ['observed-model-usage-differs'], wanted, wanted, [wanted],
             sorted([wanted, third])),
            ('modelUsage names only another model', claude_stream(wanted, usage=[other]),
             3, 'INCOMPLETE', ['observed-model-usage-differs'], wanted, wanted, [wanted], [other]),
            ('configured differently but served as requested', claude_stream(other, served=[wanted]),
             3, 'INCOMPLETE', ['configured-model-differs'], wanted, other, [wanted], [wanted]),
        ]
        for name, text, exit_code, outcome, reasons, model, configured, executed, usage in cases:
            with self.subTest(case=name):
                code, data = self.verify(selection, request, capabilities, stream=self.stream(text))
                self.assertEqual((code, data['outcome'], data['reasons']), (exit_code, outcome, reasons), data)
                observed = data['observed']
                self.assertEqual((observed['model'], observed['configured_model'],
                                  observed['executed_models'], observed['usage_models']),
                                 (model, configured, executed, usage))
                self.assertEqual((observed['terminal'], observed['effort']), ('success', None))

    def test_ambiguous_or_malformed_native_stream_carries_no_identity(self):
        unavailable = self.capabilities(self.support({'route-a': {'available': False}}))
        _, planned, selection, request, capabilities = self.plan(capabilities=unavailable)
        self.assertEqual((planned['selected']['binding'], planned['selected']['effort']), ('route-b', None))
        wanted, other = MODELS['route-b'], MODELS['route-a']
        clean = claude_stream(wanted)
        init, assistant, result = clean.splitlines()

        def rebuilt(*lines) -> str:
            return ''.join(line + '\n' for line in lines)

        def swap(line, old, new) -> str:
            self.assertEqual(line.count(old), 1, line)
            return line.replace(old, new)

        # Control: the untouched single-model stream is the only one that passes.
        code, data = self.verify(selection, request, capabilities, stream=self.stream(clean))
        self.assertEqual((code, data['outcome'], data['reasons']), (0, 'PASS', []), data)
        self.assertEqual(data['observed']['model'], wanted)

        model_key = f'"model": {json.dumps(wanted)}'
        other_key = f'"model": {json.dumps(other)}'
        usage_entry = f'{json.dumps(wanted)}: {{"inputTokens": 1, "outputTokens": 1}}'
        other_usage = f'"modelUsage": {{{json.dumps(other)}: {{"inputTokens": 1, "outputTokens": 1}}}}'
        # A repeated key is ambiguous even when the last value agrees with the selected binding.
        repeated = [
            ('assistant model repeated, another then the requested one',
             rebuilt(init, swap(assistant, model_key, f'{other_key}, {model_key}'), result)),
            ('assistant model repeated, the requested one then another',
             rebuilt(init, swap(assistant, model_key, f'{model_key}, {other_key}'), result)),
            ('assistant model repeated with the same requested value',
             rebuilt(init, swap(assistant, model_key, f'{model_key}, {model_key}'), result)),
            ('terminal modelUsage model key repeated',
             rebuilt(init, assistant, swap(result, usage_entry, f'{usage_entry}, {usage_entry}'))),
            ('terminal modelUsage repeated, another model then the requested one',
             rebuilt(init, assistant, swap(result, '"modelUsage": ', f'{other_usage}, "modelUsage": '))),
        ]
        for name, text in repeated:
            with self.subTest(case=name):
                code, data = self.verify(selection, request, capabilities, stream=self.stream(text))
                self.assertEqual((code, data['outcome'], data['reasons']),
                                 (3, 'INCOMPLETE', ['stream-identity-malformed', 'observed-model-unknown']), data)
                observed = data['observed']
                self.assertEqual((observed['model'], observed['configured_model'],
                                  observed['executed_models'], observed['usage_models']),
                                 (None, None, [], None))

        # The lifecycle parser may add its own reasons here; the identity reason always leads.
        malformed = [
            ('line that is not JSON', rebuilt(init, assistant, '{not json', result)),
            ('line that is not an object', rebuilt(init, assistant, '[]', result)),
            ('overflowing number', rebuilt(init, assistant, swap(result, '"inputTokens": 1,', '"inputTokens": 1e999,'))),
            ('non-standard constant', rebuilt(init, assistant, swap(result, '"inputTokens": 1,', '"inputTokens": NaN,'))),
        ]
        for name, text in malformed:
            with self.subTest(case=name):
                code, data = self.verify(selection, request, capabilities, stream=self.stream(text))
                self.assertEqual((code, data['outcome']), (3, 'INCOMPLETE'), data)
                self.assertEqual(data['reasons'][0], 'stream-identity-malformed', data)
                self.assertIn('observed-model-unknown', data['reasons'])
                observed = data['observed']
                self.assertEqual((observed['model'], observed['configured_model'],
                                  observed['executed_models'], observed['usage_models']),
                                 (None, None, [], None))

    def test_codex_stream_without_model_identity_is_incomplete(self):
        codex = self.support(keys=('codex',))
        request = self.request(provider='codex', surface='codex-cli')
        capabilities = self.capabilities(codex, provider='codex', surface='codex-cli')
        _, planned, selection, request, capabilities = self.plan(request=request, capabilities=capabilities)
        self.assertEqual(planned['selected']['binding'], 'codex')
        events = [{'type': 'thread.started', 'thread_id': 'thread-1'}, {'type': 'turn.completed'}]
        stream = self.stream(''.join(json.dumps(event) + '\n' for event in events))
        code, data = self.verify(selection, request, capabilities, stream=stream)
        self.assertEqual((code, data['outcome'], data['reasons']), (3, 'INCOMPLETE', ['observed-model-unknown']))
        self.assertEqual((data['observed']['model'], data['observed']['terminal']), (None, 'success'))

    def test_input_drift_evaluation_drift_and_inconsistent_records(self):
        policy = self.standard_policy()
        _, _, selection, request, capabilities = self.plan(policy=policy)
        observation = self.observation(selection)
        originals = {path: path.read_bytes() for path in (request, capabilities, self.policy_file)}
        drifts = [('request-drift', lambda: self.request(risk='critical')),
                  ('capabilities-drift', lambda: self.capabilities(observed_at=stamp(-30))),
                  ('policy-drift', lambda: self.write_policy(dict(policy, evidence_max_age_seconds=3599)))]
        for reason, mutate in drifts:
            with self.subTest(reason=reason):
                mutate()
                code, data = self.verify(selection, request, capabilities, observation=observation)
                self.assertEqual((code, data['outcome'], data['reasons']), (3, 'INCOMPLETE', [reason]))
                for path, raw in originals.items():
                    self.write_private(path, raw)
        code, data = self.verify(selection, request, capabilities, observation=observation)
        self.assertEqual(data['outcome'], 'PASS')  # restored inputs reproduce the record
        artifact = Path(policy['bindings']['route-a']['evaluation']['path'])
        artifact.write_bytes(artifact.read_bytes() + b'\n')
        code, data = self.verify(selection, request, capabilities, observation=observation)
        self.assertEqual((code, data['reasons']), (3, ['evaluation-drift']))
        self.evaluation('route-a', MODELS['route-a'])
        forged = json.loads(selection.read_text())
        forged['selected'] = dict(forged['selected'], binding='route-b', model=MODELS['route-b'], effort=None,
                                  route_index=1, fallback=True)
        forged_path = self.work / 'forged-selection.json'
        forged_path.write_text(json.dumps(forged))
        code, data = self.verify(forged_path, request, capabilities,
                                 observation=self.observation(forged_path, observed_model=MODELS['route-b'],
                                                              observed_effort=None))
        self.assertEqual((code, data['outcome'], data['reasons']), (1, 'FAIL', ['selection-record-mismatch']))

    def test_restored_earlier_evaluation_is_drift_not_a_forged_record(self):
        """A fallback chosen while an earlier binding's pinned evaluation file was missing must
        not become a FAIL record mismatch once the identical bytes are back: the earlier
        evaluation state is unreproducible history, so the run is INCOMPLETE, never PASS."""
        policy = self.standard_policy()
        artifact = Path(policy['bindings']['route-a']['evaluation']['path'])
        pinned = artifact.read_bytes()
        artifact.unlink()
        code, planned, selection, request, capabilities = self.plan(policy=policy)
        self.assertSelected(planned, code, 'route-b', fallback=True)
        self.assertEqual(self.skipped(planned), {'route-a': ['evaluation-unavailable']})
        observation = self.observation(selection, observed_model=MODELS['route-b'],
                                       observed_effort=None)
        code, data = self.verify(selection, request, capabilities, observation=observation)
        self.assertEqual((code, data['outcome'], data['reasons']), (0, 'PASS', []), data)
        self.assertEqual((data['binding'], data['fallback_used']), ('route-b', True))

        artifact.write_bytes(pinned)  # the exact pinned bytes; no other file changes
        self.assertEqual(sha256(artifact.read_bytes()),
                         policy['bindings']['route-a']['evaluation']['sha256'])
        before = self.tree()
        code, data = self.verify(selection, request, capabilities, observation=observation)
        self.assertEqual((code, data['outcome'], data['reasons']),
                         (3, 'INCOMPLETE', ['evaluation-drift']), data)
        self.assertIsNone(data['observed'])
        self.assertIsNone(data['requested'])
        self.assertEqual(self.tree(), before)  # the record and the artifact stay as they were

        # Control: with the route's evaluation facts unchanged since the record was written,
        # a selected binding the inputs do not produce is still a known mismatch.
        code, honest = self.select(request, capabilities)
        self.assertSelected(honest, code, 'route-a')
        forged = dict(honest, selected=dict(honest['selected'], binding='route-b',
                                            model=MODELS['route-b'], effort=None,
                                            route_index=1, fallback=True))
        forged_path = self.work / 'forged-selection.json'
        forged_path.write_text(json.dumps(forged))
        code, data = self.verify(forged_path, request, capabilities,
                                 observation=self.observation(forged_path,
                                                              observed_model=MODELS['route-b'],
                                                              observed_effort=None))
        self.assertEqual((code, data['outcome'], data['reasons']),
                         (1, 'FAIL', ['selection-record-mismatch']), data)

    def test_a_retained_selection_must_equal_its_recomputation(self):
        """Record integrity, not authentication: with every recorded input digest and the
        selected binding left intact, a retained record that misattributes the task, risk,
        source, policy or capability evidence must not verify, even when the host observation
        is bound to the altered record's own digest."""
        _, planned, selection, request, capabilities = self.plan()
        self.assertEqual((planned['request']['risk'], planned['request']['source']['value']),
                         ('complex', GIT_SHA))

        def clean_control():
            code, data = self.verify(selection, request, capabilities,
                                     observation=self.observation(selection))
            self.assertEqual((code, data['outcome'], data['reasons']), (0, 'PASS', []), data)

        def risk_and_source(record):
            record['request']['risk'] = 'critical'
            record['request']['source']['value'] = 'b' * 40

        clean_control()
        mismatch = (1, 'FAIL', 'selection-record-mismatch')
        invalid = (3, 'INCOMPLETE', 'selection-invalid')
        # (case, change to the retained record, (exit, outcome, reason), field named in detail)
        cases = [
            ('task risk and source', risk_and_source, mismatch, 'request'),
            ('task id', lambda r: r['request'].update(task_id='task-2'), mismatch, 'request'),
            ('policy state', lambda r: r['policy'].update(state='inactive'), mismatch, 'policy'),
            ('policy location', lambda r: r['policy'].update(location='/tmp/model-policy.json'),
             mismatch, 'policy'),
            ('capability model control', lambda r: r['capabilities'].update(model_control='role-default'),
             mismatch, 'capabilities'),
            ('capability observer', lambda r: r['capabilities'].update(observed_by='another probe'),
             mismatch, 'capabilities'),
            ('reasons', lambda r: r.update(reasons=['fallback-candidate']), mismatch, 'reasons'),
            ('executed', lambda r: r.update(executed=True), mismatch, 'executed'),
            ('boolean written as an integer', lambda r: r['selected'].update(fallback=0), mismatch, None),
            ('considered reasons', lambda r: r['considered'][0].update(reasons=['model-unavailable']),
             (3, 'INCOMPLETE', 'selection-considered-not-reproducible'), None),
            ('unknown key', lambda r: r.update(note='reviewed'), invalid, None),
            ('missing key', lambda r: r.pop('executed'), invalid, None),
            # A changed recorded digest is input drift, exactly as a changed input file is.
            ('recorded request digest', lambda r: r['request'].update(sha256='0' * 64),
             (3, 'INCOMPLETE', 'request-drift'), None),
        ]
        for name, change, (exit_code, outcome, reason), field in cases:
            with self.subTest(case=name):
                record = json.loads(selection.read_text())
                change(record)
                altered = self.work / 'altered-selection.json'
                altered.write_text(json.dumps(record))
                code, data = self.verify(altered, request, capabilities,
                                         observation=self.observation(altered))
                self.assertEqual((code, data['outcome'], data['reasons']), (exit_code, outcome, [reason]), data)
                self.assertIsNone(data['observed'])
                self.assertIsNone(data['requested'])
                if field is not None:
                    self.assertEqual(data['detail'],
                                     f'retained selection differs from its recomputation in: {field}')
        clean_control()  # the inputs and the original record were never touched

    def test_an_inherited_run_is_never_verified_as_selected(self):
        code, data, stdout = self.run_cli('select', '--request', self.request(),
                                          '--capabilities', self.capabilities())
        self.assertEqual(data['decision'], 'INHERIT')
        selection = self.work / 'inherit-selection.json'
        selection.write_text(stdout)
        code, data = self.verify(selection, self.request(), self.capabilities(),
                                 observation=self.observation(selection))
        self.assertEqual((code, data['outcome'], data['reasons']), (3, 'INCOMPLETE', ['selection-not-plan-ready']))
        self.assertIsNone(data['requested'])


if __name__ == '__main__':
    unittest.main()
