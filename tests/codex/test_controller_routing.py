"""Offline tests for the pure account-routing module. No IO, clock, provider or network:
every time is an explicit number and every quota record is a literal in native shape."""
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.claude' / 'skills' / 'delivery' / 'scripts'))
import controller_routing as cr  # noqa: E402

T0 = 1_800_000_000
NOW = T0 + 100
BOTH = ('implement', 'review')
SESSION = '0f8fad5b-d9cb-469f-a165-70867728950e'
SECRET = 'sk-ant-api03-' + 'A' * 40


def policy(profiles, auto=True, cap=4, execution=True):
    return {'profiles': [{'id': profile_id, 'provider': 'claude', 'executable': 'claude',
                          'config_dir': '/accounts/' + profile_id, 'roles': list(roles)}
                         for profile_id, roles in profiles],
            'auto_route': auto, 'execution_enabled': execution, 'max_parallel': cap,
            'review_reserve': 0}


def snap(index, status=None, windows=None, **info):
    body = {'status': status, 'resetsAt': None, 'rateLimitType': None, 'overageStatus': None,
            'overageDisabledReason': None, 'isUsingOverage': None, 'unifiedWindows': windows}
    body.update(info)
    return {'provider': 'claude', 'eventType': 'rate_limit_event', 'eventIndex': index,
            'sessionId': SESSION, 'rate_limit_info': body, 'invalidFields': []}


def native_rejection(index, reset):
    """A typed main-limit rejection in the native provenance shape."""
    windows = {'five_hour': {'utilization': 1.0, 'resetsAt': reset, 'status': 'rejected'},
               'seven_day': {'utilization': 0.4, 'resetsAt': T0 + 9000, 'status': 'allowed'}}
    return snap(index, 'rejected', windows, resetsAt=reset, rateLimitType='five_hour',
                overageStatus='rejected', isUsingOverage=False)


def obs(category='success', snaps=(), ended=T0, provider='claude'):
    return cr.observation_from_outcome(provider, category, list(snaps), ended + 1, ended)


def attempt(attempt_id, profile_id, role='implement', state='launched'):
    return {'id': attempt_id, 'profile_id': profile_id, 'role': role, 'state': state}


def states(decision):
    return {row[0]: row[1] for row in decision.considered}


class ObservationTests(unittest.TestCase):
    def assert_ledger_shaped(self, data):
        self.assertIsInstance(data, dict)
        for key, value in data.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, (str, int, float, bool, type(None)))
            self.assertFalse(type(value) is float and not math.isfinite(value))
        encoded = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False)
        self.assertLessEqual(len(encoded.encode('utf-8')), 4096)
        return encoded

    def test_success_without_quota_is_available_and_quota_stays_unknown(self):
        data = obs()
        self.assert_ledger_shaped(data)
        self.assertEqual((data['category'], data['availability']), ('success', 'available'))
        for key in ('quota_status', 'quota_reset_at', 'quota_utilization', 'retry_at'):
            self.assertIsNone(data[key])
        self.assertEqual((data['quota_seen'], data['quota_ignored']), (0, 0))

    def test_overage_rejected_with_main_allowed_is_not_exhausted(self):
        data = obs(snaps=[snap(1, 'allowed', overageStatus='rejected', isUsingOverage=False)])
        self.assertEqual(data['availability'], 'available')
        self.assertEqual((data['overage_status'], data['using_overage']), ('rejected', False))
        rejected = obs(snaps=[snap(1, 'rejected', overageStatus='allowed', resetsAt=T0 + 60)])
        self.assertEqual(rejected['availability'], 'rate_limited')

    def test_success_then_rejected_keeps_category_and_limits_next_attempt(self):
        data = obs(snaps=[snap(4, 'rejected', resetsAt=T0 + 3600, rateLimitType='five_hour')])
        self.assertEqual((data['category'], data['availability']), ('success', 'rate_limited'))
        self.assertEqual((data['retry_at'], data['retry_basis']), (T0 + 3600, 'quota_reset'))
        self.assertEqual((data['quota_event_index'], data['quota_session_id'], data['quota_type']),
                         (4, SESSION, 'five_hour'))

    def test_latest_event_index_wins_in_any_list_order(self):
        older_allowed = [snap(7, 'rejected', resetsAt=T0 + 60), snap(3, 'allowed')]
        self.assertEqual(obs(snaps=older_allowed)['availability'], 'rate_limited')
        older_rejected = [snap(7, 'allowed'), snap(3, 'rejected', resetsAt=T0 + 60)]
        data = obs(snaps=older_rejected)
        self.assertEqual((data['availability'], data['quota_event_index']), ('available', 7))

    def test_retry_uses_latest_reset_of_rejected_windows_only(self):
        windows = {'five_hour': {'utilization': 1.0, 'resetsAt': T0 + 500, 'status': 'rejected'},
                   'seven_day': {'utilization': 0.4, 'resetsAt': T0 + 9000, 'status': 'allowed'}}
        data = obs(snaps=[snap(1, 'rejected', windows, resetsAt=T0 + 100)])
        self.assertEqual((data['retry_at'], data['quota_reset_at']), (T0 + 500, T0 + 100))
        self.assertEqual((data['quota_utilization'], data['quota_utilization_window']), (1.0, 'five_hour'))

    def test_unknown_or_invalid_reset_is_never_guessed(self):
        for bad in (None, 10 ** 18, 10 ** 400, -(10 ** 400), True, False, 0, -1, float('inf'),
                    float('-inf'), float('nan'), 'soon', [T0 + 60], {'at': T0 + 60}):
            data = obs(category='rate_limited', snaps=[snap(1, 'rejected', resetsAt=bad)])
            self.assert_ledger_shaped(data)
            self.assertEqual((data['availability'], data['retry_at'], data['retry_basis'],
                              data['quota_reset_at']), ('rate_limited', None, None, None), repr(bad))
        untyped = obs(category='rate_limited')
        self.assertEqual((untyped['availability'], untyped['retry_at']), ('rate_limited', None))

    def test_known_reset_that_passed_during_the_attempt_is_kept(self):
        # A successful attempt ended at T0+60 carrying a main-limit rejection whose explicit
        # reset (T0+20) elapsed while the attempt was still running.
        for reset in (T0 + 20, T0 + 60, T0 - 10 ** 6):
            data = cr.observation_from_outcome('claude', 'success', [snap(2, 'allowed'),
                                                                     native_rejection(5, reset)],
                                               T0 + 61, T0 + 60)
            self.assert_ledger_shaped(data)
            self.assertEqual((data['category'], data['availability'], data['retry_at'],
                              data['retry_basis']), ('success', 'rate_limited', reset, 'quota_reset'))
            self.assertEqual((data['quota_reset_at'], data['quota_event_index'], data['quota_type'],
                              data['quota_utilization_window']), (reset, 5, 'five_hour', 'five_hour'))

    def test_latest_record_without_a_valid_status_leaves_quota_unknown(self):
        for status in (None, 7, True, 'Allowed!', SECRET):
            data = obs(snaps=[snap(3, 'allowed'), snap(8, status)])
            self.assert_ledger_shaped(data)
            self.assertEqual((data['availability'], data['quota_status'], data['quota_event_index']),
                             ('unknown', None, 8), repr(status))
            older_rejected = obs(snaps=[snap(3, 'rejected', resetsAt=T0 + 900), snap(8, status)])
            self.assertEqual((older_rejected['availability'], older_rejected['retry_at']), ('unknown', None))
        limited = obs('rate_limited', [snap(3, 'rejected', resetsAt=T0 + 900), snap(8, None)])
        self.assertEqual((limited['availability'], limited['retry_at']), ('rate_limited', None))

    def test_missing_or_invalid_utilization_is_none_not_zero(self):
        windows = {'five_hour': {'utilization': None, 'resetsAt': None, 'status': 'allowed'},
                   'seven_day': {'utilization': True}, 'opus': {'utilization': -1}, 'junk': 7}
        data = obs(snaps=[snap(1, 'allowed', windows)])
        self.assertIsNone(data['quota_utilization'])
        self.assertIsNone(data['quota_utilization_window'])

    def test_holds_cooldown_and_unknown_categories(self):
        self.assertEqual(obs('auth_required')['availability'], 'auth_hold')
        self.assertEqual(obs('permission_denied')['availability'], 'permission_hold')
        outage = obs('unavailable')
        self.assertEqual((outage['availability'], outage['retry_at'], outage['retry_basis']),
                         ('cooldown', T0 + cr.TRANSIENT_BACKOFF_SECONDS, 'fixed_backoff'))
        for category in ('failed', 'incomplete', 'interrupted'):
            self.assertEqual(obs(category)['availability'], 'unknown')
        for invented in ('quota exhausted, retry in 1h', None, 5, ['success']):
            data = obs(invented)
            self.assertEqual((data['category'], data['availability']), ('unknown', 'unknown'))

    def test_untrusted_snapshots_are_ignored_without_exceptions(self):
        junk = [None, 5, 'rate_limit_event', {'provider': 'codex'}, [snap(1, 'rejected')],
                dict(snap(9, 'rejected'), eventIndex=True),
                dict(snap(9, 'rejected'), eventType='assistant'),
                dict(snap(9, 'rejected'), rate_limit_info='rejected'),
                dict(snap(9, 'rejected'), invalidFields=None),
                {'truncated': True, 'dropped': 12}]
        data = obs(snaps=junk)
        self.assert_ledger_shaped(data)
        self.assertEqual((data['availability'], data['quota_seen'], data['quota_ignored']),
                         ('available', 0, len(junk)))
        not_a_list = cr.observation_from_outcome('claude', 'success', {'status': 'rejected'}, T0, T0)
        self.assertEqual((not_a_list['availability'], not_a_list['quota_ignored']), ('available', 1))
        codex = obs(snaps=[snap(1, 'rejected', resetsAt=T0 + 60)], provider='codex')
        self.assertEqual((codex['availability'], codex['quota_seen']), ('available', 0))
        empty_info = obs(snaps=[dict(snap(2), rate_limit_info=None, invalidFields=['rate_limit_info'])])
        self.assertEqual((empty_info['quota_status'], empty_info['quota_invalid_fields']), (None, 1))

    def test_free_text_and_secret_shapes_are_not_echoed(self):
        hostile = snap(1, SECRET, {SECRET: {'utilization': 0.5, 'status': SECRET}},
                       rateLimitType=SECRET, overageStatus=SECRET, overageDisabledReason=SECRET)
        hostile.update(sessionId=SECRET, note=SECRET)
        encoded = self.assert_ledger_shaped(obs(SECRET, [hostile]))
        self.assertNotIn('sk-ant', encoded)
        self.assertNotIn('A' * 8, encoded)

    def test_times_must_be_finite_ordered_epochs(self):
        for captured, ended in ((T0, T0 + 1), (float('nan'), T0), (T0, float('inf')), (True, True),
                                (T0, 0), (10 ** 400, T0), ('now', T0), (None, None)):
            with self.assertRaises(ValueError):
                cr.observation_from_outcome('claude', 'success', [], captured, ended)
        with self.assertRaises(ValueError):
            cr.observation_from_outcome('gemini', 'success', [], T0, T0)
        with self.assertRaises(ValueError):
            cr.observation_from_operator_refresh('claude', float('nan'))


class ChooseProfileTests(unittest.TestCase):
    def test_one_account_serves_both_roles_up_to_the_global_cap(self):
        solo = policy([('alpha', BOTH)], cap=2)
        first = cr.choose_profile(solo, 'implement', {}, [], NOW)
        self.assertEqual((first.profile_id, first.reason), ('alpha', 'probe_unknown'))
        seen = {'alpha': obs()}
        review = cr.choose_profile(solo, 'review', seen, [attempt(1, 'alpha')], NOW)
        self.assertEqual((review.profile_id, review.reason), ('alpha', 'observed_available'))
        self.assertEqual(review.considered, (('alpha', 'available', 1, None),))
        full = cr.choose_profile(solo, 'review', seen,
                                 [attempt(1, 'alpha'), attempt(2, 'alpha', 'review')], NOW)
        self.assertEqual((full.profile_id, full.reason, full.wait_until), (None, 'capacity', None))

    def test_four_profiles_prefer_lower_load_within_the_role(self):
        four = policy([('alpha', ('implement',)), ('beta', ('implement',)), ('gamma', BOTH),
                       ('delta', ('review',))], cap=8)
        seen = {name: obs() for name in ('alpha', 'beta', 'gamma', 'delta')}
        busy = [attempt(1, 'alpha'), attempt(2, 'alpha'), attempt(3, 'beta'), attempt(4, 'gamma')]
        implement = cr.choose_profile(four, 'implement', seen, busy, NOW)
        self.assertEqual(implement.profile_id, 'beta')
        self.assertEqual([row[0] for row in implement.considered], ['alpha', 'beta', 'gamma'])
        self.assertEqual(cr.choose_profile(four, 'review', seen, busy, NOW).profile_id, 'delta')
        # The review reserve needs task state and stays with the ledger: below the hard cap
        # a candidate is still returned, at the hard cap nothing is.
        reserve = dict(policy([('alpha', BOTH), ('beta', BOTH)], cap=4), review_reserve=1)
        three = [attempt(n, 'alpha') for n in (1, 2, 3)]
        self.assertEqual(cr.choose_profile(reserve, 'implement', {}, three, NOW).profile_id, 'beta')
        self.assertEqual(cr.choose_profile(reserve, 'review', {}, three + [attempt(4, 'beta')], NOW).reason,
                         'capacity')

    def test_active_input_fails_closed_and_ignores_resolved_rows(self):
        solo = policy([('alpha', BOTH)], cap=2)
        malformed = [{'profile_id': 'alpha'}, 'junk']
        self.assertEqual(cr.choose_profile(solo, 'implement', {}, malformed, NOW).reason, 'capacity')
        self.assertEqual(cr.choose_profile(solo, 'implement', {}, 'junk', NOW).considered,
                         (('alpha', 'unobserved', 0, None),))
        resolved = [attempt(1, 'alpha', state='finished'), attempt(2, 'alpha', state='finished')]
        self.assertEqual(cr.choose_profile(solo, 'implement', {}, resolved, NOW).profile_id, 'alpha')
        foreign = [attempt(1, 'ghost'), attempt(2, 'ghost')]
        self.assertEqual(cr.choose_profile(solo, 'implement', {}, foreign, NOW).reason, 'capacity')

    def test_quota_wait_expiry_and_unknown_reset(self):
        solo = policy([('alpha', BOTH)])
        limited = {'alpha': obs(snaps=[snap(1, 'rejected', resetsAt=T0 + 3600)])}
        waiting = cr.choose_profile(solo, 'implement', limited, [], NOW)
        self.assertEqual((waiting.profile_id, waiting.reason, waiting.wait_until),
                         (None, 'waiting_rate_limited', T0 + 3600))
        due = cr.choose_profile(solo, 'implement', limited, [], T0 + 3600)
        self.assertEqual((due.profile_id, due.reason, states(due)), ('alpha', 'probe_unknown', {'alpha': 'probe_due'}))
        unknown = {'alpha': obs('rate_limited', [snap(1, 'rejected', resetsAt=10 ** 18)])}
        for later in (NOW, T0 + 10 ** 8):
            stuck = cr.choose_profile(solo, 'implement', unknown, [], later)
            self.assertEqual((stuck.profile_id, stuck.reason, stuck.wait_until),
                             (None, 'waiting_rate_limited_unbounded', None))

    def test_reset_elapsed_during_attempt_probes_instead_of_waiting_forever(self):
        solo = policy([('alpha', BOTH)])
        passed = cr.observation_from_outcome('claude', 'success', [native_rejection(5, T0 + 20)],
                                             T0 + 61, T0 + 60)
        for later in (T0 + 61, T0 + 10 ** 6):
            due = cr.choose_profile(solo, 'implement', {'alpha': passed}, [], later)
            self.assertEqual((due.profile_id, due.reason, due.wait_until, states(due)),
                             ('alpha', 'probe_unknown', None, {'alpha': 'probe_due'}))
        future = cr.observation_from_outcome('claude', 'success', [native_rejection(5, T0 + 3600)],
                                             T0 + 61, T0 + 60)
        waiting = cr.choose_profile(solo, 'implement', {'alpha': future}, [], T0 + 61)
        self.assertEqual((waiting.profile_id, waiting.reason, waiting.wait_until),
                         (None, 'waiting_rate_limited', T0 + 3600))
        pair = policy([('alpha', BOTH), ('beta', BOTH)])
        known = cr.choose_profile(pair, 'implement', {'alpha': passed, 'beta': obs()}, [], T0 + 61)
        self.assertEqual((known.profile_id, known.reason), ('beta', 'observed_available'))
        invalid = {'alpha': obs(snaps=[snap(3, 'allowed'), snap(8, None)])}
        probe = cr.choose_profile(solo, 'implement', invalid, [], NOW)
        self.assertEqual((probe.reason, states(probe)), ('probe_unknown', {'alpha': 'unknown'}))

    def test_auth_hold_clears_only_with_a_newer_observation(self):
        solo = policy([('alpha', BOTH)])
        for category, reason in (('auth_required', 'auth_hold'), ('permission_denied', 'permission_hold')):
            held = cr.choose_profile(solo, 'implement', {'alpha': obs(category)}, [], T0 + 10 ** 7)
            self.assertEqual((held.profile_id, held.reason, held.wait_until), (None, reason, None))
        refreshed = {'alpha': cr.observation_from_operator_refresh('claude', T0 + 50)}
        retry = cr.choose_profile(solo, 'implement', refreshed, [], NOW)
        self.assertEqual((retry.profile_id, retry.reason), ('alpha', 'probe_unknown'))
        self.assertEqual(cr.choose_profile(solo, 'implement', {'alpha': obs()}, [], NOW).reason,
                         'observed_available')

    def test_outage_cooldown_runs_from_the_actual_end(self):
        solo = policy([('alpha', BOTH)])
        down = {'alpha': obs('unavailable')}
        until = T0 + cr.TRANSIENT_BACKOFF_SECONDS
        waiting = cr.choose_profile(solo, 'implement', down, [], until - 1)
        self.assertEqual((waiting.profile_id, waiting.reason, waiting.wait_until),
                         (None, 'waiting_cooldown', until))
        self.assertEqual(cr.choose_profile(solo, 'implement', down, [], until).profile_id, 'alpha')
        tampered = {'alpha': dict(down['alpha'], retry_at=T0 + 1)}
        self.assertIsNone(cr.choose_profile(solo, 'implement', tampered, [], until - 1).profile_id)

    def test_auto_route_off_pins_and_never_falls_through(self):
        seen = {'alpha': obs(snaps=[snap(1, 'rejected', resetsAt=T0 + 900)]), 'beta': obs()}
        pinned = cr.choose_profile(policy([('alpha', BOTH), ('beta', BOTH)], auto=False),
                                   'implement', seen, [], NOW)
        self.assertEqual((pinned.profile_id, pinned.reason, pinned.wait_until),
                         (None, 'waiting_rate_limited', T0 + 900))
        self.assertEqual(states(pinned), {'alpha': 'rate_limited', 'beta': 'skipped_auto_route_off'})
        routed = cr.choose_profile(policy([('alpha', BOTH), ('beta', BOTH)]), 'implement', seen, [], NOW)
        self.assertEqual((routed.profile_id, routed.reason), ('beta', 'observed_available'))
        review_pin = cr.choose_profile(policy([('alpha', ('implement',)), ('beta', BOTH)], auto=False),
                                       'review', {}, [], NOW)
        self.assertEqual(review_pin.profile_id, 'beta')

    def test_known_available_beats_unknown_and_unknowns_stay_work_conserving(self):
        pair = policy([('alpha', BOTH), ('beta', BOTH)])
        self.assertEqual(cr.choose_profile(pair, 'implement', {'beta': obs()}, [], NOW).profile_id, 'beta')
        busy_known = cr.choose_profile(pair, 'implement', {'beta': obs()}, [attempt(1, 'beta')], NOW)
        self.assertEqual(busy_known.profile_id, 'beta')
        self.assertEqual(cr.choose_profile(pair, 'implement', {'alpha': obs('failed')}, [], NOW).profile_id, 'beta')
        both = {'alpha': obs('failed', ended=T0 + 10), 'beta': obs('failed', ended=T0 - 50)}
        self.assertEqual(cr.choose_profile(pair, 'implement', both, [], NOW).profile_id, 'beta')
        self.assertEqual(cr.choose_profile(pair, 'implement', {}, [], NOW).profile_id, 'alpha')
        mixed = {'alpha': obs('auth_required'), 'beta': obs('unavailable')}
        blocked = cr.choose_profile(pair, 'implement', mixed, [], NOW)
        self.assertEqual((blocked.reason, states(blocked)),
                         ('waiting_cooldown', {'alpha': 'auth_hold', 'beta': 'cooldown'}))

    def test_utilization_orders_only_when_every_tied_profile_reports_it(self):
        pair = policy([('alpha', BOTH), ('beta', BOTH)])

        def used(ratio):
            return obs(snaps=[snap(1, 'allowed', {'five_hour': {'utilization': ratio}})])

        unknown_first = {'alpha': obs(), 'beta': used(0.1)}
        self.assertEqual(cr.choose_profile(pair, 'implement', unknown_first, [], NOW).profile_id, 'alpha')
        known = {'alpha': used(0.9), 'beta': used(0.2)}
        self.assertEqual(cr.choose_profile(pair, 'implement', known, [], NOW).profile_id, 'beta')
        tied = {'alpha': used(0.5), 'beta': used(0.5)}
        self.assertEqual(cr.choose_profile(pair, 'implement', tied, [], NOW).profile_id, 'alpha')

    def test_foreign_and_malformed_observations_are_ignored(self):
        solo = policy([('alpha', BOTH)])
        ghost = {'ghost': obs(), 'alpha ': obs(), 7: obs()}
        decision = cr.choose_profile(solo, 'implement', ghost, [], NOW)
        self.assertEqual((decision.profile_id, decision.reason), ('alpha', 'probe_unknown'))
        self.assertEqual(decision.considered, (('alpha', 'unobserved', 0, None),))
        for junk in (None, 'available', [obs()], {'availability': 'available'},
                     dict(obs(), schema='other/v9'), dict(obs(), provider='codex'),
                     dict(obs(), availability=['available']), dict(obs(), availability=SECRET)):
            decision = cr.choose_profile(solo, 'implement', {'alpha': junk}, [], NOW)
            self.assertEqual(states(decision), {'alpha': 'unobserved'})
            self.assertNotIn('sk-ant', repr(decision))
        garbled = dict(obs('rate_limited'), retry_at='tomorrow', quota_utilization='low')
        self.assertEqual(cr.choose_profile(solo, 'implement', {'alpha': garbled}, [], NOW).reason,
                         'waiting_rate_limited_unbounded')
        self.assertEqual(cr.choose_profile(solo, 'implement', [('alpha', obs())], [], NOW).profile_id, 'alpha')

    def test_roles_execution_and_invalid_inputs_return_reasons(self):
        implement_only = policy([('alpha', ('implement',))])
        missing = cr.choose_profile(implement_only, 'review', {}, [], NOW)
        self.assertEqual((missing.profile_id, missing.reason, missing.considered),
                         (None, 'no_profile_for_role', ()))
        for role in ('deploy', None, ['review'], 3):
            self.assertEqual(cr.choose_profile(implement_only, role, {}, [], NOW).reason, 'invalid_role')
        disabled = cr.choose_profile(policy([('alpha', BOTH)], execution=False), 'implement',
                                     {'alpha': obs()}, [], NOW)
        self.assertEqual((disabled.profile_id, disabled.reason, states(disabled)),
                         (None, 'execution_disabled', {'alpha': 'available'}))
        good = policy([('alpha', BOTH)])
        for bad in (None, [], {}, dict(good, profiles=[]), dict(good, profiles='alpha'),
                    dict(good, auto_route='yes'), dict(good, max_parallel=0),
                    dict(good, max_parallel=True), dict(good, profiles=good['profiles'] * 2),
                    dict(good, profiles=[{'id': 'alpha', 'provider': 'gemini', 'roles': ['review']}])):
            self.assertEqual(cr.choose_profile(bad, 'implement', {}, [], NOW).reason, 'invalid_policy')
        for bad_now in (None, float('nan'), float('inf'), True, -1, 10 ** 400, 'now'):
            self.assertEqual(cr.choose_profile(good, 'implement', {}, [], bad_now).reason, 'invalid_now')

    def test_decision_is_frozen(self):
        decision = cr.choose_profile(policy([('alpha', BOTH)]), 'implement', {}, [], NOW)
        with self.assertRaises(AttributeError):
            decision.profile_id = 'beta'


class AdmissionOrderTests(unittest.TestCase):
    @staticmethod
    def fold(*arrivals):
        latest = None
        for observation in arrivals:
            if cr.observation_supersedes(latest, observation):
                latest = observation
        return latest

    def test_ended_at_orders_evidence_not_capture_time_or_arrival(self):
        delayed = cr.observation_from_outcome('claude', 'rate_limited', [], T0 + 900, T0 + 5)
        later = obs(ended=T0 + 10)
        self.assertIs(self.fold(later, delayed), later)
        self.assertIs(self.fold(delayed, later), later)
        self.assertTrue(cr.observation_supersedes(later, obs('unavailable', ended=T0 + 11)))
        self.assertFalse(cr.observation_supersedes(later, obs(ended=T0 + 10)))
        tied_limit = obs('rate_limited', ended=T0 + 10)
        self.assertIs(self.fold(later, tied_limit), tied_limit)
        self.assertIs(self.fold(tied_limit, later), tied_limit)

    def test_holds_clear_only_through_a_strictly_newer_operator_refresh(self):
        solo = policy([('alpha', BOTH)])
        for category, reason in (('auth_required', 'auth_hold'), ('permission_denied', 'permission_hold')):
            hold = obs(category, ended=T0 + 10)
            # A concurrent attempt that ends after the hold but arrives late must not clear it.
            late_success = cr.observation_from_outcome('claude', 'success', [], T0 + 500, T0 + 20)
            same_time_refresh = cr.observation_from_operator_refresh('claude', T0 + 10)
            latest = self.fold(hold, late_success, obs(ended=T0), same_time_refresh,
                               obs('rate_limited', ended=T0 + 40))
            self.assertIs(latest, hold)
            self.assertEqual(cr.choose_profile(solo, 'implement', {'alpha': latest}, [], NOW).reason, reason)
            refresh = cr.observation_from_operator_refresh('claude', T0 + 30)
            self.assertIs(self.fold(hold, refresh, late_success), refresh)
            self.assertEqual(cr.choose_profile(solo, 'implement', {'alpha': refresh}, [], NOW).reason,
                             'probe_unknown')
        auth, permission = obs('auth_required', ended=T0 + 10), obs('permission_denied', ended=T0 + 40)
        self.assertIs(self.fold(auth, permission), permission)
        self.assertIs(self.fold(permission, auth), permission)

    def test_invalid_candidates_never_win_and_invalid_current_is_replaced(self):
        current = obs(ended=T0 + 10)
        for bad in (None, 'available', [current], dict(current, schema='other/v9'),
                    dict(current, source='ledger'), dict(current, source=['outcome']),
                    dict(current, provider='gemini'), dict(current, availability=['available']),
                    dict(current, availability='bogus'), dict(current, ended_at=float('nan')),
                    dict(current, ended_at=10 ** 400), dict(current, ended_at=T0 + 50, captured_at=T0 + 20),
                    dict(current, captured_at=True)):
            self.assertFalse(cr.observation_supersedes(current, bad), repr(bad)[:80])
            self.assertTrue(cr.observation_supersedes(bad, current), repr(bad)[:80])
        self.assertFalse(cr.observation_supersedes(current, dict(obs(ended=T0 + 20), provider='codex')))


if __name__ == '__main__':
    unittest.main()
