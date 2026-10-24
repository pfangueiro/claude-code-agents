---
description: Run the project's required quality checks with evidence and explicit incomplete outcomes
argument-hint: "[path] [--fix] [--strict]"
---

Check the requested scope using the project's actual commands and acceptance policy.
`--fix` explicitly permits configured formatter/linter fixes; without it use check
mode. `--strict` treats warnings as failures only within this requested gate.

1. Read applicable project instructions and manifests; use `/repo-context` when
   unfamiliar. Record input SHA or dirty/archive digest, changed paths, affected
   callers/contracts and tool versions. Discover tools rather than assume names.
2. Predeclare required format, lint, type/build and behavioral checks, their literal
   argv, scope and expected evidence. Prefer existing package scripts, CI commands
   and installed project tools. Do not download tools, use fetching `npx` commands,
   invent a test command or replace house tooling with a preferred ecosystem default.
3. Select tests by affected behavior and dependencies, including integration and
   consumer contracts. Nearby test files alone are insufficient. Consult the delivery
   skill's `references/acceptance-by-task.md`. An absent suite is a gap to address for
   consequential behavior; code coverage is not a correctness verdict or a universal
   percentage requirement.
4. Run configured checks and collect exact-input receipts with `/verified-handoff`.
   Keep failure logs. Run independent behavioral checks even if formatting fails;
   skip only a dependent check that cannot execute, report it UNAVAILABLE and name
   the check it depends on. A missing runtime, credential, registry or time budget is
   **UNAVAILABLE** with attribution, not a repository defect or a successful empty
   check. Do not repair authentication, install dependencies or change accounts
   without existing authority.
5. For each check report **PASS**, **FAIL**, **UNAVAILABLE**, or **NOT_APPLICABLE**.
   NOT_APPLICABLE requires a project-policy or change-scope reason declared before
   execution; never relabel an unavailable required check to make the gate green.
   Include argv, input identity, receipt/log location, actual counts where available,
   and environmental limitations. A skipped required check remains incomplete.
6. Overall **FAIL** when an applicable check actually fails; otherwise **INCOMPLETE**
   when required evidence is absent, unavailable, interrupted or unverified;
   otherwise **PASS** only for the declared completed scope. Unknown requirements
   also make the gate INCOMPLETE. Verify the required receipt manifest before PASS.
   Report failure and missing evidence together when both exist. No successful
   metric can cancel a blocking failure. PASS does not authorize a commit, review,
   merge or deployment and does not certify untested behavior.
7. After explicit fixes, inspect the diff for scope drift and rerun affected checks
   against the new input. Prior receipts do not cover changed bytes. Preserve earlier
   failures; report repaired and as-found outcomes separately.

Use a concise table of check, requirement, outcome, evidence and limitation, followed
by the overall outcome and outstanding actions. Never manufacture a grade or a zero
for work that did not run. The existing receipt schema stays unchanged; this is the
interpretation of required scope, not a new receipt format or enforced sandbox.
