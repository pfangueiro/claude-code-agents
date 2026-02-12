# Agent Coordination Protocol

Formal protocol for multi-agent collaboration in the Claude Agents system.

## Sequential Handoff Protocol

When one agent completes work and passes to the next, use this structured output:

```
### Handoff: [source-agent] -> [target-agent]

**Context**: What was done and why
**Artifacts**: Files created/modified with paths
**Decisions**: Key choices made and rationale
**Next Steps**: What the receiving agent should do
**Constraints**: Limitations or requirements to respect
```

### Example

```
### Handoff: architecture-planner -> api-backend

**Context**: Designed REST API for user auth with JWT tokens
**Artifacts**: docs/api-spec.md, docs/adr-001-jwt.md
**Decisions**: JWT over sessions (stateless scaling), bcrypt for passwords
**Next Steps**: Implement /auth/register, /auth/login, /auth/refresh endpoints
**Constraints**: Must use httpOnly cookies for refresh tokens, 15min access token TTL
```

## Parallel Coordination

When multiple agents work concurrently, they must agree on shared contracts before starting.

### Shared Contract Format

```
### Parallel Contract: [agent-a] + [agent-b]

**Interface**: Agreed API/data format between the agents
**Boundaries**: What each agent owns (no overlap)
**Sync Points**: When agents must check in with each other
```

### Example

```
### Parallel Contract: frontend-specialist + api-backend

**Interface**: OpenAPI spec at docs/api-spec.yaml
**Boundaries**:
  - frontend-specialist: UI components, client-side validation, state management
  - api-backend: Endpoints, server-side validation, database queries
**Sync Points**: After endpoint implementation, before integration testing
```

## Review Chain

Standard review order for completed work:

1. **code-quality** - Code standards, patterns, maintainability
2. **security-auditor** - OWASP compliance, vulnerability scan
3. **test-automation** - Test coverage, edge cases

Each reviewer adds findings in this format:

```
### Review: [reviewer-agent]

**Status**: PASS | PASS_WITH_NOTES | FAIL
**Findings**:
  - [Critical] Description (must fix before merge)
  - [Suggestion] Description (recommended improvement)
  - [Nit] Description (minor style/preference)
**Blocking**: Yes/No
```

## Error Recovery

When an agent encounters a failure:

1. **Document the failure**:
   ```
   ### Failure: [agent-name]

   **What failed**: Description
   **Root cause**: If known
   **Impact**: What downstream agents are affected
   **Recovery options**: List of possible next steps
   ```

2. **Conflict resolution** - When two agents produce conflicting outputs:
   - Security concerns take precedence over convenience
   - Performance concerns take precedence over code elegance
   - Correctness takes precedence over everything except security

## Priority Rules

When multiple agents could activate, priority determines which leads:

1. **incident-commander** - Always takes priority in emergencies
2. **security-auditor** - Security concerns override feature work
3. **test-automation** - Tests must pass before deployment
4. **architecture-planner** - Design decisions before implementation
5. **All other agents** - Equal priority, coordinate as peers

## Anti-Patterns

- **No silent handoffs**: Always document what was done before passing work
- **No overlapping ownership**: Each file/component has one owning agent
- **No skipping reviews**: Security review is mandatory for auth/data code
- **No cascading failures**: If one agent fails, others should not proceed blindly
