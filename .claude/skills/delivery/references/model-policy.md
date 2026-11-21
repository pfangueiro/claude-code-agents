# Model policy (opt-in)

Model and effort are separate choices. By default every edition inherits both from the
native configuration (CLI settings, agent definitions and the session), and no selection is
claimed. The static model names in the agent definition files are compatible starting points,
not a calibrated optimum and not a capability ranking. This reference describes the optional
owner policy that lets attended delivery request one specific model and effort per
invocation, and how to evaluate, approve and roll back model versions.

`scripts/model_policy.py` in this skill is a read-only JSON tool (Python 3.11+, standard
library only). It never invokes a provider, discovers accounts, reads credentials or provider
configuration, changes models, effort, approval, sandbox or defaults, or writes a file. Results
go to stdout; keep them as artifacts. Exit codes: `0` PLAN_READY, INHERIT or PASS; `1` FAIL;
`2` usage error; `3` INCOMPLETE.

## When it applies

| Owner policy at `~/.config/sdlc/model-policy.json` | `select` | Meaning |
|---|---|---|
| absent | `INHERIT` (`policy-missing`) | native configuration applies; no claim |
| valid, `"active": false` | `INHERIT` (`policy-inactive`) | same |
| present but malformed or unsafe | `INCOMPLETE` (`policy-invalid`) | never silently inherited |
| valid and active | `PLAN_READY` or `INCOMPLETE` | see *Decision rules* |

Authority is that one owner-global file: a regular file you own, mode within `0600`, no
symlinked file or parent directory, parent not group- or world-writable. There is no
`--policy` flag and no project-local policy, so a worker or a repository cannot point the
tool at a policy it wrote. These are private-file checks and digests, not authentication, a
signature or a sandbox: the same OS user can still change any file.

Set it up once per host. Installers and updates never create, adopt, rewrite or migrate it,
and updating never rediscovers accounts or asks the controller policy questions again. A new
host stays on inheritance until its owner writes a policy. Evaluation artifacts and capability
evidence are per host, so a copied policy usually needs new ones.

## Owner policy (version 1)

Start from the inactive `model-policy.example.json` beside this file; replace the example
identifiers, paths and digests with your own, then set `"active": true`.

```json
{
  "version": 1,
  "active": true,
  "evidence_max_age_seconds": 3600,
  "bindings": {
    "claude-a": {
      "provider": "claude",
      "model": "<exact model identifier>",
      "effort": "high",
      "pinned": true,
      "capabilities": ["code", "review"],
      "status": "approved",
      "evaluation": {"path": "/absolute/path/to/result.json", "sha256": "<64 hex>",
                     "model": "<exact model identifier>"},
      "approval": {"by": "owner", "at": "2026-01-15T09:00:00Z"}
    }
  },
  "routes": {"claude": {"routine": ["claude-a"], "complex": ["claude-a"], "critical": ["claude-a"]}}
}
```

- **Binding:** one provider, one exact model identifier and one effort (`null` keeps the
  native effort). Identifiers live only in this owner file; the tool hardcodes and ranks none.
- **`pinned`:** `true` when the identifier is the most specific version the provider
  accepts. `false` is allowed and reported as `version_pinned: false`. Neither promises
  immutable backend weights.
- **`capabilities`:** your own lowercase vocabulary. A request's required capabilities must
  all be present on the binding.
- **`status`:** `candidate` (never routed), `approved` (routable) or `revoked` (never
  routed). `approved` needs both `evaluation` and `approval`. A `candidate` may carry an
  evaluation but never an approval.
- **`evaluation`:** absolute path, SHA-256 of the exact bytes, and the exact observed model of
  a verified-handoff `agent-eval-result/v2` artifact (see verified-handoff
  `references/agent-evaluation.md`). Every decision rereads the bytes: the digest must match,
  `outcome` must be `PASS`, every trial must have observed exactly `model` (null is unknown),
  and every candidate-arm trial must pass. Whether those tasks cover the routed work is your
  judgment; a pass on a synthetic or offline corpus is not efficacy proof.
- **`routes`:** per provider and risk class (`routine`, `complex`, `critical`), your ordered
  binding IDs of that provider. Order is preference among fully eligible bindings, nothing more.
- **`evidence_max_age_seconds`** (60 to 604800): the maximum age of capability evidence.

The policy, the coordinator request, the capability evidence and the host observation use
closed schemas with exact types (a boolean is never an integer), bounded sizes and
collections, and reject duplicate keys, non-finite numbers and control characters. The
retained selection has closed keys. The evaluation artifact and the native provider stream
are not closed (they carry agent-eval and provider fields): they are size-bounded and parsed
strictly, with no duplicate key or non-finite number, and only the fields named here are read.

## Coordinator request

The coordinator declares each coherent slice once, in a private file (mode `0600`). Workers
do not write or lower it; a different request has a different digest, which `verify` detects.

```json
{
  "version": 1,
  "task_id": "slice-3",
  "source": {"kind": "git-sha", "value": "<40 or 64 hex commit>"},
  "declared_by": "coordinator",
  "provider": "claude",
  "role": "implement",
  "risk": "complex",
  "surface": "claude-cli",
  "capabilities": ["code"]
}
```

`source.kind` is `git-sha` or `sha256` (a content digest for source-only input). `provider`
and `role` are the already authorized ones: selection never changes the provider, account or
profile. `role` is one of `coordinate`, `implement`, `review`, `verify`.

| `surface` | Invocation |
|---|---|
| `claude-cli` | a Claude CLI invocation |
| `claude-agent` | a Claude Agent/subagent call (a fork ignores its model argument) |
| `codex-cli` | a Codex CLI invocation |
| `codex-spawn` | a Codex collaboration spawn |
| `codex-fork` | a Codex fork that may inherit the parent's model |
| `delivery-controller` | the persistent controller: always `controller-unsupported` |

## Host capability evidence

A host-side probe or the coordinator records what this exact surface accepts, freshly, in a
private file. It is a host observation, not a model's self-report.

```json
{
  "version": 1,
  "provider": "claude",
  "surface": "claude-cli",
  "observed_at": "2026-11-21T10:00:00Z",
  "observed_by": "host probe name",
  "client_version": "<CLI version or null>",
  "model_control": "per-invocation",
  "effort_control": "per-invocation",
  "models": {
    "<exact model identifier>": {"available": true, "resolves_to": "<exact model identifier>",
                                 "efforts": ["low", "high"]}
  }
}
```

- `model_control`: `per-invocation` when an explicit model request on this surface wins;
  `inherit-only` (for example a fork) or `role-default` (a forced agent default wins) make
  every request INCOMPLETE.
- `effort_control`: `per-invocation` or `unsupported`.
- Per model: `available` true, false or null (unknown); `resolves_to` the exact identifier the
  surface resolves the request to, or null (unknown); `efforts` the supported efforts, or null.
  An alias that resolves elsewhere is a mismatch. Unknown is never treated as supported.

## Decision rules

1. Missing or inactive policy: INHERIT. Malformed or unsafe policy, request or evidence:
   INCOMPLETE.
2. The controller surface, missing evidence, evidence for another surface, evidence from the
   future (beyond five minutes of clock skew) or older than the policy allows, or a surface
   without per-invocation model control: INCOMPLETE.
3. Only the route for the request's provider and exact risk class is considered. A complex or
   critical slice never uses the routine route, and nothing moves to another provider.
4. In owner order, the first binding is selected that is `approved`, has a qualifying
   evaluation, carries every required capability, is available, resolves to itself, and whose
   effort (if not null) the surface can set and supports. Each skipped binding lists its
   reasons in `considered`.
5. A later entry is a fallback (`fallback: true`, reason `fallback-candidate`) within the same
   class only. If none qualifies: INCOMPLETE `no-eligible-candidate`, never a silent weaker
   model and never a role default reported as selected.

Binding reasons: `binding-candidate`, `binding-revoked`, `evaluation-unavailable`,
`evaluation-digest-mismatch`, `evaluation-malformed`, `evaluation-unsupported-schema`,
`evaluation-not-pass`, `evaluation-empty`, `evaluation-model-unknown`,
`evaluation-model-mismatch`, `evaluation-candidate-not-pass`, `capability-missing`,
`model-support-unknown`, `availability-unknown`, `model-unavailable`,
`model-resolution-unknown`, `model-alias-mismatch`, `effort-control-unsupported`,
`effort-support-unknown`, `effort-unsupported`.

## Commands

Run from any directory; paths may be relative to it.

```bash
python3 <this skill directory>/scripts/model_policy.py status
python3 <this skill directory>/scripts/model_policy.py select \
    --request request.json --capabilities capabilities.json > selection.json
python3 <this skill directory>/scripts/model_policy.py verify --selection selection.json \
    --request request.json --capabilities capabilities.json --stream provider-events.jsonl
```

`status` prints `sdlc-model-policy-status/v1`: `policy` (`location`, `state`, `sha256`),
`detail`, `evidence_max_age_seconds`, `routes`, and per binding `provider`, `model`, `effort`,
`pinned`, `status`, `capabilities`, `approved_by`, `evaluation_sha256`, `evaluation_check`
(`verified` or a reason) and `approved_and_evaluated`. It exits 3 only for an invalid policy.

`select` prints a selection record:

```json
{
  "schema": "sdlc-model-selection/v1",
  "decided_at": "2026-11-21T10:05:00.000000Z",
  "decision": "PLAN_READY",
  "reasons": [],
  "detail": null,
  "policy": {"location": "~/.config/sdlc/model-policy.json", "state": "active", "sha256": "<64 hex>"},
  "request": {"sha256": "<64 hex>", "task_id": "slice-3", "source": {"kind": "git-sha", "value": "<sha>"},
              "declared_by": "coordinator", "provider": "claude", "role": "implement",
              "risk": "complex", "surface": "claude-cli", "capabilities": ["code"]},
  "capabilities": {"sha256": "<64 hex>", "surface": "claude-cli", "observed_at": "2026-11-21T10:00:00Z",
                   "observed_by": "host probe name", "client_version": "<version>",
                   "model_control": "per-invocation", "effort_control": "per-invocation"},
  "selected": {"binding": "claude-a", "provider": "claude", "model": "<exact model identifier>",
               "effort": "high", "version_pinned": true, "evaluation_sha256": "<64 hex>",
               "route_index": 0, "fallback": false},
  "considered": [{"binding": "claude-a", "eligible": true, "reasons": []}],
  "executed": false,
  "limitations": ["..."]
}
```

PLAN_READY is a plan, not a runtime result (`executed` is always false). Pass exactly
`selected.model` and `selected.effort` through the surface's own controls; the tool does not
render flags.

`verify` prints `sdlc-model-run-check/v1`:

```json
{
  "schema": "sdlc-model-run-check/v1",
  "checked_at": "2026-11-21T10:40:00.000000Z",
  "outcome": "PASS",
  "reasons": [],
  "detail": null,
  "selection_sha256": "<64 hex of selection.json>",
  "selection_decision": "PLAN_READY",
  "binding": "claude-a",
  "requested": {"model": "<exact model identifier>", "effort": "high"},
  "fallback_used": false,
  "observed": {"source": "host-observation", "provider": "claude", "model": "<exact model identifier>",
               "configured_model": null, "executed_models": ["<exact model identifier>"],
               "usage_models": null, "effort": "high", "terminal": "success",
               "stream_category": null, "stream_reasons": []},
  "limitations": ["..."]
}
```

The retained selection must be a `sdlc-model-selection/v1` record with exactly the keys shown
above; anything else is `selection-invalid`. `verify` first requires the current policy,
request and capability files to have the recorded digests (`policy-drift`, `request-drift`,
`capabilities-drift`), then recomputes the whole record at the recorded `decided_at` and
compares it with the retained one by exact JSON value:

- When the recomputed `selected` binding differs and evaluation state explains it, the result
  is INCOMPLETE `evaluation-drift`: either the selected binding's evaluation artifact no longer
  qualifies, or the retained and recomputed `considered` lists disagree on the `evaluation-*`
  reasons of some binding. The second case covers a fallback chosen while an earlier binding's
  pinned artifact was unavailable: once the identical bytes are readable again the
  recomputation selects the earlier binding. No recorded digest binds the evaluation artifacts
  as they were at selection time, so a changed artifact availability and an altered
  `considered` history cannot be told apart; this is never PASS and never a claimed mismatch.
  A decision that otherwise no longer reproduces is INCOMPLETE `selection-not-reproducible`.
- A record whose `selected` binding the inputs do not produce while the evaluation reasons of
  every considered binding are unchanged, or whose `decision`, `reasons`,
  `detail`, `policy`, `request`, `capabilities` or `executed` differ from the recomputation, is
  FAIL `selection-record-mismatch` (`detail` names the differing fields). The recorded digests
  alone are not enough: a record that keeps them but names another task, risk, source, policy
  state or capability evidence does not verify.
- A `considered` list that differs is INCOMPLETE `selection-considered-not-reproducible`: it
  depends on the evaluation artifacts of skipped bindings, which no recorded digest binds, so
  an artifact change and an altered record cannot be told apart.
- `limitations` is retained prose and is not compared. A selection that is not PLAN_READY is
  `selection-not-plan-ready`.

This is a consistency check of the record against its inputs, not authentication of who wrote
it.

Observed metadata comes from one of two caller-supplied sources:

- `--stream`: the native provider JSONL event log of the run. Its terminal is classified by
  the delivery controller's own parser (`controller_providers.parse_stream`); model identity
  is read here from structured fields only, and three things are kept apart:
  - `configured_model`: the model named by the init event. It is configuration, not proof of
    what was served, so an init event plus a successful terminal alone stays
    `observed-model-unknown`.
  - `executed_models`: the models named on the assistant messages (`message.model`). `model` is
    set only when exactly one identifier authored every assistant message. Any other model
    there is a failure: `observed-model-mismatch` when the requested model authored nothing
    (for example a provider-side fallback), `observed-model-mixed` when it authored only part
    of the run.
  - `usage_models`: the keys of the terminal result's `modelUsage`, when present. If they
    differ from the executed models the run is INCOMPLETE (`observed-model-usage-differs`):
    the stream does not show what the other model did.

  An assistant message without a usable model identifier is `observed-model-unrecognized`, and
  executed models that differ from the configured one add `configured-model-differs`; both are
  INCOMPLETE on their own. No served-model field is read from a Codex `exec --json` stream, so
  its model stays unknown; use a host observation there. Streams carry no effort, so a
  requested effort stays `observed-effort-unknown`. Message text is never read as identity.
  Provider fields beyond these are allowed, but every non-empty line must be an unambiguous
  strict JSON object: a malformed line, a non-object, a repeated key or a non-finite number
  makes the whole stream `stream-identity-malformed`, with every model field unknown.
- `--observation`: a host observation written by the harness or host from native metadata,
  naming the digest of the exact selection bytes:

```json
{"version": 1, "selection_sha256": "<64 hex of selection.json>", "provider": "claude",
 "surface": "claude-cli", "observed_by": "host harness name", "observed_model": "<id or null>",
 "observed_effort": "<effort or null>", "terminal": "success"}
```

Outcomes: FAIL for `observed-model-mismatch`, `observed-model-mixed` or
`observed-effort-mismatch`; INCOMPLETE for `terminal-not-success`, `observed-model-unknown`,
`observed-model-unrecognized`, `observed-model-usage-differs`, `configured-model-differs`,
`observed-effort-unknown`, `observation-not-bound`, `observation-surface-mismatch`,
`observation-invalid`, `stream-unreadable` or `stream-identity-malformed`; otherwise PASS. `fallback_used` reports a
fallback selection (a later route entry), which is separate from a provider-side fallback
seen in the stream.

## What the checks cover

- **Private inputs:** the owner policy, the coordinator request and the host capability
  evidence must each be a regular file owned by the current user, with mode within `0600`,
  reached without a symlink, in a parent directory that is not group- or world-writable. One
  that fails this is refused (`policy-invalid`, `request-invalid`, `capabilities-invalid`).
- **Retained artifacts:** the selection record, a provider stream, a host observation and the
  evaluation artifacts are caller-trusted retained files. They are read as regular files at an
  absolute path without a symlink, with no mode or ownership requirement, so an `0644`
  observation or stream is accepted. Keep them wherever your receipts live.
- **Neither is authentication.** File checks and digests are not a signature, a sandbox or a
  boundary against the same OS user. The `selection_sha256` inside an observation is the
  host's assertion of which plan it observed; it does not prove who wrote the observation.
- **`verify` compares, it does not attest.** It compares the observed metadata with the
  retained plan. It does not prove that the planned model and effort were passed to the
  invocation, or that the stream or observation belongs to this task. The caller links the
  actual argv, the session and the raw log to the slice's exact-input execution receipt. A
  digest of the log alone would not establish that provenance either.
- **Separate gates.** A `verify` PASS is evidence about one run. Task acceptance, the
  exact-input check receipts and the independent review are unchanged and decided separately.

## Requested, selected and observed

Record the requested model and effort, the selected binding and the observed model and effort
separately. A null observation stays null; it never counts as a match. An agent's statement
about which model it is, or prose in its answer, is never evidence. A verify result is evidence
about the run, not acceptance of the work: the ordinary exact-input execution receipts and the
independent review still decide that, and their schemas are unchanged.

One model choice per coherent slice: do not switch models per tool call. A model or effort
change alone is not a reason to rerun a check whose input, argv, configuration, toolchain and
environment are unchanged. Model and effort never change roles, permissions, write scopes,
verification gates or reviewer independence.

## Evaluating, approving and rolling back a model version

1. Add the new version as a `candidate` binding with its exact identifier. It is never routed.
2. Run an opt-in agent evaluation whose adapter requests that identifier (verified-handoff
   `references/agent-evaluation.md`), with tasks you judge representative. Keep the
   `result.json`; record its SHA-256 and the observed model in the binding's `evaluation`.
3. `status` shows `evaluation_check: verified` only when the artifact qualifies.
4. Approve explicitly: set `status` to `approved` and add `approval` (`by`, `at`). Nothing
   promotes itself; an evaluation alone grants nothing.
5. Put the binding in the routes you want. Earlier selection and verify records stay unchanged
   as history; new records carry the new policy digest.
6. Roll back by reordering or removing route entries. Only a binding that is still approved,
   still qualifies and is supported now can be selected; a revoked one is refused
   (`binding-revoked`). Revoke a binding by setting `status` to `revoked`.

No expiry, reset date, price or strength ranking is inferred. Re-evaluate when you decide the
evidence is old.

## Install, update and preservation

Both installers already export this skill's resource tree recursively. The skill, command and
specialist counts are unchanged; each installer's managed-file list grows by this skill's new
resources (the script, this reference and the example policy). Installing or updating never
creates, reads for approval or modifies the owner
policy, request, evidence or artifacts, and never activates the policy. Updating this skill's
guidance (`SKILL.md`, `references/task-contract.md`, `references/acceptance-by-task.md`) changes
the persistent controller's runtime digest: an existing controller holds new execution until
its owner reconciles explicitly under STOP. Nothing reconciles automatically.

## Persistent controller

The optional persistent controller does not apply this policy. Its providers deliberately emit
no model or effort flag, and its closed schemas carry none, so its runs inherit the native
configuration unchanged. `select` for the `delivery-controller` surface is always INCOMPLETE
(`controller-unsupported`). Do not describe controller runs as model-selected.

## Background reading

Context, not acceptance evidence:

- OpenAI, *A practical guide to building agents*
  (https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf):
  establish a baseline with a capable model, then evaluate whether smaller models still meet
  it.
- Claude model configuration (https://code.claude.com/docs/en/model-config): aliases move to
  newer versions and can differ by provider and client; full model names pin a version.
- RouteLLM (https://github.com/lm-sys/RouteLLM): learned routers on chat benchmarks. They are
  not evidence of SDLC task efficacy, and no learned router is used here.
