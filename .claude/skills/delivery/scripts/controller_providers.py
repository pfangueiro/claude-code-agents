#!/usr/bin/env python3
"""Native provider adapter for the persistent delivery controller (stdlib only).

Provider-specific logic only: the native launch description, a bounded read-only CLI
probe, closed JSONL stream classification, review-verdict extraction and the provider
outcome. Every process runs through the shared owned lifecycle in controller_process.py
(prepare / spawn / release / poll / finalize); this module has no bootstrap, supervisor,
signalling, journal or process-identity code of its own. Nothing here reads policy,
ledgers, credentials or provider configuration files. The native CLI's configured model,
effort, permissions, authentication, billing, hooks and HOME are inherited unchanged.

Launch description
    build_launch(Invocation) -> LaunchSpec(argv, cwd, selector, stdin)
        Claude: <exe> -p --output-format stream-json --verbose   (prompt on stdin)
        Codex:  <exe> exec --json -C <cwd> -                    (prompt on stdin)
        No model, effort, permission, approval, sandbox, bypass, resume, trust or
        fallback flag is ever emitted. Every launch is a new native session.

Attempt layout (one directory per fresh attempt id, never reused)
    <root>/<id>/provider.json      immutable invocation association, written first
    <root>/<id>/tmp/               per-attempt TMPDIR, outside the work tree and repository
    <root>/<id>/process/<id>/      the controller_process attempt (intent, logs, lifecycle)

Engine-facing wrappers (all refusals are ProcessError; ProviderError subclasses it)
    attempt = create_attempt(root, invocation, timeout_seconds=1800)  -> Path
    pending = spawn(attempt)                 # bootstrap held; nothing launched yet
    ledger.record_launch(pending.identity)   # durable first, then authorize release:
    owned = pending.release()                # or pending.abort()
    owned.poll()                             # controller_process.Recovery, short
    settled = settle(owned, timeout_seconds + grace + linger + margin, drain_seconds)
    if settled.settled:                      # exited / not-launched / lost only
        outcome = finalize(attempt, owned)   # lifecycle written once, then assess()
    # else unresolved (live past the drain, corrupt, or bootstrap gone without terminal
    # evidence): keep the attempt as evidence; never finalize it as clean or retry it blindly.
    After a restart (no association needed, so a damaged one never blocks a stop):
    recover(attempt) / attach(attempt) / request_stop(attempt) / finalize(attempt)
    assess(attempt) -> ProviderOutcome       # read-only and repeatable
    process_attempt(attempt) -> Path         # for controller_process.read_status

Probe
    probe_cli(provider, executable, attempts_root, probe_id, ...) -> CliProbe
        Runs only `--version` and the help command, each as its own owned attempt
        under <attempts_root>/<probe_id>/. It is not a provider turn and never reports
        authentication or capacity.

Stream and review evidence
    parse_stream(provider, data) -> ParsedStream      closed classification of JSONL
    extract_review_verdict(structured_output, final_text) -> (verdict | None, problem)
"""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PROCESS_MODULE_PATH = Path(__file__).resolve().with_name('controller_process.py')
PROCESS_MODULE_NAME = 'sdlc_delivery_controller_process'


def _load_process_module():
    """Load the sibling shared lifecycle module by exact path, once per interpreter.

    Loading by path (not sys.path) means no other controller_process.py on the import path
    can stand in for it. An already-loaded instance of the same file is reused, so callers
    share one ProcessError / CommandSpec class.
    """
    for name in (PROCESS_MODULE_NAME, 'controller_process'):
        loaded = sys.modules.get(name)
        location = getattr(loaded, '__file__', None)
        if location and Path(location).resolve() == PROCESS_MODULE_PATH:
            return loaded
    spec = importlib.util.spec_from_file_location(PROCESS_MODULE_NAME, PROCESS_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError('controller_process.py is not loadable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[PROCESS_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(PROCESS_MODULE_NAME, None)
        raise
    return module


controller_process = _load_process_module()
ProcessError = controller_process.ProcessError

PROVIDERS = ('claude', 'codex')
CONFIG_SELECTORS = {'claude': 'CLAUDE_CONFIG_DIR', 'codex': 'CODEX_HOME'}
# Each env selector names the same directory as one declared binding (and must bind it identically).
SELECTOR_BINDINGS = {'TMPDIR': 'tmp', 'CLAUDE_CONFIG_DIR': 'config', 'CODEX_HOME': 'config'}
# Native interfaces were checked at these versions; newer versions are reported, not assumed.
CHECKED_VERSIONS = {'claude': (2, 1, 323), 'codex': (0, 169, 0)}
HELP_ARGS = {'claude': ('--help',), 'codex': ('exec', '--help')}
REQUIRED_HELP_FLAGS = {'claude': ('--print', '--output-format', '--verbose'),
                       'codex': ('--json', '--cd')}

CATEGORIES = ('success', 'permission_denied', 'rate_limited', 'auth_required', 'unavailable',
              'interrupted', 'incomplete', 'failed')
ERROR_CATEGORIES = {
    'authentication_failed': 'auth_required',
    'oauth_org_not_allowed': 'auth_required',
    'rate_limit': 'rate_limited',
    'overloaded': 'unavailable',
    'server_error': 'unavailable',
    'billing_error': 'unavailable',
    'account_on_hold': 'unavailable',
}
# Lifecycle terminations that decide the category regardless of what the stream says.
TERMINATION_CATEGORIES = {'stopped': 'interrupted', 'timeout': 'interrupted', 'lost': 'interrupted',
                          'not-launched': 'interrupted', 'launch-failed': 'unavailable'}

SCHEMA_ASSOCIATION = 'sdlc-controller/provider-association/v2'
ASSOCIATION_FILE = 'provider.json'
ASSOCIATION_KEYS = frozenset({'schema', 'attemptId', 'provider', 'executable', 'cwd', 'configDir',
                              'prompt', 'tmpDir', 'createdAt'})
TMP_DIR = 'tmp'
PROCESS_DIR = 'process'
PROBE_WORK_DIR = 'work'

ATTEMPT_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
SHA_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
VERSION_RE = re.compile(r'(?<![\d.])\d+\.\d+\.\d+(?!\d)')
ERROR_CODE_RE = re.compile(r'^[a-z0-9_]{1,64}$')
VERDICT_OPEN_RE = re.compile(r'^```sdlc-verdict[ \t]*$', re.M)
VERDICT_BLOCK_RE = re.compile(r'^```sdlc-verdict[ \t]*\n(.*?)^```[ \t]*$', re.M | re.S)
VERDICT_KEYS = frozenset({'version', 'verdict', 'base_sha', 'result_sha', 'findings', 'gaps'})
# Documented Claude background-task lifecycle (type 'system'); 'paused' is not terminal.
TASK_SUBTYPES = frozenset({'task_started', 'task_progress', 'task_updated', 'task_notification',
                           'background_tasks_changed'})
# task_progress carries no status; these documented fields are optional but typed when present.
TASK_PROGRESS_OPTIONAL = (('description', str), ('usage', dict), ('last_tool_name', str))
TASK_TERMINAL_STATUSES = frozenset({'completed', 'failed', 'stopped', 'killed'})
# Quota is read only from this top-level Claude event; Codex quota has no verified shape here.
QUOTA_EVENT = 'rate_limit_event'
QUOTA_INFO_FIELDS = (('status', 'text'), ('resetsAt', 'epoch'), ('rateLimitType', 'text'),
                     ('overageStatus', 'text'), ('overageDisabledReason', 'text'),
                     ('isUsingOverage', 'flag'))
QUOTA_WINDOW_FIELDS = (('utilization', 'ratio'), ('resetsAt', 'epoch'), ('status', 'text'))

DEFAULT_TERM_GRACE = 5.0
DEFAULT_LINGER = 5.0
PROBE_TERM_GRACE = 2.0
PROBE_LINGER = 1.0
PROBE_SETTLE_MARGIN = 10.0
SETTLE_POLL_SECONDS = 0.1
MAX_ASSOCIATION_BYTES = 64 << 10
MAX_PROBE_OUTPUT = 1 << 20
MAX_STREAM_BYTES = 128 << 20
MAX_QUOTA_SNAPSHOTS = 64
MAX_QUOTA_WINDOWS = 16
# Larger integers are not exact as floats (10**400 overflows); they are not numeric evidence.
MAX_EXACT_INT = 2 ** 53

LIMITATIONS = (
    'process ownership, cleanup and lifecycle evidence come from controller_process and carry the '
    'limitations recorded in each lifecycle record; this module adds no supervision of its own',
    'stream classification is evidence of native execution only, never of semantic task success',
    'Codex command_execution status "declined" is a typed rejection whose cause is ambiguous (policy '
    'or an operational/setup failure); it is reported as command-declined, never as a proven '
    'permission denial; failed commands, file_change and MCP failures are not denials',
    'Codex top-level error events carry no retry flag in JSONL; they count as recovered only when '
    'exactly one turn.completed follows; free-form messages are never mapped to auth or quota',
    'quota values are observed snapshots only; no pool independence, reset or capacity is inferred',
    'only the latest 64 Claude rate_limit_event snapshots are kept (earlier ones are counted; the '
    'raw stdout log keeps every event); Codex quota events have no verified shape and are not captured',
    'background tasks are tracked only from documented Claude task events in this stream; a fresh CLI '
    'has no startup snapshot, and an empty process group does not prove remote tasks finished',
    'any valid start, progress or non-terminal update (status absent included) keeps its run live until '
    'a matching terminal or an authoritative snapshot; a terminal without run_id closes only a sole, '
    'history-free open run; a restart of a closed run or an ambiguous closure is task-run-conflict',
    'version and help probes are bounded read-only runs through the owned lifecycle; they start no '
    'provider turn and do not establish authentication, entitlement or capacity',
    'settle() waits through a live, not-proven-gone "unknown" (e.g. a release before the first '
    'journal line) but never admits it; at its deadline it requests a stop through the owned '
    'bootstrap and drains for a bounded time; anything still not finalizable is returned '
    'unresolved and is never finalized; nothing is signalled by this module',
    'the repository boundary for TMPDIR placement is the nearest ancestor of cwd containing .git',
    'provider.json and the process attempt are same-user state; they detect accidents and casual '
    'tampering, not a malicious same-user or root process',
)


class ProviderError(ProcessError):
    """Provider-level refusal with a fixed reason code; a ProcessError, so callers catch one type."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


# ---------------------------------------------------------------- launch description

@dataclass(frozen=True)
class Invocation:
    provider: str
    executable: str
    cwd: str
    prompt: str
    attempt_id: str
    config_dir: str | None = None


@dataclass(frozen=True)
class LaunchSpec:
    argv: tuple[str, ...]
    cwd: str
    selector: tuple[str, str] | None
    stdin: bytes


def _check_provider(provider) -> None:
    if provider not in PROVIDERS:
        raise ProviderError('unknown-provider')


def _check_executable(executable) -> None:
    if not isinstance(executable, str) or '\0' in executable or not os.path.isabs(executable):
        raise ProviderError('executable-not-absolute')
    if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
        raise ProviderError('executable-not-executable')


def _check_canonical_dir(value, code: str) -> None:
    if not isinstance(value, str) or '\0' in value or not os.path.isabs(value) \
            or os.path.realpath(value) != value or not os.path.isdir(value):
        raise ProviderError(code)


def _canonical_dir(value, code: str) -> str:
    try:
        path = os.fspath(value)
    except TypeError:
        raise ProviderError(code) from None
    _check_canonical_dir(path, code)
    return path


def _validate_invocation(invocation: Invocation) -> None:
    _check_provider(invocation.provider)
    _check_executable(invocation.executable)
    _check_canonical_dir(invocation.cwd, 'cwd-not-canonical')
    if invocation.config_dir is not None:
        _check_canonical_dir(invocation.config_dir, 'config-dir-not-canonical')
    if not isinstance(invocation.attempt_id, str) or not ATTEMPT_ID_RE.match(invocation.attempt_id):
        raise ProviderError('invalid-attempt-id')
    if not isinstance(invocation.prompt, str) or not invocation.prompt or '\0' in invocation.prompt:
        raise ProviderError('invalid-prompt')
    try:
        invocation.prompt.encode('utf-8')
    except UnicodeEncodeError:
        raise ProviderError('invalid-prompt') from None


def _native_argv(provider: str, executable: str, cwd: str) -> tuple[str, ...]:
    if provider == 'claude':
        return (executable, '-p', '--output-format', 'stream-json', '--verbose')
    return (executable, 'exec', '--json', '-C', cwd, '-')


def build_launch(invocation: Invocation) -> LaunchSpec:
    _validate_invocation(invocation)
    selector = None if invocation.config_dir is None \
        else (CONFIG_SELECTORS[invocation.provider], invocation.config_dir)
    return LaunchSpec(_native_argv(invocation.provider, invocation.executable, invocation.cwd),
                      invocation.cwd, selector, invocation.prompt.encode('utf-8'))


# ---------------------------------------------------------------- provider-owned files

def _fsync_dir(dir_fd: int) -> None:
    try:
        os.fsync(dir_fd)
    except OSError as err:
        # Some filesystems reject fsync on a directory; the file itself is synced.
        if err.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise


def _write_new_json(directory: Path, name: str, record: dict) -> None:
    """Create a new synced 0600 file; an existing name is never replaced. A torn write
    leaves unparsable JSON, which every reader treats as invalid (fail closed)."""
    data = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    dir_fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(errno.EIO, 'zero-length write')
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(dir_fd)
    finally:
        os.close(dir_fd)


def _read_owned(path: Path, limit: int) -> bytes:
    """Bytes of an owner-only, single-link regular file, without following a final symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise ProviderError('artifact-missing') from None
    except OSError:
        raise ProviderError('artifact-unsafe') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() \
                or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ProviderError('artifact-unsafe')
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                return b''.join(chunks)
            total += len(chunk)
            if total > limit:
                raise ProviderError('artifact-too-large')
            chunks.append(chunk)
    finally:
        os.close(fd)


def _reject_constant(_name: str):
    raise ValueError('non-finite JSON constant')


def _unique_object(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate key')
    return dict(pairs)


def _strict_json(data: bytes):
    """Parsed JSON, or None for anything malformed, duplicated or non-finite."""
    try:
        return json.loads(data.decode('utf-8'), parse_constant=_reject_constant,
                          object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None


def _verified_stdout(process_path: Path, record: dict, limit: int) -> bytes:
    """The stdout bytes the finalized lifecycle record hashed; any divergence is refused."""
    reference = record['logs']['stdout']
    if reference is None:
        return b''  # the lifecycle record already carries 'logs-missing'
    expected = process_path / controller_process.STDOUT
    if reference['path'] != str(expected):
        raise ProviderError('log-mismatch')
    if reference['size'] > limit:
        raise ProviderError('log-too-large')
    data = _read_owned(expected, limit)
    if len(data) != reference['size'] or hashlib.sha256(data).hexdigest() != reference['sha256']:
        raise ProviderError('log-mismatch')
    return data


# ---------------------------------------------------------------- attempt association

def _overlaps(first: str, second: str) -> bool:
    return os.path.commonpath([first, second]) in (first, second)


def _repository_top(cwd: str) -> str | None:
    """Nearest ancestor of cwd (inclusive) holding a .git entry, or None."""
    current = cwd
    while True:
        if os.path.lexists(os.path.join(current, '.git')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _attempt_path(attempt) -> Path:
    try:
        path = os.fspath(attempt)
    except TypeError:
        raise ProviderError('attempt-not-canonical') from None
    if not isinstance(path, str) or '\0' in path or not os.path.isabs(path) \
            or os.path.realpath(path) != path or not ATTEMPT_ID_RE.match(os.path.basename(path)):
        raise ProviderError('attempt-not-canonical')
    return Path(path)


def process_attempt(attempt) -> Path:
    """The controller_process attempt directory of a provider attempt (derived from the path only)."""
    path = _attempt_path(attempt)
    return path / PROCESS_DIR / path.name


def _association_record(invocation: Invocation, spec: LaunchSpec, attempt: Path) -> dict:
    return {'schema': SCHEMA_ASSOCIATION, 'attemptId': invocation.attempt_id,
            'provider': invocation.provider, 'executable': invocation.executable,
            'cwd': invocation.cwd, 'configDir': invocation.config_dir,
            'prompt': {'bytes': len(spec.stdin), 'sha256': hashlib.sha256(spec.stdin).hexdigest()},
            'tmpDir': str(attempt / TMP_DIR), 'createdAt': utc_now()}


def _absolute_text(value) -> bool:
    return isinstance(value, str) and '\0' not in value and os.path.isabs(value)


def _association_ok(value, attempt: Path) -> bool:
    if not isinstance(value, dict) or set(value) != ASSOCIATION_KEYS:
        return False
    prompt = value['prompt']
    return (value['schema'] == SCHEMA_ASSOCIATION and value['attemptId'] == attempt.name
            and value['provider'] in PROVIDERS and _absolute_text(value['executable'])
            and _absolute_text(value['cwd'])
            and (value['configDir'] is None or _absolute_text(value['configDir']))
            and isinstance(prompt, dict) and set(prompt) == {'bytes', 'sha256'}
            and type(prompt['bytes']) is int and prompt['bytes'] > 0
            and isinstance(prompt['sha256'], str) and SHA256_RE.match(prompt['sha256']) is not None
            and value['tmpDir'] == str(attempt / TMP_DIR) and isinstance(value['createdAt'], str))


def _load_association(attempt: Path) -> dict:
    try:
        data = _read_owned(attempt / ASSOCIATION_FILE, MAX_ASSOCIATION_BYTES)
    except ProviderError as err:
        raise ProviderError('association-missing' if err.code == 'artifact-missing'
                            else 'association-unsafe') from None
    value = _strict_json(data)
    if not _association_ok(value, attempt):
        raise ProviderError('association-invalid')
    return value


def _derived_launch(association: dict) -> tuple[tuple[str, ...], dict, dict]:
    """(argv, env selector paths, declared binding paths) implied by an association; the single
    source used both to prepare the process attempt and to verify it later. Every selector
    mirrors the declared binding SELECTOR_BINDINGS names for it."""
    provider, config = association['provider'], association['configDir']
    argv = _native_argv(provider, association['executable'], association['cwd'])
    selectors = {'TMPDIR': association['tmpDir']}
    if config is not None:
        selectors[CONFIG_SELECTORS[provider]] = config
    bindings = {SELECTOR_BINDINGS[key]: path for key, path in selectors.items()}
    return argv, selectors, bindings


def _binding_paths(bindings) -> dict | None:
    """{name: path} of helper directory bindings, each exactly {path, device, inode} with a
    text path and integer identity; None when the mapping or any entry is malformed
    (including a bare path string)."""
    if not isinstance(bindings, dict):
        return None
    paths = {}
    for name, binding in bindings.items():
        if not isinstance(binding, dict) or set(binding) != controller_process.DIR_BINDING_KEYS \
                or not isinstance(binding['path'], str) \
                or type(binding['device']) is not int or type(binding['inode']) is not int:
            return None
        paths[name] = binding['path']
    return paths


def _intent_matches(association: dict, intent) -> bool:
    """True only for exactly the associated launch. Selectors and declared bindings must be
    well-formed directory bindings whose names and paths equal the derived launch (no missing,
    extra or re-pointed entry), and each selector must bind the same directory identity as
    the declared binding it mirrors."""
    argv, selectors, bindings = _derived_launch(association)
    prompt = association['prompt']
    try:
        selected, declared = intent['environment']['selectors'], intent['bindings']
        return (intent['attemptId'] == association['attemptId'] and intent['argv'] == list(argv)
                and intent['cwd']['path'] == association['cwd']
                and intent['executable']['path'] == association['executable']
                and intent['stdin']['bytes'] == prompt['bytes']
                and intent['stdin']['sha256'] == prompt['sha256']
                and _binding_paths(selected) == selectors
                and _binding_paths(declared) == bindings
                and all(selected[key] == declared[SELECTOR_BINDINGS[key]] for key in selected))
    except (KeyError, TypeError, AttributeError):
        return False


def _bound_intent_sha(association: dict, process_path: Path) -> str:
    """sha256 of the process intent, refused unless it is exactly the associated launch."""
    try:
        data = _read_owned(process_path / controller_process.INTENT, controller_process.MAX_RECORD_BYTES)
    except ProviderError:
        raise ProviderError('intent-unreadable') from None
    if not _intent_matches(association, _strict_json(data)):
        raise ProviderError('intent-association-mismatch')
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- lifecycle wrappers

def create_attempt(attempts_root, invocation: Invocation, *, timeout_seconds: float,
                   term_grace_seconds: float = DEFAULT_TERM_GRACE,
                   linger_seconds: float = DEFAULT_LINGER) -> Path:
    """Create a NEW provider attempt: association first, then the shared prepared intent.

    A refusal after the directory exists still burns the attempt id; retry with a new one.
    """
    spec = build_launch(invocation)
    root = _canonical_dir(attempts_root, 'attempts-root-not-canonical')
    if _overlaps(root, spec.cwd):
        raise ProviderError('attempts-root-overlaps-cwd')
    repository = _repository_top(spec.cwd)
    if repository is not None and _overlaps(root, repository):
        raise ProviderError('attempts-root-inside-repository')
    attempt = Path(root, invocation.attempt_id)
    try:
        os.mkdir(attempt, 0o700)
    except FileExistsError:
        raise ProviderError('attempt-exists') from None
    association = _association_record(invocation, spec, attempt)
    try:
        for name in (TMP_DIR, PROCESS_DIR):
            os.mkdir(attempt / name, 0o700)
        _write_new_json(attempt, ASSOCIATION_FILE, association)
    except OSError as err:
        raise ProviderError('attempt-create-failed') from err
    argv, selectors, bindings = _derived_launch(association)
    command = controller_process.CommandSpec(argv, spec.cwd, spec.stdin, invocation.attempt_id, selectors)
    controller_process.prepare(attempt / PROCESS_DIR, command, timeout_seconds,
                               term_grace_seconds, linger_seconds, bindings)
    return attempt


def spawn(attempt, environment=None):
    """Spawn the held bootstrap for a verified association -> controller_process.Pending.

    The caller persists Pending.identity durably, then calls release() (or abort()).
    """
    path = _attempt_path(attempt)
    association = _load_association(path)
    process_path = path / PROCESS_DIR / path.name
    intent_sha = _bound_intent_sha(association, process_path)
    pending = controller_process.spawn(process_path, environment)
    if pending.identity['intentSha256'] != intent_sha:
        pending.abort()
        raise ProviderError('intent-association-mismatch')
    return pending


def recover(attempt):
    return controller_process.recover(process_attempt(attempt))


def attach(attempt):
    return controller_process.OwnedProcess.attach(process_attempt(attempt))


def request_stop(attempt) -> str:
    return controller_process.request_stop(process_attempt(attempt))


def finalize(attempt, handle=None) -> 'ProviderOutcome':
    """Write the single lifecycle record, then assess. The spawning controller passes its
    OwnedProcess so the bootstrap is reaped; 'already-finalized' is raised on a repeat."""
    process_path = process_attempt(attempt)
    if handle is None:
        controller_process.finalize(process_path)
    elif Path(handle.attempt) != process_path:
        raise ProviderError('handle-mismatch')
    else:
        handle.finalize()
    return assess(attempt)


@dataclass(frozen=True)
class Settlement:
    """Result of settle(). ``settled`` is True only for a finalizable state (exited,
    not-launched, lost); every other state is unresolved and must not be finalized or treated
    as clean. ``stop_status`` is None when no stop was requested, else request_stop()'s answer."""
    state: str
    reason: str | None
    identity_status: str | None
    settled: bool
    stop_status: str | None


def _settle_budget(value) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ProviderError('invalid-settle-budget')
    return float(value)


def _may_still_settle(recovery) -> bool:
    """True while the state can still move to a terminal one by itself: an active state, or
    'unknown' while the bootstrap is not proven gone (for example released before its first
    journal line was durable). This is never evidence of success."""
    if recovery.state in controller_process.ACTIVE_STATES:
        return True
    return recovery.state == 'unknown' and recovery.identity_status != 'not-owned'


def _poll_until_settled(handle, deadline: float):
    while True:
        recovery = handle.poll()
        if not _may_still_settle(recovery) or time.monotonic() >= deadline:
            return recovery
        time.sleep(SETTLE_POLL_SECONDS)


def _settlement(recovery, stop_status: str | None) -> Settlement:
    return Settlement(recovery.state, recovery.reason, recovery.identity_status,
                      recovery.state in controller_process.FINALIZABLE_STATES, stop_status)


def settle(handle, timeout_seconds: float, drain_seconds: float) -> Settlement:
    """Poll an OwnedProcess until its attempt is finalizable, within bounded budgets.

    Polls through active states and a live 'unknown'. Returns at once (no stop) on a state
    that cannot change by itself: finalizable, corrupt, finalized, or 'unknown' with the
    bootstrap proven gone. At the timeout it publishes STOP (honored only by the owned
    bootstrap, which stops its own group; nothing is signalled here) and drains for at most
    drain_seconds. Never finalizes; the caller finalizes only when ``settled`` is True.
    ProcessError from poll()/request_stop() propagates.
    """
    timeout, drain = _settle_budget(timeout_seconds), _settle_budget(drain_seconds)
    recovery = _poll_until_settled(handle, time.monotonic() + timeout)
    if not _may_still_settle(recovery):
        return _settlement(recovery, None)
    stop_status = handle.request_stop()
    # A gone bootstrap classifies immediately; a live or unproven one gets the bounded drain.
    recovery = _poll_until_settled(handle, time.monotonic() + drain)
    return _settlement(recovery, stop_status)


# ---------------------------------------------------------------- version / capability probe

@dataclass(frozen=True)
class CliProbe:
    provider: str
    version: str | None
    checked_version: str
    at_least_checked: bool | None
    help_flags: dict
    problems: tuple[str, ...]
    probe_dir: str
    authentication: str = 'not-checked'
    capacity: str = 'not-checked'


def _run_probe(process_root: Path, command, bindings: dict, environment,
               timeout: float) -> tuple[bytes | None, str | None]:
    """(stdout, None) for a provably clean owned run; otherwise (None, problem).

    'unresolved': the run never became finalizable within its budget plus a stop-and-drain
    (or its evidence is corrupt); it is not finalized and its directory stays as evidence.
    'unavailable': it could not start, or it settled but was not provably clean.
    """
    attempt = controller_process.prepare(process_root, command, timeout, PROBE_TERM_GRACE,
                                         PROBE_LINGER, bindings)
    try:
        pending = controller_process.spawn(attempt, environment)
    except ProcessError:
        return None, 'unavailable'
    try:
        owned = pending.release()
    except ProcessError:
        pending.abort()  # the release channel is closed; reap the bootstrap (bounded)
        return None, 'unavailable'
    drain = PROBE_TERM_GRACE + PROBE_LINGER + PROBE_SETTLE_MARGIN
    try:
        if not settle(owned, timeout + drain, drain).settled:
            return None, 'unresolved'
        record = owned.finalize()
    except ProcessError:
        return None, 'unresolved'
    if record['executionSuccess'] is not True:
        return None, 'unavailable'
    try:
        return _verified_stdout(attempt, record, MAX_PROBE_OUTPUT), None
    except ProcessError:
        return None, 'unavailable'


def probe_cli(provider: str, executable: str, attempts_root, probe_id: str, *,
              config_dir: str | None = None, environment=None,
              timeout_seconds: float = 10.0) -> CliProbe:
    """Report version and required help flags. Never infers authentication or capacity.

    Both commands run with empty stdin as owned attempts under <attempts_root>/<probe_id>/
    (work/ is their cwd and TMPDIR). The probe releases immediately: it is synchronous,
    read-only and its recovery evidence is that directory. Each run is waited on with
    settle(); a run that never becomes finalizable is reported '<name>-unresolved' (left
    unfinalized as evidence), an unclean or unstartable one '<name>-unavailable'.
    """
    _check_provider(provider)
    _check_executable(executable)
    if config_dir is not None:
        _check_canonical_dir(config_dir, 'config-dir-not-canonical')
    if not isinstance(probe_id, str) or not ATTEMPT_ID_RE.match(probe_id):
        raise ProviderError('invalid-probe-id')
    probe_dir = Path(_canonical_dir(attempts_root, 'attempts-root-not-canonical'), probe_id)
    work, process_root = probe_dir / PROBE_WORK_DIR, probe_dir / PROCESS_DIR
    try:
        os.mkdir(probe_dir, 0o700)
    except FileExistsError:
        raise ProviderError('probe-exists') from None
    try:
        for directory in (work, process_root):
            os.mkdir(directory, 0o700)
    except OSError as err:
        raise ProviderError('probe-create-failed') from err
    selectors, bindings = {'TMPDIR': str(work)}, {'tmp': str(work)}
    if config_dir is not None:
        selectors[CONFIG_SELECTORS[provider]] = config_dir
        bindings['config'] = config_dir

    def run(attempt_id: str, argv: tuple[str, ...]) -> tuple[bytes | None, str | None]:
        command = controller_process.CommandSpec(argv, str(work), b'', attempt_id, selectors)
        return _run_probe(process_root, command, bindings, environment, timeout_seconds)

    problems: list[str] = []
    version = None
    output, problem = run('version', (executable, '--version'))
    if output is None:
        problems.append(f'version-{problem}')
    else:
        match = VERSION_RE.search(output.decode('utf-8', 'replace'))
        version = match.group(0) if match else None
        if version is None:
            problems.append('version-unparsed')
    flags = {flag: False for flag in REQUIRED_HELP_FLAGS[provider]}
    output, problem = run('help', (executable, *HELP_ARGS[provider]))
    if output is None:
        problems.append(f'help-{problem}')
    else:
        text = output.decode('utf-8', 'replace')
        flags = {flag: re.search(rf'(?<![\w-]){re.escape(flag)}(?![\w-])', text) is not None
                 for flag in flags}
        if not all(flags.values()):
            problems.append('required-flag-missing')
    checked = CHECKED_VERSIONS[provider]
    at_least = None if version is None else tuple(int(part) for part in version.split('.')) >= checked
    return CliProbe(provider, version, '.'.join(map(str, checked)), at_least, flags,
                    tuple(problems), str(probe_dir))


# ---------------------------------------------------------------- stream parsing

@dataclass(frozen=True)
class ParsedStream:
    """Closed stream classification.

    quota_snapshots (Claude only): the LATEST <= 64 top-level rate_limit_event snapshots in
    stream order, each {provider, eventType, eventIndex (decoded-event index), line (1-based
    stdout line), sessionId, rate_limit_info: documented native keys (absent or invalid ->
    None) | None, invalidFields}. quota_snapshots_omitted counts earlier events not kept.
    quota_latest_status is the typed status of the very last event: None means unknown
    (absent or invalid) and never falls back to an earlier value. No timestamp is recorded.
    """
    category: str
    reasons: tuple[str, ...]
    session_id: str | None
    observed_model: str | None
    final_text: str | None
    structured_output: dict | None
    observed_cost_usd: float | None
    terminal_reason: str | None
    recovered_retries: tuple[str, ...]
    quota_snapshots: tuple[dict, ...]
    quota_snapshots_omitted: int
    quota_latest_status: str | None


EMPTY_PARSE = ParsedStream('incomplete', (), None, None, None, None, None, None, (), (), 0, None)


def _decode_events(data: bytes) -> tuple[list[dict], list[int], bool]:
    """(events, their 1-based line numbers, any malformed line)."""
    events, lines, malformed = [], [], False
    for number, line in enumerate(data.split(b'\n'), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line, parse_constant=_reject_constant)
        except (ValueError, UnicodeDecodeError, RecursionError):
            malformed = True
            continue
        if isinstance(event, dict):
            events.append(event)
            lines.append(number)
        else:
            malformed = True
    return events, lines, malformed


def _is_number(value) -> bool:
    """A finite JSON number. Booleans, non-finite floats and integers beyond exact float
    range are rejected instead of raising OverflowError."""
    if type(value) is int:
        return -MAX_EXACT_INT <= value <= MAX_EXACT_INT
    return type(value) is float and math.isfinite(value)


def _non_negative(value) -> bool:
    return _is_number(value) and value >= 0


def _identifier(value) -> str | None:
    """The exact native identifier when it is a non-blank string, else None."""
    return value if isinstance(value, str) and value.strip() else None


QUOTA_CHECKS = {
    'text': lambda value: _identifier(value) is not None,
    'epoch': lambda value: type(value) is int and _non_negative(value),
    'flag': lambda value: type(value) is bool,
    'ratio': _non_negative,
}


def _typed_fields(source: dict, spec, prefix: str, invalid: list[str]) -> dict:
    """Documented native keys only: absent stays None; present but invalid becomes None and
    is named in `invalid` (never coerced to zero)."""
    typed = {}
    for key, kind in spec:
        value = source.get(key)
        if value is not None and not QUOTA_CHECKS[kind](value):
            invalid.append(prefix + key)
            value = None
        typed[key] = value
    return typed


def _quota_windows(value, invalid: list[str]) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        invalid.append('unifiedWindows')
        return None
    windows = {}
    for name, window in list(value.items())[:MAX_QUOTA_WINDOWS]:
        if isinstance(window, dict):
            windows[name] = _typed_fields(window, QUOTA_WINDOW_FIELDS, f'unifiedWindows.{name}.', invalid)
        else:
            invalid.append(f'unifiedWindows.{name}')
    return windows


def _claude_quota_snapshot(index: int, line: int, event: dict) -> dict:
    """One native rate_limit_event as observed. No timestamp is invented; the caller
    records capture and ingestion times separately."""
    invalid: list[str] = []
    info, typed = event.get('rate_limit_info'), None
    if isinstance(info, dict):
        typed = _typed_fields(info, QUOTA_INFO_FIELDS, '', invalid)
        typed['unifiedWindows'] = _quota_windows(info.get('unifiedWindows'), invalid)
    else:
        invalid.append('rate_limit_info')
    return {'provider': 'claude', 'eventType': QUOTA_EVENT, 'eventIndex': index, 'line': line,
            'sessionId': _identifier(event.get('session_id')), 'rate_limit_info': typed,
            'invalidFields': invalid}


def _claude_quota(events: list[dict], lines: list[int]) -> tuple[tuple[dict, ...], int]:
    """(latest <= 64 snapshots, count omitted). Quota only from top-level rate_limit_event;
    look-alike fields inside assistant, tool or model content are never quota."""
    found = [index for index, event in enumerate(events) if event.get('type') == QUOTA_EVENT]
    kept = found[-MAX_QUOTA_SNAPSHOTS:]
    snapshots = tuple(_claude_quota_snapshot(index, lines[index], events[index]) for index in kept)
    return snapshots, len(found) - len(kept)


def _latest_quota_status(snapshots: tuple[dict, ...]) -> str | None:
    info = snapshots[-1]['rate_limit_info'] if snapshots else None
    return info['status'] if info is not None else None


def _error_code(value) -> str:
    return value if isinstance(value, str) and ERROR_CODE_RE.match(value) else 'unknown'


def _cost(value) -> float | None:
    return float(value) if _non_negative(value) else None


def _text(value) -> str | None:
    return value if isinstance(value, str) else None


def _task_envelope_problem(event: dict, session: str | None) -> str | None:
    if _identifier(event.get('uuid')) is None:
        return 'task-event-malformed'
    task_session = _identifier(event.get('session_id'))
    if task_session is None:
        return 'task-event-malformed'
    return None if task_session == session else 'task-foreign-session'


def _task_reference(event) -> tuple[str, str | None] | None:
    """(task_id, run_id) of a task event or snapshot entry; None when malformed."""
    if not isinstance(event, dict):
        return None
    task_id, run_id = _identifier(event.get('task_id')), event.get('run_id')
    if task_id is None or (run_id is not None and _identifier(run_id) is None):
        return None
    return task_id, run_id


def _task_snapshot(tasks) -> set[tuple[str, str | None]] | None:
    """The full live run set from background_tasks_changed; None when any entry is malformed."""
    if not isinstance(tasks, list):
        return None
    live = set()
    for entry in tasks:
        reference = _task_reference(entry)
        if reference is None or not isinstance(entry.get('task_type'), str) \
                or not isinstance(entry.get('description'), str):
            return None
        live.add(reference)
    return live


def _task_status(event: dict) -> tuple[bool, str | None]:
    """(well_formed, status) of a task_progress, task_updated or task_notification event."""
    if event['subtype'] == 'task_progress':
        return all(key not in event or isinstance(event[key], kind)
                   for key, kind in TASK_PROGRESS_OPTIONAL), None
    if event['subtype'] == 'task_updated':
        patch = event.get('patch')
        if not isinstance(patch, dict):
            return False, None
        status = patch.get('status')
        return status is None or isinstance(status, str), status
    status = event.get('status')
    return (isinstance(status, str) and isinstance(event.get('output_file'), str)
            and isinstance(event.get('summary'), str)), status


def _task_runs(tasks: dict, task_id: str) -> dict[str, set]:
    """Run history of one task: 'open' runs (None = run_id absent) and 'closed' run IDs."""
    return tasks.setdefault(task_id, {'open': set(), 'closed': set()})


def _finish_run(runs: dict[str, set], run_id: str | None) -> None:
    runs['open'].discard(run_id)
    if run_id is not None:
        runs['closed'].add(run_id)


def _start_task(tasks: dict, reference: tuple[str, str | None]) -> str | None:
    """A start opens its run; a repeated start of an open run changes nothing, so it can never
    replace a newer run. Restarting an already-closed run is conflicting evidence."""
    task_id, run_id = reference
    runs = _task_runs(tasks, task_id)
    if run_id is not None and run_id in runs['closed'] and run_id not in runs['open']:
        return 'task-run-conflict'
    runs['open'].add(run_id)
    return None


def _touch_task(tasks: dict, reference: tuple[str, str | None]) -> None:
    """Progress or a non-terminal update (status absent, pending, running, paused or unknown)
    proves the run live unless it names a run already closed (a stale, late event)."""
    task_id, run_id = reference
    runs = _task_runs(tasks, task_id)
    if run_id is None:
        if not runs['open']:
            runs['open'].add(None)
        return
    if run_id not in runs['closed']:
        runs['open'].add(run_id)


def _close_task(tasks: dict, reference: tuple[str, str | None]) -> str | None:
    """A terminal closes only the open run it names. Without run_id it closes only a sole open
    run of a task with no closed history; any other closure is ambiguous. A closed run is a
    stale replay; an unknown run while others are open is conflicting evidence."""
    task_id, run_id = reference
    runs = _task_runs(tasks, task_id)
    if run_id is None:
        if not runs['open']:
            return None
        if len(runs['open']) != 1 or runs['closed']:
            return 'task-run-conflict'
        _finish_run(runs, next(iter(runs['open'])))
        return None
    if run_id in runs['open'] or run_id in runs['closed'] or not runs['open']:
        _finish_run(runs, run_id)
        return None
    return 'task-run-conflict'


def _apply_snapshot(tasks: dict, snapshot: set[tuple[str, str | None]]) -> None:
    """An authoritative snapshot closes only the open runs it omits and opens every run it
    lists. A listed run keeps its actual history: no closure is fabricated for it."""
    for task_id, runs in tasks.items():
        for run_id in tuple(runs['open']):
            if (task_id, run_id) not in snapshot:
                _finish_run(runs, run_id)
    for task_id, run_id in snapshot:
        _task_runs(tasks, task_id)['open'].add(run_id)


def _apply_task_event(event: dict, tasks: dict) -> str | None:
    if event['subtype'] == 'background_tasks_changed':
        snapshot = _task_snapshot(event.get('tasks'))
        if snapshot is None:
            return 'task-event-malformed'
        _apply_snapshot(tasks, snapshot)
        return None
    reference = _task_reference(event)
    if reference is None:
        return 'task-event-malformed'
    if event['subtype'] == 'task_started':
        if not isinstance(event.get('description'), str):
            return 'task-event-malformed'
        return _start_task(tasks, reference)
    well_formed, status = _task_status(event)
    if not well_formed:
        return 'task-event-malformed'
    if status in TASK_TERMINAL_STATUSES:
        return _close_task(tasks, reference)
    _touch_task(tasks, reference)
    return None


def _background_task_reasons(events: list[dict], session: str | None) -> list[str]:
    """Reasons the run may still own native background tasks. A fresh CLI starts with no
    live set; a full snapshot replaces it (empty clears it)."""
    tasks: dict[str, dict[str, set]] = {}
    reasons: list[str] = []
    for event in events:
        if event.get('type') != 'system' or event.get('subtype') not in TASK_SUBTYPES:
            continue
        problem = _task_envelope_problem(event, session) or _apply_task_event(event, tasks)
        if problem:
            reasons.append(problem)
    if any(runs['open'] for runs in tasks.values()):
        reasons.append('background-task-unresolved')
    return list(dict.fromkeys(reasons))


def _parse_claude(events: list[dict], lines: list[int], malformed: bool) -> ParsedStream:
    reasons: list[str] = []
    init, terminals, retries = None, [], []
    denial_events, last_error, trailing = 0, None, False
    for event in events:
        kind, subtype = event.get('type'), event.get('subtype')
        trailing = trailing or bool(terminals)
        if kind == 'system' and subtype == 'init':
            if init is None:
                init = event
            else:
                reasons.append('duplicate-init')
        elif kind == 'system' and subtype == 'api_retry':
            last_error = _error_code(event.get('error'))
            retries.append(last_error)
        elif kind == 'permission_denied' or subtype == 'permission_denied':
            denial_events += 1
        elif kind == 'assistant' and 'error' in event and event['error'] is not None:
            last_error = _error_code(event['error'])
        elif kind == 'result':
            terminals.append(event)
    session = _identifier(init.get('session_id')) if init else None
    if malformed:
        reasons.append('malformed-event')
    if init is None:
        reasons.append('missing-init')
    elif session is None:
        reasons.append('missing-session')
    if not terminals:
        reasons.append('missing-terminal')
    if len(terminals) > 1:
        reasons.append('duplicate-terminal')
    if trailing:
        reasons.append('event-after-terminal')
    reasons.extend(_background_task_reasons(events, session))
    terminal = terminals[0] if len(terminals) == 1 else None
    denied, success = denial_events > 0, False
    final_text = structured = cost = None
    if terminal is not None:
        if terminal.get('session_id') != session:
            reasons.append('session-mismatch')
        denials, is_error = terminal.get('permission_denials'), terminal.get('is_error')
        if not isinstance(denials, list) or not isinstance(is_error, bool):
            reasons.append('malformed-terminal')
        elif denials:
            denied = True
        success = terminal.get('subtype') == 'success' and is_error is False
        final_text = _text(terminal.get('result'))
        structured = terminal.get('structured_output') if isinstance(terminal.get('structured_output'), dict) else None
        cost = _cost(terminal.get('total_cost_usd'))
        if cost is None and terminal.get('total_cost_usd') is not None:
            reasons.append('invalid-cost')
    snapshots, omitted = _claude_quota(events, lines)
    latest = _latest_quota_status(snapshots)
    if denied:
        reasons.append('permission-denied')
        category = 'permission_denied'
    elif reasons:
        category = 'incomplete'
    elif success:
        category = 'success'
    elif latest == 'rejected':
        reasons.append('quota-rejected')
        category = 'rate_limited'
    else:
        category = ERROR_CATEGORIES.get(last_error, 'failed')
    is_success = category == 'success'
    return ParsedStream(category, tuple(reasons), session,
                        _text(init.get('model')) if init else None, final_text, structured, cost,
                        None if is_success else last_error,
                        tuple(retries) if is_success else (), snapshots, omitted, latest)


def _codex_item(event: dict) -> dict | None:
    item = event.get('item')
    return item if isinstance(item, dict) else None


def _parse_codex(events: list[dict], malformed: bool) -> ParsedStream:
    """Codex exec JSONL (checked against rust-v0.169.0).

    A top-level `error` is a possibly-recovered transport error: it is recovered only when
    exactly one turn.completed follows. command_execution `declined` is a typed rejection of
    ambiguous cause -> command-declined (never permission_denied). Ordinary failed commands,
    file_change and MCP failures are ordinary work. Unknown events are ignored.
    """
    reasons: list[str] = []
    thread_event, terminals, last_text, trailing = None, [], None, False
    errors = declined = 0
    for event in events:
        kind = event.get('type')
        trailing = trailing or bool(terminals)
        item = _codex_item(event) if kind == 'item.completed' else None
        if kind == 'thread.started':
            if thread_event is None:
                thread_event = event
            else:
                reasons.append('duplicate-init')
        elif kind in ('turn.completed', 'turn.failed'):
            terminals.append(kind)
        elif kind == 'error':
            errors += 1
        elif item is not None and item.get('type') == 'agent_message' and isinstance(item.get('text'), str):
            last_text = item['text']
        elif item is not None and item.get('type') == 'command_execution' and item.get('status') == 'declined':
            declined += 1
    session = _identifier(thread_event.get('thread_id')) if thread_event else None
    if malformed:
        reasons.append('malformed-event')
    if thread_event is None:
        reasons.append('missing-init')
    elif session is None:
        reasons.append('missing-session')
    if not terminals:
        reasons.append('missing-terminal')
    if len(terminals) > 1:
        reasons.append('duplicate-terminal')
    if trailing:
        reasons.append('event-after-terminal')
    structural = bool(reasons)
    if declined:
        reasons.append('command-declined')
    if structural:
        category = 'incomplete'
    elif terminals == ['turn.failed']:
        category = 'failed'
    elif declined:
        category = 'incomplete'
    else:
        category = 'success'
    if errors and category != 'success':
        reasons.append('error-event')  # observed only; its free-form text is never interpreted
    retries = ('error-event',) * errors if category == 'success' else ()
    return ParsedStream(category, tuple(reasons), session,
                        _text(thread_event.get('model')) if thread_event else None, last_text,
                        None, None, None, retries, (), 0, None)


def parse_stream(provider: str, data: bytes) -> ParsedStream:
    """Classify native JSONL. Unknown fields and event types are ignored; anything short
    of exactly one recognised successful terminal is never 'success'."""
    _check_provider(provider)
    events, lines, malformed = _decode_events(data)
    if provider == 'claude':
        return _parse_claude(events, lines, malformed)
    return _parse_codex(events, malformed)


# ---------------------------------------------------------------- review verdict extraction

def _is_finding(item) -> bool:
    return (isinstance(item, str) and item.strip() != '') or (isinstance(item, dict) and bool(item))


def _validated_verdict(data) -> tuple[dict | None, str | None]:
    if not isinstance(data, dict):
        return None, 'verdict-not-object'
    if set(data) != VERDICT_KEYS:
        return None, 'verdict-fields'
    if type(data['version']) is not int or data['version'] != 1:
        return None, 'verdict-version'
    if data['verdict'] not in ('PASS', 'FAIL', 'INCOMPLETE'):
        return None, 'verdict-value'
    if not all(isinstance(data[key], str) and SHA_RE.match(data[key]) for key in ('base_sha', 'result_sha')):
        return None, 'verdict-sha'
    if not all(isinstance(data[key], list) and all(_is_finding(item) for item in data[key])
               for key in ('findings', 'gaps')):
        return None, 'verdict-findings'
    return json.loads(json.dumps(data)), None


def extract_review_verdict(structured_output, final_text) -> tuple[dict | None, str | None]:
    """Shape-check one review verdict candidate; no semantic gate is applied here.

    Native structured output is used when present. Otherwise exactly one fenced
    `sdlc-verdict` JSON block in the final assistant text is required; prose such as
    'done' is never a verdict.
    """
    if structured_output is not None:
        return _validated_verdict(structured_output)
    if not isinstance(final_text, str):
        return None, 'verdict-absent'
    openings = VERDICT_OPEN_RE.findall(final_text)
    if not openings:
        return None, 'verdict-absent'
    if len(openings) > 1:
        return None, 'verdict-multiple'
    blocks = VERDICT_BLOCK_RE.findall(final_text)
    if len(blocks) != 1:
        return None, 'verdict-unterminated'
    try:
        data = json.loads(blocks[0], parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        return None, 'verdict-malformed'
    return _validated_verdict(data)


# ---------------------------------------------------------------- outcome

@dataclass(frozen=True)
class ProviderOutcome:
    provider: str | None
    attempt_id: str
    execution_admitted: bool
    category: str
    stream_category: str | None
    reasons: tuple[str, ...]
    lifecycle_state: str
    session_id: str | None
    observed_model: str | None
    observed_cost_usd: float | None
    terminal_reason: str | None
    recovered_retries: tuple[str, ...]
    quota_snapshots: tuple[dict, ...]
    quota_snapshots_omitted: int
    quota_latest_status: str | None
    final_text: str | None
    structured_output: dict | None
    verdict_candidate: dict | None
    verdict_problem: str | None
    raw_logs: dict

    def to_record(self) -> dict:
        return {**asdict(self), 'limitations': list(LIMITATIONS)}


def _outcome(attempt_id: str, association: dict | None, lifecycle_state: str, parsed: ParsedStream,
             category: str, reasons, raw_logs: dict, stream_category: str | None) -> ProviderOutcome:
    reasons = tuple(dict.fromkeys(reasons))
    verdict, problem = extract_review_verdict(parsed.structured_output, parsed.final_text)
    return ProviderOutcome(
        provider=association['provider'] if association else None, attempt_id=attempt_id,
        execution_admitted=category == 'success' and not reasons, category=category,
        stream_category=stream_category, reasons=reasons, lifecycle_state=lifecycle_state,
        session_id=parsed.session_id, observed_model=parsed.observed_model,
        observed_cost_usd=parsed.observed_cost_usd, terminal_reason=parsed.terminal_reason,
        recovered_retries=parsed.recovered_retries, quota_snapshots=parsed.quota_snapshots,
        quota_snapshots_omitted=parsed.quota_snapshots_omitted,
        quota_latest_status=parsed.quota_latest_status, final_text=parsed.final_text,
        structured_output=parsed.structured_output, verdict_candidate=verdict,
        verdict_problem=problem, raw_logs=raw_logs)


def _finalized_record(process_path: Path) -> tuple[str, dict | None]:
    """(state, validated lifecycle record | None); anything but a current-schema finalized
    record yields None, so an old or unsupported record can never pass."""
    try:
        status = controller_process.read_status(process_path)
    except ProcessError:
        return 'unreadable', None
    record = status.get('record')
    if status.get('state') != 'finalized' or not isinstance(record, dict):
        return str(status.get('state')), None
    if record.get('schema') != controller_process.SCHEMA_RECORD:
        return 'unsupported', None
    return 'finalized', record


def assess(attempt) -> ProviderOutcome:
    """Read-only provider outcome. Success requires a valid association bound to the exact
    process intent, a finalized lifecycle with executionSuccess (terminal, proven-empty group,
    no forced cleanup or stray descendants) and a successful native terminal in the hashed
    stdout. Missing, corrupt or unsupported lifecycle evidence is INCOMPLETE."""
    path = _attempt_path(attempt)
    process_path = path / PROCESS_DIR / path.name
    association, problems = None, []
    try:
        association = _load_association(path)
    except ProviderError as err:
        problems.append(err.code)
    state, record = _finalized_record(process_path)
    if record is None:
        problems.append(f'lifecycle-{state}')
    if problems:
        return _outcome(path.name, association, state, EMPTY_PARSE, 'incomplete', problems, {}, None)
    raw_logs = dict(record['logs'])
    try:
        if _bound_intent_sha(association, process_path) != record['intentSha256']:
            raise ProviderError('intent-association-mismatch')
    except ProviderError as err:
        return _outcome(path.name, association, state, EMPTY_PARSE, 'incomplete', [err.code], raw_logs, None)
    try:
        data = _verified_stdout(process_path, record, MAX_STREAM_BYTES)
    except ProviderError as err:
        reason = 'stream-too-large' if err.code in ('log-too-large', 'artifact-too-large') \
            else 'stream-log-mismatch'
        return _outcome(path.name, association, state, EMPTY_PARSE, 'incomplete', [reason], raw_logs, None)
    parsed = parse_stream(association['provider'], data)
    reasons = list(parsed.reasons) + list(record['reasons'])
    if record['executionSuccess'] is not True:
        reasons.append('lifecycle-not-clean')
    category = TERMINATION_CATEGORIES.get(record['termination']) or parsed.category
    if category == 'success' and reasons:
        category = 'incomplete'
    return _outcome(path.name, association, state, parsed, category, reasons, raw_logs, parsed.category)


if __name__ == '__main__':
    print(json.dumps({'outcome': 'usage-error', 'reasons': ['library-module']}), file=sys.stderr)
    sys.exit(2)
