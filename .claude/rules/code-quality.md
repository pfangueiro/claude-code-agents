# Code Quality Rules

These rules guide code quality within your authorized scope — expected practice to apply
to every change, not a guaranteed enforcement mechanism or a tool sandbox.

## Read Before Modify

- ALWAYS read a file with the Read tool before editing it — never guess at file contents
- Use Grep to search for patterns instead of assuming where code lives
- Use LSP findReferences before renaming or refactoring to understand the blast radius
- Maintain a high read:edit ratio — more reading means fewer mistakes

## Right-Sized Change & Reuse

- Make the smallest COMPLETE change the requirement needs — including the callers, tests,
  fixtures, exports, config and docs it touches. Minimal is never permission to drop
  required behavior.
- Before writing new code, look for an existing project helper, component or pattern that
  fits; failing that, prefer platform/standard-library facilities, then an already-installed
  dependency, then the new code the requirement actually needs. Existing house conventions win.
- A reuse recommendation must name the existing implementation and explain why it fits. This
  is not a mandate to replace a working dependency, force a one-liner, or pull in a large
  library to save a few lines.
- Do not add speculative wrappers, configuration, dependencies or design patterns without a
  current demonstrated need. Interfaces, abstractions and security boundaries the design
  actually requires are valid.
- Never trade correctness, validation, security, data-loss or error handling, accessibility,
  required tests, exact-SHA receipts or independent review for a smaller diff. Between
  alternatives that all meet the requirement, prefer the simpler one; do not weaken project
  or owner policies.

## Dead Code

- No unused imports, variables, functions, or type definitions
- Remove commented-out code blocks — use version control history instead
- No unreachable code after return/throw/break statements

## Function Design

- Single responsibility: each function does one thing
- Split a function when it carries unrelated jobs, or when demonstrated coupling makes it hard to read or test — never merely to hit a line quota; length alone is a smell to investigate, not a trigger
- Use early returns over deeply nested conditionals
- Prefer `const` by default; use `let` only when mutation is needed

## Error Handling

- Handle errors explicitly — no empty catch blocks
- Propagate errors with meaningful context (wrap, don't swallow)
- Use typed errors where the language supports them

## Naming

- Use descriptive variable and function names
- Avoid abbreviations except common ones (e.g., `idx`, `err`, `ctx`, `req`, `res`)
- Boolean variables should read as questions: `isReady`, `hasPermission`, `canEdit`

## Code Organization

- Group related functionality together
- Keep consistent file structure within the project
- Avoid circular dependencies between modules
