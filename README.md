# Claude Agents - AI Coding Assistant

**One command. Zero config. Just works.**

## Install (10 seconds)

```bash
# For any project
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

That's it. Start coding with AI.

## How It Works

Just describe what you want in natural language:

```bash
claude> "Create a REST API for user management"
# ✅ Architect designs it, Guardian secures it, Connector integrates it

claude> "This function is slow, make it faster"
# ✅ Guardian analyzes it, optimizes it, and tests it

claude> "Add authentication to my app"
# ✅ Architect designs auth flow, Guardian implements security

claude> "Deploy this to production"
# ✅ Connector handles deployment, Guardian validates it
```

## The 4 Agents

Each agent has one clear job:

| Agent | Purpose | Activates When You Say |
|-------|---------|------------------------|
| **Architect** | Designs and builds code | "create", "build", "implement", "design" |
| **Guardian** | Quality, security, and performance | "test", "fix", "secure", "optimize" |
| **Connector** | External services and deployment | "deploy", "integrate", "connect" |
| **Documenter** | Documentation and explanations | "explain", "document", "describe" |

## Quick Examples

### 1. Build Something New
```bash
"Create a user authentication system with JWT"
```
**What happens**: Architect designs → Guardian secures → Connector integrates

### 2. Fix a Problem
```bash
"Fix the memory leak in this function"
```
**What happens**: Guardian analyzes → fixes → tests

### 3. Improve Performance
```bash
"Make this database query 10x faster"
```
**What happens**: Guardian profiles → optimizes → validates

### 4. Add Features
```bash
"Add real-time notifications to my app"
```
**What happens**: Architect designs → Connector integrates WebSocket → Guardian tests

### 5. Deploy
```bash
"Deploy this to AWS with auto-scaling"
```
**What happens**: Connector configures → Guardian validates → deploys

## Project Structure

After installation, you get:
```
your-project/
└── .claude/
    ├── agents/      # The 4 AI agents
    ├── router.sh    # Understands what you want
    └── history/     # Learns from your patterns
```

That's all. No complex configuration.

## For Different Projects

The system auto-detects your project type and adapts:

- **Node.js/React**: Focuses on components and APIs
- **Python/Django**: Emphasizes backend and data
- **Mobile**: Optimizes for app development
- **New Project**: Helps you start from scratch

## Installation Options

### New Project
```bash
mkdir my-app && cd my-app
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

### Existing Project
```bash
cd your-project
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

### Team Setup
```bash
# Install once
./install.sh

# Commit to git
git add .claude
git commit -m "Add AI agents"

# Team members just pull
git pull
```

### CI/CD Integration
```yaml
# .github/workflows/ai-assist.yml
- name: AI Code Review
  run: |
    .claude/router.sh "Review this PR for security issues"
```

## Advanced Usage

### Custom Workflows
Create `.claude.yml` (optional):
```yaml
workflows:
  review: [Guardian]
  release: [Guardian, Connector]
```

### Learning System
The system learns your patterns:
- Remembers successful workflows
- Adapts to your coding style
- Improves suggestions over time

## Deployment

### Personal Projects
Just copy the `.claude` folder.

### Team Projects
Add `.claude` to your repository.

### Enterprise
Deploy as MCP server for centralized management.

### Cloud IDE
Works in GitHub Codespaces, Replit, etc.

## Troubleshooting

**"Agents not responding"**
→ Run: `.claude/router.sh status`

**"Wrong agent activated"**
→ Be more specific: "Create REST API" vs "Create GraphQL API"

**"Need different behavior"**
→ Create `.claude.yml` with custom workflows

## Uninstall

```bash
rm -rf .claude
```

## Why Only 4 Agents?

- **Architect**: Handles ALL design and creation
- **Guardian**: Handles ALL quality and security
- **Connector**: Handles ALL integrations
- **Documenter**: Handles ALL documentation

Each agent is powerful and focused. No overlap, no confusion.

## Requirements

- Git
- Bash 4.0+
- Claude Code or any AI CLI tool

## License

MIT - Use freely in any project.

---

**Problems?** Open an issue on [GitHub](https://github.com/pfangueiro/claude-code-agents)

**Love it?** Star the repo!