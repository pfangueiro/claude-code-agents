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
