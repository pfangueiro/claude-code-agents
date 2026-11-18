# Task contract

Field lists for the live outcome contract and its tasks. Fill only what applies;
omit empty sections rather than writing placeholders.

## Outcome contract

One per delivery, amended in place.

- **Outcome:** the observable result that counts as done.
- **Input revision:** the requirements and instructions version this delivery serves.
- **Premise:** facts verified in source, with file and line.
- **Base identity:** repository, branch, exact SHA, toolchain versions, dirty state.
- **Roles:** coordinator, implementer, independent verifier, and where each
  assignment came from (default, explicit owner instruction, project instruction).
- **Authorization:** effects allowed (commit, push, PR, merge, release, deploy)
  and who granted them. Unlisted effects are not authorized.
- **Checks:** predeclared commands, the gate each one feeds and the one role that
  runs it; other roles cite its receipt (reuse rules in `acceptance-by-task.md`).
- **Manifest:** expected changed paths.
- **Gaps:** unavailable providers, reviewers or checks, by name.

## Task card

- **ID** and one-line goal: one coherent slice by dependency, responsibility and
  acceptance; about 30 minutes is a planning heuristic, not a limit.
- **Depends on:** task IDs that must be terminal first.
- **Write scope:** paths this task may change; scopes of parallel tasks are disjoint.
- **Worktree** and base SHA.
- **Routing:** provider role and capabilities or skills the task needs.
- **Checks:** subset of predeclared checks this task must pass.

## Receipt

Recorded by the process that ran the check, never reconstructed from memory.
Another role cites an existing valid receipt by location instead of rerunning the
check; a receipt is never copied, edited or relabelled to another input.

- Task ID, provider, profile, session, worktree, base SHA.
- Command, start and end time, child exit code or signal.
- Provider terminal result and any unresolved background task or later event.
- Log locations: child process output and provider event log, both complete.
- Admission outcome, recorded separately: passed, failed, timed out, killed,
  interrupted or not run.

## Result identity

- Result commit SHA, or a digest of the exact dirty bytes when uncommitted.
- When it was frozen and which receipts it was reconciled against.

## Review identity

- Reviewer, provider and session.
- Input revision, base identity and result identity the review covered.
- Verdict and findings, each bound to that result identity.
- Covers only that result identity. After remediation, a new head or input drift,
  keep the superseded verdict and its receipts unmodified as history and obtain a
  new verdict covering the delta at the new identity; prior findings may inform it,
  never approve it automatically.

## Final report

- Changed paths, compared with the manifest.
- Base, result and review identities.
- Exact commands and statuses from receipts.
- State per effect: implemented, reviewed, merged, deployed — each yes or no.
- Review findings: blockers with requirement and reproduction, then suggestions.
- Remaining blockers: gate, owner, next executable step.
- Limitations and integration dependencies.
