# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Claude Agents** — enterprise AI agent system with 13 specialized SDLC/SSDLC agents, 26 skills, and 13 slash commands that auto-activate based on natural language. Automatically selects optimal Claude model (Haiku/Sonnet/Opus) per task complexity.

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

## Built-in Tools (Always Available)

Beyond agents and skills, Claude Code provides these tools you can use directly:

| Tool | Use When |
|------|----------|
| **TaskCreate/TaskUpdate/TaskList** | Multi-step work — structured task tracking with dependencies and progress |
| **CronCreate/CronDelete/CronList** | Recurring prompts, polling, reminders (session-scoped, 7-day max) |
| **EnterWorktree/ExitWorktree** | Parallel development — isolated git worktree branches for experiments or features |
| **RemoteTrigger** | Cross-session automation — create/run scheduled remote agents |
| **LSP** | Code intelligence — go-to-definition, find-references, hover, document symbols |
| **AskUserQuestion** | Structured user input with labeled options and previews |

## Skills System

Skills provide modular knowledge packages that complement agents. See `.claude/skills/README.md` for full documentation.

**Reference skills:** skill-creator, git-workflow, code-review-checklist, deployment-runbook, security-scan
**SRE/Cloud skills:** kubernetes-ops, observability-stack, sre-runbooks, infrastructure-as-code
**Experimentation skills:** experiment-loop (autonomous optimization patterns)
**Automation skills:** scheduled-tasks (CronCreate), worktree-workflow (EnterWorktree), remote-triggers (RemoteTrigger), multi-agent-orchestration (TeamCreate/SendMessage)
**Testing skills:** browser-testing (Playwright MCP for E2E, visual regression), api-contract-testing (OpenAPI / JSON Schema / contract-first)
**API skills:** api-guidelines (Next.js/TypeScript secure endpoint patterns)
**UI skills:** ui-guidelines (React/Next.js + Ant Design + shadcn patterns, spacing / typography / color system)
**Infra skills:** docker-deployment (multi-stage builds, prod configs), ci-cd-templates (GitHub Actions / GitLab CI / CircleCI)
**Session skills:** handoff (HANDOFF.md creation for session continuity before /compact)
**MCP-powered skills:** library-docs (context7), deep-analysis (sequential-thinking)

Creating skills: `python3 .claude/skills/skill-creator/scripts/init_skill.py <name> --path .claude/skills`

**Tip:** Use `CLAUDE.local.md` (gitignored) for personal project-level notes. Use `@path/to/file` syntax in CLAUDE.md to import content from other files without bloating the main file.

## MCP Integration

MCP servers provide external tools that extend Claude Code. See `.claude/lib/mcp-guide.md` for configuration and usage.

## Hooks

10 hook events across 3 types. Hooks live in `global-config/hooks/`, installed globally to `~/.claude/hooks/`.

**Command hooks (9 scripts):**
- `session-start-healthcheck.sh` — SessionStart: fast-path framework health check, forks `install.sh --update` on drift
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

## Self-Healing

The framework reconciles its own deployed state. Two paths, one diagnostic stream.

**Fast path — SessionStart hook (`global-config/hooks/session-start-healthcheck.sh`):**
- Runs on every Claude Code session start, budget <2s
- Checks env keys in `~/.claude/settings.json` against template, hook script sha256 against source, analytics files present
- On drift: logs to `~/.claude/analytics/framework-health.jsonl` and forks `install.sh --update` in background
- Exit 0 always — never blocks session start

**Slow path — launchd watchdog (`global-config/daemon/claude-framework-watchdog.sh`):**
- Runs hourly via `com.claude-code-agents.framework-watchdog` LaunchAgent
- Hourly: `validate.sh --quick --json`, `git fsck` on repo (corruption → `watchdog-alerts.jsonl`)
- Daily: git bundle snapshot of repo, tarball of `~/.claude/hooks` + `settings.json`
- Retention: prunes snapshots older than 7 days
- Output: `~/.claude/analytics/watchdog.log`

**Snapshot restore (`~/.claude/snapshots/`):**
- Repo corruption: `git clone ~/.claude/snapshots/claude-code-agents-YYYYMMDD-HHMM.bundle recovered/`
- User config corruption: `tar -xzf ~/.claude/snapshots/userconfig-YYYYMMDD.tgz -C /`

**Diagnostic stream:** `~/.claude/analytics/framework-health.jsonl` — single source for drift events, validation output, snapshot activity. `~/.claude/analytics/watchdog-alerts.jsonl` for corruption alerts.

## Quick Start

Describe what you need naturally:

```
"I need to build a user registration system with email verification"
```

This triggers: architecture-planner → api-backend + database-architect → security-auditor → test-automation → documentation-maintainer
