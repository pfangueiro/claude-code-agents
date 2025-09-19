# Claude Agents - AI Coding Assistant

**One command. Zero config. Just works.**

## Install (10 seconds)

```bash
# For any project
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

That's it. Start coding with AI.

## How It Works

Just describe what you want in natural language. The system automatically:
1. **Detects intent** from your request
2. **Analyzes complexity** of the task
3. **Selects optimal model** (Haiku/Sonnet/Opus)
4. **Shows visual feedback** with colors and costs
5. **Activates the right agent** with the best model

```bash
claude> "Create a REST API for user management"
# 🏗️ Architect [S] - Uses Sonnet ($3/1M) for standard complexity
# ✅ Agent activated with optimal model for building

claude> "Fix critical security vulnerability in production"
# 🛡️ Guardian [O] - Uses Opus ($15/1M) for critical issues
# ✅ Agent activated with maximum intelligence

claude> "Document this function"
# 📝 Documenter [H] - Uses Haiku ($0.80/1M) to save 95% on costs
# ✅ Agent activated with cost-optimized model
```

## The 4 Agents with Smart Model Selection

Each agent has one clear job and intelligently selects the best AI model:

| Agent | Purpose | Activates When You Say | Model Selection |
|-------|---------|------------------------|------------------|
| **🏗️ Architect** | Designs and builds code | "create", "build", "implement", "design" | Sonnet ($3/1M) or Opus ($15/1M) for complex |
| **🛡️ Guardian** | Quality, security, and performance | "test", "fix", "secure", "optimize" | Sonnet ($3/1M) or Opus ($15/1M) for critical |
| **🔌 Connector** | External services and deployment | "deploy", "integrate", "connect" | Haiku ($0.80/1M) or Sonnet ($3/1M) for production |
| **📝 Documenter** | Documentation and explanations | "explain", "document", "describe" | Always Haiku ($0.80/1M) - 95% savings |

## Quick Examples

### 1. Build Something New
```bash
"Create a user authentication system with JWT"
```
**Selected**: 🏗️ Architect [S] - Uses Sonnet for standard complexity design

### 2. Fix a Problem
```bash
"Fix the memory leak in this function"
```
**Selected**: 🛡️ Guardian [S] - Uses Sonnet for debugging and fixing

### 3. Improve Performance
```bash
"Make this database query 10x faster"
```
**Selected**: 🛡️ Guardian [O] - Uses Opus for complex optimization

### 4. Add Features
```bash
"Add real-time notifications to my app"
```
**Selected**: 🏗️ Architect [S/O] - Model based on complexity

### 5. Deploy
```bash
"Deploy this to AWS with auto-scaling"
```
**Selected**: 🔌 Connector [S] - Uses Sonnet for production deployment

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

**"Want to check costs"**
→ Run: `.claude/router.sh costs`

**"See request history"**
→ Run: `.claude/router.sh history`

## Uninstall

```bash
rm -rf .claude
```

## Why Only 4 Agents?

- **🏗️ Architect**: Handles ALL design and creation (uses Sonnet/Opus)
- **🛡️ Guardian**: Handles ALL quality and security (uses Sonnet/Opus)
- **🔌 Connector**: Handles ALL integrations (uses Haiku/Sonnet)
- **📝 Documenter**: Handles ALL documentation (always Haiku for savings)

Each agent is powerful, focused, and cost-optimized. No overlap, no confusion, no waste.

## Cost Optimization

The system intelligently selects models based on task complexity:
- **Simple tasks**: Haiku at $0.80/1M tokens (80% cheaper)
- **Standard tasks**: Sonnet at $3/1M tokens (balanced)
- **Complex/Critical**: Opus at $15/1M tokens (maximum intelligence)

**Result**: 70% average cost savings vs always using Opus

## Requirements

- Git
- Bash 4.0+
- Claude Code or any AI CLI tool

## License

MIT - Use freely in any project.

---

**Problems?** Open an issue on [GitHub](https://github.com/pfangueiro/claude-code-agents)

**Love it?** Star the repo!