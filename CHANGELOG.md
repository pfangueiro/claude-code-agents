# Changelog

All notable changes to Claude Agents will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-02-12

### Quality, Coordination & Extensibility Release

This release fixes credibility gaps between documentation and reality, adds missing infrastructure, and incorporates improvements from the latest Claude Code features.

### Fixed

- **False telemetry/metrics claims**: Removed fabricated metrics ("90ms activation", "30% productivity", "85% accuracy") from README.md
- **Telemetry references**: Marked telemetry as "Planned" across README.md, CLAUDE.md, and sdlc-patterns.md — no longer claimed as existing
- **EXTENSIBILITY.md directory references**: Fixed all `.claude/subagents/` references to `.claude/agents/`
- **EXTENSIBILITY.md version**: Updated from 2.2.0 to 2.3.0
- **meta-agent.md broken tools**: Removed non-existent `firecrawl` MCP tools, added `WebSearch`
- **meta-agent.md URLs**: Fixed documentation URLs from `docs.claude.com` to `docs.anthropic.com`
- **meta-agent.md telemetry**: Replaced "Generate Telemetry Hooks" with "Define Success Criteria"
- **install.sh error handling**: `install_agent()` and `install_lib_file()` now check return codes from `download_or_copy()`

### Added

- **validate.sh**: New validation script checking all agent files (frontmatter, sections), lib files (JSON validity), skills (SKILL.md), MCP config, slash commands, and cross-references
- **Agent coordination protocol** (`.claude/lib/agent-coordination.md`): Formal protocol for sequential handoffs, parallel coordination, review chains, error recovery, and priority rules
- **.claude/rules/ directory**: Auto-loaded rules for security and code quality
  - `security.md`: Secrets, input validation, auth, HTTP security, dependencies
  - `code-quality.md`: Dead code, function design, error handling, naming
- **`/review-pr` slash command**: PR review for code quality, security (OWASP), testing, documentation
- **`/security-scan` slash command**: Security scanning with secrets detection, dependency checks, OWASP patterns, file permissions
- **install.sh preflight checks**: Write permissions, disk space, source directory validation
- **install.sh rules installation**: New `install_rules()` function and `.claude/rules/` directory creation
- **install.sh error counting**: `install_errors` counter in `install_full()`
- **EXTENSIBILITY.md meta-agent listing**: Added missing `meta-agent` to agents list

### Changed

- README.md "Enterprise Ready" description updated from "telemetry and monitoring" to "extensible architecture"
- README.md `history/` directory description updated from "Telemetry & learning" to "Session history (planned: telemetry)"
- README.md "Why Claude Agents?" section updated to reference extensibility instead of telemetry
- CLAUDE.md "Continuous Improvement" section marked as planned
- Commands README updated with `/review-pr` and `/security-scan` documentation

---

## [2.2.0] - 2025-10-28

### 🌐 MCP Integration & 4-Way Extensibility

This release introduces **Model Context Protocol (MCP)** integration, adding external tools and data sources to the Claude Code platform. Combined with Skills, Slash Commands, and Subagents, this creates a comprehensive 4-way extensibility system.

### Added

#### MCP-Powered Skills
- 🟢 **library-docs** skill (uses context7 MCP server)
  - Fetch up-to-date documentation for 100+ libraries
  - Support for React, Next.js, Vue, MongoDB, Supabase, PostgreSQL, and more
  - Topic-focused documentation retrieval
  - Version-specific query support
  - Integration with documentation-maintainer agent

- 🧠 **deep-analysis** skill (uses sequential-thinking MCP server)
  - Structured multi-step reasoning for complex problems
  - Up to 31,999 thinking tokens (vs 4,000 standard)
  - Hypothesis generation and verification
  - Course correction and branching
  - Integration with architecture-planner and performance-optimizer agents

#### Comprehensive Documentation
- 📘 **EXTENSIBILITY.md** - Complete extensibility guide
  - Comprehensive overview of all four mechanisms
  - Skills (Blue): Knowledge & methodology
  - MCP (Green): External tools & data
  - Slash Commands (Red): User-triggered workflows
  - Subagents (Orange): Isolated task execution
  - Decision matrix for choosing mechanisms
  - 5 integration patterns with real examples
  - Best practices for each mechanism
  - Validation and testing guidance

#### Enhanced Documentation
- 📝 **CLAUDE.md Updates**
  - Added comprehensive MCP Integration section
  - Documentation of both MCP servers (context7, sequential-thinking)
  - MCP + Agent integration examples
  - Configuration guidance
  - Usage patterns and examples

- 📖 **README.md Updates**
  - Version badge updated to 2.2.0
  - Skills badge updated to 6 included
  - New MCP badge added
  - Added "MCP Integration" to key features
  - Added "4-Way Extensibility" feature
  - New MCP Integration section with examples
  - Four extensibility mechanisms diagram
  - Architecture updated to show MCP-powered skills
  - Links to EXTENSIBILITY.md

### Enhanced

- 🔌 **Four Extensibility Mechanisms**
  - **Skills**: Modular knowledge packages (6 included)
  - **MCP**: External integrations (2 servers configured)
  - **Slash Commands**: User-triggered workflows
  - **Subagents**: Isolated execution (11 agents)

- 🎓 **Skills System**
  - Now includes MCP-powered skills
  - Clear integration patterns with MCP servers
  - Enhanced agent-skill collaboration
  - Updated power combos showing MCP usage

- 📊 **Integration Patterns**
  - Skill + MCP: library-docs fetches external data
  - Skill + Agent: deep-analysis guides architecture-planner
  - MCP + Agent: External tools enhance agent capabilities
  - Full Integration: All mechanisms working together

### Technical Details
- **New Skills**: 2 MCP-powered (library-docs, deep-analysis)
- **Total Skills**: 6 (skill-creator + git-workflow + code-review-checklist + deployment-runbook + library-docs + deep-analysis)
- **MCP Servers**: 2 (context7, sequential-thinking)
- **Documentation**: 800+ line extensibility guide
- **Architecture**: 4-way extensibility system

### MCP Configuration

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

### Benefits

**For Developers:**
- Access up-to-date library documentation on-demand
- Deep reasoning for complex architectural decisions
- External tool integration via MCP
- Clear decision matrix for extensibility choices

**For Organizations:**
- Comprehensive extensibility options
- Integration with external APIs and services
- Structured reasoning for critical decisions
- Complete documentation of all mechanisms

### Skills + MCP + Agents Integration

| Agent | Skill | MCP Server | Result |
|-------|-------|------------|--------|
| **architecture-planner** | **deep-analysis** | sequential-thinking | Structured architectural decisions |
| **documentation-maintainer** | **library-docs** | context7 | Documentation using library patterns |
| **performance-optimizer** | **deep-analysis** | sequential-thinking | Root cause analysis |

### What's Next?

See **[EXTENSIBILITY.md](./EXTENSIBILITY.md)** for:
- Complete guide to all four mechanisms
- Decision matrices and integration patterns
- Real-world examples from this project
- Best practices and validation guidance

---

## [2.0.0] - 2024-10-16

### 🚀 Major Release - Enterprise Agent System

This release transforms Claude Agents into a comprehensive enterprise-grade SDLC/SSDLC agent system with natural language activation.

### Added

#### Core System
- ✨ **11 Specialized SDLC/SSDLC Agents**
  - `architecture-planner` - System design and API specifications
  - `code-quality` - Code review and quality metrics
  - `security-auditor` - OWASP compliance and vulnerability scanning
  - `test-automation` - Comprehensive test generation
  - `performance-optimizer` - Profiling and optimization
  - `devops-automation` - CI/CD and deployment
  - `documentation-maintainer` - Auto-documentation with Haiku
  - `database-architect` - Schema design and query optimization
  - `frontend-specialist` - UI/UX implementation
  - `api-backend` - Backend service development
  - `incident-commander` - Production emergency response

#### Meta-Agent System
- 🤖 **Enhanced Meta-Agent v2.0**
  - SDLC/SSDLC phase awareness
  - Natural language activation patterns
  - Security-first design principles
  - Intelligent tool selection
  - Multi-agent orchestration
  - Cost optimization (Haiku/Sonnet/Opus)

#### Supporting Infrastructure
- 📚 **Agent Templates Library** (`agent-templates.json`)
  - 13 pre-built agent templates
  - Activation keywords and patterns
  - Tool configurations
  - Best practices embedded

- 📋 **SDLC Patterns Reference** (`sdlc-patterns.md`)
  - Phase detection patterns
  - Multi-agent workflows
  - Priority rules
  - Collaboration strategies

- 🔤 **Activation Keywords Database** (`activation-keywords.json`)
  - Natural language patterns
  - Confidence scoring
  - Technology-specific keywords
  - Multi-agent triggers

#### Installation System
- 🛠️ **Intelligent Installer** (`install.sh`)
  - Detects existing components
  - Multiple modes (minimal, full, repair, update)
  - Automatic backups
  - Progress tracking
  - Verification and rollback

- 📦 **Deployment Options**
  - One-liner installation from GitHub
  - Multiple CLAUDE.md variants
  - Merge-friendly configurations
  - Ultra-minimal options

### Changed
- 🔄 **Complete Architecture Overhaul**
  - From 4 basic agents to 11 specialized agents
  - From manual commands to natural language activation
  - From single agent to multi-agent collaboration
  - From fixed models to intelligent selection

### Enhanced
- 💡 **Natural Language Processing**
  - Auto-activation based on conversation context
  - Weighted confidence scoring
  - Context-aware agent selection
  - Phrase pattern matching

- 💰 **Cost Optimization**
  - Haiku for documentation (95% savings)
  - Sonnet for standard development
  - Opus for security and critical tasks
  - ~70% overall cost reduction

- 🔒 **Security Improvements**
  - OWASP Top 10 compliance
  - DevSecOps practices
  - Automatic security scanning
  - SOC2/ISO 27001 considerations

### Technical Details
- **Lines of Code**: 5,000+
- **Configuration Files**: 15+
- **Agent Definitions**: 11
- **Test Coverage**: Comprehensive
- **Performance**: Keyword-based activation

### Breaking Changes
- Old agent format deprecated
- Manual command invocation replaced with auto-activation
- Directory structure reorganized

### Migration Guide
Users can upgrade using:
```bash
./install.sh --update
```

## [1.0.0] - 2024-10-01

### Initial Release
- Basic 4-agent system
- Manual router
- Simple cost tracking
- Basic installation script

## [2.1.0] - 2024-10-28

### 🎓 Skills System Integration

This release adds a comprehensive skills system that extends the agent framework with modular knowledge packages, enabling users to create custom domain expertise alongside the existing agent system.

### Added

#### Skills System
- ✨ **Skills Infrastructure**
  - `.claude/skills/` directory for modular knowledge packages
  - Integration with existing 11-agent system
  - Progressive disclosure (metadata → SKILL.md → bundled resources)
  - Skill creation, validation, and packaging tools

- 🛠️ **skill-creator Skill**
  - `init_skill.py` - Create new skills from templates
  - `package_skill.py` - Validate and package skills for distribution
  - `quick_validate.py` - Quick validation during development
  - Comprehensive skill creation methodology (6-step process)

#### Demonstration Skills
- 📚 **git-workflow**
  - Git best practices and branching strategies
  - Commit message guidelines (Conventional Commits)
  - Pull request workflows
  - Merge conflict resolution
  - Git Flow, GitHub Flow, Trunk-Based Development

- 🔍 **code-review-checklist**
  - Systematic code review guidelines
  - 10-category review framework
  - Security checklist (OWASP Top 10)
  - Performance anti-patterns
  - Team collaboration best practices
  - Complements code-quality agent

- 🚀 **deployment-runbook**
  - Deployment strategies (blue-green, canary, rolling)
  - Pre/post-deployment checklists
  - Health check automation scripts
  - Rollback procedures
  - Troubleshooting guides
  - Complements devops-automation agent

#### Documentation
- 📖 **Comprehensive Skills Documentation**
  - Updated CLAUDE.md with Skills System section
  - Agent vs Skills comparison guide
  - Skills integration examples
  - README.md with skills features
  - Updated architecture diagrams

- 📘 **Skills README** (`.claude/skills/README.md`)
  - What skills are and when to create them
  - Skills vs agents comparison
  - Step-by-step creation guide
  - Integration patterns
  - Real-world examples

### Enhanced

- 🎯 **Agent-Skill Integration**
  - Skills complement agents for powerful workflows
  - Examples: code-quality + code-review-checklist
  - Clear guidance on when to use agents vs skills
  - Progressive disclosure for efficient context management

- 📊 **Architecture**
  - Updated to show dual agent + skills system
  - Clear separation of concerns
  - Modular, extensible design

### Technical Details
- **New Skills**: 4 (skill-creator + 3 demonstrations)
- **Scripts Added**: 3 Python utilities
- **Documentation Pages**: 5+ comprehensive guides
- **Directory Structure**: `.claude/skills/` with organized subdirectories

### Benefits

**For Users:**
- Extend capabilities with domain-specific knowledge
- Create reusable, shareable skill packages
- Bundle scripts, references, and assets
- Complement agents with specialized expertise

**For Organizations:**
- Codify company-specific knowledge (APIs, schemas, processes)
- Standardize workflows across teams
- Share best practices through skills
- Reduce onboarding time with packaged knowledge

### Skills vs Agents

| **Agents** | **Skills** |
|------------|------------|
| Auto-activating task executors | Modular knowledge packages |
| Execute SDLC workflows | Provide domain expertise & tools |
| Examples: security-auditor, test-automation | Examples: git-workflow, brand-guidelines |

---

## Upcoming Features

### [3.0.0] - Future
- VS Code extension
- Web dashboard for telemetry
- AI model fine-tuning
- Custom agent marketplace
- Enterprise dashboard
- Advanced telemetry analytics