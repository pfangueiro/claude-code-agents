# Documentation archive

These are **historical snapshots**, preserved for provenance. Each records a specific
past milestone — its dates, component counts, SHAs, payload fingerprints and test
results reflect that moment and are kept verbatim. **None of them is a current check or
a description of the framework as it stands today.**

For the live framework use the current docs: [README.md](../../README.md),
[INSTALL.md](../../INSTALL.md), [AGENTS.md](../../AGENTS.md), [MEMORY.md](../../MEMORY.md),
[codex/README.md](../../codex/README.md) and the [feature matrix](../../codex/FEATURES.md).
Current defect taxonomy and contribution rules are in
[docs/FAILURE-MODES.md](../FAILURE-MODES.md) and [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Contents

### `codex-2026-10-12/` — Codex adaptation acceptance (2026-10-12)

The initial Codex adapter audit, review and laptop installation. The figures it
records — e.g. 39 workflows (36 implicit + 3 explicit-only), 49 **implicit** skills out
of 52 **total** installed skill bundles, and 21 acceptance tests — are the counts **as of
that date**. For the current inventory, see the docs linked above; this index deliberately
does not restate live counts.

- [`REVIEW.md`](codex-2026-10-12/REVIEW.md) — initial independent acceptance result.
- [`PUBLICATION-REVIEW.md`](codex-2026-10-12/PUBLICATION-REVIEW.md) — publication-time
  acceptance and the reproduced CI dependency failure.
- [`GLOBAL-VALIDATION.md`](codex-2026-10-12/GLOBAL-VALIDATION.md) — laptop user-global
  install and cross-project/CLI validation.
- [`WORKLOG.md`](codex-2026-10-12/WORKLOG.md) — the adaptation task ledger.

### `legacy-skills-integration.md` — Skills system integration (v2.1, October 2024)

The original v2.1 skills-system integration summary, from when the framework had 11
agents and the first 4 example skills. Retained for history only.

### `quality-outcomes-2026-10-24/` — Quality-outcomes acceptance (2026-10-24)

The evidence-based quality, review and evaluation change: reviewed head `f02861d`, squashed
as `3d501c8` on `main` with an identical tree, its repository checks and CI, a small native
paired pilot that demonstrated no efficacy gain, and user-global rollout observations at
`3d501c8`. Counts and verdicts are as observed at those revisions.

- [`VALIDATION.md`](quality-outcomes-2026-10-24/VALIDATION.md) — sanitized acceptance
  record. Raw receipts stay private.

## Retired alongside this archive

- `clean-old-agents.sh` — an unused v1 helper that deleted project-local agent
  filenames. It was invoked by no installer, test, CI job or doc and was removed, not
  archived. The current installers are `install.sh` and `install-codex.sh`.
