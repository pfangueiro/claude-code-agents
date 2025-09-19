# Claude Agents - AI Coding Assistant

**One command. Zero config. Just works.**

## Install (10 seconds)

```bash
# For any project
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh | bash
```

That's it. Start coding with AI.

## How It Works

The agents provide **guidance and context** for your AI coding sessions. The router helps you understand which agent and model would be best for your task:

### Step 1: Analyze Your Request (Optional)
```bash
# See which agent and model would be used
.claude/router.sh "Create a REST API"
# Output: 🏗️ Architect [S] - Sonnet recommended
```

### Step 2: Use with Claude CLI
```bash
# In your Claude CLI or AI tool, just work naturally:
claude> Create a REST API for user management
# Claude will build it using the Architect agent context

claude> Fix the security issues in this code
# Claude will analyze using Guardian agent patterns

claude> Document this function
# Claude will write docs efficiently
```

**Note**: The router.sh is a **planning tool** that shows you which agent/model would be optimal. The actual AI work happens in your Claude CLI session.

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
# Check which agent would be used (optional)
.claude/router.sh "Create a user authentication system with JWT"
# Output: 🏗️ Architect [S] - Sonnet recommended

# Then in Claude CLI:
claude> Create a user authentication system with JWT
```

### 2. Fix a Problem
```bash
# Check recommendation (optional)
.claude/router.sh "Fix the memory leak in this function"
# Output: 🛡️ Guardian [S] - Sonnet recommended

# Then in Claude CLI:
claude> Fix the memory leak in this function
```

### 3. Improve Performance
```bash
# Check recommendation (optional)
.claude/router.sh "Make this database query 10x faster"
# Output: 🛡️ Guardian [O] - Opus recommended for complex optimization

# Then in Claude CLI:
claude> Make this database query 10x faster
```

### 4. Deploy
```bash
# Check recommendation (optional)
.claude/router.sh "Deploy this to AWS with auto-scaling"
# Output: 🔌 Connector [S] - Sonnet recommended

# Then in Claude CLI:
claude> Deploy this to AWS with auto-scaling
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

### What You Get
After installation:
1. **Agent context files** in `.claude/agents/` - Provide specialized knowledge
2. **Router tool** at `.claude/router.sh` - Shows optimal agent/model selection
3. **History tracking** in `.claude/history/` - Learns from your usage patterns

### Using the System
```bash
# OPTIONAL: Check which agent/model is recommended
.claude/router.sh "your request here"

# MAIN USAGE: Just use Claude CLI normally
claude> your actual request here
```

### CI/CD Integration
```yaml
# .github/workflows/ai-assist.yml
- name: Check AI Recommendation
  run: |
    # This just shows which agent/model would be used
    .claude/router.sh "Review this PR for security issues"
    # Output: Would use Guardian [O] for security review

    # Actual AI review would need Claude CLI integration
```

## Advanced Usage

### Understanding the System

**What the router does:**
- Analyzes your request intent
- Detects task complexity
- Recommends optimal agent and model
- Tracks usage history for learning
- Shows cost estimates

**What YOU do:**
- Use Claude CLI as normal
- Optionally check router recommendations first
- The agent contexts guide Claude's responses automatically

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