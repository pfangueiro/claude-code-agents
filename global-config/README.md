# Global Config

Shareable Claude Code configuration files. These get installed to `~/.claude/` by `install.sh` (the canonical user-global install).

This directory is **Claude-specific**. Codex's independent installer lives at
`install-codex.sh`; it does not translate settings.json into config.toml or reuse
the Claude watchdog/collector/statusline. [Codex setup](../codex/README.md).

## Files

| File | Install Target | Purpose |
|------|---------------|---------|
| `hooks/*.sh` (9) | `~/.claude/hooks/` | Command hooks: the 6 core hooks always; `agent-tracker.sh` and `session-end.sh` with `--with-analytics`; `notify.sh` with `--with-notifications` |
| `hooks/*.json` (2) | `~/.claude/hooks/` | Reference prompt/agent hook configs (opt-in, not wired) |
| `daemon/` | `~/.claude/daemon/` and `~/Library/LaunchAgents/` | Observe-only launchd watchdog (`--with-watchdog`, macOS only) |
| `output-styles/concise.md` | `~/.claude/output-styles/concise.md` | Code-first, minimal-prose output style (replaced on drift) |
| `statusline.sh` | `~/.claude/statusline.sh` | Status bar: model, git branch, cost, context usage and a framework-status glyph (replaced on drift) |
| `settings.json.template` | `~/.claude/settings.json` | Seeds a new file. Later runs reconcile only `.hooks`, `.permissions`, `.attribution` and `.statusLine`, plus add-only `.env` |
| `CLAUDE.md.template` | `~/.claude/CLAUDE.md` | Personal preferences seed (written only if absent) |
| `.mcp.json.example` | Not installed | MCP connection example (never registered automatically) |

## Settings Template

The template seeds `"model": "sonnet"` only when `~/.claude/settings.json` is created. Later
updates do not reconcile `model`, so any value you set stays. `.permissions`, `.attribution`,
`.statusLine` and framework hook bindings are replaced on drift, so keep personal overrides in
`~/.claude/settings.local.json`.

## CLAUDE.md Template

Contains `__YOUR_NAME__` and `__YOUR_GIT_EMAIL__` placeholders. The installer replaces these with values from `git config` on first install (it skips an existing `~/.claude/CLAUDE.md`, so your own file is never overwritten).

The generated file is personal and seed-only. A re-install, `--update` or `--upgrade` never replaces it, and `--uninstall` never removes it. Template improvements therefore reach an existing user only if they copy them in by hand. The template contains generic coding, Git, security, testing and delivery/quality preferences, with no provider, model, account or host policy.

## Prerequisites

- `git` and `curl` (required)
- `jq` (optional, for statusline and settings merge)
- `npx` (optional, for MCP servers)
- `notify-send` (Linux) or `osascript` (macOS) for desktop notifications

MCP examples are connection templates, not automatic registrations. Do not infer
Codex permission/model configuration from Claude aliases or hook types.
