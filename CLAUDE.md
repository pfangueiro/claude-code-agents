# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**SDLC framework** — one repository with Claude Code and Codex integrations. The Claude
edition has 13 specialized SDLC/SSDLC agents, 30 skills, and 12 executable command
templates (13 command-directory Markdown files include README.md). Agent descriptions
guide model judgment; Claude files specify Haiku/Sonnet/Opus roles.

Read [AGENTS.md](AGENTS.md) for cross-engine maintenance rules and [MEMORY.md](MEMORY.md)
for architecture and verified state. Codex builds from shared domain sources plus
`codex/overrides/`: 42 workflows, 13 specialist guides and 13 native TOML definitions
(55 skill bundles: 51 implicit, 4 explicit-only). It inherits the active Codex model and
permission policy. User-global installation is
`./install-codex.sh --user`; check with `--user --check`. See [codex/FEATURES.md](codex/FEATURES.md).

## Git & Commit Conventions

These apply to everyone committing to this repo. They live here in the repo (not only in a personal `~/.claude/CLAUDE.md`), so every contributor honors them:

- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`; add a scope when it clarifies (`fix(install):`, `feat(validate):`).
- **No AI-attribution trailers** — do NOT add `Co-Authored-By:` or any assistant/AI trailer. Commits are authored solely by the maintainer.
- **Never force-push `main`; never amend or skip hooks** unless explicitly asked.
- **CHANGELOG in the same change**: add the SHA-cited bullet when you commit the change (the recurring audit gap).

## Selection (Model Judgment)

Describe the task naturally or select the specialist explicitly. Descriptions guide
model judgment; selection/delegation are not a deterministic keyword router. Codex
may use `sdlc-agent-<name>` guides when native custom types are unavailable.

## Quality and Delivery Contract

Both editions share this contract. The canonical procedures are the verification and
code-quality rules, the `code-quality` agent, `code-review-checklist`, `/review-pr`,
`/quality-gate` and `delivery` (with `references/acceptance-by-task.md`).

- Findings are concrete and evidence-classed: runtime-reproduced, source-proven, unverified
  hypothesis or nonblocking suggestion. Do not use grades or unmeasured metrics.
- A review names the exact base and head SHA it covered. A check receipt records the exact
  checked input SHA, not a base (a source-only receipt records no SHA). A new commit
  invalidates both.
- Outcomes are PASS, FAIL or INCOMPLETE for the declared scope. A required check that did not
  run is INCOMPLETE, never PASS. Unknown is not zero.
- Acceptance follows the task type in `acceptance-by-task.md`.
- Default maintenance roles: Codex coordinates and independently verifies, and an actual Claude
  execution implements. Existing explicit owner or project instructions that set other roles
  still apply, with no extra confirmation step. Implement, review, merge, deploy and
  release are separately authorized states, and each is reported from evidence.

## Agents

| Agent | Typical cues (not triggers) | Model |
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
- **`/checkpoint <name> [--verify] [--list] [--diff]`** — Named save points captured as `refs/checkpoint/<name>` snapshots with Git plumbing (not branches); your branch, index, worktree and stashes stay untouched and recovery is explicit.
- **`/save-session [id]`** — Save structured session state with mandatory "What Did NOT Work" section.
- **`/resume-session [id]`** — Resume from a saved session with full context briefing and file state verification.
- **`/optimize <metric> [--iterations N]`** — Autonomous metric-driven improvement loop: measure → improve → verify → keep/revert.

## Host Tools (Discover at Runtime)

Depending on the Claude Code version, settings and permissions, the host may expose tools
such as these. Check what the current session actually offers before relying on one. This
framework neither installs nor guarantees them:

| Tool | Use When |
|------|----------|
| **TaskCreate/TaskUpdate/TaskList** | Multi-step work — structured task tracking with dependencies and progress |
| **CronCreate/CronDelete/CronList** | Recurring prompts, polling, reminders (session-scoped, 7-day max) |
| **EnterWorktree/ExitWorktree** | ONLY when the user (or CLAUDE.md/memory) explicitly says "worktree" — "fix this bug"/"build this feature" is not a trigger. Session-scoped and single-instance, so **not** a parallel-development or per-task mechanism; for per-agent repo isolation use the `Agent` tool's `isolation: "worktree"` parameter instead |
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
- `session-start-healthcheck.sh` — SessionStart: observe-only fast-path drift check; logs findings and reports that explicit `install.sh --update` is needed (never forks an installer)
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

## Testing the Guards

Codex validation is separate: `python3 -m unittest discover -s tests/codex -v` and
`python3 tests/codex/mutations.py`. Tests use disposable projects/homes and include
native discovery when the CLI is installed. Keep both checks green at the publish SHA;
never use `--heal` as an acceptance gate.

`validate.sh`'s guards are themselves proven by an executable mutation suite: `bash tests/gap/run.sh`
injects a real defect for each guard, asserts `validate.sh` FAILS with the expected message, and
includes a baseline plus a negative control. It runs on every push (`gap-tests` job) — a guard whose
mutation is not caught fails CI. Read [docs/FAILURE-MODES.md](./docs/FAILURE-MODES.md) before adding
a guard; the two hard rules are that every guard must be gap-tested, and a fix without a guard is
incomplete.

## Observability

Optional dashboard aggregating Claude Code JSONL session logs across all projects. Source in `observability/`; installed to `~/.claude/analytics/` only with `./install.sh --with-analytics` (default-off). Run `claude-obs` to collect data and open the dashboard. The collector never runs itself; hook-generated events (`agent-events.jsonl`, `permission-audit.jsonl`, `session-summaries.jsonl`) are ingested when the analytics hooks are installed.

## Security-First

**CRITICAL:** security-auditor and incident-commander ALWAYS use Opus. Security considerations are embedded in every agent following OWASP guidelines and DevSecOps best practices.

## Health observation & explicit repair

This section applies to **Claude**. Codex uses hash ownership and explicit integrity/
repair operations; no background self-healing or hook-trust bypass is installed.

The framework's background checks are **observe-only**: they report drift and keep
backups, but never install, migrate, reseed or repair. Repair is always an explicit,
foreground `./install.sh --update` the owner runs. **Full runbook:
[SELF-HEALING.md](./SELF-HEALING.md)** — read it before any framework-infra change.

- **Two observers (neither repairs):** the SessionStart hook (`session-start-healthcheck.sh`) logs drift and reports that an explicit `install.sh --update` is required; the optional hourly launchd watchdog (`claude-framework-watchdog.sh`, installed only with `--with-watchdog`, macOS) runs `validate.sh --quick --json` (no `--heal`), keeps snapshots and caps logs. Neither forks an installer or rewrites config.
- **Diagnostics:** `~/.claude/analytics/framework-health.jsonl` (drift findings, action `manual_repair_required`; capped by the watchdog every cycle) and `watchdog-alerts.jsonl` (corruption/backup alerts).
- **Statusline:** a `⚙<version>` glyph at the end of line 1 — `✓` only on a recent *admitted* `validation_result` from the watchdog's `validate.sh --quick --json` run (complete, healthy, zero errors), `⚠` on current drift / failed validation / recent corruption, `?` when there is no admitted evidence yet (a version marker alone is not proof). Here `complete` means the QUICK installed-integrity scope finished (deployed hooks/env/shared-set/wiring under `~/.claude`); `--quick` exits before the full-only source checks, so `✓` attests that completed watchdog quick installed-integrity scope ONLY — it does NOT certify the default full `validate.sh` repository validator, the project test suites, or CI. There is no self-healing glyph and no automatic green certification.
- **Snapshots + restore** live in `~/.claude/snapshots/` (written by the watchdog, when installed) — repo `.bundle`, `userconfig-*.tgz`, and project-memory `memory-latest.tgz` (list a memory snapshot with `tar -tzvf ~/.claude/snapshots/memory-latest.tgz` before restoring under `-C ~/.claude`; full restore commands in SELF-HEALING.md).
- **Install modes:** bare | `--update` | `--upgrade` | `--migrate-legacy` | `--help`; optional components are opt-in via `--with-watchdog` / `--with-analytics` / `--with-notifications` (default-off).
- **Enforced by `validate.sh`:** doc-accuracy (counts vs prose), live `.attribution` empty, statusline deployed==source and honest-health (no revived self-healing display), the heal-retired/observe-only regression guards, watchdog log-cap present, and the memory restore path documented.

## Reasoning Effort

- **Persistent default: `xhigh`** — `CLAUDE_CODE_EFFORT_LEVEL` in `~/.claude/settings.json` `env` (the framework template seeds `xhigh` on a fresh install only). Supported env values are `low | medium | high | xhigh | max | auto` (per the [model-config docs](https://code.claude.com/docs/en/model-config)). `.env` reconcile is **add-only**: an existing owner value among the supported set is preserved and never overwritten, and an unsupported value is reported and left unchanged. The SessionStart healthcheck only *reports* an unsupported value (`action: manual_repair_required`); it never heals or rewrites it.
- **Session vs setting:** `/effort <level>` changes the effort for the current session; the `settings.json` value is the persistent setting. `max` and `auto` are valid in both.
- **Ultracode** (standing multi-agent **workflow** orchestration) is a separate toggle, **independent of** the effort level and persistable in its own right since Claude Code 2.1.284. Enable it for a session with `/effort ultracode` (or the `ultracode` keyword, or by asking for a workflow), or persist it via its own setting. This framework ships neither an effort default change nor an ultracode enablement — it does not turn the feature on for you.

## Quick Start

Describe what you need naturally:

```
"I need to build a user registration system with email verification"
```

The model may route this through specialists such as architecture-planner → api-backend +
database-architect → security-auditor → test-automation → documentation-maintainer. That
path is model judgment, not a fixed pipeline. Name a specialist or workflow explicitly when
you need a specific one.
