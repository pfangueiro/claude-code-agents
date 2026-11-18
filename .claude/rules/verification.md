# Verification Rules

These rules guide verification within your authorized scope — expected practice after every change, not a tool-enforced gate. They sit within the instruction hierarchy, so explicit owner and project policy prevail where they genuinely conflict.

## After Every Implementation

- After implementing a feature or fix, verify it before reporting completion
- Select the smallest COMPLETE set of checks: tests that exercise the changed behavior and its affected callers, integration/consumer contracts and security boundaries, plus every gate the project or its CI requires — not a blanket build or full suite for every edit. The delivery skill's `references/acceptance-by-task.md` is the shared reference for check selection, ownership, receipt reuse and new-head evidence
- Run the build or type check when the project requires it or the change can affect what it covers (shared code, types, build configuration, dependencies)
- If changed behavior has no test, write one that exercises it; a trivial, reversible, nonbehavioral prose edit needs no new test unless a checker or consumer reads that text
- When no test exists and the change is non-trivial, prefer an INDEPENDENT reviewer (a fresh-context sub-agent or a different agent) to author or confirm the validating test — the producer writing AND grading its own oracle is self-assessment, not verification
- Run each check once per exact input by default: cite an existing valid receipt instead of repeating it, and name the concrete unresolved risk before rerunning one. Repetition that is part of the predeclared check design — repeated benchmark samples, sampling, a reliability/flakiness investigation or a freshness probe — is allowed: keep its reason, the required trial identity and every actual receipt; never rerun until a failure happens to turn green, and never substitute one sample for the agreed set (delivery `references/acceptance-by-task.md`)
- Edit-time hook feedback (for example post-edit lint) is not verification; the selected checks still run
- For UI changes, take a screenshot or describe the visual result

## Verification Standards

- "It should work" is not verification — run it and confirm
- A passing build alone is not sufficient — verify the specific behavior changed
- If tests fail after your change, fix them before reporting completion
- Never mark a task complete without stating what verification was performed

## Test-Driven Fixing

- For bug fixes: write a failing test that reproduces the bug BEFORE fixing it
- The fix is verified when the previously-failing test passes
- This prevents regressions and proves the fix addresses the actual problem

## Honest Measurement

- Distinguish a real change from measurement noise — a "10% faster" claim from a single timed run is noise, not a result. For variable metrics (timings, benchmarks), re-measure or require the delta to exceed run-to-run variance before claiming it.
- Never report a number you did not measure. If a figure is inferred or projected rather than observed, label it as an estimate — do not present it as measured.
- State the basis of every quantitative claim: what was run, how many times, against what baseline. "Faster" without a before/after is an opinion.
- Don't claim more precision than the method supports — round to what the measurement can actually resolve.

## Required scope and evidence gaps

- Predeclare required checks against the actual task and project policy. Use the
  delivery acceptance-by-task resource for feature, fix, refactor, performance,
  investigation and deployment evidence; honor dependency and consumer contracts.
- An unavailable required check makes verification INCOMPLETE. A repository-attributed
  failure is FAIL; an inapplicable check needs a declared scope/policy reason.
  Neither missing evidence nor positive inventory/coverage counts establish PASS.
- Keep confirmed source findings, runtime reproductions and unverified hypotheses
  distinct. Validate review findings against safe counterexamples; no issue quota,
  invented grade or confidence score substitutes for evidence.
