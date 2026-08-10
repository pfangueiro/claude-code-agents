# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Claude Agents** — enterprise AI agent system with 13 specialized SDLC/SSDLC agents, 27 skills, and 13 slash commands that auto-activate based on natural language. Automatically selects optimal Claude model (Haiku/Sonnet/Opus) per task complexity.

## Git & Commit Conventions

These apply to everyone committing to this repo. They live here in the repo (not only in a personal `~/.claude/CLAUDE.md`), so every contributor honors them:

- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`; add a scope when it clarifies (`fix(install):`, `feat(validate):`).
- **No AI-attribution trailers** — do NOT add `Co-Authored-By:` or any assistant/AI trailer. Commits are authored solely by the maintainer.
- **Never force-push `main`; never amend or skip hooks** unless explicitly asked.
- **CHANGELOG in the same change**: add the SHA-cited bullet when you commit the change (the recurring audit gap).

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
- **`/diverge <decision>`** — Divergent ideation: isolated parallel sub-agents under cognitive frames, then a critic pass scores/flags-traps/deepens. The divergent complement to `/deep-analysis`; gated by consequence × openness.

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
**Automation skills:** scheduled-tasks (CronCreate), worktree-workflow (EnterWorktree), remote-triggers (RemoteTrigger), multi-agent-orchestration (SendMessage/agent teams)
**Testing skills:** browser-testing (Playwright MCP for E2E, visual regression), api-contract-testing (OpenAPI / JSON Schema / contract-first)
**UI skills:** ui-guidelines (React/Next.js + Ant Design + shadcn patterns, spacing / typography / color system)
**Infra skills:** docker-deployment (multi-stage builds, prod configs), ci-cd-templates (GitHub Actions / GitLab CI)
**Session skills:** handoff (HANDOFF.md creation for session continuity before /compact), context-escalation (explicit-level policy for context management: truncate → drop-redundant-reads → fork-subagent → /compact → handoff)
**MCP-powered skills:** library-docs (context7), deep-analysis (sequential-thinking)
**Divergence skills:** diverge (isolated parallel ideation under cognitive frames + critic pass; the divergent complement to deep-analysis, gated by consequence × openness)

Creating skills: `python3 .claude/skills/skill-creator/scripts/init_skill.py <name> --path .claude/skills`

**Tip:** Use `CLAUDE.local.md` (gitignored) for personal project-level notes. Use `@path/to/file` syntax in CLAUDE.md to import content from other files without bloating the main file.

## MCP Integration

MCP servers provide external tools that extend Claude Code. See `.claude/lib/mcp-guide.md` for configuration and usage. The framework ships **4 MCP servers** — context7, sequential-thinking, playwright, and github (the deprecated `@modelcontextprotocol/server-postgres` was removed, 5→4).

## Hooks

10 hook events across 3 types. Hooks live in `global-config/hooks/`, installed globally to `~/.claude/hooks/`.

**Command hooks (9 scripts):**
- `session-start-healthcheck.sh` — SessionStart: fast-path framework health check, forks `install.sh --update` on drift
- `file-protection.sh` — PreToolUse: blocks edits to sensitive files (.env, *.key, *.pem)
- `post-edit-lint.sh` — PostToolUse: auto-lints TS/JS after Write/Edit, warns on debug statements
- `notify.sh` — Notification: desktop alerts when Claude needs attention
- `agent-tracker.sh` — SubagentStart/SubagentStop: real-time agent lifecycle tracking to `agent-events.jsonl`
- `session-end.sh` — SessionEnd: logs session completion to `session-summaries.jsonl`
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

The framework auto-reconciles its user-global install at `~/.claude` — nothing to run by hand. **Full runbook: [SELF-HEALING.md](./SELF-HEALING.md)** — read it before any framework-infra change.

- **Two paths:** the SessionStart hook (`session-start-healthcheck.sh`, <2s, forks `install.sh --update` on drift) and the hourly launchd watchdog (`claude-framework-watchdog.sh`). Only the watchdog survives a CLI settings-sync wipe of `~/.claude/settings.json`, so it — not the hook — is what actually recovers a `.hooks`/`.statusLine` wipe.
- **Diagnostics:** `~/.claude/analytics/framework-health.jsonl` (drift/heal events; capped by the watchdog every cycle) and `watchdog-alerts.jsonl` (corruption).
- **Statusline:** a `⚙<version>` glyph at the end of line 1 — ✓ healthy / ⟳ self-healing / ⚠ degraded; recovers after a resolved incident.
- **Snapshots + restore** live in `~/.claude/snapshots/` — repo `.bundle`, `userconfig-*.tgz`, and project-memory `memory-latest.tgz` (list a memory snapshot with `tar -tzvf ~/.claude/snapshots/memory-latest.tgz` before restoring under `-C ~/.claude`; full restore commands in SELF-HEALING.md).
- **Install modes:** bare | `--update` | `--upgrade` | `--migrate-legacy` | `--help`.
- **Enforced by `validate.sh`:** doc-accuracy (counts vs prose), live `.attribution` empty, statusline deployed==source, watchdog log-cap present, and the memory restore path documented.

## Reasoning Effort

- **Persistent default: `xhigh`** — set via `CLAUDE_CODE_EFFORT_LEVEL` in `~/.claude/settings.json` `env` (the framework template ships `xhigh`). Valid persistent tiers: `low | medium | high | xhigh`. validate.sh + the SessionStart healthcheck reject any other value (drift → heal).
- **Session-only (NOT persistable — by Anthropic design):**
  - `max` — deeper single-context reasoning: run `/effort max` in a session. Invalid as an env value (silently ineffective if set there).
  - `ultracode` — `xhigh` + standing multi-agent **workflow** orchestration: run `/effort ultracode`, or include the keyword `ultracode` in a prompt. Resets when the session ends.
  - **Workflows have no persistent "on" switch** — they are gated behind explicit per-request opt-in (`ultracode`, the keyword, or asking for a workflow). Only `disableWorkflows: true` / `CLAUDE_CODE_DISABLE_WORKFLOWS=1` persist (to turn them OFF). So "ultracode + workflows by default" = `xhigh` persistent baseline + `/effort ultracode` per session when you want the fleet.

## Quick Start

Describe what you need naturally:

```
"I need to build a user registration system with email verification"
```

This triggers: architecture-planner → api-backend + database-architect → security-auditor → test-automation → documentation-maintainer
