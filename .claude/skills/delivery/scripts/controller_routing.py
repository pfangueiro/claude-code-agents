"""Pure account-routing normalization and decisions for the delivery controller.

No IO, clock, credential probe or provider execution: every time is supplied by the
engine and every fact comes from a typed input.

    observation = observation_from_outcome('claude', outcome.category,
                                           outcome.quota_snapshots, captured_at, ended_at)
    if observation_supersedes(latest_admitted, observation):  # evidence order: ended_at
        ledger.observe(profile_id, observation)        # flat scalars, well under 4096 bytes
    decision = choose_profile(policy, 'review', {profile_id: observation, ...},
                              ledger.owned_work()['attempts'], now)
    # decision.profile_id | None, decision.reason, decision.wait_until, decision.considered

Contract
- ``category`` is the trusted native parser category. Anything else becomes ``unknown``.
- ``ended_at`` (actual attempt end) and ``captured_at`` (when the engine captured the
  outcome) are epoch seconds with ``ended_at <= captured_at``; violations raise ValueError.
- Quota is read only from Claude ``rate_limit_event`` provenance records. The record with
  the highest ``eventIndex`` is the latest and an older record is never a fallback: a
  latest record without a valid status leaves quota unknown, so a success is ``unknown``
  rather than ``available``. Malformed, foreign or marker entries are counted in
  ``quota_ignored`` and otherwise ignored.
- A valid explicit reset is kept even when it passed before ``ended_at`` (it elapsed
  during the attempt). ``choose_profile`` then reports ``probe_due``: one bounded probe,
  never observed available. A future reset still waits.
- Evidence order is ``ended_at``, never ``captured_at`` or arrival order.
  ``observation_supersedes(current, candidate)`` is the pure admission rule for a
  profile's latest observation: an invalid or older candidate never replaces the current
  one; an equal ``ended_at`` replaces only with a more restrictive availability; an auth
  or permission hold is replaced only by a hold at the same or a newer time, or by
  ``observation_from_operator_refresh`` at a strictly newer time -- never by an ordinary
  outcome, however late it ends or arrives.
- ``observations`` maps profile id -> the admitted latest observation of that profile.
  ``choose_profile`` reads only this mapping; it keeps no store and reads no ledger.
- ``active_attempts`` holds one mapping per unresolved attempt: ``id`` (int),
  ``profile_id``, ``role`` and ``state`` (reserved | launched | unknown). An entry that is
  not provably resolved counts toward ``max_parallel`` even when it is malformed.

Decision reasons: observed_available, probe_unknown, waiting_rate_limited,
waiting_cooldown, waiting_rate_limited_unbounded, waiting_cooldown_unbounded, auth_hold,
permission_hold, capacity, execution_disabled, no_profile_for_role, invalid_policy,
invalid_role, invalid_now.

Limits
- A returned profile is a candidate only. The ledger claim stays the authority for
  capacity, the review reserve, budgets and scopes. Only the hard ``max_parallel`` cap is
  mirrored here, and a profile is never treated as a single session.
- This module picks a profile, not a session, and proves no reviewer independence.
- Unknown utilization or reset is never zero or a guessed time. A rejected quota without
  a valid explicit reset waits until a newer observation arrives.
- Auth and permission holds clear only through ``observation_from_operator_refresh`` at a
  strictly newer ``ended_at``. This module sees two observations, not history or arrival
  order: the ledger must apply ``observation_supersedes`` when it admits an observation.
- ``probe_unknown`` means the next real bounded task is the probe; nothing is checked here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

SCHEMA = 'sdlc-controller/routing-observation/v1'
PROVIDERS = ('claude', 'codex')
ROLES = ('implement', 'review')
ACTIVE_STATES = ('reserved', 'launched', 'unknown')
# Native parser categories as inspected, plus transport/outage names and a safe unknown.
CATEGORIES = frozenset({'success', 'permission_denied', 'rate_limited', 'auth_required',
                        'unavailable', 'interrupted', 'incomplete', 'failed',
                        'outage', 'transport', 'unknown'})
TRANSIENT_CATEGORIES = frozenset({'unavailable', 'outage', 'transport'})
HOLDS = {'auth_required': 'auth_hold', 'permission_denied': 'permission_hold'}
HOLD_STATES = tuple(HOLDS.values())
QUOTA_PROVIDER, QUOTA_EVENT, QUOTA_REJECTED = 'claude', 'rate_limit_event', 'rejected'
# Fixed retry delay after a transient outage, counted from the actual attempt end. It is
# a documented backoff, not a claim about any quota reset.
TRANSIENT_BACKOFF_SECONDS = 300
MAX_EPOCH = 253402300799  # 9999-12-31T23:59:59Z; larger values are not epoch seconds
MAX_EXACT_INT = 2 ** 53
# Usable states by preference: observed available first, then work-conserving unknowns.
TIERS = {'available': 0, 'unobserved': 1, 'unknown': 1, 'probe_due': 1}
_ENUM = re.compile(r'[a-z][a-z0-9_]{0,63}')
_SESSION = re.compile(r'[0-9A-Fa-f-]{1,64}')
_QUOTA_KEYS = ('quota_status', 'quota_type', 'quota_reset_at', 'overage_status',
               'using_overage', 'quota_utilization', 'quota_utilization_window',
               'quota_event_index', 'quota_session_id', 'quota_invalid_fields')
SOURCES = ('outcome', 'operator_refresh')
# Availability restrictiveness, used only to break an equal-``ended_at`` tie on admission.
SEVERITY = {'available': 0, 'unknown': 1, 'cooldown': 2, 'rate_limited': 3,
            'auth_hold': 4, 'permission_hold': 4}


@dataclass(frozen=True)
class RoutingDecision:
    """``considered`` rows are (profile_id, state, active_load, wait_until) in owner order."""
    profile_id: str | None
    reason: str
    wait_until: int | float | None
    considered: tuple[tuple[str, str, int, int | float | None], ...]


def _number(value: Any) -> bool:
    """A finite number. Booleans and integers beyond exact float range are rejected."""
    if type(value) is int:
        return -MAX_EXACT_INT <= value <= MAX_EXACT_INT
    return type(value) is float and math.isfinite(value)


def _epoch(value: Any) -> bool:
    return _number(value) and 0 < value <= MAX_EPOCH


def _match(value: Any, pattern: re.Pattern) -> str | None:
    """Short enum- or id-shaped native text only; free text is never echoed."""
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _trusted_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict):
        return False
    index, session = snapshot.get('eventIndex'), snapshot.get('sessionId')
    info, invalid = snapshot.get('rate_limit_info'), snapshot.get('invalidFields')
    return (snapshot.get('provider') == QUOTA_PROVIDER and snapshot.get('eventType') == QUOTA_EVENT
            and type(index) is int and 0 <= index <= MAX_EXACT_INT
            and (session is None or isinstance(session, str))
            and (info is None or isinstance(info, dict))
            and isinstance(invalid, list) and all(isinstance(name, str) for name in invalid))


def _quota_fields(provider: str, snapshots: Any) -> tuple[dict[str, Any], Any]:
    """Flat fields of the latest trusted snapshot, and the retry bound it supports.

    The bound is the latest valid explicit reset among the main limit and the windows that
    are themselves rejected, and only when the main status is rejected. A reset that has
    already passed, including one that passed during the attempt, is still a known reset."""
    if snapshots is None:
        entries: Any = ()
    else:
        entries = snapshots if isinstance(snapshots, (list, tuple)) else (None,)
    trusted = [entry for entry in entries if provider == QUOTA_PROVIDER and _trusted_snapshot(entry)]
    fields: dict[str, Any] = dict.fromkeys(_QUOTA_KEYS)
    fields.update(quota_seen=len(trusted), quota_ignored=len(entries) - len(trusted))
    if not trusted:
        return fields, None
    latest = max(trusted, key=lambda entry: entry['eventIndex'])
    info = latest['rate_limit_info'] or {}
    raw_windows = info.get('unifiedWindows')
    windows = ([(name, window) for name, window in raw_windows.items() if isinstance(window, dict)]
               if isinstance(raw_windows, dict) else [])
    status, main_reset, overage = _match(info.get('status'), _ENUM), info.get('resetsAt'), info.get('isUsingOverage')
    resets = [main_reset] + [window.get('resetsAt') for _, window in windows
                             if window.get('status') == QUOTA_REJECTED]
    resets = [reset for reset in resets if _epoch(reset)]
    known = [(window['utilization'], name) for name, window in windows
             if _number(window.get('utilization')) and window['utilization'] >= 0]
    utilization, window_name = max(known, key=lambda item: item[0]) if known else (None, None)
    fields.update(
        quota_status=status, quota_type=_match(info.get('rateLimitType'), _ENUM),
        quota_reset_at=main_reset if _epoch(main_reset) else None,
        overage_status=_match(info.get('overageStatus'), _ENUM),
        using_overage=overage if type(overage) is bool else None,
        quota_utilization=utilization, quota_utilization_window=_match(window_name, _ENUM),
        quota_event_index=latest['eventIndex'],
        quota_session_id=_match(latest['sessionId'], _SESSION),
        quota_invalid_fields=len(latest['invalidFields']))
    return fields, (max(resets) if status == QUOTA_REJECTED and resets else None)


def _base(source: str, provider: Any, captured_at: Any, ended_at: Any) -> dict[str, Any]:
    if not (isinstance(provider, str) and provider in PROVIDERS):
        raise ValueError('provider must be one of ' + ', '.join(PROVIDERS))
    if not (_epoch(ended_at) and _epoch(captured_at) and ended_at <= captured_at):
        raise ValueError('ended_at and captured_at must be finite epoch seconds, ended_at <= captured_at')
    return {'schema': SCHEMA, 'source': source, 'provider': provider, 'category': 'unknown',
            'availability': 'unknown', 'captured_at': captured_at, 'ended_at': ended_at,
            'retry_at': None, 'retry_basis': None}


def observation_from_outcome(provider: str, category: Any, quota_snapshots: Any,
                             captured_at: int | float, ended_at: int | float) -> dict[str, Any]:
    """Flat scalar metadata for ``Ledger.observe``.

    ``category`` records what executed and is never rewritten: a success followed by a
    rejected main quota status stays ``success`` with availability ``rate_limited`` for
    the next attempt. A rejected overage with an allowed main status is not exhaustion. A
    latest trusted quota record without a valid status leaves a success ``unknown``."""
    observation = _base('outcome', provider, captured_at, ended_at)
    if isinstance(category, str) and category in CATEGORIES:
        observation['category'] = category
    category = observation['category']
    quota, reset = _quota_fields(provider, quota_snapshots)
    is_quota_unknown = quota['quota_seen'] > 0 and quota['quota_status'] is None
    if category in HOLDS:
        observation['availability'] = HOLDS[category]
    elif quota['quota_status'] == QUOTA_REJECTED or category == 'rate_limited':
        observation.update(availability='rate_limited', retry_at=reset,
                           retry_basis=None if reset is None else 'quota_reset')
    elif category in TRANSIENT_CATEGORIES:
        observation.update(availability='cooldown', retry_at=ended_at + TRANSIENT_BACKOFF_SECONDS,
                           retry_basis='fixed_backoff')
    elif category == 'success' and not is_quota_unknown:
        observation['availability'] = 'available'
    observation.update(quota)
    return observation


def observation_from_operator_refresh(provider: str, refreshed_at: int | float) -> dict[str, Any]:
    """The explicit newer observation an operator records after renewing access. It claims
    nothing: availability is ``unknown``, so the next real task is the probe."""
    return _base('operator_refresh', provider, refreshed_at, refreshed_at)


def _admissible(observation: Any) -> bool:
    if not isinstance(observation, dict):
        return False
    source, availability = observation.get('source'), observation.get('availability')
    ended, captured = observation.get('ended_at'), observation.get('captured_at')
    return (observation.get('schema') == SCHEMA and isinstance(source, str) and source in SOURCES
            and isinstance(observation.get('provider'), str) and observation['provider'] in PROVIDERS
            and isinstance(availability, str) and availability in SEVERITY
            and _epoch(ended) and _epoch(captured) and ended <= captured)


def observation_supersedes(current: Any, candidate: Any) -> bool:
    """True when ``candidate`` should become the profile's admitted latest observation.

    Pure rule for the ledger's admission step; it never raises. Evidence order is
    ``ended_at``. An invalid candidate never wins and an invalid or absent ``current`` is
    always replaced. A provider mismatch is refused. A hold is replaced only by a hold at
    the same or a newer time, or by an operator refresh at a strictly newer time."""
    if not _admissible(candidate):
        return False
    if not _admissible(current):
        return True
    if candidate['provider'] != current['provider']:
        return False
    held, ended, newer = current['availability'], current['ended_at'], candidate['ended_at']
    if held in HOLD_STATES:
        if candidate['availability'] in HOLD_STATES:
            return newer >= ended
        return candidate['source'] == 'operator_refresh' and newer > ended
    if newer != ended:
        return newer > ended
    return SEVERITY[candidate['availability']] > SEVERITY[held]


def _policy_profiles(policy: Any) -> list[tuple[str, str, tuple]] | None:
    """(id, provider, roles) in owner order, or None when the policy is not usable."""
    if not isinstance(policy, dict):
        return None
    profiles, cap = policy.get('profiles'), policy.get('max_parallel')
    if not (isinstance(profiles, (list, tuple)) and profiles and type(cap) is int and cap >= 1
            and type(policy.get('auto_route')) is bool
            and type(policy.get('execution_enabled')) is bool):
        return None
    rows = []
    for profile in profiles:
        if not (isinstance(profile, dict) and isinstance(profile.get('id'), str)
                and profile.get('provider') in PROVIDERS
                and isinstance(profile.get('roles'), (list, tuple))):
            return None
        rows.append((profile['id'], profile['provider'], tuple(profile['roles'])))
    return rows if len({row[0] for row in rows}) == len(rows) else None


def _active_load(active_attempts: Any, allowed: set[str]) -> tuple[int, dict[str, int]]:
    """(sessions counted toward the global cap, per-profile load). Fail closed: only a
    mapping whose ``state`` is a string outside ACTIVE_STATES is treated as resolved."""
    if active_attempts is None:
        entries: Any = ()
    else:
        entries = active_attempts if isinstance(active_attempts, (list, tuple)) else (None,)
    total, load = 0, dict.fromkeys(allowed, 0)
    for entry in entries:
        state = entry.get('state') if isinstance(entry, dict) else None
        if isinstance(state, str) and state not in ACTIVE_STATES:
            continue
        total += 1
        if state is None or type(entry.get('id')) is not int or entry.get('role') not in ROLES:
            continue
        profile_id = entry.get('profile_id')
        if isinstance(profile_id, str) and profile_id in allowed:
            load[profile_id] += 1
    return total, load


def _profile_state(provider: str, observation: Any, now: int | float) -> tuple:
    """(state, wait_until, utilization, last_ended) of one profile at ``now``."""
    if not (isinstance(observation, dict) and observation.get('schema') == SCHEMA
            and observation.get('provider') == provider):
        return 'unobserved', None, None, None
    availability, ended = observation.get('availability'), observation.get('ended_at')
    ended = ended if _epoch(ended) else None
    if availability in HOLD_STATES:
        return availability, None, None, ended
    if availability == 'available':
        utilization = observation.get('quota_utilization')
        return 'available', None, utilization if _number(utilization) and utilization >= 0 else None, ended
    if availability == 'unknown':
        return 'unknown', None, None, ended
    if availability == 'rate_limited':
        retry = observation.get('retry_at')
    elif availability == 'cooldown':
        retry = None if ended is None else ended + TRANSIENT_BACKOFF_SECONDS
    else:
        return 'unobserved', None, None, None
    if not _epoch(retry):
        return availability, None, None, ended
    if now >= retry:
        return 'probe_due', None, None, ended
    return availability, retry, None, ended


def _rank(usable: list[tuple]) -> tuple:
    """Best tier, then lowest active load. Observed-available ties use utilization only
    when every tied profile reports one; unknown ties probe the least recently observed.
    Remaining ties keep owner order."""
    tier = min(TIERS[row[1]] for row in usable)
    pool = [row for row in usable if TIERS[row[1]] == tier]
    least = min(row[2] for row in pool)
    pool = [row for row in pool if row[2] == least]
    if tier and len(pool) > 1:
        pool.sort(key=lambda row: -math.inf if row[5] is None else row[5])
    elif all(row[4] is not None for row in pool):
        pool.sort(key=lambda row: row[4])
    return pool[0]


def _blocked(rows: list[tuple], considered: tuple) -> RoutingDecision:
    timed = [(row[3], row[1]) for row in rows if row[3] is not None]
    if timed:
        wait_until, state = min(timed, key=lambda item: item[0])
        return RoutingDecision(None, 'waiting_' + state, wait_until, considered)
    states = [row[1] for row in rows]
    for state in ('rate_limited', 'cooldown'):
        if state in states:
            return RoutingDecision(None, f'waiting_{state}_unbounded', None, considered)
    return RoutingDecision(None, next(state for state in states if state in HOLD_STATES), None, considered)


def choose_profile(policy: Any, role: Any, observations: Any, active_attempts: Any,
                   now: Any) -> RoutingDecision:
    """Choose an allowlisted profile for ``role`` at ``now``. Never raises and takes no
    action. With ``auto_route`` false only the first owner-ordered profile allowed the role
    is evaluated; a blocked pin is reported, never silently replaced."""
    profiles = _policy_profiles(policy)
    if profiles is None:
        return RoutingDecision(None, 'invalid_policy', None, ())
    if not (isinstance(role, str) and role in ROLES):
        return RoutingDecision(None, 'invalid_role', None, ())
    if not _epoch(now):
        return RoutingDecision(None, 'invalid_now', None, ())
    observed = observations if isinstance(observations, dict) else {}
    total, load = _active_load(active_attempts, {row[0] for row in profiles})
    rows, skipped = [], []
    for profile_id, provider, roles in profiles:
        if role not in roles:
            continue
        if rows and not policy['auto_route']:
            skipped.append((profile_id, 'skipped_auto_route_off', load[profile_id], None))
            continue
        state, wait_until, utilization, ended = _profile_state(provider, observed.get(profile_id), now)
        rows.append((profile_id, state, load[profile_id], wait_until, utilization, ended))
    considered = tuple(row[:4] for row in rows) + tuple(skipped)
    if not rows:
        return RoutingDecision(None, 'no_profile_for_role', None, considered)
    if not policy['execution_enabled']:
        return RoutingDecision(None, 'execution_disabled', None, considered)
    if total >= policy['max_parallel']:
        return RoutingDecision(None, 'capacity', None, considered)
    usable = [row for row in rows if row[1] in TIERS]
    if not usable:
        return _blocked(rows, considered)
    choice = _rank(usable)
    reason = 'probe_unknown' if TIERS[choice[1]] else 'observed_available'
    return RoutingDecision(choice[0], reason, None, considered)
