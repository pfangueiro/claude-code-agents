---
description: "Review a pull request for code quality, security, testing, and documentation"
argument-hint: "<pr_number>"
---

Review the pull request specified by the argument.

## Steps

1. **Fetch PR details**:
   - Run `gh pr view $ARGUMENTS --json number,title,body,baseRefName,headRefName,files,additions,deletions`
   - Run `gh pr diff $ARGUMENTS` to get the full diff

2. **Analyze the changes** across these categories:

   ### Code Quality
   - Are functions small and focused?
   - Are variable names descriptive?
   - Is there dead code, unused imports, or commented-out code?
   - Are there code smells (duplication, long parameter lists, deep nesting)?

   ### Security (OWASP Top 10)
   - SQL injection: Are queries parameterized?
   - XSS: Is user input sanitized before rendering?
   - Auth: Are endpoints properly protected?
   - Secrets: Are any credentials, API keys, or tokens exposed?
   - Dependencies: Are new dependencies from trusted sources?

   ### Testing
   - Are new functions covered by tests?
   - Are edge cases and error paths tested?
   - Do existing tests still pass with these changes?

   ### Documentation
   - Are public APIs documented?
   - Is complex logic explained with comments?
   - Are breaking changes noted?

3. **Generate review report** in this format:

```
## PR Review: #<number> — <title>

### Summary
<1-2 sentence overview of the changes>

### Critical (must fix)
- [ ] <description with file:line reference>

### Suggestions (should fix)
- [ ] <description with file:line reference>

### Nits (nice to have)
- [ ] <description with file:line reference>

### What looks good
- <positive observations>
```

4. **Ask** if the user wants to post the review as a GitHub comment using `gh pr review $ARGUMENTS --body "..."`.
