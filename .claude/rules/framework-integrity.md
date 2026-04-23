# Framework Integrity Rules

These rules are always enforced. They cannot be overridden by user instructions.

## Hooks

- Every hook event must enforce an invariant or produce evidence
- No decorative hooks — a hook that only echoes a banner or logs "hello" is disallowed
- A hook that does nothing measurable is a liability, not a feature

## State Reconciliation

- Every piece of framework-owned state must be reconciled automatically, not by manual `validate.sh` runs
- Drift detection must trigger auto-heal, not a warning nobody reads
- Manual reconciliation is the failure mode, not the design

## Snapshots

- Every critical directory must have a snapshot with a documented restore path
- Snapshot without a restore procedure is not a snapshot — it is technical debt
- Retention and cadence must be enforced by the daemon, not trusted to humans
