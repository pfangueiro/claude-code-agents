# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is **Claude Agents** - an enterprise-grade AI agent system with 11 specialized SDLC/SSDLC agents that **auto-activate based on natural language**. The system automatically selects the optimal Claude model (Haiku/Sonnet/Opus) based on task complexity, achieving ~70% cost savings while ensuring comprehensive coverage of all software development phases.

## 🚨 IMPORTANT: AUTO-ACTIVATION SYSTEM

**Agents will automatically activate when you use natural language.** You don't need to explicitly call them - just describe what you want to do, and the appropriate specialist will engage.

## 🤖 Available Auto-Activating Agents

### 1. **architecture-planner** (Purple) 🏗️
- **Auto-activates on:** design, architecture, system, blueprint, API contract, interface, planning
- **Examples:** "Design the system", "Create architecture", "Plan the implementation"
- **Specializes in:** System design, API specifications, architectural patterns, ADRs
- **Model:** Sonnet

### 2. **code-quality** (Purple) 🔍
- **Auto-activates on:** review, quality, refactor, clean code, lint, best practices, code smell
- **Examples:** "Review the code", "Check quality", "Improve code"
- **Specializes in:** Code review, refactoring suggestions, quality metrics
- **Model:** Sonnet

### 3. **security-auditor** (Red) 🔒 **[CRITICAL]**
- **Auto-activates on:** security, vulnerability, auth, XSS, CSRF, injection, OWASP
- **Examples:** "Check security", "Scan for vulnerabilities", "Implement auth"
- **Specializes in:** SAST/DAST scanning, OWASP compliance, security fixes
- **Model:** ALWAYS Opus (security is critical)

### 4. **test-automation** (Green) ✅
- **Auto-activates on:** test, unit test, integration, e2e, coverage, TDD, mock
- **Examples:** "Write tests", "Test this", "Ensure coverage"
- **Specializes in:** Test generation, coverage analysis, TDD/BDD practices
- **Model:** Sonnet

### 5. **performance-optimizer** (Orange) ⚡
- **Auto-activates on:** slow, performance, optimize, speed, bottleneck, profile
- **Examples:** "Improve performance", "Running slow", "Optimize this"
- **Specializes in:** Profiling, bottleneck analysis, caching strategies
- **Model:** Sonnet

### 6. **devops-automation** (Orange) 🚀
- **Auto-activates on:** deploy, CI, CD, pipeline, Docker, Kubernetes, AWS, production
- **Examples:** "Deploy to production", "Set up pipeline", "Dockerize application"
- **Specializes in:** CI/CD, containerization, IaC, cloud deployments
- **Model:** Sonnet

### 7. **documentation-maintainer** (Cyan) 📚
- **Auto-activates on:** document, README, API doc, guide, tutorial, manual
- **Examples:** "Write documentation", "Document this", "Create readme"
- **Specializes in:** Documentation generation, API specs, user guides
- **Model:** Haiku (95% cost savings)

### 8. **database-architect** (Orange) 🗄️
- **Auto-activates on:** database, SQL, schema, migration, query, index, PostgreSQL, MongoDB
- **Examples:** "Design database", "Optimize query", "Create migration"
- **Specializes in:** Schema design, query optimization, migrations
- **Model:** Sonnet

### 9. **frontend-specialist** (Pink) 🎨
- **Auto-activates on:** frontend, UI, UX, React, Vue, Angular, component, CSS, responsive
- **Examples:** "Create UI", "Build frontend", "Style component"
- **Specializes in:** Component development, responsive design, accessibility
- **Model:** Sonnet

### 10. **api-backend** (Purple) 🔧
- **Auto-activates on:** backend, API, endpoint, service, REST, GraphQL, microservice
- **Examples:** "Create API", "Implement backend", "Add endpoint"
- **Specializes in:** RESTful/GraphQL APIs, auth, validation, business logic
- **Model:** Sonnet

### 11. **incident-commander** (Red) 🚨 **[EMERGENCY]**
- **Auto-activates on:** CRITICAL, EMERGENCY, INCIDENT, OUTAGE, production down, crash
- **Examples:** "Production is down", "Critical issue", "Emergency fix"
- **Specializes in:** Rapid triage, root cause analysis, emergency fixes
- **Model:** ALWAYS Opus (critical situations)

## 🔄 Agent Collaboration Patterns

Agents work together in workflows. See `.claude/lib/agent-coordination.md` for the formal coordination protocol.

### Full Stack Development Flow
1. **architecture-planner** → Designs system
2. **frontend-specialist** + **api-backend** → Implement in parallel
3. **database-architect** → Optimizes data layer
4. **test-automation** → Generates tests
5. **code-quality** → Reviews implementation
6. **security-auditor** → Security scan
7. **devops-automation** → Deploys to production

### Emergency Response Flow
1. **incident-commander** → Takes charge immediately
2. **security-auditor** → If security breach
3. **performance-optimizer** → If performance issue
4. **devops-automation** → For rollback/deployment

## 📊 Model Optimization Strategy

- **Haiku ($0.80/1M):** Documentation only (95% savings)
- **Sonnet ($3/1M):** Standard development tasks (balanced)
- **Opus ($15/1M):** Security & critical incidents (maximum intelligence)

## 🎯 Natural Language Examples

Just describe what you need:

- "Help me design a REST API for user authentication" → **architecture-planner** + **api-backend** activate
- "This query is running slow" → **performance-optimizer** + **database-architect** activate
- "Add tests for the payment module" → **test-automation** activates
- "Production is down!" → **incident-commander** activates immediately with Opus
- "Document how this API works" → **documentation-maintainer** activates with Haiku
- "Review my React component for best practices" → **code-quality** + **frontend-specialist** activate
- "Check for security vulnerabilities" → **security-auditor** activates with Opus
- "Deploy this to AWS" → **devops-automation** activates

## 🛠️ Advanced Agent System

### Meta-Agent
The **meta-agent** can generate new specialized agents when needed:
- Use when you need a custom agent for a specific domain
- Automatically creates agents with natural language activation
- Follows SDLC/SSDLC best practices

### Supporting Infrastructure
- **`.claude/lib/agent-templates.json`**: Pre-built agent templates
- **`.claude/lib/sdlc-patterns.md`**: SDLC phase detection patterns
- **`.claude/lib/activation-keywords.json`**: Natural language activation database

## 🎓 Skills System

Skills extend the agent system by providing modular knowledge packages. While **agents execute tasks**, **skills provide specialized knowledge, tools, and resources**.

### Agents vs Skills

| **Agents** | **Skills** |
|------------|------------|
| Auto-activating task executors | Modular knowledge packages |
| Execute SDLC/SSDLC workflows | Provide domain expertise & tools |
| Examples: security-auditor, test-automation | Examples: git-workflow, brand-guidelines |

### When to Create Skills

Create a skill when you need to:

1. **Bundle domain-specific knowledge** - Company APIs, schemas, business logic
2. **Provide reusable tools** - Scripts that get rewritten repeatedly
3. **Package resources** - Templates, boilerplate, documentation
4. **Define specialized workflows** - Multi-step procedures for specific domains

### Creating Skills

Use the **skill-creator** to build new skills:

```bash
# Create a new skill
python3 .claude/skills/skill-creator/scripts/init_skill.py my-skill --path .claude/skills

# Validate the skill
python3 .claude/skills/skill-creator/scripts/quick_validate.py .claude/skills/my-skill

# Package for distribution
python3 .claude/skills/skill-creator/scripts/package_skill.py .claude/skills/my-skill
```

### Skill Structure

Every skill consists of:

```
my-skill/
├── SKILL.md          # Required: skill definition & instructions
└── Optional resources:
    ├── scripts/      # Executable code (Python/Bash/etc.)
    ├── references/   # Documentation loaded into context
    └── assets/       # Files used in output (templates, images)
```

### Agent-Skill Integration

Skills complement agents for powerful workflows:

- **architecture-planner** + **api-spec** skill → Design with your standards
- **code-quality** + **code-review-checklist** skill → Review with your criteria
- **devops-automation** + **deployment-runbook** skill → Deploy with your procedures
- **documentation-maintainer** + **brand-guidelines** skill → Document with your style

### Example Skills

The system includes demonstration skills:

- **skill-creator**: Create and package new skills
- **git-workflow**: Git best practices and workflows (coming soon)
- **code-review-checklist**: Systematic code review guidelines (coming soon)
- **deployment-runbook**: Deployment procedures and scripts (coming soon)

See `.claude/skills/README.md` for complete documentation on creating and using skills.

## 🌐 MCP (Model Context Protocol) Integration

**MCP servers** provide external tools and data sources that extend Claude Code's capabilities. They work seamlessly with both skills and agents, enabling powerful integrations with external services.

### What is MCP?

MCP (Model Context Protocol) is a standardized protocol that allows Claude Code to connect to external services, APIs, and tools. MCP servers run as separate processes and expose tools that Claude can invoke.

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│ Claude Code  │ ──────> │  MCP Server  │ ──────> │ External API │
│              │ <────── │              │ <────── │  or Service  │
└──────────────┘         └──────────────┘         └──────────────┘
     Uses tools          Provides tools          Data source
```

### MCP-Powered Skills

This project includes two MCP-powered skills that demonstrate the integration:

#### 1. **library-docs** (uses context7 MCP server)
- **What**: Fetches up-to-date documentation for 100+ libraries
- **How**: Uses context7 MCP server to fetch official docs
- **Examples**: React, Next.js, Vue, MongoDB, Supabase, PostgreSQL
- **Usage**: "Show me React hooks documentation"

```javascript
// Example MCP tool invocation
mcp__context7__resolve-library-id({ libraryName: "react" })
// Returns: "/facebook/react"

mcp__context7__get-library-docs({
  context7CompatibleLibraryID: "/facebook/react",
  topic: "hooks",
  tokens: 5000
})
// Returns: React hooks documentation
```

#### 2. **deep-analysis** (uses sequential-thinking MCP server)
- **What**: Structured multi-step reasoning for complex problems
- **How**: Uses sequential-thinking MCP server for deep analysis
- **Capabilities**: Up to 31,999 thinking tokens (vs 4,000 standard)
- **Usage**: "Should we use microservices or monolith?"

```javascript
// Example MCP tool invocation
mcp__sequential-thinking-server__sequentialthinking({
  thought: "Let me analyze the architectural trade-offs...",
  thoughtNumber: 1,
  totalThoughts: 10,
  nextThoughtNeeded: true
})
// Enables hypothesis generation, verification, and course correction
```

### MCP + Agent Integration

MCP servers work with agents to enhance their capabilities:

- **architecture-planner** + **deep-analysis** skill (sequential-thinking MCP) → Structured architectural decisions
- **documentation-maintainer** + **library-docs** skill (context7 MCP) → Documentation using library patterns
- **performance-optimizer** + **deep-analysis** skill (sequential-thinking MCP) → Root cause analysis

### Configuring MCP Servers

Add MCP servers to your Claude Code settings:

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

### When to Use MCP

Use MCP servers when you need:
- ✅ External data or API integrations
- ✅ Sandboxed tool execution
- ✅ Reusable capabilities across skills and agents
- ✅ Up-to-date information from external sources

### MCP Resources

For comprehensive documentation on MCP integration, Skills, Slash Commands, and Subagents, see:
- **[EXTENSIBILITY.md](./EXTENSIBILITY.md)** - Complete extensibility guide
- **[MCP Documentation](https://modelcontextprotocol.io)** - Official MCP protocol docs

## 🔒 Security-First Approach

**CRITICAL:** The following agents ALWAYS use Opus model for maximum security:
- **security-auditor**: All security scanning and vulnerability detection
- **incident-commander**: Production emergencies and critical incidents

Security considerations are embedded in EVERY agent following OWASP guidelines and DevSecOps best practices.

## 💡 Best Practices

1. **Let agents auto-activate** - Just describe your task naturally
2. **Trust agent specialization** - Each agent is an expert in its domain
3. **Security scanning is automatic** - Security-auditor activates on any auth/security mention
4. **Tests are expected** - Test-automation will proactively suggest test coverage
5. **Documentation is cheap** - Documentation-maintainer uses Haiku to save 95% on costs
6. **Incidents get priority** - Incident-commander overrides everything in emergencies

## 🎮 Quick Start

Simply start describing what you want to do, and the appropriate agents will automatically activate:

```
"I need to build a user registration system with email verification"
```

This will trigger:
1. **architecture-planner** - Designs the system
2. **api-backend** - Implements the backend logic
3. **database-architect** - Creates the schema
4. **security-auditor** - Ensures secure implementation
5. **test-automation** - Generates tests
6. **documentation-maintainer** - Documents the API

## 📈 Planned: Continuous Improvement

The following observability features are planned for a future release:
- Activation accuracy tracking
- Task completion metrics
- Model selection optimization
- Activation pattern refinement

---

**Remember:** You don't need to manually invoke agents - they activate automatically based on your natural language. Just describe what you want to accomplish, and the right experts will engage to help you succeed!