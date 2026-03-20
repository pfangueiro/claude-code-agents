---
description: "Auto-detect build system, run build, parse errors, and fix them iteratively with regression guard"
argument-hint: "[path]"
---

Run the build, parse errors, and fix them one at a time with automatic regression detection.

## Steps

1. **Detect build system** in `$ARGUMENTS` path (or project root):
   - `package.json` with `build` script → `npm run build`
   - `tsconfig.json` without build script → `npx tsc --noEmit`
   - `Cargo.toml` → `cargo build`
   - `go.mod` → `go build ./...`
   - `build.gradle` / `build.gradle.kts` → `./gradlew build`
   - `pom.xml` → `mvn compile`
   - `pyproject.toml` with build backend → `python -m build` or `python -m py_compile`
   - `Makefile` → `make`
   - If multiple detected, prefer the most specific (e.g., `tsconfig.json` over `Makefile`)

2. **Run initial build** and capture stderr/stdout. Record the error count as `baseline_errors`.

3. **If build succeeds** (exit 0, no errors): report success and stop.

4. **Parse errors** from build output:
   - Extract file path, line number, and error message for each error
   - Group errors by file
   - Sort by file path, then line number

5. **Fix loop** (max 10 iterations):
   - Pick the **first error** (by file:line order)
   - Read the file around the error location (20 lines of context)
   - Analyze the error and apply the minimal fix
   - **Re-run the build** after each fix
   - Count errors in the new output as `current_errors`

6. **Regression guard** — stop immediately if ANY of these are true:
   - `current_errors > baseline_errors` (fix introduced new errors) → revert the last edit and report
   - The same error (same file, same line, same message) persists after 3 consecutive fix attempts → stop and report
   - Build command itself fails to execute (not build errors, but command not found, etc.)

7. **After each successful fix**, update `baseline_errors = current_errors` and continue to the next error.

8. **Report** when done (all errors fixed, regression detected, or max iterations reached):

```
## Build Fix Report

**Build system**: <detected system>
**Initial errors**: <count>
**Errors fixed**: <count>
**Remaining errors**: <count>
**Status**: <All fixed | Stopped: regression detected | Stopped: max iterations | Stopped: persistent error>

### Fixes Applied
1. <file:line> — <what was wrong> → <what was changed>

### Remaining Issues (if any)
1. <file:line> — <error message> — <suggested approach>
```

**Important notes:**
- Fix ONE error at a time, then rebuild — never batch fixes
- Always read the file before editing — never guess at code you haven't seen
- Prefer minimal, targeted fixes over refactoring
- If a fix would require significant refactoring, report it as a remaining issue instead
- Never suppress errors with `// @ts-ignore`, `@SuppressWarnings`, or similar
