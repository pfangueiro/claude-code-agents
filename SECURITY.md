# Security Policy

## Supported Versions

The latest minor release line is the only supported one. Older releases do
not receive backports.

| Version | Supported |
|---------|-----------|
| 2.9.x   | Yes |
| < 2.9   | No |

## Reporting a Vulnerability

If you find a security issue in this framework — for example, a script that
permits command injection from untrusted input, a hook that writes to a
sensitive location without validation, or a self-healing path that could be
abused to clobber user data — please **do not open a public issue**.

Instead:

1. Open a [private security advisory](https://github.com/pfangueiro/claude-code-agents/security/advisories/new) on GitHub.
2. Include: reproduction steps, affected files/functions, suggested severity, and (if you have one) a proposed patch.
3. Expect an acknowledgment within 7 days.

If the advisory mechanism is unavailable for any reason, contact the maintainer
listed in `LICENSE` via the email associated with their GitHub account.

## Scope

The framework executes shell scripts on your machine with your user's
privileges. The intended threat model assumes:

- **You trust the repository contents** before installing. Run `./validate.sh`
  on the source tree to see what's about to be deployed.
- **External input is sanitized at boundaries** — hooks that read stdin JSON
  use `jq` for parsing, not shell interpolation.
- **No automatic remote code execution** — `install.sh` only runs scripts that
  already exist in this repository; nothing is fetched from the network at
  install time (except optional MCP package installs via `npx`, which is
  explicit and user-driven).

Out of scope:

- Vulnerabilities in third-party MCP servers (report to those projects directly).
- Vulnerabilities in Claude Code itself (report to Anthropic).
- Issues that require an attacker to already have local code-execution as the user.

## Defensive Posture

This framework intentionally enables several safety features by default:

- **Secret scanning + push protection** are enabled on this GitHub repository.
- **No `eval` / `exec` of user input** anywhere in `install.sh`, `deploy-all.sh`,
  `validate.sh`, or the hook scripts. (Verified via grep; see security-scan in
  the audit history.)
- **Hooks log to JSONL audit streams** under `~/.claude/analytics/` for
  postmortem analysis.
- **Pre-install backups** are written per-project before any `--update` (kept
  3 deep, rotated automatically).
- **Snapshot restore paths** for `.git`, `~/.claude/hooks/`, and
  `~/.claude/settings.json` documented in CLAUDE.md (Self-Healing section).

## Privacy

This repository is public and has been audited for personal-information leakage
(history rewrite via `git-filter-repo` in v2.9.4). When contributing, do not
introduce:

- Hardcoded user paths (`/Users/<name>/...`)
- Personal project names from your local environment
- Machine hostnames or email addresses other than the public GitHub noreply form

The `.gitignore` covers common pitfalls (`.mcp.json`, `.claude/.framework-version`,
`.claude-backup-*/`).
