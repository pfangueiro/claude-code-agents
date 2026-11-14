#!/usr/bin/env python3
"""Operator CLI for the optional local persistent delivery controller.

Thin offline front end over controller_inputs (validation, identity digests),
controller_ledger (state, control, context epochs) and controller_requests (the private
request inbox). submit and refresh-profile only queue an immutable request and take no
repository lock; a running controller admits it. It never daemonizes, schedules, installs
a service, auto-starts, updates, logs in, reads credential contents or invokes a provider.
`run`, `recover` and `cleanup-workspaces` lazily load controller_engine from this directory;
without it nothing runs and the outcome is INCOMPLETE. Outcomes: PASS exit 0, FAIL exit 1, INCOMPLETE exit 2.
"""
import argparse
from collections import Counter
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import sys
import threading

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import controller_inputs as inputs
from controller_ledger import (BINDING_FILE, LEDGER_FILE, POLICY_FILE, ControllerLock, Ledger,
                               LedgerError, initialize)
import controller_requests as inbox

EXIT = {'PASS': 0, 'FAIL': 1, 'INCOMPLETE': 2}
INCOMPLETE_CODES = frozenset({'locked', 'missing', 'unbound', 'owned_work', 'repository_inventory',
                              'repository_layout_unsupported', 'runtime_layout_unsupported'})
ACK_OUTCOME = {'admitted': 'PASS', 'observed': 'PASS', 'incomplete': 'INCOMPLETE',
               'refused': 'FAIL'}
ENGINE_FILE = 'controller_engine.py'
POLL_RANGE = (0.5, 3600.0)
MAX_TRIES = 3
STOP_SIGNALS = ('SIGTERM', 'SIGINT', 'SIGHUP')
NEW_CONTEXT = '; nothing was changed. A new context is recorded only by an explicit reconcile under STOP'
LEDGER_HINTS = {
    'locked': ('; nothing was changed (a running controller or another init/reconcile/readmit '
               'holds the repository lock; submit, refresh-profile, status, stop and pause need '
               'no lock)'),
    'policy_changed': NEW_CONTEXT,
    'identity_changed': NEW_CONTEXT,
    'control_required': '; run stop first (reconcile never sets or clears STOP)',
    'owned_work': '; run recover (cleanup only) and retry',
}

DESCRIPTION = '''\
Optional local operator interface for the persistent delivery controller.

Nothing starts automatically. This tool installs no daemon, service, launchd or systemd
unit, scheduler or updater; it never logs in, never reads credential contents and never
invokes a provider itself. `run` works only in the foreground of this process; with
--background it is still this process, the flag only asserts the owner-approved
background policy. End a run with `stop`, or send SIGINT/SIGTERM once to request a
durable STOP (a second signal exits immediately). STOP is cleared only by `resume`.

submit and refresh-profile validate their input and QUEUE a private immutable request;
they take no lock and dispatch nothing. A request is pending until a controller holding
the repository lease admits it through the ledger; admitted means recorded, not executed
or completed. Requests stay pending under STOP. status lists pending and acknowledged
requests read-only.

setup asks policy questions once and creates policy and state; it never overwrites
existing state. --state must be an absolute path outside the repository. Monetary caps
are not supported: bound work with attempt and time limits. A changed policy, runtime or
rules is recorded only by an explicit `reconcile` under STOP; earlier plans then need an
explicit `readmit` with a new owner declaration.

recover settles positively owned work and deletes no workspace. cleanup-workspaces is the
explicit owner request that deletes the confirmed clean controller-managed worktrees of ONE
named plan under STOP; branches, commits and history are kept, and dirty or unknown
worktrees are held. It works under a context hold and never clears STOP or resumes.

Outcomes: PASS exit 0, FAIL exit 1, INCOMPLETE exit 2 (a required step did not run,
for example the controller_engine runtime is not installed). Absent checks are not zero.
'''
ALIAS_NOTE = ('Note: profile ids are aliases for owner-authorized account directories. '
              'Separate profiles do not prove separate quota or independent accounts.')
COST_NOTE = ('max_cost_usd is null: hard monetary caps are not supported because no cost is '
             'measured. Spend is bounded only by attempt, time and no-progress limits.')
REFRESH_NOTE = ('refresh-profile queues an explicit operator refresh only. It does not log in, '
                'verify or renew authentication, read account contents or switch accounts; '
                'availability stays unknown until a real bounded task probes the profile.')


class CliError(Exception):
    """Refusal with an outcome (FAIL or INCOMPLETE) and a stable code."""

    def __init__(self, outcome, code, message):
        super().__init__(f'{code}: {message}')
        self.outcome = outcome


class _Abort(Exception):
    """Interactive setup ended without the owner's confirmation."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT['FAIL'], f'FAIL: {message}\n')


def _say(text=''):
    print(text, file=sys.stderr)


def _report(outcome, message):
    _say(f'{outcome}: {message}')
    return EXIT[outcome]


def _abs_arg(value, flag):
    if '\0' in value or not os.path.isabs(value) or os.path.normpath(value) != value:
        raise CliError('FAIL', 'path', f'{flag} must be an absolute normalized path')
    return value


def _within(path, roots):
    located = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    return any(located == root or located.startswith(root.rstrip('/') + '/') for root in roots)


# ---- identity -------------------------------------------------------------------

def _head(root):
    head = inputs._git(root, 'rev-parse', '--verify', '--quiet', 'HEAD^{commit}').decode(
        'ascii', 'replace').strip()
    if not inputs.SHA.fullmatch(head):
        raise CliError('FAIL', 'head', 'repository HEAD is not a resolvable commit')
    return head


def _has_changes(root, paths, untracked):
    args = ['status', '--porcelain=v1', '-z', f"--untracked-files={'normal' if untracked else 'no'}"]
    if paths:
        args += ['--', *paths]
    return bool(inputs._git(root, *args).strip(b'\0'))


def _identity(policy):
    """Current runtime/rules identity. Refuses uncommitted instruction changes instead of
    hashing a HEAD that does not describe the instructions actually in force."""
    root, paths = policy['repository'], policy['instruction_paths']
    head = _head(root)
    if paths and _has_changes(root, paths, untracked=False):
        raise CliError('FAIL', 'dirty_instructions', 'instruction paths differ from HEAD; commit '
                       'them first (no identity is invented for uncommitted rules)')
    identity = {'runtime': inputs.runtime_digest(RUNTIME_DIR),
                'rules': inputs.rules_digest(root, head, paths)}
    return identity, head


def _identity_check(policy, recorded):
    try:
        current, _ = _identity(policy)
    except (inputs.InputError, CliError) as err:
        return {'runtime': 'unknown', 'rules': 'unknown', 'reason': str(err)}
    return {key: 'match' if current[key] == recorded[key] else 'differs'
            for key in ('runtime', 'rules')} | {'reason': None}


def _check_frozen(policy):
    try:
        current = inputs.validate_policy(policy)
    except inputs.InputError as err:
        raise CliError('FAIL', 'policy_context', f'recorded policy no longer validates here '
                       f'({err.code}); nothing was changed') from err
    if current != policy:
        raise CliError('FAIL', 'policy_context', 'recorded policy resolves differently now '
                       '(for example a moved config directory); nothing was changed')


def _current_identity(policy, recorded, verb):
    """The current identity, refused unless it equals the recorded current context."""
    _check_frozen(policy)
    identity, _ = _identity(policy)
    if identity != recorded:
        raise CliError('FAIL', 'identity_changed', 'runtime or rules differ from the current '
                       f'context; nothing was {verb}. Reconcile explicitly under STOP first')
    return identity


def _print_identity(state, verb, policy_digest, identity, head, clean):
    print(f'state: {state} ({verb})')
    print(f'policy_digest: {policy_digest}')
    print(f"runtime_digest: {identity['runtime']}")
    print(f"rules_digest: {identity['rules']} (committed instruction blobs at {head})")
    print(f'worktree: clean at {head}' if clean else 'worktree: dirty; no source SHA is claimed')


def _open(state, readonly):
    try:
        return Ledger.open(state, readonly=readonly)
    except LedgerError as err:
        if err.code == 'missing':
            raise CliError('INCOMPLETE', 'no_state', 'no controller state at --state; run '
                           'setup or init first') from err
        raise


def _actor(text):
    try:
        return inbox.check_actor(text)
    except inbox.RequestError as err:
        raise CliError('FAIL', 'actor', '--actor must be short printable text without '
                       'credentials') from err


def _plan_id(text):
    if not inputs.SAFE_ID.fullmatch(text):
        raise CliError('FAIL', 'plan_id', '--plan-id is not a plan id')
    return text


# ---- interactive prompts ---------------------------------------------------------

def _ask(prompt, default=None):
    sys.stderr.write(f'{prompt}{f" [{default}]" if default else ""}: ')
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise _Abort('input ended before setup finished')
    return line.strip() or (default or '')


def _ask_valid(prompt, parse, default=None):
    """Re-ask on invalid answers without echoing them (they may carry a credential)."""
    for _ in range(MAX_TRIES):
        try:
            return parse(_ask(prompt, default))
        except ValueError as err:
            _say(f'  invalid: {err}')
    raise _Abort(f'too many invalid answers to: {prompt}')


def _parse_bool(text):
    lowered = text.lower()
    if lowered in ('y', 'yes'):
        return True
    if lowered in ('n', 'no'):
        return False
    raise ValueError('answer y or n')


def _ask_bool(prompt, default=False):
    return _ask_valid(f'{prompt} (y/n)', _parse_bool, 'y' if default else 'n')


def _int_parser(low, high):
    def parse(text):
        if not (text.isascii() and text.isdigit()) or not low <= int(text) <= high:
            raise ValueError(f'enter an integer in {low}..{high}')
        return int(text)
    return parse


def _ask_int(prompt, default, low, high):
    return _ask_valid(f'{prompt} ({low}-{high})', _int_parser(low, high), str(default))


def _choice_parser(choices):
    def parse(text):
        if text not in choices:
            raise ValueError(f"choose one of {', '.join(choices)}")
        return text
    return parse


def _id_parser(taken=()):
    def parse(text):
        if not inputs.SAFE_ID.fullmatch(text):
            raise ValueError('use 1-64 letters, digits, ".", "_" or "-", starting alphanumeric')
        if text in taken:
            raise ValueError('that id is already used')
        return text
    return parse


def _pattern_parser(pattern, what):
    def parse(text):
        if not pattern.fullmatch(text):
            raise ValueError(f'enter {what}')
        return text
    return parse


def _text_parser(limit):
    def parse(text):
        if not text or len(text) > limit or not text.isprintable():
            raise ValueError(f'enter printable text of at most {limit} characters')
        return text
    return parse


def _optional(parse):
    return lambda text: parse(text) if text else ''


def _parse_executable(text):
    if not os.path.isabs(text) or os.path.normpath(text) != text:
        raise ValueError('enter a normalized absolute path')
    real = os.path.realpath(text)
    if not os.path.isfile(real) or not os.access(real, os.X_OK):
        raise ValueError('not an existing executable file')
    return text


def _parse_config_dir(text):
    if not text:
        return None
    if not os.path.isabs(text) or os.path.normpath(text) != text:
        raise ValueError('enter a normalized absolute path, or leave blank for the default')
    if not os.path.isdir(text):
        raise ValueError('not an existing directory (only its existence is checked)')
    return text


def _parse_roles(text):
    roles = [part.strip() for part in text.split(',') if part.strip()]
    if not roles or len(set(roles)) != len(roles) or any(r not in inputs.ROLES for r in roles):
        raise ValueError('enter implement, review or implement,review')
    return roles


def _parse_argv(text):
    try:
        argv = json.loads(text)
    except ValueError:
        raise ValueError('not valid JSON; enter an array such as ["/usr/bin/make", "test"]') from None
    if type(argv) is not list or not 1 <= len(argv) <= 64 or any(type(a) is not str for a in argv):
        raise ValueError('enter a JSON array of 1-64 strings')
    if not os.path.isabs(argv[0]):
        raise ValueError('the first element must be an absolute executable path')
    return argv


def _rel_file_parser(root):
    def parse(text):
        parts = text.split('/')
        if (os.path.isabs(text) or '\\' in text or any(p in ('', '.', '..') for p in parts)
                or not os.path.isfile(os.path.join(root, text))):
            raise ValueError('enter an existing repository-relative file path')
        return text
    return parse


def _ask_lines(prompt, parse, limit):
    items = []
    while len(items) < limit:
        item = _ask_valid(prompt, _optional(parse), '')
        if not item:
            break
        if item in items:
            _say('  already listed')
            continue
        items.append(item)
    return items


def _ask_profile(number, taken):
    provider = _ask_valid(f'Profile {number} provider (claude/codex)',
                          _choice_parser(inputs.PROVIDERS), 'claude')
    profile_id = _ask_valid(f'Profile {number} id', _id_parser(taken), f'{provider}-{number}')
    executable = _ask_valid(f'Profile {number} {provider} executable (absolute path)',
                            _parse_executable, shutil.which(provider))
    variable, leaf = inputs.DEFAULT_CONFIG[provider]
    config_dir = _ask_valid(f'Profile {number} config directory (absolute; blank = ${variable} '
                            f'or ~/{leaf}, resolved once and frozen)', _parse_config_dir, '')
    default_roles = 'review' if provider == 'codex' and number > 1 else 'implement,review'
    roles = _ask_valid(f'Profile {number} roles (fresh session per attempt)', _parse_roles,
                       default_roles)
    return {'id': profile_id, 'provider': provider, 'executable': executable,
            'config_dir': config_dir, 'roles': roles}


def _ask_profiles():
    profiles = [_ask_profile(1, set())]
    _say(ALIAS_NOTE)
    while len(profiles) < 16 and _ask_bool('Add another explicitly owner-authorized profile?'):
        profiles.append(_ask_profile(len(profiles) + 1, {p['id'] for p in profiles}))
    return profiles


def _ask_capacity(profiles):
    auto_route = _ask_bool('Route ready tasks automatically to eligible profiles (auto_route)?')
    max_parallel = _ask_int('Global max_parallel (owner concurrency choice across profiles)',
                            1, 1, 16)
    if max_parallel == 1:
        _say('review_reserve: 0 (single slot)')
        return auto_route, max_parallel, 0
    reviewers = any('review' in p['roles'] for p in profiles)
    reserve = _ask_int('review_reserve (slots kept for review)', 0, 0,
                       max_parallel - 1 if reviewers else 0)
    return auto_route, max_parallel, reserve


def _ask_limits():
    attempts = _ask_int('max_attempts per task and role', 3, 1, 20)
    attempt = _ask_int('attempt_seconds (wall-clock limit per attempt)', 1800, 1, 86400)
    total = _ask_int('max_total_seconds (runtime budget per plan)', max(7200, attempt), attempt,
                     604800)
    no_progress = _ask_int('max_no_progress (consecutive attempts without verified progress)',
                           2, 1, 20)
    _say(COST_NOTE)
    return {'max_attempts': attempts, 'attempt_seconds': attempt, 'max_total_seconds': total,
            'max_no_progress': no_progress, 'max_cost_usd': None}


def _ask_checks():
    checks = {}
    while len(checks) < 64:
        check_id = _ask_valid('Allowed check ID (blank to finish)', _optional(_id_parser(checks)),
                              '')
        if not check_id:
            break
        checks[check_id] = _ask_valid(f'Exact argv for {check_id} as a JSON array of strings '
                                      '(literal; no shell parsing)', _parse_argv)
    return checks


def _ask_delivery():
    return {
        'remote': _ask_valid('Delivery remote name', _id_parser(), 'origin'),
        'remote_url': _ask_valid('Delivery remote URL (https://, ssh:// or user@host:path; no '
                                 'credentials)', _pattern_parser(
                                     inputs.REMOTE_URL, 'a credential-free https, ssh or scp URL')),
        'github_repo': _ask_valid('GitHub repository (owner/name)',
                                  _pattern_parser(inputs.GITHUB_REPO, 'owner/name')),
        'base_branch': _ask_valid('Base branch', _pattern_parser(inputs.BRANCH, 'a branch'),
                                  'main'),
        'branch_prefix': _ask_valid('Controller branch prefix (ends with /)', _pattern_parser(
            inputs.BRANCH, 'a branch prefix ending in /'), 'sdlc/'),
        'required_checks': _ask_lines('Required CI check name (blank to finish)',
                                      _text_parser(200), 64),
        'merge_method': _ask_valid('Merge method (merge/squash)',
                                   _choice_parser(inputs.MERGE_METHODS), 'squash'),
    }


def _ask_effects():
    effects = [name for name in ('commit', 'integrate')
               if _ask_bool(f'Allow the local {name} effect?')]
    if not _ask_bool('Configure external publication (push/pr/merge) to a frozen delivery target?'):
        _say('External publication: disabled (delivery target null).')
        return effects, None
    delivery = _ask_delivery()
    for name in inputs.EXTERNAL_EFFECTS:
        if name == 'merge' and not delivery['required_checks']:
            _say('merge: not offered (automatic merge needs required CI check names)')
            continue
        if _ask_bool(f'Allow the external {name} effect?'):
            effects.append(name)
    return effects, delivery


def _ask_policy(root):
    profiles = _ask_profiles()
    auto_route, max_parallel, reserve = _ask_capacity(profiles)
    limits = _ask_limits()
    checks = _ask_checks()
    paths = _ask_lines('Existing instruction file, repository-relative (blank to finish)',
                       _rel_file_parser(root), 64)
    effects, delivery = _ask_effects()
    execution = _ask_bool('Enable execution (execution_enabled)?')
    background = _ask_bool('Authorize background runs (background_enabled; stored as policy '
                           'only, nothing is installed or started)?')
    return {'version': 1, 'repository': root, 'profiles': profiles, 'auto_route': auto_route,
            'execution_enabled': execution, 'background_enabled': background,
            'max_parallel': max_parallel, 'review_reserve': reserve, 'limits': limits,
            'allowed_checks': checks, 'effects': effects, 'delivery': delivery,
            'instruction_paths': paths}


def _show_policy(policy):
    print(json.dumps(policy, indent=2, sort_keys=True))
    limits, delivery = policy['limits'], policy['delivery']
    _say('Summary:')
    for profile in policy['profiles']:
        _say(f"  profile {profile['id']}: {profile['provider']}, roles "
             f"{'+'.join(profile['roles'])}, config {profile['config_dir']}")
    _say(f"  max_parallel {policy['max_parallel']}, review_reserve {policy['review_reserve']}, "
         f"auto_route {policy['auto_route']}")
    _say(f"  limits: attempts {limits['max_attempts']}, attempt {limits['attempt_seconds']}s, "
         f"plan total {limits['max_total_seconds']}s, no-progress {limits['max_no_progress']}; "
         'max_cost_usd null (no monetary cap)')
    target = f"to {delivery['github_repo']}" if delivery else 'disabled'
    _say(f"  effects: {', '.join(policy['effects']) or 'none'}; external publication: {target}")
    _say(f"  execution_enabled {policy['execution_enabled']}, background_enabled "
         f"{policy['background_enabled']} (policy only; nothing is installed or started)")


# ---- setup and init --------------------------------------------------------------

def _has_state(state):
    if not os.path.lexists(state):
        return False
    return os.path.islink(state) or not os.path.isdir(state) or bool(os.listdir(state))


def _show_existing(state):
    ledger = _open(state, readonly=True)
    try:
        policy = ledger.policy
    finally:
        ledger.close()
    _show_policy(policy)
    return _report('PASS', 'existing state preserved; setup changed nothing. Policy changes need '
                   'an explicit reconcile under STOP, not a re-run of setup')


def cmd_setup(args):
    state = _abs_arg(args.state, '--state')
    if _has_state(state):
        return _show_existing(state)
    repo = inputs.canonical_repo(_abs_arg(args.repo, '--repo'))
    root, common = repo['root'], repo['common_dir']
    if _within(state, (root, common)):
        raise CliError('FAIL', 'inside_repository', '--state must be outside the repository')
    if not os.path.isdir(os.path.dirname(state)):
        raise CliError('FAIL', 'path', 'the parent directory of --state must exist')
    if os.path.lexists(os.path.join(common, BINDING_FILE)):
        _say('Note: this repository already has a controller binding; setup will refuse unless '
             'it names this --state.')
    _say('Setup records the owner policy once. It does not start, install or schedule anything, '
         'log in, check authentication or read account contents.')
    try:
        frozen = inputs.validate_policy(_ask_policy(root))
        identity, head = _identity(frozen)
        _show_policy(frozen)
        answer = _ask("Type 'create' to write this policy and controller state (anything else "
                      'aborts)')
    except _Abort as err:
        return _report('INCOMPLETE', f'setup aborted ({err}); nothing was written')
    if answer != 'create':
        return _report('INCOMPLETE', 'setup aborted by the owner; nothing was written')
    ledger = initialize(state, frozen, common, identity)
    try:
        policy_digest = ledger.policy_digest
    finally:
        ledger.close()
    _print_identity(state, 'created', policy_digest, identity, head,
                    not _has_changes(root, [], untracked=True))
    return _report('PASS', f'policy and state created; policy snapshot {POLICY_FILE} is in --state. '
                   'Nothing was started')


def cmd_init(args):
    state = _abs_arg(args.state, '--state')
    policy = inputs.read_policy(_abs_arg(args.policy, '--policy'))
    common = inputs.canonical_repo(policy['repository'])['common_dir']
    existed = os.path.lexists(os.path.join(state, LEDGER_FILE))
    identity, head = _identity(policy)
    ledger = initialize(state, policy, common, identity)
    try:
        policy_digest = ledger.policy_digest
    finally:
        ledger.close()
    verb = 'verified unchanged' if existed else 'created'
    _print_identity(state, verb, policy_digest, identity, head,
                    not _has_changes(policy['repository'], [], untracked=True))
    return _report('PASS', f'state {verb}; nothing was started')


# ---- status ---------------------------------------------------------------------

def _print_status(report):
    status, policy, work, check = (report['status'], report['policy'], report['owned_work'],
                                   report['identity_check'])
    stale = sorted(plan['id'] for plan in report['plans'] if plan['stale'])
    counts = Counter(task['state'] + ('(stale plan)' if task['plan_id'] in stale else '')
                     for task in status['tasks'])
    requests = Counter(item['status'] for item in report['requests'])
    unknown = sum(1 for attempt in work['attempts'] if attempt['state'] == 'unknown')
    reason = f" ({check['reason']})" if check['reason'] else ''
    held = (check['runtime'], check['rules']) != ('match', 'match')
    print('\n'.join([
        f"state: {report['state_dir']}",
        f"repository: {policy['repository']}",
        f"control: {status['control']} (fence {status['fence']})",
        f"context: epoch {status['epoch']} " + ('HOLD: this runtime/rules identity is not the '
                                                'current context; only recover until reconcile'
                                                if held else 'current'),
        f"policy: {status['policy_digest']} execution_enabled={policy['execution_enabled']} "
        f"background_enabled={policy['background_enabled']}",
        f"identity: runtime {check['runtime']}, rules {check['rules']}{reason}",
        'profiles: ' + ', '.join(f"{p['id']}({p['provider']}:{'+'.join(p['roles'])})"
                                 for p in policy['profiles']),
        f"plans: {len(report['plans'])}; stale (earlier context; acceptance is not current, "
        f"readmit needed): {', '.join(stale) or 'none'}",
        'tasks: ' + (', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'none'),
        'requests: ' + (', '.join(f'{k}={v}' for k, v in sorted(requests.items())) or 'none')
        + ' (pending = queued, not admitted; admitted = recorded, not executed)',
        f"unresolved attempts: {len(work['attempts'])} (unknown {unknown})",
        f"unresolved effects: {len(work['effects'])}; workspaces not removed: "
        f"{len(work['workspaces'])}",
        f"charged seconds: {status['charged_seconds']} (per-plan limit "
        f"{policy['limits']['max_total_seconds']}); monetary cost: not measured",
    ]))


def cmd_status(args):
    state = _abs_arg(args.state, '--state')
    ledger = _open(state, readonly=True)
    try:
        status, work, plans = ledger.status(), ledger.owned_work(), ledger.plans()
        policy, recorded = ledger.policy, ledger.identity
    finally:
        ledger.close()
    report = {'state_dir': state, 'policy': policy, 'status': status, 'owned_work': work,
              'plans': plans, 'requests': inbox.list_requests(state),
              'identity_check': _identity_check(policy, recorded)}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_status(report)
    return _report('PASS', 'status read (read-only; nothing was changed)')


# ---- queued requests --------------------------------------------------------------

def _context_view(state):
    ledger = _open(state, readonly=True)
    try:
        return (ledger.policy, inbox.current_context(ledger), ledger.control(),
                ledger.plans())
    finally:
        ledger.close()


def _report_queued(queued, detail, control):
    print(f"request: {queued['id']}")
    print(detail)
    ack = queued['ack']
    if ack is not None:
        return _report(ACK_OUTCOME[ack['outcome']], f"identical request already acknowledged: "
                       f"{ack['outcome']} ({ack['code']}); nothing was queued")
    if control == 'stopped':
        _say('control is stopped: the request stays pending until an explicit resume')
    verb = 'queued' if queued['status'] == 'queued' else 'already queued (identical request)'
    return _report('PASS', f'request {verb}; not admitted yet. A controller holding the '
                   'repository lease admits it through the ledger; see status. Nothing was '
                   'executed')


def cmd_digest(args):
    policy = inputs.read_policy(_abs_arg(args.policy, '--policy'))
    plan = inputs.read_plan(_abs_arg(args.plan, '--plan'), policy)
    print(inputs.canonical_digest(plan))
    _say('Prepare the authority yourself as a private (0600) JSON file outside the repository: '
         f"version 1, this plan_digest, effects within {policy['effects']}, authorizer, "
         'approved_at (UTC, ...Z). This tool never creates authority.')
    return _report('PASS', f"canonical digest of plan {plan['id']}")


def cmd_submit(args):
    state = _abs_arg(args.state, '--state')
    plan_path = _abs_arg(args.plan, '--plan')
    authority_path = _abs_arg(args.authority, '--authority')
    policy, context, control, plans = _context_view(state)
    _current_identity(policy, context['identity'], 'queued')
    plan = inputs.read_plan(plan_path, policy)
    authority = inputs.read_authority(authority_path, policy, plan)
    plan_digest = inputs.canonical_digest(plan)
    known = next((row for row in plans if row['id'] == plan['id']), None)
    if known is not None and known['digest'] != plan_digest:
        raise CliError('FAIL', 'plan_changed', 'plan id already recorded with other content; '
                       'nothing was queued')
    if known is not None and known['stale']:
        raise CliError('FAIL', 'plan_stale', 'plan was admitted under an earlier context; use '
                       'readmit with a new declaration; nothing was queued')
    if known is not None:
        print(f'plan_digest: {plan_digest}')
        return _report('PASS', 'plan already admitted under the current context; nothing was '
                       'queued')
    queued = inbox.enqueue(state, inbox.submit_request(plan, authority, context))
    return _report_queued(queued, f'plan_digest: {plan_digest}', control)


def cmd_refresh_profile(args):
    state = _abs_arg(args.state, '--state')
    actor = _actor(args.actor)
    policy, context, control, _ = _context_view(state)
    _current_identity(policy, context['identity'], 'queued')
    profile = next((p for p in policy['profiles'] if p['id'] == args.profile), None)
    if profile is None:
        raise CliError('FAIL', 'unknown_profile', 'no such profile in the current policy; '
                       'nothing was queued')
    queued = inbox.enqueue(state, inbox.refresh_request(profile['id'], profile['provider'],
                                                        actor, context))
    _say(REFRESH_NOTE)
    return _report_queued(queued, f"profile: {profile['id']} ({profile['provider']})", control)


# ---- control and context ----------------------------------------------------------

def _set_control(args, target):
    ledger = _open(_abs_arg(args.state, '--state'), readonly=False)
    try:
        current = ledger.control()
        if current == target:
            return _report('PASS', f'control already {target}; nothing changed')
        if target == 'paused' and current == 'stopped':
            raise CliError('FAIL', 'stopped', 'controller is stopped; STOP is cleared only by an '
                           'explicit resume')
        ledger.set_control(target, actor='operator-cli')
        work = ledger.owned_work()
    finally:
        ledger.close()
    unknown = sum(1 for attempt in work['attempts'] if attempt['state'] == 'unknown')
    _say(f"held work: {len(work['attempts'])} unresolved attempts ({unknown} unknown), "
         f"{len(work['effects'])} unresolved effects; control changes clear none of them")
    return _report('PASS', f'control {current} -> {target} recorded')


def cmd_pause(args):
    return _set_control(args, 'paused')


def cmd_stop(args):
    return _set_control(args, 'stopped')


def cmd_resume(args):
    return _set_control(args, 'running')


def cmd_reconcile(args):
    state = _abs_arg(args.state, '--state')
    actor = _actor(args.actor)
    probe = _open(state, readonly=True)
    try:
        common, recorded = probe.common_dir, probe.policy
    finally:
        probe.close()
    if args.policy is None:
        _check_frozen(recorded)
        policy = recorded
    else:
        policy = inputs.read_policy(_abs_arg(args.policy, '--policy'))
    identity, head = _identity(policy)
    with ControllerLock(common, state, identity=identity) as ledger:
        result = ledger.reconcile_context(policy, identity, actor)
        control = ledger.control()
    print(f"epoch: {result['epoch']} ({'appended' if result['changed'] else 'unchanged'})")
    print(f"stale_plans: {', '.join(result['stale_plans']) or 'none'}")
    print(f"rules_digest: {identity['rules']} (committed instruction blobs at {head})")
    _say(f'control stays {control}; resume is a separate explicit owner action. No policy file '
         'outside --state was written')
    if not result['changed']:
        return _report('PASS', 'policy and identity equal the current context; nothing appended')
    return _report('PASS', 'new context recorded; stale plans need an explicit readmit')


def cmd_readmit(args):
    state = _abs_arg(args.state, '--state')
    authority_path = _abs_arg(args.authority, '--authority')
    _actor(args.actor)
    _plan_id(args.plan_id)
    probe = _open(state, readonly=True)
    try:
        common, policy, recorded = probe.common_dir, probe.policy, probe.identity
        saved = probe.plan(args.plan_id)
    finally:
        probe.close()
    if not saved['stale']:
        raise CliError('FAIL', 'plan_current', 'plan is already admitted under the current '
                       'context; nothing changed')
    identity = _current_identity(policy, recorded, 'readmitted')
    authority = inputs.read_authority(authority_path, policy, saved['body'])
    with ControllerLock(common, state, identity=identity) as ledger:
        result = ledger.readmit_plan(args.plan_id, authority, identity)
    if result['status'] == 'hold':
        print(f"held: attempts {len(result['attempts'])}, effects {len(result['effects'])}, "
              f"workspaces {len(result['workspaces'])}")
        return _report('INCOMPLETE', 'readmission held by unsettled owned work of this plan; '
                       'nothing changed. Run recover (it deletes no workspace; '
                       'cleanup-workspaces removes clean ones of this plan under STOP), '
                       'then retry')
    print(f"epoch: {result['epoch']}")
    print('tasks: ' + ', '.join(f'{k}={v}' for k, v in result['tasks'].items()))
    return _report('PASS', 'unchanged plan readmitted with the new declaration; bindings, checks '
                   'and review must be re-earned; counters and history kept; STOP unchanged')


# ---- engine entrypoints ------------------------------------------------------------

def _signal_stop(state, name):
    try:
        ledger = Ledger.open(state)
        try:
            if ledger.control() != 'stopped':
                ledger.set_control('stopped', actor=f'signal:{name}')
        finally:
            ledger.close()
    except (LedgerError, sqlite3.Error, OSError) as err:
        _say(f'{name}: STOP could not be recorded ({type(err).__name__}); run stop --state')
        return
    _say(f'{name}: durable STOP recorded; the engine drains owned work. Repeat the signal to '
         'exit immediately; resume is an explicit owner action.')


def _trap_signals(state):
    """First signal requests a durable STOP from a helper thread (never inside an engine
    transaction); the original handler is restored so a repeat exits immediately."""
    previous = {}

    def handler(signum, _frame):
        signal.signal(signum, previous[signum])
        name = signal.Signals(signum).name
        threading.Thread(target=_signal_stop, args=(state, name), daemon=True).start()

    for name in STOP_SIGNALS:
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.signal(number, handler)
    return previous


def _require_engine():
    path = RUNTIME_DIR / ENGINE_FILE
    if not path.is_file():
        raise CliError('INCOMPLETE', 'runtime_missing', f'{ENGINE_FILE} is not installed next to '
                       'controller.py; nothing ran')
    return path


def _load_engine(entrypoint):
    module = sys.modules.get('controller_engine')
    if module is None:
        spec = importlib.util.spec_from_file_location('controller_engine', _require_engine())
        module = importlib.util.module_from_spec(spec)
        sys.modules['controller_engine'] = module
        try:
            spec.loader.exec_module(module)
        except Exception as err:
            sys.modules.pop('controller_engine', None)
            raise CliError('INCOMPLETE', 'runtime_unavailable', f'{ENGINE_FILE} failed to load '
                           f'({type(err).__name__}); nothing ran') from err
    entry = getattr(module, entrypoint, None)
    if not callable(entry):
        raise CliError('INCOMPLETE', 'runtime_unavailable', f'{ENGINE_FILE} has no '
                       f'{entrypoint}; nothing ran')
    return entry


def _engine_outcome(result, message):
    outcome = {0: 'PASS', 1: 'FAIL', 2: 'INCOMPLETE'}.get(result) if type(result) is int else None
    if outcome is None:
        return _report('INCOMPLETE', 'engine returned no recognized outcome')
    return _report(outcome, message)


def _poll(value):
    low, high = POLL_RANGE
    if not math.isfinite(value) or not low <= value <= high:
        raise CliError('FAIL', 'poll_seconds', f'--poll-seconds must be within {low}..{high}')
    return value


def cmd_run(args):
    state = _abs_arg(args.state, '--state')
    poll = _poll(args.poll_seconds)
    ledger = _open(state, readonly=True)
    try:
        policy, recorded = ledger.policy, ledger.identity
    finally:
        ledger.close()
    if args.background and not policy['background_enabled']:
        raise CliError('FAIL', 'background_disabled', 'policy does not authorize background runs')
    _require_engine()
    _current_identity(policy, recorded, 'run')
    runner = _load_engine('run_controller')
    previous = _trap_signals(state)
    try:
        result = runner(state, once=bool(args.once), background=bool(args.background),
                        poll_seconds=poll)
    except KeyboardInterrupt:
        return _report('INCOMPLETE', 'interrupted; unresolved work stays recorded in the ledger')
    except Exception as err:
        return _report('FAIL', f'engine raised {type(err).__name__}; inspect status')
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    return _engine_outcome(result, 'engine run finished; see status')


def cmd_recover(args):
    """Cleanup of positively owned work only; allowed under a context hold. It never
    executes tasks, admits requests, clears STOP or reconciles the context."""
    state = _abs_arg(args.state, '--state')
    _open(state, readonly=True).close()
    recover = _load_engine('recover_owned')
    try:
        result = recover(state)
    except KeyboardInterrupt:
        return _report('INCOMPLETE', 'interrupted; unresolved work stays recorded in the ledger')
    except Exception as err:
        return _report('FAIL', f'engine recovery raised {type(err).__name__}; inspect status')
    return _engine_outcome(result, 'recovery finished (cleanup only; STOP and context '
                           'unchanged); see status')


def cmd_cleanup_workspaces(args):
    """Owner-requested removal of confirmed clean managed worktrees of ONE explicit plan.
    The concrete invocation is the owner's effect request. The read-only precheck exists
    only for a useful message: the engine is the final owner and takes the lock and
    revalidates everything. Allowed under a context hold; never clears STOP, resumes or
    reconciles."""
    state = _abs_arg(args.state, '--state')
    actor = _actor(args.actor)
    plan_id = _plan_id(args.plan_id)
    probe = _open(state, readonly=True)
    try:
        control = probe.control()
        probe.plan(plan_id)
    finally:
        probe.close()
    if control != 'stopped':
        raise CliError('FAIL', 'control_required', 'cleanup-workspaces needs a durable STOP; run '
                       'stop first; nothing was removed')
    cleanup = _load_engine('cleanup_workspaces')
    try:
        result = cleanup(state, plan_id, actor)
    except KeyboardInterrupt:
        return _report('INCOMPLETE', 'interrupted; unresolved work stays recorded in the ledger')
    except Exception as err:
        return _report('FAIL', f'engine workspace cleanup raised {type(err).__name__}; inspect '
                       'status')
    return _engine_outcome(result, f'cleanup-workspaces returned for plan {plan_id} (only '
                           'confirmed clean managed worktrees are removed; branches, commits '
                           'and history kept; dirty or unknown held; STOP and context '
                           'unchanged); see status')


COMMANDS = {'setup': cmd_setup, 'init': cmd_init, 'status': cmd_status, 'digest': cmd_digest,
            'submit': cmd_submit, 'refresh-profile': cmd_refresh_profile, 'pause': cmd_pause,
            'stop': cmd_stop, 'resume': cmd_resume, 'reconcile': cmd_reconcile,
            'readmit': cmd_readmit, 'recover': cmd_recover,
            'cleanup-workspaces': cmd_cleanup_workspaces, 'run': cmd_run}


def build_parser():
    parser = _Parser(prog='controller.py', description=DESCRIPTION,
                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True, metavar='COMMAND')

    def command(name, help_text, *, state=True):
        child = sub.add_parser(name, help=help_text, description=help_text)
        if state:
            child.add_argument('--state', required=True, help='absolute state directory')
        return child

    command('setup', 'interactive one-time policy and state creation').add_argument(
        '--repo', required=True, help='absolute repository path')
    command('init', 'create or re-verify state from an owner-private policy').add_argument(
        '--policy', required=True, help='absolute owner-private (0600) policy JSON')
    command('status', 'read-only status').add_argument('--json', action='store_true')
    submit = command('submit', 'validate a plan and its owner-private authority and queue a '
                     'request (no lock; a running controller admits it)')
    submit.add_argument('--plan', required=True)
    submit.add_argument('--authority', required=True)
    refresh = command('refresh-profile', 'queue an explicit operator refresh of one profile '
                      '(availability stays unknown; no login or auth check)')
    refresh.add_argument('--profile', required=True, help='profile id from the current policy')
    refresh.add_argument('--actor', required=True, help='who requests the refresh')
    digest = command('digest', 'print the canonical plan digest for preparing authority',
                     state=False)
    digest.add_argument('--plan', required=True)
    digest.add_argument('--policy', required=True)
    command('pause', 'pause new claims (not allowed while stopped)')
    command('stop', 'durable STOP; cleared only by resume')
    command('resume', 'explicit owner resume; clears no unresolved attempts')
    reconcile = command('reconcile', 'record a new context epoch under STOP with no owned work')
    reconcile.add_argument('--policy', help='absolute owner-private policy JSON (default: the '
                           'recorded frozen policy, unchanged)')
    reconcile.add_argument('--actor', required=True)
    readmit = command('readmit', 'readmit an unchanged stale plan with a new owner declaration')
    readmit.add_argument('--plan-id', required=True)
    readmit.add_argument('--authority', required=True)
    readmit.add_argument('--actor', required=True)
    command('recover', 'engine cleanup of positively owned work only (works under a context '
            'hold; no execution, deletes no workspace, STOP unchanged)')
    cleanup = command('cleanup-workspaces', 'explicit owner request: the engine deletes the '
                      'confirmed clean controller-managed worktrees of one plan (needs STOP; '
                      'branches, commits and history are kept; dirty or unknown worktrees are '
                      'held; works under a context hold; never resumes)')
    cleanup.add_argument('--plan-id', required=True, help='explicit plan id')
    cleanup.add_argument('--actor', required=True, help='who requests the cleanup')
    run = command('run', 'run the engine in this foreground process (never auto-started)')
    run.add_argument('--once', action='store_true', help='single pass')
    run.add_argument('--background', action='store_true',
                     help='unattended mode; needs policy background_enabled')
    run.add_argument('--poll-seconds', type=float, default=5.0,
                     help=f'poll interval within {POLL_RANGE[0]}..{POLL_RANGE[1]}')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except CliError as err:
        return _report(err.outcome, str(err))
    except inputs.InputError as err:
        return _report('FAIL', str(err))
    except inbox.RequestError as err:
        return _report('INCOMPLETE' if err.code == 'missing' else 'FAIL', str(err))
    except LedgerError as err:
        return _report('INCOMPLETE' if err.code in INCOMPLETE_CODES else 'FAIL',
                       str(err) + LEDGER_HINTS.get(err.code, ''))
    except sqlite3.OperationalError:
        return _report('INCOMPLETE', 'ledger busy or unavailable; nothing was changed by this '
                       'command; retry')
    except sqlite3.Error:
        return _report('FAIL', 'ledger database error')
    except OSError as err:
        return _report('FAIL', f'{type(err).__name__}: {err.strerror or "operating system error"}')
    except KeyboardInterrupt:
        return _report('INCOMPLETE', 'interrupted')
    except Exception as err:
        return _report('FAIL', f'unexpected {type(err).__name__} (details withheld)')


if __name__ == '__main__':
    sys.exit(main())
