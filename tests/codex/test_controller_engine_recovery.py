"""Black-box recovery regressions for the persistent controller engine.

Same rules as test_controller_engine.py, whose ControllerHarness this module reuses: only the
operator CLI and read-only Ledger / controller_effects / controller_process views are
exercised, against a copied runtime, disposable Git repositories and synthetic native
executables. Nothing is skipped and no assertion is a quality claim.

Regressions (each must fail on the engine behaviour named, never on a missing import):
  A. an unresolved task.commit effect whose journalled evidence root (spec.evidence_root, a
     random token under <state>/effects) is lost, or survives with every call directory gone,
     stays unresolved on `recover`: nothing recreated, no Git read of its worktree, no
     replayed mutation, never `failed`, and its implement attempt stays open (no retry);
  B. a durable STOP issued while the engine is inside a synchronous effect is observed
     there: the running command is ended by the helper's STOP (not its timeout) and the run
     ends without another main-loop turn;
  C. a no-change investigation task is accepted on its own execution base, recorded as a
     confirmed no-op integration (done effect, checkpoint contribution) and gated again as
     the derived candidate, with no fabricated commit or merge;
  D. readmission is held while owned workspaces remain (default `recover` deletes none);
     after the explicit `cleanup-workspaces` the preserved result is re-bound on its own
     base and re-gated (fresh check and review) without being implemented again;
  E. an outcome harvested late keeps the evidence time of its validated lifecycle end, so
     it cannot override an operator refresh requested after that end.

Fixture-only Git front end: the operator PATH entry `git` is a logging wrapper that replaces
itself with the real git. With <githome>/control/hold-<verb> present, the first `git <verb>`
publishes its own pid + OS start identity and waits instead. A held invocation ends only by
its own marker-validated self-termination (crash-<token> / terminate-all, as in
fake_native_cli), by the signal its owning process group receives, or by expiring without
running git. It changes no environment, credential or Git configuration.

Teardown never kills by argv, name or bare pid and does not expect `recover` to resolve held
effects or remove workspaces: only live processes must be proven settled (fixture markers by
pid + start identity, retained attempt bootstrap identities, the command bootstraps under
every journalled effect evidence root and unfinalized controller queries). Anything unproven
keeps the temp root as evidence and FAILS the test.
"""
import contextlib
import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import test_controller_engine as harness
finally:
    sys.path.pop(0)

PASS_TIMEOUT = harness.PASS_TIMEOUT
DONE = harness.DONE
STOP_BOUND_SECONDS = 60
HOLD_SECONDS = 600
TEE = 'def value():\n    return 7\n'
ARE = 'def value():\n    return 9\n'
SEED = 'def value():\n    return 4\n'
AYE = 'def value():\n    return 11\n'
BEE = 'def value():\n    return 12\n'
ROOT_KEY = 'evidence_root'  # controller_engine journals the per-effect root under this name
ROOT_TOKEN = re.compile(r'r[0-9a-f]{32}')
CALL_DIR = r'\d{{8}}T\d{{6}}Z-(?:observe|execute)-{kind}-\d+-[0-9a-f]{{16}}'
COMMIT_VERBS = ('add', 'commit', 'commit-tree')
SETTLED_COMMAND_STATES = ('prepared', 'not-launched', 'exited', 'lost', 'finalized')

GIT_WRAPPER = '''#!{python} -I
"""Fixture-only git front end (see test_controller_engine_recovery). Never signals another
process and never runs git for an invocation it held."""
import json, os, sys, threading, time
sys.dont_write_bytecode = True
sys.path.insert(0, {fixtures!r})
import fake_native_cli as fixture

HOME, REAL, HOLD_SECONDS = {home!r}, {real!r}, {hold_seconds!r}


def parse(args):
    bound, verb, index = None, None, 0
    while index < len(args):
        arg = args[index]
        if arg in ('-C', '-c') and index + 1 < len(args):
            bound = args[index + 1] if arg == '-C' else bound
            index += 2
            continue
        if not arg.startswith('-'):
            verb = arg
            break
        index += 1
    return verb, os.path.realpath(bound or os.getcwd())


def hold(verb, record):
    try:
        os.close(os.open(os.path.join(HOME, 'log', 'held-' + verb), os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        return
    marker, live = fixture._register(HOME)
    threading.Thread(target=fixture._watch, args=(HOME, marker['token']), daemon=True).start()
    ready = os.path.join(HOME, 'log', 'ready-' + verb + '.json')
    with open(ready + '.tmp', 'w', encoding='utf-8') as handle:
        json.dump(dict(record, **marker), handle)
    os.replace(ready + '.tmp', ready)
    time.sleep(HOLD_SECONDS)
    fixture._log(HOME, {{'event': 'hold_expired', 'verb': verb}})
    os.unlink(live)
    sys.exit(75)


args = sys.argv[1:]
verb, bound = parse(args)
record = {{'event': 'git', 'argv': args, 'verb': verb, 'bound': bound}}
fixture._log(HOME, record)
if verb and os.path.exists(os.path.join(HOME, 'control', 'hold-' + verb)):
    hold(verb, record)
os.execv(REAL, [REAL] + args)
'''


def _command_unsettled(item):
    """A controller_effects PriorCommand whose bootstrap is, or may still be, alive."""
    return item.identity_status in ('owned', 'unknown') or item.state not in SETTLED_COMMAND_STATES


class ControllerRecoveryRegressions(harness.ControllerHarness):

    # ---- fixture git front end ---------------------------------------------------------

    def setUp(self):
        super().setUp()
        self.lost_roots = set()  # evidence roots this test removed after proving them settled
        self.git_home = self.root / 'githome'
        for sub in ('log', 'control'):
            (self.git_home / sub).mkdir(parents=True)
        self.addCleanup(self._release_git_holds)  # runs before the harness cleanup
        entry = self.root / 'pathbin' / 'git'
        real = os.path.realpath(entry)
        entry.unlink()
        entry.write_text(GIT_WRAPPER.format(python=sys.executable, fixtures=str(harness.FAKE_CLI.parent),
                                            home=str(self.git_home), real=real,
                                            hold_seconds=HOLD_SECONDS))
        entry.chmod(0o700)

    def _release_git_holds(self):
        """No new hold; every held wrapper terminates ITSELF on the profile-wide trigger."""
        for path in (self.git_home / 'control').glob('hold-*'):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        (self.git_home / 'control' / 'terminate-all').touch()

    def fixture_markers(self):
        markers = super().fixture_markers()
        for path in sorted((self.git_home / 'log' / 'live').glob('*.json')):
            try:
                markers.append(json.loads(path.read_text()))
            except FileNotFoundError:
                continue  # the wrapper expired and removed its own marker
            except ValueError:
                markers.append({'pid': None, 'start': None, 'marker': str(path)})
        return markers

    def git_events(self, event='git', after=0):
        log = self.git_home / 'log' / 'events.jsonl'
        if not log.exists():
            return []
        rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        return [row for row in rows if row['event'] == event and row['ns'] > after]

    def git_ready(self, verb):
        path = self.git_home / 'log' / f'ready-{verb}.json'
        return json.loads(path.read_text()) if path.exists() else None

    def crash_git(self, marker):
        """The identified held wrapper SIGKILLs itself; the test signals nothing."""
        (self.git_home / 'control' / f"crash-{marker['token']}").touch()

    # ---- cleanup policy ----------------------------------------------------------------

    def _engine_problems(self):
        """Only live processes block removal of the temp root. A held effect, an unknown
        attempt row or a workspace that `recover` left in place is a ledger fact, not a
        process; an attempt, effect-command or query bootstrap not provably gone is."""
        done = self.cli('status', '--json', timeout=60)
        if done.returncode:
            return [f'status unreadable: {done.stderr.strip()[-400:]}']
        try:
            report = json.loads(done.stdout)
        except ValueError:
            return ['status --json printed no JSON']
        process = harness._module('controller_process', harness.SCRIPTS)
        problems = []
        for attempt in report['status']['attempts']:
            identity = self._process_identity(attempt.get('launch'), process.IDENTITY_KEYS)
            verdict = None if identity is None else process.identify(identity)
            if verdict not in (None, 'not-owned'):
                problems.append(f"attempt {attempt['id']} bootstrap {identity['pid']} is {verdict}")
        for effect in report['status']['effects']:
            problems += self._effect_command_problems(effect)
        return problems + self._query_problems(process)

    def _effect_command_problems(self, effect):
        """Read-only (fx.inspect_commands) proof that no command bootstrap recorded under
        this effect's journalled evidence root is still, or possibly, alive."""
        label = f"effect {effect['id']} ({effect['kind']})"
        spec = effect['spec'] if isinstance(effect.get('spec'), dict) else {}
        token = spec.get(ROOT_KEY)
        if type(token) is not str or not ROOT_TOKEN.fullmatch(token):
            return [f'{label} journals no evidence root; its commands cannot be inspected']
        root = self.state / 'effects' / token
        if str(root) in self.lost_roots:
            return []  # removed by this test only after settle_prior_commands proved it
        if not root.is_dir():
            return [f'{label} evidence root is missing; its commands cannot be inspected']
        effects = harness._module('controller_effects', harness.SCRIPTS)
        try:
            commands = effects.inspect_commands(str(root))
        except effects.ToolchainError as err:
            return [f'{label} evidence root not inspectable ({err.code})']
        return [f'{label} command {os.path.basename(item.attempt)} is {item.state} '
                f'({item.identity_status})' for item in commands if _command_unsettled(item)]

    def _query_problems(self, process):
        """Controller query attempts without a lifecycle record must be provably settled."""
        queries, problems = self.state / 'queries', []
        if not queries.is_dir():
            return problems
        for path in sorted(queries.iterdir()):
            if (path / process.RECORD).exists():
                continue  # a finalized record is written only for a settled attempt
            try:
                status = process.read_status(str(path))
            except process.ProcessError as err:
                problems.append(f'query {path.name} unreadable ({err.code})')
                continue
            if (status['identityStatus'] in ('owned', 'unknown')
                    or status['state'] not in SETTLED_COMMAND_STATES):
                problems.append(f"query {path.name} is {status['state']} ({status['identityStatus']})")
        return problems

    # ---- shared steps ------------------------------------------------------------------

    def task_view(self, task_id):
        return self.ledger(lambda ledger: ledger.task(task_id))

    def effect_row(self, effect_id):
        return next(row for row in self.status()['status']['effects'] if row['id'] == effect_id)

    def kind_call_dirs(self, kind):
        """Every controller_effects call directory of one effect kind anywhere under --state."""
        pattern = re.compile(CALL_DIR.format(kind=re.escape(kind)))
        return sorted(os.path.join(directory, name) for directory, names, _ in os.walk(self.state)
                      for name in names if pattern.fullmatch(name))

    def call_dirs(self, root, kind):
        pattern = re.compile(CALL_DIR.format(kind=re.escape(kind)))
        return sorted(name for name in os.listdir(root) if pattern.fullmatch(name))

    def evidence_root(self, effect):
        """The exact evidence root the read-only ledger journals for one effect: the random
        token in spec.evidence_root under <state>/effects (never the numeric effect id)."""
        spec = effect['spec'] if isinstance(effect.get('spec'), dict) else {}
        token = spec.get(ROOT_KEY)
        self.assertTrue(type(token) is str and ROOT_TOKEN.fullmatch(token),
                        f"effect {effect['id']} journals no evidence-root token: {token!r}")
        others = [row['id'] for row in self.status()['status']['effects']
                  if row['id'] != effect['id'] and row['spec'].get(ROOT_KEY) == token]
        self.assertEqual(others, [], 'an evidence root is shared between effect intents')
        return self.state / 'effects' / token

    def commit_evidence_root(self, effect):
        root = self.evidence_root(effect)
        self.assertTrue(root.is_dir() and not root.is_symlink(),
                        f'journalled evidence root {root} is not an existing directory')
        self.assertEqual(os.path.realpath(root), str(root))
        self.assertTrue(self.call_dirs(root, 'task.commit'),
                        'the running commit left no call directory under its journalled root')
        return root

    def prior_commands(self, root):
        effects = harness._module('controller_effects', harness.SCRIPTS)
        return effects.inspect_commands(str(root))

    def settle_prior_commands(self, root, timeout=60):
        """Read-only proof that no command bootstrap under this root is still (or possibly)
        alive before the fixture alters the evidence."""
        deadline = time.monotonic() + timeout
        while True:
            live = [item for item in self.prior_commands(root) if _command_unsettled(item)]
            if not live:
                return
            if time.monotonic() >= deadline:
                self.fail('command bootstraps not proven gone; evidence kept: '
                          + ', '.join(f'{item.attempt} ({item.state}, {item.identity_status})'
                                      for item in live))
            time.sleep(0.2)

    def hold_commit_effect(self):
        """Run task T until the engine's task.commit mutation (`git commit`) is held inside
        the fixture git front end; nothing has been committed and the engine is busy in it."""
        self.profile('solo', 'claude', {'recipes': {'T': {'tee.py': TEE}}})
        self.setup_controller({'tee': self.check_argv('module', 'tee', '7')})
        self.submit('held', [harness.task('T', ['tee.py'], ['tee'])])
        (self.git_home / 'control' / 'hold-commit').touch()
        proc = self.start_run()
        held = self.wait_for(lambda: self.git_ready('commit'), 300,
                             'the task commit to reach git on the operator PATH', proc)
        unresolved = self.status()['owned_work']['effects']
        self.assertEqual([row['kind'] for row in unresolved], ['task.commit'],
                         'the running commit has no journalled intent')
        return proc, held, unresolved[0]

    def crashed_commit_effect(self):
        """Controller crash inside the commit mutation: the intent stays unresolved, the held
        command never ran git and is proven gone, and its journalled evidence root is located."""
        proc, held, effect = self.hold_commit_effect()
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)  # the test's own unreaped run group
        proc.wait(timeout=30)
        self.crash_git(held)
        self.wait_for(lambda: self.worker_state(held) == 'gone', 30, 'the held git command to end itself')
        root = self.commit_evidence_root(effect)
        self.settle_prior_commands(root)
        self.assertEqual(self.git_events('hold_expired'), [])
        return held, root, effect

    def recover_after(self, held):
        """One `recover`; returns the worktree tip before it and the git invocations it made."""
        tip = self.git('rev-parse', 'HEAD', cwd=held['bound'])
        turns, mark = len(self.events('start')), time.time_ns()
        done = self.cli('recover', timeout=PASS_TIMEOUT)
        self._engine_present(done.stderr)
        self.assertNotIn('raised', done.stderr, 'recovery raised instead of holding or settling')
        calls = self.git_events(after=mark)
        self.assertEqual(len(self.events('start')), turns, 'recover launched a native session')
        return tip, calls

    def assert_commit_not_replayed(self, held, effect, tip, calls):
        replayed = [row['argv'] for row in calls if row['verb'] in COMMIT_VERBS]
        self.assertEqual(replayed, [], 'recovery replayed a commit mutation')
        self.assertNotEqual(self.effect_row(effect['id'])['state'], 'done',
                            'a commit that never ran was recorded as applied')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=held['bound']), tip, 'the task branch moved')
        self.assertTrue((Path(held['bound']) / 'tee.py').exists(), 'uncommitted task work was discarded')

    def assert_effect_held(self, held, effect, calls, states):
        """Lost command history is never read as a fresh start: the effect stays unresolved in
        one of ``states``, Git is not asked about it and its attempt is not closed for retry."""
        work = self.status()['owned_work']
        self.assertIn(effect['id'], [row['id'] for row in work['effects']],
                      'recovery resolved an effect whose command evidence is lost: '
                      f"{self.effect_row(effect['id'])['state']}")
        self.assertIn(self.effect_row(effect['id'])['state'], states)
        touched = [row['argv'] for row in calls if row['bound'] == held['bound']
                   or row['bound'].startswith(held['bound'] + os.sep)]
        self.assertEqual(touched, [], 'recovery queried Git for an effect it cannot account for')
        self.assertIn(effect['spec']['attempt'], [row['id'] for row in work['attempts']],
                      'the implement attempt was closed while its commit is unresolved (blind retry)')
        self.assertEqual(self.task_view('T')['state'], 'implementing', 'the task was requeued')

    # ---- A: lost command evidence ------------------------------------------------------

    def test_recovery_holds_commit_effect_whose_whole_evidence_root_was_lost(self):
        held, root, effect = self.crashed_commit_effect()
        self.lost_roots.add(str(root))
        shutil.rmtree(root)  # inside this test's temp root; its processes are proven gone
        for _ in range(2):  # the hold is stable across repeated recovery
            tip, calls = self.recover_after(held)
            self.assert_effect_held(held, effect, calls, ('unknown',))
            self.assertFalse(os.path.lexists(root), 'recovery recreated the lost evidence root')
            self.assertEqual(self.kind_call_dirs('task.commit'), [],
                             'recovery opened a new observe/execute call for the effect')
            self.assert_commit_not_replayed(held, effect, tip, calls)

    def test_recovery_holds_commit_effect_whose_command_evidence_was_emptied(self):
        held, root, effect = self.crashed_commit_effect()
        for child in root.iterdir():  # root survives; every call directory and command is gone
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for _ in range(2):
            tip, calls = self.recover_after(held)
            self.assert_effect_held(held, effect, calls, ('intent', 'unknown'))
            self.assertEqual(self.kind_call_dirs('task.commit'), [],
                             'recovery opened a new observe/execute call for the effect')
            self.assert_commit_not_replayed(held, effect, tip, calls)

    def test_recovery_never_replays_interrupted_commit_with_intact_evidence(self):
        """Control: with the evidence intact the documented contract decides (hold, or settle
        absent from a clean lifecycle); either way nothing is replayed or marked applied."""
        held, root, effect = self.crashed_commit_effect()
        kept = self.call_dirs(root, 'task.commit')
        tip, calls = self.recover_after(held)
        self.assertLessEqual(set(kept), set(self.call_dirs(root, 'task.commit')),
                             'earlier command evidence was removed')
        self.assert_commit_not_replayed(held, effect, tip, calls)

    # ---- B: durable STOP inside a synchronous effect -----------------------------------

    def state_paths(self, skip=()):
        """Durable files under --state (SQLite rollback journals are transient by design)."""
        skipped = tuple(str(self.state / name) + os.sep for name in skip)
        return {os.path.join(directory, name) for directory, _, names in os.walk(self.state)
                for name in names if not name.endswith('-journal')
                and not os.path.join(directory, name).startswith(skipped)}

    def test_durable_stop_reaches_a_running_synchronous_effect(self):
        proc, held, effect = self.hold_commit_effect()
        before = self.status()['status']
        paths, turns = self.state_paths(), len(self.events('start'))
        tip = self.git('rev-parse', 'HEAD', cwd=held['bound'])
        mark = time.time_ns()
        self.expect_cli(0, 'stop')
        try:
            proc.wait(timeout=STOP_BOUND_SECONDS)
        except subprocess.TimeoutExpired:
            self.fail(f'durable STOP was not observed within {STOP_BOUND_SECONDS}s while the engine '
                      'was inside a synchronous effect; the held command was never stopped')
        self._engine_present(self.proc_err(proc))
        self.wait_for(lambda: self.worker_state(held) == 'gone', 30, 'the stopped git command to end')
        self.assertEqual(self.git_events('hold_expired'), [], 'the command expired instead of being stopped')
        mutations = [item for item in self.prior_commands(self.commit_evidence_root(effect)) if item.mutation]
        self.assertIn('stopped', [item.termination for item in mutations],
                      'no command was ended by a STOP request: '
                      f'{[(item.state, item.termination) for item in mutations]}')
        self.assertNotIn('timeout', [item.termination for item in mutations])

        def frozen():
            status = self.status()['status']
            return status, (status['control'], [(a['id'], a['role']) for a in status['attempts']],
                            len(self.events('start')), len(self.reviews()))

        expected = ('stopped', [(a['id'], a['role']) for a in before['attempts']], turns, 0)
        status, facts = frozen()
        self.assertEqual(facts, expected, 'STOP did not hold claims and launches')
        self.assertIn(self.effect_row(effect['id'])['state'], ('intent', 'unknown'),
                      'a cancelled mutation was settled as applied or absent')
        self.assertTrue({row['kind'] for row in status['effects']}
                        <= {'worktree.create', 'task.commit', 'worktree.remove'},
                        'a new mutation effect was journalled after STOP')
        self.assertNotIn(status['tasks'][0]['state'], DONE)
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=held['bound']), tip, 'the task branch moved')
        self.assertTrue((Path(held['bound']) / 'tee.py').exists(), 'uncommitted task work was discarded')
        self.assertLessEqual(paths, self.state_paths(), 'earlier state artifacts were removed')

        self.run_once()
        self.assertEqual(frozen()[1], expected, 'restart under STOP launched or claimed work')
        self.assertEqual([row['argv'] for row in self.git_events(after=mark) if row['verb'] in COMMIT_VERBS],
                         [], 'a commit mutation ran after STOP')
        self.assert_owner_boundaries(self.status())

    # ---- C: no-change investigation ------------------------------------------------------

    def seed_origin(self):
        """Give the plan origin a checkable module so real checks can pass on an unchanged tree."""
        (self.repo / 'seed.py').write_text(SEED)
        self.git('add', 'seed.py')
        self.git('commit', '-q', '-m', 'chore: seed fixture module')
        self.git('push', '-q', 'origin', 'main')
        self.origin_sha = self.git('rev-parse', 'main')
        self.source_before = self._source_snapshot()

    def test_no_change_investigation_is_accepted_integrated_and_gated_as_candidate(self):
        self.seed_origin()
        self.profile('solo', 'claude', {'recipes': {'N': {}}})
        self.setup_controller({'seed': self.check_argv('module', 'seed', '4')})
        # controller_inputs._validate_task admits an empty write_scope for kind investigation.
        investigation = dict(harness.task('N', [], ['seed']), kind='investigation')
        self.submit('nochange', [investigation])
        commits, mark = set(self.git('rev-list', '--all').split()), time.time_ns()
        codes, report = self.drive()
        origin = self.origin_sha
        found = report['status']['tasks'][0]
        self.assertEqual(found['state'], 'accepted', f'run outcomes {codes}')
        self.assertEqual(found['result'], origin, 'a no-change result is not the commit the task ran on')
        binding = self.task_view('N')['binding']
        self.assertEqual(binding['execution_base'], origin)
        self.assertEqual(found['failures'], 0)
        self.assert_native_turns()

        self.assertEqual(set(self.git('rev-list', '--all').split()), commits, 'a commit was fabricated')
        self.assertEqual([row['argv'] for row in self.git_events(after=mark)
                          if row['verb'] in (*COMMIT_VERBS, 'merge')], [],
                         'a commit or merge mutation ran for a task that changed nothing')
        implemented = [row for row in self.events('end') if row['role'] == 'implement']
        self.assertTrue(implemented and all(row['written'] == [] for row in implemented))
        self.assertTrue(all(row['head'] == row['envelope']['base_sha'] == origin for row in implemented))

        # The no-op contribution is a confirmed integrate effect of N, checkpointed as such.
        integrations = [row for row in report['status']['effects'] if row['kind'] == 'integrate']
        self.assertEqual([(row['task_id'], row['state']) for row in integrations], [('N', 'done')],
                         'the no-change result has no single confirmed integration effect bound to N')
        effect = integrations[0]
        self.assertEqual((effect['spec']['result'], effect['spec']['expected_base'],
                          (effect['result'] or {}).get('result_sha')), (origin, origin, origin))
        plan = self.ledger(lambda ledger: ledger.plan('nochange'))
        checkpoint = plan['checkpoint']
        self.assertIsNotNone(checkpoint, 'the plan has no checkpoint')
        self.assertEqual((checkpoint['sha'], checkpoint['contributions'], checkpoint['effect_id']),
                         (origin, {'N': origin}, effect['id']),
                         'the checkpoint does not record N contributing the plan origin')

        # The derived candidate is that checkpoint and earned its own check and fresh review.
        self.assertEqual(len(plan['candidates']), 1, 'expected exactly one derived candidate')
        candidate = plan['candidates'][0]
        self.assertEqual((candidate['origin'], candidate['result'], candidate['stage'], candidate['current']),
                         (origin, origin, 'accepted', True))
        self.assertEqual(candidate['contributions'], {'N': {'result': origin, 'binding': binding['id']}})
        self.assertEqual(candidate['evidence']['integrations'], {'N': effect['id']})
        self.assertEqual(codes[-1], 0, f'run outcomes {codes}')
        for subject in ('N', candidate['id']):
            self.assert_check_receipts(report, subject, origin)
            self.assertTrue([row for row in report['status']['evidence'] if row['task_id'] == subject
                             and row['kind'] == 'review' and row['passed'] == 1],
                            f'no approving review evidence recorded for {subject}')

        def passed(subject):
            return self.reviews(lambda r: r['task_id'] == subject and r['verdict'] == 'PASS' and r['range_ok']
                                and (r['envelope']['base_sha'], r['envelope']['result_sha']) == (origin, origin))

        def checked(path):
            return [row for row in self.checks_run() if row['cwd'] == path and row['head'] == origin
                    and row['ok'] and row['check'] == 'module seed 4']

        task_review, whole_review = passed('N'), passed(candidate['id'])
        self.assertTrue(task_review, 'no task-level review of the no-change result')
        self.assertTrue(whole_review, 'no review claimed on the derived candidate itself')
        self.assertNotEqual(task_review[-1]['session'], whole_review[-1]['session'],
                            'the candidate review reused the task review session')
        producers = {row['pid'] for row in implemented}
        self.assertFalse({task_review[-1]['pid'], whole_review[-1]['pid']} & producers,
                         'a reviewer reused the producer process')
        self.assertEqual([r for r in self.reviews() if r['verdict'] != 'PASS'], [])
        task_checks = checked(binding['workspace']['path'])
        whole_checks = checked(candidate['workspace']['path'])
        self.assertTrue(task_checks, 'no task check ran in the task workspace')
        self.assertTrue(whole_checks, 'the candidate check did not run in the candidate workspace')
        self.assertLess(task_checks[0]['ns'], task_review[-1]['ns'], 'task review preceded its check')
        self.assertLess(task_review[-1]['ns'], whole_checks[0]['ns'],
                        'the candidate was checked before the task-level gate passed')
        self.assertLess(whole_checks[-1]['ns'], whole_review[-1]['ns'],
                        'the candidate review preceded the candidate check')

        self.assertEqual((report['owned_work']['attempts'], report['owned_work']['effects']), ([], []))
        self.assert_owner_boundaries(report)

    # ---- D: readmitted preserved result ------------------------------------------------

    def readmit_authority(self, plan):
        plan_path = self.root / f"plan-{plan['id']}.json"
        digest = self.cli('digest', '--plan', str(plan_path), '--policy', str(self.policy_path),
                          state=False).stdout.strip()
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        return self._private_json(self.root / f"authority-{plan['id']}-readmit.json", {
            'version': 1, 'plan_digest': digest, 'effects': ['commit', 'integrate'],
            'authorizer': 'acceptance-fixture', 'approved_at': now})

    def readmit(self, plan, authority):
        done = self.cli('readmit', '--plan-id', plan['id'], '--authority', str(authority),
                        '--actor', 'fixture-owner')
        self._engine_present(done.stderr)
        return done

    def created_workspaces(self):
        """{path: (branch, tip)} of every confirmed controller worktree the journal records."""
        rows = [row['spec'] for row in self.status()['status']['effects']
                if row['kind'] == 'worktree.create' and row['state'] == 'done']
        return {spec['path']: (spec['branch'], self.git('rev-parse', f"refs/heads/{spec['branch']}"))
                for spec in rows}

    def cleanup_workspaces(self, plan, retained, before):
        """The explicit operator cleanup: clean, confirmed, owned workspaces of the plan are
        removed; branches, raw logs and history stay."""
        paths = self.state_paths(skip=('workspaces',))
        done = self.cli('cleanup-workspaces', '--plan-id', plan['id'], '--actor', 'fixture-owner',
                        timeout=PASS_TIMEOUT)
        self._engine_present(done.stderr)
        if 'invalid choice' in done.stderr:
            self.fail('operator command cleanup-workspaces is not implemented, so a plan with owned '
                      'workspaces can never be readmitted (expected RED until it exists)')
        self.assertEqual(done.returncode, 0, 'cleanup-workspaces did not report PASS for clean owned '
                         f'workspaces: {done.stderr.strip()[-600:]}')
        report = self.status()
        status = report['status']
        self.assertEqual(report['owned_work']['workspaces'], [], 'owned workspaces remain after cleanup')
        for path, (branch, tip) in retained.items():
            self.assertFalse(os.path.lexists(path), f'workspace {path} was not removed')
            self.assertEqual(self.git('rev-parse', f'refs/heads/{branch}'), tip,
                             f'cleanup deleted or moved branch {branch}')
        self.assertEqual((status['control'], status['epoch']), (before['control'], before['epoch']),
                         'cleanup changed the control or the context')
        self.assertEqual((status['attempts'], status['evidence'], status['tasks']),
                         (before['attempts'], before['evidence'], before['tasks']), 'history changed')
        self.assertEqual(status['effects'][:len(before['effects'])], before['effects'],
                         'earlier effect history was rewritten')
        added = status['effects'][len(before['effects']):]
        self.assertEqual({(row['kind'], row['state']) for row in added}, {('worktree.remove', 'done')},
                         f'cleanup journalled something other than confirmed removals: {added}')
        self.assertLessEqual(paths, self.state_paths(skip=('workspaces',)),
                             'cleanup removed raw logs or evidence outside the workspaces')

    def test_readmitted_preserved_result_is_rebound_and_regated_without_reimplementation(self):
        self.profile('solo', 'claude', {'recipes': {'R': {'are.py': ARE}}})
        self.setup_controller({'are': self.check_argv('module', 'are', '9')})
        plan = self.submit('readmitted', [harness.task('R', ['are.py'], ['are'])])
        codes, report = self.drive()
        accepted = report['status']['tasks'][0]
        self.assertEqual((accepted['state'], codes[-1]), ('accepted', 0), f'run outcomes {codes}')
        result, bound = accepted['result'], self.task_view('R')['binding']

        self.expect_cli(0, 'stop')
        contract = self.runtime.parent / 'references' / 'task-contract.md'
        contract.write_bytes(contract.read_bytes() + b'\n')
        self.expect_cli(0, 'recover', timeout=PASS_TIMEOUT)
        retained = self.created_workspaces()
        self.assertIn(bound['workspace']['path'], retained)
        self.assertTrue(all(os.path.isdir(path) for path in retained),
                        'default recover removed an owned workspace')
        self.assertEqual(len(self.status()['owned_work']['workspaces']), len(retained))
        self.expect_cli(0, 'reconcile', '--actor', 'fixture-owner')
        before = self.status()['status']

        authority = self.readmit_authority(plan)
        blocked = self.readmit(plan, authority)
        self.assertEqual(blocked.returncode, 2, 'readmission was not held (INCOMPLETE) while owned '
                         f'workspaces remain: {blocked.stderr.strip()[-400:]}')
        held = self.status()['status']
        # `readmit` takes the ControllerLock even when it holds: exactly one new fence (and its
        # controller_start / readmit_hold audit events, which status does not report).
        self.assertEqual(held['fence'], before['fence'] + 1,
                         'a held readmission did not take exactly one controller fence')
        self.assertEqual({**held, 'fence': before['fence']}, before,
                         'a held readmission changed the ledger beyond its own fence')
        self.assertTrue(all(os.path.isdir(path) for path in retained))
        self.cleanup_workspaces(plan, retained, before)
        admitted = self.readmit(plan, authority)
        self.assertEqual(admitted.returncode, 0, 'readmission of the unchanged plan was refused after '
                         f'the explicit cleanup: {admitted.stderr.strip()[-600:]}')
        view = self.task_view('R')
        self.assertEqual((view['state'], view['result'], view['binding']), ('implemented', result, None),
                         'readmission did not leave a preserved result without a binding')
        self.assertEqual(self.status()['status']['control'], 'stopped', 'readmission cleared STOP')

        mark = time.time_ns()
        earlier = self.events('start')

        def launched():
            return (len([r for r in self.events('start') if r['ns'] > mark]),
                    len([c for c in self.checks_run() if c['ns'] > mark]))

        under_stop = self.run_once()
        self.assertNotIn('engine raised', under_stop.stderr, 'the engine raised on a preserved result')
        self.assertEqual((launched(), self.status()['status']['control']), ((0, 0), 'stopped'),
                         'work started under STOP after readmission')
        self.expect_cli(0, 'resume')
        passes, last = [], None
        for _ in range(4):
            seen = launched()
            last = self.run_once()
            passes.append(last.returncode)
            self.assertNotIn('engine raised', last.stderr,
                             'the engine raised on a preserved result that has no binding')
            if last.returncode == 0 or launched() == seen:
                break
        self.expect_cli(0, 'stop')

        status, view = self.status()['status'], self.task_view('R')
        starts = [row for row in self.events('start') if row['ns'] > mark]
        checks = [row for row in self.checks_run() if row['ns'] > mark]
        tail = last.stderr.strip()[-800:]
        self.assertEqual(status['attempts'][:len(before['attempts'])], before['attempts'],
                         'attempt history changed')
        self.assertGreaterEqual(status['charged_seconds'], before['charged_seconds'], 'charged time lost')
        self.assertEqual((view['failures'], view['result']), (0, result), 'the preserved result was dropped')
        self.assertEqual([c['epoch'] for c in self.ledger(lambda ledger: ledger.contexts())], [1, 2])
        self.assertEqual([row for row in starts if row['role'] == 'implement'], [],
                         'a preserved result was implemented again')
        self.assertEqual([row['argv'] for row in self.git_events(after=mark) if row['verb'] in COMMIT_VERBS],
                         [], 'a preserved result was committed again')

        binding = view['binding']
        self.assertIsNotNone(binding, f'the preserved result was never re-bound (runs {passes}): {tail}')
        self.assertEqual((binding['epoch'], binding['execution_base'], binding['dependencies']),
                         (2, bound['execution_base'], bound['dependencies']),
                         'the preserved result was not re-bound to its own base in the new context')
        self.assertNotEqual((binding['id'], binding['workspace']['path']),
                            (bound['id'], bound['workspace']['path']), 'the earlier binding was reused')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=binding['workspace']['path']), result,
                         'the new workspace is not checked out at the preserved result')
        self.assertTrue([row for row in checks if row['head'] == result and row['ok']
                         and row['cwd'] == binding['workspace']['path']],
                        f'no fresh check ran on the preserved result in its new workspace: {tail}')
        evidence = [row for row in status['evidence'] if row['task_id'] == 'R' and row['epoch'] == 2]
        self.assertTrue([row for row in evidence if row['kind'] == 'check' and row['status'] == 'PASS'
                         and row['receipt'] and row['receipt']['input_sha'] == result],
                        'no PASS check evidence in the new context bound to the preserved result')
        self.assertTrue([row for row in evidence if row['kind'] == 'review' and row['passed'] == 1],
                        'no approving review evidence in the new context')
        fresh = self.reviews(lambda r: r['ns'] > mark and r['task_id'] == 'R'
                             and r['envelope']['result_sha'] == result)
        self.assertTrue(fresh, 'no fresh review of the preserved result after readmission')
        self.assertEqual((fresh[-1]['verdict'], fresh[-1]['envelope']['base_sha']),
                         ('PASS', binding['execution_base']))
        self.assertNotIn(fresh[-1]['pid'], {row['pid'] for row in earlier},
                         'the fresh review reused an earlier process')
        self.assertNotIn(fresh[-1]['session'], {row['session'] for row in earlier},
                         'the fresh review reused an earlier session')
        self.assertEqual(view['state'], 'accepted', f'the re-gated result was not accepted (runs {passes}): {tail}')
        self.assertEqual(passes[-1], 0, 'the readmitted plan did not pass its whole-result gate in the '
                         f'new context (INCOMPLETE is not an accepted outcome; runs {passes}): {tail}')
        self.assert_native_turns()
        self.assert_owner_boundaries(self.status())

    # ---- E: delayed outcome observation --------------------------------------------------

    def lifecycle_end(self, task_id):
        """Epoch seconds of the validated, finalized lifecycle end of the task's single
        implement attempt (controller_process.read_status), else None."""
        process = harness._module('controller_process', harness.SCRIPTS)
        providers = harness._module('controller_providers', harness.SCRIPTS)
        rows = [row for row in self.status()['status']['attempts']
                if (row['task_id'], row['role']) == (task_id, 'implement')]
        if len(rows) != 1 or not isinstance(rows[0]['launch'], dict):
            return None
        try:
            status = process.read_status(str(providers.process_attempt(rows[0]['launch']['locator'])))
        except process.ProcessError:
            return None
        record = status['record']
        if status['state'] != 'finalized' or not record or record['termination'] != 'exited' \
                or not record['endedAt']:
            return None
        return datetime.datetime.fromisoformat(record['endedAt'].replace('Z', '+00:00')).timestamp()

    def wait_until(self, moment):
        self.wait_for(lambda: time.time() >= moment, 30, 'the fixture clock to pass a whole second')

    def test_late_harvested_outcome_keeps_its_end_time_and_does_not_override_a_refresh(self):
        """B ends (lifecycle endedAt) while the engine thread is busy in A's held commit; the
        operator then refreshes B's profile; only afterwards is B harvested. Evidence order is
        the actual end, so the refresh stays the profile's current routing state."""
        recipes = {'A': {'aye.py': AYE}, 'B': {'bee.py': BEE}}
        self.profile('main', 'claude', {'recipes': recipes})
        self.profile('late', 'claude', {'recipes': recipes,
                                        'hold': {'tasks': ['B'], 'once': True, 'timeout': 280}},
                     roles=('implement',))
        self.setup_controller({}, max_parallel=2, auto_route=True)
        self.submit('delayed', [harness.task('A', ['aye.py'], []), harness.task('B', ['bee.py'], [])])
        (self.git_home / 'control' / 'hold-commit').touch()
        proc = self.start_run()
        self.wait_for(lambda: self.ready('late', 'B'), 180,
                      'B to start on the second profile (least-loaded routing)', proc)
        held = self.wait_for(lambda: self.git_ready('commit'), 300, 'the commit of A to be held', proc)
        self.assertEqual(held['bound'], self.task_view('A')['binding']['workspace']['path'],
                         'the held commit is not the commit of A')

        self.go('late', 'B')
        ended = self.wait_for(lambda: self.lifecycle_end('B'), 120,
                              'the finalized lifecycle record of B', proc)
        self.wait_until(math.floor(ended) + 2)
        refresh_mark = time.time_ns()
        self.expect_cli(0, 'refresh-profile', '--profile', 'late', '--actor', 'fixture-owner')
        requests = [row['summary'] for row in self.status()['requests'] if row['action'] == 'refresh_profile']
        self.assertEqual(len(requests), 1)
        requested_at = requests[0]['requested_at']
        self.assertGreater(requested_at, ended, 'fixture: the refresh does not follow the actual end')
        self.wait_until(requested_at + 2)
        self.assertEqual(self.worker_state(held), 'running', 'fixture: the engine left the held effect early')
        self.assertEqual(self.ledger(lambda ledger: ledger.observation_history('late')), [],
                         'fixture: B was harvested before the refresh was requested')

        self.crash_git(held)  # the held command ends itself without running git; the run goes on
        proc.wait(timeout=PASS_TIMEOUT)
        self._engine_present(self.proc_err(proc))
        history = self.ledger(lambda ledger: ledger.observation_history('late'))
        outcomes = [row for row in history if row['data']['source'] == 'outcome']
        refreshes = [row for row in history if row['data']['source'] == 'operator_refresh']
        self.assertEqual([row['data']['ended_at'] for row in refreshes], [requested_at],
                         f'the operator refresh was not consumed: {self.proc_err(proc)}')
        if outcomes:
            self.assertLessEqual(abs(outcomes[0]['data']['ended_at'] - ended), 1.0,
                                 'the outcome of B carries its harvest time as evidence time, not the '
                                 f"validated lifecycle end {ended}: {outcomes[0]['data']['ended_at']}")
        self.assertEqual((refreshes[0]['admitted'], refreshes[0]['reason']), (True, 'admitted'),
                         'an outcome that ended before the operator refresh overrode it')
        self.assertEqual([row['task_id'] for row in self.events('start')
                          if row['profile'] == 'late' and row['ns'] > refresh_mark], [],
                         'a refreshed (unknown) profile was preferred over an observed available one')
        current = {row['profile_id']: row['data'] for row in self.status()['status']['observations']}['late']
        self.assertEqual((current['source'], current['availability'], current['ended_at']),
                         ('operator_refresh', 'unknown', requested_at),
                         'the operator refresh is not the current routing state of the profile')
        self.assert_owner_boundaries(self.status())


if __name__ == '__main__':
    unittest.main()
