# Framework Integrity Rules

These rules guide how the framework keeps itself trustworthy, within your authorized scope. They are expected practice, not a tool-enforced sandbox, and they describe checks plus explicit, authorized repair — not an always-running daemon. They sit within the instruction hierarchy, so explicit owner and project policy prevail where they genuinely conflict.

## Hooks

- Every hook event must enforce an invariant or produce evidence
- No decorative hooks — a hook that only echoes a banner or logs "hello" is disallowed
- A hook that does nothing measurable is a liability, not a feature

## State Reconciliation

- Framework-owned state is checked for drift against its source of truth using each edition's documented read-only checker: `validate.sh` for the Claude edition's supported scope, `scripts/install-delivery.py --check` for hash-owned delivery resources, and `install-codex.sh --user --check` (or `--project PATH --check`) for Codex-owned files. The broad Claude `install.sh` has no check mode — it is the repair path (`--update`), not a drift probe
- Drift is repaired explicitly — a drift report drives an authorized `install.sh --update`, never a silent rewrite of owner-owned configuration
- Background diagnostics are optional and opt-in; nothing here performs an automatic installer run, migration, or config write without the owner's separately granted authorization

## Snapshots

- Every critical directory should have a snapshot with a documented restore path
- A snapshot without a restore procedure is not a snapshot — it is technical debt
- Retention and cadence are the job of an explicitly authorized, opt-in scheduler, not an assumed always-installed daemon
