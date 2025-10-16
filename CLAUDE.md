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

Agents work together in workflows:

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

## 📈 Continuous Improvement

The agent system includes telemetry and learning:
- Tracks activation accuracy
- Monitors task completion rates
- Optimizes model selection
- Refines activation patterns

---

**Remember:** You don't need to manually invoke agents - they activate automatically based on your natural language. Just describe what you want to accomplish, and the right experts will engage to help you succeed!