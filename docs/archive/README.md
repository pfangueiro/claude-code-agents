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

The initial Codex adapter audit, review and laptop installation. Figures such as
39/36 workflows, 49/52 installed skill bundles and 21 acceptance tests are the counts
**as of that date**; the current inventory (30 source skills, 12 command templates,
13 specialists; 42 Codex workflows + 13 guides = 55 bundles, 52 implicit) lives in the
docs linked above.

- [`REVIEW.md`](codex-2026-10-12/REVIEW.md) — initial independent acceptance result.
- [`PUBLICATION-REVIEW.md`](codex-2026-10-12/PUBLICATION-REVIEW.md) — publication-time
  acceptance and the reproduced CI dependency failure.
- [`GLOBAL-VALIDATION.md`](codex-2026-10-12/GLOBAL-VALIDATION.md) — laptop user-global
  install and cross-project/CLI validation.
- [`WORKLOG.md`](codex-2026-10-12/WORKLOG.md) — the adaptation task ledger.

### `legacy-skills-integration.md` — Skills system integration (v2.1, October 2024)

The original v2.1 skills-system integration summary, from when the framework had 11
agents and the first 4 example skills. Retained for history only.

## Retired alongside this archive

- `clean-old-agents.sh` — an unused v1 helper that deleted project-local agent
  filenames. It was invoked by no installer, test, CI job or doc and was removed, not
  archived. The current installers are `install.sh` and `install-codex.sh`.
