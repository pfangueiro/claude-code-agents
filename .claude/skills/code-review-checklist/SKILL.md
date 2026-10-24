---
name: code-review-checklist
description: A ten-category human code-review rubric — correctness, design, readability, testing, security, performance, documentation, dependencies, error handling, and style — plus process guidance on feedback tone, review size, and a pre-submit self-review pass. Use when a review verdict is actually being produced on a concrete change, such as reviewing a pull request or diff, self-reviewing before opening one, or defining a team's code review standards. Triggers include code review, review this PR, pull request review, review checklist, review standards. It is a rubric rather than an analyzer, so it does not apply to merely reading or explaining code, answering how something works, debugging, refactoring, or running linters, formatters, and type checkers.
---

# Code Review Checklist

## Overview

This skill provides a systematic approach to code reviews, ensuring consistent quality standards across your codebase. Use it to conduct thorough, constructive code reviews that improve code quality and team knowledge sharing.

## When to Use This Skill

- Reviewing pull requests
- Defining or documenting a team's review standards
- Establishing code review standards for your team
- Self-reviewing code before submitting
- Mentoring junior developers on code quality
- Complementing the **code-quality agent** for comprehensive reviews

## Evidence and scope

Follow the canonical `/review-pr` procedure. Pin base/head or archive identity and
validate findings against triggers, affected callers and safe counterexamples.
Separate source inspection from runtime reproduction, confirmed defects from
hypotheses, and blocking failures from nonblocking suggestions. Required checks
that could not run make acceptance incomplete; neither an inventory count nor an
uncalibrated grade certifies correctness. Select acceptance evidence using the
`delivery` skill's `references/acceptance-by-task.md`.

## Core Review Categories

### 1. Functionality & Correctness

**Does the code work as intended?**

- [ ] Code accomplishes the intended purpose
- [ ] Edge cases are handled appropriately
- [ ] Error handling is comprehensive
- [ ] Input validation is present and correct
- [ ] Boundary conditions are tested
- [ ] No obvious bugs or logic errors
- [ ] Code handles null/undefined/empty values safely

**Questions to Ask:**
- What happens if this API call fails?
- Are all user inputs validated?
- What if the array is empty?
- Are there any race conditions?

### 2. Design & Architecture

**Is the code well-designed?**

- [ ] Code follows SOLID principles
- [ ] Appropriate design patterns used
- [ ] Separation of concerns is clear
- [ ] No tight coupling between components
- [ ] Abstractions are at the right level
- [ ] Code is modular and reusable
- [ ] Reuses an existing helper, component or pattern before new code; platform/standard library or an installed dependency before a new one
- [ ] Change is right-sized — the smallest complete change for the requirement, with its callers, tests and docs, and no required behavior dropped to shrink the diff
- [ ] No circular dependencies

**Red Flags:**
- God classes (doing too much)
- Parameter groups that obscure responsibility or contracts
- Nesting that demonstrably obscures control flow
- Duplicate code (DRY violation)
- Overly clever code (premature optimization)
- Speculative generality (wrappers, config, patterns or dependencies with no current need)

### 3. Readability & Maintainability

**Can others understand and maintain this code?**

- [ ] Code is self-documenting
- [ ] Variable/function names are descriptive
- [ ] Functions are single-purpose and focused
- [ ] Code follows project style guide
- [ ] Complex logic has explanatory comments
- [ ] Magic numbers are named constants
- [ ] Code structure is logical and intuitive

**Naming Conventions:**
```javascript
// BAD
function d(a, b) { return a + b; }
const x = 42;

// GOOD
function calculateTotalPrice(basePrice, taxRate) {
  return basePrice * (1 + taxRate);
}
const MAX_RETRY_ATTEMPTS = 3;
```

### 4. Testing

**Is the code adequately tested?**

- [ ] Unit tests cover new functionality
- [ ] Edge cases are tested
- [ ] Negative test cases included
- [ ] Tests are readable and maintainable
- [ ] Test names describe what they test
- [ ] No flaky tests
- [ ] Integration tests for complex interactions
- [ ] Coverage meets project policy where specified; behavior, failure paths and critical contracts are exercised (no universal percentage target)

**Test Quality Checks:**
- Tests follow AAA pattern (Arrange, Act, Assert)
- Mocks/stubs are used appropriately
- Tests are independent (no shared state)
- Test data is meaningful, not random

### 5. Security

**Is the code secure?**

- [ ] No sensitive data in code or logs
- [ ] SQL injection prevented (parameterized queries)
- [ ] XSS vulnerabilities addressed
- [ ] CSRF protection implemented
- [ ] Authentication/authorization checks present
- [ ] Secrets stored securely (environment variables, vaults)
- [ ] Input sanitization in place
- [ ] Rate limiting for APIs

**OWASP Top 10:2025 Considerations:**

1. **A01 Broken Access Control** — missing or incorrect authorization, IDOR, CSRF, path traversal (CWE-22), and SSRF (CWE-918, folded into this category in 2025)
2. **A02 Security Misconfiguration** — debug mode on in production, default credentials, permissive CORS, verbose errors, XXE (CWE-611 lives here now)
3. **A03 Software Supply Chain Failures** — vulnerable, unpinned, or unmaintained dependencies, and compromise anywhere in the build/publish chain
4. **A04 Cryptographic Failures** — missing or weak encryption, homegrown crypto, hardcoded keys, cleartext storage or transport
5. **A05 Injection** — SQL, NoSQL, command, LDAP, and template injection; **XSS (CWE-79) is part of this category**
6. **A06 Insecure Design** — missing threat model, no rate limiting, insecure-by-default flows
7. **A07 Authentication Failures** — weak credential handling, session fixation, hardcoded passwords, missing MFA on sensitive actions
8. **A08 Software or Data Integrity Failures** — insecure deserialization (CWE-502), unsigned updates, untrusted CI/CD plugins
9. **A09 Security Logging & Alerting Failures** — security events unlogged, no alerting path, secrets or PII written to logs
10. **A10 Mishandling of Exceptional Conditions** — failing open, swallowed exceptions, error messages leaking internals

Edition: **OWASP Top 10:2025** — <https://owasp.org/Top10/2025/>. Check the edition year above
against the current list before relying on it; the entry this replaced sat two editions stale
(it was the 2017 list, still naming XXE as its own category and omitting supply chain entirely).

### 6. Performance

**Will this code perform well at scale?**

- [ ] No obvious performance bottlenecks
- [ ] Database queries are optimized
- [ ] Indexes are used appropriately
- [ ] No N+1 query problems
- [ ] Appropriate data structures chosen
- [ ] Caching used where beneficial
- [ ] Large datasets handled efficiently
- [ ] Async operations used where appropriate

**Performance Anti-Patterns:**
- Synchronous I/O in loops
- Missing database indexes
- Loading entire datasets into memory
- Unnecessary object creation
- Inefficient algorithms (O(n²) where O(n) possible)

### 7. Documentation

**Is the code adequately documented?**

- [ ] Complex algorithms explained
- [ ] Public APIs documented
- [ ] README updated if needed
- [ ] CHANGELOG updated
- [ ] Migration guide provided (if breaking changes)
- [ ] Code comments explain "why", not "what"
- [ ] Docstrings/JSDoc for functions
- [ ] Architecture decisions recorded (ADRs)

**Good Comment Example:**
```python
# GOOD: Explains WHY
# Use exponential backoff to avoid overwhelming the API
# after transient failures (recommended by vendor)
retry_delay = base_delay * (2 ** attempt)

# BAD: Explains WHAT (obvious from code)
# Set retry_delay to base_delay times 2 to the power of attempt
retry_delay = base_delay * (2 ** attempt)
```

### 8. Dependencies & Libraries

**Are dependencies managed properly?**

- [ ] Dependencies are up-to-date
- [ ] No known security vulnerabilities
- [ ] Dependency versions are pinned
- [ ] License compatibility checked
- [ ] Dependencies are actually needed
- [ ] Bundle size impact considered
- [ ] Dependency documentation reviewed

### 9. Error Handling & Logging

**Are errors handled gracefully?**

- [ ] Errors are caught and handled appropriately
- [ ] Error messages are user-friendly
- [ ] Errors are logged with context
- [ ] No swallowed exceptions
- [ ] Proper logging levels used (DEBUG/INFO/WARN/ERROR)
- [ ] PII not logged
- [ ] Stack traces available for debugging

**Logging Best Practices:**
```javascript
// GOOD: Structured logging with context
logger.error('Payment processing failed', {
  orderId: order.id,
  userId: user.id,
  amount: payment.amount,
  errorCode: error.code
});

// BAD: Generic error logging
console.log('Error');
```

### 10. Code Style & Consistency

**Does the code follow team standards?**

- [ ] Linter passes
- [ ] Formatter applied
- [ ] Naming conventions followed
- [ ] File organization consistent
- [ ] Import statements organized
- [ ] No commented-out code
- [ ] No debug statements (console.log, etc.)

## Review Process Guidelines

### Before You Review

1. **Understand the context**
   - Read the PR description
   - Review linked issues/tickets
   - Understand the "why" behind the change

2. **Set aside time**
   - Don't rush reviews
   - Block dedicated time for thorough analysis
   - Review in multiple sessions if large PR

3. **Check CI/CD**
   - Ensure tests pass
   - Check build succeeds
   - Review test coverage reports

### During Review

1. **Be constructive**
   - Praise good code
   - Suggest, don't demand
   - Explain your reasoning
   - Offer alternatives

2. **Use review labels**
   - **Nitpick**: Minor suggestion, not blocking
   - **Question**: Seeking clarification
   - **Suggestion**: Proposed improvement
   - **Issue**: Needs to be addressed before merge

3. **Focus on what matters**
   - Prioritize functionality and security
   - Don't bike-shed over style (use linters)
   - Consider technical debt trade-offs
   - Ground each finding in a concrete consequence and the caller or line it affects; don't raise speculative complexity or cite metrics you didn't measure

### Giving Feedback

**Good Feedback Examples:**

```
✅ "Great use of the factory pattern here! This makes the code much
more testable. Consider extracting the validation logic into a
separate validator class for even better separation of concerns."

✅ "Question: What happens if the API returns a 429 (rate limit)?
Should we implement exponential backoff here?"

✅ "Suggestion: Instead of nested if statements, consider using
early returns to reduce complexity:
[code example]"
```

**Avoid:**

```
❌ "This is wrong."
❌ "Why didn't you use X pattern?"
❌ "This code is terrible."
❌ Rewriting entire sections without explanation
```

### Review Size Guidelines

**Small PR (< 200 lines):**
- Ideal size
- 15-30 minutes to review
- Easy to understand and test

**Medium PR (200-500 lines):**
- Acceptable
- 30-60 minutes to review
- May need to be split across sessions

**Large PR (> 500 lines):**
- Consider a responsibility-based split when it preserves complete, independently reviewable behavior
- Difficult to review thoroughly
- Higher chance of bugs slipping through

## Self-Review Checklist

Before submitting your PR, review your own code:

- [ ] Re-read your changes with fresh eyes
- [ ] Run tests locally
- [ ] Check test coverage
- [ ] Remove debug statements
- [ ] Update documentation
- [ ] Add descriptive commit messages
- [ ] Ensure PR description is clear
- [ ] Consider reviewer's perspective

## Team-Specific Considerations

Customize this checklist for your team:

- **Technology-specific checks** (React hooks rules, async/await patterns)
- **Business logic validation** (pricing calculations, data transformations)
- **Compliance requirements** (GDPR, HIPAA, SOX)
- **Company coding standards** (internal style guides)
- **Performance benchmarks** (API response time < 200ms)

## Quick Reference: Review Commands

**Inline Comments:**
- Be specific: Reference line numbers
- Provide examples: Show better alternatives
- Link to docs: Reference style guides

**Approval Criteria (code verdict for the exact reviewed head):**
- Required review scope completed: affected source, callers, tests and contracts, plus the applicable domains (correctness, security, error handling, tests, documentation); any domain not covered is named as a gap
- No unresolved blocking finding; each confirmed finding was validated against its trigger and safe counterexamples
- Acceptance evidence for the task type is present (`delivery` skill `references/acceptance-by-task.md`); missing required evidence makes the verdict INCOMPLETE, not approved
- Documentation and CHANGELOG updated where the project requires them
- The report states the inspected scope, commands run and remaining gaps; approval attests that reviewed scope only, never the absence of all defects or vulnerabilities
- Required machine checks at the same head are a separate merge gate, not part of the code verdict

**Request Changes When:**
- Bugs or logic errors present
- Security issues found
- Tests are missing or inadequate
- Breaks existing functionality
- Violates architectural principles

## Resources

For deeper dives, see:
- `.claude/skills/README.md` - Skills system overview
- OWASP guidelines for security reviews
- Google's Code Review Developer Guide
- Team-specific style guides
