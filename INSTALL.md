# 🚀 Claude Agents - Installation Guide

## One-Line Installation (Recommended)

Run this command in your project root:

```bash
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

Or with wget:

```bash
wget -qO- https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

## Installation Options

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

### Minimal Mode
```
CLAUDE.md                  # Agent auto-activation config
```

### Full Mode
```
CLAUDE.md                  # Agent auto-activation config
.claude/
├── agents/                # 11 specialized agents
│   ├── architecture-planner.md
│   ├── code-quality.md
│   ├── security-auditor.md
│   ├── test-automation.md
│   ├── performance-optimizer.md
│   ├── devops-automation.md
│   ├── documentation-maintainer.md
│   ├── database-architect.md
│   ├── frontend-specialist.md
│   ├── api-backend.md
│   ├── incident-commander.md
│   └── meta-agent.md
├── skills/                # Modular knowledge packages
│   ├── skill-creator/     # Create new skills
│   ├── git-workflow/      # Git best practices (demo)
│   ├── code-review-checklist/ # Review guidelines (demo)
│   └── deployment-runbook/    # Deployment procedures (demo)
├── lib/                   # Supporting files
│   ├── agent-templates.json
│   ├── sdlc-patterns.md
│   └── activation-keywords.json
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
| `./install.sh` | Interactive | First time or unsure |
| `./install.sh --minimal` | CLAUDE.md only | Quick setup |
| `./install.sh --full` | Everything | Complete system |
| `./install.sh --repair` | Fix issues | Missing components |
| `./install.sh --update` | Latest version | Upgrade existing |

---

*The installer is intelligent - it detects what you have and installs only what you need.*