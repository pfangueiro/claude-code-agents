# Claude Agents - Installation Guide

## Team Setup (Recommended)

Clone the repo and run the full team onboarding:

```bash
git clone git@github.com:pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh --team-setup
```

This installs everything: agents, skills, commands, hooks, statusline, keybindings, output styles, and global settings.

## Installation Options

| Command | What it does |
|---------|-------------|
| `./install.sh --team-setup` | Full team onboarding (project + global config) |
| `./install.sh` | Interactive mode (detects existing setup) |
| `./install.sh --minimal` | CLAUDE.md only (agent activation) |
| `./install.sh --full` | All agents + library files (project-level) |
| `./install.sh --repair` | Fix missing components |
| `./install.sh --update` | Update to latest version |

### Team Setup
```bash
./install.sh --team-setup
```
- Installs all 11 agents, skills, and library files (project-level)
- Installs slash commands (`.claude/commands/`)
- Installs hooks, statusline, keybindings, output styles (`~/.claude/`)
- Merges or installs global settings (`~/.claude/settings.json`)
- Personalizes `~/.claude/CLAUDE.md` with your name and email
- Checks prerequisites (`git`, `curl` required; `jq`, `npx` optional)

### Interactive Mode (Default)
```bash
./install.sh
```
- Detects existing components
- Recommends best installation type
- Offers choices: Minimal, Full, Repair, or Update

### Minimal Installation
```bash
./install.sh --minimal
```
- Adds only CLAUDE.md for agent auto-activation
- Perfect for quick setup
- No file dependencies

### Full Installation
```bash
./install.sh --full
```
- Installs all 11 agents
- Adds supporting library files
- Complete system deployment

### Repair Installation
```bash
./install.sh --repair
```
- Fixes missing components
- Preserves existing files
- Adds only what's needed

### Update Installation
```bash
./install.sh --update
```
- Updates all components to latest version
- Creates backup before updating
- Preserves customizations

## What Gets Installed

### Team Setup Mode (`--team-setup`)
```
# Project-level (current directory)
CLAUDE.md                          # Agent auto-activation config
.claude/
├── agents/                        # 11 specialized agents
├── commands/                      # Slash commands (/new-feature, /commit-pr, /create-jira)
├── skills/                        # Modular knowledge packages
├── lib/                           # Activation patterns & templates
└── history/                       # Usage tracking (auto-created)

# Global (~/.claude/)
~/.claude/
├── hooks/
│   ├── notify.sh                  # Desktop notification hook
│   └── post-edit-lint.sh          # Auto-lint after Write/Edit
├── output-styles/
│   └── concise.md                 # Code-first output style
├── statusline.sh                  # Rich status bar
├── keybindings.json               # Ctrl+S commit, Ctrl+P plan
├── settings.json                  # Model, hooks, deny rules, attribution
└── CLAUDE.md                      # Personal coding preferences
```

### Minimal Mode
```
CLAUDE.md                  # Agent auto-activation config
```

### Full Mode
```
CLAUDE.md                  # Agent auto-activation config
.claude/
├── agents/                # 11 specialized agents
├── skills/                # Modular knowledge packages
├── lib/                   # Supporting files
└── history/               # Usage tracking (auto-created)
```

## Detection Features

The installer intelligently detects:

1. **Existing .claude directory** - Preserves your files
2. **Installed agents** - Skips duplicates
3. **Library files** - Only adds missing ones
4. **CLAUDE.md status** - Merges or creates as needed
5. **Partial installations** - Offers repair option

## Safety Features

- **Automatic Backups** - Creates timestamped backups before modifications
- **Non-Destructive** - Never overwrites without backing up
- **Idempotent** - Safe to run multiple times
- **Verification** - Confirms successful installation
- **Rollback Ready** - Backups allow easy restoration

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

Once installed, just use natural language:

```
"Design a user authentication system"
"Check this code for security issues"
"Why is this query running slow?"
"Deploy this to production"
```

Agents auto-activate based on your words - no commands needed!

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
Run repair mode:
```bash
./install.sh --repair
```

### Custom Installation Path
The installer works in the current directory. Navigate to your project:
```bash
cd /path/to/your/project
./install.sh
```

## Uninstallation

To remove the agent system:
```bash
rm -rf .claude
# Optionally remove or edit CLAUDE.md
```

To keep agents but remove from CLAUDE.md:
- Remove the section between:
  - `<!-- ============ CLAUDE AGENTS AUTO-ACTIVATION SECTION START ============ -->`
  - `<!-- ============ CLAUDE AGENTS AUTO-ACTIVATION SECTION END ============ -->`

## Support & Updates

- **Repository**: github.com/pfangueiro/claude-code-agents
- **Issues**: Report problems in GitHub Issues
- **Updates**: Run `./install.sh --update` to get latest version

## Quick Reference

| Command | Action | Use When |
|---------|--------|----------|
| `./install.sh --team-setup` | Full onboarding | New team member |
| `./install.sh` | Interactive | First time or unsure |
| `./install.sh --minimal` | CLAUDE.md only | Quick setup |
| `./install.sh --full` | Everything | Complete system |
| `./install.sh --repair` | Fix issues | Missing components |
| `./install.sh --update` | Latest version | Upgrade existing |

---

*The installer is intelligent - it detects what you have and installs only what you need.*