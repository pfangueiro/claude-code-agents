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

### 0. Mandatory Preconditions — the three gates

**No valid run, no metric.** Every measure command in the table below ends in `wc -l`, `grep`,
`jq` or `head`, and a shell pipeline reports the exit status of its *last* command — so the tool's
own status is discarded and **a missing tool scores perfectly**. Executed, on a machine with no
TypeScript installed:

```
$ command -v tsc; echo "rc=$?"
rc=1                                        # tsc is NOT installed
$ tsc --noEmit 2>&1 | grep 'error TS' | wc -l
       0                                    # <- a PERFECT score
$ echo $?
0                                           # <- and the pipeline "succeeded"
```

Deleting the compiler outscores every genuine optimization. Two tempting guards do **not** work:
`set -o pipefail` (grep exits 1 on no-match, so a clean codebase and a missing tool both give
rc 1) and `${PIPESTATUS[0]}` (a bash-ism — empty in zsh, whose array is 1-indexed `pipestatus`).

Define these helpers first and route **every** measurement and **every** guard through them.
Never call a bare pipeline. They are the Gate 1/2/3 helpers from the `experiment-loop` skill,
reproduced so `/optimize` is self-sufficient — keep the copies in sync with
`.claude/skills/experiment-loop/SKILL.md`.

```bash
# --- Gate 1: the metric tool must EXIST and must have RUN --------------------
# METRIC_OK_RC: space-separated exit codes that mean "the tool RAN". Default 0 =
# fail closed. Pin the real set at BASELINE -- linters and compilers exit
# non-zero when they FIND problems, and that is a successful run.
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

metric_value() {          # metric_value <parser...>  (reads stdin) -> ONE number, or rc 2 = VOID
  v=$("$@")
  # $(...) already drops trailing newlines; strip only the surrounding blanks that BSD
  # `wc -l` pads with. Whatever survives must be ONE token -- NEVER join what is left.
  v=${v#"${v%%[![:blank:]]*}"}; v=${v%"${v##*[![:blank:]]}"}
  case "$v" in
    '')                echo "VOID: parser produced no output" >&2; return 2 ;;
    *[[:space:]]*)     printf 'VOID: parser produced %s values, not one scalar:\n%s\n' \
                         "$(printf '%s\n' "$v" | wc -w | tr -d '[:blank:]')" "$v" >&2; return 2 ;;
    *[!0-9.]*|.|*.*.*) printf "VOID: '%s' is not a number\n" "$v" >&2; return 2 ;;
  esac
  printf '%s\n' "$v"
}

# --- Gate 2: build+tests must EXIST, SUCCEED, and have actually run tests ----
# GUARD_RAN_RE: pinned at BASELINE from the runner's real output.
# The count MUST start [1-9]: `[0-9]+` matches the string "0 passed", so a runner that
# collected zero tests and exited 0 read GREEN — the exact fail-open this gate exists to catch.
: "${GUARD_RAN_RE:=[1-9][0-9]* (passed|passing|tests? ran|ok)}"

guard_run() {             # guard_run <tool> <cmd...>  -> 0 pass | 1 FAIL | 2 VOID
  tool=$1; shift
  command -v "$tool" >/dev/null 2>&1 || { echo "VOID: guard tool '$tool' not on PATH" >&2; return 2; }
  out=$("$@" 2>&1); rc=$?
  [ "$rc" -eq 0 ] || { printf 'FAIL: guard exited %s\n%s\n' "$rc" "$out" >&2; return 1; }
  printf '%s' "$out" | grep -Eqi "$GUARD_RAN_RE" || {
    printf 'VOID: guard exited 0 but nothing matched /%s/ -- zero tests is not green\n' \
      "$GUARD_RAN_RE" >&2; return 2; }
  return 0
}

# --- Gate 3: a delta inside run-to-run noise is not an improvement -----------
noise_floor() {           # noise_floor <run1> <run2> ...  -> spread (max - min)
  printf '%s\n' "$@" | awk 'NR==1{lo=hi=$1} {if($1<lo)lo=$1; if($1>hi)hi=$1} END{print hi-lo}'
}

verdict() {               # verdict <before> <after> <floor> <lower|higher> -> KEEP|REVERT|UNCHANGED
  awk -v b="$1" -v a="$2" -v f="$3" -v d="$4" 'BEGIN{
    delta = (d=="higher") ? a-b : b-a
    if (delta > f) print "KEEP"; else if (delta < -f) print "REVERT"; else print "UNCHANGED" }'
}
```

Verified behaviour of the helpers (bash 3.2, zsh 5.9 and dash `sh` all identical):

| State | Helper | Result |
|---|---|---|
| `tsc` deleted | `metric_run` | `VOID: 'tsc' not on PATH` — **no metric** |
| `tsc` present, 2 real errors (exit 2) | `metric_run` | `METRIC = 2` |
| `tsc` present, codebase genuinely clean (exit 0) | `metric_run` | `METRIC = 0` — a real zero |
| `tsc` present but crashes (exit 139) | `metric_run` | `VOID: tsc exited 139` — **no metric** |
| parser prints `3` `4` `1` (per-file counts, true total 8) | `metric_value` | `VOID: parser produced 3 values, not one scalar` |
| test runner absent | `guard_run` | `VOID: guard tool ... not on PATH` |
| test runner exits 1 | `guard_run` | `FAIL: guard exited 1` → REVERT |
| test runner exits 0, `214 passed` | `guard_run` | pass |
| test runner exits 0, zero tests collected | `guard_run` | `VOID: ... zero tests is not green` |

**VOID is not zero, and VOID is not green.** A VOID stops the loop: fix the toolchain, then
resume. Never record a VOID as an improvement, a regression, or a plateau.

### 1. Detect Metric and Tooling

> **These are measure *steps*, not metrics.** Each one ends in a counter or extractor that
> discards the tool's exit status, so **every row returns a perfect score when its tool is
> missing**. A bare invocation of any row is not a measurement — run it through `metric_run` /
> `metric_value` from step 0.

| Metric | Detection | Measure Command | Direction | Noise floor |
|--------|-----------|-----------------|-----------|-------------|
| `lint-warnings` | eslint/ruff/clippy in project | `eslint . --format json \| jq '[.[].messages[]] \| length'` | lower | 0 |
| `type-errors` | tsconfig.json/mypy.ini/pyright | `tsc --noEmit 2>&1 \| grep 'error TS' \| wc -l` | lower | 0 |
| `test-coverage` | vitest/jest/pytest config | `vitest run --coverage --reporter=json \| jq '.total.lines.pct'` | higher | 0 |
| `bundle-size` | webpack/vite/esbuild config | `npm run build 2>&1 \| grep -oP '\d+\.?\d* kB' \| head -1` | lower | ~0 (measure if the build content-hashes) |
| `build-time` | any build system | `/usr/bin/time -p npm run build 2>&1 \| awk '/^real/{print $2}'` | lower | **must be measured** |
| `custom:<cmd>` | user-provided | `<cmd>`, which must emit **exactly one** number | as declared | **must be measured** |

Each measure command is split into a *tool* invocation and a *parser*, so both halves are gated:

```bash
# type-errors, wired up
export METRIC_OK_RC="0 1 2"                                     # pinned at BASELINE
raw=$(metric_run tsc tsc --noEmit)                        || exit 2   # VOID -> stop
val=$(printf '%s\n' "$raw" | metric_value grep -c 'error TS') || exit 2
```

The parser must reduce to a single scalar. A parser that emits one line per file — `jq
'.[].errorCount'` rather than `jq '[.[].errorCount] | add'` — is voided, not joined: three files
reporting 3, 4 and 1 errors must score 8, never `341`.

If the metric tool is not found, or `metric_run` / `metric_value` returns VOID, **report and stop**.
Do not fall back to a bare pipeline, and do not record the VOID as a value.

### 2. Measure Baseline

1. Create a checkpoint: `/checkpoint optimize-baseline` (or `git stash push -m "optimize-baseline"` + `git stash pop`)
2. **Pin the metric tool (Gate 1).** Record `command -v <tool>` and `<tool> --version`, and pin
   `METRIC_OK_RC` to the exit codes the tool really uses. Both are re-asserted every iteration, so
   a change that removes, shadows or downgrades the tool fails the gate instead of winning it.
3. **Pin the correctness gate (Gate 2).** Identify the project's build+test command and prove it
   is usable *before* any change: `guard_run` must return 0 **and** the run must collect a non-zero
   number of tests. Pin `GUARD_RAN_RE` from that output. **No usable guard command → do not start
   the loop.** A metric with nothing to overrule it is a metric-gaming machine.
4. **Measure the noise floor (Gate 3).** Run the measurement **at least 5 times with no code change
   at all** and set `floor=$(noise_floor <run1> ... <run5>)`. Deterministic counts settle at 0.
   Wall-clock metrics do not: 10 runs of one identical, completely unmodified workload measured
   `median 0.0871s, spread 0.0053s` — a **6.1%** band with zero code change. Re-running that same
   unmodified code and reading a single number reported it "0.6% faster"; a loop without a floor
   banks that as a win. (The `experiment-loop` skill records a noisier workload at 19.0%.)
5. Record as `baseline_value`
6. Report: `Baseline: <metric> = <value>  (tool <ver>, guard green with N tests, noise floor <floor>)`

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

3. **Gate 2 — build and test, BEFORE looking at the metric.** Run `guard_run` on the pinned
   build+test command.
   - Returns **1 (FAIL)** → **REVERT immediately.** Do not measure, do not compare. A broken tree
     has no score. This holds *even when the metric improved* — especially then, because "metric
     improved, tests broke" is the signature of metric gaming.
   - Returns **2 (VOID)** — runner absent, crashed, or collected zero tests → **STOP.** That is not
     green. Fix the toolchain and resume.
   - Returns **0** → proceed to measure.

4. **Gate 1 + re-measure.** Re-assert `command -v <tool>` and `<tool> --version` against the values
   pinned at baseline, over the **same scope**, then re-run the measurement through `metric_run` /
   `metric_value`.
   - Tool missing, version changed, scope narrowed, or output not a single scalar → **VOID → STOP.**
     Never score it. A metric that improved because *less was measured* is a regression wearing a
     win's clothing.

5. **Gate 3 — decide against the noise floor.** For wall-clock metrics re-measure at least 3 times
   and compare **medians**, not single runs. Then:
   `verdict "$before" "$after" "$floor" "$direction"`
   - **KEEP** — gain exceeds the floor. Log `Iteration N: <before> → <after> (KEEP) — <what changed>`,
     update `current_value`.
   - **REVERT** — the metric worsened beyond the floor. Undo the edit, log
     `Iteration N: <before> → <after> (REVERT) — <what was tried>`.
   - **UNCHANGED** — the delta is inside the noise. **Revert it** and log UNCHANGED. A percentage
     smaller than the measured spread is never reported as a result.
   - **UNCHANGED 3 times consecutively** → **STOP**: `Stopping: no improvement found after 3 attempts`

6. **Log both gate results beside the metric,** then **continue** to the next iteration. An
   iteration logged without a Gate 1 and Gate 2 result is unverified and may not be counted as an
   improvement in the final report.

### 4. Regression Guard

**Tests outrank the metric, always.** The metric never overrules a red build — there is no metric
value good enough to keep a change whose tests fail.

REVERT the change and continue:
- `guard_run` returned 1 (build or tests FAILED) — regardless of what the metric did
- `verdict` returned REVERT (metric worsened beyond the floor)
- `verdict` returned UNCHANGED (delta inside the noise floor)

STOP the loop immediately:
- Revert itself failed (the tree is no longer at a known-good state)
- `guard_run` returned 2 (VOID — runner absent, crashed, or collected zero tests)
- `metric_run` or `metric_value` returned 2 (VOID — tool missing, crashed, scope narrowed, or the
  parser produced something other than one number)
- The metric tool's path or version no longer matches the value pinned at baseline
- 3 consecutive UNCHANGED iterations (plateau)
- Max iterations reached

### 5. Report

```
## Optimization Report

**Metric**: <metric name>
**Scope**: <path or "project root">
**Tool**: <path> <version> (pinned at baseline, re-asserted each iteration)
**Guard**: <build+test command> — green at baseline, <N> tests collected
**Noise floor**: <floor> (from <k> unchanged runs)
**Iterations**: <completed> / <max>

### Results
| # | Change | Gate 1 | Gate 2 | Before | After | Delta | Status |
|---|--------|--------|--------|--------|-------|-------|--------|
| 1 | <description> | ok | pass | <value> | <value> | <d> | KEEP |
| 2 | <description> | ok | pass | <value> | <value> | <d> | REVERT |
| 3 | <description> | ok | **FAIL** | <value> | — | — | REVERT — tests outrank the metric |
| 4 | <description> | ok | pass | <value> | <value> | <d> | UNCHANGED — inside noise floor |
| 5 | <description> | **VOID** | — | <value> | — | — | STOP — tool exited <rc>, no metric |

Both gate columns are mandatory. An iteration with a blank Gate 1 or Gate 2 cell was not verified
and cannot be counted as an improvement.

### Summary
- **Baseline**: <original value>
- **Final**: <current value>
- **Improvement**: <delta> (<percentage>%) — must exceed the noise floor to be stated at all
- **Kept**: <N> changes
- **Reverted**: <N> changes (<N> for failed tests, <N> for metric regression, <N> inside noise)
- **Gate results**: Gate 1 passed <N>/<N>; Gate 2 failed <N>; <N> VOID measurements
- **Status**: <Improved | Plateau | Max iterations | Stopped — VOID>

### Changes Applied
1. <file:line> — <what was changed and why>
```

## Important Rules

- **No valid run, no metric** — a number from a tool that never ran is not a measurement. Every
  measurement goes through `metric_run` / `metric_value`; never call a bare pipeline.
- **Tests outrank the metric, always** — run the build+test gate *before* comparing metrics, and
  revert on failure whatever the metric says.
- **Never break the toolchain to score** — deleting, renaming, downgrading or shadowing the metric
  tool; trimming `tsconfig.json` includes; adding `.eslintignore` entries; pointing the run at a
  subdirectory; letting the test runner collect zero tests and reading that as green.
- **No noise floor, no wall-clock metric** — a delta inside the measured run-to-run spread is
  UNCHANGED, so revert it and never report it as a percentage improvement.
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
