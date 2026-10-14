# SDLC Agents — Claude Code and Codex

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-3.2.0-blue.svg)](https://github.com/pfangueiro/claude-code-agents/releases)
[![Claude Code](https://img.shields.io/badge/Claude_Code-Compatible-purple.svg)](https://code.claude.com/docs/en/overview)
[![Codex](https://img.shields.io/badge/Codex-Compatible-blue.svg)](codex/README.md)
[![Agents](https://img.shields.io/badge/Agents-13-orange.svg)](#available-agents)
[![Skills](https://img.shields.io/badge/Source_Skills-30-green.svg)](#skills-system)
[![MCP](https://img.shields.io/badge/MCP-4%20Servers-brightgreen.svg)](#-mcp-integration)

**One framework repository, with an integration for each coding agent.** Share domain
procedures and specialist roles; keep provider-specific runtime behavior in its adapter.
Describe a task naturally or select a workflow explicitly. Selection uses model judgment.

| | Claude Code | Codex |
|---|---|---|
| User-global install | `./install.sh` | `./install-codex.sh --user` |
| Skills | 30 source bundles | 42 workflows + 13 specialist guides = 55 bundles |
| Specialists | 13 Markdown agent definitions | 13 TOML definitions plus guide fallbacks |
| Instructions | `~/.claude/CLAUDE.md` and rules | Managed block in `~/.codex/AGENTS.md` and rules resource |
| Runtime integration | Existing hooks, dashboard, statusline and watchdog | Opt-in native evidence hooks; [remaining gaps](codex/FEATURES.md) |

**Requirements:** macOS/Linux, Bash and Git. Codex building/installing additionally
needs Python 3.11+ and [declared Python dependencies](codex/requirements.txt), including
PyYAML and Requests for the bundled health checker. Claude statusline/validation uses
`jq`; MCP examples use `npx` where applicable. MCP connections are not auto-registered.
See [INSTALL.md](INSTALL.md) for both installation paths and [codex/README.md](codex/README.md)
for Codex ownership, updates, rollback and hook trust.

---

## User-global setup

```bash
git clone https://github.com/pfangueiro/claude-code-agents.git
cd claude-code-agents
# Claude Code
./install.sh --dry-run
./install.sh

# Codex: use Python 3.11+ and this environment for installation/updates
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r codex/requirements.txt
./install-codex.sh --user --dry-run
./install-codex.sh --user
```

Install the integration you use, or both. Claude loads from `~/.claude`; Codex loads
skills from `~/.agents/skills` and definitions/state from `~/.codex`. No per-project
copy is required with the default user profile. Project instructions, disabled skills,
alternate profiles and host capabilities can affect effective behavior.

### Delivery workflow

Three portable skills carry an implementation outcome through review and publication in
either integration: `delivery` (task contract, roles, separately authorized states),
`repo-context` (read-only repository discovery) and `verified-handoff` (check receipts
bound to an exact commit). The `delivery` rule routes implementation work through them,
and the provider-neutral `commit-pr` command is the single publication contract for both
editions: commit, then required checks and an independent verdict on that exact
candidate, then confirmation that the pushed head is the reviewed one. Any new commit
invalidates the earlier verdict.

- **Availability is not execution.** Installing or loading these workflows changes what
  a session can follow; nothing is implemented, reviewed, merged or deployed until a real
  tool call or process does it and its receipt is collected. Receipts are evidence of a
  run, not proof of review, CI or deployment.
- **Default roles.** The rule assigns a default pair: a coordinator that verifies
  independently and a separate implementing execution. Explicit owner or project
  instructions override that pair; the default never starts a dispatcher.
- **Project policy.** Base branch, required checks, review, release and attribution
  come from the project's own instructions. Project rules and owner instructions act as
  the policy adapter; the workflows do not assume a default branch, CI gate or ticket key.
- **Nothing runs in the background.** No watcher, daemon, scheduler, auto-merge, hook or
  hook trust is added. Gates are instructions plus receipts the session collects, not an
  enforced sandbox.

Codex receives them through `./install-codex.sh --user` as `$sdlc-delivery`,
`$sdlc-repo-context` and `$sdlc-verified-handoff` (implicit) and `$sdlc-commit-pr`
(explicit-only). For an existing Claude install, update just these resources without
rerunning the broad installer:

```bash
python3 scripts/install-delivery.py --dry-run   # report paths, change nothing
python3 scripts/install-delivery.py             # install or update
python3 scripts/install-delivery.py --check     # nonzero if installed bytes drift
python3 scripts/install-delivery.py --uninstall # remove owned files, restore adopted originals
```

It targets `CLAUDE_CONFIG_DIR` when set, otherwise `~/.claude`; pass `--claude-home` to
choose another existing profile deliberately. It manages only `skills/delivery`,
`skills/repo-context`, `skills/verified-handoff`, `rules/delivery.md` and
`commands/commit-pr.md`, records per-file hashes and the source commit in
`.sdlc-delivery/manifest.json`, and never touches settings, hooks, credentials, models,
`CLAUDE.md` or daemons. Installed bytes come from the Git objects of the source `HEAD`
commit, not the working tree. A managed path that differs from `HEAD`, carries an
assume-unchanged or skip-worktree flag, or has an untracked or ignored file beside it
(Python caches aside) marks the source dirty: `--dry-run` reports it and installation
refuses. Symlinked source resources and committed symlinks or submodules are refused in
every mode; source inspection runs no fsmonitor, filter or hook. Foreign or customized
files and symlinked destinations are refused before writing. A `commit-pr.md` copied by
an earlier full install is adopted only with `--baseline <full commit SHA>` whose
shipped bytes match it exactly; uninstall then restores those original bytes. Caught
write errors roll back; a process kill or power loss mid-write is not guaranteed to. A
later `./install.sh --update` may rewrite the same files; `--check` then reports drift
and the delivery installer refuses to overwrite or remove the changed bytes.

Open a session in a project and describe the work:

```
"Build a REST API with JWT authentication"
"This query is running slow"
"Check for security vulnerabilities"
"Deploy to production"
```

Codex examples include `$sdlc-execute`, `$sdlc-review-pr` and `$sdlc-agent-code-quality`.
Native profile routing depends on the host; guides provide a fallback.
[Cross-project and CLI validation](codex/GLOBAL-VALIDATION.md) confirmed global
discovery and reviewer use for both integrations.

> **Before you run it:** see [What the install does to your machine](#what-the-install-does-to-your-machine) for the exact
> paths written, the background daemon, and how to reverse it. `./install.sh --dry-run` prints every
> path it would touch without touching any of them.

---

## Claude edition components

| Component | Count | What It Does |
|-----------|-------|--------------|
| **Agents** | 13 | Auto-activating SDLC specialists (planning through production) |
| **Skills** | 30 | Modular knowledge packages (git, Docker, CI/CD, K8s, SRE, IaC, observability, delivery, repo-context, verified-handoff, experiment-loop, scheduled-tasks, worktree-workflow, remote-triggers, context-escalation, diverge, etc.) |
| **Command templates** | 12 | `/commit-pr`, `/review-pr`, `/compact`, `/new-feature`, `/create-jira`, `/build-fix`, `/tdd`, `/quality-gate`, `/checkpoint`, `/save-session`, `/resume-session`, `/optimize`; `/security-scan` comes from a skill |
| **MCP Servers** | 4 | context7, sequential-thinking, playwright, github |
| **Rules** | 7 | Instructions for security, code quality, fix quality, verification, framework integrity, anti-anchoring and delivery routing; native permissions/sandbox enforce access boundaries |
| **Hooks** | 10 | Agent tracking, session lifecycle, permission auditing, file protection, auto-lint, debug detection, pre-compact snapshots, notifications |

---

## Available Agents

| Agent | Activates On | Does What | Model |
|-------|-------------|-----------|-------|
| **architecture-planner** | "design", "architecture", "system" | System design, API specs, ADRs | Sonnet |
| **code-quality** | "review", "refactor", "quality" | Code review, best practices | Sonnet |
| **security-auditor** | "security", "auth", "vulnerability" | OWASP scanning, security fixes | **Opus** |
| **test-automation** | "test", "coverage", "TDD" | Test generation, coverage analysis | Sonnet |
| **performance-optimizer** | "slow", "optimize", "bottleneck" | Profiling, caching, optimization | Sonnet |
| **devops-automation** | "deploy", "CI/CD", "Docker" | Deployment, containerization | Sonnet |
| **documentation-maintainer** | "document", "README", "guide" | Docs, API specs | **Haiku** |
| **database-architect** | "database", "SQL", "schema" | Query optimization, migrations | Sonnet |
| **frontend-specialist** | "UI", "React", "frontend" | Components, responsive design | Sonnet |
| **api-backend** | "API", "backend", "endpoint" | REST/GraphQL, business logic | Sonnet |
| **incident-commander** | "CRITICAL", "outage", "emergency" | Rapid response, root cause | **Opus** |
| **sre-specialist** | "SLO", "reliability", "on-call", "runbook" | SRE, SLOs, capacity, chaos eng | Sonnet |
| **meta-agent** | "create an agent for..." | Generates new custom agents | Opus |

The model column describes the Claude source files. Codex inherits its active model;
these aliases and provider pricing are not translated.

---

## How Agents Collaborate

Agents hand off work automatically. Example: *"Build a user registration system"*

```mermaid
graph LR
    A[architecture-planner] --> B[frontend-specialist]
    A --> C[api-backend]
    C --> D[database-architect]
    B --> E[test-automation]
    C --> E
    E --> F[code-quality]
    F --> G[security-auditor]
    G --> H[devops-automation]
```

See [`.claude/lib/agent-coordination.md`](.claude/lib/agent-coordination.md) for the formal handoff protocol.

---

## Installation

The following commands and machine effects describe the **Claude installer**.
For Codex use `./install-codex.sh --user`, then `--user --check` to verify or repeat
`--user` to update. Removal is `--user --uninstall`; customized owned files cause a
conflict rather than being overwritten. [Full Codex instructions](codex/README.md).

| Command | What It Does |
|---------|-------------|
| `./install.sh` | Install everything to `~/.claude`: agents, skills, commands, rules, hooks, statusline, analytics, global config |
| `./install.sh --dry-run` | Print every path the install would touch — changes nothing |
| `./install.sh --update` | Reconcile an existing install to the latest version |
| `./install.sh --upgrade` | Migrate from an old per-project install: reconcile, confirm + tear down old copies, then self-verify ([details](./INSTALL.md#upgrading-from-the-old-per-project-framework)) |
| `./install.sh --uninstall` | Remove the framework from `~/.claude` — snapshots first, asks first ([details](./INSTALL.md#uninstallation)) |
| `./install.sh --help` | Show all options |

### Verify Installation

```bash
./validate.sh
# All validations passed! (full + --quick modes)

# Codex installed state (use the installation's Python environment)
./install-codex.sh --user --check
```

Installed components live under `~/.claude/` — verify with `ls ~/.claude/agents ~/.claude/skills ~/.claude/commands ~/.claude/rules`.

---

## What the install does to your machine

`./install.sh` writes to your home directory and installs a background daemon. Here is all of it.
Run `./install.sh --dry-run` first to see the same list resolved against your actual `$HOME`.

### Paths written

| Path | What lands there | On re-install |
|---|---|---|
| `~/.claude/agents/` | 13 agent `.md` files | Replaced (heals drift) |
| `~/.claude/skills/` | 30 skill directories | Replaced per-skill (`rm -rf` then copy) |
| `~/.claude/commands/` | 12 executable templates + README (13 Markdown files) | Replaced |
| `~/.claude/rules/` | 7 rule `.md` files | Replaced |
| `~/.claude/lib/` | 4 reference files (templates, patterns, coordination, MCP guide) | Replaced |
| `~/.claude/hooks/` | 9 hook `.sh` scripts (+`chmod +x`) and 2 reference `.json` configs | Replaced; orphans pruned |
| `~/.claude/output-styles/concise.md` | Code-first output style | Written on first install |
| `~/.claude/statusline.sh` | Status bar script | Replaced only when it differs from source |
| `~/.claude/analytics/` | `collector.py`, `server.py`, `dashboard.html`, `schema.sql` | Replaced |
| `~/.claude/daemon/` | Watchdog script (**macOS only**) | Replaced |
| `~/.claude/settings.json` | Seeded from template if absent; otherwise only framework-owned keys are reconciled — see below | Merged, never wholesale-replaced |
| `~/.claude/CLAUDE.md` | Personal preferences, from template, with your name/email from `git config` | **Only if absent.** Never touched again, including by `--update` |
| `~/.claude/.framework-path`<br>`~/.claude/.framework-version`<br>`~/.claude/.watchdog-plist.sha` | Markers the self-heal paths read | Rewritten |

Written **outside** `~/.claude`:

| Path | Why | Notes |
|---|---|---|
| `~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist` | The hourly self-heal daemon | **macOS only** |
| `~/.zshrc` or `~/.bashrc` | Appends a `claude-obs` alias for the dashboard (3 lines) | Idempotent — guarded by a `grep`, added once |

Created later at runtime, not by the installer: `~/.claude/analytics/*.jsonl` and `claude-obs.db`
(hooks and the collector), `~/.claude/snapshots/` (the daemon), `~/.claude/sessions/`
(pre-compact auto-snapshots, 10 kept per project).

**In `settings.json`, only these keys are framework-owned:** `.hooks` (replaced per event on drift),
`.permissions`, `.attribution`, and `.statusLine` (replaced on drift), plus `.env` (**add-only** —
your values are never overwritten). Every other key you set is left alone. Want different
permissions or attribution? Put them in `settings.local.json`, which takes precedence.

### It is framework-scoped — your own content survives

The install **never** deletes or overwrites a name the framework does not ship. Personal skills,
agents, commands, and rules in `~/.claude` are preserved on every install and every `--update`; the
orphan-prune is only ever *eligible* to remove names the framework itself ships or has explicitly
retired, so a personal entry is not merely spared — it is never a candidate.

Measured, not assumed: with a personal skill, agent, command and rule planted in a throwaway
`HOME`, two consecutive `--update` runs left all four **byte-identical** and the skills directory at
27 framework + 1 personal. A working machine here carries 14 personal skills alongside the
framework's 27; all 41 are present. (Measured when the framework shipped 27 skills.)

### The background daemon

On **macOS**, the install registers an hourly `launchd` agent
(`com.claude-code-agents.framework-watchdog`, `StartInterval 3600`). Each cycle it runs
`validate.sh --quick`, forks `install.sh --update` if it finds drift, `git fsck`s the repo, and
writes daily snapshots to `~/.claude/snapshots/` with 7-day retention. It makes **no network
requests**.

```bash
launchctl list | grep claude-code-agents            # is it running?
tail -f ~/.claude/analytics/watchdog.log            # what did it do?
launchctl bootout gui/$(id -u)/com.claude-code-agents.framework-watchdog   # stop it
```

Full operational detail: **[SELF-HEALING.md](./SELF-HEALING.md)**.

### Platform contract

| | macOS | Linux / WSL |
|---|---|---|
| Agents, skills, commands, rules, lib | Yes | Yes |
| Hooks, statusline, settings reconcile | Yes | Yes |
| Observability dashboard | Yes | Yes |
| SessionStart self-heal hook | Yes | Yes |
| **Hourly watchdog daemon** | **Yes** | **No** — the daemon is Darwin-gated and silently skipped |
| Daily snapshots + retention | Yes | **No** — produced by the watchdog |

On Linux and WSL, drift is still detected and healed, but **only at session start**. There is no
out-of-band recovery, so the one failure the watchdog exists to catch — an external wholesale
rewrite of `~/.claude/settings.json` that drops the `.hooks` block, which disables the SessionStart
hook itself — is not self-recoverable there. Run `./install.sh --update` by hand if the statusline
or hooks disappear.

### Reversing it

```bash
./install.sh --dry-run     # preview every path, change nothing
./install.sh --uninstall   # remove the framework (asks first, snapshots first)
```

`--dry-run` and `--uninstall` read the **same source-derived enumeration** of framework-owned paths,
so the preview cannot drift from the removal.

`--uninstall` asks for confirmation at your terminal, writes a full `~/.claude` tarball to
`~/.claude/snapshots/preuninstall-<UTC>.tgz` and **aborts if that snapshot fails**, unloads and
removes the launchd plist, deletes the framework's own files, and surgically strips the framework's
hook bindings and `statusLine` out of `settings.json` — leaving `settings.json.pre-uninstall.bak`
beside it. It keeps your own skills, agents and commands, your `CLAUDE.md`, `projects/`, `todos/`,
telemetry, and snapshots. It prints the restore command on the way out.

Do **not** `rm -rf ~/.claude`: that directory also holds your own Claude Code data. Snapshot restore
commands: [SELF-HEALING.md](./SELF-HEALING.md#snapshot-restore-claudesnapshots).

Threat model, reporting, and the repo's security posture: **[SECURITY.md](./SECURITY.md)**.

---

## Slash Commands

### Project Workflow

| Command | Usage | What It Does |
|---------|-------|-------------|
| `/commit-pr` | `/commit-pr [message]` | Commit, run required checks and an independent review on that exact commit, then push and open the PR; merge, release and ticket updates only when authorized |
| `/review-pr` | `/review-pr 123` | Code quality + security + testing review |
| `/security-scan` | `/security-scan [path]` | OWASP scanning, secrets detection, dependency audit |
| `/compact` | `/compact [note]` | Write HANDOFF.md with session context, then compact conversation |
| `/new-feature` | `/new-feature PROJ-123 desc` | Create feature branch from latest main |
| `/create-jira` | `/create-jira epic Title` | Create JIRA issue and assign to you |

### Developer Workflow (new in v2.5.0)

| Command | Usage | What It Does |
|---------|-------|-------------|
| `/build-fix` | `/build-fix [path]` | Auto-detect build system, fix errors one at a time with regression guard |
| `/tdd` | `/tdd <feature>` | Enforce RED-GREEN-REFACTOR: failing test → implement → refactor |
| `/quality-gate` | `/quality-gate [path] [--fix]` | Pre-commit validation: formatter + linter + type checker + tests |
| `/checkpoint` | `/checkpoint <name>` | Named save points via git branches for complex multi-step work |
| `/save-session` | `/save-session [id]` | Save structured session state with mandatory "What Did NOT Work" section |
| `/resume-session` | `/resume-session [id]` | Resume from a saved session with context briefing and file state verification |
| `/optimize` | `/optimize <metric> [--iterations N]` | Autonomous metric-driven improvement loop: measure → improve → keep/revert |

---

## Skills System

Skills provide domain knowledge that agents apply. 30 included:

| Skill | What It Provides |
|-------|-----------------|
| **git-workflow** | Branching strategies, conventional commits, PR workflows |
| **code-review-checklist** | 10-category review framework, security checklist |
| **deployment-runbook** | Blue-green deployment, rollback procedures, health checks |
| **api-contract-testing** | OpenAPI validation, PACT testing, mock servers |
| **ui-guidelines** | React/Next.js patterns, Ant Design, responsive design |
| **ci-cd-templates** | GitHub Actions, GitLab CI, deployment strategies |
| **docker-deployment** | Multi-stage builds, Docker Compose, security |
| **execute** | Orchestrated task engine: decompose goals, plan dependencies, parallel execution |
| **investigate** | 8-phase root cause analysis: observe, reproduce, trace, hypothesize, prove, fix, prevent |
| **library-docs** | MCP-powered: fetch docs for React, Next.js, Vue, etc. |
| **deep-analysis** | MCP-powered: structured reasoning with branching and revision (rewritten) |
| **diverge** | Divergent ideation: isolated parallel sub-agents + critic pass; the divergent complement to deep-analysis |
| **deep-read** | 6-phase codebase reading engine: scope, map, trace, deep read, connect, report |
| **handoff** | Session continuity — write HANDOFF.md for cross-session context |
| **context-escalation** | Five-level context-pressure policy: truncate → drop-reads → fork-subagent → /compact → handoff |
| **security-scan** | Auto-activating security scanner (secrets, OWASP, dependencies, file permissions) |
| **kubernetes-ops** | K8s manifests, Helm, Karpenter, GitOps (ArgoCD/Flux), network policies, troubleshooting |
| **observability-stack** | OpenTelemetry, Prometheus/Grafana, RED/USE metrics, SLI/SLO monitoring, alerting |
| **sre-runbooks** | On-call handbook, postmortem templates, SLO/error budgets, chaos engineering, capacity planning |
| **infrastructure-as-code** | Terraform/CDK/Pulumi patterns, IaC testing pyramid, CI/CD for infra, state management |
| **experiment-loop** | Autonomous experimentation pattern: modify → measure → keep/discard (autoresearch-inspired) |
| **scheduled-tasks** | CronCreate/CronDelete/CronList for recurring prompts, polling, reminders |
| **worktree-workflow** | Git worktree isolation via EnterWorktree/ExitWorktree — explicit-request-only, session-scoped, single-instance (not a parallelism mechanism) |
| **remote-triggers** | RemoteTrigger API for cross-session automation, scheduled agents |
| **browser-testing** | E2E testing with Playwright MCP — visual regression, responsive design, codegen |
| **multi-agent-orchestration** | Coordinator pattern, teams, background agents, worker restrictions, SendMessage |
| **skill-creator** | Create your own custom skills |
| **delivery** | Provider-neutral delivery: outcome contract, implementer/verifier roles, receipts, separately authorized review/publish/merge/deploy states |
| **repo-context** | Read-only repository discovery: Git root, HEAD, dirty state, instructions, manifests and command candidates as data |
| **verified-handoff** | Run checks into receipts bound to an exact commit and verify a declared check manifest before claiming results |

### Create Your Own Skill

```bash
python3 .claude/skills/skill-creator/scripts/init_skill.py my-skill --path .claude/skills
```

---

## MCP Integration

4 Model Context Protocol servers, provided as an example config (`.mcp.json.example`) — install does **not** register them; add the ones you want to Claude Code with the commands below:

| Server | What It Does |
|--------|-------------|
| **context7** | Fetch documentation for 100+ libraries on-demand |
| **sequential-thinking** | Deep structured reasoning (31,999 thinking tokens) |
| **playwright** | Browser automation and E2E testing |
| **github** | PR/issue management via GitHub API |

### Manual MCP Setup

```bash
claude mcp add context7 -- npx @upstash/context7-mcp@latest
claude mcp add sequential-thinking-server -- npx @modelcontextprotocol/server-sequential-thinking
claude mcp add playwright -- npx @executeautomation/playwright-mcp-server
claude mcp add github -- npx -y @modelcontextprotocol/server-github
```

---

## Auto-Enforced Rules

Seven rule files in `~/.claude/rules/` are automatically loaded by Claude Code in every session:

- **security.md** — No secrets in commits, parameterized queries, input validation, security headers, least privilege
- **code-quality.md** — No dead code, single responsibility, early returns, explicit error handling, descriptive naming
- **fix-quality.md** — Root cause analysis before fixing, never suppress errors, minimal changes, test-driven fixing
- **verification.md** — Verify after every implementation, run tests, build to catch errors, test-driven bug fixes
- **framework-integrity.md** — Hooks must enforce invariants, state reconciles automatically, snapshots have documented restore paths
- **anti-anchoring.md** — Name the obvious pick + a non-obvious alternative + a trap on open-ended judgment calls; escalate consequential open decisions to `/diverge`
- **delivery.md** — Route implementation outcomes through `/delivery` with a default role pair that owner or project instructions override; report states only from receipts

---

## Hooks

10 hook events across 9 command hooks, installed globally to `~/.claude/hooks/`:

| Hook | Event | What It Does |
|------|-------|-------------|
| **session-start-healthcheck.sh** | SessionStart | Fast-path framework drift check (<2s); forks `install.sh --update` on drift |
| **file-protection.sh** | PreToolUse | Blocks edits to sensitive files (.env, *.key, *.pem, secrets/) |
| **post-edit-lint.sh** | PostToolUse | Auto-lints TS/JS after Write/Edit, warns on debug statements |
| **notify.sh** | Notification | Desktop alert when Claude needs attention |
| **agent-tracker.sh** | SubagentStart/Stop | Real-time agent lifecycle tracking to analytics |
| **session-end.sh** | SessionEnd | Logs session completion for observability |
| **smart-guard.sh** | PermissionRequest | Auto-approves safe reads, audits dangerous operations |
| **pre-compact.sh** | PreCompact | Auto-saves session snapshot before context compaction |
| **post-compact.sh** | PostCompact | Verifies session snapshot was saved after compaction |

**Phase 2 reference configs** (opt-in, not enabled by default):
- `smart-file-guard.json` — prompt hook: LLM-based file protection
- `pre-commit-review.json` — agent hook: automated code review before commit

---

## Architecture

Installed once, user-global under `~/.claude/` — Claude Code loads it in every project:

```
~/.claude/
├── agents/          # 13 auto-activating SDLC agents
├── commands/        # 12 executable templates + README
├── skills/          # 30 modular knowledge packages
├── rules/           # 7 auto-enforced rule sets
├── lib/             # Templates, patterns, coordination protocol
├── hooks/           # 9 command hooks + 2 reference configs
├── daemon/          # launchd watchdog (hourly validate + snapshots) — macOS only
├── analytics/       # Observability dashboard + ingested session logs
├── snapshots/       # Daily repo/config/memory snapshots (written by the daemon)
├── sessions/        # Pre-compact auto-snapshots (written by the PreCompact hook)
├── statusline.sh    # Rich status bar — ends line 1 with a framework-status glyph (✓ healthy / ⟳ self-healing / ⚠ stalled-or-degraded)
└── settings.json    # 10 hook events, permissions, model config
```

Plus one file outside `~/.claude` on macOS —
`~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist` — and a `claude-obs` alias
appended once to your shell rc. See [What the install does to your machine](#what-the-install-does-to-your-machine).

See [EXTENSIBILITY.md](./EXTENSIBILITY.md) for the complete guide on Skills, MCP, Slash Commands, and Subagents.

---

## Usage Examples

**Building a feature:**
```
You: "Build a shopping cart with Stripe integration"
  → architecture-planner designs the system
  → api-backend implements payment logic
  → database-architect creates order schema
  → security-auditor validates payment security
  → test-automation generates tests
  → documentation-maintainer documents the API
```

**Performance issue:**
```
You: "The product search is running really slow"
  → performance-optimizer profiles the code
  → database-architect optimizes queries
  → code-quality suggests improvements
```

**Production emergency:**
```
You: "CRITICAL: Production API is returning 500 errors!"
  → incident-commander takes charge (Opus)
  → security-auditor checks for breaches
  → devops-automation prepares rollback
```

---

## Observability Dashboard

Built-in analytics dashboard that reads Claude Code's native JSONL session logs — zero cloud dependencies, Python stdlib only, single SQLite database.

```bash
# Quick start (after install)
claude-obs

# Or run manually
python3 ~/.claude/analytics/collector.py    # Ingest JSONL → SQLite
python3 ~/.claude/analytics/server.py --open # Serve dashboard at localhost:3141
```

**Dashboard panels:**
- **Summary cards** — total cost, projects, sessions, agent activations, input/output tokens
- **Daily cost & sessions** — dual-axis bar+line chart with configurable time ranges (7d/14d/30d/All)
- **Cost by project** — horizontal bar chart ranking projects by spend
- **Agent activations** — which agents are used most and across how many projects
- **Model distribution** — doughnut chart showing Opus/Sonnet/Haiku cost split
- **Top projects by tokens** — token consumption per project
- **Sessions table** — recent sessions with project, duration, cost, model, and agents used

**Architecture:**
- **Data source**: `~/.claude/projects/**/*.jsonl` (Claude Code writes these automatically)
- **Collector** (`collector.py`): incremental JSONL scanner with per-file watermarks, per-model cost estimation (Opus/Sonnet/Haiku pricing)
- **Storage**: SQLite with WAL mode at `~/.claude/analytics/claude-obs.db`
- **Server** (`server.py`): 6 JSON API endpoints + static file server on `localhost:3141`
- **Dashboard** (`dashboard.html`): single-file dark-themed UI with Chart.js

**What it reads, and where the data goes.** The collector reads Claude Code's own session
transcripts — `~/.claude/projects/**/*.jsonl`, **across every project on the machine**, not just this
one — plus the three JSONL streams the framework's hooks write (`agent-events.jsonl`,
`session-summaries.jsonl`, `permission-audit.jsonl`). Those transcripts contain your prompts and
Claude's responses, so the SQLite database derived from them is as sensitive as your session history.

It **stays local**. `collector.py` makes no network calls of any kind; `server.py` binds
`127.0.0.1:3141` — loopback only, not reachable from your network — and nothing is uploaded,
phoned home, or shared. Both are Python stdlib only, with no third-party dependencies. Delete
`~/.claude/analytics/claude-obs.db` at any time; the next `claude-obs` run rebuilds it.

**CLI options:**
```bash
python3 collector.py --full          # Re-ingest everything (ignore watermarks)
python3 collector.py --db /path/to.db # Custom database path
python3 server.py --port 8080        # Custom port
python3 server.py --open             # Auto-open browser
```

Installed automatically by `./install.sh`. Data stays entirely local.

---

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/my-feature`)
3. Run `./validate.sh` to verify everything passes
4. Commit your changes (`git commit -m 'feat: add my feature'`)
5. Push and open a Pull Request

Read **[docs/FAILURE-MODES.md](./docs/FAILURE-MODES.md)** before adding any check, guard, or fix —
it is the taxonomy of the nine defect classes that actually shipped here, with the real examples.
Full flow and the two hard rules: **[CONTRIBUTING.md](./CONTRIBUTING.md)**.

---

## Roadmap

- [ ] VS Code extension
- [x] Observability dashboard
- [x] Lifecycle hooks (agent tracking, permission auditing, session lifecycle)
- [ ] Additional specialized agents
- [ ] Multi-language support
- [ ] Team collaboration features
- [ ] Custom agent marketplace

---

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- [GitHub Issues](https://github.com/pfangueiro/claude-code-agents/issues)
- [GitHub Discussions](https://github.com/pfangueiro/claude-code-agents/discussions)
- Update: `./install.sh --update`

---

<div align="center">

**No configuration. No commands. Just describe what you need.**


</div>
