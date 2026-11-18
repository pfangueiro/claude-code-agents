# Acceptance evidence by task

Choose the smallest complete set of checks that can distinguish success from a
plausible wrong result. Project and owner policy selects required gates; these
profiles add relevant questions, not universal tool, coverage or review quotas.
Record each requirement, affected contract, check, input identity and receipt.
Mark a requirement unresolved when no suitable oracle exists. Keep source-proven
conclusions separate from runtime captures and unverified hypotheses.

| Work | Required questions and discriminating evidence |
| --- | --- |
| Feature | Define acceptance examples before implementation, including invalid/boundary inputs; check affected integration and consumer contracts, compatibility and failure behavior. Existing behavior remains intact. |
| Bug fix | Reproduce the trigger and obtain a failing regression test before the fix; show the test passes afterward and unaffected cases still pass. Establish root cause, not only the absence of a crash. Independently confirm consequential test oracles. |
| Refactor | Preserve observable behavior, public contracts, ordering, error semantics and data shape; exercise callers and valid alternative implementations. A smaller diff alone is not evidence. |
| Performance | Define workload, environment, baseline and target; repeat comparable measurements and report variance, input sizes and resource costs. Verify correctness alongside speed. One fast run or an asymptotic guess is insufficient. |
| Support investigation | Capture actual symptoms and authorized read-only runtime evidence; distinguish repository failure from runtime, credentials, service availability and time limits. Test competing hypotheses. Preserve unknowns and contradicting evidence; a diagnosis does not authorize live repair. |
| Deployment | Pin the artifact/source and environment, verify configured CI, preflight, health and user-journey checks, and recovery/rollback evidence. Deployment and rollback each require their own operational authority; a code-review approval grants neither. |

Formatting, lint, types/build and tests answer different questions. Discover and
honor actual project commands. Run independent checks despite an unrelated format
failure; record dependencies that genuinely prevent execution. Missing required
evidence is INCOMPLETE; an actual blocking failure is FAIL. A justified inapplicable
check is NOT_APPLICABLE, not an unavailable check renamed to obtain PASS.

Use verified-handoff for exact-input execution receipts and delivery for independent
review/publication. Receipts alone do not establish that the chosen tests cover the
requirement. For fragile guards, prove a representative defect is rejected and a
safe counterexample is accepted; avoid tests that merely mirror implementation.

When the subject under evaluation is agent or workflow guidance itself, judge the
delivered outcomes, separately from how closely instruction text was followed or
whether an installer works. No provider call or additional runtime is required for
an ordinary delivery. Repository measurements are optional context, never an
acceptance verdict; see [repository-measurements.md](repository-measurements.md).
An opt-in baseline/candidate comparison is described in verified-handoff's
`references/agent-evaluation.md`; it supplements, never replaces, the task-specific
acceptance above.

## Selecting checks

Select checks by what the change can affect and by the project's actual gates, not a
blanket build or full suite for every edit:

- Behavior: tests that exercise the changed behavior, its affected callers,
  integration/consumer contracts and security boundaries. A bug-fix regression test
  is RED before the fix and GREEN after.
- Build, type check or wider suite: when project policy or CI requires it, or when
  the change can affect what it covers (shared code, types, build configuration,
  dependencies, generated output).
- Prose: a trivial, reversible, nonbehavioral wording change needs no new test. Text
  that a checker, installer, exporter or consumer reads is behavior for that reader
  and keeps its check.
- Required gates: project-required CI and a repository's own maintenance checks stay
  required; a faster delivery never drops or weakens them.
- Edit-time feedback, such as a post-edit lint hook, is not an acceptance check.

## One plan, one owner per check

The delivery's predeclared plan lists each check once with the role that runs it.
Other roles cite that receipt instead of running the same command. A receipt is
reusable only when every one of these matches the current need: scope and exact
input identity (the commit SHA; for source-only work, the recorded content fingerprint
or snapshot of the relevant bytes plus a description, compared with the current
relevant bytes and context — a label or description alone never establishes identity,
and no other SHA's receipt stands in), argv and cwd, the check's
configuration, dependencies and toolchain, and any environment or freshness the
result depends on (live health, authentication, services, time-sensitive data). A
failed, unavailable, pending, unknown or stale result is never reused as PASS. One
valid receipt can feed several stages at the same input (task acceptance, quality
gate, review, pre-push) without repeating the command.

Verifying a receipt checks its structure and recorded input; it executes nothing and
does not show that the current source or environment still match. That verification
checks history and logs, not current applicability: whoever reuses a receipt compares
its recorded identity with the current input. Reviewers
independently assess requirement coverage, the diff and the raw logs. Rerun a check
only for a concrete unresolved risk — a missing or contradictory log, suspected
flakiness, an input or environment the receipt does not cover, or a check that does
not exercise the change — and state that reason first. A changed role or session is
not a reason.

Declared repetition is not a rerun. When the check design itself requires repeats —
benchmark samples (see Performance above), sampling, a reliability or flakiness
investigation, or a freshness probe of live state — predeclare the reason and the
required trials, record each trial's identity and keep every actual receipt, failures
included. Never rerun until a failure happens to turn green, and never report one
sample in place of the agreed set. This adds no receipt field, form or service.

## Freezing and new heads

Freeze a coherent slice, and later the final candidate, before running its expensive
checks. A receipt or verdict covers only the exact input it names. After a new head,
the original receipts, logs and verdicts stay unmodified as truthful history for
their original input. A v1 receipt cannot be relabelled to another SHA, even when the
trees match, and no cross-SHA equivalence reuse is defined, so the new head needs a
current receipt for every applicable check and a new independent verdict covering its
delta. That includes checks whose result depends on Git metadata (for example an
installer that embeds the source SHA) and live health, authentication or environment
probes. A delta review may use prior findings and evidence, but it is an explicit
decision at the current head, never automatic approval or a CI bypass.
