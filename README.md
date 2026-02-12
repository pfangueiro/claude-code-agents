# Claude Agents - AI-Powered SDLC Agent System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-2.3.0-blue.svg)](https://github.com/pfangueiro/claude-code-agents/releases)
[![Claude Code](https://img.shields.io/badge/Claude_Code-Compatible-purple.svg)](https://docs.anthropic.com/en/docs/claude-code)
[![Agents](https://img.shields.io/badge/Agents-12-orange.svg)](#-available-agents)
[![Skills](https://img.shields.io/badge/Skills-11-green.svg)](#-skills-system)
[![MCP](https://img.shields.io/badge/MCP-5%20Servers-brightgreen.svg)](#-mcp-integration)

**12 auto-activating AI agents for every phase of software development.** Just describe what you want to build — the right specialists engage automatically.

> Works with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (Anthropic's CLI). No plugins, no configuration, no commands to memorize.

---

## 30-Second Setup

```bash
git clone https://github.com/pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh --team-setup
```

Then open any project with Claude Code and talk naturally:

```
"Build a REST API with JWT authentication"
"This query is running slow"
"Check for security vulnerabilities"
"Deploy to production"
```

Agents activate automatically based on your words.

---

## What You Get

| Component | Count | What It Does |
|-----------|-------|--------------|
| **Agents** | 12 | Auto-activating SDLC specialists (planning through production) |
| **Skills** | 11 | Modular knowledge packages (git, Docker, CI/CD, API design, etc.) |
| **Slash Commands** | 5 | `/commit-pr`, `/review-pr`, `/security-scan`, `/new-feature`, `/create-jira` |
| **MCP Servers** | 5 | context7, sequential-thinking, playwright, github, postgres |
| **Rules** | 2 | Auto-enforced security and code quality standards |
| **Hooks** | 3 | Desktop notifications, auto-lint, pre-commit validation |
| **Keybindings** | 6 | Ctrl+S (commit), Ctrl+T (PR), Ctrl+R (review), etc. |

---

## Available Agents

| Agent | Activates On | Does What | Model |
|-------|-------------|-----------|-------|
| **architecture-planner** | "design", "architecture", "system" | System design, API specs, ADRs | Sonnet |
| **code-quality** | "review", "refactor", "quality" | Code review, best practices | Sonnet |
| **security-auditor** | "security", "auth", "vulnerability" | OWASP scanning, security fixes | **Opus** |
| **test-automation** | "test", "coverage", "TDD" | Test generation, coverage analysis | Sonnet |
| **performance-optimizer** | "slow", "optimize", "bottleneck" | Profiling, caching, optimization | Sonnet |
| **devops-automation** | "deploy", "CI/CD", "Docker" | Deployment, containerization | Sonnet |
| **documentation-maintainer** | "document", "README", "guide" | Docs, API specs | **Haiku** |
| **database-architect** | "database", "SQL", "schema" | Query optimization, migrations | Sonnet |
| **frontend-specialist** | "UI", "React", "frontend" | Components, responsive design | Sonnet |
| **api-backend** | "API", "backend", "endpoint" | REST/GraphQL, business logic | Sonnet |
| **incident-commander** | "CRITICAL", "outage", "emergency" | Rapid response, root cause | **Opus** |
| **meta-agent** | "create an agent for..." | Generates new custom agents | Opus |

**Cost optimization:** Haiku for docs (95% cheaper), Sonnet for dev work, Opus for security/emergencies.

---

## How Agents Collaborate

Agents hand off work automatically. Example: *"Build a user registration system"*

```mermaid
graph LR
    A[architecture-planner] --> B[frontend-specialist]
    A --> C[api-backend]
    C --> D[database-architect]
    B --> E[test-automation]
    C --> E
    E --> F[code-quality]
    F --> G[security-auditor]
    G --> H[devops-automation]
```

See [`.claude/lib/agent-coordination.md`](.claude/lib/agent-coordination.md) for the formal handoff protocol.

---

## Installation Options

| Mode | Command | What It Does |
|------|---------|-------------|
| **Team Setup** | `./install.sh --team-setup` | Everything: agents, skills, commands, hooks, keybindings, MCP, global config |
| **Full** | `./install.sh --full` | Agents + skills + commands for one project (no global config) |
| **Minimal** | `./install.sh --minimal` | Just CLAUDE.md with agent activation |
| **Repair** | `./install.sh --repair` | Fix missing components |
| **Update** | `./install.sh --update` | Update to latest version |
| **Validate** | `./validate.sh` | Verify all 79 checks pass |

### Deploy to an Existing Project

```bash
cd /path/to/your/project
/path/to/claude-code-agents/install.sh --full
```

### Verify Installation

```bash
./validate.sh
# All validations passed! (79/79 checks)
```

---

## Slash Commands

| Command | Usage | What It Does |
|---------|-------|-------------|
| `/commit-pr` | `/commit-pr [message]` | Stage, commit, push, create PR, update JIRA |
| `/review-pr` | `/review-pr 123` | Code quality + security + testing review |
| `/security-scan` | `/security-scan [path]` | OWASP scanning, secrets detection, dependency audit |
| `/new-feature` | `/new-feature PROJ-123 desc` | Create feature branch from latest main |
| `/create-jira` | `/create-jira epic Title` | Create JIRA issue and assign to you |

---

## Skills System

Skills provide domain knowledge that agents apply. 11 included:

| Skill | What It Provides |
|-------|-----------------|
| **git-workflow** | Branching strategies, conventional commits, PR workflows |
| **code-review-checklist** | 10-category review framework, security checklist |
| **deployment-runbook** | Blue-green deployment, rollback procedures, health checks |
| **api-guidelines** | REST/GraphQL patterns, input validation, error handling |
| **api-contract-testing** | OpenAPI validation, PACT testing, mock servers |
| **ui-guidelines** | React/Next.js patterns, Ant Design, responsive design |
| **ci-cd-templates** | GitHub Actions, GitLab CI, deployment strategies |
| **docker-deployment** | Multi-stage builds, Docker Compose, security |
| **library-docs** | MCP-powered: fetch docs for React, Next.js, Vue, etc. |
| **deep-analysis** | MCP-powered: 31,999-token structured reasoning |
| **skill-creator** | Create your own custom skills |

### Create Your Own Skill

```bash
python3 .claude/skills/skill-creator/scripts/init_skill.py my-skill --path .claude/skills
```

---

## MCP Integration

5 Model Context Protocol servers auto-configured with team setup:

| Server | What It Does |
|--------|-------------|
| **context7** | Fetch documentation for 100+ libraries on-demand |
| **sequential-thinking** | Deep structured reasoning (31,999 thinking tokens) |
| **playwright** | Browser automation and E2E testing |
| **github** | PR/issue management via GitHub API |
| **postgres** | Database queries and optimization |

### Manual MCP Setup

```bash
claude mcp add context7 -- npx @upstash/context7-mcp@latest
claude mcp add sequential-thinking-server -- npx @modelcontextprotocol/server-sequential-thinking
claude mcp add playwright -- npx @executeautomation/playwright-mcp-server
claude mcp add github -- npx -y @modelcontextprotocol/server-github
claude mcp add postgres -- npx -y @modelcontextprotocol/server-postgres
```

---

## Auto-Enforced Rules

Two rule files in `.claude/rules/` are automatically loaded by Claude Code in every session:

- **security.md** — No secrets in commits, parameterized queries, input validation, security headers, least privilege
- **code-quality.md** — No dead code, single responsibility, early returns, explicit error handling, descriptive naming

---

## Architecture

```
.claude/
├── agents/          # 12 auto-activating SDLC agents
├── commands/        # 5 slash commands
├── skills/          # 11 modular knowledge packages
├── rules/           # 2 auto-enforced rule sets
├── lib/             # Templates, patterns, coordination protocol
└── history/         # Session history

global-config/       # Team-shareable config (hooks, keybindings, styles, settings)
```

See [EXTENSIBILITY.md](./EXTENSIBILITY.md) for the complete guide on Skills, MCP, Slash Commands, and Subagents.

---

## Usage Examples

**Building a feature:**
```
You: "Build a shopping cart with Stripe integration"
  → architecture-planner designs the system
  → api-backend implements payment logic
  → database-architect creates order schema
  → security-auditor validates payment security
  → test-automation generates tests
  → documentation-maintainer documents the API
```

**Performance issue:**
```
You: "The product search is running really slow"
  → performance-optimizer profiles the code
  → database-architect optimizes queries
  → code-quality suggests improvements
```

**Production emergency:**
```
You: "CRITICAL: Production API is returning 500 errors!"
  → incident-commander takes charge (Opus)
  → security-auditor checks for breaches
  → devops-automation prepares rollback
```

---

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/my-feature`)
3. Run `./validate.sh` to verify everything passes
4. Commit your changes (`git commit -m 'feat: add my feature'`)
5. Push and open a Pull Request

---

## Roadmap

- [ ] VS Code extension
- [ ] Observability dashboard
- [ ] Additional specialized agents
- [ ] Multi-language support
- [ ] Team collaboration features
- [ ] Custom agent marketplace

---

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- [GitHub Issues](https://github.com/pfangueiro/claude-code-agents/issues)
- [GitHub Discussions](https://github.com/pfangueiro/claude-code-agents/discussions)
- Update: `./install.sh --update`

---

<div align="center">

**No configuration. No commands. Just describe what you need.**

Built by [Pedro Fangueiro](https://github.com/pfangueiro) with [Claude](https://anthropic.com)

</div>
