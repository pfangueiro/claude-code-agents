---
name: delivery
description: Provider-neutral delivery procedure for implementation outcomes. Grounds work in project rules and an exact SHA, keeps one live outcome contract, splits work into short dependency-ordered tasks with write scopes, assigns implementer and independent verifier roles, collects real check receipts, and treats review, publication, merge and deployment as separately authorized states. Use when asked to implement, fix, ship or land a change through review or merge. Not for read-only questions, explanations or lookups; answer those directly without launching workers.
---

# Delivery

Carry an implementation outcome from premise to an honestly reported state. Loading
this skill is guidance only: nothing is executed, dispatched, reviewed or published
until a real tool call or process does it and its receipt is collected.

## Scope

- Use for outcomes that change source, configuration or external state.
- Read-only questions, explanations and lookups do not launch workers.
- Keep effort proportional. A one-file fix is one task; there are no fixed task
  counts, file caps or coverage targets.

## Roles

- Default: Codex coordinates and independently verifies; an actual Claude
  execution implements. Only explicit owner or project instructions override it.
- The default assigns roles; it does not start a dispatcher. A role is fulfilled
  only when a real controller or CLI invocation runs it.
- Never hardcode accounts, profiles, models or paths. By default inherit configured
  CLI defaults (model and effort included) and report the model actually observed.
  Only an active owner model policy permits a per-invocation model or effort request
  (see *Model selection*).
- An unavailable provider or reviewer stays a named gap, for example
  `independent review: not performed (verifier provider unavailable)`. Same-provider
  self-review is never reported as cross-provider review.
- An existing configured controller owns dispatch and STOP (see *Optional persistent
  controller*). Without one, a direct CLI invocation is a fallback. It preserves
  identity (provider, profile, session) and every gate, and is not reported as managed
  delivery.

## Workflow

1. **Ground.** Read project instruction files and verify the request's premise
   against source. Record the base identity: exact SHA, toolchain versions and
   dirty state. For an unfamiliar repository run /repo-context first.
2. **Contract.** Write one live outcome contract
   ([task contract](references/task-contract.md)). Amend it in place when scope
   changes; do not keep parallel copies.
3. **Decompose.** Split by dependency, responsibility and acceptance into coherent
   logical slices, not administrative fragments; about 30 minutes per task is a
   planning heuristic, never a hard slicing rule. Each task has dependencies, a write
   scope and capability routing. Disjoint write scopes may run in parallel in
   separate worktrees; coupled work runs sequentially.
4. **Predeclare.** Name the checks, the one role that owns running each, and the
   expected changed-path manifest before execution starts. Select checks and map
   requirements to discriminating evidence using
   [acceptance by task](references/acceptance-by-task.md); unavailable required
   evidence means incomplete acceptance, not a successful zero. Other roles cite an
   owned check's valid receipt rather than running the same command again.
5. **Execute and collect.** Freeze a coherent slice before running its expensive
   checks, so one run (or one predeclared set of repeated trials; see acceptance by
   task) serves every stage at that input. Gather actual terminal
   receipts (command, exit status, log location) with /verified-handoff. A pending, killed or timed-out run is not
   a pass. See *Provider lifecycle* for when a provider run counts as complete.
6. **Freeze and reconcile.** Freeze the result identity: the result commit SHA, or
   a digest of the exact dirty bytes when uncommitted. Worktree diff, task result,
   report and PR must agree with that result and the manifest. Explain every
   difference or treat it as a defect.
7. **Independent review.** The reviewer sees requirements, source, diff and raw
   artifacts before any producer conclusions. Findings and the verdict are bound
   to the input revision, base identity and frozen result identity. A blocker
   states the violated requirement and a reproduction; low-impact suggestions are
   labelled as such. The reviewer assesses coverage, the diff and raw evidence
   independently, cites valid receipts at that identity and reruns a check only for
   a named unresolved risk.
8. **Remediate.** Preserve failure evidence; do not overwrite logs. Remediation,
   a new head or input drift ends the bound verdict's coverage. Earlier receipts and
   verdicts stay unmodified as history for their original input; freeze the new
   result, run the checks applicable to it and obtain a verdict covering its delta
   (see *Freezing and new heads* in acceptance by task). After repeated failure through the same mechanism, change
   strategy instead of retrying.
9. **Publish.** Required local checks pass and an independent verdict without
   unresolved blockers covers the exact result before push or PR; otherwise hold.
   Merge requires the configured CI and approval at the exact head SHA, verified
   ancestry and existing authorization. Report implemented, reviewed, merged and
   deployed as distinct states.
10. **Continue.** Proceed through remaining authorized slices while attended. Once
    acceptance and required gates are satisfied, proceed to authorized delivery or the
    report; do not invent work to fill time. Do not create watchers, schedules or
    operational authority that was not granted.

## Provider lifecycle

- A child process exiting 0 is not completion. Completion also requires the
  provider's own terminal result to report success (not an error, permission
  denial or interruption) and no unresolved background task or later lifecycle
  event.
- Before cleanup or removing anything a run depends on, collect every predeclared
  check's actual receipt and both complete logs: the child process output and the
  provider event log.
- Record child exit code or signal separately from the admission outcome (whether
  the result is accepted as complete).
- An interrupted or incomplete run keeps its recorded outcome. A later recovery is
  a new boundary with its own receipts; it never relabels the earlier history.

## Model selection (opt-in)

Default: with no owner model policy, or an inactive one, inherit the native configuration
and claim no selection. An owner opts in once with a private policy; see
[model policy](references/model-policy.md).

- The coordinator declares each slice's risk class (routine, complex, critical) and
  required capabilities; workers cannot lower it.
- `scripts/model_policy.py select` returns PLAN_READY only for an approved, evaluated
  binding of the same provider and risk class whose exact model and effort the actual
  invocation surface is freshly observed to support. Anything else is INCOMPLETE: never a
  silent weaker model, and never a role default reported as selected.
- Model and effort never change roles, permissions, write scopes, verification gates or
  reviewer independence. Choose once per coherent slice; a model change alone is not a
  reason to rerun unchanged checks.
- `verify` compares the requested model with native or host-observed metadata. Record
  requested, selected and observed separately; null stays unknown.
- The persistent controller does not apply the policy. Its runs inherit native
  configuration, and a controller request is INCOMPLETE.

## Recovery

- Preserve task ID, provider, profile, session, worktree, SHA and evidence.
- Incomplete provider termination (timeout, crash, quota, kill) is never completion.
- No silent retry, profile switch or billing switch.
- Clean up only identified processes this delivery owns, and only after their
  checks are terminal.
- Revalidate drift (head SHA, base, dirty state) before resuming.
- Every blocker names the gate, its owner and the next executable step.

## Optional persistent controller

`scripts/controller.py` in this skill directory is an optional operator CLI for local
persistent delivery, for one repository on one host. It stays off until an owner runs
`setup` for one repository, or `init` from an owner-private policy. It never installs,
schedules or starts itself. Installing or loading this skill runs nothing.

- State lives in a private directory outside the repository, its worktrees and the
  installed skills tree (for example under `~/.local/state`). `setup`/`init` refuse
  other placements before writing anything; an unprovable layout is INCOMPLETE.
- A candidate's instruction or native policy changes are review material only. The plan
  is held INCOMPLETE for attended review; a changed policy is never adopted.
- Policy, plans and authority declarations are owner files, never worker text. Do not edit policy
  snapshots, the ledger or request files in place. A policy, runtime or rules change
  is recorded only by an explicit `reconcile` under STOP.
- `submit` only queues a request. A running controller admits it. Queued, admitted,
  executed, verified, integrated, published and merged are distinct states.
- `run` is a foreground process. `stop` records a durable STOP that only `resume`
  clears.
- External publication needs an actual approving review of the current integrated
  candidate from an owner-configured Codex profile. Without one, local work is kept and
  publication is INCOMPLETE with an attended handoff.
- One Claude account is enough: every attempt is a fresh session. Extra owner-configured
  profiles are used only when observed availability, dependencies and review capacity
  make them eligible.
- `recover` settles owned work and never removes a worktree. Only the explicit
  `cleanup-workspaces --plan-id <id> --actor <name>` under STOP removes confirmed clean,
  journal-bound worktrees of one plan; branches, commits and history are kept.
- Lost or unproven effect evidence stays `unknown` and is never retried. Nothing claims
  exactly-once delivery or process containment.

Before setup, run `python3 <this skill directory>/scripts/controller.py --help` and read
the repository's `docs/PERSISTENT-DELIVERY.md` operator guide.

## Project adapters

Repository-specific policy (base branch, release, issue tracking, required checks)
lives in that project's own instructions or adapter skill. Adapters add policy for
their repository; they never become universal exceptions to this procedure.

These procedures are guidance, not an enforcement engine; compliance is shown by
the receipts, not assumed.

## Resources

- `references/task-contract.md` — outcome contract, task card, receipt, review
  and final report fields.

- `references/acceptance-by-task.md` — proportional behavioral acceptance profiles,
  check selection and ownership, receipt reuse and new-head evidence.
- `references/repository-measurements.md` — optional measurement and task-grounding limits.
- `references/model-policy.md` and `references/model-policy.example.json` — opt-in model
  selection and model-version lifecycle (inactive example).
- `scripts/model_policy.py` — read-only model-policy `status`, `select` and `verify`.
- `scripts/controller.py` — optional local persistent-delivery operator CLI (off until
  set up).
