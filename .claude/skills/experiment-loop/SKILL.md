---
name: experiment-loop
description: Autonomous experimentation pattern for iterative code improvement. Describes the modify-commit-run-evaluate-keep/discard loop generalized from autoresearch. Auto-activates on optimize, experiment, improve iteratively, benchmark, metric-driven, A/B test approaches, autonomous improvement, iterate until better.
---

# Experiment Loop Pattern

## Overview

The experiment loop is a systematic approach to iterative code improvement where each change is measured against a baseline metric and kept only if it improves the result. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) and generalized for any measurable code quality metric.

## The Core Pattern

```
0. VALIDATE  → Prove the tool exists and actually RAN. No valid run, no metric.
1. DEFINE    → Choose a measurable metric, its noise floor, and constraints
2. BASELINE  → Measure current state; pin tool path + version + accepted exit codes
3. MODIFY    → Make one targeted change
4. MEASURE   → Re-run step 0 FIRST, then re-evaluate the metric
5. GUARD     → Run build + tests. If they fail → REVERT, whatever the metric says
6. DECIDE    → Keep only if the gain EXCEEDS the noise floor; otherwise revert
7. LOG       → Record the change, the metric, and BOTH gate results
8. REPEAT    → Go to step 3 (until done or plateau)
```

Steps 0, 5 and 6 are the difference between an improvement loop and a loop that
optimizes for breaking the toolchain. They are specified in
**Mandatory Preconditions** below and are not optional.

## When to Use This Pattern

**Good fit:**
- Reducing lint warnings or type errors in a codebase
- Improving test coverage for a module
- Reducing bundle size or build time
- Optimizing database query performance (measurable via EXPLAIN ANALYZE)
- Improving accessibility scores (Lighthouse, axe)
- Reducing code complexity (cyclomatic complexity metrics)

**Bad fit:**
- Subjective improvements (readability, "cleaner" code)
- Exploratory work (no clear metric)
- Feature development (no single metric captures correctness)
- Security fixes (can't reduce to one number)

## Requirements for the Pattern

For the loop to work, you need all five. Missing any one of them makes the loop actively
harmful — it will confidently report as "improvements" things that are breakage or noise.

1. **A metric that can be proved valid** — not merely "a command that outputs a number." The tool must be present and must actually have run. A number from a tool that never ran is not a measurement. See **Gate 1**.
2. **A known noise floor** — the run-to-run spread of the metric on an *unchanged* tree. Any gain smaller than that spread is noise. Deterministic counts have a noise floor of 0; wall-clock metrics do not. See **Gate 3**.
3. **A correctness gate independent of the metric** — a build and test command whose pass/fail is authoritative. The metric never overrules it. See **Gate 2**.
4. **Controlled experiments** — each change is isolated. One modification per iteration, measured independently.
5. **Automatic evaluation** — the keep/discard decision is mechanical *once gated*: gates pass AND gain exceeds the noise floor? Keep. Otherwise revert. "Mechanical" describes the decision rule; it is not a licence to skip the gates.

## Mandatory Preconditions

**No valid run, no metric.** A number produced without these three gates is void, and a loop
that scores void numbers is a loop that rewards destroying the toolchain.

### Gate 1 — the tool must exist and must have RUN

**Root cause:** a shell pipeline reports the exit status of its *last* command. Every metric
command in the table below ends in `wc -l`, `grep -c`, `jq`, or `awk`, so the tool's own exit
status is discarded. A missing compiler and a clean compile become indistinguishable.

Executed proof, on a machine with no TypeScript installed:

```
$ which tsc
tsc not found
$ tsc --noEmit 2>&1 | grep error | wc -l
       0        # <- a PERFECT score
$ echo $?
0              # <- and the pipeline "succeeded"
```

Deleting the compiler outscores every genuine optimization. This is a property of the pipeline
shape, not of `tsc` — the `eslint`, `vitest`, `du` and `time` rows all have the same hole.

Two tempting guards that do **not** work:

- `set -o pipefail` — `grep` exits 1 when it matches nothing, so a *clean codebase* and a
  *missing tool* both yield rc 1. Verified: both cases return 1.
- `${PIPESTATUS[0]}` — a bash-ism. Verified: in bash it is `127`; in zsh `PIPESTATUS[0]` is
  empty (the array is `pipestatus`, and it is 1-indexed).

Use the portable two-step capture, which returns 127 in both shells:

```bash
# METRIC_OK_RC: space-separated exit codes that mean "the tool RAN".
# Default 0 = fail closed. Record the real set at BASELINE — linters and compilers
# exit non-zero when they FIND problems, and that is a successful run, not a failure.
: "${METRIC_OK_RC:=0}"

metric_run() {            # metric_run <tool> <cmd...>  -> raw output, or rc 2 = VOID
  tool=$1; shift
  command -v "$tool" >/dev/null 2>&1 || { echo "VOID: '$tool' not on PATH" >&2; return 2; }
  raw=$("$@" 2>&1); rc=$?
  case " $METRIC_OK_RC " in
    *" $rc "*) ;;
    *) printf 'VOID: %s exited %s\n%s\n' "$tool" "$rc" "$raw" >&2; return 2 ;;
  esac
  printf '%s\n' "$raw"
}

metric_value() {          # metric_value <parser...>  (reads stdin) -> number, or rc 2 = VOID
  v=$("$@"); v=$(printf '%s' "$v" | tr -d '[:space:]')
  case "$v" in ''|*[!0-9.]*) echo "VOID: '$v' is not a number" >&2; return 2 ;; esac
  printf '%s\n' "$v"
}
```

Every measurement goes through it — never call the bare pipeline:

```bash
export METRIC_OK_RC="0 1 2"                                        # pinned at BASELINE
raw=$(metric_run tsc tsc --noEmit)                        || exit 2   # VOID -> stop
val=$(printf '%s\n' "$raw" | metric_value grep -c 'error TS') || exit 2
```

Verified behaviour of that guard across all four toolchain states:

| Toolchain state | Guard result |
|---|---|
| `tsc` deleted | `VOID: 'tsc' not on PATH` — **no metric** |
| `tsc` present, 2 real errors (exit 2) | `METRIC = 2` |
| `tsc` present, codebase genuinely clean (exit 0) | `METRIC = 0` — a real zero |
| `tsc` present but crashes (exit 139) | `VOID: tsc exited 139` — **no metric** |

**VOID is not zero.** Never record it as an improvement, a regression, or a plateau. A VOID
measurement stops the loop: fix the toolchain, then resume. Pin the tool at BASELINE
(`command -v <tool>` plus `<tool> --version`) and re-assert both every iteration, so a change
that removes, shadows or downgrades the tool fails the gate instead of winning it.

### Gate 2 — regression gate: tests outrank the metric, always

After every MODIFY, run the project's build and test command **before** looking at the metric.

- Build or tests **fail** → **REVERT immediately.** Do not compare metrics; a broken tree has no
  score. This holds *even when the metric improved* — especially then, because "metric improved,
  tests broke" is the signature of metric gaming.
- The test command is itself subject to Gate 1. A test runner that is absent, crashed, or
  collected zero tests has not "passed" — that is VOID, not green.
- Record the gate result in the log beside the metric. An iteration logged without a gate result
  is unverified, and unverified iterations may not be counted as improvements in the final report.

### Gate 3 — noise floor: a delta inside the noise is not a result

Before the first iteration, measure the metric **at least 5 times with no code change at all**
and record the spread. Only a delta larger than that spread counts as a change.

Measured here — 10 runs of one identical, completely unmodified workload:

```
0.0542 0.0609 0.0522 0.0519 0.0553 0.0516 0.0507 0.0535 0.0520 0.0542
n=10  mean=0.0537s  stdev=0.0028s (5.2%)  spread=0.0102s (19.0%)
```

With **zero** code change, a mechanical keep/revert would have "KEPT" every run below the mean
and "REVERTED" every run above it — manufacturing a 19% swing out of nothing.

| Metric class | Examples | Noise floor | Rule |
|---|---|---|---|
| Deterministic counts | lint warnings, type errors, TODO count | 0 | Any non-zero delta is real |
| Deterministic sizes | `du -sk dist/` with no content hashing | ~0 | Any delta beyond byte-level jitter is real |
| Wall-clock / sampled | build time, benchmark ms, query latency | **must be measured** | Keep only if delta > max(2 × stdev, observed spread); otherwise log **UNCHANGED** and revert |

For wall-clock metrics, re-measure the candidate at least 3 times and compare **medians**, not
single runs. If the baseline and candidate distributions overlap, the verdict is UNCHANGED — not
a win. A percentage improvement smaller than the measured spread must never be reported as a
result.

## Integration with Framework Commands

| Command | Role in the Loop |
|---------|-----------------|
| `/optimize <metric>` | Runs the full loop automatically |
| `/checkpoint` | Creates save points to revert to |
| `/build-fix` | Uses the same regression guard pattern |
| `/tdd` | Similar loop structure (RED-GREEN-REFACTOR) |
| `/quality-gate` | Provides metrics (lint, types, tests) |

## Metric Selection Guide

### Built-In Metrics

> **These are measure *steps*, not metrics.** Every command below ends in a counter that
> discards the tool's exit status, so every row returns a perfect score when its tool is
> missing. Run each one through `metric_run` / `metric_value` from **Gate 1**; a bare
> invocation of any row is not a measurement.

| Metric | Command | Direction | Good For |
|--------|---------|-----------|----------|
| Lint warnings | `eslint . --format json` | Lower is better | Code quality |
| Type errors | `tsc --noEmit 2>&1 \| grep error \| wc -l` | Lower is better | Type safety |
| Test coverage | `vitest --coverage --reporter=json` | Higher is better | Test completeness |
| Bundle size | `du -sk dist/` | Lower is better | Frontend performance |
| Build time | `time npm run build` | Lower is better | Developer experience |
| Complexity | `npx eslint . --rule 'complexity: error'` | Lower is better | Maintainability |

### Custom Metrics

Any command that outputs a number works:

```bash
# Count TODO comments
grep -r "TODO\|FIXME\|HACK" src/ | wc -l

# Count functions without JSDoc
grep -rP "^(export )?(async )?function" src/ | wc -l
# minus
grep -rP "@param|@returns" src/ | wc -l

# Database query time
psql -c "EXPLAIN ANALYZE SELECT ..." | grep "Execution Time" | awk '{print $3}'
```

## Anti-Patterns

### Breaking the Toolchain
- Deleting, renaming, downgrading or shadowing the metric tool — the measure command then reports a perfect score
- Narrowing what the tool analyzes (trimming `tsconfig.json` includes, adding `.eslintignore` entries, pointing the run at a subdirectory)
- Letting the test runner collect zero tests and reading that as green
- **Rule:** Gate 1 every iteration — the tool must be proved present, at the pinned version, run over the same scope as the baseline. A metric that improved because *less was measured* is a regression wearing a win's clothing.

### Trusting Noise
- Keeping a change because one timed run came out 3% faster
- Comparing single runs of a wall-clock metric instead of medians of repeated runs
- Reporting a percentage improvement smaller than the measured run-to-run spread
- **Rule:** No noise floor, no wall-clock metric (Gate 3). A delta inside the noise is UNCHANGED, so revert it.

### Metric Gaming
- Adding `// eslint-disable` to "fix" lint warnings
- Marking tests as `.skip` to "improve" coverage percentages
- Moving code to `node_modules` to "reduce" bundle size
- **Rule:** The improvement must be genuine, not cosmetic

### Overfitting
- Making changes that improve the metric on this specific codebase but are bad practice generally
- Example: replacing all `any` types with `unknown` improves type error count but may hurt usability
- **Rule:** Each change should make sense in isolation, not just as a metric hack

### Complexity Creep
- Adding 50 lines of code to reduce lint warnings by 2
- The cure is worse than the disease
- **Rule:** The complexity of the change should be proportional to the improvement

### Infinite Loops
- Not setting a maximum iteration count
- Continuing when improvements are negligible (diminishing returns)
- **Rule:** Set a max (default 10), stop on plateau (3 consecutive no-improvement iterations)

## Structured Logging

Each iteration should be logged for post-hoc analysis:

```
## Optimization Log

| # | Timestamp | Change | Gate 1 | Gate 2 | Before | After | Delta | Status |
|---|-----------|--------|--------|--------|--------|-------|-------|--------|
| 1 | 14:30:01 | Remove unused import in auth.ts | ok | pass | 42 | 41 | -1 | KEEP |
| 2 | 14:32:15 | Fix missing return type on getUser | ok | pass | 41 | 40 | -1 | KEEP |
| 3 | 14:34:30 | Add explicit any → unknown in utils | ok | pass | 40 | 40 | 0 | REVERT |
| 4 | 14:36:02 | Narrow tsconfig include globs | ok | pass | 40 | 12 | -28 | REVERT — scope shrank, the errors did not |
| 5 | 14:38:44 | Reorder imports in server.ts | ok | **FAIL** | 40 | 38 | -2 | REVERT — tests outrank the metric |
| 6 | 14:41:10 | Upgrade typescript | **VOID** | — | 40 | — | — | STOP — tool exited 139, no metric |
```

Both gate columns are mandatory. An iteration with a blank Gate 1 or Gate 2 cell was not
verified and cannot be counted as an improvement in the final report.

This log enables:
- Understanding which changes had the biggest impact
- Identifying patterns (e.g., "import cleanup" is always effective)
- Avoiding repeating failed approaches in future sessions
- Proving, after the fact, that every kept change passed both gates rather than exploiting one

## Prior Art

- **[karpathy/autoresearch](https://github.com/karpathy/autoresearch)** — Autonomous ML experimentation on GPU training. 5-minute time-boxed experiments, single metric (val_bpb), ~100 experiments overnight. The original inspiration for this pattern.
- **[ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)** — Auto-Research-In-Sleep. Markdown-only, zero dependencies, cross-model review loops.
- **Ralph Wiggum Technique** — Persistence pattern for autonomous iteration until verification passes.
- **Anthropic long-running agents** — Initializer agent + coding agent pattern for multi-session chaining.

## Example: Reducing Lint Warnings

```
User: /optimize lint-warnings --iterations 5 --scope src/

Step 0: Validate the toolchain (Gate 1)
  → command -v eslint     → /usr/local/bin/eslint      [pinned]
  → eslint --version      → 9.14.0                     [pinned]
  → METRIC_OK_RC="0 1"    (eslint exits 1 when it FINDS warnings)
  → Test gate command: `npm test` — exists, currently green, collects 214 tests

Step 1: Baseline + noise floor (Gate 3)
  → 3 unchanged runs all report 47 → deterministic, noise floor = 0
  → Baseline: 47 warnings

Step 2: Iteration 1
  → Analyze: 12 warnings are "no-unused-vars"
  → Fix: Remove 12 unused imports across 8 files
  → Gate 1: eslint 9.14.0 still present, same scope → ok
  → Gate 2: npm test → 214 passed
  → Measure: 35 warnings
  → KEEP (47 → 35, -12; > noise floor 0)

Step 3: Iteration 2
  → Analyze: 8 warnings are "prefer-const"
  → Fix: Change let → const where no reassignment
  → Gate 1: ok   → Gate 2: 214 passed
  → Measure: 27 warnings
  → KEEP (35 → 27, -8)

Step 4: Iteration 3
  → Analyze: 5 warnings are "no-explicit-any"
  → Fix: Add types to 5 function parameters
  → Gate 1: ok   → Gate 2: npm test → 2 FAILED
  → REVERT (metric said 27 → 22, but tests outrank the metric)

...

Report:
  Baseline: 47 → Final: 18 → Improvement: 29 warnings (-62%)
  5 iterations, 4 kept, 1 reverted
  Gate 1 passed on all 5; Gate 2 failed once (iteration 3, reverted); 0 VOID measurements
```
