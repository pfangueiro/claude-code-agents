# Claude Code Extensibility Guide

**The Complete Guide to Extending Claude Code with Skills, MCP, Slash Commands, and Subagents**

Version: 2.3.0
Last Updated: 2026-02-12

---

## Table of Contents

1. [Introduction](#introduction)
2. [The Four Extensibility Mechanisms](#the-four-extensibility-mechanisms)
3. [Skills](#skills)
4. [MCP Servers](#mcp-servers)
5. [Slash Commands](#slash-commands)
6. [Subagents](#subagents)
7. [Integration Patterns](#integration-patterns)
8. [Decision Matrix](#decision-matrix)
9. [Real-World Examples](#real-world-examples)
10. [Best Practices](#best-practices)

---

## Introduction

Claude Code provides four powerful mechanisms for extending its capabilities. Each mechanism serves a different purpose, and they work together to create a comprehensive extensibility system.

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude Code Platform                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Skills  │  │   MCP    │  │  Slash   │  │Subagents │   │
│  │  (Blue)  │  │ (Green)  │  │Commands  │  │ (Orange) │   │
│  │          │  │          │  │  (Red)   │  │          │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│       │             │              │              │         │
│       └─────────────┴──────────────┴──────────────┘         │
│                         │                                    │
│                   Integration Layer                          │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### When to Use Each Mechanism

| Mechanism | Purpose | Loading | Isolation |
|-----------|---------|---------|-----------|
| **Skills** | Knowledge & methodology | Automatic | Shared context |
| **MCP** | External tools & data | On-demand | Sandboxed |
| **Slash Commands** | User-triggered workflows | Manual | Shared context |
| **Subagents** | Complex isolated tasks | Agent-triggered | Complete isolation |

---

## The Four Extensibility Mechanisms

### 1. Skills (Blue) 📘

**What**: Modular knowledge packages that provide expertise, methodologies, and best practices.

**How They Work**:
- Automatically loaded based on relevance
- Progressive disclosure (metadata → SKILL.md → resources)
- Provide knowledge, Claude executes actions

**Key Characteristics**:
- 🔵 Automatic activation
- 🔵 Shared context with main conversation
- 🔵 Knowledge-focused, not execution-focused
- 🔵 Can reference other skills and agents

**Example**: `git-workflow` skill provides Git best practices; Claude applies them.

---

### 2. MCP Servers (Green) 🟢

**What**: Model Context Protocol servers that provide external tools and data sources.

**How They Work**:
- Connect to external services and APIs
- Provide tools that Claude can invoke
- Sandboxed execution for security

**Key Characteristics**:
- 🟢 External integrations
- 🟢 Tool-based invocation
- 🟢 Sandboxed execution
- 🟢 Can be used by skills and agents

**Example**: `context7` MCP server fetches library documentation; `sequential-thinking` provides deep reasoning.

---

### 3. Slash Commands (Red) 🔴

**What**: User-triggered workflows defined in `.claude/commands/`.

**How They Work**:
- User types `/command-name` to trigger
- Expands into a detailed prompt
- Executes in shared context

**Key Characteristics**:
- 🔴 Manual user activation
- 🔴 Shared context
- 🔴 Workflow orchestration
- 🔴 Can invoke skills, MCP, and agents

**Example**: `/review-pr 123` triggers a comprehensive pull request review workflow.

---

### 4. Subagents (Orange) 🟠

**What**: Specialized agents that handle complex tasks in isolated contexts.

**How They Work**:
- Triggered automatically based on keywords or by other agents
- Run in complete isolation
- Return results to parent context

**Key Characteristics**:
- 🟠 Automatic or agent-triggered activation
- 🟠 Complete context isolation
- 🟠 Task-focused execution
- 🟠 Can use skills and MCP

**Example**: `architecture-planner` agent designs systems; `security-auditor` scans for vulnerabilities.

---

## Skills

### What Are Skills?

Skills are modular knowledge packages that teach Claude how to handle specific tasks. Unlike agents (which execute in isolation), skills provide knowledge that Claude applies in the main conversation.

### Skill Anatomy

```
.claude/skills/my-skill/
├── SKILL.md              # Required: Core knowledge
├── scripts/              # Optional: Executable tools
│   ├── process.py
│   └── validate.sh
├── references/           # Optional: Deep-dive documentation
│   ├── api_reference.md
│   └── workflow_guide.md
└── assets/               # Optional: Templates, data
    ├── template.json
    └── example_data.csv
```

### Progressive Disclosure

Skills use a three-level loading strategy to optimize context:

1. **Level 1: Metadata** (always loaded)
   - Frontmatter: name, description
   - Enables skill discovery

2. **Level 2: SKILL.md** (loaded when relevant)
   - Core knowledge and methodology
   - Usage examples and patterns

3. **Level 3: Resources** (loaded on-demand)
   - scripts/, references/, assets/
   - Bundled only when needed

### Creating a Skill

Use the skill-creator skill:

```bash
# Initialize a new skill
python3 .claude/skills/skill-creator/scripts/init_skill.py my-skill .claude/skills

# Validate skill structure
python3 .claude/skills/skill-creator/scripts/quick_validate.py .claude/skills/my-skill
```

### Example: git-workflow Skill

```markdown
---
name: git-workflow
description: Git best practices, branching strategies, and commit conventions
---

# Git Workflow

## When to Use This Skill
- Creating commits with conventional commit messages
- Choosing branching strategies
- Managing pull requests
...
```

This skill provides knowledge. Claude applies it by:
- Formatting commit messages correctly
- Suggesting appropriate branching strategies
- Reviewing PRs against best practices

---

## MCP Servers

### What Are MCP Servers?

Model Context Protocol (MCP) servers provide external tools and data sources that Claude can invoke. They run as separate processes and communicate via a standardized protocol.

### How MCP Integration Works

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│ Claude Code  │ ──────> │  MCP Server  │ ──────> │ External API │
│              │ <────── │              │ <────── │  or Service  │
└──────────────┘         └──────────────┘         └──────────────┘
     Uses tools          Provides tools          Data source
```

### Configuring MCP Servers

Add to Claude Code settings:

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@context7/mcp-server"]
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

### MCP Tools

MCP servers expose tools that Claude can invoke:

```javascript
// Example: context7 MCP server provides two tools

// Tool 1: Resolve library name to ID
mcp__context7__resolve-library-id({
  libraryName: "react"
})
// Returns: "/facebook/react"

// Tool 2: Get library documentation
mcp__context7__get-library-docs({
  context7CompatibleLibraryID: "/facebook/react",
  topic: "hooks",
  tokens: 5000
})
// Returns: React hooks documentation
```

### MCP + Skills Integration

Skills can leverage MCP servers to enhance their capabilities:

**Example: library-docs Skill**

The `library-docs` skill uses the `context7` MCP server:

```markdown
---
name: library-docs
description: Quick access to library documentation using MCP
---

# Library Docs

This MCP-powered skill fetches up-to-date documentation for React, Next.js, Vue,
MongoDB, Supabase, and hundreds of other libraries.

## How It Works

1. User asks: "Show me React hooks documentation"
2. Skill activates based on keyword matching
3. Skill uses MCP tool to resolve "react" → "/facebook/react"
4. Skill fetches documentation focused on "hooks"
5. Claude presents documentation to user
```

**Why This Works**:
- 🔵 Skill provides the **knowledge** of how to use MCP tools
- 🟢 MCP server provides the **capability** to fetch external data
- Together they create a powerful documentation lookup system

### Available MCP Servers

This project includes two MCP-powered skills:

1. **library-docs** (uses `context7`)
   - Fetch library documentation
   - Support for 100+ popular libraries
   - Version-specific queries

2. **deep-analysis** (uses `sequential-thinking`)
   - Structured multi-step reasoning
   - Hypothesis generation and verification
   - Up to 31,999 thinking tokens

---

## Slash Commands

### What Are Slash Commands?

Slash commands are user-triggered workflows stored in `.claude/commands/`. They expand into detailed prompts when invoked.

### Command Structure

```
.claude/commands/
├── review-pr.md
├── deploy-prod.md
└── analyze-logs.md
```

Each command is a markdown file with frontmatter:

```markdown
---
name: review-pr
description: Comprehensive pull request review
args:
  - name: pr_number
    required: true
---

Please perform a comprehensive review of pull request #{{pr_number}}.

1. Analyze code changes
2. Check for security issues
3. Verify test coverage
4. Review documentation
...
```

### Using Slash Commands

```bash
# User types:
/review-pr 123

# Claude Code expands this to:
# "Please perform a comprehensive review of pull request #123..."
# Then executes the workflow
```

### Slash Commands + Skills

Slash commands can invoke skills:

```markdown
---
name: secure-deploy
description: Deploy with security checks
---

Using the **deployment-runbook** skill and **security-auditor** agent:

1. Run security scan (security-auditor)
2. Check deployment checklist (deployment-runbook skill)
3. Execute deployment
4. Run health checks
...
```

---

## Subagents

### What Are Subagents?

Subagents are specialized agents (defined in `.claude/agents/`) that execute complex tasks in complete isolation. They're part of the Claude Agents system.

### Agent Anatomy

```
.claude/agents/
├── architecture-planner.md
├── security-auditor.md
├── test-automation.md
└── performance-optimizer.md
```

### Auto-Activation

Agents activate automatically based on natural language:

```
User: "Design a REST API for user authentication"
→ Triggers: architecture-planner + api-backend agents
```

### Agents vs Skills

| Aspect | Skills | Agents |
|--------|--------|--------|
| **Context** | Shared | Isolated |
| **Purpose** | Provide knowledge | Execute tasks |
| **Activation** | Automatic (relevance) | Automatic (keywords) |
| **Execution** | In main conversation | Separate subprocess |
| **Result** | Knowledge applied | Deliverable returned |

### Example Agent: architecture-planner

```markdown
---
name: architecture-planner
auto_activate_on: ["design", "architecture", "system", "blueprint"]
model: sonnet
---

You are an expert software architect specializing in system design,
API specifications, and architectural patterns.

When activated, you should:
1. Understand requirements
2. Design system architecture
3. Create API contracts
4. Document decisions (ADRs)
5. Identify risks and mitigations
...
```

### Agents + Skills Integration

Agents can use skills:

```
┌─────────────────────────────────────┐
│   architecture-planner (Agent)      │
│                                     │
│   Uses:                             │
│   - deployment-runbook (Skill)      │
│   - security-auditor (Agent)        │
│                                     │
│   Result: Secure, deployable design │
└─────────────────────────────────────┘
```

---

## Integration Patterns

### Pattern 1: Skill + MCP

**Use Case**: Fetching external data with built-in knowledge

**Example**: library-docs skill + context7 MCP

```
User: "Show me Next.js routing docs"
  ↓
library-docs skill activates
  ↓
Skill uses context7 MCP to fetch docs
  ↓
Claude presents formatted documentation
```

**Why**: Skill knows HOW to use MCP, MCP provides the data.

---

### Pattern 2: Skill + Agent

**Use Case**: Providing methodology for agent execution

**Example**: deployment-runbook skill + devops-automation agent

```
User: "Deploy to production"
  ↓
devops-automation agent activates
  ↓
Agent references deployment-runbook skill
  ↓
Agent executes deployment following runbook
```

**Why**: Skill provides best practices, agent executes in isolation.

---

### Pattern 3: Slash Command + Skill + Agent

**Use Case**: User-triggered workflow with specialist execution

**Example**: /secure-deploy command

```
User types: /secure-deploy staging
  ↓
Slash command expands prompt
  ↓
Triggers security-auditor agent
  ↓
Agent uses security best practices (from skill)
  ↓
Returns security report
```

**Why**: Command orchestrates, skill guides, agent executes.

---

### Pattern 4: MCP + Agent

**Use Case**: Agent using external tools

**Example**: deep-analysis skill + architecture-planner agent

```
User: "Design a scalable microservices architecture"
  ↓
architecture-planner agent activates
  ↓
Agent invokes deep-analysis skill
  ↓
Skill uses sequential-thinking MCP for deep reasoning
  ↓
Agent creates architecture based on analysis
```

**Why**: MCP provides advanced reasoning, agent implements design.

---

### Pattern 5: Full Integration

**Use Case**: Complex workflow using all mechanisms

**Example**: Production deployment with security scan

```
User types: /deploy-production v2.1.0
  ↓
Slash command orchestrates workflow
  ↓
1. security-auditor agent (uses OWASP skill)
2. test-automation agent (uses test patterns)
3. devops-automation agent (uses deployment-runbook skill)
4. incident-commander agent (standby for issues)
  ↓
Each agent may use MCP servers for external integrations
  ↓
Results aggregated and returned
```

**Why**: Each mechanism plays its role in a comprehensive workflow.

---

## Decision Matrix

### When to Use Each Mechanism

#### Use a Skill When:
- ✅ You need to provide methodology or best practices
- ✅ Knowledge should be available across conversations
- ✅ No task isolation required
- ✅ Can be referenced by agents and commands

#### Use an MCP Server When:
- ✅ You need external data or services
- ✅ Tool invocation should be sandboxed
- ✅ Multiple skills/agents need the same capability
- ✅ You want to leverage existing MCP servers

#### Use a Slash Command When:
- ✅ Users need to manually trigger workflows
- ✅ Workflow requires specific parameters
- ✅ Multi-step orchestration needed
- ✅ User confirmation before execution

#### Use a Subagent When:
- ✅ Task requires complete isolation
- ✅ Complex multi-step execution
- ✅ Should auto-activate on keywords
- ✅ Deliverable needs to be returned

### Combination Decision Tree

```
┌─────────────────────────────────────────────┐
│ What are you trying to achieve?            │
└─────────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
    Provide                 Execute
    Knowledge               Task
        │                       │
        ▼                       ▼
    Use Skill           Need Isolation?
                              │
                    ┌─────────┴─────────┐
                    No                  Yes
                    │                   │
                    ▼                   ▼
            User triggers?          Use Agent
                  │
        ┌─────────┴─────────┐
       Yes                  No
        │                   │
        ▼                   ▼
    Use Slash          Use Skill
    Command            (auto-activates)

Need external data? → Add MCP Server
```

---

## Real-World Examples

### Example 1: Documentation System

**Goal**: Fetch and maintain documentation

**Implementation**:
1. **library-docs skill** (uses context7 MCP)
   - Fetches external library docs
2. **documentation-maintainer agent**
   - Generates project documentation
3. **Slash command**: `/document-api`
   - Triggers documentation workflow

**Flow**:
```
/document-api auth-service
  ↓
1. library-docs skill fetches auth library docs (via context7 MCP)
2. documentation-maintainer agent generates docs
3. Result: Comprehensive API documentation
```

---

### Example 2: Architecture Decision

**Goal**: Make complex architectural decisions

**Implementation**:
1. **deep-analysis skill** (uses sequential-thinking MCP)
   - Structured reasoning for decisions
2. **architecture-planner agent**
   - Designs system architecture
3. **deployment-runbook skill**
   - Provides deployment guidance

**Flow**:
```
User: "Should we use microservices or monolith?"
  ↓
1. deep-analysis skill activates (uses sequential-thinking MCP)
   - 10-step reasoning process
   - Hypothesis generation and verification
2. architecture-planner agent creates design
3. deployment-runbook skill provides deployment strategy
4. Result: Well-reasoned architecture decision
```

---

### Example 3: Security Audit

**Goal**: Comprehensive security review

**Implementation**:
1. **security-auditor agent** (Opus model for critical tasks)
   - OWASP compliance scanning
2. **code-review-checklist skill**
   - Security review methodology
3. **Slash command**: `/security-scan`
   - Triggers audit workflow

**Flow**:
```
/security-scan src/
  ↓
1. security-auditor agent activates
2. Agent uses code-review-checklist skill for methodology
3. Agent scans for OWASP Top 10 vulnerabilities
4. Result: Security report with remediation steps
```

---

### Example 4: Performance Optimization

**Goal**: Diagnose and fix performance issues

**Implementation**:
1. **deep-analysis skill** (uses sequential-thinking MCP)
   - Root cause analysis
2. **performance-optimizer agent**
   - Implements optimizations
3. **database-architect agent**
   - Query optimization

**Flow**:
```
User: "API response time went from 200ms to 2s"
  ↓
1. deep-analysis skill activates
   - Multi-step hypothesis testing
   - Found: O(n²) algorithm in new feature
2. performance-optimizer agent implements fix
3. database-architect agent optimizes queries
4. Result: Performance restored
```

---

## Best Practices

### Skill Best Practices

1. **Progressive Disclosure**
   - Keep SKILL.md focused and concise
   - Move detailed docs to references/
   - Bundle assets only when needed

2. **Clear Scope**
   - One skill = one domain
   - Avoid overlap with other skills
   - Reference related skills

3. **Examples Over Theory**
   - Provide concrete usage examples
   - Show real-world scenarios
   - Include code snippets

4. **Integration-Aware**
   - Document agent integration points
   - Show MCP server usage
   - Link to related skills

### MCP Best Practices

1. **Tool Design**
   - Clear, descriptive tool names
   - Comprehensive parameter documentation
   - Error handling and validation

2. **Security**
   - Sandbox external calls
   - Validate all inputs
   - Rate limiting for APIs

3. **Performance**
   - Cache results when appropriate
   - Minimize external calls
   - Use token limits wisely

4. **Documentation**
   - Document all available tools
   - Provide usage examples
   - Show integration patterns

### Slash Command Best Practices

1. **User Experience**
   - Clear, descriptive names
   - Required vs optional args
   - Helpful descriptions

2. **Workflow Design**
   - Break into logical steps
   - Show progress to user
   - Handle errors gracefully

3. **Integration**
   - Leverage skills for methodology
   - Use agents for execution
   - Invoke MCP for external data

### Agent Best Practices

1. **Specialization**
   - Clear domain boundaries
   - Focused activation keywords
   - Specific deliverables

2. **Model Selection**
   - Haiku: Documentation (95% savings)
   - Sonnet: Standard development
   - Opus: Security & emergencies

3. **Context Management**
   - Return concise results
   - Summarize complex analysis
   - Link to detailed artifacts

4. **Collaboration**
   - Reference relevant skills
   - Invoke other agents when needed
   - Follow established patterns

---

## Validation and Testing

### Validating Skills

```bash
# Validate skill structure
python3 .claude/skills/skill-creator/scripts/quick_validate.py \
    .claude/skills/my-skill

# Expected output: "Skill is valid!"
```

### Testing MCP Servers

```bash
# Check if MCP server is configured
claude-code mcp list

# Test MCP tool invocation
# (done within Claude Code conversation)
```

### Testing Slash Commands

```bash
# Test command expansion
/my-command arg1 arg2

# Verify prompt expansion is correct
```

### Testing Agents

```bash
# Test agent activation
# Use activation keywords in conversation

# Example:
# "Check security of authentication flow"
# → Should trigger security-auditor agent
```

---

## Migration Guide

### From Monolithic to Extensible

If you have existing documentation or workflows:

1. **Identify Knowledge vs Execution**
   - Knowledge → Skills
   - Execution → Agents

2. **Extract Methodologies**
   - Create skills for best practices
   - Keep them focused and reusable

3. **Define Workflows**
   - Complex workflows → Agents
   - User-triggered → Slash commands

4. **Add External Integrations**
   - External APIs → MCP servers
   - Connect to existing skills

### Example Migration

**Before**: Monolithic deployment script

**After**:
- **deployment-runbook skill**: Deployment methodology
- **devops-automation agent**: Executes deployments
- **/deploy-production command**: User-triggered workflow
- **Health check script**: Bundled in skill

---

## Appendix: Project Structure

```
claude-code-agents/
├── .claude/
│   ├── skills/                    # Skills (Blue)
│   │   ├── skill-creator/
│   │   ├── git-workflow/
│   │   ├── code-review-checklist/
│   │   ├── deployment-runbook/
│   │   ├── library-docs/          # MCP-powered
│   │   └── deep-analysis/         # MCP-powered
│   │
│   ├── agents/                    # Agents (Orange)
│   │   ├── architecture-planner.md
│   │   ├── security-auditor.md
│   │   ├── test-automation.md
│   │   ├── performance-optimizer.md
│   │   ├── devops-automation.md
│   │   ├── documentation-maintainer.md
│   │   ├── database-architect.md
│   │   ├── frontend-specialist.md
│   │   ├── api-backend.md
│   │   ├── incident-commander.md
│   │   └── code-quality.md
│   │
│   ├── commands/                  # Slash Commands (Red)
│   │   └── (user-defined commands)
│   │
│   └── lib/                       # Shared infrastructure
│       ├── agent-templates.json
│       ├── sdlc-patterns.md
│       └── activation-keywords.json
│
├── EXTENSIBILITY.md               # This guide
├── CLAUDE.md                      # Claude Code instructions
├── README.md                      # Project overview
├── SKILLS-QUICKSTART.md           # Skills quick start
└── CHANGELOG.md                   # Version history
```

---

## Additional Resources

### Documentation
- [Skills Quickstart](./SKILLS-QUICKSTART.md)
- [Claude Code Documentation](https://docs.claude.com/claude-code)
- [MCP Documentation](https://modelcontextprotocol.io)

### Skills in This Project
- `skill-creator`: Create new skills from templates
- `git-workflow`: Git best practices and conventions
- `code-review-checklist`: Systematic code review framework
- `deployment-runbook`: Deployment strategies and automation
- `library-docs`: MCP-powered library documentation (context7)
- `deep-analysis`: MCP-powered deep reasoning (sequential-thinking)

### Agents in This Project
- `architecture-planner`: System design and API specifications
- `security-auditor`: Security scanning and OWASP compliance
- `test-automation`: Test generation and coverage analysis
- `performance-optimizer`: Performance analysis and optimization
- `devops-automation`: CI/CD, containerization, deployments
- `documentation-maintainer`: Documentation generation
- `database-architect`: Database design and optimization
- `frontend-specialist`: Frontend development and UI/UX
- `api-backend`: Backend API development
- `incident-commander`: Emergency response and triage
- `code-quality`: Code review and quality assessment
- `meta-agent`: Generates new specialized agents

---

## Conclusion

Claude Code's extensibility system provides four complementary mechanisms:

1. **Skills** (Blue): Knowledge and methodology
2. **MCP** (Green): External tools and data
3. **Slash Commands** (Red): User-triggered workflows
4. **Subagents** (Orange): Isolated task execution

By understanding when and how to use each mechanism, you can create powerful, maintainable extensions that enhance Claude Code's capabilities while following best practices.

**Key Takeaways**:
- Use skills for knowledge, agents for execution
- Leverage MCP servers for external integrations
- Combine mechanisms for complex workflows
- Follow progressive disclosure principles
- Validate and test all extensions

---

**Version**: 2.3.0 - Quality & Coordination Release
**License**: MIT
**Maintainer**: Claude Agents Project
