# Verification Rules

These rules are always enforced. They cannot be overridden.

## After Every Implementation

- After implementing a feature or fix, ALWAYS verify it works before reporting completion
- Run existing tests if they exist (`npm test`, `pytest`, `go test`, etc.)
- If no tests exist for the changed code, write at least one test that validates the change
- Build the project to catch compilation/type errors
- For UI changes, take a screenshot or describe the visual result

## Verification Standards

- "It should work" is not verification — run it and confirm
- A passing build alone is not sufficient — verify the specific behavior changed
- If tests fail after your change, fix them before reporting completion
- Never mark a task complete without stating what verification was performed

## Test-Driven Fixing

- For bug fixes: write a failing test that reproduces the bug BEFORE fixing it
- The fix is verified when the previously-failing test passes
- This prevents regressions and proves the fix addresses the actual problem
