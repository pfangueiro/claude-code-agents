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

- Explicit roles from the user and owner or project policy prevail.
- Where owner or project policy selects the paired default: Codex coordinates and
  independently verifies; Claude implements.
- Never hardcode accounts, profiles, models or paths. Inherit configured CLI
  defaults and report the model actually observed.
- An unavailable provider or reviewer stays a named gap, for example
  `independent review: not performed (verifier provider unavailable)`. Same-provider
  self-review is never reported as cross-provider review.
- An existing configured controller owns dispatch and STOP. Without one, a direct
  CLI invocation is a fallback: it preserves identity (provider, profile, session)
  and every gate, and is not reported as managed delivery.

## Workflow

1. **Ground.** Read project instruction files and verify the request's premise
   against source. Record the exact SHA, toolchain versions and dirty state. For an
   unfamiliar repository run /repo-context first.
2. **Contract.** Write one live outcome contract
   ([task contract](references/task-contract.md)). Amend it in place when scope
   changes; do not keep parallel copies.
3. **Decompose.** Tasks under about 30 minutes, each with dependencies, a write
   scope and capability routing. Disjoint write scopes may run in parallel in
   separate worktrees; coupled work runs sequentially.
4. **Predeclare.** Name the checks and the expected changed-path manifest before
   execution starts.
5. **Execute and collect.** Gather actual terminal receipts (command, exit status,
   log location) with /verified-handoff. A pending, killed or timed-out run is not
   a pass.
6. **Reconcile.** Worktree diff, task result, report and PR must agree with the
   manifest. Explain every difference or treat it as a defect.
7. **Independent review.** The reviewer sees requirements, source, diff and raw
   artifacts before any producer conclusions. A blocker states the violated
   requirement and a reproduction; low-impact suggestions are labelled as such.
8. **Remediate.** Preserve failure evidence; do not overwrite logs. After repeated
   failure through the same mechanism, change strategy instead of retrying.
9. **Publish.** Local checks and review complete before push or PR. Merge requires
   the configured CI and approval at the exact head SHA, verified ancestry and
   existing authorization. Report implemented, reviewed, merged and deployed as
   distinct states.
10. **Continue.** Proceed through remaining authorized slices while attended. Do not
    create watchers, schedules or operational authority that was not granted.

## Recovery

- Preserve task ID, provider, profile, session, worktree, SHA and evidence.
- Incomplete provider termination (timeout, crash, quota, kill) is never completion.
- No silent retry, profile switch or billing switch.
- Clean up only identified processes this delivery owns, and only after their
  checks are terminal.
- Revalidate drift (head SHA, base, dirty state) before resuming.
- Every blocker names the gate, its owner and the next executable step.

## Project adapters

Repository-specific policy (base branch, release, issue tracking, required checks)
lives in that project's own instructions or adapter skill. Adapters add policy for
their repository; they never become universal exceptions to this procedure.

## Resources

- `references/task-contract.md` — outcome contract, task card, receipt and final
  report fields.
