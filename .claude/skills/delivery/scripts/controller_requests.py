#!/usr/bin/env python3
"""Private durable request inbox shared by the operator CLI and the controller engine.

The CLI never takes the repository flock to change controller work: it writes one
immutable request and returns. Only a controller holding a live ControllerLock lease
consumes a request: it re-validates it against the CURRENT policy and context, admits a
plan through Ledger.submit (or hands an explicit profile refresh to an engine callback)
and only after that durable step writes an immutable acknowledgement. This is an inbox,
not a second task queue or scheduler.

Layout: <state>/requests/<id>.json and <id>.ack.json, owner-only 0600 files in an
owner-only 0700 directory, each written completely, fsynced, published by exclusive hard
link and followed by a directory fsync. Nothing is overwritten or deleted. Records are
owner declarations guarded by private-file checks: not signatures and not an OS sandbox.

Statuses: enqueue returns queued | already_queued. A request is then pending (not
admitted), held (controller in a context hold), admitted (durably recorded by
Ledger.submit; never started, executed or completed), observed (refresh handed to the
engine), incomplete (stale context; the owner resubmits explicitly), refused, invalid
(unreadable or unsafe request) or ack_invalid (unreadable acknowledgement; never retried).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import stat
import time
import uuid

from controller_inputs import (CREDENTIAL_FORM, CREDENTIAL_SHAPE, DIGEST, PROVIDERS, SAFE_ID,
                               InputError, canonical_digest, canonical_json, validate_authority,
                               validate_plan)
from controller_ledger import LedgerError

REQUESTS_DIR = 'requests'
ACTIONS = ('submit', 'refresh_profile')
ACK_OUTCOMES = ('admitted', 'observed', 'incomplete', 'refused')
MAX_REQUEST_BYTES = 3 << 20
MAX_ACK_BYTES = 8192
MAX_EPOCH = 253402300799
REQUEST_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
CODE = re.compile(r'[a-z][a-z0-9_]{0,47}')
STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
REQUEST_KEYS = {'version', 'id', 'action', 'context', 'payload'}
PAYLOAD_KEYS = {'submit': {'plan', 'plan_digest', 'authority'},
                'refresh_profile': {'profile_id', 'provider', 'actor', 'requested_at'}}
ACK_KEYS = {'version', 'request_id', 'request_sha256', 'outcome', 'code', 'result', 'fence',
            'acked_at'}
_REFUSED = frozenset({'plan_invalid', 'authority_mismatch', 'authority_invalid',
                      'effect_unauthorized', 'plan_changed', 'task_ids'})
_LEFT = {'control_stopped': 'pending', 'context_hold': 'held', 'identity_changed': 'held'}
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)


class RequestError(Exception):
    """Refusal with a fixed ``code``; messages never echo request content."""

    def __init__(self, code, message):
        super().__init__(f'{code}: {message}')
        self.code = code


@dataclass(frozen=True)
class RefreshRequest:
    """Typed payload handed to the engine's ``on_refresh`` callback. It asserts nothing
    about authentication; the engine records it as an operator refresh observation."""
    request_id: str
    profile_id: str
    provider: str
    actor: str
    requested_at: int


# ---- encoding and validation ----------------------------------------------------

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _encode(record):
    try:
        return (canonical_json(record) + '\n').encode('utf-8')
    except InputError as err:
        raise RequestError('schema', 'record is not canonical JSON') from err


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result

    def finite(text):
        number = float(text)
        if not math.isfinite(number):
            raise ValueError('non-finite number')
        return number

    def constant(_name):
        raise ValueError('non-standard constant')

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_float=finite,
                          parse_constant=constant)
    except (ValueError, RecursionError) as err:
        raise RequestError('corrupt', 'record is not strict UTF-8 JSON') from err


def _decode(data):
    record = _strict_json(data)
    if _encode(record) != data:
        raise RequestError('corrupt', 'record is not complete canonical JSON')
    return record


def _is_digest(value):
    return type(value) is str and DIGEST.fullmatch(value) is not None


def check_actor(value):
    """Short printable owner text; refused (never echoed) when it looks like a credential."""
    if type(value) is not str or not value.strip() or len(value) > 200 or not value.isprintable():
        raise RequestError('schema', 'actor must be short printable text')
    if CREDENTIAL_FORM.search(value) or CREDENTIAL_SHAPE.search(value):
        raise RequestError('credential', 'actor appears to carry a credential; refused')
    return value


def _check_context(context):
    identity = context.get('identity') if type(context) is dict else None
    if not (type(context) is dict and set(context) == {'epoch', 'policy_digest', 'identity'}
            and type(context['epoch']) is int and 1 <= context['epoch'] <= 1 << 62
            and _is_digest(context['policy_digest']) and type(identity) is dict
            and set(identity) == {'runtime', 'rules'} and all(map(_is_digest, identity.values()))):
        raise RequestError('schema', 'context must be {epoch, policy_digest, identity}')


def _check_payload(action, payload):
    if type(payload) is not dict or set(payload) != PAYLOAD_KEYS[action]:
        raise RequestError('schema', f'{action} payload has missing or unknown fields')
    if action == 'submit':
        plan, authority = payload['plan'], payload['authority']
        if not (type(plan) is dict and type(authority) is dict and _is_digest(payload['plan_digest'])
                and canonical_digest(plan) == payload['plan_digest']
                and authority.get('plan_digest') == payload['plan_digest']):
            raise RequestError('schema', 'submit needs a plan, its digest and an authority bound to it')
        return
    when = payload['requested_at']
    if not (type(payload['profile_id']) is str and SAFE_ID.fullmatch(payload['profile_id'])
            and payload['provider'] in PROVIDERS and type(when) is int and 0 < when <= MAX_EPOCH):
        raise RequestError('schema', 'refresh_profile needs a profile id, provider and epoch time')
    check_actor(payload['actor'])


def _check_request(record):
    if type(record) is not dict or set(record) != REQUEST_KEYS:
        raise RequestError('schema', 'request has missing or unknown fields')
    if type(record['version']) is not int or record['version'] != 1:
        raise RequestError('schema', 'request version must be 1')
    if type(record['action']) is not str or record['action'] not in ACTIONS:
        raise RequestError('unknown_action', 'only submit and refresh_profile requests exist')
    if type(record['id']) is not str or not REQUEST_ID.fullmatch(record['id']):
        raise RequestError('schema', 'request id must be 1-64 letters, digits, "_" or "-"')
    _check_context(record['context'])
    _check_payload(record['action'], record['payload'])
    return record


def _check_ack(record):
    if not (type(record) is dict and set(record) == ACK_KEYS and type(record['version']) is int
            and record['version'] == 1 and type(record['request_id']) is str
            and REQUEST_ID.fullmatch(record['request_id']) and _is_digest(record['request_sha256'])
            and record['outcome'] in ACK_OUTCOMES and type(record['code']) is str
            and CODE.fullmatch(record['code']) and type(record['result']) is dict
            and (record['fence'] is None or (type(record['fence']) is int and record['fence'] >= 1))
            and type(record['acked_at']) is str and STAMP.fullmatch(record['acked_at'])):
        raise RequestError('schema', 'acknowledgement does not match its fixed schema')
    return record


# ---- builders -------------------------------------------------------------------

def current_context(ledger):
    """The context identity a request is bound to: current epoch, policy and identity."""
    return {'epoch': ledger.epoch, 'policy_digest': ledger.policy_digest,
            'identity': dict(ledger.identity)}


def _new(action, context, payload, request_id):
    body = {'version': 1, 'action': action, 'context': context, 'payload': payload}
    if request_id is None:
        request_id = f"{action.split('_')[0]}-{_sha(_encode(body))[:32]}"
    return _check_request({**body, 'id': request_id})


def submit_request(plan, authority, context, request_id=None):
    """Request to admit ``plan``; the caller has validated plan and authority against the
    policy of ``context`` (for example with controller_inputs.read_plan/read_authority).
    Without ``request_id`` the id derives from the content, so an identical submission
    under the same context is the same request."""
    try:
        plan_digest = canonical_digest(plan)
    except InputError as err:
        raise RequestError('schema', 'plan is not canonical JSON') from err
    return _new('submit', context, {'plan': plan, 'plan_digest': plan_digest,
                                    'authority': authority}, request_id)


def refresh_request(profile_id, provider, actor, context, requested_at=None, request_id=None):
    """Request to record an explicit operator refresh of one profile. It claims no renewed
    or verified authentication; availability stays unknown until a real task probes it."""
    when = int(time.time()) if requested_at is None else requested_at
    return _new('refresh_profile', context, {'profile_id': profile_id, 'provider': provider,
                                             'actor': actor, 'requested_at': when}, request_id)


# ---- private files --------------------------------------------------------------

def _private_dir(info):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and not stat.S_IMODE(info.st_mode) & 0o077)


def _state(state_dir):
    path = os.fspath(state_dir)
    if ('\0' in path or not os.path.isabs(path) or os.path.normpath(path) != path
            or os.path.realpath(path) != path):
        raise RequestError('path', 'state directory must be an absolute symlink-free path')
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise RequestError('missing', 'no controller state directory') from None
    if not _private_dir(info):
        raise RequestError('insecure', 'state directory is not a private owner directory')
    return path


def _fsync_path(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _open_dir(state_dir, create):
    """Descriptor of the private requests directory, or None when absent and not created."""
    state = _state(state_dir)
    path = os.path.join(state, REQUESTS_DIR)
    if create:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        else:
            _fsync_path(state)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    except FileNotFoundError:
        if create:
            raise RequestError('missing', 'requests directory vanished') from None
        return None
    except OSError as err:
        raise RequestError('insecure', 'requests directory is not a private directory') from err
    if not _private_dir(os.fstat(fd)):
        os.close(fd)
        raise RequestError('insecure', 'requests directory is not a private owner directory')
    return fd


def _publish(dfd, name, data):
    """Write ``data`` completely to a private temp file, fsync it, publish it as ``name``
    by exclusive hard link and fsync the directory. False when ``name`` already exists."""
    tmp = f'.tmp-{uuid.uuid4().hex}'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        except FileExistsError:
            return False
    finally:
        os.unlink(tmp, dir_fd=dfd)
    os.fsync(dfd)
    return True


def _read(dfd, name, limit):
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=dfd)
    except FileNotFoundError:
        raise RequestError('missing', 'record is missing') from None
    except OSError as err:
        raise RequestError('insecure', 'record is not a private regular file') from err
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise RequestError('insecure', 'record is not a private regular file')
        if info.st_size > limit:
            raise RequestError('too_large', 'record exceeds its size limit')
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(fd, limit + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        os.close(fd)
    if size > limit:
        raise RequestError('too_large', 'record exceeds its size limit')
    return b''.join(chunks)


def _ids(dfd):
    """Request ids with a request or acknowledgement file, oldest first (read-only)."""
    found = {}
    for name in os.listdir(dfd):
        if name.endswith('.ack.json'):
            stem = name[:-len('.ack.json')]
        elif name.endswith('.json'):
            stem = name[:-len('.json')]
        else:
            continue
        if not REQUEST_ID.fullmatch(stem):
            continue
        try:
            when = os.stat(name, dir_fd=dfd, follow_symlinks=False).st_mtime_ns
        except FileNotFoundError:
            continue
        found[stem] = min(found.get(stem, when), when)
    return sorted(found, key=lambda rid: (found[rid], rid))


def _summary(record):
    payload = record['payload']
    if record['action'] == 'submit':
        plan_id = payload['plan'].get('id')
        return {'plan_id': plan_id if type(plan_id) is str else None,
                'plan_digest': payload['plan_digest']}
    return {key: payload[key] for key in ('profile_id', 'provider', 'requested_at')}


def _entry(dfd, request_id):
    """(view, record); record is returned only while the request is pending."""
    view = {'id': request_id, 'action': None, 'status': 'invalid', 'code': None,
            'sha256': None, 'context': None, 'summary': None, 'ack': None}
    try:
        data = _read(dfd, request_id + '.json', MAX_REQUEST_BYTES)
        view['sha256'] = _sha(data)
        record = _check_request(_decode(data))
        if record['id'] != request_id:
            raise RequestError('corrupt', 'request id does not match its file name')
    except RequestError as err:
        view['code'] = err.code
        return view, None
    view.update(action=record['action'], context=record['context'], summary=_summary(record))
    try:
        ack = _check_ack(_decode(_read(dfd, request_id + '.ack.json', MAX_ACK_BYTES)))
    except RequestError as err:
        if err.code == 'missing':
            view['status'] = 'pending'
            return view, record
        view.update(status='ack_invalid', code=err.code)
        return view, None
    if (ack['request_id'], ack['request_sha256']) != (request_id, view['sha256']):
        view.update(status='ack_invalid', code='ack_mismatch')
        return view, None
    view.update(status=ack['outcome'], code=ack['code'], ack=ack)
    return view, None


def _ack(dfd, request_id, request_sha256, outcome, code, result, fence):
    record = _check_ack({'version': 1, 'request_id': request_id, 'request_sha256': request_sha256,
                         'outcome': outcome, 'code': code, 'result': result, 'fence': fence,
                         'acked_at': _now()})
    data = _encode(record)
    if len(data) > MAX_ACK_BYTES:
        raise RequestError('too_large', 'acknowledgement exceeds its size limit')
    if _sha(_read(dfd, request_id + '.json', MAX_REQUEST_BYTES)) != request_sha256:
        raise RequestError('ack_mismatch', 'acknowledgement does not match the request content')
    name = request_id + '.ack.json'
    if _publish(dfd, name, data):
        return record
    existing = _check_ack(_decode(_read(dfd, name, MAX_ACK_BYTES)))
    fixed = ('acked_at', 'fence')
    if ({k: v for k, v in existing.items() if k not in fixed}
            != {k: v for k, v in record.items() if k not in fixed}):
        raise RequestError('ack_conflict', 'a different acknowledgement exists; nothing was overwritten')
    return existing


# ---- public API -----------------------------------------------------------------

def enqueue(state_dir, record):
    """Publish one immutable request. Returns {status: queued | already_queued, id, sha256,
    ack}. Identical bytes under an existing id are recognized (with any acknowledgement);
    other content under that id is refused as ``conflict`` and nothing is written."""
    data = _encode(_check_request(record))
    if len(data) > MAX_REQUEST_BYTES:
        raise RequestError('too_large', 'request exceeds its size limit')
    dfd = _open_dir(state_dir, create=True)
    try:
        if _publish(dfd, record['id'] + '.json', data):
            return {'status': 'queued', 'id': record['id'], 'sha256': _sha(data), 'ack': None}
        view, _ = _entry(dfd, record['id'])
    finally:
        os.close(dfd)
    if view['sha256'] != _sha(data) or view['status'] in ('invalid', 'ack_invalid'):
        raise RequestError('conflict', 'another request already uses this id; nothing was written')
    return {'status': 'already_queued', 'id': record['id'], 'sha256': view['sha256'],
            'ack': view['ack']}


def list_requests(state_dir):
    """Read-only inventory, oldest first. Creates, fsyncs and writes nothing."""
    dfd = _open_dir(state_dir, create=False)
    if dfd is None:
        return []
    try:
        return [_entry(dfd, request_id)[0] for request_id in _ids(dfd)]
    finally:
        os.close(dfd)


def load_request(state_dir, request_id):
    """(record, sha256) of one valid request, acknowledged or not; read-only."""
    if type(request_id) is not str or not REQUEST_ID.fullmatch(request_id):
        raise RequestError('schema', 'invalid request id')
    dfd = _open_dir(state_dir, create=False)
    if dfd is None:
        raise RequestError('missing', 'no requests directory')
    try:
        data = _read(dfd, request_id + '.json', MAX_REQUEST_BYTES)
    finally:
        os.close(dfd)
    record = _check_request(_decode(data))
    if record['id'] != request_id:
        raise RequestError('corrupt', 'request id does not match its file name')
    return record, _sha(data)


def acknowledge(state_dir, request_id, request_sha256, outcome, code, result=None, fence=None):
    """Write the immutable acknowledgement of one request, tied to its exact id and content
    hash. An equal acknowledgement is recognized; a different one is refused."""
    if type(request_id) is not str or not REQUEST_ID.fullmatch(request_id):
        raise RequestError('schema', 'invalid request id')
    dfd = _open_dir(state_dir, create=False)
    if dfd is None:
        raise RequestError('missing', 'no requests directory')
    try:
        return _ack(dfd, request_id, request_sha256, outcome, code,
                    {} if result is None else result, fence)
    finally:
        os.close(dfd)


def consume_pending(ledger, identity, on_refresh=None, limit=64):
    """Engine-side consumer. ``ledger`` comes from ControllerLock (live lease) and
    ``identity`` is the runtime/rules identity the engine presented to it.

    Every pending request is re-validated against the current policy and context. Under
    STOP or a context hold nothing is acknowledged. A request bound to another context
    is acknowledged ``incomplete`` and never executed. A plan is acknowledged only after
    Ledger.submit committed it, so a crash before the acknowledgement reconciles on the
    next pass through the ledger's idempotent plan digest. Without ``on_refresh`` a
    refresh stays pending. Returns [{id, action, status, code}] for pending requests."""
    if getattr(ledger, 'fence', None) is None:
        raise RequestError('lease_required', 'only a controller-held ledger consumes requests')
    dfd = _open_dir(ledger.state_dir, create=False)
    if dfd is None:
        return []
    results = []
    try:
        for request_id in _ids(dfd):
            view, record = _entry(dfd, request_id)
            if record is None:
                continue
            if len(results) >= limit:
                break
            results.append(_consume_one(ledger, identity, dfd, record, view['sha256'], on_refresh))
    finally:
        os.close(dfd)
    return results


def _consume_one(ledger, identity, dfd, record, request_sha256, on_refresh):
    def leave(status, code):
        return {'id': record['id'], 'action': record['action'], 'status': status, 'code': code}

    def ack(outcome, code, result=None):
        _ack(dfd, record['id'], request_sha256, outcome, code, result or {}, ledger.fence)
        return leave(outcome, code)

    if identity != ledger.identity:
        return leave('held', 'context_hold')
    if ledger.control() == 'stopped':
        return leave('pending', 'control_stopped')
    if record['context'] != current_context(ledger):
        return ack('incomplete', 'context_stale', {'epoch': ledger.epoch})
    if record['action'] == 'refresh_profile':
        return _refresh(ledger, record, on_refresh, ack, leave)
    return _admit(ledger, identity, record['payload'], ack, leave)


def _refresh(ledger, record, on_refresh, ack, leave):
    payload = record['payload']
    if not any((p['id'], p['provider']) == (payload['profile_id'], payload['provider'])
               for p in ledger.policy['profiles']):
        return ack('refused', 'unknown_profile')
    if on_refresh is None:
        return leave('pending', 'no_consumer')
    on_refresh(RefreshRequest(record['id'], payload['profile_id'], payload['provider'],
                              payload['actor'], payload['requested_at']))
    return ack('observed', 'operator_refresh', {'profile_id': payload['profile_id']})


def _admit(ledger, identity, payload, ack, leave):
    try:
        plan = validate_plan(payload['plan'], ledger.policy)
    except InputError:
        return ack('refused', 'plan_invalid')
    if canonical_digest(plan) != payload['plan_digest']:
        return ack('refused', 'plan_digest')
    try:
        authority = validate_authority(payload['authority'], ledger.policy, plan)
    except InputError as err:
        return ack('refused', 'authority_mismatch' if err.code == 'digest' else 'authority_invalid')
    prior = next((row for row in ledger.plans() if row['id'] == plan['id']), None)
    if prior is not None and prior['stale']:
        return ack('refused', 'readmit_required')
    try:
        plan_digest = ledger.submit(plan, authority, identity)
    except LedgerError as err:
        if err.code in _LEFT:
            return leave(_LEFT[err.code], err.code)
        if err.code in _REFUSED:
            return ack('refused', err.code)
        raise
    return ack('admitted', 'admitted', {
        'plan_id': plan['id'], 'plan_digest': plan_digest, 'epoch': ledger.epoch,
        'reconciled': prior is not None and prior['digest'] == plan_digest})
