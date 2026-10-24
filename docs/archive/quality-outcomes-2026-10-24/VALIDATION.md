# Quality-outcomes acceptance record

> **Historical snapshot — recorded 2026-10-24.** Fixed observations at the revisions named
> below. It does not certify any later commit, branch, documentation change or install,
> including the commit that added this file. Raw receipts and provider, account and host
> details are private and are not reproduced here. See [docs/archive/README.md](../README.md)
> for scope and the [current docs](../../../README.md) for the live framework. No release or
> version bump accompanied this change.

## Revisions

| Role | Revision |
|---|---|
| Reviewed source implementation head | `f02861da2a30f23dc2562bd3a6907df0fcb63b7d` |
| Merged as | [PR #9](https://github.com/pfangueiro/claude-code-agents/pull/9), squash commit `3d501c852406ff7ee30420ae5d7afc6de580d674` on `main` |
| Git tree of both commits | `8c02044ee33369a1fce4f799b8c8783fce8129c5` |

Both commits carry the same tree, so the merged content is byte-identical to the reviewed
head.

## Repository checks at the reviewed head

| Check | Observed |
|---|---|
| Test suite | 442 tests passed |
| Codex adapter mutation controls | 29 passed |
| Claude validator mutations (`tests/gap`) | 27 detected, each with its restored safe control passing |

## CI

- First `main` run at `3d501c8`:
  [run 40107026381](https://github.com/pfangueiro/claude-code-agents/actions/runs/40107026381) —
  all 5 jobs succeeded.
- An earlier PR CI attempt failed: a restored control for gap case 08 reported `WRONGFAIL`
  (the validator failed, but not with the expected line). An unchanged-source debug repeat
  and the first `main` run both passed. **The root cause is unknown**; this record does not
  call it fixed.

## Native paired pilot

- Design: six synthetic tasks × 2 trials × 2 instruction sets (baseline and candidate) =
  24 native Claude runs. Observed model: `claude-opus-5-5`.
- Result: baseline 12/12, candidate 12/12. **No efficacy gain was demonstrated**, and a pilot
  of this size is not evidence of effectiveness either way.

## User-global rollout at `3d501c8`

| Observation | Value |
|---|---|
| Claude source payload files installed | 94 |
| Codex adapter owned files (not the workflow count) | 147 |
| Claude delivery-manifest owned files | 14 |
| Receipts independently verified | 11 install/check receipts plus 3 preview receipts |
| Selected personal or unplanned changes | 0 |
| Obsolete files removed | None |
| Full installed Claude validator | 257 checks: 255 passed, 2 known fork-reference warnings, 0 errors |
| Refreshed-session `validate.sh --quick` | 41/41 passed, 0 warnings, 0 errors |
| Installed correct/wrong offline evaluation controls | Passed for both integrations, in a disposable `HOME`, with no provider calls |

## Not claimed

- Authenticated native execution of every workflow.
- Runtime parity between the Claude and Codex editions.
- An OS sandbox around evaluation adapters or hooks.
- Any measured quality improvement.
