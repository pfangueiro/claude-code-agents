# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Claude Agents** — enterprise AI agent system with 13 specialized SDLC/SSDLC agents, 21 skills, and 13 slash commands that auto-activate based on natural language. Automatically selects optimal Claude model (Haiku/Sonnet/Opus) per task complexity.

## IMPORTANT: Auto-Activation

Agents activate automatically from natural language. Just describe what you want — the right specialist engages.

## Agents

| Agent | Activates On | Model |
|-------|-------------|-------|
| **architecture-planner** | design, architecture, system, blueprint, API contract, planning | Sonnet |
| **code-quality** | review, quality, refactor, clean code, lint, best practices | Sonnet |
| **security-auditor** | security, vulnerability, auth, XSS, CSRF, injection, OWASP | **Opus** |
| **test-automation** | test, unit test, integration, e2e, coverage, TDD, mock | Sonnet |
| **performance-optimizer** | slow, performance, optimize, speed, bottleneck, profile | Sonnet |
| **devops-automation** | deploy, CI/CD, pipeline, Docker, Kubernetes, AWS, production | Sonnet |
| **documentation-maintainer** | document, README, API doc, guide, tutorial | Haiku |
| **database-architect** | database, SQL, schema, migration, query, index | Sonnet |
| **frontend-specialist** | frontend, UI, UX, React, Vue, Angular, component, CSS | Sonnet |
| **api-backend** | backend, API, endpoint, service, REST, GraphQL, microservice | Sonnet |
| **incident-commander** | CRITICAL, EMERGENCY, INCIDENT, OUTAGE, production down | **Opus** |
| **sre-specialist** | SRE, reliability, SLO, SLI, error budget, on-call, postmortem, capacity, chaos, runbook | Sonnet |
| **meta-agent** | create agent, generate agent, agent template, SDLC agent | **Opus** |

Agent collaboration patterns: see `.claude/lib/agent-coordination.md`

## Orchestration Skills (Slash Commands)

- **`/deep-read <target>`** — 6-phase codebase reading engine (SCOPE/MAP/TRACE/DEEP READ/CONNECT/REPORT). Source code is the source of truth.
- **`/execute <goal>`** — Orchestrated task engine: decompose → plan → select agents → execute in parallel batches → track progress.
- **`/investigate <symptom>`** — 8-phase root cause analysis (OBSERVE/REPRODUCE/TRACE/HYPOTHESIZE/PROVE/ROOT CAUSE/FIX/PREVENT). Never jumps to a fix.
- **`/deep-analysis <problem>`** — Structured reasoning via sequential-thinking MCP: branching, revision, hypothesis testing.

## Developer Workflow Commands

- **`/build-fix [path]`** — Auto-detect build system, run build, parse errors, fix one at a time with regression guard.
- **`/tdd <feature>`** — Enforce RED-GREEN-REFACTOR cycle: write failing test → implement minimally → refactor → verify.
- **`/quality-gate [path] [--fix] [--strict]`** — Pre-commit validation: formatter + linter + type checker + tests.
- **`/checkpoint <name> [--verify] [--list] [--diff]`** — Named save points via git branches for complex multi-step work.
- **`/save-session [id]`** — Save structured session state with mandatory "What Did NOT Work" section.
- **`/resume-session [id]`** — Resume from a saved session with full context briefing and file state verification.
- **`/optimize <metric> [--iterations N]`** — Autonomous metric-driven improvement loop: measure → improve → verify → keep/revert.

## Skills System

Skills provide modular knowledge packages that complement agents. See `.claude/skills/README.md` for full documentation.

**Reference skills:** skill-creator, git-workflow, code-review-checklist, deployment-runbook, security-scan
**SRE/Cloud skills:** kubernetes-ops, observability-stack, sre-runbooks, infrastructure-as-code
**Experimentation skills:** experiment-loop (autonomous optimization patterns)
**MCP-powered skills:** library-docs (context7), deep-analysis (sequential-thinking)

Creating skills: `python3 .claude/skills/skill-creator/scripts/init_skill.py <name> --path .claude/skills`

## MCP Integration

MCP servers provide external tools that extend Claude Code. See `.claude/lib/mcp-guide.md` for configuration and usage.

## Hooks

10 hook events across 3 types. Hooks live in `global-config/hooks/`, installed globally to `~/.claude/hooks/`.

**Command hooks (8 scripts):**
- `file-protection.sh` — PreToolUse: blocks edits to sensitive files (.env, *.key, *.pem)
- `post-edit-lint.sh` — PostToolUse: auto-lints TS/JS after Write/Edit, warns on debug statements
- `notify.sh` — Notification: desktop alerts when Claude needs attention
- `agent-tracker.sh` — SubagentStart/SubagentStop: real-time agent lifecycle tracking to `agent-events.jsonl`
- `session-end.sh` — Stop: logs session completion to `session-summaries.jsonl`
- `smart-guard.sh` — PermissionRequest: auto-approves safe read operations, audits dangerous ones
- `pre-compact.sh` — PreCompact: auto-saves session snapshot before context compaction
- `post-compact.sh` — PostCompact: verifies session snapshot was saved after compaction

**Reference configs (Phase 2 opt-in):**
- `smart-file-guard.json` — prompt hook: LLM-based file protection for edge cases
- `pre-commit-review.json` — agent hook: automated code review before git commit

## Observability

Built-in dashboard aggregating Claude Code JSONL session logs across all projects. Files in `observability/`, installed to `~/.claude/analytics/`. Run `claude-obs` to collect data and open the dashboard. Hook-generated events (`agent-events.jsonl`, `permission-audit.jsonl`, `session-summaries.jsonl`) are also ingested.

## Security-First

**CRITICAL:** security-auditor and incident-commander ALWAYS use Opus. Security considerations are embedded in every agent following OWASP guidelines and DevSecOps best practices.

## Quick Start

Describe what you need naturally:

```
"I need to build a user registration system with email verification"
```

This triggers: architecture-planner → api-backend + database-architect → security-auditor → test-automation → documentation-maintainer
