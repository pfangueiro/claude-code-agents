# 🚀 Claude Agents - Quick Deployment Guide

Deploy auto-activating AI agents to any project in seconds.

## Option 1: One-Line Installation (Recommended)

Run this in your project root:

```bash
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install-claude-config.sh | bash
```

## Option 2: Manual Installation

### For New Projects (No CLAUDE.md)

Copy `CLAUDE-minimal.md` to your project as `CLAUDE.md`:

```bash
cp path/to/CLAUDE-minimal.md ./CLAUDE.md
```

### For Existing Projects (Has CLAUDE.md)

Append the agent section from `CLAUDE-append-section.md` to your existing `CLAUDE.md`.

## Option 3: Ultra-Minimal (3 Lines)

Add just this to any `CLAUDE.md`:

```markdown
## 🤖 Auto-Activating Agents
Specialized agents auto-activate when you use natural language:
design→architecture | review→quality | security→auditor | test→automation | slow→performance | deploy→devops | document→docs | database→architect | UI→frontend | API→backend | CRITICAL→incident
```

## 🎯 That's It!

Once added, just use natural language:
- "Design a REST API" → architecture-planner activates
- "This is running slow" → performance-optimizer activates
- "Check security" → security-auditor activates
- "Production is down!" → incident-commander activates

**No configuration. No setup. Just describe what you need.**

## Files Included

| File | Purpose | Size |
|------|---------|------|
| `CLAUDE-minimal.md` | Complete minimal CLAUDE.md | ~45 lines |
| `CLAUDE-append-section.md` | Section to append to existing files | ~20 lines |
| `install-claude-config.sh` | Automatic installation script | Detects & merges |
| `CLAUDE-DEPLOYMENT.md` | This guide | You're reading it |

## Why Minimal?

- **Zero friction** - Add to any project instantly
- **No bloat** - Just the essentials for auto-activation
- **Merge-friendly** - Won't conflict with existing configs
- **Self-documenting** - Table format shows everything at a glance

## Advanced: Full System

For the complete agent system with all features:
1. Copy the entire `.claude/` directory to your project
2. Use the full `CLAUDE.md` (63 lines) for comprehensive documentation

## Support

The agents will auto-activate based on keywords. No other configuration needed. If agents aren't activating:
1. Ensure `CLAUDE.md` exists in your project root
2. Verify you're using Claude Code (claude.ai/code)
3. Use the trigger keywords naturally in conversation

---

*Powered by enterprise-grade SDLC/SSDLC agents with Opus for security, Haiku for docs (95% savings), and natural language activation.*