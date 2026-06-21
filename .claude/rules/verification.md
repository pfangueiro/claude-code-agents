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

## Honest Measurement

- Distinguish a real change from measurement noise — a "10% faster" claim from a single timed run is noise, not a result. For variable metrics (timings, benchmarks), re-measure or require the delta to exceed run-to-run variance before claiming it.
- Never report a number you did not measure. If a figure is inferred or projected rather than observed, label it as an estimate — do not present it as measured.
- State the basis of every quantitative claim: what was run, how many times, against what baseline. "Faster" without a before/after is an opinion.
- Don't claim more precision than the method supports — round to what the measurement can actually resolve.
