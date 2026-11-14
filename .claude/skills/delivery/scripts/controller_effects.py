#!/usr/bin/env python3
"""Fixed-catalogue Git/GitHub effects for an optional persistent delivery controller.

This module is a library for a TRUSTED controller process. It is not a CLI, not a sandbox
against the same OS user, and never a source of authority: the controller's engine owns the
owner policy, the durable ledger and every result/check/review gate. This module only
(1) validates a typed effect spec, (2) observes whether an effect is already applied and
(3) executes one concrete, fixed Git/GitHub operation with literal argv.

Catalogue (closed; there is no generic command or success callback)
    worktree.create  new branch + linked worktree at an exact base SHA (unique branch/path)
    task.commit      commit exactly the owned changed paths of one task worktree
    integrate        advance one owned integration branch, checked out ONLY in its owned
                     linked integration worktree at the expected base, with a normal
                     ``git merge --ff-only`` or ``git merge --no-ff`` (normal merge hooks
                     run; the user's own worktrees are never touched). A task result
                     already contained in the expected base (equal SHA or strict
                     ancestor, either strategy) is an OBSERVED no-op: observe confirms
                     ``already-contained`` (result_sha == expected_base, containment,
                     ``mutation_required`` False) only while the target is at the base in
                     its clean, sole-holder integration worktree on the target and the task
                     branch tip is exactly task_result; execute refuses it as
                     ``already-applied`` through the normal precondition path, so no
                     mutating command (and never an empty commit) runs
    push             non-force push of an exact SHA to an exact remote branch
    pr.create        open one PR for an exact head branch/SHA, reusing an exact match
    pr.merge         merge an exact reviewed, up-to-date head after declared required checks
                     pass, only on a qualified strict, admin-enforced classic-protected base
                     with the merge queue proven off; observe verifies the merged commit's
                     parents and tree
    worktree.remove  remove one clean, committed, owned task worktree (never the branch)

Journal contract (what the engine must do around these calls)
    1. Validate: ``validate_spec(kind, spec)`` (or ``spec_from_mapping`` when reloading a
       ledger row). Specs carry identities only; no field can grant authority.
    2. Gate: enforce owner policy and the exact result/check/review gates in the engine.
       Nothing here reads a worker-supplied "pass"; pr.merge re-reads required checks itself.
    3. Persist intent (kind + ``spec_to_mapping(spec)``) durably BEFORE ``execute``.
    4. ``execute(kind, spec, toolchain=..., authorized_kinds=...)`` re-observes the effect and
       its preconditions immediately before mutating and returns a raw ``ExecuteOutcome``.
       No status, including ``completed``, is success.
    5. Persist the outcome, then ``observe(kind, spec, toolchain=...)`` and persist it.
    6. ``settle(outcome, observation)`` gives the ledger state. Only ``confirmed`` is applied.
       ``unknown`` holds (re-observe later; never retry blindly); ``conflict`` blocks for the
       owner; ``not_applied`` may be retried as a NEW intent boundary.
    7. Crash recovery: an intent without an outcome is uncertain. ``Toolchain.evidence_root``
       is the engine-owned directory of ONE effect intent (journalled before any call), so
       every later observe/execute for that intent first inspects the command attempts of
       all earlier calls under it. A command that is not provably terminal (active, owned,
       unknown, corrupt, unreadable, or finalized with a non-empty group / unresolved
       descendants) holds: observe returns ``unknown:prior-command-unresolved`` and execute
       returns ``incomplete:prior-command-unresolved`` without running any command, Git
       read or provider query. ``inspect_commands(evidence_root)`` is the read-only view;
       its typed ``PriorCommand.attempt`` is what the engine passes to
       ``controller_process.request_stop`` for a positively owned attempt (the helper never
       acts on an unproven identity). A settled-but-unfinalized prior attempt is finalized
       (evidence only) before observing. A terminal prior MUTATION that did not end by
       itself (timeout, STOP, forced cleanup, lingering, escaped, lost) still allows a
       confirmed/conflict observation, but ``not_applied`` becomes
       ``unknown:prior-mutation-unclean`` and execute refuses to replay. A prior command
       that exited nonzero with a clean lifecycle does not hold. Call
       ``settle(None, observation)`` only after the engine's own hold period for remote
       (GitHub) effects, because list/view APIs can lag a just-completed write.
    This gives at-least-once attempts with observation-based deduplication, not exactly-once:
    a provider write can land after its command was stopped, and nothing here can prove a
    provider did NOT apply a write whose command did not exit cleanly.
    The engine must serialise effects per repository (one integration target at a time).

State vocabulary
    observe -> confirmed | not_applied | unknown | conflict  (``Observation``)
    execute -> completed | failed | timed_out | cancelled | refused | incomplete
              (``ExecuteOutcome``; ``incomplete`` = required evidence missing/pending, a
              command whose lifecycle ended uncleanly or never settled, or an unresolved
              prior command; ``refused`` = precondition violated or already applied,
              nothing mutated)

Safety properties
    - Executables come only from ``Toolchain`` (absolute, owner-approved paths). Specs never
      name an executable; tests inject fake git/gh the same way.
    - Fixed literal argv, no shell. Every command runs through the shared owned-process
      helper (``controller_process``, loaded from this directory): a NEW exclusive attempt
      (intent, stdin and identity persisted before release), an anchored process group,
      the helper's own ``timeout_seconds``, a bounded ``linger_seconds`` drain for
      descendants that outlive the command (for example a hook's redirected background
      child), SIGTERM then SIGKILL of ONLY the positively owned group, and one finalized
      lifecycle record. A call returns from a command only once that record exists.
      Cancel publishes the helper's STOP request; nothing here signals a process.
      Timeout, STOP, forced cleanup, lingering, escaped/unresolved descendants or an
      unobserved group are never success and never conclusive ``not_applied``.
    - Inherited ``GIT_*`` selectors (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_CONFIG_*
      parameters, GIT_EXEC_PATH ...) and GH_REPO/GH_HOST are dropped; only config-file
      selectors and SSH/askpass auth variables pass through. Prompts are disabled.
    - Every gh call names its GitHub host explicitly: ``gh api --hostname <host>`` (REST
      and the fixed GraphQL read) and PR commands ``--repo <host>/<owner>/<name>``, where
      host is the spec's explicit host or github.com. Neither GH_HOST nor the CLI's
      configured default host (which may be a sole enterprise host) selects the target.
      GH_CONFIG_DIR and the owner's auth stay inherited; no account or host is switched.
    - Every Git call binds ``-C <path>`` and is checked against the canonical common Git dir.
    - Push refuses repository-local config that runs commands or rewrites URLs
      (sshCommand, credential helpers, insteadOf, receivepack, include ...) and requires the
      effective fetch AND push URL to equal the expected URL. The saved URL is never changed.
    - Push screens every repository-controlled config file Git would read: always the local
      file, plus config.worktree only when the trusted local config enables
      extensions.worktreeConfig. An enabled but absent config.worktree is proven empty; a
      symlinked, non-regular or unreadable file is never treated as empty.
    - Hooks run normally. Nothing passes --no-verify, -n, core.hooksPath, --force,
      --force-with-lease, --amend, --admin, --auto, --delete-branch or --rebase, and no
      commit is written with plumbing (no commit-tree / update-ref). ``-c
      core.fsmonitor=false`` and ``protocol.{ext,fd}.allow=never`` only tighten one call;
      ``--no-autostash``, ``--no-rerere-autoupdate`` and ``--no-log`` only tighten a merge.
    - No reset, clean, stash, merge --abort or checkout of user work. A stopped merge
      (conflict or rejecting hook) is preserved in the integration worktree and observe
      reports ``conflict:integration-worktree-blocked`` until the owner reconciles it.
    - Full private command evidence: ``Toolchain.evidence_root`` must be an existing,
      owner-owned, mode-0700 canonical directory outside every repository path in the
      spec. Each observe/execute creates one exclusive call directory
      (``<stamp>-<operation>-<kind>-<pid>-<random>``) holding attempt.json, an empty 0700
      ``cwd/`` (neutral working directory for gh and ``git version``), ``commands/`` (the
      helper's attempts root: one NEW attempt ``NNNN-mutation|read`` per command with the
      immutable intent - literal argv, cwd, executable binding, stdin bytes and sha256 -
      spawn identity, journal, full raw stdout.log/stderr.log and lifecycle.json with log
      sizes and sha256), ``claim-<id>.json`` (identity, persisted before release) and
      ``receipt-<id>.json`` (the returned ``CommandRecord`` without tails). Raw logs are
      the helper's immutable files (never copied), unredacted owner-private evidence;
      stdout is re-hashed against lifecycle.json before it is parsed, and returned tails
      are bounded and credential-redacted. If a command never settles or its evidence
      cannot be verified, the call stops, ``evidence_complete`` is False and the outcome
      settles ``unknown``. Observe writes only this evidence and never mutates Git or the
      provider.
    - The merge prediction runs ``git --git-dir=<quarantine> merge-tree`` against a private
      0700 scratch repository inside the call directory: the repository object store is
      only an alternate, the repository config is included, the common
      ``info/attributes`` is copied and ``attr.tree`` names the expected base (Git >= 2.42;
      older Git ignores it). The helper strips GIT_OBJECT_DIRECTORY-style selectors, so
      the quarantine is a literal argument, not environment. It is removed after a
      settled read and retained as evidence otherwise.
    - The merge prediction must be pure built-in Git. Effective config (any scope Git
      reads) naming a command-running merge driver or filter (merge.<name>.driver,
      filter.<name>.clean/smudge/process) or setting merge.renormalize holds a merge-commit
      integrate as ``conflict:merge-prediction-driver-unsupported``. Config is never
      changed; the authorized ``git merge`` itself runs normal hooks, drivers and filters.
    - worktree.create confirms only an existing, non-prunable linked worktree whose
      directory, top level, common dir, branch and HEAD are bound exactly; a missing,
      replaced or prunable registration is a conflict and is never pruned or recreated.
    - pr.create proves absence only from a complete listing: ``--limit 101`` and at most
      100 rows (gh pages internally until the limit or the last page); a longer listing is
      ``unknown:pr-list-truncated``. Every row must be fully typed and a matching PR must
      carry its canonical URL; otherwise the observation is ``unknown``.
    - pr.merge binds the reviewed head with ``--match-head-commit`` and re-reads the base
      ref, base containment and declared required checks just before merging. Before any
      ``gh pr merge`` it also requires (a) a freshly read, typed CLASSIC branch protection
      of the exact base with ``required_status_checks.strict`` True, a non-empty configured
      check set and ``enforce_admins.enabled`` True, and (b) the PR's typed GraphQL
      ``isMergeQueueEnabled`` and ``isInMergeQueue`` exactly False for the exact
      repository/number/base/head (``gh pr merge`` enqueues on a merge-queue base even
      without ``--auto``; ``autoMergeRequest: null`` proves nothing). Unreadable,
      404/403, missing, malformed, loose, admin-bypassable, ruleset-only or queue-enabled
      governance is ``incomplete`` with no mutation. Settings, credentials and protection
      are never changed; there is no ``--admin`` or ``--auto``. Qualified assumption:
      strict server rules reject an out-of-date head, but GitHub still has no
      compare-and-swap on the exact base and governance can change after it was observed,
      so a foreign base push or governance change inside that window leaves observe at
      ``unknown:merged-identity-mismatch`` from the merged commit's parents/tree. No
      rollback, retry, exactly-once or global foreign-actor lock.

Engine-facing API beyond observe/execute/settle
    ``Toolchain.term_grace_seconds`` / ``linger_seconds`` (helper bounds, defaults 5s),
    ``CommandRecord`` lifecycle fields (mutation, termination, process_state,
    identity_status, stop_status, forced, lingering, lifecycle_clean, lifecycle_reasons;
    ``pid`` is the anchored group leader), ``PriorCommand`` and
    ``inspect_commands(evidence_root)``.

Requires Git >= 2.38 (merge-tree --write-tree, worktree list -z, merge -F) and, for
pr.merge, a gh whose ``pr merge --help`` documents ``--match-head-commit`` and a
credential that can read the base's classic branch protection (otherwise ``incomplete``).
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import stat
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol


def _load_process_helper() -> Any:
    """The shared owned-process helper next to this file (never a PATH or sys.path lookup)."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'controller_process.py')
    loaded = sys.modules.get('controller_process')
    if loaded is not None:
        if os.path.realpath(getattr(loaded, '__file__', None) or '') != path:
            raise ImportError('a different controller_process module is already loaded')
        return loaded
    spec = importlib.util.spec_from_file_location('controller_process', path)
    if spec is None or spec.loader is None:
        raise ImportError('controller_process helper is unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules['controller_process'] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules['controller_process']
        raise
    return module


_process = _load_process_helper()

# Observation states.
CONFIRMED = 'confirmed'
NOT_APPLIED = 'not_applied'
UNKNOWN = 'unknown'
CONFLICT = 'conflict'

# Raw execute statuses. None of them is success on its own; only an observation confirms.
COMPLETED = 'completed'
FAILED = 'failed'
TIMED_OUT = 'timed_out'
CANCELLED = 'cancelled'
REFUSED = 'refused'
INCOMPLETE = 'incomplete'

WORKTREE_CREATE = 'worktree.create'
TASK_COMMIT = 'task.commit'
INTEGRATE = 'integrate'
PUSH = 'push'
PR_CREATE = 'pr.create'
PR_MERGE = 'pr.merge'
WORKTREE_REMOVE = 'worktree.remove'
KINDS = (WORKTREE_CREATE, TASK_COMMIT, INTEGRATE, PUSH, PR_CREATE, PR_MERGE, WORKTREE_REMOVE)
# Effects whose provider read APIs may lag a completed write.
REMOTE_ASYNC_KINDS = frozenset({PR_CREATE, PR_MERGE})

FAST_FORWARD = 'fast-forward'
MERGE_COMMIT = 'merge'
INTEGRATE_STRATEGIES = (FAST_FORWARD, MERGE_COMMIT)
MERGE_METHODS = ('merge', 'squash')

MIN_GIT_VERSION = (2, 38)
DEFAULT_TIMEOUT_SECONDS = 300.0
MAX_TIMEOUT_SECONDS = 3600.0
DEFAULT_OUTPUT_LIMIT = 16384
MAX_LISTED = 200
# Bounds handed to the shared process helper (same limits it enforces).
DEFAULT_TERM_GRACE_SECONDS = 5.0
MAX_TERM_GRACE_SECONDS = 60.0
DEFAULT_LINGER_SECONDS = 5.0
MAX_LINGER_SECONDS = 600.0


class Cancellation(Protocol):
    """Anything with ``is_set()``, for example ``threading.Event``."""

    def is_set(self) -> bool: ...


class SpecError(ValueError):
    """An effect spec failed validation; raised before any command runs."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ToolchainError(ValueError):
    """The owner-approved toolchain or authority set is unusable; raised before any command."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------- specs

@dataclass(frozen=True)
class WorktreeCreateSpec:
    repo: str
    common_dir: str
    branch: str
    path: str
    base_sha: str


@dataclass(frozen=True)
class TaskCommitSpec:
    repo: str
    common_dir: str
    worktree: str
    branch: str
    expected_parent: str
    owned_paths: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class IntegrateSpec:
    repo: str
    common_dir: str
    integration_worktree: str
    target_branch: str
    expected_base: str
    task_branch: str
    task_result: str
    strategy: str
    message: str


@dataclass(frozen=True)
class PushSpec:
    repo: str
    common_dir: str
    remote: str
    remote_url: str
    local_branch: str
    expected_result: str
    remote_branch: str
    expected_remote_old: str | None
    base_branch: str
    expected_base: str


@dataclass(frozen=True)
class PrCreateSpec:
    github_repo: str
    base_branch: str
    expected_base_sha: str
    head_branch: str
    head_sha: str
    title: str
    body: str


@dataclass(frozen=True)
class PrMergeSpec:
    github_repo: str
    number: int
    base_branch: str
    expected_base_sha: str
    head_branch: str
    expected_head: str
    required_checks: tuple[str, ...]
    method: str


@dataclass(frozen=True)
class WorktreeRemoveSpec:
    repo: str
    common_dir: str
    cleanup_root: str
    path: str
    branch: str
    expected_head: str


SPEC_TYPES: dict[str, type] = {
    WORKTREE_CREATE: WorktreeCreateSpec,
    TASK_COMMIT: TaskCommitSpec,
    INTEGRATE: IntegrateSpec,
    PUSH: PushSpec,
    PR_CREATE: PrCreateSpec,
    PR_MERGE: PrMergeSpec,
    WORKTREE_REMOVE: WorktreeRemoveSpec,
}


# --------------------------------------------------------------------------- toolchain

@dataclass(frozen=True)
class Toolchain:
    """Owner-approved executables and limits. Never built from project or worker input."""

    git: str
    gh: str | None = None
    environment: Mapping[str, str] | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    output_limit: int = DEFAULT_OUTPUT_LIMIT
    # Required (None is refused): existing owner-owned 0700 canonical directory outside
    # every repository path in a spec, owned by the engine for ONE effect intent. Full raw
    # command evidence is retained here and inspected before every later call.
    evidence_root: str | None = None
    # SIGTERM-to-SIGKILL grace and the bounded drain for descendants that outlive a command.
    term_grace_seconds: float = DEFAULT_TERM_GRACE_SECONDS
    linger_seconds: float = DEFAULT_LINGER_SECONDS


# --------------------------------------------------------------------------- results

@dataclass(frozen=True)
class CommandRecord:
    argv: tuple[str, ...]
    cwd: str
    exit_code: int | None
    signal: int | None
    timed_out: bool
    cancelled: bool
    duration_ms: int
    stdout_tail: str
    stderr_tail: str
    spawn_error: str | None = None
    evidence_dir: str = ''
    pid: int | None = None
    started_at: str = ''
    ended_at: str = ''
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_sha256: str = ''
    stderr_sha256: str = ''
    evidence_error: str | None = None
    mutation: bool = False
    termination: str | None = None
    process_state: str | None = None
    identity_status: str | None = None
    process_reason: str | None = None
    stop_status: str | None = None
    forced: bool = False
    lingering: bool = False
    lifecycle_clean: bool = False
    lifecycle_reasons: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        """Exit 0 of a command whose owned group ended cleanly; never semantic success."""
        return (self.exit_code == 0 and not self.timed_out and not self.cancelled
                and self.spawn_error is None and self.lifecycle_clean)

    def as_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data['argv'] = list(self.argv)
        data['lifecycle_reasons'] = list(self.lifecycle_reasons)
        return data


@dataclass(frozen=True)
class Observation:
    kind: str
    state: str
    reason: str
    evidence: Mapping[str, Any]
    commands: tuple[CommandRecord, ...]
    evidence_dir: str = ''

    def as_dict(self) -> dict[str, Any]:
        return {'kind': self.kind, 'state': self.state, 'reason': self.reason,
                'evidence': dict(self.evidence), 'commands': [c.as_dict() for c in self.commands],
                'evidence_dir': self.evidence_dir}


@dataclass(frozen=True)
class ExecuteOutcome:
    kind: str
    status: str
    reason: str
    mutation_attempted: bool
    commands: tuple[CommandRecord, ...]
    details: Mapping[str, Any]
    evidence_dir: str = ''
    evidence_complete: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {'kind': self.kind, 'status': self.status, 'reason': self.reason,
                'mutation_attempted': self.mutation_attempted, 'details': dict(self.details),
                'commands': [c.as_dict() for c in self.commands], 'evidence_dir': self.evidence_dir,
                'evidence_complete': self.evidence_complete}


@dataclass(frozen=True)
class PriorCommand:
    """One command attempt left under an effect's evidence root by an earlier call.

    ``hold`` is True when the command is not provably terminal (active, owned, unknown,
    corrupt, unreadable, settled-but-unfinalized, or finalized with a non-empty group or
    unresolved descendants) or its evidence is missing (a claim or receipt whose attempt
    is gone, an untrusted claim/receipt, a lost commands root, a claimed attempt with no
    spawn evidence, or a receipt recording a spawn or settlement the helper facts
    contradict): nothing may observe or replay the effect while it holds.
    ``attempt`` is the helper attempt path the engine may pass to
    ``controller_process.request_stop`` / ``OwnedProcess.attach``; the helper acts only on
    a positively owned bootstrap."""

    attempt: str
    call_dir: str
    mutation: bool
    state: str
    identity_status: str | None
    reason: str | None
    termination: str | None
    lifecycle_clean: bool
    hold: bool

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# --------------------------------------------------------------------------- validation

_SHA_RE = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
_BRANCH_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}')
_REMOTE_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
_GH_REPO_RE = re.compile(r'(?:(?P<host>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)/)?'
                         r'(?P<owner>[A-Za-z0-9-]{1,39})/(?P<name>[A-Za-z0-9._-]{1,100})')
_SCP_URL_RE = re.compile(r'[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._~][A-Za-z0-9._~/-]*')
_CONVENTIONAL_RE = re.compile(r'(?:feat|fix|docs|refactor|test|chore|perf|build|ci|style|revert)'
                              r'(?:\([A-Za-z0-9._/-]+\))?!?: \S.*')
_ATTRIBUTION_RE = re.compile(
    r'(?im)^[ \t]*(?:co-authored-by|assisted-by|generated-by|ai-assisted)[ \t]*:'
    r'|\b(?:generated|created|written|authored)[ \t]+(?:with|by|using)[ \t]+\[?'
    r'(?:claude|codex|chatgpt|gpt|copilot|anthropic|openai|an?[ \t]+ai\b|ai\b)'
    r'|\U0001F916')


def _is_canonical_abs(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and not any(ch in value for ch in '\0\n\r')
            and os.path.isabs(value) and os.path.normpath(value) == value
            and os.path.realpath(value) == value)


def _require_abs(value: object, name: str) -> None:
    if not _is_canonical_abs(value):
        raise SpecError(f'non-canonical-path:{name}')


def _require_sha(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise SpecError(f'invalid-sha:{name}')


def _require_branch(value: object, name: str) -> None:
    if not isinstance(value, str) or not _BRANCH_RE.fullmatch(value) or '..' in value:
        raise SpecError(f'invalid-branch:{name}')
    for part in value.split('/'):
        if not part or part.startswith('.') or part.endswith(('.', '.lock')):
            raise SpecError(f'invalid-branch:{name}')
    if value == 'HEAD':
        raise SpecError(f'invalid-branch:{name}')


def _require_text(value: object, name: str, *, max_len: int, single_line: bool) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise SpecError(f'invalid-text:{name}')
    if '\0' in value or '\r' in value or (single_line and '\n' in value):
        raise SpecError(f'invalid-text:{name}')
    if _ATTRIBUTION_RE.search(value):
        raise SpecError(f'ai-attribution:{name}')
    return value


def _require_conventional(value: object, name: str, *, max_len: int, single_line: bool) -> None:
    text = _require_text(value, name, max_len=max_len, single_line=single_line)
    subject = text.split('\n', 1)[0]
    if len(subject) > 100 or not _CONVENTIONAL_RE.fullmatch(subject):
        raise SpecError(f'non-conventional:{name}')


def _require_owned_paths(paths: tuple[str, ...]) -> None:
    if not paths or len(paths) > 1000:
        raise SpecError('invalid-owned-paths')
    for path in paths:
        if not path or len(path) > 4096 or any(ch in path for ch in '\0\n\r\\') or path.startswith('/'):
            raise SpecError('invalid-owned-paths')
        body = path[:-1] if path.endswith('/') else path
        if any(segment in ('', '.', '..', '.git') for segment in body.split('/')):
            raise SpecError('invalid-owned-paths')


def _require_remote_url(value: object) -> None:
    if (not isinstance(value, str) or not value or len(value) > 2048 or '::' in value
            or any(ch.isspace() or ord(ch) < 32 for ch in value)):
        raise SpecError('invalid-remote-url')
    if value.startswith(('https://', 'ssh://')):
        authority = value.split('://', 1)[1].split('/', 1)[0]
        userinfo = authority.rpartition('@')[0]
        if value.startswith('https://') and userinfo or ':' in userinfo:
            raise SpecError('credential-in-remote-url')
        if not authority or authority.startswith('-'):
            raise SpecError('invalid-remote-url')
        return
    if value.startswith('/'):
        _require_abs(value, 'remote_url')
        return
    if _SCP_URL_RE.fullmatch(value):
        return
    raise SpecError('invalid-remote-url')


def _require_github_repo(value: object) -> None:
    match = _GH_REPO_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None or match['name'] in ('.', '..') or match['owner'].startswith('-'):
        raise SpecError('invalid-github-repo')


def _require_check_names(names: tuple[str, ...]) -> None:
    if not names or len(names) > 100 or len(set(names)) != len(names):
        raise SpecError('invalid-required-checks')
    for name in names:
        if not name.strip() or len(name) > 200 or any(ord(ch) < 32 for ch in name):
            raise SpecError('invalid-required-checks')


def _validate_worktree_create(spec: WorktreeCreateSpec) -> None:
    _require_abs(spec.repo, 'repo')
    _require_abs(spec.common_dir, 'common_dir')
    _require_abs(spec.path, 'path')
    _require_branch(spec.branch, 'branch')
    _require_sha(spec.base_sha, 'base_sha')
    if spec.path in (spec.repo, spec.common_dir) or spec.path.startswith(spec.common_dir + os.sep):
        raise SpecError('worktree-path-collides')


def _validate_task_commit(spec: TaskCommitSpec) -> None:
    _require_abs(spec.repo, 'repo')
    _require_abs(spec.common_dir, 'common_dir')
    _require_abs(spec.worktree, 'worktree')
    _require_branch(spec.branch, 'branch')
    _require_sha(spec.expected_parent, 'expected_parent')
    _require_owned_paths(spec.owned_paths)
    _require_conventional(spec.message, 'message', max_len=20000, single_line=False)


def _validate_integrate(spec: IntegrateSpec) -> None:
    _require_abs(spec.repo, 'repo')
    _require_abs(spec.common_dir, 'common_dir')
    _require_abs(spec.integration_worktree, 'integration_worktree')
    if (spec.integration_worktree in (spec.repo, spec.common_dir)
            or spec.integration_worktree.startswith(spec.common_dir + os.sep)
            or spec.repo.startswith(spec.integration_worktree + os.sep)):
        raise SpecError('integration-worktree-collides')
    _require_branch(spec.target_branch, 'target_branch')
    _require_branch(spec.task_branch, 'task_branch')
    _require_sha(spec.expected_base, 'expected_base')
    _require_sha(spec.task_result, 'task_result')
    # expected_base == task_result is allowed: an already-contained result is an observed no-op.
    if spec.target_branch == spec.task_branch:
        raise SpecError('integrate-identity-collides')
    if spec.strategy not in INTEGRATE_STRATEGIES:
        raise SpecError('invalid-strategy')
    if spec.strategy == FAST_FORWARD:
        if spec.message != '':
            raise SpecError('fast-forward-takes-no-message')
        return
    _require_conventional(spec.message, 'message', max_len=20000, single_line=False)


def _validate_push(spec: PushSpec) -> None:
    _require_abs(spec.repo, 'repo')
    _require_abs(spec.common_dir, 'common_dir')
    if not _REMOTE_RE.fullmatch(spec.remote):
        raise SpecError('invalid-remote')
    _require_remote_url(spec.remote_url)
    _require_branch(spec.local_branch, 'local_branch')
    _require_branch(spec.remote_branch, 'remote_branch')
    _require_branch(spec.base_branch, 'base_branch')
    _require_sha(spec.expected_result, 'expected_result')
    _require_sha(spec.expected_base, 'expected_base')
    if spec.expected_remote_old is not None:
        _require_sha(spec.expected_remote_old, 'expected_remote_old')
        if spec.expected_remote_old == spec.expected_result:
            raise SpecError('push-identity-collides')


def _validate_pr_create(spec: PrCreateSpec) -> None:
    _require_github_repo(spec.github_repo)
    _require_branch(spec.base_branch, 'base_branch')
    _require_branch(spec.head_branch, 'head_branch')
    _require_sha(spec.expected_base_sha, 'expected_base_sha')
    _require_sha(spec.head_sha, 'head_sha')
    if spec.base_branch == spec.head_branch:
        raise SpecError('pr-identity-collides')
    _require_conventional(spec.title, 'title', max_len=256, single_line=True)
    _require_text(spec.body, 'body', max_len=60000, single_line=False)


def _validate_pr_merge(spec: PrMergeSpec) -> None:
    _require_github_repo(spec.github_repo)
    if not 0 < spec.number < 10**9:
        raise SpecError('invalid-pr-number')
    _require_branch(spec.base_branch, 'base_branch')
    _require_branch(spec.head_branch, 'head_branch')
    _require_sha(spec.expected_base_sha, 'expected_base_sha')
    _require_sha(spec.expected_head, 'expected_head')
    _require_check_names(spec.required_checks)
    if spec.method not in MERGE_METHODS:
        raise SpecError('invalid-merge-method')


def _validate_worktree_remove(spec: WorktreeRemoveSpec) -> None:
    _require_abs(spec.repo, 'repo')
    _require_abs(spec.common_dir, 'common_dir')
    _require_abs(spec.cleanup_root, 'cleanup_root')
    _require_abs(spec.path, 'path')
    _require_branch(spec.branch, 'branch')
    _require_sha(spec.expected_head, 'expected_head')
    if spec.cleanup_root == os.sep or not spec.path.startswith(spec.cleanup_root + os.sep):
        raise SpecError('path-outside-cleanup-scope')
    if spec.path == spec.repo or spec.repo.startswith(spec.path + os.sep):
        raise SpecError('path-is-repository')


_VALIDATORS: dict[str, Callable[[Any], None]] = {
    WORKTREE_CREATE: _validate_worktree_create,
    TASK_COMMIT: _validate_task_commit,
    INTEGRATE: _validate_integrate,
    PUSH: _validate_push,
    PR_CREATE: _validate_pr_create,
    PR_MERGE: _validate_pr_merge,
    WORKTREE_REMOVE: _validate_worktree_remove,
}


def _coerce(type_name: str, value: object, name: str, *, from_json: bool) -> object:
    if type_name == 'str' and isinstance(value, str):
        return value
    if type_name == 'str | None' and (value is None or isinstance(value, str)):
        return value
    if type_name == 'int' and isinstance(value, int) and not isinstance(value, bool):
        return value
    if type_name == 'tuple[str, ...]':
        allowed = (list, tuple) if from_json else (tuple,)
        if isinstance(value, allowed) and all(isinstance(item, str) for item in value):
            return tuple(value)
    raise SpecError(f'invalid-field-type:{name}')


def validate_spec(kind: str, spec: object) -> None:
    """Validate kind, spec type, field types and every identity in the spec (no I/O except
    path canonicalisation). Raises SpecError with a fixed code; never echoes input."""
    if kind not in SPEC_TYPES:
        raise SpecError('unknown-kind')
    if type(spec) is not SPEC_TYPES[kind]:
        raise SpecError('spec-type-mismatch')
    for item in dataclasses.fields(spec):
        _coerce(item.type, getattr(spec, item.name), item.name, from_json=False)
    _VALIDATORS[kind](spec)


def spec_from_mapping(kind: str, mapping: Mapping[str, Any]) -> Any:
    """Rebuild and validate a spec from a ledger row. Unknown or missing keys are refused,
    so a stored or worker-supplied extra field (for example 'checks_passed') cannot
    smuggle authority into an effect."""
    if kind not in SPEC_TYPES:
        raise SpecError('unknown-kind')
    if not isinstance(mapping, Mapping):
        raise SpecError('spec-not-a-mapping')
    cls = SPEC_TYPES[kind]
    names = [item.name for item in dataclasses.fields(cls)]
    unknown = sorted(set(mapping) - set(names))
    if unknown:
        raise SpecError('unknown-field')
    missing = [name for name in names if name not in mapping]
    if missing:
        raise SpecError('missing-field')
    values = {item.name: _coerce(item.type, mapping[item.name], item.name, from_json=True)
              for item in dataclasses.fields(cls)}
    spec = cls(**values)
    validate_spec(kind, spec)
    return spec


def spec_to_mapping(spec: object) -> dict[str, Any]:
    """JSON-ready mapping of a spec for the intent journal."""
    if type(spec) not in SPEC_TYPES.values():
        raise SpecError('spec-type-mismatch')
    return {key: list(value) if isinstance(value, tuple) else value
            for key, value in dataclasses.asdict(spec).items()}


def _require_executable(value: object, name: str) -> None:
    if not isinstance(value, str) or not os.path.isabs(value) or os.path.normpath(value) != value:
        raise ToolchainError(f'executable-not-absolute:{name}')
    if not os.path.isfile(value) or not os.access(value, os.X_OK):
        raise ToolchainError(f'executable-unusable:{name}')
    info = os.stat(value)
    if info.st_mode & stat.S_IWOTH:
        raise ToolchainError(f'executable-world-writable:{name}')
    # The shared process helper binds the same rule at prepare: owner root or us, no group write.
    if info.st_mode & stat.S_IWGRP or info.st_uid not in (0, os.geteuid()):
        raise ToolchainError(f'executable-unsafe:{name}')


def validate_toolchain(toolchain: Toolchain) -> None:
    if not isinstance(toolchain, Toolchain):
        raise ToolchainError('toolchain-type')
    _require_executable(toolchain.git, 'git')
    if toolchain.gh is not None:
        _require_executable(toolchain.gh, 'gh')
    timeout = toolchain.timeout_seconds
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        raise ToolchainError('invalid-timeout')
    limit = toolchain.output_limit
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1024 <= limit <= 1 << 20:
        raise ToolchainError('invalid-output-limit')
    grace = toolchain.term_grace_seconds
    if isinstance(grace, bool) or not isinstance(grace, (int, float)) or not 0 < grace <= MAX_TERM_GRACE_SECONDS:
        raise ToolchainError('invalid-term-grace')
    linger = toolchain.linger_seconds
    if isinstance(linger, bool) or not isinstance(linger, (int, float)) or not 0 <= linger <= MAX_LINGER_SECONDS:
        raise ToolchainError('invalid-linger')
    env = toolchain.environment
    if env is not None and (not isinstance(env, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in env.items())):
        raise ToolchainError('invalid-environment')
    _require_evidence_root(toolchain.evidence_root)


def _require_evidence_root(value: object) -> None:
    """Full evidence needs a real owner-private root; anything else is refused, never ignored."""
    if value is None:
        raise ToolchainError('evidence-root-missing')
    if not _is_canonical_abs(value):
        raise ToolchainError('evidence-root-not-canonical')
    try:
        info = os.lstat(value)
    except OSError:
        raise ToolchainError('evidence-root-missing') from None
    if not stat.S_ISDIR(info.st_mode):
        raise ToolchainError('evidence-root-not-directory')
    if info.st_uid != os.geteuid():
        raise ToolchainError('evidence-root-not-owned')
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ToolchainError('evidence-root-not-private')


_PATH_FIELDS = frozenset({'repo', 'common_dir', 'worktree', 'integration_worktree', 'path',
                          'cleanup_root', 'remote_url'})


def _require_evidence_outside(root: str, spec: object) -> None:
    """Raw logs live outside every repository/worktree/remote path the spec names."""
    for item in dataclasses.fields(spec):
        value = getattr(spec, item.name)
        if item.name not in _PATH_FIELDS or not isinstance(value, str) or not value.startswith(os.sep):
            continue
        if root == value or root.startswith(value + os.sep):
            raise ToolchainError('evidence-root-inside-repository')


def _authorized(kinds: Iterable[str]) -> frozenset[str]:
    if isinstance(kinds, (str, bytes)):
        raise ToolchainError('invalid-authorized-kinds')
    granted = frozenset(kinds)
    if not granted <= set(KINDS):
        raise ToolchainError('invalid-authorized-kinds')
    return granted


# --------------------------------------------------------------------------- subprocess

# Config-file selectors keep no more authority than the owner's own config; SSH/askpass
# variables are the owner's inherited auth. Every other GIT_* selector is dropped.
_GIT_ENV_KEEP = frozenset({'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_NOSYSTEM',
                           'GIT_SSH', 'GIT_SSH_COMMAND', 'GIT_SSH_VARIANT', 'GIT_ASKPASS'})
_ENV_DROP = frozenset({'GH_REPO', 'GH_HOST', 'GH_DEBUG', 'GH_PAGER', 'GH_EDITOR', 'GH_BROWSER',
                       'PAGER', 'EDITOR', 'VISUAL', 'BROWSER'})
_ENV_FIXED = {'GIT_TERMINAL_PROMPT': '0', 'GIT_EDITOR': 'false', 'GH_PROMPT_DISABLED': '1',
              'GH_NO_UPDATE_NOTIFIER': '1', 'GH_SPINNER_DISABLED': '1', 'NO_COLOR': '1', 'LC_ALL': 'C'}
_GIT_FIXED = ('--no-replace-objects', '--no-optional-locks', '--literal-pathspecs',
              '-c', 'core.fsmonitor=false', '-c', 'protocol.ext.allow=never',
              '-c', 'protocol.fd.allow=never')
_REDACTIONS = (
    (re.compile(r'(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@'), r'\1***@'),
    (re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})'), '***'),
    (re.compile(r'(?i)\b(authorization|proxy-authorization)\s*:\s*\S+(?:[ \t]+\S+)?'), r'\1: ***'),
    (re.compile(r'(?i)\b(token|password|passwd|secret|api[_-]?key)\s*[=:]\s*\S+'), r'\1=***'),
)


def _redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _child_env(toolchain: Toolchain) -> dict[str, str]:
    base = os.environ if toolchain.environment is None else toolchain.environment
    env = {key: value for key, value in base.items()
           if (not key.startswith('GIT_') or key in _GIT_ENV_KEEP) and key not in _ENV_DROP}
    env.update(_ENV_FIXED)
    return env


class _Observed(Exception):
    """An observation verdict reached while reading (binding mismatch or unreadable state)."""

    def __init__(self, state: str, reason: str, evidence: Mapping[str, Any] | None = None):
        super().__init__(reason)
        self.state = state
        self.reason = reason
        self.evidence = dict(evidence or {})


class _Refuse(Exception):
    """A pre-mutation stop: precondition violated (refused) or evidence missing (incomplete)."""

    def __init__(self, status: str, reason: str, details: Mapping[str, Any] | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.details = dict(details or {})


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='microseconds')


_PRIVATE_CREATE = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
                   | getattr(os, 'O_CLOEXEC', 0))
_PRIVATE_READ = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)


def _open_private(path: str) -> int:
    return os.open(path, _PRIVATE_CREATE, 0o600)


def _write_private(path: str, data: bytes) -> str:
    """Create ``path`` exclusively (0600, never through a symlink), fsync it, return sha256."""
    fd = _open_private(path)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    return hashlib.sha256(data).hexdigest()


def _write_json(path: str, payload: Mapping[str, Any]) -> None:
    _write_private(path, json.dumps(payload, sort_keys=True, indent=2).encode('utf-8') + b'\n')


def _digest_log(path: str, *, keep_tail: int | None) -> tuple[bytes, int, str]:
    """(kept bytes, size, sha256) of a finished raw log; keeps every byte when keep_tail is None."""
    digest = hashlib.sha256()
    kept = bytearray()
    size = 0
    with os.fdopen(os.open(path, _PRIVATE_READ), 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 16), b''):
            digest.update(chunk)
            size += len(chunk)
            kept += chunk
            if keep_tail is not None and len(kept) > keep_tail:
                del kept[:-keep_tail]
    return bytes(kept), size, digest.hexdigest()


_CALL_DIR_RE = re.compile(r'\d{8}T\d{6}Z-(?:observe|execute)-[a-z.]+-\d+-[0-9a-f]{16}')
_COMMAND_ID_RE = re.compile(r'(\d{4})-(mutation|read)')
_SETTLED_STATES = frozenset({'exited', 'lost', 'not-launched', 'finalized'})
_FINALIZABLE_STATES = frozenset({'exited', 'lost', 'not-launched'})
_NOTHING_RAN = frozenset({'not-launched', 'launch-failed'})
_SETTLE_MARGIN_SECONDS = 15.0
_POLL_MIN_SECONDS = 0.02
_POLL_MAX_SECONDS = 0.25


class _Evidence:
    """Owner-private, create-exclusive evidence directory for one observe/execute call."""

    def __init__(self, toolchain: Toolchain, operation: str, kind: str, spec: Any,
                 prior_unclean: tuple[Mapping[str, Any], ...]):
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        self.path = os.path.join(toolchain.evidence_root,
                                 f'{stamp}-{operation}-{kind}-{os.getpid()}-{secrets.token_hex(8)}')
        # The helper's attempts root and the neutral cwd are siblings, so they never overlap.
        self.commands_root = os.path.join(self.path, 'commands')
        self.neutral_cwd = os.path.join(self.path, 'cwd')
        self.commands = 0
        self.inputs = 0
        self.scratch = 0
        try:
            os.mkdir(self.path, 0o700)
            os.mkdir(self.commands_root, 0o700)
            os.mkdir(self.neutral_cwd, 0o700)
            _write_json(os.path.join(self.path, 'attempt.json'), {
                'operation': operation, 'kind': kind, 'spec': spec_to_mapping(spec), 'pid': os.getpid(),
                'started_at': _utc_now(), 'git': toolchain.git, 'gh': toolchain.gh,
                'timeout_seconds': toolchain.timeout_seconds,
                'term_grace_seconds': toolchain.term_grace_seconds,
                'linger_seconds': toolchain.linger_seconds,
                'commands_root': self.commands_root, 'neutral_cwd': self.neutral_cwd,
                'prior_unclean_mutations': list(prior_unclean)})
        except OSError as err:
            raise ToolchainError('evidence-root-unwritable') from err

    def input_file(self, name: str, data: bytes) -> str:
        """Persist one literal command input (message/body file) and return its path."""
        self.inputs += 1
        path = os.path.join(self.path, f'input-{self.inputs:04d}-{name}')
        try:
            _write_private(path, data)
        except OSError:
            raise _Observed(UNKNOWN, 'command-evidence-unwritable') from None
        return path

    def scratch_dir(self, name: str) -> str:
        """Create one private 0700 working directory inside this attempt directory."""
        self.scratch += 1
        path = os.path.join(self.path, f'scratch-{self.scratch:04d}-{name}')
        try:
            os.mkdir(path, 0o700)
        except OSError:
            raise _Observed(UNKNOWN, 'command-evidence-unwritable') from None
        return path

    def remove_scratch(self, path: str) -> None:
        """Remove one scratch directory this attempt created, and nothing else."""
        if os.path.dirname(path) != self.path or not os.path.basename(path).startswith('scratch-'):
            raise _Observed(UNKNOWN, 'scratch-cleanup-refused')
        try:
            if not stat.S_ISDIR(os.lstat(path).st_mode):
                raise _Observed(UNKNOWN, 'scratch-cleanup-refused')
            shutil.rmtree(path)
        except OSError:
            raise _Observed(UNKNOWN, 'scratch-cleanup-failed') from None

    def next_command_id(self, mutation: bool) -> str:
        """A NEW exclusive helper attempt id; the suffix records the mutation flag durably."""
        self.commands += 1
        return f'{self.commands:04d}-{"mutation" if mutation else "read"}'

    def write_record(self, name: str, payload: Mapping[str, Any]) -> None:
        _write_json(os.path.join(self.path, name), payload)


@dataclass
class _Run:
    """Bookkeeping for one command while it is driven through the process helper."""

    argv: tuple[str, ...]
    cwd: str
    mutation: bool
    started: float
    started_at: str
    attempt_id: str | None = None
    attempt: str | None = None
    pid: int | None = None
    spawn_error: str | None = None
    cancelled: bool = False
    watchdog_stop: bool = False
    stop_status: str | None = None
    process_state: str | None = None
    identity_status: str | None = None
    process_reason: str | None = None
    lifecycle: dict[str, Any] | None = None
    evidence_error: str | None = None


def _signal_number(name: object) -> int | None:
    member = signal.Signals.__members__.get(name) if isinstance(name, str) else None
    return None if member is None else int(member)


def _lifecycle_terminal(record: Mapping[str, Any]) -> bool:
    """The owned group is proven gone (as far as the helper can observe): nothing this
    command started can still act."""
    if record['termination'] == 'not-launched':
        return True
    return record['groupEmpty'] is True and record['unresolvedDescendants'] == 0


def _lifecycle_clean(record: Mapping[str, Any]) -> bool:
    """Terminal AND ended by itself (any exit code) or never ran: no timeout, STOP, forced
    cleanup, lingering or escaped descendants, an observed group and both raw logs."""
    if not _lifecycle_terminal(record):
        return False
    if record['termination'] in _NOTHING_RAN:
        return True
    logs = record['logs']
    return (record['termination'] == 'exited' and not record['forced'] and not record['signalsSent']
            and not record['lingering'] and record['escapedDescendants'] == 0
            and record['groupObservation'] == 'ok'
            and logs['stdout'] is not None and logs['stderr'] is not None)


def _verified_log(attempt: str, ref: Mapping[str, Any] | None,
                  keep_tail: int | None) -> tuple[bytes, int, str]:
    """Bytes of one helper raw log, re-hashed against its finalized lifecycle reference."""
    if ref is None:
        return b'', 0, ''
    if os.path.dirname(ref['path']) != attempt:
        raise ValueError('log-outside-attempt')
    kept, size, digest = _digest_log(ref['path'], keep_tail=keep_tail)
    if size != ref['size'] or digest != ref['sha256']:
        raise ValueError('log-mismatch')
    return kept, size, digest


class _Call:
    """One observe/execute invocation. Every command is a NEW owned attempt of the shared
    process helper; this class only drives it (prepare, spawn, claim, release, poll, STOP,
    finalize) and turns the finalized lifecycle record into a ``CommandRecord``."""

    def __init__(self, toolchain: Toolchain, cancel: Cancellation | None, evidence: _Evidence,
                 prior_unclean: tuple[Mapping[str, Any], ...] = ()):
        self.toolchain = toolchain
        self.cancel = cancel
        self.evidence = evidence
        self.prior_unclean = prior_unclean
        self.env = _child_env(toolchain)
        self.records: list[CommandRecord] = []
        self.mutation_started = False
        self.evidence_complete = True
        self.git_checked = False

    def git(self, cwd: str, *args: str, stdin: bytes | None = None,
            mutation: bool = False) -> tuple[CommandRecord, bytes]:
        return self.run((self.toolchain.git, *_GIT_FIXED, '-C', cwd, *args), cwd, stdin, mutation=mutation)

    def gh(self, *args: str, mutation: bool = False) -> tuple[CommandRecord, bytes]:
        if self.toolchain.gh is None:
            raise _Observed(UNKNOWN, 'gh-not-configured')
        return self.run((self.toolchain.gh, *args), self.evidence.neutral_cwd, None, mutation=mutation)

    def cancelled(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()

    def run(self, argv: tuple[str, ...], cwd: str, stdin: bytes | None, *,
            mutation: bool = False) -> tuple[CommandRecord, bytes]:
        """Run one literal argv as a NEW owned attempt; return only once it is settled."""
        run = _Run(argv=tuple(argv), cwd=cwd, mutation=mutation, started=time.monotonic(),
                   started_at=_utc_now())
        if self.cancelled():
            run.cancelled = True
            return self._finish(run)
        run.attempt_id = self.evidence.next_command_id(mutation)
        command = _process.CommandSpec(argv=run.argv, cwd=cwd, stdin=b'' if stdin is None else stdin,
                                       attempt_id=run.attempt_id)
        try:
            run.attempt = str(_process.prepare(
                self.evidence.commands_root, command, self.toolchain.timeout_seconds,
                term_grace_seconds=self.toolchain.term_grace_seconds,
                linger_seconds=self.toolchain.linger_seconds))
        except _process.ProcessError as err:
            run.spawn_error = f'prepare:{err.code}'
            return self._finish(run)
        except OSError:
            run.spawn_error = 'prepare:io-error'
            return self._finish(run)
        owned = self._launch(run)
        self._await_settled(run, owned)
        self._finalize(run, owned)
        return self._finish(run)

    def _launch(self, run: _Run) -> Any:
        """Spawn the anchored bootstrap, persist its identity, then release (unless cancelled)."""
        try:
            pending = _process.spawn(run.attempt, environment=self.env)
        except _process.ProcessError as err:
            run.spawn_error = f'spawn:{err.code}'
            return None
        except OSError:
            run.spawn_error = 'spawn:io-error'
            return None
        identity = pending.identity
        run.pid = identity['pid']
        try:
            self.evidence.write_record(f'claim-{run.attempt_id}.json', {
                'attempt': run.attempt, 'identity': identity, 'mutation': run.mutation,
                'claimed_at': _utc_now()})
        except OSError:
            pending.abort()
            run.spawn_error = 'claim-unwritable'
            return None
        if self.cancelled():
            pending.abort()
            run.cancelled = True
            return None
        if run.mutation:
            self.mutation_started = True  # conservative: set before the release message is sent
        try:
            return pending.release()
        except _process.ProcessError as err:
            pending.abort()
            run.spawn_error = f'release:{err.code}'
            return None

    def _await_settled(self, run: _Run, owned: Any) -> None:
        """Poll until the attempt settles. Cancel (or the overall bound) publishes STOP, which
        only a positively owned bootstrap acts on; nothing is signalled from here."""
        toolchain = self.toolchain
        drain = toolchain.term_grace_seconds + toolchain.linger_seconds + _SETTLE_MARGIN_SECONDS
        deadline = time.monotonic() + toolchain.timeout_seconds + drain
        stop_deadline: float | None = None
        delay = _POLL_MIN_SECONDS
        while True:
            recovery = self._poll(run, owned)
            run.process_state = recovery.state
            run.identity_status = recovery.identity_status
            run.process_reason = recovery.reason
            if recovery.state in _SETTLED_STATES or recovery.state in ('prepared', 'corrupt'):
                return
            now = time.monotonic()
            if stop_deadline is None and (self.cancelled() or now >= deadline):
                run.cancelled = self.cancelled()
                run.watchdog_stop = not run.cancelled
                run.stop_status = self._request_stop(run, owned)
                stop_deadline = now + drain
            elif stop_deadline is not None and now >= stop_deadline:
                return
            time.sleep(delay)
            delay = min(delay * 2, _POLL_MAX_SECONDS)

    @staticmethod
    def _poll(run: _Run, owned: Any) -> Any:
        try:
            return owned.poll() if owned is not None else _process.recover(run.attempt)
        except _process.ProcessError as err:
            return _process.Recovery('corrupt', False, None, err.code)
        except OSError:
            return _process.Recovery('unknown', False, None, 'io-error')

    @staticmethod
    def _request_stop(run: _Run, owned: Any) -> str:
        try:
            return owned.request_stop() if owned is not None else _process.request_stop(run.attempt)
        except _process.ProcessError as err:
            return f'error:{err.code}'
        except OSError:
            return 'error:io-error'

    @staticmethod
    def _finalize(run: _Run, owned: Any) -> None:
        """Write (or read back) the single lifecycle record of a settled attempt."""
        if run.process_state not in _SETTLED_STATES:
            return
        if run.process_state in _FINALIZABLE_STATES:
            try:
                run.lifecycle = owned.finalize() if owned is not None else _process.finalize(run.attempt)
                return
            except _process.ProcessError as err:
                if err.code != 'already-finalized':
                    run.evidence_error = f'finalize:{err.code}'
                    return
            except OSError:
                run.evidence_error = 'finalize:io-error'
                return
        try:
            status = _process.read_status(run.attempt)
        except (_process.ProcessError, OSError):
            run.evidence_error = 'lifecycle-unreadable'
            return
        if status['state'] == 'finalized' and isinstance(status['record'], dict):
            run.lifecycle = status['record']
        else:
            run.evidence_error = 'lifecycle-unreadable'

    @staticmethod
    def _lifecycle_fields(run: _Run, lifecycle: Mapping[str, Any]) -> dict[str, Any]:
        termination = lifecycle['termination']
        return dict(termination=termination, exit_code=lifecycle['exitCode'],
                    signal=_signal_number(lifecycle['signal']), forced=lifecycle['forced'],
                    lingering=lifecycle['lingering'], lifecycle_clean=_lifecycle_clean(lifecycle),
                    lifecycle_reasons=tuple(lifecycle['reasons']),
                    timed_out=termination == 'timeout' or (termination == 'stopped' and run.watchdog_stop),
                    cancelled=run.cancelled and termination in ('stopped', 'not-launched'))

    def _finish(self, run: _Run) -> tuple[CommandRecord, bytes]:
        lifecycle = run.lifecycle
        unsettled = run.attempt is not None and lifecycle is None and run.process_state != 'prepared'
        fields: dict[str, Any] = dict(
            argv=run.argv, cwd=run.cwd, mutation=run.mutation, exit_code=None, signal=None,
            timed_out=run.watchdog_stop, cancelled=run.cancelled,
            duration_ms=int((time.monotonic() - run.started) * 1000), stdout_tail='', stderr_tail='',
            spawn_error=run.spawn_error, evidence_dir=run.attempt or '', pid=run.pid,
            started_at=run.started_at, ended_at=_utc_now(), process_state=run.process_state,
            identity_status=run.identity_status, process_reason=run.process_reason,
            stop_status=run.stop_status, evidence_error=run.evidence_error)
        stdout = b''
        if lifecycle is not None:
            fields.update(self._lifecycle_fields(run, lifecycle))
            try:
                stdout, out_size, out_sha = _verified_log(run.attempt, lifecycle['logs']['stdout'], None)
                stderr, err_size, err_sha = _verified_log(run.attempt, lifecycle['logs']['stderr'],
                                                          4 * self.toolchain.output_limit)
                fields.update(stdout_tail=self._tail(stdout), stderr_tail=self._tail(stderr),
                              stdout_bytes=out_size, stderr_bytes=err_size,
                              stdout_sha256=out_sha, stderr_sha256=err_sha)
            except (OSError, ValueError):
                stdout = b''
                fields['evidence_error'] = 'command-log-unverifiable'
        elif unsettled and fields['evidence_error'] is None:
            fields['evidence_error'] = 'command-unsettled'
        record = CommandRecord(**fields)
        if run.attempt_id is not None:
            receipt = {key: value for key, value in record.as_dict().items()
                       if key not in ('stdout_tail', 'stderr_tail')}
            try:
                self.evidence.write_record(f'receipt-{run.attempt_id}.json', receipt)
            except OSError:
                record = dataclasses.replace(record, evidence_error='command-receipt-unwritable')
        self.records.append(record)
        if record.evidence_error is not None:
            self.evidence_complete = False
            raise _Observed(UNKNOWN, 'command-unsettled' if unsettled else 'command-evidence-incomplete')
        return record, stdout

    def _tail(self, data: bytes) -> str:
        return _redact(data.decode('utf-8', 'replace'))[-self.toolchain.output_limit:]


def _mutate_git(call: _Call, cwd: str, *args: str, stdin: bytes | None = None) -> CommandRecord:
    record, _ = call.git(cwd, *args, stdin=stdin, mutation=True)
    return record


def _mutate_gh(call: _Call, *args: str) -> CommandRecord:
    record, _ = call.gh(*args, mutation=True)
    return record


def _status_of(record: CommandRecord, label: str) -> tuple[str, str]:
    if record.cancelled:
        return CANCELLED, f'{label}-cancelled'
    if record.timed_out:
        return TIMED_OUT, f'{label}-timed-out'
    if record.spawn_error is not None:
        return FAILED, f'{label}-spawn-error'
    if record.termination == 'launch-failed':
        return FAILED, f'{label}-launch-failed'
    if not record.lifecycle_clean:
        # Forced cleanup, lingering/escaped descendants, a lost supervisor or an unobserved
        # group: never success and never conclusive absence (settle holds it as unknown).
        return INCOMPLETE, f'{label}-lifecycle-unclean'
    if record.exit_code is None:
        return FAILED, f'{label}-signalled'
    if record.exit_code != 0:
        return FAILED, f'{label}-exit-{record.exit_code}'
    return COMPLETED, f'{label}-exited-0'


# --------------------------------------------------------------------------- git reads

def _text(data: bytes) -> str:
    return data.decode('utf-8', 'surrogateescape').strip()


def _git_read(call: _Call, cwd: str, *args: str, stdin: bytes | None = None,
              accept: tuple[int, ...] = (0,)) -> tuple[int, bytes]:
    record, out = call.git(cwd, *args, stdin=stdin)
    if (record.exit_code is None or record.exit_code not in accept or record.timed_out or record.cancelled
            or not record.lifecycle_clean):
        raise _Observed(UNKNOWN, f'git-{args[0]}-unobservable')
    return record.exit_code, out


def _require_git_version(call: _Call) -> None:
    if call.git_checked:
        return
    _, out = _git_read(call, call.evidence.neutral_cwd, 'version')
    match = re.search(r'git version (\d+)\.(\d+)', _text(out))
    if match is None or (int(match[1]), int(match[2])) < MIN_GIT_VERSION:
        raise _Observed(UNKNOWN, 'git-version-unsupported')
    call.git_checked = True


def _bind_repo(call: _Call, repo: str, common_dir: str) -> None:
    _require_git_version(call)
    if not os.path.isdir(repo):
        raise _Observed(CONFLICT, 'repo-missing')
    _, out = _git_read(call, repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if os.path.realpath(_text(out)) != common_dir:
        raise _Observed(CONFLICT, 'repo-binding-mismatch')


def _bind_worktree(call: _Call, worktree: str, common_dir: str) -> None:
    if not os.path.isdir(worktree):
        raise _Observed(CONFLICT, 'worktree-missing')
    _, out = _git_read(call, worktree, 'rev-parse', '--path-format=absolute',
                       '--git-common-dir', '--show-toplevel')
    lines = _text(out).splitlines()
    if len(lines) != 2 or os.path.realpath(lines[0]) != common_dir or os.path.realpath(lines[1]) != worktree:
        raise _Observed(CONFLICT, 'worktree-binding-mismatch')


def _resolve_commit(call: _Call, cwd: str, rev: str) -> str | None:
    code, out = _git_read(call, cwd, 'rev-parse', '--verify', '--quiet', f'{rev}^{{commit}}', accept=(0, 1))
    value = _text(out)
    return value if code == 0 and _SHA_RE.fullmatch(value) else None


def _branch_tip(call: _Call, repo: str, branch: str) -> str | None:
    return _resolve_commit(call, repo, f'refs/heads/{branch}')


def _is_ancestor(call: _Call, repo: str, ancestor: str, descendant: str) -> bool:
    code, _ = _git_read(call, repo, 'merge-base', '--is-ancestor', ancestor, descendant, accept=(0, 1))
    return code == 0


def _parents(call: _Call, repo: str, sha: str) -> list[str]:
    _, out = _git_read(call, repo, 'rev-list', '--parents', '-n', '1', sha)
    return _text(out).split()[1:]


def _commit_message(call: _Call, repo: str, sha: str) -> str:
    _, out = _git_read(call, repo, 'cat-file', 'commit', sha)
    return out.split(b'\n\n', 1)[1].decode('utf-8', 'replace') if b'\n\n' in out else ''


def _diff_paths(call: _Call, repo: str, old: str, new: str) -> list[str]:
    _, out = _git_read(call, repo, 'diff-tree', '--no-commit-id', '--name-only', '-r', '-z',
                       '--no-renames', old, new)
    return [p.decode('utf-8', 'surrogateescape') for p in out.split(b'\0') if p]


def _worktree_entries(call: _Call, repo: str) -> list[dict[str, Any]]:
    _, out = _git_read(call, repo, 'worktree', 'list', '--porcelain', '-z')
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in out.split(b'\0'):
        if not item:
            if current is not None:
                entries.append(current)
                current = None
            continue
        key, _, value = item.partition(b' ')
        text = value.decode('utf-8', 'surrogateescape')
        if key == b'worktree':
            if current is not None:
                entries.append(current)
            current = {'path': text}
        elif current is not None:
            current[key.decode('ascii', 'replace')] = text if value else True
    if current is not None:
        entries.append(current)
    return entries


def _find_worktree(entries: list[dict[str, Any]], path: str) -> dict[str, Any] | None:
    for entry in entries:
        if os.path.realpath(entry['path']) == path:
            return entry
    return None


class _StatusEntry(NamedTuple):
    tag: str
    xy: str
    submodule: bool
    path: str


def _status(call: _Call, worktree: str, *, ignored: bool = False) -> list[_StatusEntry]:
    args = ['status', '--porcelain=v2', '-z', '--untracked-files=all', '--no-renames',
            '--ignore-submodules=none']
    if ignored:
        args.append('--ignored')
    _, out = _git_read(call, worktree, *args)
    entries: list[_StatusEntry] = []
    for item in out.split(b'\0'):
        if not item:
            continue
        tag = item[:1].decode('ascii', 'replace')
        if tag in ('?', '!'):
            entries.append(_StatusEntry(tag, tag * 2, False, item[2:].decode('utf-8', 'surrogateescape')))
            continue
        splits = {'1': 8, 'u': 10}.get(tag)
        if splits is None:
            raise _Observed(UNKNOWN, 'status-unparseable')  # renames are disabled above
        parts = item.split(b' ', splits)
        if len(parts) != splits + 1:
            raise _Observed(UNKNOWN, 'status-unparseable')
        entries.append(_StatusEntry(tag, parts[1].decode('ascii', 'replace'),
                                    parts[2].startswith(b'S'),
                                    parts[splits].decode('utf-8', 'surrogateescape')))
    return entries


def _operations_in_progress(call: _Call, worktree: str) -> list[str]:
    names = ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'BISECT_LOG')
    args = ['rev-parse', '--path-format=absolute']
    for name in names:
        args += ['--git-path', name]
    _, out = _git_read(call, worktree, *args)
    paths = _text(out).splitlines()
    if len(paths) != len(names):
        raise _Observed(UNKNOWN, 'git-path-unobservable')
    return [name for name, path in zip(names, paths) if os.path.lexists(os.path.join(worktree, path))]


def _is_owned(path: str, owned: tuple[str, ...]) -> bool:
    return any(path == entry or (entry.endswith('/') and path.startswith(entry)) for entry in owned)


def _require_not_applied(call: _Call, spec: Any,
                         observer: Callable[[_Call, Any], tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    state, reason, evidence = observer(call, spec)
    if state == NOT_APPLIED and call.prior_unclean:
        # An earlier mutation for this intent may have applied it; absence is not proven.
        raise _Refuse(REFUSED, 'unknown:prior-mutation-unclean',
                      {'observed_state': UNKNOWN, **evidence, 'prior_commands': list(call.prior_unclean)})
    if state == NOT_APPLIED:
        return evidence
    code = 'already-applied' if state == CONFIRMED else f'{state}:{reason}'
    raise _Refuse(REFUSED, code, {'observed_state': state, **evidence})


# --------------------------------------------------------------------------- worktree.create

def _worktree_intact(call: _Call, spec: WorktreeCreateSpec, entries: list[dict[str, Any]],
                     entry: dict[str, Any], tip: str) -> tuple[str, str] | None:
    """None only for an existing, usable linked worktree whose non-prunable registration,
    directory, top level, common dir, branch and HEAD are bound exactly to this spec. A
    missing, replaced or prunable registration is reported for the owner; it is never
    pruned, recreated or force-cleaned here."""
    if entry is entries[0]:
        return CONFLICT, 'path-is-main-worktree'
    if 'prunable' in entry:
        return CONFLICT, 'worktree-registration-prunable'
    try:
        info = os.lstat(spec.path)
    except FileNotFoundError:
        return CONFLICT, 'worktree-path-missing'
    except OSError:
        return UNKNOWN, 'worktree-path-unreadable'
    if not stat.S_ISDIR(info.st_mode):
        return CONFLICT, 'worktree-path-not-directory'
    _bind_worktree(call, spec.path, spec.common_dir)
    code, out = _git_read(call, spec.path, 'symbolic-ref', '--quiet', 'HEAD', accept=(0, 1))
    if code != 0 or _text(out) != f'refs/heads/{spec.branch}':
        return CONFLICT, 'worktree-head-not-on-branch'
    if entry.get('HEAD') != tip or _resolve_commit(call, spec.path, 'HEAD') != tip:
        return CONFLICT, 'worktree-head-mismatch'
    return None


def _observe_worktree_create(call: _Call, spec: WorktreeCreateSpec) -> tuple[str, str, dict[str, Any]]:
    _bind_repo(call, spec.repo, spec.common_dir)
    tip = _branch_tip(call, spec.repo, spec.branch)
    entries = _worktree_entries(call, spec.repo)
    entry = _find_worktree(entries, spec.path)
    evidence: dict[str, Any] = {'branch_tip': tip, 'worktree_registered': entry is not None}
    if entry is None:
        if tip is not None:
            return CONFLICT, 'branch-exists', evidence
        if os.path.lexists(spec.path):
            return CONFLICT, 'path-exists', evidence
        return NOT_APPLIED, 'absent', evidence
    if tip is None or entry.get('branch') != f'refs/heads/{spec.branch}':
        return CONFLICT, 'path-registered-to-other-branch', evidence
    evidence.update(worktree_prunable='prunable' in entry, worktree_locked='locked' in entry)
    broken = _worktree_intact(call, spec, entries, entry, tip)
    if broken is not None:
        return (*broken, evidence)
    if tip == spec.base_sha:
        return CONFIRMED, 'created-at-base', evidence
    if _is_ancestor(call, spec.repo, spec.base_sha, tip):
        return CONFIRMED, 'created-and-advanced', evidence
    return CONFLICT, 'branch-not-based-on-base', evidence


def _execute_worktree_create(call: _Call, spec: WorktreeCreateSpec) -> tuple[str, str, dict[str, Any]]:
    _require_not_applied(call, spec, _observe_worktree_create)
    if _resolve_commit(call, spec.repo, spec.base_sha) != spec.base_sha:
        raise _Refuse(REFUSED, 'base-not-a-commit')
    record = _mutate_git(call, spec.repo, 'worktree', 'add', '-b', spec.branch, spec.path, spec.base_sha)
    return (*_status_of(record, 'worktree-add'), {})


# --------------------------------------------------------------------------- task.commit

def _observe_task_commit(call: _Call, spec: TaskCommitSpec) -> tuple[str, str, dict[str, Any]]:
    _bind_repo(call, spec.repo, spec.common_dir)
    _bind_worktree(call, spec.worktree, spec.common_dir)
    tip = _branch_tip(call, spec.repo, spec.branch)
    evidence: dict[str, Any] = {'branch_tip': tip}
    if tip is None:
        return CONFLICT, 'branch-missing', evidence
    if tip == spec.expected_parent:
        return NOT_APPLIED, 'branch-at-parent', evidence
    if _parents(call, spec.repo, tip) != [spec.expected_parent]:
        return CONFLICT, 'branch-moved-unexpectedly', evidence
    message = _commit_message(call, spec.repo, tip)
    changed = _diff_paths(call, spec.repo, spec.expected_parent, tip)
    evidence.update(result_sha=tip, changed_paths=changed[:MAX_LISTED])
    if message.split('\n', 1)[0] != spec.message.split('\n', 1)[0]:
        return CONFLICT, 'commit-subject-mismatch', evidence
    if _ATTRIBUTION_RE.search(message):
        return CONFLICT, 'ai-attribution-in-commit', evidence
    foreign = [path for path in changed if not _is_owned(path, spec.owned_paths)]
    if foreign:
        evidence['foreign_paths'] = foreign[:MAX_LISTED]
        return CONFLICT, 'commit-touches-foreign-paths', evidence
    return CONFIRMED, 'committed', evidence


def _execute_task_commit(call: _Call, spec: TaskCommitSpec) -> tuple[str, str, dict[str, Any]]:
    _require_not_applied(call, spec, _observe_task_commit)
    code, out = _git_read(call, spec.worktree, 'symbolic-ref', '--quiet', 'HEAD', accept=(0, 1))
    if code != 0 or _text(out) != f'refs/heads/{spec.branch}':
        raise _Refuse(REFUSED, 'worktree-not-on-branch')
    if _resolve_commit(call, spec.worktree, 'HEAD') != spec.expected_parent:
        raise _Refuse(REFUSED, 'worktree-head-mismatch')
    busy = _operations_in_progress(call, spec.worktree)
    if busy:
        raise _Refuse(REFUSED, 'operation-in-progress', {'operations': busy})
    entries = _status(call, spec.worktree)
    if any(entry.tag == 'u' for entry in entries):
        raise _Refuse(REFUSED, 'unmerged-paths')
    if any(entry.submodule for entry in entries):
        raise _Refuse(REFUSED, 'submodule-change-unsupported')
    changed = sorted({entry.path for entry in entries})
    if not changed:
        raise _Refuse(REFUSED, 'nothing-to-commit')
    foreign = [path for path in changed if not _is_owned(path, spec.owned_paths)]
    if foreign:
        raise _Refuse(REFUSED, 'foreign-changes', {'foreign_paths': foreign[:MAX_LISTED],
                                                     'foreign_count': len(foreign)})
    manifest = b''.join(path.encode('utf-8', 'surrogateescape') + b'\0' for path in changed)
    record = _mutate_git(call, spec.worktree, 'add', '--all', '--pathspec-from-file=-',
                         '--pathspec-file-nul', stdin=manifest)
    if not record.succeeded:
        return (*_status_of(record, 'stage'), {})
    _, staged_raw = _git_read(call, spec.worktree, 'diff-index', '--cached', '--name-only', '-z',
                              '--no-renames', 'HEAD')
    staged = sorted(p.decode('utf-8', 'surrogateescape') for p in staged_raw.split(b'\0') if p)
    after = _status(call, spec.worktree)
    unstaged = sorted(entry.path for entry in after if entry.tag != '1' or entry.xy[1:] != '.')
    if not staged or not set(staged) <= set(changed) or unstaged:
        return FAILED, 'staged-set-mismatch', {'staged_paths': staged[:MAX_LISTED],
                                               'unstaged_paths': unstaged[:MAX_LISTED]}
    message = spec.message if spec.message.endswith('\n') else spec.message + '\n'
    message_path = call.evidence.input_file('commit-message.txt', message.encode('utf-8'))
    record = _mutate_git(call, spec.worktree, 'commit', '--quiet', '-F', message_path)
    return (*_status_of(record, 'commit'), {'staged_paths': staged[:MAX_LISTED]})


# --------------------------------------------------------------------------- integrate

def _tree_of(call: _Call, repo: str, sha: str) -> str:
    _, out = _git_read(call, repo, 'rev-parse', '--verify', f'{sha}^{{tree}}')
    tree = _text(out)
    if not _SHA_RE.fullmatch(tree):
        raise _Observed(UNKNOWN, 'tree-unobservable')
    return tree


_MERGE_COMMAND_KEY_RE = re.compile(r'merge\..+\.driver|filter\..+\.(?:clean|smudge|process)|merge\.renormalize',
                                   re.S)


def _require_builtin_merge(call: _Call, repo: str) -> None:
    """Hold unless the merge prediction is provably pure built-in Git. Effective config (every
    scope Git reads) that names a command-running merge driver or filter, or sets
    renormalisation, could make merge-tree run configured commands, which is not a read-only
    observation. First release: such repositories are held for merge-commit integrate; the
    config is reported, never changed."""
    _, out = _git_read(call, repo, 'config', '--list', '-z')
    keys = sorted({key for key in _config_keys(out) if _MERGE_COMMAND_KEY_RE.fullmatch(key)})
    if keys:
        raise _Observed(CONFLICT, 'merge-prediction-driver-unsupported', {'keys': keys[:MAX_LISTED]})


def _quarantine_git_dir(call: _Call, spec: IntegrateSpec) -> str:
    """A private scratch repository for merge-tree inside this call's evidence directory.

    Objects resolve through the real store as an alternate; new objects land only here.
    The repository config is included (our core settings follow, so bare=true wins) and the
    common info/attributes is copied. The shared process helper strips every
    GIT_OBJECT_DIRECTORY-style selector from the environment, so the quarantine is a
    literal ``--git-dir`` argument."""
    if any(ch in spec.common_dir for ch in '"\\\n'):
        raise _Observed(UNKNOWN, 'merge-tree-quarantine-unsupported')
    attributes = os.path.join(spec.common_dir, 'info', 'attributes')
    copied = None
    if _config_file_present(attributes, 'repo-attributes'):
        try:
            with os.fdopen(os.open(attributes, _PRIVATE_READ), 'rb') as stream:
                copied = stream.read()
        except OSError:
            raise _Observed(UNKNOWN, 'repo-attributes-unreadable') from None
    sha256 = len(spec.expected_base) == 64
    config = ['[include]', f'\tpath = "{os.path.join(spec.common_dir, "config")}"', '[core]',
              f'\trepositoryformatversion = {1 if sha256 else 0}', '\tbare = true']
    if sha256:
        config += ['[extensions]', '\tobjectformat = sha256']
    quarantine = call.evidence.scratch_dir('merge-quarantine')
    try:
        for name in ('objects', os.path.join('objects', 'info'), 'refs', 'info'):
            os.mkdir(os.path.join(quarantine, name), 0o700)
        _write_private(os.path.join(quarantine, 'objects', 'info', 'alternates'),
                       (os.path.join(spec.common_dir, 'objects') + '\n').encode('utf-8', 'surrogateescape'))
        _write_private(os.path.join(quarantine, 'HEAD'), b'ref: refs/heads/quarantine\n')
        _write_private(os.path.join(quarantine, 'config'),
                       ('\n'.join(config) + '\n').encode('utf-8', 'surrogateescape'))
        if copied is not None:
            _write_private(os.path.join(quarantine, 'info', 'attributes'), copied)
    except OSError:
        call.evidence.remove_scratch(quarantine)
        raise _Observed(UNKNOWN, 'command-evidence-unwritable') from None
    return quarantine


def _premerge_tree(call: _Call, spec: IntegrateSpec) -> tuple[str | None, list[str]]:
    """Deterministic built-in merge of expected_base and task_result: (tree, []) or
    (None, conflicts).

    merge-tree runs against ``_quarantine_git_dir``, so new objects land only in this call's
    evidence directory and refs, index, worktrees and the repository object store stay
    untouched; observe may use it."""
    _require_builtin_merge(call, spec.repo)
    quarantine = _quarantine_git_dir(call, spec)
    record, out = call.git(spec.repo, f'--git-dir={quarantine}', '-c', f'attr.tree={spec.expected_base}',
                           'merge-tree', '--write-tree', '--name-only', '--no-messages',
                           spec.expected_base, spec.task_result)
    # Reached only for a settled command; an unsettled one raised above and keeps the
    # quarantine as evidence.
    call.evidence.remove_scratch(quarantine)
    lines = _text(out).splitlines()
    if record.exit_code == 1 and record.lifecycle_clean and not record.timed_out and not record.cancelled:
        return None, lines[1:]
    if not record.succeeded or not lines or not _SHA_RE.fullmatch(lines[0]):
        raise _Observed(UNKNOWN, 'merge-tree-unobservable')
    return lines[0], []


def _integration_identity(call: _Call, spec: IntegrateSpec) -> dict[str, Any]:
    """Prove the owned integration worktree is a linked worktree of this repository and the
    ONLY holder of the target branch (the engine creates and journals it at expected_base)."""
    _bind_worktree(call, spec.integration_worktree, spec.common_dir)
    entries = _worktree_entries(call, spec.repo)
    entry = _find_worktree(entries, spec.integration_worktree)
    ref = f'refs/heads/{spec.target_branch}'
    holders = sorted(os.path.realpath(item['path']) for item in entries if item.get('branch') == ref)
    evidence: dict[str, Any] = {'target_holders': holders[:MAX_LISTED]}
    if entry is None or entry is entries[0]:
        raise _Observed(CONFLICT, 'integration-worktree-not-linked', evidence)
    if entry.get('branch') != ref or holders != [spec.integration_worktree]:
        raise _Observed(CONFLICT, 'integration-worktree-identity-mismatch', evidence)
    return evidence


def _integration_blockers(call: _Call, spec: IntegrateSpec) -> dict[str, Any]:
    """Preserved in-progress state of the integration worktree (never reset, aborted, cleaned)."""
    blockers: dict[str, Any] = {}
    busy = _operations_in_progress(call, spec.integration_worktree)
    if busy:
        blockers['operations'] = busy
    _, out = _git_read(call, spec.integration_worktree, 'rev-parse', '--path-format=absolute',
                       '--git-path', 'index.lock')
    if os.path.lexists(_text(out)):
        blockers['index_lock'] = True
    dirty = _status(call, spec.integration_worktree, ignored=True)
    if dirty:
        blockers['paths'] = sorted({entry.path for entry in dirty})[:MAX_LISTED]
        conflicted = sorted(entry.path for entry in dirty if entry.tag == 'u')
        if conflicted:
            blockers['conflicted_paths'] = conflicted[:MAX_LISTED]
    return blockers


def _verify_merge_result(call: _Call, spec: IntegrateSpec, tip: str,
                         evidence: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Only a merge with the exact parents, subject and deterministic merge tree is confirmed."""
    evidence = {**evidence, 'result_sha': tip}
    message = _commit_message(call, spec.repo, tip)
    if message.split('\n', 1)[0] != spec.message.split('\n', 1)[0]:
        return CONFLICT, 'merge-subject-mismatch', evidence
    if _ATTRIBUTION_RE.search(message):
        return CONFLICT, 'ai-attribution-in-commit', evidence
    expected_tree, _ = _premerge_tree(call, spec)
    result_tree = _tree_of(call, spec.repo, tip)
    evidence.update(expected_tree=expected_tree, result_tree=result_tree)
    if expected_tree is None or result_tree != expected_tree:
        return CONFLICT, 'merge-result-tree-mismatch', evidence
    return CONFIRMED, 'merge-committed', evidence


def _containment(call: _Call, spec: IntegrateSpec) -> str | None:
    """'equal' or 'ancestor' when task_result is already in expected_base, else None.

    Called only once the target tip resolved to expected_base, so an equal SHA is a commit.
    A task_result that is not a commit object here cannot be contained; it keeps the
    unchanged forward observation instead of an unobservable ancestry read."""
    if spec.task_result == spec.expected_base:
        return 'equal'
    if _resolve_commit(call, spec.repo, spec.task_result) != spec.task_result:
        return None
    return 'ancestor' if _is_ancestor(call, spec.repo, spec.task_result, spec.expected_base) else None


def _observe_contained(call: _Call, spec: IntegrateSpec, evidence: Mapping[str, Any],
                       containment: str) -> tuple[str, str, dict[str, Any]]:
    """Confirm an observed no-op: nothing needs to change because the exact accepted task
    result is already in the exact checkpoint. Requires the task branch tip to be exactly
    task_result and the integration worktree HEAD on the target at expected_base (identity
    and cleanliness were proven by the caller). Never mutates and never fabricates a commit."""
    task_tip = _branch_tip(call, spec.repo, spec.task_branch)
    evidence = {**evidence, 'task_tip': task_tip, 'containment': containment}
    if task_tip != spec.task_result:
        return CONFLICT, 'task-result-mismatch', evidence
    code, out = _git_read(call, spec.integration_worktree, 'symbolic-ref', '--quiet', 'HEAD', accept=(0, 1))
    if code != 0 or _text(out) != f'refs/heads/{spec.target_branch}':
        return CONFLICT, 'integration-worktree-not-on-target', evidence
    if _resolve_commit(call, spec.integration_worktree, 'HEAD') != spec.expected_base:
        return CONFLICT, 'integration-worktree-head-mismatch', evidence
    return CONFIRMED, 'already-contained', {**evidence, 'result_sha': spec.expected_base,
                                            'mutation_required': False}


def _observe_integrate(call: _Call, spec: IntegrateSpec) -> tuple[str, str, dict[str, Any]]:
    _bind_repo(call, spec.repo, spec.common_dir)
    tip = _branch_tip(call, spec.repo, spec.target_branch)
    evidence: dict[str, Any] = {'target_tip': tip}
    if tip is None:
        return CONFLICT, 'target-missing', evidence
    if tip == spec.expected_base:
        evidence.update(_integration_identity(call, spec))
        blockers = _integration_blockers(call, spec)
        if blockers:
            return CONFLICT, 'integration-worktree-blocked', {**evidence, **blockers}
        containment = _containment(call, spec)
        if containment is not None:
            return _observe_contained(call, spec, evidence, containment)
        return NOT_APPLIED, 'target-at-base', evidence
    if spec.strategy == FAST_FORWARD:
        if tip == spec.task_result:
            return CONFIRMED, 'fast-forwarded', {**evidence, 'result_sha': tip}
        return CONFLICT, 'target-moved', evidence
    if _parents(call, spec.repo, tip) != [spec.expected_base, spec.task_result]:
        return CONFLICT, 'target-moved', evidence
    return _verify_merge_result(call, spec, tip, evidence)


def _execute_integrate(call: _Call, spec: IntegrateSpec) -> tuple[str, str, dict[str, Any]]:
    """Normal ``git merge`` inside the owned integration worktree; hooks run normally."""
    _require_not_applied(call, spec, _observe_integrate)
    if _branch_tip(call, spec.repo, spec.task_branch) != spec.task_result:
        raise _Refuse(REFUSED, 'task-result-mismatch')
    code, out = _git_read(call, spec.integration_worktree, 'symbolic-ref', '--quiet', 'HEAD', accept=(0, 1))
    if code != 0 or _text(out) != f'refs/heads/{spec.target_branch}':
        raise _Refuse(REFUSED, 'integration-worktree-not-on-target')
    if _resolve_commit(call, spec.integration_worktree, 'HEAD') != spec.expected_base:
        raise _Refuse(REFUSED, 'integration-worktree-head-mismatch')
    if spec.strategy == FAST_FORWARD:
        if not _is_ancestor(call, spec.repo, spec.expected_base, spec.task_result):
            raise _Refuse(REFUSED, 'not-fast-forward')
        record = _mutate_git(call, spec.integration_worktree, 'merge', '--ff-only', '--no-autostash',
                             spec.task_result)
        return _integration_outcome(call, spec, record, 'merge-ff-only')
    # A contained task_result was already confirmed by observe and refused as already-applied.
    expected_tree, conflicted = _premerge_tree(call, spec)
    if expected_tree is None:
        raise _Refuse(REFUSED, 'merge-conflict', {'conflicted_paths': conflicted[:MAX_LISTED]})
    message = spec.message if spec.message.endswith('\n') else spec.message + '\n'
    message_path = call.evidence.input_file('merge-message.txt', message.encode('utf-8'))
    record = _mutate_git(call, spec.integration_worktree, 'merge', '--no-ff', '--no-edit', '--no-log',
                         '--no-squash', '--no-autostash', '--no-rerere-autoupdate', '-F', message_path,
                         spec.task_result)
    return _integration_outcome(call, spec, record, 'merge')


def _integration_outcome(call: _Call, spec: IntegrateSpec, record: CommandRecord,
                         label: str) -> tuple[str, str, dict[str, Any]]:
    """Re-read the target after the merge; a stopped merge is reported, never cleaned up."""
    status, reason = _status_of(record, label)
    tip = _branch_tip(call, spec.repo, spec.target_branch)
    details: dict[str, Any] = {'result_sha': tip}
    if status != COMPLETED:
        details.update(_integration_blockers(call, spec))
        return status, reason, details
    if spec.strategy == FAST_FORWARD:
        if tip != spec.task_result:
            return FAILED, 'fast-forward-result-mismatch', details
        return status, reason, details
    if tip is None or _parents(call, spec.repo, tip) != [spec.expected_base, spec.task_result]:
        return FAILED, 'merge-parents-mismatch', details
    state, verdict, evidence = _verify_merge_result(call, spec, tip, details)
    if state != CONFIRMED:
        return FAILED, verdict, evidence
    return status, reason, evidence


# --------------------------------------------------------------------------- push

_COMMAND_KEYS = frozenset({'core.sshcommand', 'core.gitproxy', 'core.askpass', 'credential.helper',
                           'include.path'})
_REMOTE_COMMAND_KEYS = frozenset({'receivepack', 'uploadpack', 'vcs', 'proxy', 'mirror'})


def _is_redirecting_key(key: str, remote: str) -> bool:
    if key in _COMMAND_KEYS:
        return True
    if key.startswith('includeif.') and key.endswith('.path'):
        return True
    if key.startswith('credential.') and key.endswith('.helper'):
        return True
    if key.startswith('url.') and key.endswith(('.insteadof', '.pushinsteadof')):
        return True
    prefix = f'remote.{remote.lower()}.'
    return key.startswith(prefix) and key[len(prefix):] in _REMOTE_COMMAND_KEYS


def _config_keys(out: bytes) -> list[str]:
    return [item.split(b'\n', 1)[0].decode('utf-8', 'replace').lower() for item in out.split(b'\0') if item]


def _config_file_present(path: str, label: str) -> bool:
    """True for a readable regular file, False only when provably absent; otherwise a verdict."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        raise _Observed(UNKNOWN, f'{label}-unreadable') from None
    if not stat.S_ISREG(info.st_mode):
        raise _Observed(CONFLICT, f'{label}-unsafe')
    if not os.access(path, os.R_OK):
        raise _Observed(UNKNOWN, f'{label}-unreadable')
    return True


def _worktree_config_enabled(call: _Call, repo: str) -> bool:
    """Effective extensions.worktreeConfig; Git reads extensions only from the common config."""
    code, out = _git_read(call, repo, 'config', '--local', '--type=bool', '--get',
                          'extensions.worktreeConfig', accept=(0, 1))
    if code == 1:
        return False
    value = _text(out)
    if value not in ('true', 'false'):
        raise _Observed(UNKNOWN, 'worktree-config-extension-unparseable')
    return value == 'true'


def _local_config_keys(call: _Call, repo: str, common_dir: str) -> list[str]:
    """Keys from every repository-controlled config file Git reads for ``repo``.

    The local file is always read. With extensions.worktreeConfig disabled Git ignores
    config.worktree, so the local scope is already complete and ``--worktree`` (which exits
    128 with several worktrees) is never run. When enabled, config.worktree is located with
    --git-path: provably absent means empty; a symlink, non-regular, out-of-repository or
    unreadable file, or any other Git error, is never treated as empty."""
    if not _config_file_present(os.path.join(common_dir, 'config'), 'repo-config'):
        raise _Observed(UNKNOWN, 'repo-config-unreadable')
    _, out = _git_read(call, repo, 'config', '--local', '--list', '-z')
    keys = _config_keys(out)
    if not _worktree_config_enabled(call, repo):
        return keys
    _, out = _git_read(call, repo, 'rev-parse', '--path-format=absolute', '--git-path', 'config.worktree')
    path = _text(out)
    parent = os.path.realpath(os.path.dirname(path))
    if not os.path.isabs(path) or not (parent == common_dir or parent.startswith(common_dir + os.sep)):
        raise _Observed(CONFLICT, 'worktree-config-unsafe')
    if not _config_file_present(path, 'worktree-config'):
        return keys
    _, out = _git_read(call, repo, 'config', '--worktree', '--list', '-z')
    return keys + _config_keys(out)


def _bind_remote(call: _Call, spec: PushSpec) -> None:
    redirecting = sorted({key for key in _local_config_keys(call, spec.repo, spec.common_dir)
                          if _is_redirecting_key(key, spec.remote)})
    if redirecting:
        raise _Observed(CONFLICT, 'repo-config-redirects-remote', {'keys': redirecting[:MAX_LISTED]})
    urls = {}
    for mode, extra in (('fetch', ()), ('push', ('--push',))):
        code, out = _git_read(call, spec.repo, 'remote', 'get-url', *extra, '--all', spec.remote, accept=(0, 2))
        if code == 2:
            raise _Observed(CONFLICT, 'remote-missing')
        urls[mode] = _text(out).splitlines()
    if urls['fetch'] != [spec.remote_url] or urls['push'] != [spec.remote_url]:
        raise _Observed(CONFLICT, 'remote-url-mismatch',
                        {mode: [_redact(url) for url in values][:10] for mode, values in urls.items()})


def _remote_tips(call: _Call, spec: PushSpec) -> dict[str, str]:
    refs = [f'refs/heads/{spec.remote_branch}', f'refs/heads/{spec.base_branch}']
    _, out = _git_read(call, spec.repo, 'ls-remote', '--refs', spec.remote, *refs)
    tips: dict[str, str] = {}
    for line in _text(out).splitlines():
        sha, _, ref = line.partition('\t')
        if ref in refs and _SHA_RE.fullmatch(sha):
            tips[ref[len('refs/heads/'):]] = sha
    return tips


def _observe_push(call: _Call, spec: PushSpec) -> tuple[str, str, dict[str, Any]]:
    _bind_repo(call, spec.repo, spec.common_dir)
    _bind_remote(call, spec)
    tips = _remote_tips(call, spec)
    target = tips.get(spec.remote_branch)
    evidence: dict[str, Any] = {'remote_tip': target, 'remote_base_tip': tips.get(spec.base_branch)}
    if target == spec.expected_result:
        return CONFIRMED, 'remote-at-result', evidence
    if target == spec.expected_remote_old:
        return NOT_APPLIED, 'remote-branch-absent' if target is None else 'remote-at-expected-old', evidence
    return CONFLICT, 'remote-target-mismatch', evidence


def _execute_push(call: _Call, spec: PushSpec) -> tuple[str, str, dict[str, Any]]:
    evidence = _require_not_applied(call, spec, _observe_push)
    if evidence['remote_base_tip'] != spec.expected_base:
        raise _Refuse(REFUSED, 'remote-base-moved', evidence)
    if _branch_tip(call, spec.repo, spec.local_branch) != spec.expected_result:
        raise _Refuse(REFUSED, 'local-result-mismatch')
    if not _is_ancestor(call, spec.repo, spec.expected_base, spec.expected_result):
        raise _Refuse(REFUSED, 'result-not-based-on-base')
    if spec.expected_remote_old is not None and not _is_ancestor(
            call, spec.repo, spec.expected_remote_old, spec.expected_result):
        raise _Refuse(REFUSED, 'not-fast-forward')
    record = _mutate_git(call, spec.repo, 'push', '--porcelain', '--no-follow-tags',
                         '--recurse-submodules=no', spec.remote,
                         f'{spec.expected_result}:refs/heads/{spec.remote_branch}')
    return (*_status_of(record, 'push'), {})


# --------------------------------------------------------------------------- GitHub reads

_PR_LIST_FIELDS = 'number,state,headRefName,headRefOid,baseRefName,isCrossRepository,url'
_PR_VIEW_FIELDS = ('number,state,headRefName,headRefOid,baseRefName,isCrossRepository,'
                   'mergeCommit,autoMergeRequest,url')
# A listing proves absence only when complete: gh pages internally until --limit or the
# last page, so at most _PR_LIST_CAP rows from a --limit of _PR_LIST_CAP + 1 is complete.
_PR_LIST_CAP = 100
_PR_STATES = ('OPEN', 'CLOSED', 'MERGED')


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA_RE.fullmatch(value) is not None


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _has_typed_pr_identity(pr: object) -> bool:
    """Every identity field present with its native type (number a positive int, never bool)."""
    return (isinstance(pr, dict) and _is_positive_int(pr.get('number')) and _is_sha(pr.get('headRefOid'))
            and isinstance(pr.get('isCrossRepository'), bool)
            and all(isinstance(pr.get(key), str) and bool(pr.get(key))
                    for key in ('state', 'headRefName', 'baseRefName', 'url')))


def _is_typed_pr_view(pr: object) -> bool:
    return (_has_typed_pr_identity(pr) and 'mergeCommit' in pr and 'autoMergeRequest' in pr
            and all(pr[key] is None or isinstance(pr[key], dict) for key in ('mergeCommit', 'autoMergeRequest')))


def _gh_host(github_repo: str) -> str:
    """The spec's explicit GitHub host, else github.com; never the CLI's default host."""
    return _GH_REPO_RE.fullmatch(github_repo)['host'] or 'github.com'


def _gh_repo_arg(github_repo: str) -> str:
    """``HOST/OWNER/NAME`` for ``--repo``, so the CLI's default host never picks the target."""
    match = _GH_REPO_RE.fullmatch(github_repo)
    return f"{_gh_host(github_repo)}/{match['owner']}/{match['name']}"


def _canonical_pr_url(github_repo: str, number: int) -> str:
    return f'https://{_gh_repo_arg(github_repo)}/pull/{number}'


def _gh_json(call: _Call, *args: str) -> Any:
    record, out = call.gh(*args)
    if not record.succeeded:
        raise _Observed(UNKNOWN, f'gh-{args[0]}-{args[1]}-unobservable')
    try:
        return json.loads(out)
    except ValueError:
        raise _Observed(UNKNOWN, 'gh-output-unparseable') from None


def _gh_api(call: _Call, github_repo: str, *args: str) -> Any:
    """Parsed JSON of one read-only ``gh api`` call bound to the explicit host of
    ``github_repo``; None when it exited nonzero or is unparseable."""
    record, out = call.gh('api', '--hostname', _gh_host(github_repo), *args)
    if record.exit_code is None or record.timed_out or record.cancelled or not record.lifecycle_clean:
        # A query that did not settle cleanly is never read as absent/empty provider data.
        raise _Observed(UNKNOWN, 'gh-api-unobservable')
    if record.exit_code != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def _gh_api_get(call: _Call, github_repo: str, path: str) -> Any:
    """Parsed JSON of one read-only REST GET; None when unreadable or unparseable."""
    match = _GH_REPO_RE.fullmatch(github_repo)
    return _gh_api(call, github_repo, '--method', 'GET', f"repos/{match['owner']}/{match['name']}/{path}")


def _remote_ref(call: _Call, github_repo: str, branch: str) -> str | None:
    """Exact branch tip from the provider; None only for an unreadable/absent ref."""
    data = _gh_api_get(call, github_repo, f'git/ref/heads/{branch}')
    if not isinstance(data, dict) or data.get('ref') != f'refs/heads/{branch}':
        return None
    target = data.get('object')
    sha = target.get('sha') if isinstance(target, dict) else None
    return sha if isinstance(sha, str) and _SHA_RE.fullmatch(sha) else None


def _provider_commit(call: _Call, github_repo: str, sha: str) -> tuple[list[str], str] | None:
    """(parents, tree) of one provider commit; None when unreadable or malformed."""
    data = _gh_api_get(call, github_repo, f'commits/{sha}')
    if not isinstance(data, dict) or data.get('sha') != sha:
        return None
    parents = data.get('parents')
    commit = data.get('commit')
    tree = commit.get('tree') if isinstance(commit, dict) else None
    tree_sha = tree.get('sha') if isinstance(tree, dict) else None
    if (not isinstance(parents, list) or not parents or not _is_sha(tree_sha)
            or not all(isinstance(item, dict) and _is_sha(item.get('sha')) for item in parents)):
        return None
    return [item['sha'] for item in parents], tree_sha


# --------------------------------------------------------------------------- pr.create

def _observe_pr_create(call: _Call, spec: PrCreateSpec) -> tuple[str, str, dict[str, Any]]:
    """Absence only from a complete, fully typed listing; a truncated listing, a malformed
    row or a matching PR without its canonical URL is unknown, never absence or a match."""
    prs = _gh_json(call, 'pr', 'list', '--repo', _gh_repo_arg(spec.github_repo), '--head', spec.head_branch,
                   '--base', spec.base_branch, '--state', 'all', '--limit', str(_PR_LIST_CAP + 1),
                   '--json', _PR_LIST_FIELDS)
    if not isinstance(prs, list):
        raise _Observed(UNKNOWN, 'gh-output-unparseable')
    if len(prs) > _PR_LIST_CAP:
        raise _Observed(UNKNOWN, 'pr-list-truncated', {'listed': len(prs), 'cap': _PR_LIST_CAP})
    malformed = [idx for idx, row in enumerate(prs)
                 if not _has_typed_pr_identity(row) or row['state'] not in _PR_STATES]
    if malformed:
        raise _Observed(UNKNOWN, 'pr-list-row-malformed', {'rows': malformed[:MAX_LISTED]})
    matching = [pr for pr in prs if pr['headRefName'] == spec.head_branch
                and pr['baseRefName'] == spec.base_branch and pr['isCrossRepository'] is False]
    evidence: dict[str, Any] = {'prs': [{key: pr[key] for key in ('number', 'state', 'headRefOid', 'url')}
                                        for pr in matching][:20]}
    unbound = [pr['number'] for pr in matching if pr['url'] != _canonical_pr_url(spec.github_repo, pr['number'])]
    if unbound:
        return UNKNOWN, 'pr-url-not-canonical', {**evidence, 'numbers': unbound[:MAX_LISTED]}
    if not matching:
        return NOT_APPLIED, 'no-pr', evidence
    open_prs = [pr for pr in matching if pr['state'] == 'OPEN']
    if len(open_prs) > 1:
        return CONFLICT, 'multiple-open-prs', evidence
    if not open_prs:
        return CONFLICT, 'closed-pr-exists', evidence
    pr = open_prs[0]
    if pr['headRefOid'] != spec.head_sha:
        return CONFLICT, 'open-pr-head-mismatch', evidence
    evidence.update(number=pr['number'], url=pr['url'])
    return CONFIRMED, 'pr-open-at-head', evidence


def _execute_pr_create(call: _Call, spec: PrCreateSpec) -> tuple[str, str, dict[str, Any]]:
    _require_not_applied(call, spec, _observe_pr_create)
    if _remote_ref(call, spec.github_repo, spec.head_branch) != spec.head_sha:
        raise _Refuse(REFUSED, 'remote-head-mismatch')
    if _remote_ref(call, spec.github_repo, spec.base_branch) != spec.expected_base_sha:
        raise _Refuse(REFUSED, 'remote-base-moved')
    body_path = call.evidence.input_file('pr-body.md', spec.body.encode('utf-8'))
    record = _mutate_gh(call, 'pr', 'create', '--repo', _gh_repo_arg(spec.github_repo), '--base', spec.base_branch,
                        '--head', spec.head_branch, '--title', spec.title, '--body-file', body_path)
    return (*_status_of(record, 'pr-create'), {})


# --------------------------------------------------------------------------- pr.merge

def _observe_pr_merge(call: _Call, spec: PrMergeSpec) -> tuple[str, str, dict[str, Any]]:
    pr = _gh_json(call, 'pr', 'view', str(spec.number), '--repo', _gh_repo_arg(spec.github_repo),
                  '--json', _PR_VIEW_FIELDS)
    if not _is_typed_pr_view(pr):
        raise _Observed(UNKNOWN, 'pr-view-malformed')
    merge_commit = pr['mergeCommit'] or {}
    evidence: dict[str, Any] = {'state': pr.get('state'), 'head': pr.get('headRefOid'), 'url': pr.get('url'),
                                'merge_commit': merge_commit.get('oid')}
    if (pr.get('number') != spec.number or pr.get('headRefName') != spec.head_branch
            or pr.get('baseRefName') != spec.base_branch or pr.get('isCrossRepository') is not False):
        return CONFLICT, 'pr-identity-mismatch', evidence
    state = pr.get('state')
    if state == 'MERGED':
        if pr.get('headRefOid') != spec.expected_head:
            return CONFLICT, 'merged-at-other-head', evidence
        oid = merge_commit.get('oid')
        if not isinstance(oid, str) or not _SHA_RE.fullmatch(oid):
            return UNKNOWN, 'merge-commit-unreported', evidence
        return _verify_provider_merge(call, spec, oid, evidence)
    if state == 'CLOSED':
        return CONFLICT, 'pr-closed', evidence
    if state != 'OPEN':
        return UNKNOWN, 'pr-state-unrecognised', evidence
    if pr.get('headRefOid') != spec.expected_head:
        return CONFLICT, 'pr-head-moved', evidence
    if pr.get('autoMergeRequest'):
        return UNKNOWN, 'merge-pending', evidence
    return NOT_APPLIED, 'open-unmerged', evidence


def _gh_supports_match_head(call: _Call) -> bool:
    record, out = call.gh('pr', 'merge', '--help')
    return record.succeeded and ('--match-head-commit' in out.decode('utf-8', 'replace')
                                 or '--match-head-commit' in record.stderr_tail)


def _require_required_checks(call: _Call, spec: PrMergeSpec) -> dict[str, Any]:
    """Read the provider's required-check set for the PR head. Worker claims are never read."""
    record, out = call.gh('pr', 'checks', str(spec.number), '--repo', _gh_repo_arg(spec.github_repo),
                          '--required', '--json', 'name,state,bucket')
    if (record.exit_code not in (0, 1, 8) or record.timed_out or record.cancelled
            or not record.lifecycle_clean):
        raise _Refuse(INCOMPLETE, 'required-checks-unobservable')
    try:
        data = json.loads(out)
    except ValueError:
        raise _Refuse(INCOMPLETE, 'required-checks-unreported') from None
    if not isinstance(data, list) or not data or not all(
            isinstance(item, dict) and isinstance(item.get('name'), str) for item in data):
        raise _Refuse(INCOMPLETE, 'required-checks-unreported')
    checks = [{'name': item['name'], 'bucket': item.get('bucket'), 'state': item.get('state')} for item in data]
    details = {'required_checks': checks[:MAX_LISTED]}
    if any(check['bucket'] in ('fail', 'cancel') for check in checks):
        raise _Refuse(REFUSED, 'required-check-failed', details)
    if any(check['bucket'] == 'pending' for check in checks):
        raise _Refuse(INCOMPLETE, 'required-check-pending', details)
    if any(check['bucket'] != 'pass' for check in checks):
        raise _Refuse(INCOMPLETE, 'required-check-not-passed', details)
    reported = {check['name'] for check in checks}
    missing = [name for name in spec.required_checks if name not in reported]
    if missing:
        raise _Refuse(INCOMPLETE, 'declared-check-missing', {**details, 'missing': missing})
    if record.exit_code != 0:
        raise _Refuse(INCOMPLETE, 'required-checks-inconsistent', details)
    return details


def _verify_provider_merge(call: _Call, spec: PrMergeSpec, oid: str,
                           evidence: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Confirm only the exact merged identity: parents [base, head] (merge) or [base]
    (squash) and a tree equal to the reviewed head tree. A mismatch is held as unknown for
    the owner; nothing is rolled back or retried."""
    merged = _provider_commit(call, spec.github_repo, oid)
    head = _provider_commit(call, spec.github_repo, spec.expected_head)
    if merged is None or head is None:
        return UNKNOWN, 'merge-commit-unreadable', dict(evidence)
    parents, tree = merged
    expected = ([spec.expected_base_sha, spec.expected_head] if spec.method == 'merge'
                else [spec.expected_base_sha])
    evidence = {**evidence, 'merge_parents': parents, 'merge_tree': tree, 'head_tree': head[1]}
    if parents != expected or tree != head[1]:
        return UNKNOWN, 'merged-identity-mismatch', evidence
    return CONFIRMED, 'merged', evidence


def _require_up_to_date(call: _Call, spec: PrMergeSpec) -> dict[str, Any]:
    """The reviewed head must already contain the reviewed base, so the merged tree equals
    the reviewed head tree and observe can verify it exactly."""
    data = _gh_api_get(call, spec.github_repo, f'compare/{spec.expected_base_sha}...{spec.expected_head}')
    if not isinstance(data, dict):
        raise _Refuse(INCOMPLETE, 'base-containment-unobservable')
    status, ahead, behind = data.get('status'), data.get('ahead_by'), data.get('behind_by')
    details: dict[str, Any] = {'compare_status': status, 'ahead_by': ahead, 'behind_by': behind}
    if not isinstance(status, str) or not _is_count(ahead) or not _is_count(behind):
        raise _Refuse(INCOMPLETE, 'base-containment-unreported', details)
    if status != 'ahead' or behind != 0 or ahead < 1:
        raise _Refuse(REFUSED, 'head-not-up-to-date-with-base', details)
    commits = [data.get(key) for key in ('base_commit', 'merge_base_commit')]
    shas = [item.get('sha') if isinstance(item, dict) else None for item in commits]
    details.update(base_commit=shas[0], merge_base_commit=shas[1])
    if not all(_is_sha(sha) for sha in shas):
        raise _Refuse(INCOMPLETE, 'base-containment-unreported', details)
    if shas != [spec.expected_base_sha, spec.expected_base_sha]:
        raise _Refuse(REFUSED, 'compare-identity-mismatch', details)
    return details


# Fixed read-only GraphQL query (gh POSTs it as a query, never a mutation); only typed
# variables vary. PullRequest.isMergeQueueEnabled / isInMergeQueue are public schema fields.
_MERGE_QUEUE_QUERY = ('query($owner: String!, $repo: String!, $number: Int!) { '
                      'repository(owner: $owner, name: $repo) { nameWithOwner '
                      'pullRequest(number: $number) { number baseRefName headRefOid '
                      'isMergeQueueEnabled isInMergeQueue } } }')


def _governance_read(label: str, read: Callable[[], Any]) -> Any:
    """One governance read: unsettled, failed or unparseable is INCOMPLETE, never permissive."""
    try:
        data = read()
    except _Observed:
        raise _Refuse(INCOMPLETE, f'{label}-unobservable') from None
    if data is None:
        raise _Refuse(INCOMPLETE, f'{label}-unreadable')
    return data


def _configured_status_checks(rules: Mapping[str, Any]) -> set[str] | None:
    """Typed check names of classic ``required_status_checks``; None when malformed."""
    contexts, checks = rules.get('contexts'), rules.get('checks')
    if not isinstance(contexts, list) or not all(isinstance(item, str) and item for item in contexts):
        return None
    if not isinstance(checks, list) or not all(
            isinstance(item, dict) and isinstance(item.get('context'), str) and item['context'] for item in checks):
        return None
    return set(contexts) | {item['context'] for item in checks}


def _require_strict_protection(call: _Call, spec: PrMergeSpec) -> dict[str, Any]:
    """Classic branch protection of the exact base must require up-to-date branches
    (``strict``) with a non-empty configured check set and apply to administrators. An
    unprotected or ruleset-only base (404), an unreadable, missing, malformed, loose or
    admin-bypassable rule is INCOMPLETE. Settings and protection are never changed."""
    data = _governance_read('branch-protection', lambda: _gh_api_get(
        call, spec.github_repo, f'branches/{spec.base_branch}/protection'))
    if not isinstance(data, dict):
        raise _Refuse(INCOMPLETE, 'branch-protection-malformed')
    rules, admins = data.get('required_status_checks'), data.get('enforce_admins')
    if rules is None:
        raise _Refuse(INCOMPLETE, 'branch-protection-status-checks-absent')
    if not isinstance(rules, dict) or not isinstance(admins, dict):
        raise _Refuse(INCOMPLETE, 'branch-protection-malformed')
    configured = _configured_status_checks(rules)
    strict, enforced = rules.get('strict'), admins.get('enabled')
    if configured is None or not isinstance(strict, bool) or not isinstance(enforced, bool):
        raise _Refuse(INCOMPLETE, 'branch-protection-malformed')
    details = {'protection': {'strict': strict, 'enforce_admins': enforced,
                              'status_checks': sorted(configured)[:MAX_LISTED]}}
    if not strict:
        raise _Refuse(INCOMPLETE, 'branch-protection-not-strict', details)
    if not configured:
        raise _Refuse(INCOMPLETE, 'branch-protection-checks-empty', details)
    if not enforced:
        raise _Refuse(INCOMPLETE, 'branch-protection-admin-bypass', details)
    return details


def _require_no_merge_queue(call: _Call, spec: PrMergeSpec) -> dict[str, Any]:
    """``gh pr merge`` enqueues on a merge-queue base even without ``--auto``, which would
    merge an artifact other than the frozen head and base. The PR's typed
    ``isMergeQueueEnabled`` and ``isInMergeQueue`` must be exactly False for the exact
    repository/number/base/head; ``autoMergeRequest: null`` proves nothing. Anything else,
    including an API error, is INCOMPLETE (never read as False)."""
    match = _GH_REPO_RE.fullmatch(spec.github_repo)
    data = _governance_read('merge-queue-state', lambda: _gh_api(
        call, spec.github_repo, 'graphql', '-f', f'query={_MERGE_QUEUE_QUERY}',
        '-f', f"owner={match['owner']}", '-f', f"repo={match['name']}", '-F', f'number={spec.number}'))
    payload = data.get('data') if isinstance(data, dict) and 'errors' not in data else None
    repo = payload.get('repository') if isinstance(payload, dict) else None
    pr = repo.get('pullRequest') if isinstance(repo, dict) else None
    if not isinstance(repo, dict) or not isinstance(pr, dict) or not isinstance(repo.get('nameWithOwner'), str):
        raise _Refuse(INCOMPLETE, 'merge-queue-state-malformed')
    enabled, queued = pr.get('isMergeQueueEnabled'), pr.get('isInMergeQueue')
    details = {'merge_queue': {'enabled': enabled, 'in_queue': queued}}
    if not isinstance(enabled, bool) or not isinstance(queued, bool):
        raise _Refuse(INCOMPLETE, 'merge-queue-state-malformed', details)
    # GitHub owner/repository names are case-insensitive; everything else binds exactly.
    if (repo['nameWithOwner'].lower() != f"{match['owner']}/{match['name']}".lower()
            or not _is_positive_int(pr.get('number')) or pr['number'] != spec.number
            or pr.get('baseRefName') != spec.base_branch or pr.get('headRefOid') != spec.expected_head):
        raise _Refuse(INCOMPLETE, 'merge-queue-pr-identity-mismatch', details)
    if enabled:
        raise _Refuse(INCOMPLETE, 'merge-queue-enabled', details)
    if queued:
        raise _Refuse(INCOMPLETE, 'pr-in-merge-queue', details)
    return details


def _execute_pr_merge(call: _Call, spec: PrMergeSpec) -> tuple[str, str, dict[str, Any]]:
    """Merge the exact reviewed head (``--match-head-commit``) after base, containment and
    declared required checks are re-read, then re-observe the PR so the checks are bound to
    the unchanged head, then require qualified strict/no-bypass protection and a proven-off
    merge queue. GitHub cannot compare-and-swap the base and governance can change after
    it was read, so a foreign base push after the final base read leaves observe at
    ``merged-identity-mismatch`` (held; never retried or rolled back)."""
    if not _gh_supports_match_head(call):
        raise _Refuse(REFUSED, 'gh-match-head-unsupported')
    _require_not_applied(call, spec, _observe_pr_merge)
    if _remote_ref(call, spec.github_repo, spec.base_branch) != spec.expected_base_sha:
        raise _Refuse(REFUSED, 'remote-base-moved')
    details = {**_require_up_to_date(call, spec), **_require_required_checks(call, spec)}
    _require_not_applied(call, spec, _observe_pr_merge)
    details.update(_require_strict_protection(call, spec))
    details.update(_require_no_merge_queue(call, spec))
    if _remote_ref(call, spec.github_repo, spec.base_branch) != spec.expected_base_sha:
        raise _Refuse(REFUSED, 'remote-base-moved', details)
    record = _mutate_gh(call, 'pr', 'merge', str(spec.number), '--repo', _gh_repo_arg(spec.github_repo),
                        f'--{spec.method}', '--match-head-commit', spec.expected_head)
    return (*_status_of(record, 'pr-merge'), details)


# --------------------------------------------------------------------------- worktree.remove

def _observe_worktree_remove(call: _Call, spec: WorktreeRemoveSpec) -> tuple[str, str, dict[str, Any]]:
    _bind_repo(call, spec.repo, spec.common_dir)
    entries = _worktree_entries(call, spec.repo)
    entry = _find_worktree(entries, spec.path)
    tip = _branch_tip(call, spec.repo, spec.branch)
    evidence: dict[str, Any] = {'branch_tip': tip, 'worktree_registered': entry is not None}
    if entry is None:
        if os.path.lexists(spec.path):
            return CONFLICT, 'path-not-a-registered-worktree', evidence
        if tip != spec.expected_head:
            return CONFLICT, 'branch-not-at-expected-head', evidence
        return CONFIRMED, 'worktree-absent-branch-retained', evidence
    if entries and entry is entries[0]:
        return CONFLICT, 'main-worktree', evidence
    if entry.get('branch') != f'refs/heads/{spec.branch}' or entry.get('HEAD') != spec.expected_head:
        return CONFLICT, 'worktree-identity-mismatch', evidence
    return NOT_APPLIED, 'worktree-present', {**evidence, 'locked': 'locked' in entry,
                                             'prunable': 'prunable' in entry}


def _execute_worktree_remove(call: _Call, spec: WorktreeRemoveSpec) -> tuple[str, str, dict[str, Any]]:
    evidence = _require_not_applied(call, spec, _observe_worktree_remove)
    if evidence['locked'] or evidence['prunable']:
        raise _Refuse(REFUSED, 'worktree-locked-or-prunable')
    _bind_worktree(call, spec.path, spec.common_dir)
    busy = _operations_in_progress(call, spec.path)
    if busy:
        raise _Refuse(REFUSED, 'operation-in-progress', {'operations': busy})
    dirty = _status(call, spec.path, ignored=True)
    if dirty:
        raise _Refuse(REFUSED, 'worktree-not-clean', {'paths': [entry.path for entry in dirty][:MAX_LISTED]})
    record = _mutate_git(call, spec.repo, 'worktree', 'remove', spec.path)
    return (*_status_of(record, 'worktree-remove'), {})


# --------------------------------------------------------------------------- public API

_OBSERVERS: dict[str, Callable[[_Call, Any], tuple[str, str, dict[str, Any]]]] = {
    WORKTREE_CREATE: _observe_worktree_create,
    TASK_COMMIT: _observe_task_commit,
    INTEGRATE: _observe_integrate,
    PUSH: _observe_push,
    PR_CREATE: _observe_pr_create,
    PR_MERGE: _observe_pr_merge,
    WORKTREE_REMOVE: _observe_worktree_remove,
}
_EXECUTORS: dict[str, Callable[[_Call, Any], tuple[str, str, dict[str, Any]]]] = {
    WORKTREE_CREATE: _execute_worktree_create,
    TASK_COMMIT: _execute_task_commit,
    INTEGRATE: _execute_integrate,
    PUSH: _execute_push,
    PR_CREATE: _execute_pr_create,
    PR_MERGE: _execute_pr_merge,
    WORKTREE_REMOVE: _execute_worktree_remove,
}


def _unresolved(path: str, call_dir: str, reason: str, *, mutation: bool = True,
                state: str = 'corrupt') -> PriorCommand:
    """An entry that cannot be classified: held, and conservatively treated as a mutation."""
    return PriorCommand(attempt=path, call_dir=call_dir, mutation=mutation, state=state, identity_status=None,
                        reason=reason, termination=None, lifecycle_clean=False, hold=True)


def _inspect_command(path: str, call_dir: str,
                     mutation: bool) -> tuple[PriorCommand, Mapping[str, Any] | None]:
    """The classified attempt and, once finalized, its validated helper lifecycle record."""
    try:
        status = _process.read_status(path)
    except _process.ProcessError as err:
        return _unresolved(path, call_dir, err.code, mutation=mutation), None
    except OSError:
        return _unresolved(path, call_dir, 'io-error', mutation=mutation, state='unknown'), None
    state, record = status['state'], status['record']
    base = dict(attempt=path, call_dir=call_dir, mutation=mutation, state=state,
                identity_status=status['identityStatus'], reason=status['reason'])
    if state == 'finalized' and isinstance(record, dict):
        return PriorCommand(**base, termination=record['termination'],
                            lifecycle_clean=_lifecycle_clean(record),
                            hold=not _lifecycle_terminal(record)), record
    nothing_ran = state in ('prepared', 'not-launched')
    return PriorCommand(**base, termination=None, lifecycle_clean=nothing_ran, hold=not nothing_ran), None


_COMMAND_REF_RE = re.compile(r'(claim|receipt)-(\d{4}-(?:mutation|read))\.json')
_MAX_REF_BYTES = 1 << 20


def _read_ref(path: str) -> dict[str, Any] | None:
    """One claim/receipt JSON object from a regular file (never a symlink or FIFO); None if unusable."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        with os.fdopen(os.open(path, _PRIVATE_READ | os.O_NONBLOCK), 'rb') as stream:
            data = stream.read(_MAX_REF_BYTES + 1)
    except OSError:
        return None
    if len(data) > _MAX_REF_BYTES:
        return None
    try:
        payload = json.loads(data)
    except (ValueError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _ref_consistent(kind: str, payload: Mapping[str, Any], attempt_id: str, expected: str) -> bool:
    """The ref names exactly its own attempt and mutation flag; only a receipt may name no
    attempt, because prepare failed before one existed."""
    is_mutation = attempt_id.endswith('-mutation')
    if payload.get('mutation') is not is_mutation:
        return False
    if kind == 'claim':
        return payload.get('attempt') == expected
    return payload.get('evidence_dir') in (expected, '')


def _command_refs(call_dir: str, names: Iterable[str]) -> tuple[dict[str, dict[str, Mapping[str, Any]]],
                                                                 list[PriorCommand]]:
    """(trusted claims/receipts by attempt id, held entries for every untrusted one)."""
    refs: dict[str, dict[str, Mapping[str, Any]]] = {}
    untrusted: list[PriorCommand] = []
    for name in sorted(names):
        if not name.startswith(('claim-', 'receipt-')):
            continue
        path = os.path.join(call_dir, name)
        match = _COMMAND_REF_RE.fullmatch(name)
        if match is None:
            untrusted.append(_unresolved(path, call_dir, 'command-ref-unexpected'))
            continue
        kind, attempt_id = match[1], match[2]
        payload = _read_ref(path)
        if payload is None:
            untrusted.append(_unresolved(path, call_dir, 'command-ref-malformed'))
        elif not _ref_consistent(kind, payload, attempt_id, os.path.join(call_dir, 'commands', attempt_id)):
            untrusted.append(_unresolved(path, call_dir, 'command-ref-mismatch'))
        else:
            refs.setdefault(attempt_id, {})[kind] = payload
    return refs, untrusted


# Failure codes as the effects layer records them ('<stage>:<ProcessError code>'); their
# meaning is fixed by the shared helper's source (controller_process.prepare/spawn).
# spawn raises these before it creates spawn.lock (attempt path, root and permission
# checks), so that spawn started nothing. Every other spawn failure is raised at or after
# the lock, or (untyped io-error) may be, so a bare 'prepared' attempt cannot explain it.
_PRE_LOCK_SPAWN_CODES = frozenset({'attempt-not-found', 'attempt-not-private', 'root-not-canonical',
                                   'root-ancestor-unsafe', 'root-unavailable', 'root-not-private'})
# spawn found a lock it did not create: an earlier spawn of this attempt existed.
_PRIOR_SPAWN_ERRORS = frozenset({'spawn:attempt-already-spawned'})
# spawn.json exists without a returned Pending (so no receipt pid) only when its publish
# raised after linking.
_SPAWN_RECORDED_ERRORS = frozenset({'spawn:spawn-record-failed'})
# prepare publishes the intent last: only an OSError after that publish leaves a valid
# 'prepared' attempt behind a failed prepare; every typed prepare code is raised earlier.
_POST_INTENT_PREPARE_ERRORS = frozenset({'prepare:io-error'})
# prepare found the attempt directory already present: one this call never created.
_FOREIGN_PREPARE_ERRORS = frozenset({'prepare:attempt-exists'})


def _never_prepared(by_kind: Mapping[str, Mapping[str, Any]]) -> bool:
    """Only an unclaimed receipt recording a prepare failure proves no attempt ever existed;
    'attempt-exists' instead proves a directory this call did not create held the id."""
    receipt = by_kind.get('receipt')
    if 'claim' in by_kind or receipt is None:
        return False
    spawn_error = receipt.get('spawn_error')
    return (receipt.get('evidence_dir') == '' and receipt.get('pid') is None
            and isinstance(spawn_error, str) and spawn_error.startswith('prepare:')
            and spawn_error not in _FOREIGN_PREPARE_ERRORS)


def _receipt_recorded(receipt: Mapping[str, Any]) -> bool:
    """The receipt claims a settled lifecycle, which only a finalized helper record supplies."""
    return (receipt.get('termination') is not None or receipt.get('exit_code') is not None
            or receipt.get('lifecycle_clean') is True
            or bool(receipt.get('stdout_sha256')) or bool(receipt.get('stderr_sha256')))


def _prelaunch_failure(receipt: Mapping[str, Any], attempt: str) -> bool:
    """The receipt itself shows its run never spawned this 'prepared' attempt: no pid and no
    ownership, and either a prepare that failed after publishing the intent (no attempt was
    returned, so spawn never ran) or a typed spawn failure raised before any spawn lock,
    after which the call polled the attempt as 'prepared' or hit the same path fault."""
    if receipt.get('pid') is not None or receipt.get('identity_status') is not None:
        return False
    spawn_error, process_state = receipt.get('spawn_error'), receipt.get('process_state')
    if spawn_error in _POST_INTENT_PREPARE_ERRORS:
        return receipt.get('evidence_dir') == '' and process_state is None
    stage, _, code = (spawn_error or '').partition(':')
    if stage != 'spawn' or code not in _PRE_LOCK_SPAWN_CODES or receipt.get('evidence_dir') != attempt:
        return False
    return (process_state, receipt.get('process_reason')) in (('prepared', None), ('corrupt', code))


def _record_conflict(receipt: Mapping[str, Any], record: Mapping[str, Any]) -> str | None:
    """Why a receipt contradicts its attempt's validated, finalized helper record, or None.

    ``CommandRecord.pid`` is the bootstrap anchor spawn returned (``identity.pid``), never
    the declared command's ``commandPid``; it is absent only when no Pending was returned,
    and spawn.json then exists only after a failed spawn-record publish. A recorded
    lifecycle must be the record's own, with log sizes/digests from its log references
    (none when the receipt says the logs did not verify)."""
    identity = record['identity']
    anchor = identity['pid'] if isinstance(identity, dict) else None
    pid = receipt.get('pid')
    if pid != anchor and not (pid is None and receipt.get('spawn_error') in _SPAWN_RECORDED_ERRORS):
        return 'receipt-pid-unmatched'
    if not _receipt_recorded(receipt):
        return None
    expected = {'termination': record['termination'], 'exit_code': record['exitCode'],
                'signal': _signal_number(record['signal']), 'forced': record['forced'],
                'lingering': record['lingering'], 'lifecycle_clean': _lifecycle_clean(record),
                'lifecycle_reasons': list(record['reasons'])}
    if any(receipt.get(key) != value for key, value in expected.items()):
        return 'receipt-lifecycle-unmatched'
    unverified = receipt.get('evidence_error') == 'command-log-unverifiable'
    for stream in ('stdout', 'stderr'):
        ref = record['logs'][stream]
        logged = (0, '') if unverified or ref is None else (ref['size'], ref['sha256'])
        if (receipt.get(f'{stream}_bytes'), receipt.get(f'{stream}_sha256')) != logged:
            return 'receipt-logs-unmatched'
    return None


def _receipt_conflict(receipt: Mapping[str, Any], item: PriorCommand,
                      record: Mapping[str, Any] | None) -> str | None:
    """Why a trusted receipt contradicts its helper attempt's validated facts, or None.

    The receipt is bound to its attempt: an empty ``evidence_dir`` exactly when prepare
    failed. A recorded lifecycle needs a finalized helper record. An attempt the helper
    shows as never spawned ('prepared': no spawn lock) needs a receipt proving its run
    never spawned it; an untyped error, a failure raised at or after the lock, a proven
    earlier lock or a pid never turns a bare prepared directory into 'never started'. A
    spawned attempt contradicts a failed prepare or a pre-lock spawn failure, and is
    checked against its finalized record (pid anchor, lifecycle, log digests)."""
    termination, pid = receipt.get('termination'), receipt.get('pid')
    spawn_error, process_state = receipt.get('spawn_error'), receipt.get('process_state')
    if (not all(value is None or isinstance(value, str) for value in (termination, spawn_error, process_state))
            or not (pid is None or type(pid) is int)):
        return 'receipt-fields-invalid'
    prepare_failed = isinstance(spawn_error, str) and spawn_error.startswith('prepare:')
    if (receipt.get('evidence_dir') == '') is not prepare_failed:
        return 'receipt-identity-unmatched'
    if _receipt_recorded(receipt) and record is None:
        return 'receipt-lifecycle-unmatched'
    if item.state == 'prepared':
        return None if _prelaunch_failure(receipt, item.attempt) else 'receipt-spawn-unmatched'
    stage, _, code = (spawn_error or '').partition(':')
    if (prepare_failed or spawn_error in _PRIOR_SPAWN_ERRORS
            or (stage == 'spawn' and code in _PRE_LOCK_SPAWN_CODES)):
        return 'receipt-spawn-unmatched'
    return None if record is None else _record_conflict(receipt, record)


def _inspect_attempts(commands: str, call_dir: str, required: bool) -> tuple[
        dict[str, PriorCommand], dict[str, Mapping[str, Any]], list[PriorCommand]]:
    """(helper attempts by id, their finalized lifecycle records by id, held entries) under
    one commands root. ``required`` is True when attempt.json or any claim/receipt proves
    the root was created."""
    try:
        info = os.lstat(commands)
    except FileNotFoundError:
        return {}, {}, [_unresolved(commands, call_dir, 'commands-root-missing')] if required else []
    except OSError:
        return {}, {}, [_unresolved(commands, call_dir, 'commands-root-unreadable')]
    if not stat.S_ISDIR(info.st_mode):
        return {}, {}, [_unresolved(call_dir, call_dir, 'call-dir-unsafe')]
    try:
        names = sorted(os.listdir(commands))
    except OSError:
        return {}, {}, [_unresolved(commands, call_dir, 'commands-root-unreadable')]
    attempts: dict[str, PriorCommand] = {}
    records: dict[str, Mapping[str, Any]] = {}
    unexpected: list[PriorCommand] = []
    for name in names:
        path = os.path.join(commands, name)
        match = _COMMAND_ID_RE.fullmatch(name)
        if match is None:
            unexpected.append(_unresolved(path, call_dir, 'command-entry-unexpected'))
            continue
        attempts[name], record = _inspect_command(path, call_dir, match[2] == 'mutation')
        if record is not None:
            records[name] = record
    return attempts, records, unexpected


def _inspect_call(call_dir: str) -> list[PriorCommand]:
    """Every command one call may have started: the helper attempts under ``commands/``
    cross-reconciled with the call's durable claims and receipts. A claim or receipt whose
    attempt is missing, an untrusted claim/receipt, a claimed attempt with no spawn
    evidence, a receipt whose recorded spawn or settlement the helper facts do not bear
    out, or a lost commands root is missing evidence and holds; it is never read as
    absence and nothing is recreated. Only a call that left no attempt.json, commands root,
    claim or receipt (initialisation stopped before anything could spawn) adds nothing."""
    try:
        if not stat.S_ISDIR(os.lstat(call_dir).st_mode):
            return [_unresolved(call_dir, call_dir, 'call-dir-unsafe')]
        names = os.listdir(call_dir)
    except OSError:
        return [_unresolved(call_dir, call_dir, 'call-dir-unreadable')]
    refs, untrusted = _command_refs(call_dir, names)
    commands = os.path.join(call_dir, 'commands')
    required = bool(refs) or bool(untrusted) or 'attempt.json' in names
    attempts, records, unexpected = _inspect_attempts(commands, call_dir, required)
    dangling: list[PriorCommand] = []
    for attempt_id, by_kind in sorted(refs.items()):
        item = attempts.get(attempt_id)
        if item is None:
            if not _never_prepared(by_kind):
                dangling.append(_unresolved(os.path.join(commands, attempt_id), call_dir,
                                            'command-evidence-missing'))
        elif 'claim' in by_kind and item.state == 'prepared':
            # A claim is written only after spawn, so a 'prepared' attempt lost its spawn evidence.
            attempts[attempt_id] = dataclasses.replace(item, reason='claimed-attempt-unspawned',
                                                       lifecycle_clean=False, hold=True)
        elif 'receipt' in by_kind and not item.hold:
            conflict = _receipt_conflict(by_kind['receipt'], item, records.get(attempt_id))
            if conflict is not None:
                attempts[attempt_id] = dataclasses.replace(item, reason=conflict,
                                                           lifecycle_clean=False, hold=True)
    return [*attempts.values(), *unexpected, *untrusted, *dangling]


def inspect_commands(evidence_root: str) -> tuple[PriorCommand, ...]:
    """Read-only classification of every command attempt recorded under one effect's
    evidence root: helper ``read_status`` only; nothing is written, signalled or finalized."""
    _require_evidence_root(evidence_root)
    try:
        names = sorted(os.listdir(evidence_root))
    except OSError:
        return (_unresolved(evidence_root, evidence_root, 'evidence-root-unreadable'),)
    found: list[PriorCommand] = []
    for name in names:
        if _CALL_DIR_RE.fullmatch(name):
            found.extend(_inspect_call(os.path.join(evidence_root, name)))
    return tuple(found)


def _finalize_prior(attempt: str) -> str | None:
    """Complete the lifecycle record of a settled prior attempt; the failure code, if any."""
    try:
        _process.finalize(attempt)
    except _process.ProcessError as err:
        return None if err.code == 'already-finalized' else err.code
    except OSError:
        return 'io-error'
    return None


def _reconcile_prior(evidence_root: str) -> tuple[PriorCommand, ...]:
    """inspect_commands after finalizing (evidence only) any settled but unfinalized attempt;
    the re-inspection is authoritative, so a failed finalize stays held."""
    prior = inspect_commands(evidence_root)
    pending = [item.attempt for item in prior if item.state in _FINALIZABLE_STATES]
    if not pending:
        return prior
    failures = {attempt: code for attempt in pending if (code := _finalize_prior(attempt)) is not None}
    return tuple(dataclasses.replace(item, reason=f'finalize:{failures[item.attempt]}')
                 if item.attempt in failures and item.state in _FINALIZABLE_STATES else item
                 for item in inspect_commands(evidence_root))


def _held(prior: tuple[PriorCommand, ...]) -> list[dict[str, Any]]:
    return [item.as_dict() for item in prior if item.hold][:MAX_LISTED]


def _unclean_mutations(prior: tuple[PriorCommand, ...]) -> tuple[dict[str, Any], ...]:
    """Terminal prior mutations that did not end by themselves: they may have applied the
    effect, so absence can no longer be concluded for this intent."""
    return tuple(item.as_dict() for item in prior
                 if item.mutation and not item.hold and not item.lifecycle_clean)[:MAX_LISTED]


def _open_call(toolchain: Toolchain, cancel: Cancellation | None, operation: str, kind: str,
               spec: Any, prior_unclean: tuple[dict[str, Any], ...]) -> _Call:
    return _Call(toolchain, cancel, _Evidence(toolchain, operation, kind, spec, prior_unclean), prior_unclean)


def observe(kind: str, spec: Any, *, toolchain: Toolchain,
            cancel: Cancellation | None = None) -> Observation:
    """Is this exact effect applied? Never mutates repository or provider state; the only
    writes are owner-private command evidence under ``evidence_root`` (this call's, plus
    the lifecycle record of a settled prior attempt). An unresolved prior command holds
    the observation as unknown without running anything."""
    validate_toolchain(toolchain)
    validate_spec(kind, spec)
    _require_evidence_outside(toolchain.evidence_root, spec)
    prior = _reconcile_prior(toolchain.evidence_root)
    held = _held(prior)
    if held:
        return Observation(kind, UNKNOWN, 'prior-command-unresolved', {'prior_commands': held}, ())
    call = _open_call(toolchain, cancel, 'observe', kind, spec, _unclean_mutations(prior))
    try:
        state, reason, evidence = _OBSERVERS[kind](call, spec)
    except _Observed as verdict:
        state, reason, evidence = verdict.state, verdict.reason, verdict.evidence
    if state == NOT_APPLIED and call.prior_unclean:
        state, reason = UNKNOWN, 'prior-mutation-unclean'
        evidence = {**evidence, 'prior_commands': list(call.prior_unclean)}
    return Observation(kind, state, reason, evidence, tuple(call.records), call.evidence.path)


def execute(kind: str, spec: Any, *, toolchain: Toolchain, authorized_kinds: Iterable[str],
            cancel: Cancellation | None = None) -> ExecuteOutcome:
    """Re-observe preconditions, then run the one fixed mutation for ``kind``.

    ``authorized_kinds`` is the owner-policy grant the trusted engine resolved; it is not a
    substitute for the engine's result/check/review gates. The returned outcome is raw: the
    engine must persist it and confirm the effect with ``observe``."""
    validate_toolchain(toolchain)
    validate_spec(kind, spec)
    _require_evidence_outside(toolchain.evidence_root, spec)
    if kind not in _authorized(authorized_kinds):
        return ExecuteOutcome(kind, REFUSED, 'kind-not-authorized', False, (), {})
    prior = _reconcile_prior(toolchain.evidence_root)
    held = _held(prior)
    if held:
        return ExecuteOutcome(kind, INCOMPLETE, 'prior-command-unresolved', False, (), {'prior_commands': held})
    call = _open_call(toolchain, cancel, 'execute', kind, spec, _unclean_mutations(prior))
    try:
        status, reason, details = _EXECUTORS[kind](call, spec)
    except _Refuse as stop:
        status, reason, details = stop.status, stop.reason, stop.details
    except _Observed as verdict:
        if not call.evidence_complete:
            status = INCOMPLETE
        else:
            status = FAILED if call.mutation_started else REFUSED
        reason, details = f'{verdict.state}:{verdict.reason}', verdict.evidence
    return ExecuteOutcome(kind, status, reason, call.mutation_started, tuple(call.records), details,
                          call.evidence.path, call.evidence_complete)


_UNCERTAIN_STATUSES = frozenset({COMPLETED, TIMED_OUT, CANCELLED, INCOMPLETE})


def settle(outcome: ExecuteOutcome | None, observation: Observation) -> str:
    """Ledger state from the latest raw outcome and a fresh observation.

    Only an observation can confirm. ``not_applied`` after a mutation that exited 0, timed
    out, was cancelled (STOP) or ended with an unclean/unsettled lifecycle, after any
    attempted provider write whose read API may lag, or after an attempt whose command
    evidence is incomplete, is ``unknown`` (hold and re-observe). Only a mutation whose
    command ended by itself with a clean lifecycle and a nonzero exit can settle absent."""
    if outcome is not None and outcome.kind != observation.kind:
        raise ValueError('outcome and observation kinds differ')
    if observation.state != NOT_APPLIED:
        return observation.state
    if outcome is None or not outcome.mutation_attempted:
        return NOT_APPLIED
    if (outcome.status in _UNCERTAIN_STATUSES or outcome.kind in REMOTE_ASYNC_KINDS
            or not outcome.evidence_complete):
        return UNKNOWN
    return NOT_APPLIED
