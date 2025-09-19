# Claude Agents - AI Coding Assistant

**Smart AI agent system with automatic model selection for 70% cost savings**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Bash Version](https://img.shields.io/badge/Bash-4.0%2B-green)](https://www.gnu.org/software/bash/)
[![Models](https://img.shields.io/badge/Models-Haiku%20%7C%20Sonnet%20%7C%20Opus-blue)]()

**One command. Zero config. Just works.**

## 🎯 Key Benefits

- **70% Cost Savings** - Automatically uses cheapest model that can handle each task
- **Zero Setup** - Works immediately, no configuration needed
- **4 Specialized Agents** - Each optimized for specific tasks
- **Smart Detection** - 100+ technical keywords recognized
- **Minimal Footprint** - Only 12 files, 30KB total
- **Project Aware** - Auto-detects your tech stack

## 🚀 Quick Start

```bash
# 1. Install (10 seconds)
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash

# 2. Check recommendation (optional)
.claude/router.sh "Create a REST API"
# Output: Architect [S] - Using Sonnet ($3/1M)

# 3. Use Claude normally
claude> Create a REST API with user authentication
```

## What Is This?

A lightweight agent system that:
- **Automatically selects the cheapest AI model** that can handle your task
- **Provides specialized context** to Claude for better results
- **Tracks costs and usage** to optimize over time
- **Works with existing projects** without breaking anything

## How It Works

### 1. Smart Model Selection
The router analyzes your request and chooses:
- **Haiku ($0.80/1M)** - For simple tasks, documentation, basic operations
- **Sonnet ($3/1M)** - For standard development, debugging, integration
- **Opus ($15/1M)** - Only for complex architecture, critical bugs, deep analysis

### 2. Agent Specialization
Four focused agents handle all tasks:
- **Architect** - Builds and designs code
- **Guardian** - Fixes, tests, and secures
- **Connector** - Deploys and integrates
- **Documenter** - Explains and documents

### 3. Usage Pattern
```bash
# OPTIONAL: Preview which agent/model would be used
.claude/router.sh "Create a REST API"
# Output: Architect [S] - Sonnet recommended ($3/1M)

# MAIN: Just use Claude CLI normally
claude> Create a REST API for user management
# Claude automatically uses the optimal agent context
```

### Special Keywords

Use these trigger words to activate special modes:

| Keyword | Effect | Indicator | Model Override |
|---------|--------|-----------|----------------|
| **ULTRATHINK** | Deep analysis mode | [ULTRATHINK] in magenta | Forces Opus ($15/1M) |
| **CRITICAL** | Maximum priority | [CRITICAL] in red | Forces Opus ($15/1M) |
| **FAST** | Speed optimized | [FAST] in green | Forces Haiku ($0.80/1M) |
| **REVIEW** | Thorough analysis | [REVIEW] in blue | Guardian + Opus |

```bash
# Examples:
.claude/router.sh "ULTRATHINK about the architecture"
.claude/router.sh "CRITICAL production bug"
.claude/router.sh "FAST prototype this feature"
.claude/router.sh "REVIEW code for security issues"
```

**Note**: The router.sh is a **planning tool** that shows you which agent/model would be optimal. The actual AI work happens in your Claude CLI session.

## The 4 Agents

| Agent | Purpose | Keywords | Model Strategy |
|-------|---------|----------|----------------|
| **Architect** | Builds & designs code | create, build, implement, design, API, component, feature | Sonnet default, Opus for complex systems |
| **Guardian** | Quality & security | test, fix, secure, optimize, bug, error, performance | Sonnet default, Opus for critical issues |
| **Connector** | Integrations & deployment | deploy, integrate, connect, AWS, Docker, CI/CD | Haiku default, Sonnet for production |
| **Documenter** | Documentation | document, explain, describe, comment, README | Always Haiku (95% cost savings) |

## Real-World Examples

### Building a Feature (Architect → Sonnet)
```bash
# Router analysis
.claude/router.sh "Create user authentication with JWT"
# → Architect [S] $0.003/1K tokens

# In Claude CLI
claude> Create user authentication with JWT
# Builds complete auth system with optimal model
```

### Fixing Production Bug (Guardian → Opus)
```bash
# Router analysis
.claude/router.sh "CRITICAL memory leak in production"
# → [CRITICAL] Guardian [O] $0.015/1K tokens

# In Claude CLI
claude> Fix the critical memory leak in production
# Uses maximum intelligence for critical issue
```

### Quick Documentation (Documenter → Haiku)
```bash
# Router analysis
.claude/router.sh "Document this API"
# → Documenter [H] $0.0008/1K tokens (95% savings!)

# In Claude CLI
claude> Document this API with examples
# Generates docs with cheapest model
```

## Project Structure

After installation, you get:
```
your-project/
└── .claude/
    ├── agents/      # The 4 AI agents with model configs
    ├── router.sh    # Smart router with complexity detection
    └── history/     # Learns patterns and tracks costs
```

**Smart Features**:
- **Automatic model selection**: Saves 70% on API costs
- **Visual feedback**: Color-coded agents with emojis
- **Cost tracking**: See exactly what each request costs
- **Complexity detection**: Uses expensive models only when needed

## For Different Projects

The system auto-detects your project type and adapts:

- **Node.js/React**: Focuses on components and APIs
- **Python/Django**: Emphasizes backend and data
- **Mobile**: Optimizes for app development
- **New Project**: Helps you start from scratch

## Installation

### Quick Install (Any Project)
```bash
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

### What Gets Installed
```
your-project/
├── .claude/
│   ├── agents/        # 4 agent definitions (2KB each)
│   │   ├── architect.md
│   │   ├── guardian.md
│   │   ├── connector.md
│   │   └── documenter.md
│   ├── router.sh      # Smart router (10KB)
│   └── history/       # Usage tracking (auto-created)
└── [your files unchanged]
```

### CLAUDE.md Integration
- **If you have CLAUDE.md**: Installer shows 3 lines to add
- **If you don't**: Creates minimal CLAUDE.md automatically
- **Minimal context**: Only 2 lines about agents

### Team Usage
```bash
# One person installs
curl -sSL ... | bash

# Commit to repo
git add .claude .gitignore
git commit -m "Add AI agent system"

# Team pulls and uses
git pull
.claude/router.sh "Check recommendation"
```

## Advanced Features

### Router Commands
```bash
.claude/router.sh status          # System status
.claude/router.sh costs           # Cost analysis
.claude/router.sh history         # Request history
.claude/router.sh "your task"    # Analyze any request
```

### Cost Tracking
```bash
$ .claude/router.sh costs
Cost Optimization Report
───────────────────────
Model usage distribution:
  Haiku:  45 requests (60%)
  Sonnet: 25 requests (33%)
  Opus:   5 requests (7%)

Estimated savings: 70% vs all-Opus usage
```

## Deployment Options

- **Local Development**: Installs in current directory
- **CI/CD**: Add to GitHub Actions, GitLab CI, Jenkins
- **Docker**: Include in Dockerfile
- **Cloud IDE**: Works in Codespaces, Replit, Gitpod
- **Enterprise**: Deploy as MCP server for central management

## Troubleshooting

**"How do I use this?"**
→ Just use Claude CLI normally. The agents provide context automatically.

**"What does router.sh do?"**
→ It's a planning tool that shows which agent/model would be optimal. Run: `.claude/router.sh "your task"`

**"Check system status"**
→ Run: `.claude/router.sh status`

**"View cost analysis"**
→ Run: `.claude/router.sh costs`

**"See request history"**
→ Run: `.claude/router.sh history`

**"Wrong agent recommended?"**
→ Be more specific in your request description

## Uninstall

```bash
rm -rf .claude
```

## Key Features

### 🎯 Smart Model Selection
- Automatically picks cheapest model that can do the job
- 70% average cost savings vs always using Opus
- Override with keywords: FAST, CRITICAL, ULTRATHINK, REVIEW

### 📊 Usage Intelligence
- Tracks which agents and models you use
- Learns your patterns over time
- Shows cost breakdowns and savings

### 🔧 Zero Configuration
- Works immediately after install
- Auto-detects project type
- No setup, no config files needed

### 🚀 Minimal Footprint
- Only 12 files total (~30KB)
- Doesn't modify your code
- Easy to remove (`rm -rf .claude`)

## Model Pricing & Selection Logic

### Automatic Selection
| Complexity | Model | Input Cost | Output Cost | When Used |
|------------|-------|------------|-------------|------------|
| Simple | Haiku | $0.80/1M | $4/1M | Docs, simple tasks, prototypes |
| Standard | Sonnet | $3/1M | $15/1M | Most development tasks |
| Complex | Opus | $15/1M | $75/1M | Critical bugs, architecture |

### Manual Override Keywords
- `FAST` → Forces Haiku (fastest, cheapest)
- `CRITICAL` → Forces Opus (maximum intelligence)
- `ULTRATHINK` → Forces Opus (deep analysis)
- `REVIEW` → Forces Guardian + Opus (thorough review)

## Requirements

- Git
- Bash 4.0+
- Claude Code or any AI CLI tool

## License

MIT - Use freely in any project.

---

## Support

- **Issues**: [GitHub Issues](https://github.com/pfangueiro/claude-code-agents/issues)
- **Discussions**: [GitHub Discussions](https://github.com/pfangueiro/claude-code-agents/discussions)
- **Updates**: Star and watch the repo for updates

## Contributing

Contributions welcome! The system is intentionally simple:
- All logic in `router.sh` (Bash)
- Agent definitions in Markdown
- No dependencies, no frameworks

---

**Built with simplicity in mind.** If it's not simple, it's not in this project.