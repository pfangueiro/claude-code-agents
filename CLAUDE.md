# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Claude Agents** — enterprise AI agent system with 13 specialized SDLC/SSDLC agents, 28 skills, and 13 slash commands that auto-activate based on natural language. Automatically selects optimal Claude model (Haiku/Sonnet/Opus) per task complexity.

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
**API skills:** api-guidelines (Next.js/TypeScript secure endpoint patterns)
**UI skills:** ui-guidelines (React/Next.js + Ant Design + shadcn patterns, spacing / typography / color system)
**Infra skills:** docker-deployment (multi-stage builds, prod configs), ci-cd-templates (GitHub Actions / GitLab CI / CircleCI)
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

The framework reconciles its own user-global install at `~/.claude` (the single install that serves every project). Two paths, one diagnostic stream.

**Fast path — SessionStart hook (`global-config/hooks/session-start-healthcheck.sh`):**
- Runs on every Claude Code session start, budget <2s
- Checks env keys in `~/.claude/settings.json` against template, hook script sha256 against source, the shared set (agents/skills/commands/rules) sha256 against source (Check 7), analytics files present
- On drift: logs to `~/.claude/analytics/framework-health.jsonl` and forks `install.sh --update` in background
- Exit 0 always — never blocks session start

**Slow path — launchd watchdog (`global-config/daemon/claude-framework-watchdog.sh`):**
- Runs hourly via `com.claude-code-agents.framework-watchdog` LaunchAgent
- Hourly: `validate.sh --quick --json`, `git fsck` on repo (corruption → `watchdog-alerts.jsonl`)
- Daily: git bundle snapshot of repo, tarball of `~/.claude/hooks` + `settings.json`, separate tarball of project memory (`~/.claude/projects/*/memory`)
- Retention: prunes snapshots older than 7 days (memory snapshots keep a floor of the newest 3 regardless of age)
- Output: `~/.claude/analytics/watchdog.log`

**Snapshot restore (`~/.claude/snapshots/`):**
- Repo corruption: `git clone ~/.claude/snapshots/claude-code-agents-YYYYMMDD-HHMM.bundle recovered/`
- User config corruption: `tar -xzf ~/.claude/snapshots/userconfig-YYYYMMDD.tgz -C /`
- Project memory (`~/.claude/projects/<slug>/memory/*.md`): archives use paths relative to `~/.claude` and restore with `-C ~/.claude` (never `-C /`), so they can only write under `projects/*/memory`. **List before restoring.**
  - List a snapshot: `tar -tzvf ~/.claude/snapshots/memory-latest.tgz`
  - One project (common case): `tar -xzf ~/.claude/snapshots/memory-latest.tgz -C ~/.claude projects/<slug>/memory`
  - Compare backup vs current before clobbering: `tar -xzOf ~/.claude/snapshots/memory-latest.tgz projects/<slug>/memory/MEMORY.md | diff - ~/.claude/projects/<slug>/memory/MEMORY.md`
  - All memory (fresh machine / mass loss): `tar -xzf ~/.claude/snapshots/memory-latest.tgz -C ~/.claude`

**Known external cause — CLI settings-sync hooks wipe:** Claude Code's own settings-sync (`tengu_enable_settings_sync_push`) does a *wholesale replace* of `~/.claude/settings.json` (CLI `src/services/settingsSync/index.ts:519`, no merge, change-detection suppressed). When settings-sync is enabled across machines, a sync cycle can pull a payload lacking the framework's `.hooks` block and overwrite it to `{}` — with no install.sh involvement and no drift event at write time. This is external CLI behavior, not an install bug. Defense is detect-and-heal on TWO independent triggers: (1) the SessionStart `hook_wiring`/`statusline_wiring` checks re-run `install.sh --update` on the next session — but the SessionStart hook itself lives in the wiped `.hooks`, so it cannot recover the wipe that removed it; (2) the launchd watchdog, which runs independently of `~/.claude/settings.json` and therefore SURVIVES the wipe, parses `validate.sh --quick --json` and on `errors>0` runs `install.sh --update` itself (Task 1) — this is the trigger that actually recovers a `.hooks` wipe, logging `heal_triggered`/`heal_succeeded` to `framework-health.jsonl`. install.sh's settings writes are hardened via `_atomic_settings_jq` (unique mktemp temp file + non-empty + valid-JSON guards) so the framework's own reconcile can never contribute to a wipe. On install / `--update`, `settings.json` `.attribution` also AUTO-HEALS (scrubs a stale `Co-Authored-By` commit trailer to `""` and restores the template PR footer, replace-on-drift like `.permissions`); `validate.sh --quick` now also checks the LIVE `~/.claude/settings.json` `.attribution.commit` (the old check only guarded the source template, so a failed/absent heal was invisible). This is the config-layer enforcement behind the "No AI-attribution trailers" convention above; a user wanting a custom PR footer edits `settings.local.json` (higher precedence).

**Autonomous cross-system migration (opt-in):** for the AUTONOMOUS path, a `git pull` on any machine is the only manual trigger — the next SessionStart healthcheck / watchdog forks `install.sh --update`, which reconciles `~/.claude` AND (only if `~/.claude/.framework-autonomy` sets `LEGACY_PROJECTS_DIR`) tears down old per-project `.claude` copies there. That teardown is framework-scoped, untracked-only (never rewrites a repo's history), snapshot-first, skips committed repos, and idempotent. The committed-guard requires ALL five framework subdirs (agents/skills/commands/rules/lib) to be git-untracked before any teardown (previously agents-only — a repo that committed `.claude/rules/<framework-name>.md` could have had TRACKED files removed), plus symlink guards. No marker → no teardown; there is deliberately **no auto-pull**.

**Manual one-command migration — `install.sh --upgrade`:** distinct from the marker-driven autonomous teardown, `cd ~/.claude-code-agents && ./install.sh --upgrade` reconciles `~/.claude`, detects old per-project `.claude` copies, prints a COUNT + candidate LIST, and asks ONE confirmation at the controlling terminal (a dedicated fd bound to `/dev/tty`, never stdin) — or `--yes` / `CLAUDE_UPGRADE_ASSUME_YES=1`. Snapshot-first, framework-scoped teardown, then self-verifies with `validate.sh --quick` (observe-only, never `--heal`). No tty + no explicit consent → fail-closed SKIP (exit 0) with a re-run one-liner. Checkout-local only; `curl|bash` cannot pass it. Bare install / `--update` / `--migrate-legacy` stay byte-identical. **Install modes:** bare | `--update` | `--upgrade` | `--migrate-legacy` | `--help`.

**Statusline framework-status:** `statusline.sh` renders a compact `⚙<version> <glyph>` segment at the end of line 1 — ✓ healthy / ⟳ self-healing / ⚠ (watchdog stalled >150 min | heal_failed | recent corruption). It reads only `~/.claude/.framework-version` and `~/.claude/analytics/{framework-health.jsonl,watchdog-alerts.jsonl}`, NEVER runs validate in the hot path, caches 60s, and emits nothing when the framework isn't installed. `validate.sh` asserts the segment exists AND that deployed `~/.claude/statusline.sh` == source; install kickstarts the watchdog, stamps a fresh `install_reconciled` health event, and drops the 60s cache after a reload so there is no transient ⚠ post-install. Timestamps are parsed as UTC (`date -j -u -f` on macOS) — a prior local-time parse produced a false ⚠ on non-UTC machines.

**Diagnostic stream:** `~/.claude/analytics/framework-health.jsonl` — single source for drift events, validation output, snapshot activity. `~/.claude/analytics/watchdog-alerts.jsonl` for corruption alerts.

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
