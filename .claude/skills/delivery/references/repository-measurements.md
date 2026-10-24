# Optional repository measurements

A repository inventory can inform unfamiliar-project discovery and propose useful
engineering tasks. It is not a code-quality grade, acceptance verdict, valuation or
mandatory step on every edit. LOC, complexity, commit volume, task counts, coverage
and positive runnability indicators cannot cancel a failing requirement.

Before running an external auditor, inspect its actual version and execution path.
Get authority for the effects it performs: a nominal measurement may execute install
scripts, modify the checkout, fetch dependencies and disclose source/history to an
account's provider. Use a disposable copy and the host's actual execution boundaries.
A scratch HOME, cleaned environment or read-only filesystem setting is not a complete
OS sandbox or a guarantee against reading credentials, network use or escaped child
processes. Never silently switch provider, account, model or billing.

Order matters. Finish source-only readers and inventories before any install, build
or runtime probe can change the measured tree. If they must run concurrently, give the
probe its own disposable copy. Record which inputs were measured as found and which
after a repair or install, and attribute each result to its input.

Keep deterministic observations, executed outcomes and model judgments separate.
For every measurement retain its definition, source/input digest, collector/model/
harness versions, scope, caps and failure attribution. Unavailable parsers, missing
runtimes, credentials, registries and time budgets produce unknown values with a
reason, never a successful zero or an invented repository failure. Schema-valid
JSON establishes structure, not the truth of the model's statements. A model's
requested name is distinct from the model actually observed; record unknown when
it cannot be observed. Do not pool results across changed measurement definitions.

Before adopting a proposed task or review finding:

- Verify each cited file/symbol/commit exists at the stated revision, that paths
  remain within the permitted tree without symlink/traversal escape, and that the
  proposed behavior follows from the actual source and requirements.
- Verify claimed test strength using relevant assertions or an executed behavioral
  check. A model saying tests are strong is not test evidence. Deduplicate claims;
  a longer enumerated list is not necessarily more verified material.
- Keep sufficient private local grounding to investigate the claim. When exporting,
  use an allowlisted report with deliberate data minimization, not arbitrary source,
  paths, transcripts, author identities or secret values. An export allowlist does
  not undo source/history already disclosed to a model provider.
- Keep measured-as-found and repaired outcomes separate. No automatic source repair,
  authentication change or live-data operation is implied by auditing authority.

For benchmark replay, validate the task statement and acceptance tests with expert
judgment. Allow valid alternate solutions; reject incomplete fixes. Give the solver
only the pre-change fixture and intended requirements. Do not expose future refs,
gold patches, hidden grader files or prepared history containing the answer. Keep
sensitive real-project fixtures private; any public evaluation example must be
synthetic and must not import an external auditor's implementation or data.
