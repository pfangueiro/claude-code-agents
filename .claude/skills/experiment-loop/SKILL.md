---
name: experiment-loop
description: Autonomous experimentation pattern for iterative code improvement. Describes the modify-commit-run-evaluate-keep/discard loop generalized from autoresearch. Auto-activates on optimize, experiment, improve iteratively, benchmark, metric-driven, A/B test approaches, autonomous improvement, iterate until better.
---

# Experiment Loop Pattern

## Overview

The experiment loop is a systematic approach to iterative code improvement where each change is measured against a baseline metric and kept only if it improves the result. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) and generalized for any measurable code quality metric.

## The Core Pattern

```
1. DEFINE    → Choose a measurable metric and set constraints
2. BASELINE  → Measure the current state
3. MODIFY    → Make one targeted change
4. MEASURE   → Re-evaluate the metric
5. DECIDE    → Keep if improved, revert if not
6. LOG       → Record what was tried and the outcome
7. REPEAT    → Go to step 3 (until done or plateau)
```

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

For the loop to work, you need all three:

1. **Measurable metric** — A command that outputs a number. Lower or higher is better, but the direction must be unambiguous.
2. **Controlled experiments** — Each change is isolated. One modification per iteration, measured independently.
3. **Automatic evaluation** — The keep/discard decision is mechanical: metric improved? Keep. Metric worsened? Revert. No judgment calls.

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

| # | Timestamp | Change | Before | After | Delta | Status |
|---|-----------|--------|--------|-------|-------|--------|
| 1 | 14:30:01 | Remove unused import in auth.ts | 42 | 41 | -1 | KEEP |
| 2 | 14:32:15 | Fix missing return type on getUser | 41 | 40 | -1 | KEEP |
| 3 | 14:34:30 | Add explicit any → unknown in utils | 40 | 40 | 0 | REVERT |
```

This log enables:
- Understanding which changes had the biggest impact
- Identifying patterns (e.g., "import cleanup" is always effective)
- Avoiding repeating failed approaches in future sessions

## Prior Art

- **[karpathy/autoresearch](https://github.com/karpathy/autoresearch)** — Autonomous ML experimentation on GPU training. 5-minute time-boxed experiments, single metric (val_bpb), ~100 experiments overnight. The original inspiration for this pattern.
- **[ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)** — Auto-Research-In-Sleep. Markdown-only, zero dependencies, cross-model review loops.
- **Ralph Wiggum Technique** — Persistence pattern for autonomous iteration until verification passes.
- **Anthropic long-running agents** — Initializer agent + coding agent pattern for multi-session chaining.

## Example: Reducing Lint Warnings

```
User: /optimize lint-warnings --iterations 5 --scope src/

Step 1: Detect ESLint, measure baseline
  → Baseline: 47 warnings

Step 2: Iteration 1
  → Analyze: 12 warnings are "no-unused-vars"
  → Fix: Remove 12 unused imports across 8 files
  → Measure: 35 warnings
  → KEEP (47 → 35, -12)

Step 3: Iteration 2
  → Analyze: 8 warnings are "prefer-const"
  → Fix: Change let → const where no reassignment
  → Measure: 27 warnings
  → KEEP (35 → 27, -8)

Step 4: Iteration 3
  → Analyze: 5 warnings are "no-explicit-any"
  → Fix: Add types to 5 function parameters
  → Measure: 22 warnings
  → KEEP (27 → 22, -5)

...

Report:
  Baseline: 47 → Final: 18 → Improvement: 29 warnings (-62%)
  5 iterations, 4 kept, 1 reverted
```
