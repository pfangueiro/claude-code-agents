# SDLC/SSDLC Patterns Reference

## Overview
This reference guide helps the meta-agent identify which phase of the Software Development Life Cycle (SDLC) or Secure Software Development Life Cycle (SSDLC) the user is working in, and generate appropriate agents.

## Phase Detection Patterns

### 1. Planning & Requirements Phase
**Keywords**: plan, requirement, design, architecture, specification, proposal, feasibility, scope
**Context Phrases**:
- "design a system for..."
- "create an architecture for..."
- "plan the implementation of..."
- "define requirements for..."
- "propose a solution for..."

**Recommended Agents**: architecture-planner, database-architect
**Tools Focus**: Research and documentation tools (Read, WebFetch, WebSearch, Write)
**Model Preference**: Sonnet or Opus for complex systems

### 2. Design & Architecture Phase
**Keywords**: blueprint, schema, interface, api, contract, diagram, model, pattern
**Context Phrases**:
- "create the database schema..."
- "design the API interface..."
- "model the data structure..."
- "define the system architecture..."

**Recommended Agents**: architecture-planner, database-architect, api-backend
**Tools Focus**: Design and documentation tools (Write, WebFetch, Task)
**Model Preference**: Sonnet for standard designs, Opus for complex architectures

### 3. Development & Implementation Phase
**Keywords**: implement, code, build, create, develop, function, component, feature
**Context Phrases**:
- "implement the feature..."
- "write code for..."
- "build the component..."
- "create the service..."

**Recommended Agents**: frontend-specialist, api-backend, code-quality
**Tools Focus**: Full development tools (Read, Write, Edit, Bash)
**Model Preference**: Sonnet for standard development, Haiku for simple tasks

### 4. Testing & Quality Assurance Phase
**Keywords**: test, validate, verify, coverage, assertion, mock, quality, bug
**Context Phrases**:
- "write tests for..."
- "validate the implementation..."
- "ensure quality of..."
- "check for bugs in..."

**Recommended Agents**: test-automation, code-quality, performance-optimizer
**Tools Focus**: Testing and analysis tools (Read, Bash, Grep, Task)
**Model Preference**: Sonnet for comprehensive testing

### 5. Security & Compliance Phase (SSDLC)
**Keywords**: security, vulnerability, auth, encryption, compliance, owasp, threat
**Context Phrases**:
- "scan for vulnerabilities..."
- "implement security measures..."
- "ensure compliance with..."
- "check for security issues..."

**Recommended Agents**: security-auditor (ALWAYS)
**Tools Focus**: All tools for comprehensive scanning
**Model Preference**: ALWAYS Opus for security-critical tasks

### 6. Deployment & Release Phase
**Keywords**: deploy, release, ci, cd, pipeline, docker, kubernetes, production
**Context Phrases**:
- "deploy to production..."
- "set up the pipeline..."
- "configure deployment..."
- "release the application..."

**Recommended Agents**: devops-automation, incident-commander (for hotfixes)
**Tools Focus**: Deployment tools (Bash, Write, Edit, WebFetch)
**Model Preference**: Sonnet for standard deployments, Opus for production-critical

### 7. Maintenance & Operations Phase
**Keywords**: monitor, maintain, optimize, update, patch, incident, performance
**Context Phrases**:
- "optimize performance..."
- "fix the production issue..."
- "update the documentation..."
- "monitor the system..."

**Recommended Agents**: incident-commander, performance-optimizer, documentation-maintainer
**Tools Focus**: Monitoring and update tools (Read, Edit, Bash)
**Model Preference**: Opus for incidents, Sonnet for optimization, Haiku for documentation

## Multi-Phase Workflows

### Full Stack Development
Phases: Design → Development → Testing → Deployment
Agents: architecture-planner → frontend-specialist/api-backend → test-automation → devops-automation

### Security-First Development (SSDLC)
Phases: Planning → Development → Security → Testing → Deployment
Agents: security-auditor (throughout) + phase-specific agents

### Incident Response
Phases: Detection → Triage → Mitigation → Recovery → Postmortem
Agents: incident-commander (lead) + supporting specialists

### Performance Optimization
Phases: Profiling → Analysis → Optimization → Testing → Deployment
Agents: performance-optimizer → code-quality → test-automation → devops-automation

## Agent Collaboration Patterns

### Sequential Pattern
- Agent A completes → Agent B starts
- Example: architecture-planner → api-backend

### Parallel Pattern
- Multiple agents work simultaneously
- Example: frontend-specialist + api-backend

### Hierarchical Pattern
- Lead agent coordinates sub-agents
- Example: incident-commander coordinates multiple specialists

### Review Pattern
- Main agent → Review agent validates
- Example: Any development agent → code-quality

## Priority Rules

### Critical Priority (Immediate Activation)
- Production incidents
- Security vulnerabilities
- Data loss risks
Agents: incident-commander, security-auditor

### High Priority
- Testing before deployment
- Code review before merge
Agents: test-automation, code-quality

### Medium Priority
- Performance optimization
- Architecture planning
Agents: performance-optimizer, architecture-planner

### Low Priority
- Documentation updates
- Non-critical refactoring
Agents: documentation-maintainer

## Best Practices for Agent Generation

1. **Single Responsibility**: Each agent should have one clear purpose
2. **Clear Activation**: Use PROACTIVELY, MUST BE USED keywords appropriately
3. **Tool Minimization**: Only grant necessary tools (principle of least privilege)
4. **Model Optimization**:
   - Haiku for simple/documentation tasks (95% cost savings)
   - Sonnet for standard development (balanced)
   - Opus for critical/security tasks (maximum capability)
5. **Collaboration Awareness**: Define how agents hand off work
6. **Observability**: Include success metrics and logging
7. **Security First**: Always consider security implications
8. **Testing Integration**: Encourage test-driven development patterns

## Common Anti-Patterns to Avoid

1. **Over-Engineering**: Don't create complex agents for simple tasks
2. **Tool Overload**: Don't grant all tools to every agent
3. **Model Waste**: Don't use Opus for simple documentation
4. **Missing Security**: Never skip security considerations
5. **Poor Handoffs**: Always define clear agent boundaries
6. **No Testing**: Always include testing in workflows
7. **Ignored Documentation**: Keep docs synchronized with code

## Telemetry & Improvement

Track these metrics for generated agents:
- Activation accuracy (did the right agent activate?)
- Task completion rate
- Model cost efficiency
- Security issue detection rate
- Collaboration effectiveness
- User satisfaction

Use telemetry data to continuously improve:
- Keyword patterns
- Tool assignments
- Model selections
- Collaboration patterns