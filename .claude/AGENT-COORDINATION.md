# Claude Code Agent System Coordination

## ⚠️ IMPORTANT
This file contains the core coordination rules for the Claude Code Agent System.
It should be copied with the agents and NOT modified per project.
Project-specific configuration goes in the root CLAUDE.md file.

## 📊 Model Selection Rules

### Automatic Model Assignment
Agents are pre-configured with optimal models:
- **Haiku** ($0.80/1M tokens): Simple operations
- **Sonnet** ($3/1M tokens): Standard development
- **Opus** ($15/1M tokens): Complex architecture

### Model Override Guidelines
Only override if you have specific requirements:
```yaml
# In agent frontmatter
model: sonnet  # Default assignment
# Change only if needed for cost or performance reasons
```

## 🔄 Agent Collaboration Patterns

### Sequential Workflow
Agents hand off tasks in sequence:
```
Agent A completes → Agent B starts → Agent C finishes
```

### Parallel Execution
Independent agents work simultaneously:
```
Agent A ┐
         ├→ Merge results
Agent B ┘
```

### Fork-Join Pattern
Split work, then merge:
```
        ┌→ Agent B ┐
Agent A ┤          ├→ Agent D
        └→ Agent C ┘
```

### Quality Gate Pattern
Validation before proceeding:
```
Development → Quality Gates (parallel) → Deployment
              - test-engineer
              - secure-coder
              - performance-optimizer
```

## 🤝 Handoff Protocol Specification

### Required Fields
Every handoff MUST include:
```yaml
HANDOFF_TOKEN: [Unique identifier]
COMPLETED: [What was done]
FILES_MODIFIED: [List of files]
NEXT_AGENT: [Target agent(s)]
CONTEXT: [Critical information]
VALIDATION: [Success: true/false]
```

### Handoff States
- `PENDING`: Task not started
- `IN_PROGRESS`: Agent working
- `COMPLETED`: Ready for handoff
- `BLOCKED`: Requires intervention
- `FAILED`: Task failed

## 🧠 Thinking Mode Usage

### Token Budgets
- `think`: 4,000 tokens
- `megathink`: 10,000 tokens
- `ultrathink`: 32,000 tokens

### When to Use
- **Standard processing**: No thinking mode
- **Complex logic**: `think`
- **Architecture decisions**: `megathink`
- **Critical analysis**: `ultrathink`

## 📈 Performance Optimization

### Token Management
1. Agents keep prompts under 5,000 tokens
2. Reference CLAUDE.md for shared context
3. Use handoffs to transfer context
4. Clear context between major milestones

### Parallel Execution Limits
- Maximum: 10 concurrent agents
- Optimal: 3-5 agents
- Monitor token usage when parallel

## 🔐 Quality Enforcement

### Mandatory Quality Gates
Before deployment, ALL must pass:
1. `test-engineer`: All tests passing
2. `secure-coder`: No vulnerabilities
3. `performance-optimizer`: No regressions

### Gate Bypass
Only with explicit user approval:
```
User: "Deploy without security review"
System: Warns about risks, proceeds if confirmed
```

## 🎯 Agent Activation Priority

### Activation Precedence
1. Explicit invocation: "Use api-builder to..."
2. Keyword match: "REST API" → api-builder
3. Context inference: API file → api-builder
4. Workflow stage: After frontend → test-engineer

### Conflict Resolution
When multiple agents could activate:
1. Most specific keywords win
2. "MUST BE USED" overrides "PROACTIVELY"
3. Project CLAUDE.md preferences apply
4. User can override with explicit invocation

## 📊 Agent Performance Metrics

### Success Indicators
- Task completion rate
- Handoff success rate
- Quality gate pass rate
- Token efficiency

### Performance Thresholds
- Handoff success: >95%
- Quality gate pass: >90%
- Token per task: <10,000 average

## 🔄 Workflow Orchestration

### Standard Workflows

#### Feature Development
```yaml
trigger: "implement feature"
sequence:
  - project-coordinator    # Planning
  - database-architect    # Schema
  - api-builder          # Backend
  - frontend-architect   # Frontend
  - test-engineer        # Testing
  - secure-coder        # Security
  - deployment-engineer  # Deploy
```

#### Bug Fix
```yaml
trigger: "fix bug"
sequence:
  - performance-optimizer OR secure-coder  # Based on bug type
  - refactor-specialist                   # Fix implementation
  - test-engineer                        # Validation
  - deployment-engineer                  # Hotfix
```

#### Code Review
```yaml
trigger: "review code"
parallel:
  - secure-coder         # Security
  - performance-optimizer # Performance
  - refactor-specialist  # Quality
  - test-engineer       # Coverage
```

## 🚀 Orchestration Commands

### /workflow
Executes predefined workflow based on type:
- `feature`: Full development pipeline
- `bug`: Bug fix workflow
- `review`: Code review workflow
- `security`: Security audit
- `performance`: Optimization workflow

### /orchestrate
Dynamic orchestration based on task analysis

### /quality-check
Runs all quality gates in parallel

## 📝 System Constants

### File Locations
- User agents: `~/.claude/agents/`
- Project agents: `.claude/agents/`
- Commands: `.claude/commands/`
- Project config: `./CLAUDE.md`

### Precedence Rules
1. Project agents override user agents
2. Project CLAUDE.md overrides defaults
3. Explicit invocation overrides automatic

## 🔧 Troubleshooting

### Common Issues
1. **Agent not activating**: Check keywords in description
2. **Wrong model used**: Verify model parameter
3. **Handoff failing**: Check VALIDATION field
4. **Token limit**: Use /clear or /compact

### Debug Mode
Enable verbose output:
```
/debug on
[Perform task]
/debug off
```

---
*Agent Coordination System v2.0 - Do not modify*
*Project customization goes in root CLAUDE.md*