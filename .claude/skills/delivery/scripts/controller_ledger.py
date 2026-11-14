#!/usr/bin/env python3
"""Persistent controller ledger: one SQLite store and one authority per repository.

State lives in a private directory outside the repository (directory 0700, policy
snapshots 0600, ledger 0600). A binding file plus an OS-held flock in the Git common
directory give one controller authority per repository. Fenced writes need a live lease
(the flock still held by this process) AND the matching monotonic fence in the ledger;
an integer fence alone grants nothing. Only boundary-valid, frozen inputs are stored:
the policy, plan and authority are re-validated with controller_inputs.

Context epochs. The frozen policy and the runtime/rules identity form an append-only
context epoch; ``policy``, ``identity`` and ``policy_digest`` always mean the current
one. initialize never reconfigures. A controller that presents another identity (or
none) is held: it can clean up but not claim, bind, release, run effects or accept.
Only reconcile_context appends an epoch, under a persistent STOP with all owned work
resolved. Every plan is bound to the epoch it was admitted under; after a reconcile it
is stale until the owner readmits the unchanged plan with a new declaration.

Execution bindings. plans.base_sha is the immutable owner origin. Each task separately
binds its exact execution base, dependency results and workspace before it can be
claimed. The ledger cannot run Git: the ancestry facts in a binding are a typed
observation made by the fixed engine and are recorded for a later independent Git
check. They are never producer text and are not proof by themselves.

Outcome attribution and budgets. A closed attempt records why it ended with fixed
enumerated values only (ATTRIBUTIONS, REASONS, PROVIDER_CATEGORIES; never free text).
Only a ``semantic`` close (an actual wrong result, check failure or review block) adds to
the task's failure history and no-progress streak and consumes the semantic attempt
budget. Availability (quota, auth, permission, outage), operator (STOP, pause) and
execution (launch failure, timeout, lost) closes are incomplete history, not repository
defects: they requeue or leave the task as it was, keep every row and event and are
charged their time. Every launch is still counted. Per lane (task x native role, or
task x declared check):

    semantic_limit = limits.max_attempts
    dispatch_limit = limits.max_attempts * (1 + L)

where L is the number of configured profiles allowed that role and L = 1 for a local
check. A task is therefore bounded by max_attempts * (2 + P_implement + P_review + 2 * C)
launches for C declared checks, and a plan by the sum over its tasks. The per-plan time
budget applies to every attempt as before.

Checks. A declared check is a real owned local command reserved with claim_check: an
attempt of role ``check`` with no profile, holding the task's declared resources, a
``max_parallel`` slot and plan time until it is settled. A finished check process is not
a verdict: record_check_outcome stores PASS, FAIL or INCOMPLETE for one finished check
attempt of the current result with a closed reference to the v1 receipt. In
finalize_checks a recorded FAIL makes the aggregate FAIL at once, but the result is kept
until every declared check has a row, so the remaining independent results can still be
collected. FAIL means that declared check failed for this result, not a proven cause.

Derived candidates. An accepted task is never published. After the engine confirms the
integration of every accepted task of a plan, create_candidate records one derived
publication candidate: an immutable ``candidates`` row plus an internal task row of kind
``candidate`` (a kind the public plan boundary refuses) bound to the plan origin, so the
existing check, review, acceptance, budget and gate machinery covers origin..result as a
whole. It needs its own run of the union of the declared checks and a fresh review, and
it is never implemented, committed or integrated itself. Currency is derived on every
use and never stored: a newer revision, another context or any changed contributing
state, result, binding or dependency holds it (``candidate_stale``) while every row
stays. push, pr.create and pr.merge are authorized only for a current accepted
candidate. Revisions per plan are bounded by limits.max_attempts and share the plan
time budget; nothing published is rolled back.

Plan workspace and checkpoints. Integration needs a worktree before any task is accepted,
so each plan owns one integration workspace per context epoch (register_plan_workspace):
the plan origin on a controller branch inside the state workspace. It is created and
removed only through plan_effect_intent, journalled as plan-owned effects (``task_id``
NULL, ``owner`` 'plan'); no task or candidate is invented for it. Registration grants
ownership of a name, never acceptance or publication. record_checkpoint appends the
confirmed head of that workspace: first the plan origin after the confirmed creation,
then one compare-and-set step per confirmed ``integrate`` effect of an accepted task.
The facts are a typed engine observation (the ledger runs no Git) and a command exit
status is never enough. create_candidate accepts only the current checkpoint.

Publication governance. External effects additionally need the candidate's newest
approving review to come from an owner-configured ``codex`` profile through a released,
successful attempt in the current context. Without one the refusal is a named INCOMPLETE
(``codex_unavailable`` or ``codex_review_required``); a Claude review never substitutes.
Local acceptance needs no Codex. This is the fixed first-release default: an owner or
project role override is not supported by this executor and means an attended handoff.
The ledger records which configured profile reviewed; it cannot prove a native Codex ran.

Routing observations. observe stores only a strict routing-observation/v1 record and
keeps every one. The current state per profile follows evidence time (``ended_at``),
never arrival order, and an auth or permission hold stays until a strictly newer
``operator_refresh``. The ledger never calls a provider.

STOP is an operator control that blocks new claims, releases and effects. It is bounded:
work already released keeps running until the engine cleans it up, and nothing is rolled
back. The ledger is an integrity aid for cooperating processes. It is not tamper-proof
against same-user code and is not a sandbox or a signature.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import glob
import hashlib
import json
import math
import os
import posixpath
import re
import sqlite3
import stat
import threading
import time
import uuid
from urllib.parse import quote

from controller_inputs import (BRANCH, DIGEST, EFFECT_CATALOG, EXTERNAL_EFFECTS, SAFE_ID, SHA,
                               WORKSPACE_EFFECTS, InputError, canonical_json, canonical_repo,
                               check_delivery_spec, validate_authority, validate_plan,
                               validate_policy)

SCHEMA_VERSION = 6
POLICY_FILE = 'policy.json'
LEDGER_FILE = 'ledger.sqlite3'
BINDING_FILE = 'sdlc-controller.binding'
LOCK_FILE = 'sdlc-controller.lock'
WORKSPACE_DIR = 'workspaces'
ROLES = ('implement', 'review')  # native profile roles; a local check is never a profile role
CHECK_ROLE = 'check'
ATTRIBUTIONS = ('semantic', 'availability', 'operator', 'execution')
REASONS = {
    'semantic': ('unspecified', 'wrong_result', 'no_result', 'scope_violation', 'check_failed',
                 'review_blocked'),
    'availability': ('quota', 'auth', 'permission_denied', 'outage', 'transport'),
    'operator': ('stop', 'pause', 'cancelled', 'context_hold'),
    'execution': ('launch_failed', 'timeout', 'lost', 'interrupted', 'unknown'),
}
# Native parser categories: the same set as controller_routing.CATEGORIES.
PROVIDER_CATEGORIES = ('success', 'permission_denied', 'rate_limited', 'auth_required',
                       'unavailable', 'interrupted', 'incomplete', 'failed', 'outage',
                       'transport', 'unknown')
AVAILABILITY_CATEGORIES = ('permission_denied', 'rate_limited', 'auth_required', 'unavailable',
                           'outage', 'transport')
CHECK_STATUSES = ('PASS', 'FAIL', 'INCOMPLETE')
RECEIPT_SCHEMA = 'verified-handoff/evidence-receipt/v1'
RECEIPT_KEYS = ('schema', 'receipt_sha256', 'lifecycle_sha256', 'input_sha')
OBSERVATION_SCHEMA = 'sdlc-controller/routing-observation/v1'
OBSERVATION_SOURCES = ('outcome', 'operator_refresh')
HOLD_AVAILABILITY = {'auth_required': 'auth_hold', 'permission_denied': 'permission_hold'}
MAX_EPOCH = 253402300799  # 9999-12-31T23:59:59Z
MAX_EXACT_INT = 2 ** 53
MAX_CLOCK_SKEW_SECONDS = 300  # an observation may not be captured further in the future
_HOLDS = tuple(HOLD_AVAILABILITY.values())
_TRANSIENT = ('unavailable', 'outage', 'transport')
_RESTRICTION = {'available': 0, 'unknown': 1, 'rate_limited': 2, 'cooldown': 2,
                'auth_hold': 3, 'permission_hold': 3}
_OBS_BASE = ('schema', 'source', 'provider', 'category', 'availability', 'captured_at',
             'ended_at', 'retry_at', 'retry_basis')
_OBS_TEXT = ('quota_status', 'quota_type', 'overage_status', 'quota_utilization_window')
_OBS_COUNT = ('quota_event_index', 'quota_invalid_fields', 'quota_seen', 'quota_ignored')
_OBS_QUOTA = _OBS_TEXT + _OBS_COUNT + ('quota_reset_at', 'using_overage', 'quota_utilization',
                                       'quota_session_id')
_ENUM = re.compile(r'[a-z][a-z0-9_]{0,63}')
_SESSION = re.compile(r'[0-9A-Fa-f-]{1,64}')
_EXCUSED_SQL = "('availability','operator','execution')"
CONTROLS = ('running', 'paused', 'stopped')
OUTCOMES = ('success', 'failure', 'cancelled', 'unknown')
DONE_STATES = ('accepted', 'published')
PROGRESS_STATES = ('checked', 'reviewed', 'accepted', 'published')
TRANSITIONS = {('reviewed', 'accepted'), ('accepted', 'published'),
               ('pending', 'blocked'), ('blocked', 'pending')}
MAX_USED_SECONDS = 366 * 86400
_ACTIVE_SQL = "('reserved','launched','unknown')"
_BINDING_JSON = ('dependencies', 'workspace', 'evidence')
_CANDIDATE_JSON = ('contributions', 'checks', 'workspace', 'evidence')
CANDIDATE_KIND = 'candidate'  # internal task kind; controller_inputs.KINDS never admits it
CANDIDATE_PREFIX = 'candidate-'
_CANDIDATE_STAGE = {'implemented': 'checking', 'checked': 'reviewing', 'reviewed': 'reviewed',
                    'accepted': 'accepted'}
_EXTERNAL_KINDS = tuple(kind for kind, effect in EFFECT_CATALOG.items() if effect in EXTERNAL_EFFECTS)
_INTEGRATION_KEYS = {'checkpoint', 'confirmed', 'owned', 'ancestors', 'integrations'}
_OBSERVED_KEYS = {'confirmed', 'head', 'branch', 'path', 'ancestors'}
_WORKSPACE_JSON = ('write_scope',)
_CHECKPOINT_JSON = ('contributions', 'observation')
LOCAL_BRANCH_PREFIX = 'sdlc/'  # controller branch namespace when policy.delivery is null
PUBLICATION_PROVIDER = 'codex'  # fixed first-release governance; no override is supported
# Exact field names of the adapter specs (controller_effects dataclasses) that the strict
# inner ``fx`` mapping of a journalled spec must carry.
_FX_FIELDS = {
    'worktree.create': {'repo', 'common_dir', 'branch', 'path', 'base_sha'},
    'worktree.remove': {'repo', 'common_dir', 'cleanup_root', 'path', 'branch', 'expected_head'},
    'integrate': {'repo', 'common_dir', 'integration_worktree', 'target_branch', 'expected_base',
                  'task_branch', 'task_result', 'strategy', 'message'},
}
_SCHEMA = '''
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE controller(id INTEGER PRIMARY KEY CHECK(id = 1), fence INTEGER NOT NULL,
  control TEXT NOT NULL);
CREATE TABLE contexts(epoch INTEGER PRIMARY KEY, policy_digest TEXT NOT NULL,
  policy_file TEXT NOT NULL, identity TEXT NOT NULL, actor TEXT NOT NULL, fence INTEGER,
  at TEXT NOT NULL);
CREATE TABLE plans(id TEXT PRIMARY KEY, digest TEXT NOT NULL, base_sha TEXT NOT NULL,
  body TEXT NOT NULL, authority TEXT NOT NULL, submitted_at TEXT NOT NULL,
  epoch INTEGER NOT NULL REFERENCES contexts(epoch));
CREATE TABLE admissions(id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id TEXT NOT NULL REFERENCES plans(id), epoch INTEGER NOT NULL REFERENCES contexts(epoch),
  authority TEXT NOT NULL, fence INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE tasks(id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id),
  spec TEXT NOT NULL, state TEXT NOT NULL, failures INTEGER NOT NULL DEFAULT 0,
  no_progress INTEGER NOT NULL DEFAULT 0, progress TEXT, result TEXT);
CREATE TABLE bindings(id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id), epoch INTEGER NOT NULL REFERENCES contexts(epoch),
  execution_base TEXT NOT NULL, dependencies TEXT NOT NULL, workspace TEXT NOT NULL,
  evidence TEXT NOT NULL, state TEXT NOT NULL, fence INTEGER NOT NULL, at TEXT NOT NULL,
  ended_at TEXT, reason TEXT);
CREATE UNIQUE INDEX bindings_active ON bindings(task_id) WHERE state = 'active';
CREATE TABLE candidates(id TEXT PRIMARY KEY REFERENCES tasks(id),
  plan_id TEXT NOT NULL REFERENCES plans(id), revision INTEGER NOT NULL,
  epoch INTEGER NOT NULL REFERENCES contexts(epoch), origin TEXT NOT NULL, result TEXT NOT NULL,
  contributions TEXT NOT NULL, checks TEXT NOT NULL, workspace TEXT NOT NULL,
  evidence TEXT NOT NULL, fence INTEGER NOT NULL, at TEXT NOT NULL,
  UNIQUE(plan_id, revision));
CREATE TABLE attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id), profile_id TEXT, role TEXT NOT NULL,
  state TEXT NOT NULL, fence INTEGER NOT NULL, reserved_seconds INTEGER NOT NULL,
  used_seconds INTEGER, launch TEXT, released_at TEXT, outcome TEXT, result TEXT,
  created_at TEXT NOT NULL, finished_at TEXT, epoch INTEGER NOT NULL, check_name TEXT,
  attribution TEXT, reason TEXT, category TEXT,
  CHECK((role = 'check') = (profile_id IS NULL)),
  CHECK((role = 'check') = (check_name IS NOT NULL)));
CREATE TABLE evidence(id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id), kind TEXT NOT NULL, name TEXT NOT NULL,
  passed INTEGER NOT NULL, identity TEXT NOT NULL, attempt_id INTEGER, at TEXT NOT NULL,
  epoch INTEGER NOT NULL, status TEXT NOT NULL, receipt TEXT);
CREATE TABLE progress(id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id), fingerprint TEXT NOT NULL, result TEXT NOT NULL,
  reason TEXT NOT NULL, cleared INTEGER NOT NULL, fence INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE effects(id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT REFERENCES tasks(id), plan_id TEXT NOT NULL REFERENCES plans(id),
  owner TEXT NOT NULL CHECK(owner IN ('task', 'plan')), kind TEXT NOT NULL, spec TEXT NOT NULL,
  state TEXT NOT NULL, result TEXT, fence INTEGER NOT NULL, at TEXT NOT NULL, resolved_at TEXT,
  CHECK((owner = 'task') = (task_id IS NOT NULL)),
  CHECK(owner = 'task' OR kind IN ('worktree.create', 'worktree.remove')));
CREATE TABLE plan_workspaces(id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id TEXT NOT NULL REFERENCES plans(id), epoch INTEGER NOT NULL REFERENCES contexts(epoch),
  purpose TEXT NOT NULL CHECK(purpose = 'integration'), path TEXT NOT NULL UNIQUE,
  cleanup_id TEXT NOT NULL UNIQUE, branch TEXT NOT NULL UNIQUE, base_sha TEXT NOT NULL,
  write_scope TEXT NOT NULL, fence INTEGER NOT NULL, at TEXT NOT NULL,
  UNIQUE(plan_id, epoch, purpose));
CREATE TABLE checkpoints(id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id TEXT NOT NULL REFERENCES plans(id), epoch INTEGER NOT NULL REFERENCES contexts(epoch),
  workspace_id INTEGER NOT NULL REFERENCES plan_workspaces(id),
  previous INTEGER UNIQUE REFERENCES checkpoints(id), sha TEXT NOT NULL,
  contributions TEXT NOT NULL, effect_id INTEGER NOT NULL UNIQUE REFERENCES effects(id),
  observation TEXT NOT NULL, fence INTEGER NOT NULL, at TEXT NOT NULL);
CREATE UNIQUE INDEX checkpoints_initial ON checkpoints(workspace_id) WHERE previous IS NULL;
CREATE TABLE observations(id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL,
  data TEXT NOT NULL, at TEXT NOT NULL, admitted INTEGER NOT NULL, reason TEXT NOT NULL);
CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, fence INTEGER,
  kind TEXT NOT NULL, ref TEXT NOT NULL, data TEXT NOT NULL);
CREATE TRIGGER plans_origin BEFORE UPDATE OF id, digest, base_sha, body, submitted_at ON plans
  BEGIN SELECT RAISE(ABORT, 'plan origin is immutable'); END;
CREATE TRIGGER bindings_facts BEFORE UPDATE OF id, task_id, epoch, execution_base,
  dependencies, workspace, evidence, fence, at ON bindings
  BEGIN SELECT RAISE(ABORT, 'binding facts are immutable'); END;
''' + ''.join(
    f"CREATE TRIGGER {table}_fixed BEFORE UPDATE ON {table} "
    f"BEGIN SELECT RAISE(ABORT, '{table} are append-only'); END;\n"
    for table in ('events', 'contexts', 'admissions', 'candidates', 'plan_workspaces',
                  'checkpoints')) + ''.join(
    f"CREATE TRIGGER {table}_kept BEFORE DELETE ON {table} "
    f"BEGIN SELECT RAISE(ABORT, 'history is retained'); END;\n"
    for table in ('events', 'attempts', 'effects', 'evidence', 'progress', 'observations',
                  'contexts', 'admissions', 'bindings', 'plans', 'tasks', 'candidates',
                  'plan_workspaces', 'checkpoints'))


class LedgerError(Exception):
    """Refusal with a stable machine-readable ``code``."""

    def __init__(self, code, message=''):
        super().__init__(f'{code}: {message}' if message else code)
        self.code = code


def _canon(value):
    """The canonical JSON shared with controller_inputs (sorted, compact, UTF-8, no NaN)."""
    try:
        return canonical_json(value)
    except InputError as err:
        raise LedgerError('canonical', 'value is not canonical JSON') from err


def digest(value):
    """SHA-256 of the canonical JSON form; equals controller_inputs.canonical_digest."""
    return hashlib.sha256(_canon(value).encode('utf-8')).hexdigest()


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _stamp(value):
    """Parse a validated UTC ``...Z`` timestamp."""
    return _dt.datetime.fromisoformat(value[:-1] + '+00:00')


def _is_sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _label(value, code):
    if type(value) is not str or not value.strip() or len(value) > 200:
        raise LedgerError(code, f'{code} must be short non-empty text')
    return value


def _seconds(value):
    """Validated measured runtime. Fractions are charged rounded up; nothing is clamped."""
    if value is None:
        return None
    if (type(value) not in (int, float) or (type(value) is float and not math.isfinite(value))
            or not 0 <= value <= MAX_USED_SECONDS):
        raise LedgerError('used_seconds', 'used_seconds must be a finite non-negative number of seconds')
    return math.ceil(value)


def _number(value):
    """A finite number. Booleans and integers beyond exact float range are refused."""
    if type(value) is int:
        return -MAX_EXACT_INT <= value <= MAX_EXACT_INT
    return type(value) is float and math.isfinite(value)


def _epoch(value):
    return _number(value) and 0 < value <= MAX_EPOCH


def _attribute(outcome, local, attribution, reason, category):
    """Stored (attribution, reason) of a reconciled close; ``local`` marks a check attempt.

    Success carries no failure attribution. ``semantic`` means actual evidence of a wrong
    result from a native attempt, so it is refused for a cancelled attempt, for a local
    check process (its verdict is record_check_outcome) and next to an availability
    category. Every other close must name its fixed reason."""
    if outcome == 'success':
        if attribution is not None or reason is not None or category not in (None, 'success'):
            raise LedgerError('attribution', 'success carries no failure attribution or category')
        return None, None
    owner = attribution
    if owner is None:
        if outcome != 'failure' or local:
            raise LedgerError('attribution', 'name availability, operator or execution with a reason')
        owner = 'semantic'
    if owner == 'semantic':
        if outcome != 'failure' or local or category in AVAILABILITY_CATEGORIES:
            raise LedgerError('attribution', 'semantic needs actual evidence of a wrong native result')
        return owner, reason or 'unspecified'
    if reason is None:
        raise LedgerError('attribution', 'a non-semantic close needs a fixed reason')
    return owner, reason


def _receipt(status, refs):
    """Closed reference to the v1 check receipt and the shared process lifecycle record:
    exactly RECEIPT_KEYS, digests as 64-hex and the checked input as a full object id.
    The ledger reads no file: the engine verified both and this only records which ones.
    INCOMPLETE may carry no reference, or one whose missing parts are null."""
    absent = status == 'INCOMPLETE'
    if refs is None and absent:
        return None
    if not (type(refs) is dict and set(refs) == set(RECEIPT_KEYS) and refs['schema'] == RECEIPT_SCHEMA):
        raise LedgerError('receipt', 'receipt_refs must be exactly ' + ', '.join(RECEIPT_KEYS))
    for key in ('receipt_sha256', 'lifecycle_sha256'):
        value = refs[key]
        if not ((absent and value is None) or (type(value) is str and DIGEST.fullmatch(value))):
            raise LedgerError('receipt', f'{key} must be a 64-hex digest')
    if not ((absent and refs['input_sha'] is None) or _is_sha(refs['input_sha'])):
        raise LedgerError('receipt', 'input_sha must be a full 40- or 64-hex object id')
    return dict(refs)


def _aggregate(states):
    """Aggregate of the declared checks: a recorded FAIL outranks everything, a missing or
    INCOMPLETE row is otherwise INCOMPLETE and PASS needs every declared check to pass.
    No checks: None."""
    values = list(states.values())
    if not values:
        return None
    if 'FAIL' in values:
        return 'FAIL'
    if None in values or 'INCOMPLETE' in values:
        return 'INCOMPLETE'
    return 'PASS'


def _observation(metadata, provider, now):
    """Accept only a strict routing-observation/v1 record for ``provider``: the exact keys
    the normalizer emits, enumerated or id-shaped text, exact finite numeric types in
    range and mutually consistent fields. Untyped metadata proves nothing and is refused."""
    def need(fact):
        if not fact:
            raise LedgerError('metadata', 'observation must be a valid routing-observation/v1 record')

    need(type(metadata) is dict and all(type(key) is str for key in metadata))
    need(set(_OBS_BASE) <= set(metadata) <= set(_OBS_BASE + _OBS_QUOTA))
    source, category, availability = (metadata[key] for key in ('source', 'category', 'availability'))
    ended, captured = metadata['ended_at'], metadata['captured_at']
    retry, basis = metadata['retry_at'], metadata['retry_basis']
    need(metadata['schema'] == OBSERVATION_SCHEMA and metadata['provider'] == provider)
    need(all(type(value) is str for value in (source, category, availability)))
    need(source in OBSERVATION_SOURCES and category in PROVIDER_CATEGORIES
         and availability in _RESTRICTION)
    need(_epoch(ended) and _epoch(captured) and ended <= captured <= now + MAX_CLOCK_SKEW_SECONDS)
    need(retry is None or _epoch(retry))
    need(basis is None or type(basis) is str)
    need((basis is None) == (retry is None))
    if source == 'operator_refresh':
        need(set(metadata) == set(_OBS_BASE) and ended == captured
             and (category, availability, retry) == ('unknown', 'unknown', None))
    else:
        need((availability in _HOLDS) == (category in HOLD_AVAILABILITY))
        need(HOLD_AVAILABILITY.get(category, availability) == availability)
        need(availability != 'available' or category == 'success')
        need(availability != 'cooldown' or category in _TRANSIENT)
        need(basis == {'rate_limited': 'quota_reset', 'cooldown': 'fixed_backoff'}.get(availability)
             or (basis is None and availability != 'cooldown'))
    for key in _OBS_TEXT:
        value = metadata.get(key)
        need(value is None or (type(value) is str and _ENUM.fullmatch(value) is not None))
    for key in _OBS_COUNT:
        value = metadata.get(key)
        need(value is None or (type(value) is int and 0 <= value <= MAX_EXACT_INT))
    session, overage = metadata.get('quota_session_id'), metadata.get('using_overage')
    reset, utilization = metadata.get('quota_reset_at'), metadata.get('quota_utilization')
    need(session is None or (type(session) is str and _SESSION.fullmatch(session) is not None))
    need(overage is None or type(overage) is bool)
    need(reset is None or _epoch(reset))
    need(utilization is None or (_number(utilization) and utilization >= 0))
    need(len(_canon(metadata)) <= 4096)
    return dict(metadata)


def _admission(current, incoming):
    """Whether ``incoming`` replaces the admitted ``current`` observation of a profile.

    Order is evidence time (``ended_at``; the refresh time for an operator refresh),
    never capture or arrival order. Older evidence is ``stale``. An auth or permission
    hold is replaced only by another hold or by a strictly newer operator refresh
    (``hold_sticky`` otherwise). On equal time the more restrictive state wins
    (``tie_conservative``)."""
    if current is None:
        return 'admitted'
    if incoming['ended_at'] < current['ended_at']:
        return 'stale'
    newer = incoming['ended_at'] > current['ended_at']
    if current['availability'] in _HOLDS:
        if incoming['availability'] in _HOLDS or (newer and incoming['source'] == 'operator_refresh'):
            return 'admitted'
        return 'hold_sticky'
    if newer or _RESTRICTION[incoming['availability']] >= _RESTRICTION[current['availability']]:
        return 'admitted'
    return 'tie_conservative'


def _state_path(state_dir):
    path = os.fspath(state_dir)
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise LedgerError('path', 'state directory must be an absolute normalized path')
    current = os.sep
    for part in path.split(os.sep)[1:]:
        current = os.path.join(current, part)
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            break
        if stat.S_ISLNK(mode):
            raise LedgerError('symlink', f'symlink in state path: {current}')
    return path


def _check_private(path, kind):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise LedgerError('missing', f'{os.path.basename(path)} is missing') from None
    if not kind(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise LedgerError('insecure', f'{os.path.basename(path)} has an unsafe type, owner or mode')


def _read_private(path, limit=1 << 20):
    _check_private(path, stat.S_ISREG)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        return os.read(fd, limit)
    finally:
        os.close(fd)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_tmp(path, data):
    tmp = path + '.tmp'
    with contextlib.suppress(FileNotFoundError):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return tmp


def _common(common_dir):
    real = os.path.realpath(os.fspath(common_dir))
    if not os.path.isfile(os.path.join(real, 'HEAD')) or not os.path.isdir(os.path.join(real, 'objects')):
        raise LedgerError('not_git', 'not a Git common directory')
    return real


def _inside_repo(state, common):
    roots = [common]
    if os.path.basename(common) == '.git':
        roots.append(os.path.dirname(common))
    for link in glob.glob(os.path.join(glob.escape(common), 'worktrees', '*', 'gitdir')):
        with open(link, encoding='utf-8') as handle:
            roots.append(os.path.realpath(os.path.dirname(handle.read().strip())))
    return any(state == root or state.startswith(root + os.sep) for root in roots)


def _acquire(common):
    """Take the repository flock without waiting; a held lock is never taken over."""
    path = os.path.join(common, LOCK_FILE)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held, named = os.fstat(fd), os.lstat(path)
        if not stat.S_ISREG(named.st_mode) or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
            raise OSError('lock file was replaced')
    except OSError as err:
        os.close(fd)
        raise LedgerError('locked', 'another controller holds this repository') from err
    return fd


def _release(fd):
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


class _Lease:
    """Live controller capability: the OS-held repository flock plus its fence.

    Created only by ControllerLock. It is valid in the creating process only (a forked
    child holds nothing) and only until the owner revokes it on exit. ``guard`` makes
    revocation wait for an in-flight fenced write instead of racing it. ``identity`` is
    the runtime/rules identity this controller presented, or None.
    """

    def __init__(self, fd, path, identity=None):
        self.fd, self.path, self.pid = fd, path, os.getpid()
        self.fence, self.alive, self.guard = None, True, threading.Lock()
        self.identity = identity

    def held(self):
        """True only while this process positively holds the flock on the named lock file."""
        if not self.alive or self.pid != os.getpid():
            return False
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held, named = os.fstat(self.fd), os.lstat(self.path)
        except OSError:
            return False
        return (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)

    def revoke(self):
        with self.guard:
            self.alive = False


def _read_binding(common):
    try:
        binding = json.loads(_read_private(os.path.join(common, BINDING_FILE)))
        valid = (binding['version'] == 1 and isinstance(binding['state_dir'], str)
                 and isinstance(binding['authority_id'], str))
    except (ValueError, KeyError, TypeError) as err:
        raise LedgerError('corrupt', 'repository binding is unreadable') from err
    if not valid:
        raise LedgerError('corrupt', 'repository binding is unsupported')
    return binding


def _bind(common, state, create):
    """Compare the binding with ``state``; with ``create``, bind first use atomically."""
    path = os.path.join(common, BINDING_FILE)
    if not os.path.lexists(path):
        if not create:
            return None
        record = {'version': 1, 'state_dir': state, 'authority_id': uuid.uuid4().hex}
        tmp = _write_tmp(path, _canon(record).encode('utf-8'))
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass
        finally:
            os.unlink(tmp)
        _fsync_dir(common)
    binding = _read_binding(common)
    if binding['state_dir'] != state:
        raise LedgerError('bound_elsewhere', 'repository is bound to another state directory')
    return binding['authority_id']


def _connect(path, readonly):
    uri = 'file:' + quote(path) + ('?mode=ro' if readonly else '?mode=rw')
    db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    if not readonly:
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
    return db


def _create_ledger(path, meta, policy_digest, identity):
    tmp = _write_tmp(path, b'')
    db = sqlite3.connect(tmp, isolation_level=None)
    try:
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        db.executescript(_SCHEMA)
        db.executemany('INSERT INTO meta VALUES (?, ?)', list(meta.items()))
        db.execute("INSERT INTO controller VALUES (1, 0, 'running')")
        db.execute('INSERT INTO contexts(epoch, policy_digest, policy_file, identity, actor, at) '
                   "VALUES (1, ?, ?, ?, 'initialize', ?)",
                   (policy_digest, POLICY_FILE, _canon(identity), _now()))
        db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
    finally:
        db.close()
    _fsync_dir(os.path.dirname(path))
    os.rename(tmp, path)
    _fsync_dir(os.path.dirname(path))


def _check_identity(identity):
    if not (type(identity) is dict and set(identity) == {'runtime', 'rules'}
            and all(type(v) is str and DIGEST.fullmatch(v) for v in identity.values())):
        raise LedgerError('identity', 'identity needs 64-hex runtime and rules digests')


def _overlap(left, right):
    def norm(path):
        return posixpath.normpath(path.strip('/') or '.')
    for a in map(norm, left):
        for b in map(norm, right):
            if '.' in (a, b) or a == b or a.startswith(b + '/') or b.startswith(a + '/'):
                return True
    return False


def _released(attempt):
    """True when the attempt row retains a positive launch identity and a release grant.
    Necessary ledger evidence only: it does not prove that a provider process did the work."""
    launch = attempt['launch']
    return (type(launch) is dict and type(launch.get('pid')) is int and launch['pid'] > 0
            and attempt['released_at'] is not None)


def _checkpoint(evidence, base, required):
    """Typed engine observation that ``base`` is the confirmed, controller-owned
    integration checkpoint and that every SHA in ``required`` is its ancestor.

    Trust boundary: the ledger runs no Git. It accepts only the exact closed shape with
    every fact literally True (missing, unknown, false or free text is refused) and
    records it so the engine observation can be independently Git-checked later. It must
    come from the fixed engine's own Git queries, never from producer output."""
    if not (type(evidence) is dict and set(evidence) == {'checkpoint', 'confirmed', 'ancestors'}
            and type(evidence['ancestors']) is dict):
        raise LedgerError('checkpoint_evidence', 'checkpoint evidence must be exactly '
                                                 '{checkpoint, confirmed, ancestors}')
    ancestors = evidence['ancestors']
    if (evidence['checkpoint'] != base or evidence['confirmed'] is not True
            or set(ancestors) != required or any(fact is not True for fact in ancestors.values())):
        raise LedgerError('checkpoint_unproven', 'the execution base must be the confirmed checkpoint '
                                                 'and contain the plan origin and every dependency result')
    return {'checkpoint': base, 'confirmed': True, 'ancestors': {sha: True for sha in sorted(required)}}


def _integration(evidence, origin, result, contributions):
    """Typed engine observation that ``result`` is the confirmed, controller-owned
    integrated checkpoint of a whole plan: the plan origin and every contributing result
    are its ancestors and each contribution names the integration effect that merged it.

    Same trust boundary as _checkpoint: the ledger runs no Git. It accepts only the exact
    closed shape with every fact literally True and integer effect references (which the
    caller then verifies against the ledger's own effect journal), and records it for a
    later independent Git check. It must come from the fixed engine's own Git queries,
    never from producer or reviewer output."""
    if not (type(evidence) is dict and set(evidence) == _INTEGRATION_KEYS
            and type(evidence['ancestors']) is dict and type(evidence['integrations']) is dict):
        raise LedgerError('integration_evidence', 'integration evidence must be exactly '
                                                  '{checkpoint, confirmed, owned, ancestors, integrations}')
    ancestors, effects = evidence['ancestors'], evidence['integrations']
    required = {origin, *contributions.values()}
    if (evidence['checkpoint'] != result or evidence['confirmed'] is not True
            or evidence['owned'] is not True or set(ancestors) != required
            or any(fact is not True for fact in ancestors.values())
            or set(effects) != set(contributions)
            or any(type(effect_id) is not int for effect_id in effects.values())):
        raise LedgerError('integration_unproven', 'the result must be the confirmed owned integrated '
                                                  'checkpoint containing the plan origin and every '
                                                  'contribution, each with its integration effect')
    return {'checkpoint': result, 'confirmed': True, 'owned': True,
            'ancestors': {sha: True for sha in sorted(required)},
            'integrations': {task_id: effects[task_id] for task_id in sorted(effects)}}


def _safe_branch(value):
    """The branch-name safety rule of the controller_inputs boundary (no refspec syntax)."""
    return (type(value) is str and BRANCH.fullmatch(value) is not None and '..' not in value
            and not any(not part or part.startswith('.') or part.endswith(('.', '.lock'))
                        for part in value.split('/')))


def _observed(observation, head, workspace, required):
    """Typed engine observation of the plan workspace after one confirmed effect: exactly
    ``{confirmed, head, branch, path, ancestors}`` with ``confirmed`` literally True, the
    exact ``head``, the registered branch and path, and one literally True ancestry fact
    for the plan origin and every contributing result (``required``).

    Same trust boundary as _checkpoint: the ledger runs no Git. Missing, unknown, false or
    free-text facts are refused, and the accepted record is kept for a later independent
    Git check. It must come from the fixed engine's own Git queries, never from an exit
    status or from producer output."""
    if not (type(observation) is dict and set(observation) == _OBSERVED_KEYS
            and type(observation['ancestors']) is dict):
        raise LedgerError('checkpoint_evidence', 'the observation must be exactly '
                                                 '{confirmed, head, branch, path, ancestors}')
    ancestors = observation['ancestors']
    if (observation['confirmed'] is not True or observation['head'] != head
            or observation['branch'] != workspace['branch'] or observation['path'] != workspace['path']
            or set(ancestors) != required or any(fact is not True for fact in ancestors.values())):
        raise LedgerError('checkpoint_unproven', 'the registered workspace must be confirmed at this '
                                                 'head and contain the plan origin and every contribution')
    return {'confirmed': True, 'head': head, 'branch': workspace['branch'], 'path': workspace['path'],
            'ancestors': {sha: True for sha in sorted(required)}}


def _frozen_policy(policy, common):
    """Accept only the frozen output of validate_policy for this exact repository."""
    try:
        frozen = validate_policy(policy)
        repo = canonical_repo(frozen['repository'])
    except InputError as err:
        raise LedgerError('policy_invalid', str(err)) from err
    if frozen != policy:
        raise LedgerError('policy_not_frozen', 'pass the frozen policy returned by validate_policy')
    if repo['common_dir'] != common:
        raise LedgerError('repository_mismatch', 'policy.repository is not this Git common directory')
    return frozen


def _policy_bytes(frozen):
    return (_canon(frozen) + '\n').encode('utf-8')


def initialize(state_dir, policy, common_dir, identity):
    """Create or re-verify state. ``policy`` must be the frozen validate_policy result
    (profiles carry their canonical config_dir), so a changed environment that would
    select another default profile surfaces as ``policy_changed``.

    Strict and idempotent: it never reconfigures, migrates, resets or relabels. A policy
    or identity that differs from the current context epoch is refused and everything
    recorded is preserved; the state stays usable through ControllerLock (held for
    cleanup) and only Ledger.reconcile_context appends a new context."""
    common = _common(common_dir)
    _check_identity(identity)
    frozen = _frozen_policy(policy, common)
    state = _state_path(state_dir)
    if _inside_repo(state, common):
        raise LedgerError('inside_repository', 'state directory must be outside the repository')
    proposed = _policy_bytes(frozen)
    proposed_digest = hashlib.sha256(proposed).hexdigest()
    lock = _acquire(common)
    try:
        _bind(common, state, create=False)
        if not os.path.lexists(state):
            os.mkdir(state, 0o700)
        _check_private(state, stat.S_ISDIR)
        authority = _bind(common, state, create=True)
        policy_path, ledger_path = os.path.join(state, POLICY_FILE), os.path.join(state, LEDGER_FILE)
        if not os.path.lexists(ledger_path):
            if not os.path.lexists(policy_path):
                os.rename(_write_tmp(policy_path, proposed), policy_path)
                _fsync_dir(state)
            elif _read_private(policy_path) != proposed:
                raise LedgerError('policy_changed', 'policy differs from the recorded snapshot')
            _create_ledger(ledger_path, {'schema_version': str(SCHEMA_VERSION), 'authority_id': authority,
                                         'common_dir': common}, proposed_digest, identity)
        ledger = Ledger.open(state)
        refusal = ('policy_changed' if ledger.policy_digest != proposed_digest
                   else 'identity_changed' if ledger.identity != identity else None)
        if refusal:
            ledger.close()
            raise LedgerError(refusal, 'differs from the current context; initialize never '
                                       'reconfigures (see Ledger.reconcile_context)')
        return ledger
    finally:
        _release(lock)


class ControllerLock:
    """Hold the repository authority; entering yields a Ledger bound to a live lease and
    a new fence. Leaving revokes the lease first, so every connection that shared it
    (see Ledger.helper) loses write access immediately, before any takeover.

    ``identity`` is the runtime/rules identity the engine computed for itself. Entering
    never fails on a mismatch, so cleanup and reconciliation stay possible, but unless
    it equals the current context identity the controller is held (``context_hold``)."""

    def __init__(self, common_dir, state_dir, identity=None):
        self.common, self.state = _common(common_dir), _state_path(state_dir)
        if identity is not None:
            _check_identity(identity)
        self.identity = None if identity is None else dict(identity)
        self.ledger, self._lease = None, None

    def __enter__(self):
        self._lease = _Lease(_acquire(self.common), os.path.join(self.common, LOCK_FILE), self.identity)
        try:
            if _bind(self.common, self.state, create=False) is None:
                raise LedgerError('unbound', 'repository has no controller state')
            self.ledger = Ledger.open(self.state)
            if self.ledger.common_dir != self.common:
                raise LedgerError('unbound', 'state belongs to another repository')
            self.ledger._take_fence(self._lease)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self.ledger

    def __exit__(self, *_exc):
        lease, ledger = self._lease, self.ledger
        self.ledger, self._lease = None, None
        if lease is not None:
            lease.revoke()
        if ledger is not None:
            ledger.close()
        if lease is not None:
            _release(lease.fd)
        return False


class Ledger:
    def __init__(self, state, db, readonly, meta):
        self.state_dir, self._db, self.readonly, self._lease = state, db, readonly, None
        self.common_dir, self.authority_id = meta['common_dir'], meta['authority_id']
        self._load_context()

    @property
    def fence(self):
        """Fence of the lease this connection is bound to (read-only); None without one."""
        return None if self._lease is None else self._lease.fence

    @classmethod
    def open(cls, state_dir, readonly=False):
        """Open existing state. Without a live ControllerLock lease only the read-only
        views and set_control are usable; ``readonly`` writes nothing."""
        state = _state_path(state_dir)
        _check_private(state, stat.S_ISDIR)
        path = os.path.join(state, LEDGER_FILE)
        head = _read_private(path, 100)
        if len(head) < 100 or head[:16] != b'SQLite format 3\x00':
            raise LedgerError('corrupt', 'ledger is not a SQLite database')
        if head[18] != 1 or head[19] != 1 or int.from_bytes(head[60:64], 'big') != SCHEMA_VERSION:
            raise LedgerError('unsupported_schema', 'ledger schema or journal mode is unsupported')
        db = None
        try:
            db = _connect(path, readonly)
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('quick_check failed')
            meta = {row[0]: row[1] for row in db.execute('SELECT key, value FROM meta')}
            if meta.get('schema_version') != str(SCHEMA_VERSION):
                raise LedgerError('unsupported_schema', 'ledger schema version is unsupported')
            binding = _read_binding(meta['common_dir'])
            if (binding['state_dir'], binding['authority_id']) != (state, meta['authority_id']):
                raise LedgerError('unbound', 'repository binding does not match this state')
            return cls(state, db, readonly, meta)
        except (sqlite3.DatabaseError, KeyError, ValueError) as err:
            if db is not None:
                db.close()
            raise LedgerError('corrupt', 'ledger is unreadable') from err
        except LedgerError:
            if db is not None:
                db.close()
            raise

    def helper(self):
        """Open another connection (for example one per worker thread) explicitly bound to
        this controller's live lease. It can write only while the owner still holds the
        lock in this same process; the caller closes it. A separately opened Ledger, a
        forked child or a copied fence number never gains this capability."""
        lease = self._lease
        if lease is None:
            raise LedgerError('lease_required', 'only a controller-held ledger can lend its lease')
        if not lease.held():
            raise LedgerError('lease_lost', 'the controller lease is no longer held')
        other = Ledger.open(self.state_dir)
        other._lease = lease
        return other

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None

    def _epoch_policy(self, row):
        """Bytes of one epoch's immutable policy file, verified against its digest."""
        name = row['policy_file']
        if name not in (POLICY_FILE, f"policy-{row['policy_digest']}.json"):
            raise LedgerError('corrupt', 'context epoch names an unexpected policy file')
        try:
            data = _read_private(os.path.join(self.state_dir, name))
        except LedgerError as err:
            if err.code != 'missing':
                raise
            raise LedgerError('corrupt', 'policy snapshot of a context epoch is missing') from err
        if hashlib.sha256(data).hexdigest() != row['policy_digest']:
            raise LedgerError('corrupt', 'policy snapshot does not match its context epoch')
        return data

    def _load_context(self):
        """Load the current (highest) context epoch; it is the only pointer there is."""
        row = self._db.execute('SELECT * FROM contexts ORDER BY epoch DESC LIMIT 1').fetchone()
        if row is None:
            raise LedgerError('corrupt', 'ledger has no context epoch')
        self.policy = json.loads(self._epoch_policy(row))
        self.epoch, self.policy_digest = row['epoch'], row['policy_digest']
        self.identity, self._context_at = json.loads(row['identity']), row['at']

    @contextlib.contextmanager
    def _begin(self):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            yield self._db.execute('SELECT fence, control, (SELECT MAX(epoch) FROM contexts) AS epoch '
                                   'FROM controller WHERE id = 1').fetchone()
            self._db.execute('COMMIT')
        except BaseException:
            self._db.execute('ROLLBACK')
            raise

    @contextlib.contextmanager
    def _tx(self, fenced=True):
        """Short write transaction. Fenced writes need the live OS-held lease, its fence
        to equal the ledger's and this connection to have loaded the current context;
        never keep one open while a command runs."""
        if self.readonly:
            raise LedgerError('readonly', 'ledger was opened read-only')
        if not fenced:
            with self._begin() as row:
                yield row['control']
            return
        lease = self._lease
        if lease is None:
            raise LedgerError('lease_required', 'writer holds no controller lease')
        with lease.guard:
            if not lease.held():
                raise LedgerError('lease_lost', 'the controller lease is no longer held')
            with self._begin() as row:
                if row['fence'] != lease.fence:
                    raise LedgerError('stale_fence', 'writer does not hold the active controller fence')
                if row['epoch'] != self.epoch:
                    raise LedgerError('context_changed', 'the context was reconciled; reopen the ledger')
                yield row['control']

    @contextlib.contextmanager
    def _snapshot(self):
        """Consistent read; a connection that predates a reconcile reloads the context."""
        self._db.execute('BEGIN')
        try:
            if self._db.execute('SELECT MAX(epoch) FROM contexts').fetchone()[0] != self.epoch:
                self._load_context()
            yield
        finally:
            self._db.execute('COMMIT')

    def _take_fence(self, lease):
        with self._tx(fenced=False):
            self._db.execute('UPDATE controller SET fence = fence + 1 WHERE id = 1')
            lease.fence = self._db.execute('SELECT fence FROM controller WHERE id = 1').fetchone()[0]
            self._lease = lease
            self._event('controller_start', str(lease.fence), {
                'epoch': self.epoch, 'context': 'current' if lease.identity == self.identity else 'hold'})

    def _event(self, kind, ref, data=None):
        self._db.execute('INSERT INTO events(at, fence, kind, ref, data) VALUES (?, ?, ?, ?, ?)',
                         (_now(), self.fence, kind, str(ref), _canon(data or {})))

    def _cas(self, sql, params):
        if self._db.execute(sql, params).rowcount != 1:
            raise LedgerError('conflict', 'record is not in the expected state')

    def _rows(self, sql, params=(), decode=()):
        rows = []
        for row in self._db.execute(sql, params):
            item = dict(row)
            for column in decode:
                if item[column] is not None:
                    item[column] = json.loads(item[column])
            rows.append(item)
        return rows

    def _task(self, task_id):
        row = self._db.execute(
            'SELECT t.*, p.base_sha, p.authority, p.epoch AS plan_epoch FROM tasks t '
            'JOIN plans p ON p.id = t.plan_id WHERE t.id = ?', (task_id,)).fetchone()
        if row is None:
            raise LedgerError('unknown_task', str(task_id))
        return row

    def _attempt(self, attempt_id):
        rows = self._rows('SELECT * FROM attempts WHERE id = ?', (attempt_id,), ('launch',))
        if not rows:
            raise LedgerError('unknown_attempt', str(attempt_id))
        return rows[0]

    def _binding(self, task_id):
        rows = self._rows("SELECT * FROM bindings WHERE task_id = ? AND state = 'active'",
                          (task_id,), _BINDING_JSON)
        return rows[0] if rows else None

    def _candidate(self, task_id):
        rows = self._rows('SELECT * FROM candidates WHERE id = ?', (task_id,), _CANDIDATE_JSON)
        return rows[0] if rows else None

    def _plan_row(self, plan_id):
        row = None if type(plan_id) is not str else self._db.execute(
            'SELECT id, digest, base_sha, epoch, authority FROM plans WHERE id = ?', (plan_id,)).fetchone()
        if row is None:
            raise LedgerError('unknown_plan', str(plan_id))
        return row

    def _plan_ws(self, plan_id, epoch):
        """The integration workspace a plan registered under one context epoch, or None."""
        rows = self._rows('SELECT * FROM plan_workspaces WHERE plan_id = ? AND epoch = ?',
                          (plan_id, epoch), _WORKSPACE_JSON)
        return rows[0] if rows else None

    def _ws_row(self, workspace_id):
        return self._rows('SELECT * FROM plan_workspaces WHERE id = ?', (workspace_id,), _WORKSPACE_JSON)[0]

    def _ws_effects(self, workspace, owner, kinds):
        """Journal rows of one owner type recorded against a plan workspace, oldest first.
        For these rows the ``workspace`` reference in the stored spec is written by the
        ledger itself (see _plan_spec and _local_spec), never taken from the caller."""
        marks = ','.join('?' * len(kinds))
        rows = self._rows('SELECT id, task_id, kind, spec, state FROM effects WHERE plan_id = ? '
                          f'AND owner = ? AND kind IN ({marks}) ORDER BY id',
                          (workspace['plan_id'], owner, *kinds), ('spec',))
        return [row for row in rows if row['spec'].get('workspace') == workspace['id']]

    def _ws_state(self, workspace):
        """Lifecycle of a plan workspace, derived from its own journal and never stored:
        ``registered`` (nothing ran), ``creating`` or ``removing`` (an unresolved effect),
        ``created``, ``failed`` (the last creation failed) or ``removed`` (final)."""
        settled, busy = 'registered', None
        for row in self._ws_effects(workspace, 'plan', WORKSPACE_EFFECTS):
            create = row['kind'] == 'worktree.create'
            if row['state'] in ('intent', 'unknown'):
                busy = 'creating' if create else 'removing'
            elif row['state'] == 'done':
                settled = 'created' if create else 'removed'
            elif create:
                settled = 'failed'
        return busy or settled

    def _head(self, workspace_id):
        """The current (newest) checkpoint row of a plan workspace, or None."""
        rows = self._rows('SELECT * FROM checkpoints WHERE workspace_id = ? ORDER BY id DESC LIMIT 1',
                          (workspace_id,), _CHECKPOINT_JSON)
        return rows[0] if rows else None

    def _unrecorded(self, workspace):
        """Confirmed integrations of this workspace that no checkpoint records yet: what a
        restarted engine must observe and record before anything else is integrated."""
        recorded = {row[0] for row in self._db.execute(
            'SELECT effect_id FROM checkpoints WHERE workspace_id = ?', (workspace['id'],))}
        return [row['id'] for row in self._ws_effects(workspace, 'task', ('integrate',))
                if row['state'] == 'done' and row['id'] not in recorded]

    def _workspace_view(self, row):
        head = self._head(row['id'])
        return {**row, 'state': self._ws_state(row), 'current': row['epoch'] == self.epoch,
                'head': None if head is None else head['sha'], 'unrecorded': self._unrecorded(row)}

    def _checkpoint_view(self, row):
        before = None if row['previous'] is None else self._db.execute(
            'SELECT sha FROM checkpoints WHERE id = ?', (row['previous'],)).fetchone()[0]
        return {**row, 'expected': before, 'workspace': self._workspace_view(self._ws_row(row['workspace_id']))}

    def _plan_integration(self, plan_id, epoch):
        """(workspace view, current checkpoint view) of a plan in one context epoch."""
        workspace = self._plan_ws(plan_id, epoch)
        head = None if workspace is None else self._head(workspace['id'])
        return (None if workspace is None else self._workspace_view(workspace),
                None if head is None else self._checkpoint_view(head))

    def _workspace_taken(self, path, cleanup):
        """Whether an active task binding or a plan registration already names this workspace."""
        for other in self._rows("SELECT workspace FROM bindings WHERE state = 'active'", (), ('workspace',)):
            if path == other['workspace']['path'] or cleanup == other['workspace']['cleanup_id']:
                return True
        return self._db.execute('SELECT 1 FROM plan_workspaces WHERE path = ? OR cleanup_id = ?',
                                (path, cleanup)).fetchone() is not None

    def _integration_granted(self, plan):
        """Plan-owned work exists only to integrate: it needs the ``integrate`` effect in the
        current policy and in the authority the plan was admitted with."""
        if ('integrate' not in self.policy['effects']
                or 'integrate' not in json.loads(plan['authority'])['effects']):
            raise LedgerError('effect_unauthorized', 'the plan holds no integrate grant')

    def _candidate_hold(self, task, candidate):
        """Fixed reason a derived candidate is not current, else None. Evaluated on every
        use and never stored, so a later change of a contributing state, result, binding
        or dependency, a newer revision or another context holds the candidate without
        touching its rows."""
        latest = self._db.execute('SELECT MAX(revision) FROM candidates WHERE plan_id = ?',
                                  (candidate['plan_id'],)).fetchone()[0]
        if candidate['revision'] != latest:
            return 'superseded'
        if (candidate['epoch'], task['plan_epoch']) != (self.epoch, self.epoch):
            return 'context'
        if task['result'] != candidate['result'] or self._binding(task['id']) is None:
            return 'withdrawn'
        for task_id, bound in candidate['contributions'].items():
            row = self._db.execute('SELECT state, result FROM tasks WHERE id = ?', (task_id,)).fetchone()
            if row is None or row['state'] not in DONE_STATES:
                return 'contribution_state'
            if row['result'] != bound['result']:
                return 'contribution_result'
            binding = self._binding(task_id)
            if binding is None or binding['id'] != bound['binding']:
                return 'contribution_binding'
            try:
                self._check_dependencies(binding['dependencies'])
            except LedgerError:
                return 'contribution_dependency'
        workspace = self._plan_ws(candidate['plan_id'], self.epoch)
        head = None if workspace is None else self._head(workspace['id'])
        if head is None or head['sha'] != candidate['result']:
            return 'checkpoint'
        return None

    def _derived(self, task):
        """The candidate row behind a derived task (None for an ordinary task), refused as
        ``candidate_stale`` with the fixed hold reason unless it is still current."""
        candidate = self._candidate(task['id'])
        if candidate is not None:
            hold = self._candidate_hold(task, candidate)
            if hold is not None:
                raise LedgerError('candidate_stale', hold)
        return candidate

    def _reviewable(self, task_id):
        """Whether checked work can still be reviewed: a held candidate reserves no slot."""
        candidate = self._candidate(task_id)
        return candidate is None or self._candidate_hold(self._task(task_id), candidate) is None

    def _require_context(self):
        """Hold: the lease must have presented exactly the current context identity."""
        lease = self._lease
        if lease is None or lease.identity != self.identity:
            raise LedgerError('context_hold', 'the presented runtime/rules identity is not the current '
                                              'context; only cleanup is allowed until reconcile_context')

    def _live(self, task):
        if task['plan_epoch'] != self.epoch:
            raise LedgerError('plan_stale', 'the plan was admitted under an earlier context; '
                                            'readmit_plan is required')

    def _check_dependencies(self, dependencies):
        """Every bound dependency must still be accepted with exactly the bound result."""
        for dep, sha in dependencies.items():
            row = self._db.execute('SELECT state, result FROM tasks WHERE id = ?', (dep,)).fetchone()
            if row is None or row['state'] not in DONE_STATES:
                raise LedgerError('dependencies', f'{dep} is not accepted')
            if row['result'] != sha:
                raise LedgerError('dependency_stale', f'{dep} is accepted with another result')

    def _expected(self, task):
        """The exact five-key gate identity, or None without a result or a binding. ``base``
        is the task's bound execution base, never the plan origin."""
        binding = self._binding(task['id'])
        if binding is None or task['result'] is None:
            return None
        return {'result': task['result'], 'base': binding['execution_base'],
                'policy': self.policy_digest, **self.identity}

    def _gate(self, task, identity):
        """Canonical result/base/policy/runtime/rules tuple. Anything else, including a
        partial or widened record, is stale."""
        if self._binding(task['id']) is None:
            raise LedgerError('binding_required', 'the task has no execution binding')
        expected = self._expected(task)
        if expected is None or type(identity) is not dict or identity != expected:
            raise LedgerError('stale_identity', 'identity tuple does not match the current result')
        return _canon(expected)

    def _check_states(self, task_id, checks, gate):
        """Recorded status per declared check for one gate identity in the current epoch.
        The latest row wins, except that a FAIL is never superseded; None is missing."""
        states = dict.fromkeys(checks)
        rows = self._db.execute(
            "SELECT name, status FROM evidence WHERE task_id = ? AND kind = 'check' "
            'AND identity = ? AND epoch = ? ORDER BY id', (task_id, gate, self.epoch)).fetchall()
        for row in rows:
            if row['name'] in states and states[row['name']] != 'FAIL':
                states[row['name']] = row['status']
        return states

    def _checks_pass(self, task_id, checks, gate):
        return all(status == 'PASS' for status in self._check_states(task_id, checks, gate).values())

    def _gates_hold(self, task, gate):
        """Every declared check passes and the newest review approves, both recorded in the
        current context for exactly ``gate``."""
        review = self._db.execute(
            "SELECT passed FROM evidence WHERE task_id = ? AND kind = 'review' AND identity = ? "
            'AND epoch = ? ORDER BY id DESC LIMIT 1', (task['id'], gate, self.epoch)).fetchone()
        checks = json.loads(task['spec'])['checks']
        return self._checks_pass(task['id'], checks, gate) and review is not None and review[0] == 1

    def _requeue(self, task_id, state, semantic):
        """Return a task to pending and drop its unaccepted result. Only a semantic cause
        adds to the failure history and the no-progress streak."""
        counted = 'failures = failures + 1, no_progress = no_progress + 1, ' if semantic else ''
        self._cas(f"UPDATE tasks SET state = 'pending', {counted}result = NULL WHERE id = ? AND state = ?",
                  (task_id, state))

    def _active(self):
        return self._db.execute(
            'SELECT a.task_id, a.role, t.spec FROM attempts a '
            f'JOIN tasks t ON t.id = a.task_id WHERE a.state IN {_ACTIVE_SQL}').fetchall()

    def _dispatch(self, task_id, role, check=None):
        """Counts and derived limits of one lane (see the module docstring). ``dispatched``
        is every launch; ``semantic`` leaves out closes attributed to availability,
        operator or execution and still counts everything unresolved."""
        row = self._db.execute(
            "SELECT COUNT(*) AS dispatched, COALESCE(SUM(CASE WHEN state = 'finished' AND attribution "
            f"IN {_EXCUSED_SQL} THEN 0 ELSE 1 END), 0) AS semantic FROM attempts "
            "WHERE task_id = ? AND role = ? AND COALESCE(check_name, '') = ?",
            (task_id, role, check or '')).fetchone()
        limit = int(self.policy['limits']['max_attempts'])
        lanes = 1 if role == CHECK_ROLE else sum(1 for p in self.policy['profiles'] if role in p['roles'])
        return {'role': role, 'check': check, 'dispatched': row['dispatched'], 'semantic': row['semantic'],
                'semantic_limit': limit, 'dispatch_limit': limit * (1 + lanes)}

    def _admit_dispatch(self, task, role, check=None):
        lane = self._dispatch(task['id'], role, check)
        if lane['semantic'] >= lane['semantic_limit']:
            raise LedgerError('attempts_exhausted', 'attempt limit reached')
        if lane['dispatched'] >= lane['dispatch_limit']:
            raise LedgerError('dispatch_exhausted', 'derived dispatch limit reached')
        if task['no_progress'] >= self.policy['limits']['max_no_progress']:
            raise LedgerError('no_progress_limit', 'no-progress limit reached')

    def _charged(self, plan_id):
        """Seconds charged to one plan: measured time of finished attempts plus the full
        reservation of every attempt still reserved, launched or unknown."""
        return self._db.execute(
            "SELECT COALESCE(SUM(CASE WHEN a.state = 'finished' THEN a.used_seconds "
            'ELSE a.reserved_seconds END), 0) FROM attempts a JOIN tasks t ON t.id = a.task_id '
            'WHERE t.plan_id = ?', (plan_id,)).fetchone()[0]

    def _authority(self, authority, plan):
        try:
            return validate_authority(authority, self.policy, plan)
        except InputError as err:
            code = {'digest': 'authority_mismatch', 'unauthorized': 'effect_unauthorized'}.get(
                err.code, 'authority_invalid')
            raise LedgerError(code, str(err)) from err

    def submit(self, plan, authority, identity):
        """Record a plan the boundary accepts and its authority approves, exactly once,
        bound to the current context epoch."""
        try:
            plan = validate_plan(plan, self.policy)
        except InputError as err:
            raise LedgerError('plan_invalid', str(err)) from err
        authority = self._authority(authority, plan)
        plan_digest = digest(plan)
        with self._tx() as control:
            if control == 'stopped':
                raise LedgerError('control_stopped', 'controller is stopped')
            if identity != self.identity:
                raise LedgerError('identity_changed', 'runtime or rules identity differs from the record')
            self._require_context()
            known = self._db.execute('SELECT digest FROM plans WHERE id = ?', (plan['id'],)).fetchone()
            if known is not None:
                if known[0] != plan_digest:
                    raise LedgerError('plan_changed', 'plan id already recorded with other content')
                return plan_digest
            existing = {row[0] for row in self._db.execute('SELECT id FROM tasks')}
            if existing & {task['id'] for task in plan['tasks']}:
                raise LedgerError('task_ids', 'task ids must be unique across plans')
            stored, now = _canon(authority), _now()
            self._db.execute('INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?, ?)', (
                plan['id'], plan_digest, plan['base_sha'], _canon(plan), stored, now, self.epoch))
            self._db.execute('INSERT INTO admissions(plan_id, epoch, authority, fence, at) '
                             'VALUES (?, ?, ?, ?, ?)', (plan['id'], self.epoch, stored, self.fence, now))
            self._db.executemany(
                "INSERT INTO tasks(id, plan_id, spec, state) VALUES (?, ?, ?, 'pending')",
                [(task['id'], plan['id'], _canon(task)) for task in plan['tasks']])
            self._event('submit', plan['id'], {'digest': plan_digest, 'identity': identity,
                                               'epoch': self.epoch})
        return plan_digest

    def _workspace_ident(self, spec, code):
        """A workspace is only a symlink-free path inside the controller-owned state
        workspace plus a cleanup identity; never an arbitrary personal path."""
        root = os.path.join(self.state_dir, WORKSPACE_DIR)
        path, cleanup = spec.get('path'), spec.get('cleanup_id')
        if not (type(path) is str and '\0' not in path and os.path.normpath(path) == path
                and path.startswith(root + os.sep) and os.path.realpath(path) == path
                and type(cleanup) is str and SAFE_ID.fullmatch(cleanup)):
            raise LedgerError(code, 'workspaces need a symlink-free path inside the controller '
                                    'state workspace and a cleanup_id')
        return path, cleanup

    def bind_execution(self, task_id, execution_base, dependencies, workspace, checkpoint_evidence):
        """Durably bind a task's exact execution base, dependency results and workspace.
        Required before claim and before worktree.create.

        ``execution_base`` is a full SHA, ``dependencies`` maps every declared dependency
        to its exact accepted current result, ``workspace`` is exactly
        ``{path, cleanup_id}`` inside the state workspace, and ``checkpoint_evidence`` is
        the typed engine observation described at _checkpoint, covering the plan origin
        and every dependency result. An identical call returns the existing binding
        (restart-safe). A different one is refused as ``binding_conflict`` until
        invalidate_binding: nothing is ever rebased implicitly. A preserved result may
        only be re-bound to the base and dependencies it was built on."""
        if not _is_sha(execution_base):
            raise LedgerError('binding_base', 'execution_base must be a full 40- or 64-hex commit id')
        if not (type(dependencies) is dict
                and all(type(dep) is str and _is_sha(sha) for dep, sha in dependencies.items())):
            raise LedgerError('binding_dependencies', 'dependencies must map task ids to full result ids')
        if not (type(workspace) is dict and set(workspace) == {'path', 'cleanup_id'}):
            raise LedgerError('binding_workspace', 'workspace must be exactly {path, cleanup_id}')
        path, cleanup = self._workspace_ident(workspace, 'binding_workspace')
        with self._tx() as control:
            task = self._task(task_id)
            if self._candidate(task_id) is not None:
                raise LedgerError('candidate_derived', 'a derived candidate is bound only by '
                                                       'create_candidate')
            if set(dependencies) != set(json.loads(task['spec'])['depends_on']):
                raise LedgerError('binding_dependencies', 'bind exactly the declared dependencies')
            evidence = _checkpoint(checkpoint_evidence, execution_base,
                                   {task['base_sha'], *dependencies.values()})
            active = self._binding(task_id)
            if active is not None:
                if (active['execution_base'], active['dependencies'], active['workspace']) != (
                        execution_base, dependencies, workspace):
                    raise LedgerError('binding_conflict', 'the task is bound differently; '
                                                          'invalidate_binding first')
                return active
            if control != 'running':
                raise LedgerError('control_' + control, 'new bindings are blocked')
            self._require_context()
            self._live(task)
            if task['result'] is None:
                if task['state'] != 'pending':
                    raise LedgerError('task_state', f"task is {task['state']}")
            else:
                last = self._db.execute('SELECT execution_base, dependencies FROM bindings '
                                        'WHERE task_id = ? ORDER BY id DESC LIMIT 1', (task_id,)).fetchone()
                if task['state'] not in ('implemented', 'checked') or last is None:
                    raise LedgerError('task_state', f"task is {task['state']}")
                if (last['execution_base'], json.loads(last['dependencies'])) != (execution_base, dependencies):
                    raise LedgerError('binding_conflict', 'a preserved result keeps the base and '
                                                          'dependencies it was built on')
            self._check_dependencies(dependencies)
            if self._workspace_taken(path, cleanup):
                raise LedgerError('workspace_conflict', 'workspace is bound to another task or plan')
            binding_id = self._db.execute(
                'INSERT INTO bindings(task_id, epoch, execution_base, dependencies, workspace, evidence, '
                "state, fence, at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (task_id, self.epoch, execution_base, _canon(dependencies), _canon(workspace),
                 _canon(evidence), self.fence, _now())).lastrowid
            self._event('bind', task_id, {'binding': binding_id, 'execution_base': execution_base,
                                          'dependencies': dependencies, 'workspace': workspace,
                                          'epoch': self.epoch})
        return self._binding(task_id)

    def invalidate_binding(self, task_id, reason):
        """Explicitly drop a task's binding so it can be bound again. Any unpublished
        result built on it is discarded with it (the task returns to pending; attempts,
        evidence and counters are kept, nothing is zeroed). Refused while the task is
        claimed, reserved or published. Grants nothing, so it works in every control state."""
        _label(reason, 'reason')
        with self._tx():
            task = self._task(task_id)
            busy = self._db.execute(f'SELECT 1 FROM attempts WHERE task_id = ? AND state IN {_ACTIVE_SQL}',
                                    (task_id,)).fetchone()
            if busy or task['state'] in ('implementing', 'published'):
                raise LedgerError('binding_locked', 'a claimed, reserved or published task keeps its binding')
            binding = self._binding(task_id)
            if binding is None and task['result'] is None:
                raise LedgerError('binding_required', 'the task has no binding or result to invalidate')
            if binding is not None:
                self._cas("UPDATE bindings SET state = 'invalidated', ended_at = ?, reason = ? "
                          "WHERE id = ? AND state = 'active'", (_now(), reason, binding['id']))
            if task['result'] is not None:
                self._cas("UPDATE tasks SET state = 'pending', result = NULL WHERE id = ? AND state = ?",
                          (task_id, task['state']))
            self._event('binding_invalidated', task_id, {
                'binding': None if binding is None else binding['id'], 'from': task['state'],
                'discarded': task['result'], 'reason': reason})

    def integration_branch_prefix(self):
        """Controller branch namespace a plan integration branch must sit inside: the frozen
        ``policy.delivery.branch_prefix``, or LOCAL_BRANCH_PREFIX without a delivery target."""
        delivery = self.policy.get('delivery')
        return LOCAL_BRANCH_PREFIX if delivery is None else delivery['branch_prefix']

    def register_plan_workspace(self, plan_id, path, cleanup_id, branch, base_sha):
        """Register the one integration workspace a plan owns in the current context.

        ``path`` and ``cleanup_id`` must sit inside the state workspace, ``branch`` inside
        integration_branch_prefix() and ``base_sha`` must be the plan origin. The row is
        immutable, one per (plan, context epoch): an identical call returns it
        (restart-safe) and a different one is ``plan_workspace_conflict``. No other
        registration, active task binding or unremoved controller workspace may share its
        path, cleanup identity or branch. Needs a running controller, the current context
        and the plan's ``integrate`` grant. It records ownership of a name only: nothing
        is created (see plan_effect_intent) and nothing is accepted or published.
        Returns the workspace view; ``write_scope`` is the union of the task scopes."""
        path, cleanup_id = self._workspace_ident({'path': path, 'cleanup_id': cleanup_id}, 'plan_workspace')
        prefix = self.integration_branch_prefix()
        if not (_safe_branch(branch) and branch.startswith(prefix) and len(branch) > len(prefix)):
            raise LedgerError('plan_workspace_branch', 'the integration branch must be a safe name '
                                                       'inside the controller branch prefix')
        if not _is_sha(base_sha):
            raise LedgerError('plan_workspace_base', 'base_sha must be a full 40- or 64-hex commit id')
        with self._tx() as control:
            plan = self._plan_row(plan_id)
            known = self._plan_ws(plan_id, self.epoch)
            if known is not None:
                if (known['path'], known['cleanup_id'], known['branch'], known['base_sha']) != (
                        path, cleanup_id, branch, base_sha):
                    raise LedgerError('plan_workspace_conflict', 'the plan already registered another '
                                                                 'integration workspace in this context')
                return self._workspace_view(known)
            if control != 'running':
                raise LedgerError('control_' + control, 'new registrations are blocked')
            self._require_context()
            if plan['epoch'] != self.epoch:
                raise LedgerError('plan_stale', 'the plan was admitted under an earlier context; '
                                                'readmit_plan is required')
            self._integration_granted(plan)
            if base_sha != plan['base_sha']:
                raise LedgerError('plan_workspace_base', 'the integration workspace starts at the plan origin')
            unremoved = self._owned()['workspaces']
            if (self._workspace_taken(path, cleanup_id)
                    or self._db.execute('SELECT 1 FROM plan_workspaces WHERE branch = ?', (branch,)).fetchone()
                    or any(path == item['path'] or cleanup_id == item['cleanup_id'] for item in unremoved)):
                raise LedgerError('workspace_conflict', 'the path, cleanup identity or branch already '
                                                        'belongs to a task, a plan or an unremoved workspace')
            members = self._rows('SELECT spec FROM tasks WHERE plan_id = ? AND id NOT IN '
                                 '(SELECT id FROM candidates) ORDER BY rowid', (plan_id,), ('spec',))
            scope = list(dict.fromkeys(name for member in members for name in member['spec']['write_scope']))
            workspace_id = self._db.execute(
                'INSERT INTO plan_workspaces(plan_id, epoch, purpose, path, cleanup_id, branch, base_sha, '
                "write_scope, fence, at) VALUES (?, ?, 'integration', ?, ?, ?, ?, ?, ?, ?)",
                (plan_id, self.epoch, path, cleanup_id, branch, base_sha, _canon(scope), self.fence,
                 _now())).lastrowid
            self._event('plan_workspace', plan_id, {
                'workspace': workspace_id, 'epoch': self.epoch, 'path': path, 'cleanup_id': cleanup_id,
                'branch': branch, 'base_sha': base_sha})
        return self.plan_workspace(plan_id)

    def _checkpoint_step(self, workspace, head, effect_id, result):
        """Verify, against the ledger's own journal, the confirmed effect a checkpoint rests
        on and return the contributions it yields. Initial: the plan-owned creation of this
        workspace at the registered origin. Afterwards: an ``integrate`` effect of a task
        of this plan that is accepted in the current context with exactly the journalled
        result, recorded against the current checkpoint, branch and worktree."""
        def need(fact):
            if not fact:
                raise LedgerError('checkpoint_effect', 'not the confirmed journalled effect of this '
                                                       'plan workspace that yields this checkpoint')

        rows = self._rows('SELECT task_id, plan_id, owner, kind, state, spec FROM effects WHERE id = ?',
                          (effect_id,), ('spec',))
        need(rows)
        effect, spec = rows[0], rows[0]['spec']
        need((effect['plan_id'], effect['state'], spec.get('workspace'))
             == (workspace['plan_id'], 'done', workspace['id']))
        if head is None:
            need((effect['owner'], effect['kind']) == ('plan', 'worktree.create')
                 and result == workspace['base_sha'])
            return {}
        need((effect['owner'], effect['kind']) == ('task', 'integrate'))
        task, inner = self._task(effect['task_id']), spec.get('fx')
        binding = self._binding(task['id'])
        need(task['state'] in DONE_STATES and _is_sha(task['result']) and binding is not None
             and binding['epoch'] == self.epoch and type(inner) is dict)
        need((spec.get('expected_base'), spec.get('result'), spec.get('branch'))
             == (head['sha'], task['result'], workspace['branch']))
        need((inner.get('expected_base'), inner.get('task_result'), inner.get('target_branch'),
              inner.get('integration_worktree'))
             == (head['sha'], task['result'], workspace['branch'], workspace['path']))
        return {**head['contributions'], task['id']: task['result']}

    def record_checkpoint(self, plan_id, expected_sha, result_sha, contributions, effect_id, observation):
        """Append the confirmed head of the plan workspace (compare-and-set).

        Initial (``expected_sha`` None): ``effect_id`` is the confirmed plan-owned
        ``worktree.create``, ``result_sha`` the registered origin and ``contributions``
        empty. Afterwards ``expected_sha`` must be the current checkpoint and
        ``effect_id`` a confirmed ``integrate`` effect of a task of this plan that is
        accepted in the current context with exactly the journalled result (see
        _checkpoint_step); ``contributions`` is the current mapping with only that task
        added or replaced. ``observation`` is the typed engine fact described at
        _observed. The same effect with the same facts returns the existing checkpoint;
        anything else for that effect is ``checkpoint_conflict`` and a stale
        ``expected_sha`` is ``checkpoint_stale``. Recording needs the current context but
        no running control: it retains a fact about finished work and grants nothing.
        Returns the checkpoint view."""
        if not _is_sha(result_sha) or not (expected_sha is None or _is_sha(expected_sha)):
            raise LedgerError('checkpoint_sha', 'checkpoint ids must be full 40- or 64-hex commit ids')
        if not (type(contributions) is dict
                and all(type(tid) is str and _is_sha(sha) for tid, sha in contributions.items())):
            raise LedgerError('checkpoint_contributions', 'contributions must map task ids to full result ids')
        if type(effect_id) is not int:
            raise LedgerError('checkpoint_effect', 'a checkpoint names the journalled effect it rests on')
        with self._tx():
            self._plan_row(plan_id)
            workspace = self._plan_ws(plan_id, self.epoch)
            if workspace is None:
                raise LedgerError('plan_workspace_required', 'the plan has no integration workspace '
                                                             'registered in the current context')
            facts = _observed(observation, result_sha, workspace,
                              {workspace['base_sha'], *contributions.values()})
            known = self._rows('SELECT * FROM checkpoints WHERE effect_id = ?', (effect_id,), _CHECKPOINT_JSON)
            if known:
                view = self._checkpoint_view(known[0])
                if (view['workspace_id'], view['expected'], view['sha'], view['contributions'],
                        view['observation']) != (workspace['id'], expected_sha, result_sha, contributions, facts):
                    raise LedgerError('checkpoint_conflict', 'this effect already yielded another checkpoint')
                return view
            self._require_context()
            state = self._ws_state(workspace)
            if state != 'created':
                raise LedgerError('plan_workspace_state', f'the plan workspace is {state}')
            head = self._head(workspace['id'])
            if expected_sha != (None if head is None else head['sha']):
                raise LedgerError('checkpoint_stale', 'expected_sha is not the current checkpoint')
            if contributions != self._checkpoint_step(workspace, head, effect_id, result_sha):
                raise LedgerError('checkpoint_contributions', 'only the integrated task contribution may '
                                                              'be added or replaced')
            checkpoint_id = self._db.execute(
                'INSERT INTO checkpoints(plan_id, epoch, workspace_id, previous, sha, contributions, '
                'effect_id, observation, fence, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (plan_id, self.epoch, workspace['id'], None if head is None else head['id'], result_sha,
                 _canon(contributions), effect_id, _canon(facts), self.fence, _now())).lastrowid
            self._event('checkpoint', plan_id, {
                'checkpoint': checkpoint_id, 'workspace': workspace['id'], 'expected': expected_sha,
                'sha': result_sha, 'contributions': contributions, 'effect': effect_id})
        return self.checkpoint(plan_id)

    def _checkpointed(self, plan_id, result, contributions, integrations):
        """A candidate must be exactly the current confirmed checkpoint of the plan's created
        workspace in this context, and every cited integration must be the journalled step
        that last set that contribution (the ledger's own registry, not a caller fact)."""
        workspace = self._plan_ws(plan_id, self.epoch)
        head = None if workspace is None else self._head(workspace['id'])
        if (head is None or self._ws_state(workspace) != 'created'
                or (head['sha'], head['contributions']) != (result, contributions)):
            raise LedgerError('checkpoint_stale', 'the candidate must be the current confirmed checkpoint '
                                                  'of the created plan workspace')
        steps = {row['task_id']: row['effect_id'] for row in self._db.execute(
            'SELECT e.task_id, c.effect_id FROM checkpoints c JOIN effects e ON e.id = c.effect_id '
            'WHERE c.workspace_id = ? AND c.previous IS NOT NULL ORDER BY c.id', (workspace['id'],))}
        if steps != integrations:
            raise LedgerError('integration_unproven', 'cite the checkpointed integration of every '
                                                      'contribution')

    def _integrated(self, integrations, contributions):
        """Each cited integration must be a resolved ``integrate`` effect of that very task,
        recorded for exactly the contributing result (the ledger's own journal, not a
        caller fact)."""
        for task_id, effect_id in integrations.items():
            rows = self._rows('SELECT task_id, kind, state, spec FROM effects WHERE id = ?',
                              (effect_id,), ('spec',))
            if (not rows or (rows[0]['task_id'], rows[0]['kind'], rows[0]['state'])
                    != (task_id, 'integrate', 'done')
                    or rows[0]['spec'].get('result') != contributions[task_id]):
                raise LedgerError('integration_unproven', f'{task_id} has no resolved integration '
                                                          'effect for this result')

    def _supersede(self, plan_id, successor):
        """Retire the newest candidate of a plan in favour of ``successor`` and return the
        next revision number. Revisions are bounded by limits.max_attempts over the whole
        history of the plan. A candidate with an unsettled attempt or effect is not
        replaced. Its rows, attempts, evidence and effects stay; a published one keeps
        its state and nothing remote is rolled back."""
        row = self._db.execute(
            'SELECT c.id, c.revision, t.state FROM candidates c JOIN tasks t ON t.id = c.id '
            'WHERE c.plan_id = ? ORDER BY c.revision DESC LIMIT 1', (plan_id,)).fetchone()
        if row is None:
            return 1
        if row['revision'] >= int(self.policy['limits']['max_attempts']):
            raise LedgerError('candidate_revisions', 'candidate revision limit reached')
        busy = self._db.execute(
            f'SELECT 1 FROM attempts WHERE task_id = ? AND state IN {_ACTIVE_SQL} UNION ALL '
            "SELECT 1 FROM effects WHERE task_id = ? AND state IN ('intent','unknown')",
            (row['id'], row['id'])).fetchone()
        if busy:
            raise LedgerError('candidate_busy', 'settle the attempts and effects of the current '
                                                'candidate first')
        if row['state'] != 'published':
            self._db.execute("UPDATE bindings SET state = 'invalidated', ended_at = ?, reason = ? "
                             "WHERE task_id = ? AND state = 'active'",
                             (_now(), 'superseded by ' + successor, row['id']))
            self._db.execute("UPDATE tasks SET state = 'superseded' WHERE id = ?", (row['id'],))
        self._event('candidate_superseded', row['id'], {'by': successor, 'from': row['state']})
        return row['revision'] + 1

    def create_candidate(self, plan_id, result_sha, contributions, checks, workspace,
                         integration_evidence):
        """Record the derived publication candidate of a whole plan: origin..``result_sha``.

        ``contributions`` maps EVERY task of the plan to its exact current accepted
        result; ``checks`` is the exact duplicate-free union of their declared checks;
        ``workspace`` is exactly ``{path, cleanup_id}`` inside the state workspace (a
        separate review worktree); ``integration_evidence`` is the typed engine
        observation described at _integration. Each contribution must be accepted with
        that result under a binding of the current context with unchanged dependencies,
        and its cited integration must be a resolved ``integrate`` effect recorded for
        that result. ``result_sha`` and ``contributions`` must also be exactly the current
        checkpoint of the plan's created workspace, with each cited integration the step
        that checkpoint chain recorded (see _checkpointed); the candidate workspace is its
        own and never the plan workspace. The engine queries Git itself before calling;
        the ledger runs no Git and takes no worker fact.

        The candidate is an immutable ``candidates`` row plus an internal task row of
        kind ``candidate`` bound to the plan origin with the integrated result. It starts
        without any evidence: its own checks (claim_check, record_check_outcome,
        finalize_checks) and a fresh review of origin..result (claim role ``review``,
        record_review) must pass before transition accepts it. It is never implemented.

        The id is derived from the plan, origin, result, contributions with their binding
        ids, checks and the current context. An identical call returns the existing view
        (restart-safe, whatever its stage; a failed candidate is not reset); the same
        identity with another workspace or evidence is ``candidate_conflict``. Any other
        input is a new revision that supersedes the previous one (history kept), bounded
        per plan by limits.max_attempts (``candidate_revisions``); every candidate attempt
        is charged to the plan time budget. Returns the candidate view."""
        if not _is_sha(result_sha):
            raise LedgerError('candidate_result', 'result_sha must be a full 40- or 64-hex commit id')
        if not (type(contributions) is dict and contributions
                and all(type(tid) is str and _is_sha(sha) for tid, sha in contributions.items())):
            raise LedgerError('candidate_contributions', 'contributions must map task ids to full result ids')
        if not (type(checks) is list and all(type(name) is str for name in checks)
                and len(set(checks)) == len(checks)):
            raise LedgerError('candidate_checks', 'checks must be a list of unique check names')
        if not (type(workspace) is dict and set(workspace) == {'path', 'cleanup_id'}):
            raise LedgerError('candidate_workspace', 'workspace must be exactly {path, cleanup_id}')
        path, cleanup = self._workspace_ident(workspace, 'candidate_workspace')
        with self._tx() as control:
            plan = None if type(plan_id) is not str else self._db.execute(
                'SELECT digest, base_sha, epoch FROM plans WHERE id = ?', (plan_id,)).fetchone()
            if plan is None:
                raise LedgerError('unknown_plan', str(plan_id))
            members = self._rows('SELECT id, spec, state, result FROM tasks WHERE plan_id = ? AND id '
                                 'NOT IN (SELECT id FROM candidates) ORDER BY rowid', (plan_id,), ('spec',))
            if set(contributions) != {member['id'] for member in members}:
                raise LedgerError('candidate_contributions', 'name exactly every task of the plan')
            union = list(dict.fromkeys(name for member in members for name in member['spec']['checks']))
            if set(checks) != set(union):
                raise LedgerError('candidate_checks', 'checks must be the exact union of the declared checks')
            evidence = _integration(integration_evidence, plan['base_sha'], result_sha, contributions)
            bindings = {member['id']: self._binding(member['id']) for member in members}
            bound = {tid: {'result': contributions[tid], 'binding': None if binding is None else binding['id']}
                     for tid, binding in bindings.items()}
            candidate_id = CANDIDATE_PREFIX + digest({
                'plan': plan_id, 'plan_digest': plan['digest'], 'origin': plan['base_sha'],
                'result': result_sha, 'contributions': bound, 'checks': union, 'epoch': self.epoch,
                'policy': self.policy_digest, **self.identity})[:40]
            known = self._candidate(candidate_id)
            if known is not None:
                if (known['workspace'], known['evidence']) != (workspace, evidence):
                    raise LedgerError('candidate_conflict', 'this candidate is recorded with another '
                                                            'workspace or integration evidence')
                view = self._candidate_view(known)
                if view['hold'] == 'superseded':
                    raise LedgerError('candidate_superseded', 'a newer candidate replaced this one')
                return view
            if control != 'running':
                raise LedgerError('control_' + control, 'new candidates are blocked')
            self._require_context()
            if plan['epoch'] != self.epoch:
                raise LedgerError('plan_stale', 'the plan was admitted under an earlier context; '
                                                'readmit_plan is required')
            for member in members:
                binding = bindings[member['id']]
                if (member['state'] not in DONE_STATES or member['result'] != contributions[member['id']]
                        or binding is None or binding['epoch'] != self.epoch):
                    raise LedgerError('contribution_stale', f"{member['id']} is not accepted with this "
                                                            'result in the current context')
                self._check_dependencies(binding['dependencies'])
            for name in union:
                if name not in self.policy['allowed_checks']:
                    raise LedgerError('check_not_allowed', name)
            self._integrated(evidence['integrations'], contributions)
            self._checkpointed(plan_id, result_sha, contributions, evidence['integrations'])
            if self._db.execute('SELECT 1 FROM tasks WHERE id = ?', (candidate_id,)).fetchone():
                raise LedgerError('candidate_id', 'a task already uses the derived candidate id')
            revision = self._supersede(plan_id, candidate_id)
            if self._workspace_taken(path, cleanup):
                raise LedgerError('workspace_conflict', 'workspace is bound to another task or plan')
            resources = list(dict.fromkeys(name for member in members
                                           for name in member['spec']['resources']))
            spec = {'id': candidate_id, 'kind': CANDIDATE_KIND,
                    'objective': f'Derived publication candidate {revision} of plan {plan_id}',
                    'depends_on': [member['id'] for member in members], 'write_scope': [],
                    'resources': resources, 'checks': union,
                    'acceptance': ['every declared check of the plan passes on the integrated result',
                                   'a fresh independent review approves origin..result']}
            now = _now()
            self._db.execute('INSERT INTO tasks(id, plan_id, spec, state, result) VALUES (?, ?, ?, ?, ?)',
                             (candidate_id, plan_id, _canon(spec), 'implemented' if union else 'checked',
                              result_sha))
            binding_id = self._db.execute(
                'INSERT INTO bindings(task_id, epoch, execution_base, dependencies, workspace, evidence, '
                "state, fence, at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (candidate_id, self.epoch, plan['base_sha'], _canon(contributions), _canon(workspace),
                 _canon(evidence), self.fence, now)).lastrowid
            self._db.execute(
                'INSERT INTO candidates(id, plan_id, revision, epoch, origin, result, contributions, '
                'checks, workspace, evidence, fence, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (candidate_id, plan_id, revision, self.epoch, plan['base_sha'], result_sha, _canon(bound),
                 _canon(union), _canon(workspace), _canon(evidence), self.fence, now))
            self._event('candidate', candidate_id, {
                'plan': plan_id, 'revision': revision, 'origin': plan['base_sha'], 'result': result_sha,
                'contributions': bound, 'checks': union, 'binding': binding_id, 'epoch': self.epoch})
        return self.candidate(candidate_id)

    def claim(self, task_id, profile_id, role='implement'):
        """Atomically reserve an attempt, its plan time budget, capacity and scopes. The
        reserved row is the durable launch intent; nothing ever requeues it by expiry.
        A claim is not a release: see record_launch and authorize_release.

        Needs the current context (no hold, plan not stale) and an execution binding
        whose dependency results are still the accepted ones.

        Budgets are per lane (see the module docstring): closes attributed to
        availability, operator or execution do not consume ``max_attempts``, but every
        launch counts toward the derived dispatch limit (``dispatch_exhausted``).

        A profile is an account, not a session, so it is not a mutex: policy
        ``max_parallel`` is the only session-concurrency authority. Every active attempt,
        reviewers included, excludes the resources its task declares."""
        limits, db = self.policy['limits'], self._db
        with self._tx() as control:
            if control != 'running':
                raise LedgerError('control_' + control, 'claims are blocked')
            if not self.policy.get('execution_enabled'):
                raise LedgerError('execution_disabled', 'policy does not enable execution')
            self._require_context()
            profile = next((p for p in self.policy['profiles'] if p['id'] == profile_id), None)
            if profile is None or role not in ROLES or role not in profile['roles']:
                raise LedgerError('profile_role', 'profile is not allowed this role')
            task = self._task(task_id)
            self._live(task)
            if role == 'implement' and self._candidate(task_id) is not None:
                raise LedgerError('candidate_derived', 'a derived candidate is never implemented')
            self._derived(task)
            spec = json.loads(task['spec'])
            if task['state'] != ('pending' if role == 'implement' else 'checked'):
                raise LedgerError('task_state', f"task is {task['state']}")
            active = self._active()
            if any(row['task_id'] == task_id for row in active):
                raise LedgerError('task_busy', 'task has an unresolved attempt')
            capacity = int(self.policy['max_parallel'])
            implementing = role == 'implement'
            if implementing:
                states = {row[0]: row[1] for row in db.execute('SELECT id, state FROM tasks')}
                if any(states.get(dep) not in DONE_STATES for dep in spec['depends_on']):
                    raise LedgerError('dependencies', 'dependencies are not accepted')
            binding = self._binding(task_id)
            if binding is None:
                raise LedgerError('binding_required', 'bind_execution must record the task base first')
            if implementing:
                self._check_dependencies(binding['dependencies'])
            for other in active:
                held = json.loads(other['spec'])
                if set(spec['resources']) & set(held['resources']):
                    raise LedgerError('resource_conflict', other['task_id'])
                if (implementing and other['role'] == 'implement'
                        and _overlap(spec['write_scope'], held['write_scope'])):
                    raise LedgerError('scope_conflict', other['task_id'])
            if implementing:
                reviewing = {row['task_id'] for row in active if row['role'] == 'review'}
                if any(state == 'checked' and tid not in reviewing and self._reviewable(tid)
                       for tid, state in states.items()):
                    capacity -= int(self.policy['review_reserve'])
            if len(active) >= capacity:
                raise LedgerError('capacity', 'no free slot (review reserve included)')
            self._admit_dispatch(task, role)
            seconds = int(limits['attempt_seconds'])
            if self._charged(task['plan_id']) + seconds > limits['max_total_seconds']:
                raise LedgerError('time_budget', "the plan's runtime budget would be exceeded")
            attempt_id = db.execute(
                'INSERT INTO attempts(task_id, profile_id, role, state, fence, reserved_seconds, '
                "created_at, epoch) VALUES (?, ?, ?, 'reserved', ?, ?, ?, ?)",
                (task_id, profile_id, role, self.fence, seconds, _now(), self.epoch)).lastrowid
            if role == 'implement':
                self._cas("UPDATE tasks SET state = 'implementing' WHERE id = ? AND state = 'pending'",
                          (task_id,))
            self._event('claim', attempt_id, {'task': task_id, 'profile': profile_id, 'role': role,
                                              'binding': binding['id']})
        return self._attempt(attempt_id)

    def claim_check(self, task_id, check_name):
        """Atomically reserve one declared check of the task's current result as a real
        owned local command: an attempt of role ``check`` with no profile (a local check
        is not a provider and never a native success). It holds the task's declared
        resources, a ``max_parallel`` slot and the plan time reservation until it is
        finished, exactly like any other attempt, and uses the same record_launch,
        authorize_release, finish_attempt and STOP cleanup.

        Needs the current context, a task in ``implemented`` with an execution binding,
        and a check that is both declared by the task and allowed by policy. One attempt
        per task at a time, so checks of one task run one after another. A check whose
        current result already has a PASS or FAIL row is ``check_settled``. The attempt
        records the exact result it was claimed for."""
        limits, db = self.policy['limits'], self._db
        with self._tx() as control:
            if control != 'running':
                raise LedgerError('control_' + control, 'claims are blocked')
            if not self.policy.get('execution_enabled'):
                raise LedgerError('execution_disabled', 'policy does not enable execution')
            self._require_context()
            task = self._task(task_id)
            self._live(task)
            self._derived(task)
            spec = json.loads(task['spec'])
            if (type(check_name) is not str or check_name not in spec['checks']
                    or check_name not in self.policy['allowed_checks']):
                raise LedgerError('check_not_allowed', str(check_name))
            if task['state'] != 'implemented':
                raise LedgerError('task_state', f"task is {task['state']}")
            binding = self._binding(task_id)
            if binding is None:
                raise LedgerError('binding_required', 'bind_execution must record the task base first')
            expected = self._expected(task)
            if expected is None:
                raise LedgerError('task_state', 'the task has no result to check')
            if self._check_states(task_id, [check_name], _canon(expected))[check_name] in ('PASS', 'FAIL'):
                raise LedgerError('check_settled', 'this check already has a verdict for the current result')
            active = self._active()
            if any(row['task_id'] == task_id for row in active):
                raise LedgerError('task_busy', 'task has an unresolved attempt')
            for other in active:
                if set(spec['resources']) & set(json.loads(other['spec'])['resources']):
                    raise LedgerError('resource_conflict', other['task_id'])
            if len(active) >= int(self.policy['max_parallel']):
                raise LedgerError('capacity', 'no free slot')
            self._admit_dispatch(task, CHECK_ROLE, check_name)
            seconds = int(limits['attempt_seconds'])
            if self._charged(task['plan_id']) + seconds > limits['max_total_seconds']:
                raise LedgerError('time_budget', "the plan's runtime budget would be exceeded")
            attempt_id = db.execute(
                'INSERT INTO attempts(task_id, role, check_name, state, fence, reserved_seconds, result, '
                "created_at, epoch) VALUES (?, ?, ?, 'reserved', ?, ?, ?, ?, ?)",
                (task_id, CHECK_ROLE, check_name, self.fence, seconds, task['result'], _now(),
                 self.epoch)).lastrowid
            self._event('claim', attempt_id, {'task': task_id, 'profile': None, 'role': CHECK_ROLE,
                                              'check': check_name, 'binding': binding['id'],
                                              'result': task['result']})
        return self._attempt(attempt_id)

    def record_launch(self, attempt_id, identity):
        """Retain the identity of a spawned, still-held child (``pid`` required) so it can
        be found and cleaned up. Works in every control state, including after STOP, and
        grants nothing: only authorize_release permits the child to start working."""
        if not (type(identity) is dict and type(identity.get('pid')) is int and identity['pid'] > 0
                and len(_canon(identity)) <= 4096):
            raise LedgerError('launch_identity', 'launch identity must be a small object with a positive pid')
        with self._tx():
            self._cas("UPDATE attempts SET state = 'launched', launch = ? "
                      "WHERE id = ? AND state = 'reserved'", (_canon(identity), attempt_id))
            self._event('launch', attempt_id, {'identity': identity})
        return self._attempt(attempt_id)

    def authorize_release(self, attempt_id):
        """The only release grant. Succeeds once for a launched attempt while control is
        ``running`` and the context is not held; otherwise the denial is recorded and
        raised so the engine keeps the child held and cleans it up through
        owned_work/finish_attempt."""
        with self._tx() as control:
            attempt = self._attempt(attempt_id)
            if attempt['state'] != 'launched' or attempt['released_at'] is not None:
                raise LedgerError('conflict', 'attempt is not launched and unreleased')
            denied = None if control == 'running' else 'control_' + control
            if denied is None and self._lease.identity != self.identity:
                denied = 'context_hold'
            if denied is None:
                task = self._task(attempt['task_id'])
                candidate = self._candidate(task['id'])
                if candidate is not None and self._candidate_hold(task, candidate) is not None:
                    denied = 'candidate_stale'
            if denied is None:
                self._cas("UPDATE attempts SET released_at = ? WHERE id = ? AND state = 'launched' "
                          'AND released_at IS NULL', (_now(), attempt_id))
                self._event('release', attempt_id, {'control': control})
            else:
                self._event('release_denied', attempt_id, {'control': control, 'reason': denied})
        if denied is not None:
            raise LedgerError(denied, 'release is not authorized; clean up the held child')
        return self._attempt(attempt_id)

    def finish_attempt(self, attempt_id, outcome, reconciled, result=None, used_seconds=None,
                       attribution=None, reason=None, category=None):
        """Close an attempt only when ``reconciled`` is exactly True; otherwise it stays
        held as unknown with its full reservation charged. ``used_seconds`` is the
        measured runtime: omitted charges the reservation, an overrun is retained as
        measured. ``result`` is a full 40- or 64-hex object id or digest. Allowed in every
        control state, because finishing is cleanup.

        ``success`` is admitted only for an attempt that is still ``launched``, retains a
        positive launch identity and was released by authorize_release; anything else is
        refused as ``not_released`` and changes nothing. Failure, cancelled and unknown
        need no release, so reserved, held and stopped attempts can always be closed.

        Attribution takes fixed values only (ATTRIBUTIONS, REASONS, PROVIDER_CATEGORIES).
        A success carries none and is refused next to any category but ``success``. A
        native ``failure`` defaults to ``semantic``; ``cancelled`` and every non-success
        close of a check attempt must name availability, operator or execution with a
        reason. Only a semantic close adds to failures and the no-progress streak and
        consumes the semantic attempt budget; the others requeue an implementation or
        leave a checked task waiting for another review. A check attempt keeps the result
        it was claimed for and never changes the task: a finished check process is not a
        verdict (see record_check_outcome)."""
        if outcome not in OUTCOMES:
            raise LedgerError('outcome', str(outcome))
        if type(reconciled) is not bool:
            raise LedgerError('strict_type', 'reconciled must be a boolean')
        used = _seconds(used_seconds)
        if result is not None and not _is_sha(result):
            raise LedgerError('result_identity', 'result must be a full 40- or 64-hex object id or digest')
        if ((attribution is not None and attribution not in ATTRIBUTIONS)
                or (reason is not None and (attribution is None or reason not in REASONS[attribution]))
                or (category is not None and category not in PROVIDER_CATEGORIES)):
            raise LedgerError('attribution', 'attribution, reason and category take fixed enumerated values')
        with self._tx():
            attempt = self._attempt(attempt_id)
            if attempt['state'] == 'finished':
                raise LedgerError('conflict', 'attempt is already finished')
            if not reconciled or outcome == 'unknown':
                self._cas("UPDATE attempts SET state = 'unknown' WHERE id = ? AND state = ?",
                          (attempt_id, attempt['state']))
                self._event('attempt_unknown', attempt_id, {
                    'reported': outcome, 'attribution': attribution, 'reason': reason,
                    'category': category})
            else:
                implement, local = attempt['role'] == 'implement', attempt['role'] == CHECK_ROLE
                if outcome == 'success' and not (attempt['state'] == 'launched' and _released(attempt)):
                    raise LedgerError('not_released', 'success needs a launched attempt with a retained '
                                                      'launch identity and an authorized release')
                if outcome == 'success' and implement and result is None:
                    raise LedgerError('result_required', 'success needs a result identity')
                if local and result not in (None, attempt['result']):
                    raise LedgerError('result_identity', 'a check attempt keeps the result it was claimed for')
                owner, cause = _attribute(outcome, local, attribution, reason, category)
                stored = attempt['result'] if local else result
                reserved = attempt['reserved_seconds']
                charged = reserved if used is None else used
                self._cas("UPDATE attempts SET state = 'finished', outcome = ?, result = ?, "
                          'used_seconds = ?, finished_at = ?, attribution = ?, reason = ?, category = ? '
                          'WHERE id = ? AND state = ?',
                          (outcome, stored, charged, _now(), owner, cause, category, attempt_id,
                           attempt['state']))
                task_id = attempt['task_id']
                if outcome == 'success' and implement:
                    checks = json.loads(self._task(task_id)['spec'])['checks']
                    self._cas("UPDATE tasks SET state = ?, result = ? WHERE id = ? AND state = 'implementing'",
                              ('implemented' if checks else 'checked', result, task_id))
                elif implement:
                    self._requeue(task_id, 'implementing', owner == 'semantic')
                elif owner == 'semantic':
                    self._db.execute('UPDATE tasks SET failures = failures + 1, '
                                     'no_progress = no_progress + 1 WHERE id = ?', (task_id,))
                self._event('finish', attempt_id, {'outcome': outcome, 'result': stored,
                                                   'used': charged, 'reserved': reserved,
                                                   'attribution': owner, 'reason': cause,
                                                   'category': category})
        return self._attempt(attempt_id)

    def record_check_outcome(self, task_id, name, status, identity, receipt_refs, attempt_id):
        """Retain the outcome of one declared check: ``status`` is PASS, FAIL or INCOMPLETE.
        The task state never changes here, so every declared result is stored before
        finalize_checks aggregates. Returns the evidence id.

        ``attempt_id`` must be a finished check attempt of this task and check, made in
        the current context for exactly the current result, newer than the newest
        implementation and not used for another outcome. PASS and FAIL additionally need
        that attempt to have finished ``success`` after a retained launch and an
        authorized release, and ``receipt_refs`` (see _receipt) to name the current
        result as its checked input. INCOMPLETE keeps whatever reference exists.

        Trust boundary: the ledger reads no receipt or lifecycle file and runs nothing.
        The fixed engine verified the v1 receipt and the shared process lifecycle; this
        records which attempt and which receipt identity that verdict rests on."""
        if type(status) is not str or status not in CHECK_STATUSES:
            raise LedgerError('check_status', 'status must be PASS, FAIL or INCOMPLETE')
        if type(attempt_id) is not int:
            raise LedgerError('check_attempt', 'a check outcome names its check attempt')
        receipt = _receipt(status, receipt_refs)
        decisive = status != 'INCOMPLETE'
        with self._tx():
            self._require_context()
            task = self._task(task_id)
            self._live(task)
            if task['state'] != 'implemented':
                raise LedgerError('task_state', f"task is {task['state']}")
            if (type(name) is not str or name not in json.loads(task['spec'])['checks']
                    or name not in self.policy['allowed_checks']):
                raise LedgerError('check_not_allowed', str(name))
            self._derived(task)
            gate = self._gate(task, identity)
            attempt = self._attempt(attempt_id)
            newest = self._db.execute(
                'SELECT MAX(id) FROM attempts WHERE task_id = ? AND role = ?',
                (task_id, 'implement')).fetchone()[0]
            reused = self._db.execute('SELECT 1 FROM evidence WHERE attempt_id = ?', (attempt_id,)).fetchone()
            facts = (attempt['task_id'], attempt['role'], attempt['check_name'], attempt['state'],
                     attempt['epoch'], attempt['result'])
            if (facts != (task_id, CHECK_ROLE, name, 'finished', self.epoch, task['result'])
                    or (newest is not None and attempt_id < newest) or reused
                    or (decisive and not (attempt['outcome'] == 'success' and _released(attempt)))):
                raise LedgerError('check_attempt', 'not a finished check attempt of the current result')
            if decisive and receipt['input_sha'] != task['result']:
                raise LedgerError('receipt_mismatch', 'the receipt checked another input')
            evidence_id = self._db.execute(
                'INSERT INTO evidence(task_id, kind, name, passed, status, identity, attempt_id, receipt, '
                "at, epoch) VALUES (?, 'check', ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, name, int(status == 'PASS'), status, gate, attempt_id,
                 None if receipt is None else _canon(receipt), _now(), self.epoch)).lastrowid
            self._event('check', task_id, {'name': name, 'status': status, 'attempt': attempt_id,
                                           'evidence': evidence_id})
        return evidence_id

    def finalize_checks(self, task_id, identity):
        """Aggregate the declared checks of the current result for the exact gate identity.

        A recorded FAIL makes the aggregate FAIL at once: it outranks a missing row and an
        INCOMPLETE one. While a declared check still has no row the FAIL is only reported
        (``collection_pending``): the result, its rows and the state are kept, so the
        remaining independent checks can still be claimed and recorded. Once every
        declared check has a row the FAIL is charged as a semantic failure and the task is
        requeued; its rows, attempts and the failed result stay in history. FAIL means the
        declared check failed for this result; it does not establish why. Without a FAIL,
        a missing or INCOMPLETE row holds the result (INCOMPLETE) for another bounded check
        attempt or owner resolution, and only all PASS moves the task to ``checked`` for a
        fresh review. A task that declares no checks never passes through here and no
        zero-check PASS is recorded.

        Returns ``{status, checks, missing, collection_pending, state}``."""
        with self._tx():
            self._require_context()
            task = self._task(task_id)
            self._live(task)
            if task['state'] != 'implemented':
                raise LedgerError('task_state', f"task is {task['state']}")
            self._derived(task)
            checks = json.loads(task['spec'])['checks']
            states = self._check_states(task_id, checks, self._gate(task, identity))
            aggregate = _aggregate(states)
            missing = [name for name in checks if states[name] is None]
            pending = aggregate == 'FAIL' and bool(missing)
            state = 'implemented'
            if aggregate == 'PASS':
                state = 'checked'
                self._cas("UPDATE tasks SET state = 'checked' WHERE id = ? AND state = 'implemented'",
                          (task_id,))
            elif aggregate == 'FAIL' and not pending:
                state = 'pending'
                self._requeue(task_id, 'implemented', True)
            self._event('checks_final', task_id, {'aggregate': aggregate, 'result': task['result'],
                                                  'checks': states, 'missing': missing,
                                                  'collection_pending': pending})
        return {'status': aggregate, 'checks': states, 'missing': missing,
                'collection_pending': pending, 'state': state}

    def note_progress(self, task_id, fingerprint, reason):
        """Record verified progress and clear the consecutive no-progress count.

        Trusted-engine oracle only: ``fingerprint`` must be a digest the fixed engine
        computed itself over the verified content of the current result (for example the
        tree object id of the task scope). Never pass producer-reported text, a commit id
        (an empty commit changes it) or anything derived from logs. The ledger accepts it
        only while the current result has every declared check passing for the recorded
        identity in the current context, and only when neither this fingerprint nor this
        result has already counted for the task, so restarts, retries and repeated content
        never reset the count. Historical failures and the attempt and time caps are
        never reset. Returns True when the count was cleared."""
        if not _is_sha(fingerprint):
            raise LedgerError('fingerprint', 'fingerprint must be a full 40- or 64-hex digest')
        if type(reason) is not str or not reason.strip() or len(reason) > 500:
            raise LedgerError('reason', 'progress needs a short audit reason')
        with self._tx():
            task = self._task(task_id)
            checks = json.loads(task['spec'])['checks']
            expected = self._expected(task)
            if (task['state'] not in PROGRESS_STATES or expected is None
                    or not self._checks_pass(task_id, checks, _canon(expected))):
                raise LedgerError('progress_unverified', 'the current result has no passing check evidence')
            fresh = self._db.execute(
                'SELECT 1 FROM progress WHERE task_id = ? AND (fingerprint = ? OR result = ?)',
                (task_id, fingerprint, task['result'])).fetchone() is None
            if fresh:
                self._db.execute(
                    'INSERT INTO progress(task_id, fingerprint, result, reason, cleared, fence, at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (task_id, fingerprint, task['result'], reason, task['no_progress'], self.fence, _now()))
                self._db.execute('UPDATE tasks SET no_progress = 0, progress = ? WHERE id = ?',
                                 (fingerprint, task_id))
            self._event('progress' if fresh else 'progress_repeat', task_id, {
                'fingerprint': fingerprint, 'result': task['result'], 'reason': reason,
                'cleared': task['no_progress'] if fresh else 0})
        return fresh

    def record_review(self, task_id, attempt_id, verdict, identity):
        """Record the verdict of a completed, released review attempt made in the current
        context. The reviewer's range is the task's bound execution base..result; for a
        derived candidate that is the plan origin..integrated result, and only a review
        attempt claimed on the candidate itself counts."""
        if verdict not in ('approve', 'reject'):
            raise LedgerError('verdict', str(verdict))
        with self._tx():
            self._require_context()
            task, attempt = self._task(task_id), self._attempt(attempt_id)
            self._live(task)
            if task['state'] != 'checked':
                raise LedgerError('task_state', f"task is {task['state']}")
            self._derived(task)
            gate = self._gate(task, identity)
            newest = self._db.execute("SELECT MAX(id) FROM attempts WHERE task_id = ? AND role = 'implement'",
                                      (task_id,)).fetchone()[0]
            reused = self._db.execute('SELECT 1 FROM evidence WHERE attempt_id = ?', (attempt_id,)).fetchone()
            if ((attempt['task_id'], attempt['role'], attempt['state'], attempt['outcome'])
                    != (task_id, 'review', 'finished', 'success')
                    or (newest is not None and attempt_id < newest) or reused
                    or attempt['epoch'] != self.epoch or not _released(attempt)):
                raise LedgerError('review_attempt', 'not a completed review of the current result')
            self._db.execute(
                "INSERT INTO evidence(task_id, kind, name, passed, status, identity, attempt_id, at, epoch) "
                "VALUES (?, 'review', ?, ?, ?, ?, ?, ?, ?)",
                (task_id, attempt['profile_id'], int(verdict == 'approve'), verdict, gate, attempt_id,
                 _now(), self.epoch))
            if verdict == 'approve':
                self._cas("UPDATE tasks SET state = 'reviewed' WHERE id = ? AND state = 'checked'", (task_id,))
            else:
                self._requeue(task_id, 'checked', True)
            self._event('review', task_id, {'attempt': attempt_id, 'verdict': verdict})

    def transition(self, task_id, expected, new, identity=None):
        """Compare-and-set task state. Acceptance and publication need the current
        context, re-verify check and review evidence recorded in it for the exact
        identity tuple, and require every bound dependency result to still be the
        accepted one; a producer outcome alone can never accept."""
        if (expected, new) not in TRANSITIONS:
            raise LedgerError('transition', f'{expected} -> {new} is not permitted')
        with self._tx():
            task = self._task(task_id)
            if new in DONE_STATES:
                self._require_context()
                self._live(task)
                candidate = self._derived(task)
                gate = self._gate(task, identity)
                if not self._gates_hold(task, gate):
                    raise LedgerError('gates', 'check or review evidence is missing for this identity')
                if new == 'published' and candidate is not None:
                    self._governed(task, gate)
                self._check_dependencies(self._binding(task_id)['dependencies'])
            self._cas('UPDATE tasks SET state = ? WHERE id = ? AND state = ?', (new, task_id, expected))
            self._event('transition', task_id, {'from': expected, 'to': new})

    def _workspace_spec(self, task, kind, spec):
        """Internal worktree effects: only inside the controller-owned state workspace,
        tied to the task's declared scope and a cleanup identity. Creation is allowed
        only for the workspace the task's execution binding names."""
        path, cleanup = self._workspace_ident(spec, 'effect_workspace')
        scope = json.loads(task['spec'])['write_scope']
        if kind == 'worktree.remove':
            made = self._rows("SELECT spec FROM effects WHERE task_id = ? AND kind = 'worktree.create'",
                              (task['id'],), ('spec',))
            if not any((row['spec']['path'], row['spec']['cleanup_id']) == (path, cleanup) for row in made):
                raise LedgerError('effect_unauthorized', 'no controller-created workspace has this identity')
            return {**spec, 'write_scope': scope}
        binding = self._binding(task['id'])
        if binding is None:
            raise LedgerError('binding_required', 'bind_execution must record the workspace first')
        if binding['workspace'] != {'path': path, 'cleanup_id': cleanup}:
            raise LedgerError('effect_workspace', 'not the workspace bound to this task')
        stored = {**spec, 'write_scope': scope, 'execution_base': binding['execution_base']}
        candidate = self._derived(task)  # a candidate worktree is detached at its frozen result
        return stored if candidate is None else {**stored, 'result': candidate['result']}

    def _local_spec(self, task, effect, spec):
        """Spec to record for a local stage of an ordinary task. task.commit precedes the
        checks. integrate follows acceptance and targets only the plan's created workspace
        at its current checkpoint: the envelope names ``expected_base`` (that checkpoint),
        ``result`` (the accepted task result, filled in when omitted), ``branch`` (the
        registered integration branch) and the strict inner ``fx`` IntegrateSpec mapping,
        which must agree with all of them. One integration of a plan runs at a time and a
        confirmed one is checkpointed before the next (``checkpoint_pending``).
        record_checkpoint and create_candidate later verify this record. A derived
        candidate has neither stage."""
        if self._candidate(task['id']) is not None:
            raise LedgerError('candidate_derived', 'a derived candidate is never committed or '
                                                   'integrated itself')
        if effect != 'integrate':
            return dict(spec)
        if task['state'] not in DONE_STATES:
            raise LedgerError('task_state', 'integration follows acceptance')
        workspace = self._plan_ws(task['plan_id'], self.epoch)
        head = None if workspace is None else self._head(workspace['id'])
        if head is None or self._ws_state(workspace) != 'created':
            raise LedgerError('checkpoint_required', 'integration needs the created plan workspace '
                                                     'and its recorded checkpoint')
        inner = spec.get('fx')
        if not (type(inner) is dict and set(inner) == _FX_FIELDS['integrate']):
            raise LedgerError('effect_spec', 'fx must be the exact adapter spec mapping')
        wanted = (head['sha'], task['result'], workspace['branch'])
        if ((spec.get('expected_base'), spec.get('result', task['result']), spec.get('branch')) != wanted
                or (inner['expected_base'], inner['task_result'], inner['target_branch']) != wanted
                or (inner['integration_worktree'], inner['common_dir'])
                != (workspace['path'], self.common_dir)):
            raise LedgerError('stale_identity', 'not the accepted result of this task on the current '
                                                'checkpoint of the plan workspace')
        if self._unrecorded(workspace):
            raise LedgerError('checkpoint_pending', 'record the checkpoint of the confirmed '
                                                    'integration first')
        if self._db.execute("SELECT 1 FROM effects WHERE plan_id = ? AND kind = 'integrate' AND state IN "
                            "('intent','unknown')", (task['plan_id'],)).fetchone():
            raise LedgerError('effect_unresolved', 'reconcile the earlier integration of this plan first')
        return {**spec, 'result': task['result'], 'workspace': workspace['id']}

    def _publication_reviewers(self):
        """Ids of the owner-configured profiles that may review for publication."""
        return [profile['id'] for profile in self.policy['profiles']
                if profile['provider'] == PUBLICATION_PROVIDER and 'review' in profile['roles']]

    def _publication_hold(self, task, gate):
        """Fixed reason the publication governance is INCOMPLETE for ``gate``, else None.

        The newest review recorded for exactly this gate in the current context must
        approve, come from a configured ``codex`` review profile and rest on that
        profile's own finished, successful review attempt of this task with a retained
        launch identity and an authorized release. That one review also serves as the
        independent review; no second approval exists. Ledger evidence only: the engine
        separately verifies the native outcome."""
        reviewers = self._publication_reviewers()
        if not reviewers:
            return 'codex_unavailable'
        review = self._db.execute(
            "SELECT name, passed, attempt_id FROM evidence WHERE task_id = ? AND kind = 'review' "
            'AND identity = ? AND epoch = ? ORDER BY id DESC LIMIT 1',
            (task['id'], gate, self.epoch)).fetchone()
        if (review is None or review['passed'] != 1 or review['name'] not in reviewers
                or review['attempt_id'] is None):
            return 'codex_review_required'
        attempt = self._attempt(review['attempt_id'])
        facts = (attempt['task_id'], attempt['profile_id'], attempt['role'], attempt['state'],
                 attempt['outcome'], attempt['epoch'])
        if (facts != (task['id'], review['name'], 'review', 'finished', 'success', self.epoch)
                or not _released(attempt)):
            return 'codex_review_required'
        return None

    def _governed(self, task, gate):
        hold = self._publication_hold(task, gate)
        if hold is not None:
            raise LedgerError(hold, 'INCOMPLETE: publication needs a fresh approving review of this '
                                    'candidate by an owner-configured Codex profile; no other reviewer '
                                    'substitutes and an attended handoff is required without one')

    def _publication(self, task, spec):
        """Gate of every external effect. Only a CURRENT derived candidate that is accepted
        with its check and review evidence still holding is published, the spec must name
        its frozen result, and every external effect of one candidate uses one branch.
        The approval of an original task never publishes integrated code."""
        candidate = self._derived(task)
        if candidate is None:
            raise LedgerError('candidate_required', 'only a derived candidate is published; an '
                                                    'accepted task is not')
        expected = self._expected(task)
        if (task['state'] not in DONE_STATES or expected is None
                or not self._gates_hold(task, _canon(expected))):
            raise LedgerError('candidate_unaccepted', 'the candidate needs its own passing checks, a '
                                                      'fresh approving review and acceptance')
        self._governed(task, _canon(expected))
        if spec.get('result') != candidate['result']:
            raise LedgerError('candidate_mismatch', 'the effect must name the frozen candidate result')
        marks = ','.join('?' * len(_EXTERNAL_KINDS))
        earlier = self._rows(f'SELECT spec FROM effects WHERE task_id = ? AND kind IN ({marks})',
                             (task['id'], *_EXTERNAL_KINDS), ('spec',))
        if any(row['spec'].get('branch') != spec['branch'] for row in earlier):
            raise LedgerError('candidate_mismatch', 'a candidate is published on one branch')

    def _authorize_effect(self, task, kind, spec):
        """Map a catalog kind to the owner effect it needs and bind the spec to record.
        The grant is the fixed intersection of the current policy and the authority the
        plan was admitted with; a wider policy alone adds nothing."""
        if kind in WORKSPACE_EFFECTS:
            return None, self._workspace_spec(task, kind, spec)
        effect = EFFECT_CATALOG.get(kind)
        if (effect is None or effect not in self.policy['effects']
                or effect not in json.loads(task['authority'])['effects']):
            raise LedgerError('effect_unauthorized', kind)
        if effect not in EXTERNAL_EFFECTS:
            return effect, self._local_spec(task, effect, spec)
        try:
            stored = check_delivery_spec(effect, spec, self.policy['delivery'])
        except InputError as err:
            raise LedgerError('effect_target', str(err)) from err
        self._publication(task, stored)
        return effect, stored

    def effect_intent(self, task_id, kind, spec):
        """Record the intent for one catalog effect before it runs. ``kind`` is the engine
        catalog kind; the fixed EFFECT_CATALOG decides which owner effect authorizes it.
        External kinds are bound to the frozen policy.delivery target (recorded as
        ``target``) and are authorized only for a current accepted derived candidate whose
        frozen result the spec names (see _publication); task.commit and integrate stay
        local stages of an ordinary task, integrate only once it is accepted.
        worktree.create/remove need no owner effect but are confined to the
        state workspace; removal is cleanup and stays allowed under pause, STOP, a
        context hold and for stale plans. Everything else needs the current context."""
        if type(kind) is not str or type(spec) is not dict:
            raise LedgerError('effect_unauthorized', 'effect needs a catalog kind and an object spec')
        cleanup = kind == 'worktree.remove'
        with self._tx() as control:
            if control != 'running' and not cleanup:
                raise LedgerError('control_' + control, 'effects are blocked')
            task = self._task(task_id)
            if not cleanup:
                self._require_context()
                self._live(task)
            effect, stored = self._authorize_effect(task, kind, spec)
            if self._db.execute("SELECT 1 FROM effects WHERE task_id = ? AND kind = ? AND state IN "
                                "('intent','unknown')", (task_id, kind)).fetchone():
                raise LedgerError('effect_unresolved', 'reconcile the earlier effect first')
            effect_id = self._db.execute(
                'INSERT INTO effects(task_id, plan_id, owner, kind, spec, state, fence, at) '
                "VALUES (?, ?, 'task', ?, ?, 'intent', ?, ?)",
                (task_id, task['plan_id'], kind, _canon(stored), self.fence, _now())).lastrowid
            self._event('effect_intent', effect_id, {'task': task_id, 'kind': kind, 'effect': effect})
        return effect_id

    def _plan_spec(self, workspace, kind, spec):
        """Spec to record for a plan-owned worktree effect: the registered identity as top
        metadata plus the strict inner ``fx`` adapter mapping, which must name the same
        path, branch and origin and this repository. Removal is confined to the state
        workspace root; its ``expected_head`` is typed here and checked by the adapter."""
        inner = spec.get('fx')
        if not (type(inner) is dict and set(inner) == _FX_FIELDS[kind]):
            raise LedgerError('effect_spec', 'fx must be the exact adapter spec mapping')
        same = (all(spec.get(key) == workspace[key] for key in ('path', 'cleanup_id', 'branch'))
                and (inner['path'], inner['branch'], inner['common_dir'])
                == (workspace['path'], workspace['branch'], self.common_dir))
        if kind == 'worktree.create':
            same = same and spec.get('base_sha') == inner['base_sha'] == workspace['base_sha']
        else:
            same = (same and spec.get('base_sha', workspace['base_sha']) == workspace['base_sha']
                    and inner['cleanup_root'] == os.path.join(self.state_dir, WORKSPACE_DIR)
                    and _is_sha(inner['expected_head']))
        if not same:
            raise LedgerError('effect_workspace', 'not the registered plan workspace')
        return {**spec, 'write_scope': workspace['write_scope'], 'workspace': workspace['id'],
                'epoch': workspace['epoch']}

    def _plan_idle(self, plan_id):
        """Removal needs the workspace unused: no unsettled attempt or effect of the plan."""
        busy = self._db.execute(
            'SELECT 1 FROM attempts a JOIN tasks t ON t.id = a.task_id WHERE t.plan_id = ? '
            f'AND a.state IN {_ACTIVE_SQL} UNION ALL '
            "SELECT 1 FROM effects WHERE plan_id = ? AND state IN ('intent','unknown')",
            (plan_id, plan_id)).fetchone()
        if busy:
            raise LedgerError('plan_workspace_busy', 'settle every attempt and effect of the plan first')

    def plan_effect_intent(self, plan_id, kind, spec):
        """Record the intent for a plan-owned ``worktree.create`` or ``worktree.remove`` of
        the registered integration workspace before it runs; no other kind has a plan
        owner. ``spec`` is the engine journal envelope: ``path``, ``cleanup_id``,
        ``branch`` (and ``base_sha``) as registered plus the strict inner ``fx`` adapter
        mapping (see _plan_spec). Creation needs a running controller, the current
        context, the ``integrate`` grant and a workspace that was never created (a failed
        creation may be retried). Removal is cleanup: it stays allowed under pause, STOP,
        a context hold and for a stale plan, but only for a created (or failed)
        registration of this plan and only while the plan has no unsettled attempt or
        effect. A confirmed removal is final for that context epoch. Resolve with
        effect_result or effect_reconcile. Returns the effect id."""
        if type(kind) is not str or kind not in WORKSPACE_EFFECTS or type(spec) is not dict:
            raise LedgerError('effect_unauthorized', 'a plan owns only worktree.create and '
                                                     'worktree.remove with an object spec')
        path, cleanup_id = self._workspace_ident(spec, 'effect_workspace')
        cleanup = kind == 'worktree.remove'
        with self._tx() as control:
            if control != 'running' and not cleanup:
                raise LedgerError('control_' + control, 'effects are blocked')
            plan = self._plan_row(plan_id)
            if cleanup:
                rows = self._rows('SELECT * FROM plan_workspaces WHERE plan_id = ? AND path = ? '
                                  'AND cleanup_id = ?', (plan_id, path, cleanup_id), _WORKSPACE_JSON)
                if not rows:
                    raise LedgerError('effect_unauthorized', 'no plan-owned workspace has this identity')
                workspace = rows[0]
            else:
                self._require_context()
                if plan['epoch'] != self.epoch:
                    raise LedgerError('plan_stale', 'the plan was admitted under an earlier context; '
                                                    'readmit_plan is required')
                self._integration_granted(plan)
                workspace = self._plan_ws(plan_id, self.epoch)
                if workspace is None:
                    raise LedgerError('plan_workspace_required', 'register_plan_workspace must record '
                                                                 'the workspace first')
            stored = self._plan_spec(workspace, kind, spec)
            state = self._ws_state(workspace)
            if state in ('creating', 'removing'):
                raise LedgerError('effect_unresolved', 'reconcile the earlier effect first')
            if state not in (('created', 'failed') if cleanup else ('registered', 'failed')):
                raise LedgerError('plan_workspace_state', f'the plan workspace is {state}')
            if cleanup:
                self._plan_idle(plan_id)
            effect_id = self._db.execute(
                'INSERT INTO effects(plan_id, owner, kind, spec, state, fence, at) '
                "VALUES (?, 'plan', ?, ?, 'intent', ?, ?)",
                (plan_id, kind, _canon(stored), self.fence, _now())).lastrowid
            self._event('effect_intent', effect_id, {'plan': plan_id, 'kind': kind, 'effect': None})
        return effect_id

    def _resolve_effect(self, effect_id, outcome, payload, sources, event):
        with self._tx():
            marks = ','.join('?' * len(sources))
            self._cas(f'UPDATE effects SET state = ?, result = ?, resolved_at = ? '
                      f'WHERE id = ? AND state IN ({marks})',
                      (outcome, _canon(payload or {}), _now(), effect_id, *sources))
            self._event(event, effect_id, {'outcome': outcome, 'payload': payload or {}})

    def effect_result(self, effect_id, outcome, result=None):
        if outcome not in ('done', 'failed', 'unknown'):
            raise LedgerError('outcome', str(outcome))
        self._resolve_effect(effect_id, outcome, result, ('intent',), 'effect_result')

    def effect_reconcile(self, effect_id, outcome, evidence):
        if outcome not in ('done', 'failed') or not isinstance(evidence, dict) or not evidence:
            raise LedgerError('outcome', 'reconciliation needs done/failed and evidence')
        self._resolve_effect(effect_id, outcome, evidence, ('intent', 'unknown'), 'effect_reconcile')

    def observe(self, profile_id, metadata):
        """Store one routing observation of a configured profile and decide, in the same
        leased transaction, whether it becomes that profile's current routing state.

        Only a strict routing-observation/v1 record for the profile's own provider is
        accepted (see _observation); anything else is refused as ``metadata`` and nothing
        is stored. Every accepted record is kept. Admission follows evidence time, never
        arrival order (see _admission): a late older success cannot clear a newer hold,
        and an auth or permission hold stays until a strictly newer operator refresh.
        The ledger calls no provider. Returns ``{id, admitted, reason}``."""
        profile = next((p for p in self.policy['profiles'] if p['id'] == profile_id), None)
        if profile is None:
            raise LedgerError('profile_role', 'unknown profile')
        observation = _observation(metadata, profile['provider'], time.time())
        with self._tx():
            current = self._rows('SELECT data FROM observations WHERE profile_id = ? AND admitted = 1 '
                                 'ORDER BY id DESC LIMIT 1', (profile_id,), ('data',))
            reason = _admission(current[0]['data'] if current else None, observation)
            admitted = reason == 'admitted'
            observation_id = self._db.execute(
                'INSERT INTO observations(profile_id, data, at, admitted, reason) VALUES (?, ?, ?, ?, ?)',
                (profile_id, _canon(observation), _now(), int(admitted), reason)).lastrowid
            self._event('observe', profile_id, {
                'observation': observation_id, 'admitted': admitted, 'reason': reason,
                'source': observation['source'], 'availability': observation['availability'],
                'ended_at': observation['ended_at']})
        return {'id': observation_id, 'admitted': admitted, 'reason': reason}

    def set_control(self, state, actor='operator'):
        """Operator control; needs no lease and is committed (synchronous FULL) before
        return. ``stopped`` persists across restarts and is sticky: the compare and the
        write share one transaction, so a ``paused`` decided on an earlier read is refused
        (``control_stopped``) once a STOP has landed. Only an explicit ``running`` clears
        STOP; nothing in the ledger resumes on its own."""
        if state not in CONTROLS:
            raise LedgerError('control', str(state))
        with self._tx(fenced=False) as control:
            if state == 'paused' and control == 'stopped':
                raise LedgerError('control_stopped', 'STOP is cleared only by an explicit running')
            self._db.execute('UPDATE controller SET control = ? WHERE id = 1', (state,))
            self._event('control', state, {'actor': actor})
        return state

    def control(self):
        """Current operator control; the engine checks it before spawning anything."""
        return self._db.execute('SELECT control FROM controller WHERE id = 1').fetchone()[0]

    def _settled(self, control):
        if control != 'stopped':
            raise LedgerError('control_required', 'reconciliation needs a persistent STOP')
        owned = self._owned()
        if owned['attempts'] or owned['effects']:
            raise LedgerError('owned_work', 'resolve every owned attempt and effect first')

    def _store_policy(self, data, policy_digest):
        """Make the policy of a new epoch durable as an immutable private file BEFORE the
        ledger row that names it commits. A crash leaves at worst an unreferenced file,
        which a retry verifies and reuses; an existing file is never overwritten and
        nothing outside the state directory is touched."""
        known = self._db.execute('SELECT policy_file FROM contexts WHERE policy_digest = ? LIMIT 1',
                                 (policy_digest,)).fetchone()
        name = known[0] if known else f'policy-{policy_digest}.json'
        path = os.path.join(self.state_dir, name)
        if not known and not os.path.lexists(path):
            tmp = _write_tmp(path, data)
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
            finally:
                os.unlink(tmp)
            _fsync_dir(self.state_dir)
        try:
            stored = _read_private(path)
        except LedgerError as err:
            if err.code != 'missing':
                raise
            raise LedgerError('corrupt', 'policy snapshot of a context epoch is missing') from err
        if stored != data:
            raise LedgerError('corrupt', 'an epoch policy file holds other content')
        return name

    def reconcile_context(self, policy, identity, actor):
        """Explicit operator reconciliation: append a new immutable context epoch holding
        the frozen validated ``policy`` and the runtime/rules ``identity``.

        Needs the controller lease, a persistent STOP, every owned attempt terminal and
        no effect in intent/unknown. It reads no auth, config contents or billing and
        changes nothing else: STOP stays stopped, earlier epochs and their policy files,
        budgets, failures, events and evidence are kept, and every existing plan becomes
        stale (task states untouched) until readmit_plan. An unchanged policy and
        identity append nothing. Returns ``{epoch, changed, stale_plans}``."""
        _check_identity(identity)
        _label(actor, 'actor')
        data = _policy_bytes(_frozen_policy(policy, self.common_dir))
        policy_digest = hashlib.sha256(data).hexdigest()
        if self.readonly:
            raise LedgerError('readonly', 'ledger was opened read-only')
        if self._lease is None:
            raise LedgerError('lease_required', 'writer holds no controller lease')
        self._settled(self.control())
        name = self._store_policy(data, policy_digest)
        with self._tx() as control:
            self._settled(control)
            if (policy_digest, identity) == (self.policy_digest, self.identity):
                return {'epoch': self.epoch, 'changed': False, 'stale_plans': []}
            epoch = self.epoch + 1
            stale = [row[0] for row in self._db.execute('SELECT id FROM plans ORDER BY rowid')]
            self._db.execute('INSERT INTO contexts(epoch, policy_digest, policy_file, identity, actor, '
                             'fence, at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                             (epoch, policy_digest, name, _canon(identity), actor, self.fence, _now()))
            self._event('context_reconcile', epoch, {
                'previous': self.epoch, 'policy_digest': policy_digest, 'identity': identity,
                'actor': actor, 'stale_plans': stale})
        self._load_context()
        return {'epoch': epoch, 'changed': True, 'stale_plans': stale}

    def readmit_plan(self, plan_id, authority, identity):
        """Owner reapproval of the UNCHANGED saved plan under the current context.

        The saved body is re-validated against the current policy and ``authority`` must
        bind its exact digest (a changed scope or objective needs a new plan). The
        declaration must be new: approved no earlier than the current epoch, so a grant
        made under an earlier context is never replayed or widened. While any attempt,
        effect or controller-created workspace of the plan is unsettled nothing changes
        and ``{'status': 'hold', ...}`` lists what the engine must inspect and clean up.

        On success every unpublished task loses its binding and its acceptance: a task
        with a preserved result returns to implemented (or checked without checks) and
        needs a fresh binding, checks and review in this context. An unpublished derived
        candidate of the earlier context is superseded (rows kept): the re-accepted tasks
        need a new candidate. Results, receipts, effects, attempts, used time and counters
        are kept. Nothing resumes and STOP is not cleared."""
        with self._tx():
            self._require_context()
            if identity != self.identity:
                raise LedgerError('identity_changed', 'runtime or rules identity differs from the record')
            row = self._db.execute('SELECT body, epoch FROM plans WHERE id = ?', (plan_id,)).fetchone()
            if row is None:
                raise LedgerError('unknown_plan', str(plan_id))
            if row['epoch'] == self.epoch:
                raise LedgerError('plan_current', 'the plan is already admitted under the current context')
            try:
                plan = validate_plan(json.loads(row['body']), self.policy)
            except InputError as err:
                raise LedgerError('plan_invalid', str(err)) from err
            authority = self._authority(authority, plan)
            if _stamp(authority['approved_at']) < _stamp(self._context_at):
                raise LedgerError('authority_stale', 'readmission needs a declaration approved under '
                                                     'the current context')
            owned = self._owned(plan_id)
            if any(owned.values()):
                self._event('readmit_hold', plan_id, {
                    'attempts': [item['id'] for item in owned['attempts']],
                    'effects': [item['id'] for item in owned['effects']],
                    'workspaces': [item['effect_id'] for item in owned['workspaces']]})
                return {'status': 'hold', 'plan': plan_id, **owned}
            now, states, moved = _now(), {}, {}
            tasks = self._db.execute('SELECT id, spec, state, result FROM tasks WHERE plan_id = ? '
                                     'ORDER BY rowid', (plan_id,)).fetchall()
            derived = {item[0] for item in self._db.execute(
                'SELECT id FROM candidates WHERE plan_id = ?', (plan_id,))}
            for task in tasks:
                if task['id'] not in derived:
                    states[task['id']] = task['state']
                if task['state'] == 'published':
                    continue
                self._db.execute("UPDATE bindings SET state = 'invalidated', ended_at = ?, reason = ? "
                                 "WHERE task_id = ? AND state = 'active'",
                                 (now, f'readmitted under context {self.epoch}', task['id']))
                if task['id'] in derived:
                    self._db.execute("UPDATE tasks SET state = 'superseded' WHERE id = ?", (task['id'],))
                    continue
                if task['result'] is not None:
                    states[task['id']] = 'implemented' if json.loads(task['spec'])['checks'] else 'checked'
                    self._cas('UPDATE tasks SET state = ? WHERE id = ? AND state = ?',
                              (states[task['id']], task['id'], task['state']))
                    moved[task['id']] = task['state']
            stored = _canon(authority)
            self._cas('UPDATE plans SET epoch = ?, authority = ? WHERE id = ? AND epoch = ?',
                      (self.epoch, stored, plan_id, row['epoch']))
            self._db.execute('INSERT INTO admissions(plan_id, epoch, authority, fence, at) '
                             'VALUES (?, ?, ?, ?, ?)', (plan_id, self.epoch, stored, self.fence, now))
            self._event('readmit', plan_id, {'epoch': self.epoch, 'previous': row['epoch'],
                                             'effects': authority['effects'], 'revalidate': moved})
        return {'status': 'readmitted', 'plan': plan_id, 'epoch': self.epoch, 'tasks': states}

    def _owned_workspace(self, row):
        """One created, unremoved workspace. A plan-owned one also carries what its cleanup
        needs: the registered epoch, branch and origin and its current checkpoint head."""
        item = {'effect_id': row['id'], 'task_id': row['task_id'], 'plan_id': row['plan_id'],
                'owner': row['owner'], 'state': row['state'], 'path': row['spec']['path'],
                'cleanup_id': row['spec']['cleanup_id']}
        if row['owner'] == 'plan':
            workspace = self._ws_row(row['spec']['workspace'])
            head = self._head(workspace['id'])
            item.update(epoch=workspace['epoch'], branch=workspace['branch'],
                        base_sha=workspace['base_sha'], head=None if head is None else head['sha'])
        return item

    def _owned(self, plan_id=None):
        """Unsettled attempts and effects plus every task- or plan-owned workspace creation
        that no LATER confirmed removal of the same identity covers."""
        attempts, effects, args = '', '', ()
        if plan_id is not None:
            attempts = ' AND task_id IN (SELECT id FROM tasks WHERE plan_id = ?)'
            effects, args = ' AND plan_id = ?', (plan_id,)
        live = {}
        for row in self._rows('SELECT id, task_id, plan_id, owner, kind, spec, state FROM effects '
                              "WHERE kind IN ('worktree.create','worktree.remove')" + effects
                              + ' ORDER BY id', args, ('spec',)):
            identity = (row['spec']['path'], row['spec']['cleanup_id'])
            if row['kind'] == 'worktree.create':
                live.setdefault(identity, []).append(row)
            elif row['state'] == 'done':
                live.pop(identity, None)
        created = sorted((row for rows in live.values() for row in rows), key=lambda row: row['id'])
        return {
            'attempts': self._rows(
                'SELECT id, task_id, profile_id, role, check_name, result, state, launch, released_at '
                'FROM attempts '
                f'WHERE state IN {_ACTIVE_SQL}{attempts} ORDER BY id', args, ('launch',)),
            'effects': self._rows('SELECT id, task_id, plan_id, owner, kind, spec, state FROM effects '
                                  "WHERE state IN ('intent','unknown')" + effects + ' ORDER BY id',
                                  args, ('spec',)),
            'workspaces': [self._owned_workspace(row) for row in created],
        }

    def owned_work(self):
        """Read-only cleanup inventory: every unresolved attempt with its retained launch
        identity and release state, every unresolved effect and every controller-created
        workspace not yet removed, task-owned (``owner`` 'task') or plan-owned (``owner``
        'plan', ``task_id`` None). After STOP the engine drains exactly this list."""
        with self._snapshot():
            return {'control': self.control(), **self._owned()}

    def events(self, after=0, limit=1000):
        return self._rows('SELECT * FROM events WHERE id > ? ORDER BY id LIMIT ?', (after, limit), ('data',))

    def context(self, epoch=None):
        """Read-only view of one context epoch (default: current) with its frozen policy.
        ``hold`` is None without a lease, else whether this controller is held."""
        with self._snapshot():
            number = self.epoch if epoch is None else epoch
            rows = (self._rows('SELECT * FROM contexts WHERE epoch = ?', (number,), ('identity',))
                    if type(number) is int else [])
            if not rows:
                raise LedgerError('unknown_context', str(epoch))
            view, lease = rows[0], self._lease
            view['policy'] = json.loads(self._epoch_policy(view))
            view['current'] = number == self.epoch
            view['hold'] = None if lease is None else lease.identity != self.identity
            return view

    def contexts(self):
        """Read-only context history, oldest first (policies are read with context())."""
        return self._rows('SELECT * FROM contexts ORDER BY epoch', (), ('identity',))

    def _task_view(self, row):
        stale = row['plan_epoch'] != self.epoch
        return {
            'id': row['id'], 'plan_id': row['plan_id'], 'plan_base': row['base_sha'],
            'plan_epoch': row['plan_epoch'], 'stale': stale, 'spec': json.loads(row['spec']),
            'state': row['state'], 'failures': row['failures'], 'no_progress': row['no_progress'],
            'progress': row['progress'], 'result': row['result'],
            'binding': self._binding(row['id']),
            'bindings': self._rows('SELECT * FROM bindings WHERE task_id = ? ORDER BY id',
                                   (row['id'],), _BINDING_JSON),
            'gate': None if stale else self._expected(row),
        }

    def task(self, task_id):
        """Read-only task view: spec, state, counters, the plan origin (``plan_base``), the
        active execution binding, binding history and the exact gate identity the
        current result needs (None when stale, unbound or without a result)."""
        with self._snapshot():
            return self._task_view(self._task(task_id))

    def plans(self):
        """Read-only plan summaries in submission order."""
        with self._snapshot():
            rows = self._rows('SELECT id, digest, base_sha, epoch, submitted_at FROM plans ORDER BY rowid')
            for row in rows:
                row['stale'] = row['epoch'] != self.epoch
            return rows

    def plan(self, plan_id):
        """Read-only plan view: the saved body, current authority, admission history and
        every task view. ``base_sha`` is the immutable owner origin of the whole plan."""
        with self._snapshot():
            rows = self._rows('SELECT * FROM plans WHERE id = ?', (plan_id,), ('body', 'authority'))
            if not rows:
                raise LedgerError('unknown_plan', str(plan_id))
            view = rows[0]
            view['stale'] = view['epoch'] != self.epoch
            view['admissions'] = self._rows('SELECT epoch, authority, fence, at FROM admissions '
                                            'WHERE plan_id = ? ORDER BY id', (plan_id,), ('authority',))
            ids = [row[0] for row in self._db.execute(
                'SELECT id FROM tasks WHERE plan_id = ? AND id NOT IN (SELECT id FROM candidates) '
                'ORDER BY rowid', (plan_id,)).fetchall()]
            view['tasks'] = [self._task_view(self._task(task_id)) for task_id in ids]
            view['candidates'] = self._candidate_views(plan_id)
            view['workspace'], view['checkpoint'] = self._plan_integration(plan_id, self.epoch)
            return view

    def _candidate_view(self, row):
        """One derived candidate with its derived stage: ``checking``, ``reviewing``,
        ``reviewed``, ``accepted`` or ``published`` while it advances; ``failed`` when its
        result was dropped by a failed check, a rejecting review or an explicit
        invalidation; ``stale`` when a contribution or the context changed; ``superseded``
        when a newer revision or a readmission replaced it. ``hold`` is the fixed reason
        it is not current (None when current), ``gate`` the exact identity its evidence
        needs, ``publishable`` whether an external effect could be authorized now and
        ``publication_hold`` the fixed reason it could not (see _publication_hold)."""
        task = self._task(row['id'])
        hold, state = self._candidate_hold(task, row), task['state']
        if state == 'published':
            stage = 'published'
        elif 'superseded' in (state, hold):
            stage = 'superseded'
        elif task['result'] is None:
            stage = 'failed'
        elif hold is not None:
            stage = 'stale'
        else:
            stage = _CANDIDATE_STAGE.get(state, state)
        expected = None if hold is not None else self._expected(task)
        if hold is not None:
            blocked = 'candidate_stale'
        elif state not in DONE_STATES:
            blocked = 'candidate_unaccepted'
        else:
            blocked = self._publication_hold(task, _canon(expected))
        return {**row, 'state': state, 'failures': task['failures'], 'hold': hold,
                'current': hold is None, 'stage': stage,
                'publishable': state == 'accepted' and blocked is None,
                'publication_hold': blocked, 'gate': expected}

    def _candidate_views(self, plan_id=None):
        where, args = ('', ()) if plan_id is None else (' WHERE plan_id = ?', (plan_id,))
        rows = self._rows(f'SELECT * FROM candidates{where} ORDER BY rowid', args, _CANDIDATE_JSON)
        return [self._candidate_view(row) for row in rows]

    def candidates(self, plan_id=None):
        """Read-only views of every derived candidate (of one plan), oldest first."""
        with self._snapshot():
            return self._candidate_views(plan_id)

    def candidate(self, candidate_id):
        """Read-only view of one derived candidate (see _candidate_view)."""
        with self._snapshot():
            row = self._candidate(candidate_id)
            if row is None:
                raise LedgerError('unknown_candidate', str(candidate_id))
            return self._candidate_view(row)

    def plan_workspace(self, plan_id, epoch=None):
        """Read-only view of the integration workspace a plan registered in the current
        context (or in ``epoch``), else None: ``{plan_id, epoch, path, cleanup_id, branch,
        base_sha, write_scope}`` plus ``id``, ``purpose``, the derived ``state`` (see
        _ws_state), ``current``, the checkpoint ``head`` and the ``unrecorded`` confirmed
        integrations a restarted engine must still checkpoint."""
        with self._snapshot():
            return self._plan_integration(plan_id, self.epoch if epoch is None else epoch)[0]

    def checkpoint(self, plan_id, epoch=None):
        """Read-only view of the current checkpoint of a plan in the current context (or in
        ``epoch``), else None: ``{plan_id, epoch, sha, contributions, effect_id, workspace}``
        plus ``id``, ``previous``, ``expected`` (the SHA it replaced) and ``observation``."""
        with self._snapshot():
            return self._plan_integration(plan_id, self.epoch if epoch is None else epoch)[1]

    def _dispatch_rows(self):
        rows = []
        tasks = self._db.execute('SELECT id, plan_id, spec FROM tasks ORDER BY rowid').fetchall()
        derived = {row[0] for row in self._db.execute('SELECT id FROM candidates')}
        for task in tasks:
            lanes = [(role, None) for role in ROLES if role != 'implement' or task['id'] not in derived]
            lanes += [(CHECK_ROLE, name) for name in json.loads(task['spec'])['checks']]
            rows += [{'task_id': task['id'], 'plan_id': task['plan_id'],
                      **self._dispatch(task['id'], role, check)} for role, check in lanes]
        return rows

    def observation_history(self, profile_id=None, limit=1000):
        """Read-only raw observation history, oldest first: every stored record, whether it
        was admitted as current routing state and the fixed reason when it was not."""
        where, args = ('', ()) if profile_id is None else (' WHERE profile_id = ?', (profile_id,))
        rows = self._rows('SELECT id, profile_id, data, at, admitted, reason FROM observations'
                          f'{where} ORDER BY id LIMIT ?', (*args, limit), ('data',))
        for row in rows:
            row['admitted'] = bool(row['admitted'])
        return rows

    def checks(self, task_id):
        """Read-only check view for the engine: per declared check the status recorded for
        the current gate (None when missing), its lane counts and limits, its attempts
        and its evidence rows; plus the aggregate finalize_checks would compute (None
        when the task is stale, unbound, without a result or declares no checks)."""
        with self._snapshot():
            task = self._task(task_id)
            declared = json.loads(task['spec'])['checks']
            expected = None if task['plan_epoch'] != self.epoch else self._expected(task)
            states = (dict.fromkeys(declared) if expected is None
                      else self._check_states(task_id, declared, _canon(expected)))
            return {
                'task_id': task_id, 'state': task['state'], 'result': task['result'], 'gate': expected,
                'aggregate': None if expected is None else _aggregate(states),
                'checks': [{
                    'name': name, 'status': states[name], **self._dispatch(task_id, CHECK_ROLE, name),
                    'attempts': self._rows(
                        'SELECT id, state, outcome, attribution, reason, result, epoch, released_at '
                        'FROM attempts WHERE task_id = ? AND role = ? AND check_name = ? ORDER BY id',
                        (task_id, CHECK_ROLE, name)),
                    'evidence': self._rows(
                        'SELECT id, status, attempt_id, receipt, identity, epoch, at FROM evidence '
                        "WHERE task_id = ? AND kind = 'check' AND name = ? ORDER BY id",
                        (task_id, name), ('receipt', 'identity')),
                } for name in declared],
            }

    def status(self):
        with self._snapshot():
            controller = self._rows('SELECT fence, control FROM controller')[0]
            budgets = self._rows(
                "SELECT p.id AS plan_id, COALESCE(SUM(CASE WHEN a.state = 'finished' "
                "THEN a.used_seconds END), 0) AS used_seconds, COALESCE(SUM(CASE WHEN "
                "a.state != 'finished' THEN a.reserved_seconds END), 0) AS held_seconds "
                'FROM plans p LEFT JOIN tasks t ON t.plan_id = p.id '
                'LEFT JOIN attempts a ON a.task_id = t.id GROUP BY p.id ORDER BY p.rowid')
            for row in budgets:
                row['charged_seconds'] = row['used_seconds'] + row['held_seconds']
                row['limit_seconds'] = self.policy['limits']['max_total_seconds']
            return {
                'schema_version': SCHEMA_VERSION, 'authority_id': self.authority_id,
                'epoch': self.epoch, 'policy_digest': self.policy_digest, 'identity': self.identity,
                **controller,
                'charged_seconds': sum(row['charged_seconds'] for row in budgets),
                'budgets': budgets,
                'tasks': self._rows(
                    'SELECT t.id, t.plan_id, t.state, t.failures, t.no_progress, t.progress, '
                    't.result, (SELECT COUNT(*) FROM attempts a WHERE a.task_id = t.id) AS attempts '
                    'FROM tasks t WHERE t.id NOT IN (SELECT id FROM candidates) ORDER BY t.rowid'),
                'candidates': self._candidate_views(),
                'governance': {'publication_review': PUBLICATION_PROVIDER,
                               'reviewers': self._publication_reviewers(),
                               'role_override': 'attended_handoff'},
                'plan_workspaces': [self._workspace_view(row) for row in self._rows(
                    'SELECT * FROM plan_workspaces ORDER BY id', (), _WORKSPACE_JSON)],
                'checkpoints': self._rows('SELECT * FROM checkpoints ORDER BY id', (), _CHECKPOINT_JSON),
                'attempts': self._rows('SELECT * FROM attempts ORDER BY id', (), ('launch',)),
                'evidence': self._rows('SELECT * FROM evidence ORDER BY id', (), ('identity', 'receipt')),
                'progress': self._rows('SELECT * FROM progress ORDER BY id'),
                'effects': self._rows('SELECT * FROM effects ORDER BY id', (), ('spec', 'result')),
                'observations': self._rows(
                    'SELECT profile_id, data, at FROM observations WHERE id IN (SELECT MAX(id) '
                    'FROM observations WHERE admitted = 1 GROUP BY profile_id) ORDER BY id',
                    (), ('data',)),
                'dispatch': self._dispatch_rows(),
            }
