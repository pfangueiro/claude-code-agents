# Claude Agents - Installation Guide

## Install (one command, user-global)

Clone the repo and run the installer:

```bash
git clone git@github.com:pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh
```

That's it. Everything installs **once**, user-global to `~/.claude`. Claude Code natively loads `~/.claude/{agents,skills,commands,rules}`, so every project on your machine gets the agents automatically — there is no per-project step.

The install includes: agents, skills, commands, rules, hooks, statusline, output styles, the observability dashboard, MCP servers, and global settings.

## Commands

| Command | What it does |
|---------|-------------|
| `./install.sh` | Install everything user-global to `~/.claude` |
| `./install.sh --update` | Reconcile an existing install to the latest version (backs up first, preserves customizations) |
| `./install.sh --help` | Show all options |

## What Gets Installed

Everything lands under `~/.claude/` and is loaded by Claude Code in every project:

```
~/.claude/
├── agents/                # 13 specialized agents
├── commands/              # 13 slash commands
├── skills/                # 28 modular knowledge packages
├── rules/                 # 6 auto-enforced rule sets
├── lib/                   # Activation patterns, templates, coordination protocol
├── hooks/                 # 9 command hooks + 2 reference configs
├── daemon/                # launchd watchdog (hourly validate + snapshots)
├── analytics/             # Observability dashboard (claude-obs alias)
├── output-styles/
│   └── concise.md         # Code-first output style
├── statusline.sh          # Rich status bar
├── settings.json          # Model, hooks, deny rules, MCP config
└── CLAUDE.md              # Personal coding preferences (personalized with your name/email)
```

The installer also:

- Merges or installs global settings in `~/.claude/settings.json`
- Ships an MCP reference guide (`~/.claude/lib/mcp-guide.md`); add your own MCP servers per Claude Code's docs (MCP config is machine-specific and not auto-installed)
- Installs the observability dashboard with the `claude-obs` alias
- Checks prerequisites (`git`, `curl` required; `jq`, `npx` optional)

## Update & migrate other machines

The framework is **self-updating**: after a `git pull` on any machine, the SessionStart healthcheck and the launchd watchdog automatically fork `install.sh --update` to reconcile `~/.claude` — you don't have to run the installer by hand. `git pull` is the one deliberate trigger (there is deliberately **no auto-pull**).

```bash
cd claude-code-agents && git pull --ff-only    # the one manual step; the rest is autonomous
./install.sh --update                          # optional: reconcile now instead of waiting for self-heal
```

`--update` re-copies the framework's shared set to `~/.claude` (replacing framework files so drift heals) while preserving your own `~/.claude/CLAUDE.md`, personal skills, and settings.

**Optional — autonomously migrate old per-project `.claude/` copies.** If you previously deployed the framework into individual projects, create an opt-in marker so `--update` migrates them to user-global for you:

```bash
echo 'LEGACY_PROJECTS_DIR=/absolute/path/to/your/projects' > ~/.claude/.framework-autonomy
```

With the marker set, the framework removes its own shared-set subdirs from projects under that dir — **only when git-untracked** (never rewrites a repo's history), **framework-scoped** (your custom agents/skills are never touched), **snapshot-first** (to `~/.claude/snapshots/`), and idempotent. No marker → nothing happens. The watchdog re-runs this every cycle, so setting the marker migrates old copies within the hour; run `./install.sh --migrate-legacy` to do it immediately.

## Safety Features

- **Automatic Backups** — Creates timestamped backups before modifications
- **Non-Destructive** — Never overwrites without backing up
- **Idempotent** — Safe to run multiple times
- **Verification** — Confirms successful installation

## Installation Summary

After installation, you'll see:

```
=== Installation Summary ===
┌─────────────────────────────┐
│ Components Checked:      45 │
│ Components Installed:    11 │
│ Components Skipped:       0 │
│ Components Updated:       0 │
│ Files Backed Up:          1 │
└─────────────────────────────┘
```

## Usage After Installation

Open any project with Claude Code and use natural language:

```
"Design a user authentication system"
"Check this code for security issues"
"Why is this query running slow?"
"Deploy this to production"
```

Agents auto-activate based on your words — no commands needed.

## Troubleshooting

### Permission Denied
```bash
chmod +x install.sh
./install.sh
```

### Network Issues
Download the script locally:
```bash
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh > install.sh
chmod +x install.sh
./install.sh
```

### Verification Failed
Reconcile the install:
```bash
./install.sh --update
```

## Uninstallation

The framework installs into `~/.claude`, which also holds your personal Claude Code data (your own `CLAUDE.md`, `projects/`, `settings.json`). Do **not** `rm -rf ~/.claude`. Remove only the framework-owned components:

```bash
rm -rf ~/.claude/agents ~/.claude/commands ~/.claude/skills \
       ~/.claude/rules ~/.claude/lib ~/.claude/hooks ~/.claude/daemon \
       ~/.claude/output-styles ~/.claude/statusline.sh
```

Then edit `~/.claude/settings.json` and `~/.claude/CLAUDE.md` by hand to remove the framework's `hooks`/statusline blocks and the agent auto-activation section (between the `CLAUDE AGENTS AUTO-ACTIVATION SECTION START`/`END` markers) if you want them gone.

To unload the background watchdog:
```bash
launchctl bootout gui/$(id -u)/com.claude-code-agents.framework-watchdog 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist
```

## Support & Updates

- **Repository**: github.com/pfangueiro/claude-code-agents
- **Issues**: Report problems in GitHub Issues
- **Updates**: Run `./install.sh --update` to get the latest version

---

*One install, user-global — the agents are available in every project on your machine.*
