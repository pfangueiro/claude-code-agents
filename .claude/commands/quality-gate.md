---
description: "Run formatter, linter, and type checker as a pre-commit quality gate"
argument-hint: "[path] [--fix] [--strict]"
---

Run a comprehensive quality gate check on the codebase or a specific path.

## Arguments

- `$ARGUMENTS` may contain:
  - A file or directory path to scope the check (default: project root)
  - `--fix` flag: auto-fix issues where possible (formatter + linter auto-fix)
  - `--strict` flag: treat warnings as errors (zero-warning policy)

Parse `$ARGUMENTS` to extract the path and flags.

## Steps

1. **Detect language and tooling** in the target path:

   **TypeScript/JavaScript:**
   - Formatter: `prettier` (check `node_modules/.bin/prettier` or `npx prettier`)
   - Linter: `eslint` (check `node_modules/.bin/eslint` or `npx eslint`)
   - Type checker: `tsc --noEmit` (if `tsconfig.json` exists)
   - Test: `vitest run` or `jest` (if test config exists)

   **Python:**
   - Formatter: `black` or `ruff format`
   - Linter: `ruff check` or `flake8` or `pylint`
   - Type checker: `mypy` or `pyright`
   - Test: `pytest` (if `pytest.ini` or `pyproject.toml` with pytest)

   **Go:**
   - Formatter: `gofmt -l`
   - Linter: `golangci-lint run` or `go vet`
   - Type checker: `go build ./...`
   - Test: `go test ./...`

   **Rust:**
   - Formatter: `cargo fmt --check`
   - Linter: `cargo clippy`
   - Type checker: `cargo check`
   - Test: `cargo test`

2. **Run checks in order** (stop on first failure unless `--fix` mode):

   ### Step 1: Format Check
   - Run formatter in check mode (or fix mode if `--fix`)
   - Report files that need formatting
   - If `--fix`: auto-format and report changes

   ### Step 2: Lint Check
   - Run linter on target path
   - If `--fix`: apply auto-fixable rules
   - Report errors and warnings separately
   - If `--strict`: treat warnings as errors

   ### Step 3: Type Check
   - Run type checker (language-specific)
   - Report type errors with file:line references

   ### Step 4: Test Check (if tests exist for changed files)
   - Only run if test files exist in or near the target path
   - Run relevant test suite
   - Report pass/fail counts

3. **Generate report:**

```
## Quality Gate Report

**Scope**: <path checked>
**Mode**: <check | fix | strict>

### Format
- Status: PASS/FAIL
- Files checked: <count>
- Issues: <count> (<count> auto-fixed if --fix)

### Lint
- Status: PASS/FAIL
- Errors: <count>
- Warnings: <count>
- Auto-fixed: <count> (if --fix)

### Types
- Status: PASS/FAIL
- Errors: <count>

### Tests
- Status: PASS/FAIL/SKIPPED
- Passed: <count> | Failed: <count>

### Overall: PASS / FAIL
<summary of blocking issues if FAIL>
```

4. **Exit status interpretation:**
   - All checks pass → `PASS` — safe to commit
   - Any check fails → `FAIL` — list what needs fixing
   - If `--fix` was used, re-run checks after fixes to confirm resolution

**Important notes:**
- Only run tools that are actually installed/configured in the project
- Skip checks gracefully if a tool is not available (report as SKIPPED, not FAIL)
- Never install tools — only use what's already in the project
- Complements the `post-edit-lint.sh` hook (reactive) with proactive invocation
