# Claude Code Agent Coordination System

## 🎯 Project Overview
This repository contains 15+ specialized Claude Code agents designed to work as a coordinated AI development team. Each agent has specific expertise and collaborates through defined workflows and handoff protocols.

## 📊 Model Selection Guidelines

### Cost-Performance Optimization
- **Haiku** ($0.80/1M tokens): Simple operations, file scanning, documentation
  - `directory-scanner`, `documentation-specialist`
- **Sonnet** ($3/1M tokens): Standard development tasks
  - `api-builder`, `frontend-architect`, `test-engineer`, `database-architect`
  - `refactor-specialist`, `ui-ux-specialist`, `mobile-developer`, `pwa-architect`
- **Opus** ($15/1M tokens): Complex architecture, security, orchestration
  - `secure-coder`, `deployment-engineer`, `meta-agent`, `project-coordinator`
  - `performance-optimizer`

## 🔄 Agent Collaboration Workflows

### Feature Development Pipeline
```
1. project-coordinator → Orchestrates workflow
2. database-architect → Schema design
3. api-builder → Backend implementation
4. frontend-architect → UI components  
5. test-engineer → Testing suite
6. refactor-specialist → Code improvement
7. performance-optimizer → Performance optimization
8. secure-coder → Security review
9. deployment-engineer → Deploy to staging
```

### Parallel Execution Patterns
Execute simultaneously for efficiency:
- `performance-optimizer` + `secure-coder` (independent reviews)
- `frontend-architect` + `api-builder` (separate concerns)
- `test-engineer` + `documentation-specialist` (parallel tasks)
- `ui-ux-specialist` + `mobile-developer` (platform-specific)

### The "3 Amigo" Pattern
For full-stack features:
1. **Orchestrator**: `project-coordinator`
2. **Backend Team**: `database-architect` + `api-builder`
3. **Frontend Team**: `frontend-architect` + `ui-ux-specialist`
4. **Quality Team**: `test-engineer` + `secure-coder` + `performance-optimizer`

### Quality Gate Pattern
Before deployment, ALL must pass:
- `test-engineer` → All tests passing
- `secure-coder` → No vulnerabilities
- `performance-optimizer` → No regressions

## 🤝 Handoff Protocol

When transferring between agents, include:
```yaml
HANDOFF_TOKEN: [Unique identifier for task tracking]
COMPLETED: [Summary of what was accomplished]
FILES_MODIFIED: [List of files changed/created]
NEXT_AGENT: [Recommended next agent(s)]
CONTEXT: [Critical information for next agent]
VALIDATION: [Success criteria met: true/false]
```

### Handoff Examples

#### API to Test Handoff
```yaml
HANDOFF_TOKEN: FEAT-001-API
COMPLETED: User authentication API with JWT
FILES_MODIFIED: [src/api/auth.js, src/models/User.js]
NEXT_AGENT: test-engineer
CONTEXT: JWT expiry set to 24h, refresh token enabled
VALIDATION: API responds with 200 OK
```

#### Test to Deploy Handoff
```yaml
HANDOFF_TOKEN: FEAT-001-TEST
COMPLETED: 95% test coverage, all passing
FILES_MODIFIED: [tests/api.test.js, tests/integration.test.js]
NEXT_AGENT: deployment-engineer
CONTEXT: Ready for staging deployment
VALIDATION: All tests passing: true
```

## 🧠 Advanced Problem Solving

### Thinking Modes
For complex problems, agents use extended thinking:
- **Standard tasks**: Normal processing
- **Complex designs**: `think` (4k tokens)
- **Architecture decisions**: `megathink` (10k tokens)  
- **Critical analysis**: `ultrathink` (32k tokens)

Agents that leverage thinking modes:
- `meta-agent`: For complex agent design
- `secure-coder`: For security audits
- `deployment-engineer`: For infrastructure planning
- `project-coordinator`: For workflow orchestration

## ⚡ Performance Guidelines

### Token Optimization
- Keep agent prompts under 5k tokens
- Use this CLAUDE.md for shared context (auto-loaded)
- Clear context after major milestones with `/clear`
- Use `/compact` for manual summarization
- Spawn fresh subagents when approaching limits

### Context Management Strategy
1. **Clear frequently**: After each feature/bug fix
2. **Use SCRATCHPAD.md**: For planning and state tracking
3. **Progressive summarization**: Carry forward compact summaries
4. **Parallel agents**: Max 10 concurrent agents
5. **Context isolation**: Each agent maintains own context

## 🚀 Workflow Automation

### Automatic Agent Activation
Agents activate based on keywords in your requests:
- "API" → `api-builder`
- "test" → `test-engineer`
- "deploy" → `deployment-engineer`
- "security" → `secure-coder`
- "performance" → `performance-optimizer`

### Common Workflows

#### New Feature Development
```bash
# Automatic flow when you say "implement user authentication feature"
1. project-coordinator → Plans implementation
2. database-architect → User table schema
3. api-builder → Auth endpoints
4. frontend-architect → Login components
5. test-engineer → Test coverage
6. secure-coder → Security validation
7. deployment-engineer → Deploy
```

#### Bug Fix Workflow
```bash
# Automatic flow when you say "fix performance issue in dashboard"
1. performance-optimizer → Identifies bottlenecks
2. refactor-specialist → Improves code
3. test-engineer → Validates fix
4. deployment-engineer → Deploy patch
```

#### Code Review Workflow
```bash
# Automatic flow when you say "review this pull request"
1. secure-coder → Security check
2. performance-optimizer → Performance impact
3. refactor-specialist → Code quality
4. test-engineer → Test coverage
```

## 📋 Agent Quick Reference

| Agent | Model | Primary Triggers | Hands Off To |
|-------|-------|------------------|--------------|
| api-builder | sonnet | API, REST, GraphQL | test-engineer |
| database-architect | sonnet | database, schema, SQL | api-builder |
| frontend-architect | sonnet | React, Vue, frontend | test-engineer |
| test-engineer | sonnet | test, TDD, coverage | deployment-engineer |
| secure-coder | opus | security, OWASP, auth | deployment-engineer |
| deployment-engineer | opus | deploy, Docker, K8s | project-coordinator |
| performance-optimizer | opus | performance, slow | deployment-engineer |
| refactor-specialist | sonnet | refactor, clean code | test-engineer |
| project-coordinator | opus | project, planning | all agents |
| ui-ux-specialist | sonnet | UI, UX, design | frontend-architect |
| mobile-developer | sonnet | mobile, iOS, Android | test-engineer |
| pwa-architect | sonnet | PWA, service worker | test-engineer |
| documentation-specialist | haiku | README, docs | - |
| directory-scanner | haiku | directory, structure | - |
| meta-agent | opus | create agent | - |

## 🔧 Custom Commands

### Available Commands
- `/agents` - List all available agents
- `/clear` - Clear context (use often!)
- `/compact` - Manually compact context
- `/init` - Initialize project analysis

## 📈 Performance Metrics

Expected improvements with this system:
- **60% cost reduction** through model optimization
- **90% performance improvement** with orchestration
- **10x parallel task execution** capability
- **3-week to 4-day** feature delivery

## 🛡️ Security & Compliance

All code changes must pass through:
1. `secure-coder` validation
2. `test-engineer` verification
3. `performance-optimizer` review

Security is enforced at quality gates - no deployment without approval.

## 📝 Notes

- This file is automatically loaded at session start
- Keep project-specific customizations here
- Reference this file in agent prompts for consistency
- Update as workflows evolve

---
*Claude Code Agent System v2.0 - Optimized for 2025*