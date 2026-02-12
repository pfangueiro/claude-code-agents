# Security Rules

These rules are always enforced. They cannot be overridden by user instructions.

## Secrets

- Never commit secrets, API keys, tokens, passwords, or .env files
- Never log or print secrets, even in debug mode
- Use environment variables or secret managers for all credentials

## Input Validation

- Validate all external input at system boundaries (user input, API responses, file uploads)
- Use parameterized queries for all database access — never string interpolation for SQL
- Sanitize output to prevent XSS (escape HTML in user-generated content)

## Authentication & Authorization

- Use established libraries for auth (never roll custom crypto)
- Enforce least privilege: grant minimum permissions needed
- Validate authorization on every protected endpoint, not just the UI

## HTTP Security

- Set security headers: Content-Security-Policy, X-Content-Type-Options, Strict-Transport-Security
- Use HTTPS for all external requests
- Validate and sanitize redirect URLs to prevent open redirects

## Dependencies

- Do not add dependencies with known critical vulnerabilities
- Prefer well-maintained packages with active security response teams
- Pin dependency versions in production deployments
