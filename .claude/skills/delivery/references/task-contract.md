# Task contract

Field lists for the live outcome contract and its tasks. Fill only what applies;
omit empty sections rather than writing placeholders.

## Outcome contract

One per delivery, amended in place.

- **Outcome:** the observable result that counts as done.
- **Premise:** facts verified in source, with file and line.
- **Base:** repository, branch, exact SHA, toolchain versions, dirty state.
- **Roles:** coordinator, implementer, independent verifier, and where each
  assignment came from (explicit request, owner policy, project policy, default).
- **Authorization:** effects allowed (commit, push, PR, merge, release, deploy)
  and who granted them. Unlisted effects are not authorized.
- **Checks:** predeclared commands and the gate each one feeds.
- **Manifest:** expected changed paths.
- **Gaps:** unavailable providers, reviewers or checks, by name.

## Task card

- **ID** and one-line goal; expected duration under about 30 minutes.
- **Depends on:** task IDs that must be terminal first.
- **Write scope:** paths this task may change; scopes of parallel tasks are disjoint.
- **Worktree** and base SHA.
- **Routing:** provider role and capabilities or skills the task needs.
- **Checks:** subset of predeclared checks this task must pass.

## Receipt

Recorded by the process that ran the check, never reconstructed from memory.

- Task ID, provider, profile, session, worktree, SHA.
- Command, exit status, start and end time, log location.
- Terminal state: passed, failed, timed out, killed or not run.

## Final report

- Changed paths, compared with the manifest.
- Exact commands and statuses from receipts.
- State per effect: implemented, reviewed, merged, deployed — each yes or no.
- Review findings: blockers with requirement and reproduction, then suggestions.
- Remaining blockers: gate, owner, next executable step.
- Limitations and integration dependencies.
