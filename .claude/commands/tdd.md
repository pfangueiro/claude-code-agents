---
description: "Enforce RED-GREEN-REFACTOR test-driven development cycle for a function or feature"
argument-hint: "<description of function/feature to implement>"
---

Implement `$ARGUMENTS` using strict Test-Driven Development (RED → GREEN → REFACTOR).

## Steps

### Phase 1: RED — Write a Failing Test

1. **Understand the requirement** from `$ARGUMENTS`. If unclear, ask for clarification before proceeding.

2. **Detect test framework**:
   - `package.json` with vitest/jest → use that framework
   - `pytest.ini` / `pyproject.toml` with pytest → use pytest
   - `go.mod` → use Go testing
   - `Cargo.toml` → use Rust's `#[test]`
   - Fall back to the project's existing test patterns

3. **Write the test FIRST**:
   - Create a test file (or add to existing) following project conventions
   - Write test cases covering:
     - Happy path (expected behavior)
     - Edge cases (empty input, boundary values, null/undefined)
     - Error paths (invalid input, expected failures)
   - The function/module under test **does not exist yet** — that's intentional

4. **Run the tests** — confirm they **FAIL** (RED phase).
   - If tests pass, something is wrong — the implementation shouldn't exist yet
   - If tests fail for the wrong reason (import error vs assertion error), fix the test setup

5. **Report RED status**:
   ```
   RED: X tests written, all failing as expected
   - test_happy_path: FAIL (function not found)
   - test_edge_case: FAIL (function not found)
   - test_error_path: FAIL (function not found)
   ```

### Phase 2: GREEN — Minimal Implementation

6. **Implement the minimum code** to make ALL tests pass:
   - Write only what the tests require — no extra features
   - Prefer simple, obvious implementations over clever ones
   - Do NOT refactor yet — that's the next phase

7. **Run the tests** — confirm they **ALL PASS** (GREEN phase).
   - If any test fails, fix the implementation (not the test) until green
   - If a test was wrong, explain why and fix it with justification

8. **Report GREEN status**:
   ```
   GREEN: All X tests passing
   - test_happy_path: PASS
   - test_edge_case: PASS
   - test_error_path: PASS
   ```

### Phase 3: REFACTOR — Clean Up

9. **Refactor** the implementation while keeping all tests green:
   - Extract common logic
   - Improve naming and readability
   - Remove duplication
   - Add types/interfaces if applicable
   - **Run tests after each refactor step** to ensure nothing breaks

10. **Refactor tests** if needed:
    - Remove duplication in test setup
    - Add descriptive test names
    - Group related tests

11. **Final test run** — confirm everything still passes.

### Phase 4: REPORT

12. **Show coverage** if the project has a coverage tool configured:
    - `npx vitest --coverage` / `npx jest --coverage`
    - `pytest --cov`
    - `go test -cover`

13. **Final report**:
    ```
    ## TDD Report

    **Feature**: <description>
    **Cycle**: RED → GREEN → REFACTOR — Complete

    ### Tests Written
    - <test file>: X tests (Y assertions)

    ### Implementation
    - <file:line> — <what was implemented>

    ### Coverage
    - Function/feature coverage: <percentage if available>

    ### Refactoring Applied
    - <what was cleaned up>
    ```

**Important rules:**
- NEVER write implementation before the test — the RED phase must come first
- NEVER skip the RED phase verification (tests must actually fail)
- NEVER modify tests to make them pass — fix the implementation instead
- If you realize a test is wrong during GREEN phase, explain why before changing it
- Keep each cycle small — one behavior per RED-GREEN-REFACTOR cycle
- Delegates to the **test-automation** agent for complex test generation if needed
