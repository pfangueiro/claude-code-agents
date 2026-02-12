---
description: "Scan the project or specified path for security vulnerabilities"
argument-hint: "[path]"
---

Perform a security scan on the project or the path specified by the argument (defaults to the project root if no argument given).

## Steps

1. **Determine scan scope**:
   - If `$ARGUMENTS` is provided, scan that path
   - Otherwise, scan the entire project root

2. **Secrets Detection**:
   - Search for hardcoded API keys, tokens, passwords, and secrets in source files
   - Check for `.env` files that should not be committed
   - Look for patterns: `API_KEY=`, `SECRET=`, `PASSWORD=`, `TOKEN=`, base64-encoded credentials
   - Check `.gitignore` includes `.env`, `*.pem`, `*.key`

3. **Dependency Vulnerabilities**:
   - If `package.json` exists, check for `npm audit` issues
   - If `requirements.txt` or `pyproject.toml` exists, note that `pip-audit` or `safety` should be run
   - Flag dependencies with known CVEs if detectable from lock files

4. **OWASP Code Patterns**:
   - **Injection**: String concatenation in SQL queries, shell commands with user input
   - **Broken Auth**: Missing auth checks on routes, weak password requirements
   - **Sensitive Data**: Logging sensitive data, missing encryption for PII
   - **XSS**: Unescaped user input in HTML/JSX output, `dangerouslySetInnerHTML`
   - **Insecure Deserialization**: `eval()`, `JSON.parse` on untrusted input without validation
   - **Misconfiguration**: Debug mode in production, permissive CORS, missing security headers

5. **File Permissions**:
   - Check for overly permissive file modes on scripts and config files
   - Ensure private keys and certificates are not world-readable

6. **Generate security report**:

```
## Security Scan Report

**Scope**: <path scanned>
**Date**: <current date>

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
```

7. **Recommendations**: List the top 3 most impactful fixes to prioritize.
