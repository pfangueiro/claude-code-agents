---
name: security-scan
description: Scan the project or specified path for security vulnerabilities. Auto-activates on security-sensitive code patterns (auth, crypto, input handling, SQL, file uploads). Also available as /security-scan command.
---

# Security Scan

## Overview

Comprehensive security vulnerability scanner that checks for secrets, dependency vulnerabilities, OWASP code patterns, and file permission issues. This skill can be invoked explicitly via `/security-scan` or activates autonomously when the security-auditor agent detects security-sensitive code.

## When This Skill Activates

**Explicit invocation:** `/security-scan [path]`

**Autonomous activation** (via security-auditor agent) when code touches:
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

- If `package.json` exists, check for `npm audit` issues
- If `requirements.txt` or `pyproject.toml` exists, note that `pip-audit` or `safety` should be run
- If `Cargo.toml` exists, note that `cargo audit` should be run
- Flag dependencies with known CVEs if detectable from lock files

### 4. OWASP Code Patterns

- **Injection**: String concatenation in SQL queries, shell commands with user input, template injection
- **Broken Auth**: Missing auth checks on routes, weak password requirements, session fixation
- **Sensitive Data**: Logging sensitive data, missing encryption for PII, cleartext storage
- **XSS**: Unescaped user input in HTML/JSX output, `dangerouslySetInnerHTML`, `v-html`
- **Insecure Deserialization**: `eval()`, `JSON.parse` on untrusted input without validation, `pickle.loads`
- **Misconfiguration**: Debug mode in production, permissive CORS (`*`), missing security headers
- **SSRF**: Unvalidated URLs in server-side requests
- **Path Traversal**: User-controlled file paths without sanitization

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

### Critical
- [ ] <finding with file:line and remediation>

### High
- [ ] <finding with file:line and remediation>

### Medium
- [ ] <finding with file:line and remediation>

### Low
- [ ] <finding with file:line and remediation>

### Summary
- Total findings: <count>
- Critical: <count>  High: <count>  Medium: <count>  Low: <count>

### Top 3 Recommendations
1. <most impactful fix>
2. <next most impactful>
3. <third priority>
```

## Integration

- Complements the **security-auditor** agent (which uses Opus for maximum intelligence)
- Works with the `file-protection.sh` hook (which blocks edits to .env, *.key, *.pem)
- Works with the `smart-guard.sh` hook (which audits dangerous operations)
- Follows the project's `security.md` rules
