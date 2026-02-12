# Code Quality Rules

These rules are always enforced to maintain code quality standards.

## Dead Code

- No unused imports, variables, functions, or type definitions
- Remove commented-out code blocks — use version control history instead
- No unreachable code after return/throw/break statements

## Function Design

- Single responsibility: each function does one thing
- Keep functions short and focused (aim for < 40 lines)
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
