---
description: "Autonomous metric-driven improvement loop: measure → improve → verify → keep/revert"
argument-hint: "<metric> [--iterations N] [--scope path]"
---

Run an autonomous optimization loop that iteratively improves a measurable code metric.

Inspired by the autoresearch pattern: modify → commit → run → evaluate → keep if better, revert if worse.

## Arguments

Parse `$ARGUMENTS` for:
- `<metric>` — what to optimize (required). One of:
  - `lint-warnings` — reduce ESLint/Ruff/Clippy warnings
  - `type-errors` — reduce TypeScript/mypy/pyright type errors
  - `test-coverage` — increase test coverage percentage
  - `bundle-size` — reduce build output size
  - `build-time` — reduce build duration
  - `custom:<command>` — run a custom command that outputs a number (lower is better)
- `--iterations N` — max improvement cycles (default: 10)
- `--scope <path>` — limit changes to a specific directory or file

## Steps

### 1. Detect Metric and Tooling

| Metric | Detection | Measure Command |
|--------|-----------|-----------------|
| `lint-warnings` | eslint/ruff/clippy in project | `eslint . --format json \| jq '[.[].messages[]] \| length'` |
| `type-errors` | tsconfig.json/mypy.ini/pyright | `tsc --noEmit 2>&1 \| grep 'error TS' \| wc -l` |
| `test-coverage` | vitest/jest/pytest config | `vitest run --coverage --reporter=json \| jq '.total.lines.pct'` |
| `bundle-size` | webpack/vite/esbuild config | `npm run build 2>&1 \| grep -oP '\d+\.?\d* kB' \| head -1` |
| `build-time` | any build system | `time npm run build 2>&1` (extract real time) |
| `custom:<cmd>` | user-provided | Run `<cmd>`, parse last number from stdout |

If the metric tool is not found, report and stop.

### 2. Measure Baseline

1. Create a checkpoint: `/checkpoint optimize-baseline` (or `git stash push -m "optimize-baseline"` + `git stash pop`)
2. Run the measurement command
3. Record as `baseline_value`
4. Report: `Baseline: <metric> = <value>`

### 3. Improvement Loop

For each iteration (up to `--iterations`):

1. **Analyze** the current state:
   - For `lint-warnings`: read the lint output, pick the most common warning category
   - For `type-errors`: read the error output, pick the first error
   - For `test-coverage`: find uncovered files/functions, write a test
   - For `bundle-size`: identify largest dependencies or unused imports
   - For `build-time`: look for unoptimized configs, missing caches
   - For `custom`: analyze the output and identify improvement opportunities

2. **Apply one improvement** — make the smallest targeted change that should improve the metric. Read the relevant files before editing.

3. **Re-measure** — run the same measurement command

4. **Evaluate**:
   - If metric **improved** (or stayed same for coverage which rounds): **KEEP**
     - Log: `Iteration N: <metric> <before> → <after> (KEEP) — <what changed>`
     - Update `current_value = new_value`
   - If metric **worsened**: **REVERT**
     - Undo the change (revert the edit)
     - Log: `Iteration N: <metric> <before> → <after> (REVERT) — <what was tried>`
   - If metric is **unchanged after 3 consecutive attempts**: **STOP**
     - Log: `Stopping: no improvement found after 3 attempts`

5. **Continue** to next iteration

### 4. Regression Guard

Stop immediately if ANY of these occur:
- Metric worsened and revert failed
- Build/test command itself fails (not metric regression, but broken tooling)
- Same metric value for 3 consecutive iterations (plateau)
- Max iterations reached

### 5. Report

```
## Optimization Report

**Metric**: <metric name>
**Scope**: <path or "project root">
**Iterations**: <completed> / <max>

### Results
| # | Change | Before | After | Status |
|---|--------|--------|-------|--------|
| 1 | <description> | <value> | <value> | KEEP |
| 2 | <description> | <value> | <value> | REVERT |
| 3 | <description> | <value> | <value> | KEEP |

### Summary
- **Baseline**: <original value>
- **Final**: <current value>
- **Improvement**: <delta> (<percentage>%)
- **Kept**: <N> changes
- **Reverted**: <N> changes
- **Status**: <Improved | Plateau | Max iterations>

### Changes Applied
1. <file:line> — <what was changed and why>
```

## Important Rules

- **One change at a time** — never batch multiple improvements. Measure after each.
- **Read before edit** — always read the file and understand the context before modifying.
- **Minimal changes** — prefer the smallest fix that improves the metric.
- **No suppressions** — never add `// @ts-ignore`, `eslint-disable`, `# type: ignore` to "improve" metrics. That's gaming, not improving.
- **No test skipping** — never mark tests as `.skip` or `@pytest.mark.skip` to improve coverage math.
- **Preserve behavior** — changes must not alter the program's functional behavior. Only improve the measured quality.
- **Regression guard** — if you break something, revert immediately. The metric must move in one direction only.

## Integration with Other Commands

- Use `/checkpoint` to create save points before starting
- Use `/quality-gate` to verify no regressions after optimization
- Use `/build-fix` if an optimization accidentally breaks the build
- Complements `/tdd` — optimize can improve coverage that TDD established
