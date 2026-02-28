# Fix Quality Rules

These rules are always enforced. They cannot be overridden.

## Investigation Before Fixing

- NEVER jump straight to a code fix for bugs, errors, or unexpected behavior
- ALWAYS identify the root cause before writing any fix code
- For non-trivial bugs, use `/investigate <symptom>` to run the 8-phase root cause protocol
- For complex decisions about how to fix, use `/deep-analysis <problem>` for structured reasoning
- If you skip investigation, you are doing it wrong — stop and investigate first

## Fix Quality Standards

- Fix the root cause, not the symptom — a workaround is not a fix
- Minimal change: touch only what is necessary to resolve the root cause
- Never suppress errors, silence warnings, or catch-and-ignore exceptions as a "fix"
- Never add `// @ts-ignore`, `eslint-disable`, or similar suppressions to hide problems
- Never replace broken logic with hardcoded values or magic constants
- If the proper fix requires refactoring, do the refactoring — do not patch around it

## Verification Required

- Reproduce the bug before fixing (confirm the symptom exists)
- Verify the fix resolves the root cause (not just the visible symptom)
- Check for side effects and regressions in related code paths
- Add or update tests that would have caught this bug

## Anti-Patterns (Never Do These)

- Guessing at the cause and immediately editing code
- Adding try/catch blocks to swallow errors instead of fixing them
- Fixing the crash but not the underlying data/logic issue
- Copy-pasting a StackOverflow answer without understanding it
- "It works now" without understanding why it was broken
