"""Physical-settlement gate of the persistent controller engine (controller_engine.py).

A finalized lifecycle record whose own process tree is not proven settled (a live or unknown
escaped child, an incomplete observation, a group not proven empty, or an unreadable record)
must keep the attempt UNKNOWN: no reconcile, success, approval, check record or retry slot is
released from it. Settled outcomes keep their existing attribution and acceptance paths, and
proven never-launched attempts keep their safe cancellation.

The REAL engine completion methods (_complete_native, _complete_check, _complete_adopted,
_reconcile_attempt) run on an Engine built from its real methods with an inert ledger (an
attempt state machine with finish_attempt semantics) and a read-only helper seam that
returns helper-shaped read_status/recover results. The gate (_lifecycle_gap) and the public
controller_process.escaped_settled predicate are never mocked, and every fixture record first
proves which value escaped_settled gives it. Two cases use a real, self-terminating
controller_process lifecycle (a command that exits 0; an attempt aborted before release); no
daemon is started and nothing is signalled by pid or name.
"""
import contextlib
import copy
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / '.claude' / 'skills' / 'delivery' / 'scripts'


def _load(name):
    """Import a runtime module from the source tree without writing bytecode into it."""
    if name not in sys.modules:
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(SCRIPTS))
        try:
            importlib.import_module(name)
        finally:
            sys.path.remove(str(SCRIPTS))
            sys.dont_write_bytecode = previous
    return sys.modules[name]


engine = _load('controller_engine')
process = engine.process
LedgerError = engine.LedgerError

HOLD = engine.LIFECYCLE_HOLD
BOOT = 'fixture-boot-0001'
START = 'Sat Nov 14 05:39:14 2026'
BASE = 'a' * 40
RESULT = 'b' * 40
PROFILE = {'id': 'solo', 'provider': 'claude'}
ACTIVE = ('reserved', 'launched', 'unknown')
# One typed settlement proof per escaped identity, as controller_process._probe_escaped writes them.
GONE = {'pid': 4101, 'start': START, 'status': 'gone', 'proof': 'esrch', 'currentStart': None}
LIVE = {'pid': 4102, 'start': START, 'status': 'live', 'proof': 'start-matches', 'currentStart': START}
UNKNOWN = {'pid': 4103, 'start': None, 'status': 'unknown', 'proof': 'original-start-missing',
           'currentStart': START}
SCRIPT = '#!/bin/sh\nexit 0\n'
SETTLE_SECONDS = 60
# What controller_checks reports for a check whose release the ledger refused.
DENIED = SimpleNamespace(status='INCOMPLETE', reasons=('release-not-authorized',))


def v4_record(identities=(), group_empty=True, termination='exited', exit_code=0):
    """A lifecycle/v4 record shaped as controller_process._build_record writes it, with a
    self-consistent escape settlement (counts, boot, unresolved total)."""
    items = [dict(item) for item in identities]
    statuses = [item['status'] for item in items]
    live, unknown = statuses.count('live'), statuses.count('unknown')
    unresolved = live + unknown + (1 if group_empty is False else 0)
    reasons = [code for failed, code in (
        (exit_code not in (None, 0), 'nonzero-exit'), (group_empty is not True, 'group-not-proven-empty'),
        (live + unknown > 0, 'escaped-descendants-unsettled'), (unresolved > 0, 'unresolved-descendants'))
        if failed]
    return {'schema': process.SCHEMA_RECORD, 'attemptId': 'fixture', 'intentSha256': 'c' * 64,
            'identity': {'attemptId': 'fixture', 'pid': 4000, 'pgid': 4000, 'bootId': BOOT},
            'commandPid': 4001, 'commandStart': START, 'termination': termination, 'stopSource': None,
            'exitCode': exit_code, 'signal': None, 'forced': False, 'signalsSent': [], 'lingering': False,
            'membersAtExit': 0, 'groupEmpty': group_empty, 'groupObservation': 'ok',
            'escapedDescendants': len(items), 'escapedOverflow': False,
            'escapedSettlement': {'observationComplete': True, 'bootId': BOOT,
                                  'observedAt': '2026-11-14T05:39:15.000Z', 'identities': items,
                                  'settled': len(items) - live - unknown, 'live': live, 'unknown': unknown},
            'unresolvedDescendants': unresolved, 'reasons': reasons,
            'executionSuccess': not reasons and termination == 'exited'}


def v3_record(escaped, group_empty=True):
    """A legacy lifecycle/v3 record: no settlement proof, escapedDescendants is history only."""
    record = v4_record(group_empty=group_empty)
    for key in ('escapedOverflow', 'escapedSettlement'):
        del record[key]
    record.update(schema=process.SCHEMA_RECORD_V3, escapedDescendants=escaped, unresolvedDescendants=0,
                  reasons=['escaped-descendants'] if escaped else [], executionSuccess=not escaped)
    return record


class HelperSeam:
    """Read-only stand-in for controller_process.read_status/recover keyed by attempt path.
    relaunchSafe is False for every launched record, as the real helper reports it."""

    def __init__(self):
        self.statuses, self.reads = {}, []

    def add(self, path, record=None, state='finalized'):
        safe = state == 'not-launched' or (record or {}).get('termination') == 'not-launched'
        self.statuses[os.fspath(path)] = {
            'schema': process.SCHEMA_STATUS, 'attemptId': os.path.basename(os.fspath(path)), 'state': state,
            'relaunchSafe': safe, 'identityStatus': 'not-owned', 'reason': None,
            'record': copy.deepcopy(record) if state == 'finalized' else None}

    def read_status(self, attempt):
        key = os.fspath(attempt)
        self.reads.append(key)
        if key not in self.statuses:
            raise process.ProcessError('attempt-not-found')
        return copy.deepcopy(self.statuses[key])

    def recover(self, attempt):
        status = self.read_status(attempt)
        return process.Recovery(status['state'], status['relaunchSafe'], status['identityStatus'],
                                status['reason'])


class InertLedger:
    """Attempt state machine with controller_ledger.finish_attempt semantics: reconciled=False
    or outcome 'unknown' keeps the attempt active ('unknown'); success needs a launched,
    released attempt; a finished attempt never finishes again. Everything else is recorded."""

    def __init__(self, attempts, task=None, effects=()):
        self.attempts = {row['id']: dict(row) for row in attempts}
        self.task_view, self.effects, self.calls = task, list(effects), []

    def control(self):
        return 'running'

    def owned_work(self):
        rows = [dict(row) for row in self.attempts.values() if row['state'] in ACTIVE]
        return {'control': 'running', 'attempts': rows, 'effects': [], 'workspaces': []}

    def status(self):
        return {'effects': copy.deepcopy(self.effects)}

    def task(self, task_id):
        if self.task_view is None or task_id != self.task_view['id']:
            raise LedgerError('unknown_task', str(task_id))
        return copy.deepcopy(self.task_view)

    def finish_attempt(self, attempt_id, outcome, reconciled, result=None, used_seconds=None,
                       attribution=None, reason=None, category=None):
        row = self.attempts[attempt_id]
        if row['state'] == 'finished':
            raise LedgerError('conflict', 'attempt is already finished')
        if outcome == 'success' and reconciled and not (row['state'] == 'launched' and row['released_at']):
            raise LedgerError('not_released', 'success needs a launched, released attempt')
        self.calls.append(('finish', attempt_id, outcome, reconciled, attribution, reason, result))
        row['state'] = 'unknown' if not reconciled or outcome == 'unknown' else 'finished'

    def record_check_outcome(self, *args):
        self.calls.append(('check_outcome', *args))

    def record_review(self, *args):
        self.calls.append(('review', *args))

    def transition(self, *args):
        self.calls.append(('transition', *args))

    def observe(self, *args):
        self.calls.append(('observe', *args))


class RecordingQueries:
    """Git query stand-in for the implementation path: one clean worktree at its base."""

    def __init__(self, branch='ctl/t', head=BASE):
        self.answers, self.calls = {'branch': branch, 'head': head, 'changed': []}, []

    def __getattr__(self, name):
        if name not in ('branch', 'head', 'changed'):
            raise AttributeError(name)

        def query(path):
            self.calls.append((name, path))
            return self.answers[name]
        return query


def outcome(admitted=True, category='success', session='session-1', verdict=None):
    return SimpleNamespace(execution_admitted=admitted, category=category, quota_latest_status=None,
                           reasons=(), session_id=session, verdict_candidate=verdict, verdict_problem=None,
                           quota_snapshots=())


def native_result(provider_outcome, stopped=False):
    return engine.NativeResult('exited', provider_outcome, stopped, False, 1.0, None)


def attempt_row(attempt_id, role, locator, kind='native', state='launched', released=True):
    launch = {'kind': kind, 'locator': locator, 'pid': 4000} if locator is not None else None
    return {'id': attempt_id, 'task_id': 'T', 'role': role, 'state': state, 'launch': launch,
            'released_at': '2026-11-14T05:39:14Z' if released else None}


class UnsettledLifecycleGate(unittest.TestCase):

    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix='ctl-unsettled-')))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.handoffs = self.root / 'handoffs'
        self.handoffs.mkdir(mode=0o700)
        self.seam = HelperSeam()
        for name in ('read_status', 'recover'):
            patcher = mock.patch.object(process, name, getattr(self.seam, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        quiet = mock.patch.object(sys, 'stderr', io.StringIO())
        quiet.start()
        self.addCleanup(quiet.stop)

    # ---- fixture builders ----------------------------------------------------------------

    def native(self, name):
        """(provider attempt locator, its controller_process attempt path)."""
        locator = str(self.root / 'attempts' / name)
        return locator, engine.providers.process_attempt(locator)

    def check_path(self, name):
        return str(self.root / 'checks' / name / 'process' / name)

    def task_view(self, kind='feature'):
        path = str(self.root / 'workspaces' / 't')
        return {'id': 'T', 'plan_id': 'P', 'gate': 'gate-1',
                'binding': {'workspace': {'path': path}, 'execution_base': BASE},
                'spec': {'kind': kind, 'write_scope': []}}

    def worktree_effect(self, view):
        return {'id': 9, 'kind': 'worktree.create', 'state': 'done', 'owner': 'task', 'task_id': 'T',
                'spec': {'path': view['binding']['workspace']['path'], 'branch': 'ctl/t'}}

    def engine_for(self, ledger, queries=None):
        eng = engine.Engine.__new__(engine.Engine)
        eng.ledger, eng.queries = ledger, queries or RecordingQueries()
        eng.holds, eng.task_holds, eng.said, eng.jobs = {}, {}, set(), {}
        eng.dirs = {'handoffs': str(self.handoffs)}
        eng.stop_event = threading.Event()
        return eng

    # ---- shared assertions ---------------------------------------------------------------

    def assert_held(self, ledger, eng, attempt_id, plan_id='P'):
        row = ledger.attempts[attempt_id]
        self.assertEqual(row['state'], 'unknown', 'an unsettled attempt was closed (scope/capacity released)')
        self.assertIn(attempt_id, [item['id'] for item in ledger.owned_work()['attempts']],
                      'the unsettled attempt left the active set, so a retry could be claimed')
        finishes = [call for call in ledger.calls if call[0] == 'finish' and call[1] == attempt_id]
        self.assertTrue(all(call[2] == 'unknown' or call[3] is False for call in finishes),
                        f'an unsettled attempt was reconciled: {finishes}')
        self.assertEqual([call for call in ledger.calls if call[0] in ('review', 'transition', 'check_outcome')],
                         [], 'a verdict, acceptance or check outcome was recorded from an unsettled attempt')
        self.assertEqual(eng.task_holds.get('T'), HOLD)
        if plan_id is None:
            return
        self.assertEqual(eng.holds.get(plan_id), ('INCOMPLETE', HOLD))
        record = json.loads((self.handoffs / f'{plan_id}-{HOLD}.json').read_text())
        self.assertEqual((record['plan_id'], record['code'], record['to'], record['outcome']),
                         (plan_id, HOLD, 'codex', 'INCOMPLETE'))

    def assert_closed(self, ledger, eng, attempt_id, outcome_name, attribution, reason, result=None):
        self.assertEqual(ledger.attempts[attempt_id]['state'], 'finished')
        finishes = [call for call in ledger.calls if call[0] == 'finish' and call[1] == attempt_id]
        self.assertEqual(finishes, [('finish', attempt_id, outcome_name, True, attribution, reason, result)])
        self.assertNotIn('T', eng.task_holds)
        self.assertEqual(eng.holds, {})

    # ---- native completion ---------------------------------------------------------------

    def test_native_implement_with_live_escaped_child_is_held_not_accepted(self):
        locator, path = self.native('n1-live')
        record = v4_record([LIVE])
        self.assertFalse(process.escaped_settled(record), 'fixture: the live child must be unsettled')
        self.seam.add(path, record)
        ledger = InertLedger([attempt_row(1, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 1, 'T', 'P', PROFILE, locator, {}), native_result(outcome()))
        self.assert_held(ledger, eng, 1)
        self.assertEqual(eng.queries.calls, [], 'the implementation path ran while a child may still mutate')

    def test_native_review_with_unknown_child_and_later_empty_group_is_never_approved(self):
        locator, path = self.native('n2-unknown')
        record = v4_record([UNKNOWN], group_empty=True)
        self.assertFalse(process.escaped_settled(record), 'fixture: an unknown child is never settled')
        self.seam.add(path, record)
        ledger = InertLedger([attempt_row(2, 'review', locator)], self.task_view())
        eng = self.engine_for(ledger)
        verdict = {'version': 1, 'verdict': 'PASS', 'base_sha': BASE, 'result_sha': RESULT, 'findings': [],
                   'gaps': []}
        extra = {'base': BASE, 'result': RESULT, 'producers': set(), 'cwd': str(self.root), 'untracked': [],
                 'bundle': None}
        eng._complete_native(engine.Job('review', 2, 'T', 'P', PROFILE, locator, extra),
                             native_result(outcome(verdict=verdict)))
        self.assert_held(ledger, eng, 2)
        # Recovery reads the same once-written record: still held, never upgraded or re-finished.
        for _ in range(2):
            eng._reconcile_attempt(ledger.owned_work()['attempts'][0], False)
        self.assert_held(ledger, eng, 2)
        self.assertEqual(len([call for call in ledger.calls if call[0] == 'finish']), 1)

    def test_unadmitted_permission_failure_with_live_child_is_held_not_retried(self):
        locator, path = self.native('n3-perm')
        self.seam.add(path, v4_record([LIVE], exit_code=1))
        ledger = InertLedger([attempt_row(3, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 3, 'T', 'P', PROFILE, locator, {}),
                             native_result(outcome(admitted=False, category='permission_denied')))
        self.assert_held(ledger, eng, 3)

    def test_stopped_attempt_with_live_child_is_held_not_cancelled(self):
        locator, path = self.native('n4-stop')
        self.seam.add(path, v4_record([LIVE], exit_code=None))
        ledger = InertLedger([attempt_row(4, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 4, 'T', 'P', PROFILE, locator, {}),
                             native_result(outcome(admitted=False, category='interrupted'), stopped=True))
        self.assert_held(ledger, eng, 4)

    def test_v3_record_with_historical_escape_keeps_strict_meaning(self):
        locator, path = self.native('n5-v3')
        record = v3_record(escaped=1)
        self.assertFalse(process.escaped_settled(record), 'fixture: v3 history of one escape is unsettled')
        self.seam.add(path, record)
        ledger = InertLedger([attempt_row(5, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 5, 'T', 'P', PROFILE, locator, {}), native_result(outcome()))
        self.assert_held(ledger, eng, 5)

    def test_unreadable_lifecycle_is_unknown_not_failed(self):
        locator, _ = self.native('n6-missing')  # the seam has no record: read_status raises
        ledger = InertLedger([attempt_row(6, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 6, 'T', 'P', PROFILE, locator, {}),
                             native_result(outcome(admitted=False, category='failed')))
        self.assert_held(ledger, eng, 6)

    def test_settled_nonzero_failure_keeps_semantic_attribution(self):
        locator, path = self.native('n7-nonzero')
        record = v4_record([GONE], exit_code=1)
        self.assertTrue(process.escaped_settled(record), 'fixture: a positively settled escape is settled')
        self.seam.add(path, record)
        ledger = InertLedger([attempt_row(7, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 7, 'T', 'P', PROFILE, locator, {}),
                             native_result(outcome(admitted=False, category='failed')))
        self.assert_closed(ledger, eng, 7, 'failure', 'semantic', 'no_result')

    def test_settled_permission_failure_keeps_availability_attribution(self):
        locator, path = self.native('n8-perm')
        self.seam.add(path, v4_record(exit_code=1))
        ledger = InertLedger([attempt_row(8, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 8, 'T', 'P', PROFILE, locator, {}),
                             native_result(outcome(admitted=False, category='permission_denied')))
        self.assert_closed(ledger, eng, 8, 'failure', 'availability', 'permission_denied')

    def test_settled_stop_keeps_operator_cancellation(self):
        locator, path = self.native('n9-stop')
        self.seam.add(path, v4_record(exit_code=None))
        ledger = InertLedger([attempt_row(9, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 9, 'T', 'P', PROFILE, locator, {}),
                             native_result(outcome(admitted=False, category='interrupted'), stopped=True))
        self.assert_closed(ledger, eng, 9, 'cancelled', 'operator', 'stop')

    def test_settled_clean_success_reaches_the_existing_implementation_path(self):
        locator, path = self.native('n10-clean')
        record = v4_record([GONE])
        self.assertTrue(process.escaped_settled(record))
        self.seam.add(path, record)
        view = self.task_view(kind='investigation')
        ledger = InertLedger([attempt_row(10, 'implement', locator)], view, [self.worktree_effect(view)])
        eng = self.engine_for(ledger)
        eng._complete_native(engine.Job('implement', 10, 'T', 'P', PROFILE, locator, {}),
                             native_result(outcome()))
        self.assertTrue(eng.queries.calls, 'the settled success never reached the implementation path')
        self.assert_closed(ledger, eng, 10, 'success', None, None, result=BASE)

    # ---- check completion ----------------------------------------------------------------

    def test_check_with_live_child_is_held_without_a_check_record(self):
        path = self.check_path('c11')
        self.seam.add(path, v4_record([LIVE]))
        ledger = InertLedger([attempt_row(11, 'check', path, kind='check')], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_check(engine.Job('check', 11, 'T', 'P', None, str(self.root), {'name': 'alpha'}),
                            SimpleNamespace(status='INCOMPLETE', reasons=('process-record-not-clean',)))
        self.assert_held(ledger, eng, 11)

    def test_settled_check_incomplete_still_closes_and_records(self):
        path = self.check_path('c12')
        self.seam.add(path, v4_record(exit_code=None))
        ledger = InertLedger([attempt_row(12, 'check', path, kind='check')], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_check(engine.Job('check', 12, 'T', 'P', None, str(self.root), {'name': 'alpha'}),
                            SimpleNamespace(status='INCOMPLETE', reasons=('process-timeout',)))
        self.assert_closed(ledger, eng, 12, 'failure', 'execution', 'timeout')
        self.assertEqual([call for call in ledger.calls if call[0] == 'check_outcome'],
                         [('check_outcome', 'T', 'alpha', 'INCOMPLETE', 'gate-1', None, 12)])

    # ---- unreleased (release-denied) check completion ------------------------------------

    def unreleased_check(self, attempt_id, name, control='running'):
        """A launched check attempt whose release was never authorized, ready for the real
        _complete_check: (process path, ledger, engine, job)."""
        path = self.check_path(name)
        ledger = InertLedger([attempt_row(attempt_id, 'check', path, kind='check', released=False)],
                             self.task_view())
        ledger.control = lambda: control
        job = engine.Job('check', attempt_id, 'T', 'P', None, str(self.root), {'name': 'alpha'})
        return path, ledger, self.engine_for(ledger), job

    def assert_unreleased_held(self, path, ledger, eng, job, outcome_value, gap):
        """The real gate names ``gap`` for the fixture, and the real _complete_check then
        reads that lifecycle and holds the attempt instead of cancelling it, repeatedly."""
        self.assertEqual(engine._lifecycle_gap('check', path), gap, 'fixture: not the intended gap')
        del self.seam.reads[:]
        for _ in range(3):
            eng._complete_check(job, outcome_value)
        self.assertIn(path, self.seam.reads, 'the unreleased launch was closed without reading its lifecycle')
        self.assert_held(ledger, eng, job.attempt_id)
        finishes = [call for call in ledger.calls if call[0] == 'finish']
        self.assertEqual(finishes, [('finish', job.attempt_id, 'unknown', False, None, None, None)])

    def test_unreleased_check_awaiting_release_is_held_not_cancelled(self):
        path, ledger, eng, job = self.unreleased_check(21, 'c21')
        self.seam.add(path, state='awaiting-release')  # abort returned; the bootstrap has not exited
        self.assert_unreleased_held(path, ledger, eng, job, DENIED, 'lifecycle-awaiting-release')

    def test_unreleased_check_with_unknown_lifecycle_is_held_after_failed_supervision(self):
        path, ledger, eng, job = self.unreleased_check(22, 'c22')
        self.seam.add(path, state='unknown')
        self.assert_unreleased_held(path, ledger, eng, job, None, 'lifecycle-unknown')

    def test_unreleased_check_with_unreadable_lifecycle_is_held(self):
        path, ledger, eng, job = self.unreleased_check(23, 'c23')  # the seam has no record: read_status raises
        self.assert_unreleased_held(path, ledger, eng, job, DENIED, 'lifecycle-unreadable (attempt-not-found)')

    def test_unreleased_check_awaiting_release_under_stop_is_held_not_stop_cancelled(self):
        path, ledger, eng, job = self.unreleased_check(24, 'c24', control='stopped')
        self.seam.add(path, state='awaiting-release')
        self.assert_unreleased_held(path, ledger, eng, job, DENIED, 'lifecycle-awaiting-release')

    def test_unreleased_check_finalized_not_launched_keeps_cancellation(self):
        path, ledger, eng, job = self.unreleased_check(25, 'c25')
        self.seam.add(path, v4_record(termination='not-launched', exit_code=None, group_empty=None))
        self.assertIsNone(engine._lifecycle_gap('check', path), 'fixture: a finalized not-launched record')
        del self.seam.reads[:]
        eng._complete_check(job, DENIED)
        self.assertIn(path, self.seam.reads, 'the cancellation did not pass the settlement gate')
        self.assert_closed(ledger, eng, 25, 'cancelled', 'operator', 'cancelled')
        self.assertEqual([call for call in ledger.calls if call[0] == 'check_outcome'], [])

    def test_unreleased_check_proven_not_launched_under_stop_keeps_stop_cancellation(self):
        path, ledger, eng, job = self.unreleased_check(26, 'c26', control='stopped')
        self.seam.add(path, state='not-launched')  # bootstrap exited unlaunched, not yet finalized
        self.assertIsNone(engine._lifecycle_gap('check', path), 'fixture: a proven never-launched attempt')
        eng._complete_check(job, DENIED)
        self.assert_closed(ledger, eng, 26, 'cancelled', 'operator', 'stop')
        self.assertEqual([call for call in ledger.calls if call[0] == 'check_outcome'], [])

    # ---- recovered and adopted completion ------------------------------------------------

    def test_recovered_native_with_live_child_stays_unknown_across_recovery(self):
        locator, path = self.native('n13-recovered')
        self.seam.add(path, v4_record([LIVE]))
        ledger = InertLedger([attempt_row(13, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        for _ in range(3):
            eng._reconcile_attempt(ledger.owned_work()['attempts'][0], True)
        self.assert_held(ledger, eng, 13)
        self.assertEqual(len([call for call in ledger.calls if call[0] == 'finish']), 1)

    def test_adopted_completion_with_live_child_is_held(self):
        locator, path = self.native('n14-adopted')
        self.seam.add(path, v4_record([UNKNOWN]))
        ledger = InertLedger([attempt_row(14, 'implement', locator)], self.task_view())
        eng = self.engine_for(ledger)
        eng._complete_adopted(engine.Job('adopted', 14, 'T', None, None, locator, {'role': 'implement'}),
                              native_result(outcome()))
        self.assert_held(ledger, eng, 14)

    def test_recovered_settled_attempt_closes_as_before(self):
        path = self.check_path('c15')
        self.seam.add(path, v4_record())
        ledger = InertLedger([attempt_row(15, 'check', path, kind='check')], self.task_view())
        eng = self.engine_for(ledger)
        eng._reconcile_attempt(ledger.owned_work()['attempts'][0], False)
        self.assert_closed(ledger, eng, 15, 'failure', 'execution', 'lost')

    def test_never_launched_attempts_keep_safe_cancellation(self):
        reserved = attempt_row(16, 'implement', None, state='reserved', released=False)
        path = self.check_path('c17')
        self.seam.add(path, v4_record(termination='not-launched', exit_code=None, group_empty=None))
        aborted = attempt_row(17, 'check', path, kind='check', released=False)
        ledger = InertLedger([reserved, aborted], self.task_view())
        eng = self.engine_for(ledger)
        for row in ledger.owned_work()['attempts']:
            eng._reconcile_attempt(row, False)
        for attempt_id in (16, 17):
            self.assertEqual(ledger.attempts[attempt_id]['state'], 'finished')
            self.assertEqual([call[2:6] for call in ledger.calls if call[1] == attempt_id],
                             [('cancelled', True, 'execution', 'interrupted')])
        self.assertEqual((eng.task_holds, eng.holds), ({}, {}))


class RealLifecycleSettlement(unittest.TestCase):
    """The gate against real controller_process records: no seam, nothing long-lived."""

    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix='ctl-settle-')))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.attempts, self.work = self.root / 'attempts', self.root / 'work'
        self.attempts.mkdir(mode=0o700)
        self.work.mkdir(mode=0o700)
        (self.root / 'bin').mkdir(mode=0o700)
        self.script = self.root / 'bin' / 'ok.sh'
        self.script.write_text(SCRIPT)
        self.script.chmod(0o700)

    def prepare(self, name):
        spec = process.CommandSpec((str(self.script),), str(self.work), b'', name)
        return process.prepare(str(self.attempts), spec, 30.0)

    def test_real_clean_finalized_command_is_settled_although_not_relaunch_safe(self):
        path = self.prepare('clean1')
        pending = process.spawn(path)
        settled = False
        try:
            owned = pending.release()
            deadline = time.monotonic() + SETTLE_SECONDS
            while owned.poll().state not in process.FINALIZABLE_STATES:
                self.assertLess(time.monotonic(), deadline, 'the exit-0 command did not settle')
                time.sleep(0.05)
            record = owned.finalize()
            settled = True
        finally:
            if not settled:
                with contextlib.suppress(process.ProcessError):
                    process.request_stop(path)  # the helper's own durable STOP; no pid is signalled
        status = process.read_status(path)
        self.assertEqual((status['state'], status['record']), ('finalized', record))
        self.assertIs(record['executionSuccess'], True, f"fixture: not a clean run {record['reasons']}")
        self.assertIs(status['relaunchSafe'], False, 'relaunchSafe is not a quiescence flag')
        self.assertIsNone(engine._lifecycle_gap('check', str(path)))

    def test_real_never_launched_attempt_is_settled_before_and_after_finalize(self):
        path = self.prepare('aborted1')
        process.spawn(path).abort()  # closes the release channel; the bootstrap exits unlaunched
        deadline = time.monotonic() + SETTLE_SECONDS
        while process.recover(path).state != 'not-launched':
            self.assertLess(time.monotonic(), deadline, 'fixture: the aborted attempt is not proven unlaunched')
            time.sleep(0.05)
        self.assertIsNone(engine._lifecycle_gap('check', str(path)))
        record = process.finalize(path)
        self.assertEqual(record['termination'], 'not-launched')
        self.assertIsNone(engine._lifecycle_gap('check', str(path)))


if __name__ == '__main__':
    unittest.main()
