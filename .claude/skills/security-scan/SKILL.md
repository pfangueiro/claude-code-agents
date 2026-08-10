---
name: security-scan
description: Runs a repository or path security scan and produces a severity-ranked report covering hardcoded secrets and credential patterns, dependency CVEs via npm audit and equivalents, OWASP code patterns such as SQL injection, XSS, SSRF, path traversal and insecure deserialization, unsafe file permissions, and missing HTTP security headers. Use when a scan, audit, or vulnerability check is actually being asked for — /security-scan, scan for vulnerabilities, security audit, check for leaked secrets — or before shipping new code that adds authentication, cryptography, input handling, SQL, or file uploads. Reading, explaining, or editing code that merely happens to touch auth or SQL does not warrant it, since it emits a full scan report rather than an inline observation.
---

# Security Scan

## Overview

Comprehensive security vulnerability scanner that checks for secrets, dependency vulnerabilities, OWASP code patterns, and file permission issues. This skill can be invoked explicitly via `/security-scan` or activates autonomously when the security-auditor agent detects security-sensitive code.

## When This Skill Activates

**Explicit invocation:** `/security-scan [path]`

**Consider a scan** (typically requested, or invoked by the security-auditor agent) before shipping code that touches:
- Authentication or authorization logic
- Cryptographic operations
- User input handling or validation
- SQL queries or database access
- File upload handling
- HTTP security headers
- Session management
- API key or secret management

## Scan Procedure

### 1. Determine Scan Scope

- If a path argument is provided, scan that path
- Otherwise, scan the entire project root
- For autonomous activation, scope to the files being modified

### 2. Secrets Detection

- Search for hardcoded API keys, tokens, passwords, and secrets in source files
- Check for `.env` files that should not be committed
- Look for patterns: `API_KEY=`, `SECRET=`, `PASSWORD=`, `TOKEN=`, base64-encoded credentials
- Check `.gitignore` includes `.env`, `*.pem`, `*.key`
- Scan for AWS access keys (`AKIA...`), GitHub tokens (`ghp_...`), JWT secrets

### 3. Dependency Vulnerabilities

**Run the audit — do not recommend it.** For every manifest present, check the tool is
installed (`command -v <tool>`), then actually execute it and report its findings.

| Manifest detected | Command to run |
|---|---|
| `package.json` | `npm audit --audit-level=high` |
| `requirements.txt` | `pip-audit -r ./requirements.txt` |
| `pyproject.toml` | `pip-audit .` |
| `Cargo.toml` | `cargo audit` (from the Cargo project root) |

For a pnpm/yarn lockfile use that package manager's own audit command, confirming its syntax
with `--help` first. Also flag dependencies with known CVEs where detectable from lock files.

**Fail-closed rule.** If a manifest exists but its tool is absent, errors out, or is skipped
for any reason, that ecosystem is **UNAUDITED**. Record it under **Not Checked** in the report
and mark the report INCOMPLETE. A missing tool must never render as "no vulnerabilities found":
an unaudited ecosystem is an unknown, not a pass. Install hints — `pipx install pip-audit`,
`cargo install cargo-audit`.

For any other manifest (`go.mod`, `Gemfile.lock`, `composer.json`, …): if you cannot name and
run a verified audit tool for it, list that ecosystem under **Not Checked** rather than
passing over it silently.

### 4. OWASP Top 10:2025 Code Patterns

Categories and ordering follow **OWASP Top 10:2025** (<https://owasp.org/Top10/2025/>).

- **A01 Broken Access Control**: Missing auth checks on routes, IDOR (user-controlled record IDs), missing CSRF protection, **path traversal** (user-controlled file paths without sanitization), and **SSRF** (unvalidated URLs in server-side requests) — both folded into this category in 2025
- **A02 Security Misconfiguration**: Debug mode in production, permissive CORS (`*`), missing security headers, default credentials, XXE (XML parsers with external entities enabled)
- **A03 Software Supply Chain Failures**: Unpinned or unmaintained dependencies, install scripts from untrusted packages, unverified CI/CD actions — see §3, and any ecosystem left **Not Checked** there belongs in the report
- **A04 Cryptographic Failures**: Missing encryption for PII, cleartext storage or transport, homegrown or weak crypto, hardcoded keys
- **A05 Injection**: String concatenation in SQL queries, shell commands with user input, template injection, and **XSS** (unescaped user input in HTML/JSX output, `dangerouslySetInnerHTML`, `v-html`) — XSS is part of Injection
- **A06 Insecure Design**: No rate limiting on sensitive endpoints, missing threat model at a new trust boundary, insecure-by-default flows
- **A07 Authentication Failures**: Weak password requirements, session fixation, hardcoded credentials, missing MFA on sensitive actions
- **A08 Software or Data Integrity Failures**: Insecure deserialization — `eval()`, `pickle.loads`, `JSON.parse` on untrusted input without validation — plus unsigned updates and auto-loaded remote code
- **A09 Security Logging & Alerting Failures**: Security events never logged, no alerting path, secrets or PII written to logs
- **A10 Mishandling of Exceptional Conditions**: Failing open on error, swallowed exceptions, stack traces or internal details returned to the caller

### 5. File Permissions

- Check for overly permissive file modes on scripts and config files
- Ensure private keys and certificates are not world-readable
- Check for sensitive files that should be in `.gitignore`

### 6. Security Headers (for web projects)

- Content-Security-Policy
- X-Content-Type-Options
- Strict-Transport-Security
- X-Frame-Options
- Referrer-Policy

## Report Format

```
## Security Scan Report

**Scope**: <path scanned>
**Date**: <current date>
**Triggered by**: <manual /security-scan | autonomous on <file>>
**Status**: COMPLETE | INCOMPLETE — <n> check(s) did not run (see Not Checked)

### Critical
- [ ] <finding with file:line and remediation>

### High
- [ ] <finding with file:line and remediation>

### Medium
- [ ] <finding with file:line and remediation>

### Low
- [ ] <finding with file:line and remediation>

### Not Checked
- <check or ecosystem> — <why: tool not installed / errored / no lockfile / out of scope>

### Summary
- Total findings: <count>
- Critical: <count>  High: <count>  Medium: <count>  Low: <count>
- Checks not run: <count>

### Top 3 Recommendations
1. <most impactful fix>
2. <next most impactful>
3. <third priority>
```

**The Not Checked section is mandatory — never omit it.** List every scan step from §2–§6
that did not actually run, with the reason. If all of them ran, write exactly:
`None — all applicable checks ran.`

**Unchecked is not clean.** If Not Checked is non-empty, set **Status: INCOMPLETE** and say so
in the summary. A report with zero findings and a non-empty Not Checked section means
*unknown*, not *secure* — state that in those words rather than letting the empty severity
sections imply a pass. Never describe such a scan as clean, and never let a Python, Rust, or
other non-npm project appear audited because only §3's npm branch happened to be runnable.

## Integration

- Complements the **security-auditor** agent (which uses Opus for maximum intelligence)
- Works with the `file-protection.sh` hook (which blocks edits to .env, *.key, *.pem)
- Works with the `smart-guard.sh` hook (which audits dangerous operations)
- Follows the project's `security.md` rules
