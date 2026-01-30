# Global Config

Shareable Claude Code configuration files. These get installed to `~/.claude/` during `--team-setup`.

## Files

| File | Install Target | Purpose |
|------|---------------|---------|
| `hooks/notify.sh` | `~/.claude/hooks/notify.sh` | Desktop notification when Claude needs attention (Linux + macOS) |
| `hooks/post-edit-lint.sh` | `~/.claude/hooks/post-edit-lint.sh` | Auto-lint TS/JS files after Write/Edit tool use |
| `output-styles/concise.md` | `~/.claude/output-styles/concise.md` | Code-first, minimal prose output style |
| `statusline.sh` | `~/.claude/statusline.sh` | Rich status bar: model, git branch, cost, context usage |
| `keybindings.json` | `~/.claude/keybindings.json` | Keyboard shortcuts (Ctrl+S commit, Ctrl+P plan) |
| `settings.json.template` | `~/.claude/settings.json` | Global settings: model, hooks, statusline, deny rules |
| `CLAUDE.md.template` | `~/.claude/CLAUDE.md` | Personal coding preferences (name/email placeholders) |

## Settings Template

The `settings.json.template` defaults to **Sonnet** model (team default). Override per-user:
- Change `"model": "sonnet"` to `"opus"` in `~/.claude/settings.json` if you have access

## CLAUDE.md Template

Contains `__YOUR_NAME__` and `__YOUR_GIT_EMAIL__` placeholders. The installer replaces these with values from `git config` during `--team-setup`.

## Prerequisites

- `git` and `curl` (required)
- `jq` (optional, for statusline and settings merge)
- `npx` (optional, for MCP servers)
- `notify-send` (Linux) or `osascript` (macOS) for desktop notifications
