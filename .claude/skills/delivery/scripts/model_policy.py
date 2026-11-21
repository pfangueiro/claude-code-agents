#!/usr/bin/env python3
"""Opt-in model selection and model-version lifecycle policy for attended delivery.

Read-only JSON CLI and pure decision API (standard library only, Python 3.11+). Nothing here
invokes a provider, discovers accounts, reads credentials or provider configuration, changes a
model, effort, approval, sandbox or default, or writes a file. Results go to stdout; the caller
keeps them as artifacts.

Owner policy
    One owner-global private file, $HOME/.config/sdlc/model-policy.json: a regular file owned
    by the current user, mode within 0600, no symlinked leaf or ancestor. There is no --policy
    flag and no project-local policy, so a worker cannot point this tool at a policy it wrote.
    Installers never create, trust or update the file.
        missing, or valid with "active": false  -> INHERIT (native configuration, no claim)
        present but malformed or unsafe        -> INCOMPLETE (never silently inherited)

Commands (exit 0 PLAN_READY / INHERIT / PASS, 1 FAIL, 2 usage error, 3 INCOMPLETE)
    status
        Policy state and digest, each binding's evaluation-artifact check, and the routes.
    select --request FILE [--capabilities FILE]
        A coordinator task declaration plus fresh host capability evidence for one exact
        invocation surface -> a selection record. PLAN_READY names the first owner-ordered
        approved binding for the request's provider and exact risk class that meets every
        requirement. It is a plan, never a runtime result. Anything else is INCOMPLETE.
    verify --selection FILE --request FILE [--capabilities FILE] (--stream FILE | --observation FILE)
        Recomputes the retained selection from the current inputs at its recorded decision
        time (input drift is INCOMPLETE; a record whose policy, request, capability or
        selected fields differ from the recomputation is FAIL), then compares the requested
        model and effort with a host observation file or native provider JSONL. In a native
        Claude stream the served model is the one named on the assistant messages,
        cross-checked with the terminal modelUsage. The init event names only the configured
        model, so an init plus a successful terminal alone is INCOMPLETE. A stream with any
        line that is not a strict JSON object (a repeated key, a non-finite number) carries
        no model identity and is INCOMPLETE. An agent's own statement about its model is
        never evidence.

Schemas, workflow and limits: references/model-policy.md in this skill.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True  # read-only tool: never leave bytecode beside installed sources
RUNTIME_DIR = Path(__file__).resolve().parent


def _load_sibling(name: str, filename: str):
    """Load a co-located module by exact path under a private name, once per interpreter."""
    path = RUNTIME_DIR / filename
    loaded = sys.modules.get(name)
    location = getattr(loaded, '__file__', None)
    if location and Path(location).resolve() == path:
        return loaded
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'{filename} is not loadable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


inputs = _load_sibling('sdlc_model_policy_inputs', 'controller_inputs.py')
InputError = inputs.InputError

POLICY_PARTS = ('.config', 'sdlc', 'model-policy.json')
POLICY_DISPLAY = '~/.config/sdlc/model-policy.json'
SELECTION_SCHEMA = 'sdlc-model-selection/v1'
RUN_CHECK_SCHEMA = 'sdlc-model-run-check/v1'
STATUS_SCHEMA = 'sdlc-model-policy-status/v1'
EVALUATION_SCHEMA = 'verified-handoff/agent-eval-result/v2'
PROVIDERS = inputs.PROVIDERS
RISKS = ('routine', 'complex', 'critical')
ROLES = ('coordinate', 'implement', 'review', 'verify')
CONTROLLER_SURFACE = 'delivery-controller'
# Exact invocation surfaces and the provider each belongs to. The persistent controller emits
# no model or effort flag, so a request for it is always INCOMPLETE.
SURFACES = {'claude-cli': 'claude', 'claude-agent': 'claude', 'codex-cli': 'codex',
            'codex-spawn': 'codex', 'codex-fork': 'codex', CONTROLLER_SURFACE: None}
STATUSES = ('candidate', 'approved', 'revoked')
MODEL_CONTROLS = ('per-invocation', 'inherit-only', 'role-default')
EFFORT_CONTROLS = ('per-invocation', 'unsupported')
TERMINALS = ('success', 'failed', 'interrupted', 'unknown')
SOURCE_KINDS = {'git-sha': inputs.SHA, 'sha256': inputs.DIGEST}
POLICY_KEYS = ('version', 'active', 'evidence_max_age_seconds', 'bindings', 'routes')
BINDING_KEYS = ('provider', 'model', 'effort', 'pinned', 'capabilities', 'status', 'evaluation',
                'approval')
EVALUATION_KEYS = ('path', 'sha256', 'model')
APPROVAL_KEYS = ('by', 'at')
REQUEST_KEYS = ('version', 'task_id', 'source', 'declared_by', 'provider', 'role', 'risk',
                'surface', 'capabilities')
REQUEST_SUMMARY = ('task_id', 'source', 'declared_by', 'provider', 'role', 'risk', 'surface',
                   'capabilities')
SOURCE_KEYS = ('kind', 'value')
EVIDENCE_KEYS = ('version', 'provider', 'surface', 'observed_at', 'observed_by', 'client_version',
                 'model_control', 'effort_control', 'models')
EVIDENCE_SUMMARY = ('surface', 'observed_at', 'observed_by', 'client_version', 'model_control',
                    'effort_control')
EVIDENCE_MODEL_KEYS = ('available', 'resolves_to', 'efforts')
OBSERVATION_KEYS = ('version', 'selection_sha256', 'provider', 'surface', 'observed_by',
                    'observed_model', 'observed_effort', 'terminal')
SELECTION_KEYS = ('schema', 'decided_at', 'decision', 'reasons', 'detail', 'policy', 'request',
                  'capabilities', 'selected', 'considered', 'executed', 'limitations')
# Retained selection fields that are a pure function of the digest-bound inputs and the selected
# binding: verify requires each one to equal its recomputation.
SELECTION_DERIVED = ('decision', 'reasons', 'detail', 'policy', 'request', 'capabilities',
                     'executed')
MAX_POLICY_BYTES = 256 << 10
MAX_INPUT_BYTES = 64 << 10
MAX_SELECTION_BYTES = 256 << 10
MAX_EVALUATION_BYTES = 8 << 20
MAX_STREAM_BYTES = 32 << 20
MAX_BINDINGS = 64
MAX_ROUTE = 16
MAX_TAGS = 32
MAX_EVIDENCE_MODELS = 64
MODEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}')
TOKEN = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}')
EXIT = {'PLAN_READY': 0, 'INHERIT': 0, 'PASS': 0, 'FAIL': 1, 'INCOMPLETE': 3}
STREAM_TERMINALS = {'success': 'success', 'interrupted': 'interrupted', 'incomplete': 'unknown'}
LIMITATIONS = (
    'trusted inputs, not authentication: the owner policy, coordinator request and host '
    'capability evidence must pass private-file checks (owned by the current user, mode '
    'within 0600, no symlink); the retained selection, provider stream, host observation and '
    'evaluation artifacts are caller-trusted regular files read with no mode or ownership '
    'requirement; none of these checks or digests is a signature, a sandbox or a boundary '
    'against the same OS user',
    'PLAN_READY is a plan: this tool invokes nothing and renders no flags',
    'verify compares observed metadata with the retained plan; it does not prove that the '
    'planned model and effort were passed to the invocation, or that a stream or observation '
    'belongs to this task: the caller links the actual argv, session and raw log to the '
    'exact-input execution receipt, and the selection digest inside an observation is the '
    'host\'s assertion, not authentication',
    'native stream identity is the model named on each assistant message, cross-checked with '
    'the terminal modelUsage when present; the init event is configuration only, an extra '
    'model in modelUsage is unexplained (INCOMPLETE), and streams carry no effort',
    'a verify result is evidence about one run, not acceptance of the work: exact-input check '
    'receipts and independent review remain separate gates',
    'capability evidence is one host observation of one invocation surface at observed_at; '
    'support can change afterwards, and unknown support is never treated as supported',
    'a pinned identifier is the most specific model ID the provider accepts; it does not '
    'guarantee immutable backend weights, and unpinned bindings report version_pinned false',
    'evaluation artifacts are bound by digest and exact observed model; whether their tasks '
    'cover the routed work is the owner\'s judgment, and an offline fixture is not efficacy '
    'evidence',
    'the persistent delivery controller does not apply this policy: its providers emit no model '
    'or effort flag, so controller runs inherit native configuration',
    'verify shows that a retained selection is consistent with the current inputs at its '
    'recorded decision time; it cannot prove when the decision was made',
    'no model-name strength ranking, expiry, reset or pricing is inferred; ordering and '
    'approvals are owner data',
)


# ---- primitives -------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _stamp(moment: _dt.datetime) -> str:
    return moment.astimezone(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _moment(value, where: str) -> _dt.datetime:
    inputs._match(value, inputs.UTC_STAMP, where)
    try:
        return _dt.datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as err:
        raise InputError('schema', f'{where} is not a valid UTC timestamp') from err


def _model(value, where: str) -> str:
    return inputs._match(value, MODEL_ID, where)


def _tags(value, where: str) -> list:
    items = inputs._list(value, where, max_len=MAX_TAGS)
    return inputs._unique([inputs._match(item, TOKEN, f'{where}[]') for item in items], where)


def _read_private_json(path, where: str, validator) -> tuple[dict, str]:
    """(validated data, sha256 of the exact bytes) of an owner/coordinator private file."""
    if path is None:
        raise InputError('file', f'{where} was not supplied')
    target = inputs.private_file(path)
    raw = inputs._read_regular(target, where, MAX_INPUT_BYTES, 0o600)
    return validator(inputs._parse_json(raw, where)), _sha256(raw)


def _private_digest(path) -> str | None:
    """sha256 of a private input file's bytes, or None when it is absent or unsafe."""
    if path is None:
        return None
    try:
        target = inputs.private_file(path)
        return _sha256(inputs._read_regular(target, 'input', MAX_INPUT_BYTES, 0o600))
    except InputError:
        return None


def _read_artifact(path, where: str, limit: int) -> bytes:
    """Bytes of a retained artifact: absolute, no symlinked leaf or ancestor, regular file."""
    if path is None:
        raise InputError('file', f'{where} was not supplied')
    text = inputs._abs_path(os.fspath(path), where)
    if os.path.realpath(text) != text:
        raise InputError('file', f'{where} must not be reached through a symlink')
    return inputs._read_regular(text, where, limit)


# ---- schemas ----------------------------------------------------------------------

def _validate_binding(binding, where: str) -> None:
    inputs._fields(binding, BINDING_KEYS, where)
    inputs._enum(binding['provider'], PROVIDERS, f'{where}.provider')
    model = _model(binding['model'], f'{where}.model')
    if binding['effort'] is not None:
        inputs._match(binding['effort'], TOKEN, f'{where}.effort')
    inputs._bool(binding['pinned'], f'{where}.pinned')
    _tags(binding['capabilities'], f'{where}.capabilities')
    status = inputs._enum(binding['status'], STATUSES, f'{where}.status')
    evaluation, approval = binding['evaluation'], binding['approval']
    if evaluation is not None:
        inputs._fields(evaluation, EVALUATION_KEYS, f'{where}.evaluation')
        inputs._abs_path(evaluation['path'], f'{where}.evaluation.path')
        inputs._match(evaluation['sha256'], inputs.DIGEST, f'{where}.evaluation.sha256')
        if _model(evaluation['model'], f'{where}.evaluation.model') != model:
            raise InputError('schema', f'{where}.evaluation.model must equal the binding model')
    if approval is not None:
        inputs._fields(approval, APPROVAL_KEYS, f'{where}.approval')
        inputs._text(approval['by'], f'{where}.approval.by', limit=200)
        inputs._timestamp(approval['at'], f'{where}.approval.at')
    if status == 'approved' and (evaluation is None or approval is None):
        raise InputError('unauthorized', f'{where} is approved without both an evaluation and '
                                         'an owner approval')
    if status == 'candidate' and approval is not None:
        raise InputError('unauthorized', f'{where} is a candidate carrying an approval; an '
                                         'approval needs status approved')


def _validate_routes(routes, bindings: dict) -> None:
    if type(routes) is not dict or not set(routes) <= set(PROVIDERS):
        raise InputError('schema', f'policy.routes must be an object keyed by {list(PROVIDERS)}')
    for provider, classes in routes.items():
        if type(classes) is not dict or not set(classes) <= set(RISKS):
            raise InputError('schema', f'policy.routes.{provider} must be an object keyed by '
                                       f'{list(RISKS)}')
        for risk, route in classes.items():
            where = f'policy.routes.{provider}.{risk}'
            ids = inputs._list(route, where, min_len=1, max_len=MAX_ROUTE)
            for binding_id in inputs._unique([inputs._match(item, inputs.SAFE_ID, f'{where}[]')
                                              for item in ids], where):
                binding = bindings.get(binding_id)
                if binding is None:
                    raise InputError('schema', f'{where} names unknown binding {binding_id}')
                if binding['provider'] != provider:
                    raise InputError('unauthorized', f'{where} names binding {binding_id} of '
                                                     'another provider')


def validate_policy(data) -> dict:
    """Validate an owner model policy (closed schema, version 1) and return a deep copy."""
    inputs._fields(data, POLICY_KEYS, 'policy')
    inputs._version(data['version'], 'policy')
    inputs._bool(data['active'], 'policy.active')
    inputs._int(data['evidence_max_age_seconds'], 60, 604800, 'policy.evidence_max_age_seconds')
    bindings = data['bindings']
    if type(bindings) is not dict or len(bindings) > MAX_BINDINGS:
        raise InputError('schema', f'policy.bindings must be an object of at most {MAX_BINDINGS} '
                                   'bindings')
    for binding_id, binding in bindings.items():
        inputs._match(binding_id, inputs.SAFE_ID, 'policy.bindings key')
        _validate_binding(binding, f'policy.bindings.{binding_id}')
    _validate_routes(data['routes'], bindings)
    return copy.deepcopy(data)


def validate_request(data) -> dict:
    """Validate a coordinator task declaration (closed schema, version 1)."""
    inputs._fields(data, REQUEST_KEYS, 'request')
    inputs._version(data['version'], 'request')
    inputs._match(data['task_id'], inputs.SAFE_ID, 'request.task_id')
    source = inputs._fields(data['source'], SOURCE_KEYS, 'request.source')
    kind = inputs._enum(source['kind'], tuple(SOURCE_KINDS), 'request.source.kind')
    inputs._match(source['value'], SOURCE_KINDS[kind], 'request.source.value')
    inputs._text(data['declared_by'], 'request.declared_by', limit=200)
    provider = inputs._enum(data['provider'], PROVIDERS, 'request.provider')
    inputs._enum(data['role'], ROLES, 'request.role')
    inputs._enum(data['risk'], RISKS, 'request.risk')
    surface = inputs._enum(data['surface'], tuple(SURFACES), 'request.surface')
    if SURFACES[surface] not in (None, provider):
        raise InputError('schema', 'request.surface belongs to another provider')
    _tags(data['capabilities'], 'request.capabilities')
    return copy.deepcopy(data)


def _surface(value, provider: str, where: str) -> str:
    native = tuple(name for name, owner in SURFACES.items() if owner is not None)
    surface = inputs._enum(value, native, where)
    if SURFACES[surface] != provider:
        raise InputError('schema', f'{where} belongs to another provider')
    return surface


def validate_evidence(data) -> dict:
    """Validate host capability evidence for one exact surface (closed schema, version 1)."""
    inputs._fields(data, EVIDENCE_KEYS, 'capabilities')
    inputs._version(data['version'], 'capabilities')
    provider = inputs._enum(data['provider'], PROVIDERS, 'capabilities.provider')
    _surface(data['surface'], provider, 'capabilities.surface')
    _moment(data['observed_at'], 'capabilities.observed_at')
    inputs._text(data['observed_by'], 'capabilities.observed_by', limit=200)
    if data['client_version'] is not None:
        inputs._text(data['client_version'], 'capabilities.client_version', limit=200)
    inputs._enum(data['model_control'], MODEL_CONTROLS, 'capabilities.model_control')
    inputs._enum(data['effort_control'], EFFORT_CONTROLS, 'capabilities.effort_control')
    models = data['models']
    if type(models) is not dict or len(models) > MAX_EVIDENCE_MODELS:
        raise InputError('schema', f'capabilities.models must be an object of at most '
                                   f'{MAX_EVIDENCE_MODELS} models')
    for model, entry in models.items():
        _model(model, 'capabilities.models key')
        where = f'capabilities.models.{model}'
        inputs._fields(entry, EVIDENCE_MODEL_KEYS, where)
        if entry['available'] is not None:
            inputs._bool(entry['available'], f'{where}.available')
        if entry['resolves_to'] is not None:
            _model(entry['resolves_to'], f'{where}.resolves_to')
        if entry['efforts'] is not None:
            _tags(entry['efforts'], f'{where}.efforts')
    return copy.deepcopy(data)


def validate_observation(data) -> dict:
    """Validate a host observation of one run (closed schema, version 1)."""
    inputs._fields(data, OBSERVATION_KEYS, 'observation')
    inputs._version(data['version'], 'observation')
    inputs._match(data['selection_sha256'], inputs.DIGEST, 'observation.selection_sha256')
    provider = inputs._enum(data['provider'], PROVIDERS, 'observation.provider')
    _surface(data['surface'], provider, 'observation.surface')
    inputs._text(data['observed_by'], 'observation.observed_by', limit=200)
    if data['observed_model'] is not None:
        _model(data['observed_model'], 'observation.observed_model')
    if data['observed_effort'] is not None:
        inputs._match(data['observed_effort'], TOKEN, 'observation.observed_effort')
    inputs._enum(data['terminal'], TERMINALS, 'observation.terminal')
    return copy.deepcopy(data)


# ---- owner policy -------------------------------------------------------------------

def policy_path(home=None) -> Path:
    base = os.fspath(home) if home is not None else os.path.expanduser('~')
    return Path(base, *POLICY_PARTS)


def load_policy(path) -> dict:
    """{'state': missing|inactive|active|invalid, 'policy', 'sha256', 'detail'}."""
    state = {'state': 'invalid', 'policy': None, 'sha256': None, 'detail': None}
    try:
        os.lstat(path)
    except FileNotFoundError:
        return dict(state, state='missing')
    except OSError as err:
        return dict(state, detail=f'file: model policy unavailable: {err.strerror}')
    try:
        target = inputs.private_file(path)
        raw = inputs._read_regular(target, 'model policy', MAX_POLICY_BYTES, 0o600)
        state['sha256'] = _sha256(raw)
        policy = validate_policy(inputs._parse_json(raw, 'model policy'))
    except InputError as err:
        return dict(state, detail=str(err))
    return dict(state, state='active' if policy['active'] else 'inactive', policy=policy)


def _policy_summary(state: dict) -> dict:
    return {'location': POLICY_DISPLAY, 'state': state['state'], 'sha256': state['sha256']}


# ---- evaluation artifacts -----------------------------------------------------------

def _evaluation_verdict(data, model: str) -> str | None:
    if type(data) is not dict or data.get('schema') != EVALUATION_SCHEMA:
        return 'evaluation-unsupported-schema'
    if data.get('outcome') != 'PASS':
        return 'evaluation-not-pass'
    rows = data.get('results')
    if type(rows) is not list or not rows:
        return 'evaluation-empty'
    if any(type(row) is not dict for row in rows):
        return 'evaluation-malformed'
    observed = [row.get('observed_model') for row in rows]
    if any(type(value) is not str for value in observed):
        return 'evaluation-model-unknown'
    if set(observed) != {model}:
        return 'evaluation-model-mismatch'
    candidate = [row for row in rows if row.get('arm') == 'candidate']
    if not candidate or any(row.get('outcome') != 'PASS' for row in candidate):
        return 'evaluation-candidate-not-pass'
    return None


def check_evaluation(evaluation: dict) -> str | None:
    """None when the artifact bytes match the pinned digest and record an agent-eval PASS in
    which every trial observed exactly the bound model; otherwise the reason it does not."""
    try:
        raw = _read_artifact(evaluation['path'], 'evaluation artifact', MAX_EVALUATION_BYTES)
    except InputError:
        return 'evaluation-unavailable'
    if _sha256(raw) != evaluation['sha256']:
        return 'evaluation-digest-mismatch'
    try:
        data = inputs._parse_json(raw, 'evaluation artifact')
    except InputError:
        return 'evaluation-malformed'
    return _evaluation_verdict(data, evaluation['model'])


def _route(policy: dict, request: dict) -> list:
    return policy['routes'].get(request['provider'], {}).get(request['risk']) or []


def evaluate_route(policy: dict, request: dict) -> dict:
    """{binding id: evaluation reason or None} for the approved bindings on the request's route."""
    results = {}
    for binding_id in _route(policy, request):
        binding = policy['bindings'][binding_id]
        if binding['status'] == 'approved':
            results[binding_id] = check_evaluation(binding['evaluation'])
    return results


# ---- decision (pure) ----------------------------------------------------------------

def binding_reasons(binding: dict, request: dict, evidence: dict,
                    evaluation_reason: str | None) -> list[str]:
    """Every reason one binding is not eligible for this request now (empty when eligible)."""
    if binding['status'] != 'approved':
        return [f'binding-{binding["status"]}']
    reasons = [evaluation_reason] if evaluation_reason else []
    if set(request['capabilities']) - set(binding['capabilities']):
        reasons.append('capability-missing')
    seen = evidence['models'].get(binding['model'])
    if seen is None:
        reasons.append('model-support-unknown')
    else:
        if seen['available'] is None:
            reasons.append('availability-unknown')
        elif not seen['available']:
            reasons.append('model-unavailable')
        if seen['resolves_to'] is None:
            reasons.append('model-resolution-unknown')
        elif seen['resolves_to'] != binding['model']:
            reasons.append('model-alias-mismatch')
    effort = binding['effort']
    if effort is not None:
        if evidence['effort_control'] != 'per-invocation':
            reasons.append('effort-control-unsupported')
        elif seen is None or seen['efforts'] is None:
            reasons.append('effort-support-unknown')
        elif effort not in seen['efforts']:
            reasons.append('effort-unsupported')
    return reasons


def _incomplete(reasons, considered=()) -> dict:
    return {'decision': 'INCOMPLETE', 'reasons': list(reasons), 'selected': None,
            'considered': list(considered)}


def _selected(binding_id: str, binding: dict, index: int) -> dict:
    return {'binding': binding_id, 'provider': binding['provider'], 'model': binding['model'],
            'effort': binding['effort'], 'version_pinned': binding['pinned'],
            'evaluation_sha256': binding['evaluation']['sha256'], 'route_index': index,
            'fallback': index > 0}


def decide(policy: dict, request: dict, evidence: dict | None, now: _dt.datetime,
           evaluations: dict) -> dict:
    """Pure decision for an ACTIVE validated policy, a validated request and validated evidence.

    Selects within the request's provider and exact risk class only, in owner order, the first
    approved binding with a qualifying evaluation, every required capability and fresh evidence
    that this exact surface can request that exact model (resolving to itself) and effort. No
    other class, provider or account is ever used. ``evaluations`` maps binding id to an
    evaluation reason or None (see evaluate_route); a missing entry is unchecked, not passing.
    """
    if request['surface'] == CONTROLLER_SURFACE:
        return _incomplete(['controller-unsupported'])
    if evidence is None:
        return _incomplete(['capabilities-missing'])
    if (evidence['provider'], evidence['surface']) != (request['provider'], request['surface']):
        return _incomplete(['evidence-surface-mismatch'])
    observed_at = _moment(evidence['observed_at'], 'capabilities.observed_at')
    if observed_at > now + inputs.CLOCK_SKEW:
        return _incomplete(['evidence-future'])
    if (now - observed_at).total_seconds() > policy['evidence_max_age_seconds']:
        return _incomplete(['evidence-stale'])
    if evidence['model_control'] != 'per-invocation':
        return _incomplete([f'surface-{evidence["model_control"]}'])
    route = _route(policy, request)
    if not route:
        return _incomplete(['no-route-for-risk'])
    considered = []
    for index, binding_id in enumerate(route):
        binding = policy['bindings'][binding_id]
        reasons = binding_reasons(binding, request, evidence,
                                  evaluations.get(binding_id, 'evaluation-unchecked'))
        considered.append({'binding': binding_id, 'eligible': not reasons, 'reasons': reasons})
        if not reasons:
            return {'decision': 'PLAN_READY', 'reasons': ['fallback-candidate'] if index else [],
                    'selected': _selected(binding_id, binding, index), 'considered': considered}
    return _incomplete(['no-eligible-candidate'], considered)


# ---- commands -----------------------------------------------------------------------

def select(request_path, evidence_path=None, *, home=None, now=None) -> dict:
    """Selection record for one coordinator request (read-only)."""
    now = now or _now()
    record = {'schema': SELECTION_SCHEMA, 'decided_at': _stamp(now), 'decision': 'INCOMPLETE',
              'reasons': [], 'detail': None, 'policy': None, 'request': None,
              'capabilities': None, 'selected': None, 'considered': [], 'executed': False,
              'limitations': list(LIMITATIONS)}
    state = load_policy(policy_path(home))
    record['policy'] = _policy_summary(state)
    if state['state'] in ('missing', 'inactive'):
        return dict(record, decision='INHERIT', reasons=[f'policy-{state["state"]}'])
    if state['state'] == 'invalid':
        return dict(record, reasons=['policy-invalid'], detail=state['detail'])
    try:
        request, request_sha = _read_private_json(request_path, 'request', validate_request)
    except InputError as err:
        return dict(record, reasons=['request-invalid'], detail=str(err))
    record['request'] = dict({key: request[key] for key in REQUEST_SUMMARY}, sha256=request_sha)
    evidence = None
    if evidence_path is not None and request['surface'] != CONTROLLER_SURFACE:
        try:
            evidence, evidence_sha = _read_private_json(evidence_path, 'capabilities',
                                                        validate_evidence)
        except InputError as err:
            return dict(record, reasons=['capabilities-invalid'], detail=str(err))
        record['capabilities'] = dict({key: evidence[key] for key in EVIDENCE_SUMMARY},
                                      sha256=evidence_sha)
    policy = state['policy']
    record.update(decide(policy, request, evidence, now, evaluate_route(policy, request)))
    return record


def _binding_status(binding: dict) -> dict:
    evaluation, approval = binding['evaluation'], binding['approval']
    check = None if evaluation is None else (check_evaluation(evaluation) or 'verified')
    return {'provider': binding['provider'], 'model': binding['model'], 'effort': binding['effort'],
            'pinned': binding['pinned'], 'status': binding['status'],
            'capabilities': list(binding['capabilities']),
            'approved_by': approval['by'] if approval else None,
            'evaluation_sha256': evaluation['sha256'] if evaluation else None,
            'evaluation_check': check,
            'approved_and_evaluated': binding['status'] == 'approved' and check == 'verified'}


def status(*, home=None) -> dict:
    """Read-only summary of the owner policy, its bindings and routes."""
    state = load_policy(policy_path(home))
    record = {'schema': STATUS_SCHEMA, 'policy': _policy_summary(state), 'detail': state['detail'],
              'evidence_max_age_seconds': None, 'bindings': None, 'routes': None,
              'limitations': list(LIMITATIONS)}
    policy = state['policy']
    if policy is None:
        return record
    record['evidence_max_age_seconds'] = policy['evidence_max_age_seconds']
    record['bindings'] = {binding_id: _binding_status(binding)
                          for binding_id, binding in policy['bindings'].items()}
    record['routes'] = copy.deepcopy(policy['routes'])
    return record


def _retained_selection(data) -> tuple:
    """(decided_at, recorded input digests) of a retained selection record with closed keys.

    Only the shape needed to recompute is validated here; verify then requires the retained
    fields to equal the recomputed record, so no unknown or altered field can reach PASS."""
    if type(data) is not dict or data.get('schema') != SELECTION_SCHEMA:
        raise InputError('schema', f'selection is not a {SELECTION_SCHEMA} record')
    inputs._fields(data, SELECTION_KEYS, 'selection')
    decision = inputs._enum(data['decision'], ('PLAN_READY', 'INHERIT', 'INCOMPLETE'),
                            'selection.decision')
    decided_at = _moment(data['decided_at'], 'selection.decided_at')
    digests = {}
    for key in ('policy', 'request', 'capabilities'):
        part = data[key]
        value = part.get('sha256') if type(part) is dict else None
        digests[key] = None if value is None else inputs._match(value, inputs.DIGEST,
                                                                f'selection.{key}.sha256')
    if decision == 'PLAN_READY' and type(data['selected']) is not dict:
        raise InputError('schema', 'a PLAN_READY selection must name its selected binding')
    return decided_at, digests


def _same(first, second) -> bool:
    """Exact JSON equality: true is not 1 and 1 is not 1.0."""
    return json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def _drift(digests: dict, request_path, evidence_path, home) -> list[str]:
    current = {'policy': load_policy(policy_path(home))['sha256'],
               'request': _private_digest(request_path),
               'capabilities': _private_digest(evidence_path)}
    return [f'{key}-drift' for key in ('policy', 'request', 'capabilities')
            if current[key] != digests[key]]


def _evaluation_reasons(considered) -> dict | None:
    """{binding id: its sorted evaluation reasons} of a considered list, or None when the
    value (a retained one is not shape-validated) is not such a list."""
    if type(considered) is not list:
        return None
    found = {}
    for item in considered:
        if type(item) is not dict:
            return None
        binding_id, reasons = item.get('binding'), item.get('reasons')
        if (type(binding_id) is not str or type(reasons) is not list
                or any(type(reason) is not str for reason in reasons)):
            return None
        found[binding_id] = sorted(reason for reason in reasons
                                   if reason.startswith('evaluation-'))
    return found


def _evaluation_drift(current: dict, retained: dict) -> bool:
    """True when a differing selected binding is explained by evaluation state rather than
    known to be a record the inputs never produced.

    Either the recomputation now rejects the retained selected binding on its evaluation, or
    the retained and recomputed considered lists disagree on the evaluation reasons of some
    binding (for example an earlier binding recorded as evaluation-unavailable whose pinned
    artifact is readable again). No recorded digest binds the evaluation artifacts as they
    were at selection time, so that history cannot be reproduced or disproved here."""
    selected_id = retained['selected'].get('binding')
    now = _evaluation_reasons(current['considered'])
    if any(binding_id == selected_id and reasons for binding_id, reasons in now.items()):
        return True
    before = _evaluation_reasons(retained['considered'])
    if before is None:
        return False
    return any(before.get(binding_id, []) != now.get(binding_id, [])
               for binding_id in {*before, *now})


def _usable(value) -> bool:
    return type(value) is str and MODEL_ID.fullmatch(value) is not None


def _claude_identity(events: list) -> tuple[set, set | None, bool]:
    """(models named on assistant messages, terminal modelUsage models or None when no result
    event carries modelUsage, whether every identity field was a usable identifier).

    Only structured fields are read: assistant ``message.model`` and the keys of the result
    event's ``modelUsage``. Message text, usage figures and cost are never interpreted."""
    authored, usage, usable = set(), None, True
    for event in events:
        kind = event.get('type')
        if kind == 'assistant':
            message = event.get('message')
            model = message.get('model') if type(message) is dict else None
            if _usable(model):
                authored.add(model)
            else:
                usable = False
        elif kind == 'result' and 'modelUsage' in event:
            entries = event['modelUsage']
            if type(entries) is not dict:
                usable = False
                continue
            usage = set() if usage is None else usage
            for model in entries:
                if _usable(model):
                    usage.add(model)
                else:
                    usable = False
    return authored, usage, usable


def _strict_events(raw: bytes) -> list | None:
    """Every non-empty JSONL line as a strictly parsed object, or None when any line is not
    one. Strict means UTF-8 JSON with no repeated key and no non-finite number: a repeated
    key makes a field ambiguous, so such a stream names no model at all."""
    events = []
    for line in raw.split(b'\n'):
        if not line.strip():
            continue
        try:
            event = inputs._parse_json(line, 'provider stream line')
        except InputError:
            return None
        if type(event) is not dict:
            return None
        events.append(event)
    return events


def _stream_identity(provider: str, raw: bytes, parsed) -> tuple[dict, list[str]]:
    """(model identity fields of one native stream, reasons that identity is incomplete).

    The stream is strictly re-parsed first: the lifecycle parser that produced ``parsed``
    tolerates repeated keys, so none of its model fields is trusted until every line is an
    unambiguous object. A malformed stream yields no identity and one stable reason.

    The configured model (the init event) and the executed models (assistant messages) are
    kept apart. ``model`` is set only when exactly one usable identifier authored every
    assistant message; a configured model alone never establishes what was served. No
    served-model field is read from a Codex stream, so its model stays unknown."""
    events = _strict_events(raw)
    if events is None:
        unknown = {'model': None, 'configured_model': None, 'executed_models': [],
                   'usage_models': None}
        return unknown, ['stream-identity-malformed']
    configured = parsed.observed_model if _usable(parsed.observed_model) else None
    authored, usage, usable = set(), None, True
    if provider == 'claude':
        authored, usage, usable = _claude_identity(events)
    problems = []
    if not usable:
        problems.append('observed-model-unrecognized')
    if authored and usage is not None and usage != authored:
        problems.append('observed-model-usage-differs')
    if authored and configured is not None and authored != {configured}:
        problems.append('configured-model-differs')
    served = next(iter(authored)) if usable and len(authored) == 1 else None
    identity = {'model': served, 'configured_model': configured,
                'executed_models': sorted(authored),
                'usage_models': None if usage is None else sorted(usage)}
    return identity, problems


def _observe(provider: str, surface: str, selection_sha: str, stream_path,
             observation_path) -> tuple[dict, list[str]]:
    """(observed metadata, reasons it is incomplete). Null stays null: unknown is not a match.

    Both sources are caller-trusted retained artifacts (see LIMITATIONS): nothing here proves
    that a stream or observation came from the planned invocation."""
    observed = {'source': None, 'provider': provider, 'model': None, 'configured_model': None,
                'executed_models': [], 'usage_models': None, 'effort': None,
                'terminal': 'unknown', 'stream_category': None, 'stream_reasons': []}
    if (stream_path is None) == (observation_path is None):
        return observed, ['observation-missing']
    if stream_path is not None:
        try:
            raw = _read_artifact(stream_path, 'provider stream', MAX_STREAM_BYTES)
        except InputError:
            return observed, ['stream-unreadable']
        providers = _load_sibling('sdlc_model_policy_providers', 'controller_providers.py')
        parsed = providers.parse_stream(provider, raw)
        identity, problems = _stream_identity(provider, raw, parsed)
        observed.update(identity, source='native-stream',
                        terminal=STREAM_TERMINALS.get(parsed.category, 'failed'),
                        stream_category=parsed.category, stream_reasons=list(parsed.reasons))
        return observed, problems
    try:
        raw = _read_artifact(observation_path, 'observation', MAX_INPUT_BYTES)
        data = validate_observation(inputs._parse_json(raw, 'observation'))
    except InputError:
        return observed, ['observation-invalid']
    reasons = []
    if data['selection_sha256'] != selection_sha:
        reasons.append('observation-not-bound')
    if (data['provider'], data['surface']) != (provider, surface):
        reasons.append('observation-surface-mismatch')
    model = data['observed_model']
    observed.update(source='host-observation', provider=data['provider'], model=model,
                    executed_models=[] if model is None else [model],
                    effort=data['observed_effort'], terminal=data['terminal'])
    return observed, reasons


def _compare(requested: dict, observed: dict) -> tuple[list[str], list[str]]:
    """(failures, gaps) between the requested model/effort and what was observed."""
    failures, gaps = [], []
    if observed['terminal'] != 'success':
        gaps.append('terminal-not-success')
    executed = observed['executed_models']
    if any(model != requested['model'] for model in executed):
        failures.append('observed-model-mixed' if requested['model'] in executed
                        else 'observed-model-mismatch')
    elif observed['model'] is None:
        gaps.append('observed-model-unknown')
    if requested['effort'] is not None:
        if observed['effort'] is None:
            gaps.append('observed-effort-unknown')
        elif observed['effort'] != requested['effort']:
            failures.append('observed-effort-mismatch')
    return failures, gaps


def verify(selection_path, request_path, evidence_path=None, *, stream_path=None,
           observation_path=None, home=None, now=None) -> dict:
    """Check one run against its retained selection. PASS only when the whole retained record
    reproduces from unchanged inputs and the observed model (and requested effort) match with
    a successful terminal; a known mismatch, including a retained record whose derived fields
    differ from the recomputation, is FAIL; anything unproven is INCOMPLETE."""
    now = now or _now()
    record = {'schema': RUN_CHECK_SCHEMA, 'checked_at': _stamp(now), 'outcome': 'INCOMPLETE',
              'reasons': [], 'detail': None, 'selection_sha256': None,
              'selection_decision': None, 'binding': None, 'requested': None,
              'fallback_used': None, 'observed': None, 'limitations': list(LIMITATIONS)}
    try:
        raw = _read_artifact(selection_path, 'selection', MAX_SELECTION_BYTES)
        record['selection_sha256'] = _sha256(raw)
        retained = inputs._parse_json(raw, 'selection')
        decided_at, digests = _retained_selection(retained)
    except InputError as err:
        return dict(record, reasons=['selection-invalid'], detail=str(err))
    decision, selected = retained['decision'], retained['selected']
    record['selection_decision'] = decision
    if decision != 'PLAN_READY':
        return dict(record, reasons=['selection-not-plan-ready'])
    if decided_at > now + inputs.CLOCK_SKEW:
        return dict(record, reasons=['selection-time-future'])
    drift = _drift(digests, request_path, evidence_path, home)
    if drift:
        return dict(record, reasons=drift)
    current = select(request_path, evidence_path, home=home, now=decided_at)
    if not _same(current['selected'], selected):
        if _evaluation_drift(current, retained):
            return dict(record, reasons=['evaluation-drift'])
        if current['decision'] != 'PLAN_READY':
            return dict(record, reasons=['selection-not-reproducible', *current['reasons']])
        return dict(record, outcome='FAIL', reasons=['selection-record-mismatch'])
    altered = [key for key in SELECTION_DERIVED if not _same(retained[key], current[key])]
    if altered:
        return dict(record, outcome='FAIL', reasons=['selection-record-mismatch'],
                    detail='retained selection differs from its recomputation in: '
                           + ', '.join(altered))
    if not _same(retained['considered'], current['considered']):
        # Depends on evaluation artifacts of skipped bindings, which no recorded digest binds:
        # an artifact change and an altered record cannot be told apart here.
        return dict(record, reasons=['selection-considered-not-reproducible'])
    requested = {'model': selected['model'], 'effort': selected['effort']}
    record.update(binding=selected['binding'], requested=requested,
                  fallback_used=selected['fallback'])
    observed, problems = _observe(selected['provider'], current['request']['surface'],
                                  record['selection_sha256'], stream_path, observation_path)
    failures, gaps = _compare(requested, observed)
    gaps = problems + gaps
    outcome = 'FAIL' if failures else 'INCOMPLETE' if gaps else 'PASS'
    return dict(record, observed=observed, outcome=outcome, reasons=failures + gaps)


# ---- CLI ----------------------------------------------------------------------------

def _path(value):
    return None if value is None else os.path.abspath(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='model_policy.py', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', allow_abbrev=False,
                        help='summarize the owner policy, binding evaluations and routes')
    chooser = commands.add_parser('select', allow_abbrev=False,
                                  help='plan a model and effort for one coordinator request')
    chooser.add_argument('--request', required=True, help='coordinator request JSON (mode 0600)')
    chooser.add_argument('--capabilities', help='host capability evidence JSON (mode 0600)')
    checker = commands.add_parser('verify', allow_abbrev=False,
                                  help='check a run against its retained selection')
    checker.add_argument('--selection', required=True, help='retained select stdout')
    checker.add_argument('--request', required=True, help='the same coordinator request')
    checker.add_argument('--capabilities', help='the same host capability evidence')
    source = checker.add_mutually_exclusive_group(required=True)
    source.add_argument('--stream', help='native provider JSONL event log of the run')
    source.add_argument('--observation', help='host observation JSON of the run')
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == 'status':
        record = status()
        code = EXIT['INCOMPLETE'] if record['policy']['state'] == 'invalid' else 0
    elif args.command == 'select':
        record = select(_path(args.request), _path(args.capabilities))
        code = EXIT[record['decision']]
    else:
        record = verify(_path(args.selection), _path(args.request), _path(args.capabilities),
                        stream_path=_path(args.stream), observation_path=_path(args.observation))
        code = EXIT[record['outcome']]
    print(json.dumps(record, indent=2, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
