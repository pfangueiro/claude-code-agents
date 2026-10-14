# Compatibility and independent audit

Audited Claude baseline: `509d282a195cc7a0e3b4d63b51b5f791be519eed`.
Official capability documentation researched 2026-10-12. The initial audit input is
recorded above; [publication review](PUBLICATION-REVIEW.md) identifies the implementation
commit. Install manifests record checkout HEAD at install time and owned output hashes.
Do not describe this as complete runtime parity.

| Framework surface | Codex treatment | Verification or limit |
|---|---|---|
| 30 skills | 30 namespaced SKILL.md bundles | YAML parsed; resources retained; runtime procedures rewritten |
| Commands | 12 additional skills | README excluded; actual inventory is 42 total workflows; 3 explicit-only |
| 13 agents | Native standalone TOML | name/description/developer_instructions; model inherited; code-quality read-only sandbox |
| Specialist fallback | 13 additional role-guide skills | Apply inline or give procedure to generic worker when native roles are unavailable; no native sandbox enforcement claim |
| Agent auto-selection | Descriptions guide Codex | Model judgment; not deterministic keyword routing |
| Seven rules | Managed AGENTS guidance + rules resource | Instruction hierarchy respected; not enforced sandbox policy |
| Delivery workflow | Exported delivery, repo-context and verified-handoff skills; AGENTS routing | Exported scripts executed in tests; procedures and receipts, not an enforced gate; no watcher, daemon or auto-merge |
| Task DAG / teams | Plan/ledger and actual collaboration APIs | Claude Task/implicit-team persistence not assumed |
| Background/fork behavior | Host schema discovery | No automatic context fork or Claude background defaults |
| Parallel coding | Separate Git worktrees | Coupled steps sequential; no fake launcher isolation parameter |
| Model tiers/effort | Inherit active Codex config | No Opus/Sonnet/Haiku mapping or hardcoded pricing |
| Four MCPs | Disabled TOML examples | Availability/schema/account checked at use; nothing auto-connected |
| Deep analysis | Optional Sequential Thinking workflow | Actual tool discovery, local evidence fallback disclosed |
| Browser testing / Context7 | Preserved MCP-specific domain procedures | Example schema depends on installed server; no MCP assumed available |
| Scheduling | Available host scheduler or honest unsupported result | No Claude Cron/session-limit emulation; no schedule created merely by installing |
| Remote triggers | Available remote tool / requested codex exec | No Claude cloud routine API or credentials assumption |
| Handoff / save / resume | Markdown notes with SHA/state verification | Native transcript/compaction managed by Codex |
| Install/update/check/uninstall | Hash ownership, preflight, lock, atomic files, rollback | No overwrite of customized files; process-kill rollback not guaranteed |
| Hook events | Nine opt-in native command events | Definitions require native trust; cloud orchestration differs |
| Sensitive file hook | Direct-patch add/update/delete/move guard | Does not constrain arbitrary shell/MCP writes |
| Permission auditing | Metadata event log | No automatic approval or credential/command logging |
| Agent/session lifecycle | Actual event identifiers | No fabricated duration/status/token/cost fields |
| Post-edit quality | Quality-gate reminder | Automatic linting/rewrite remains unported |
| Compaction hooks | Lifecycle evidence | Automatic git/conversation snapshots remain unported |
| Prompt/agent hook handlers | Not installed | Current Codex parses but skips these handler types |
| Desktop notifications | Unported | Claude Notification event absent from current supported list |
| Custom statusline / output styles | Unported runtime UI | Claude executable input protocol differs; no status config changed |
| Claude dashboard/cost collector | Unported | Claude JSONL schema/pricing cannot be reused for Codex |
| Auto-heal/watchdog/snapshot retention | Unported | Drift check and explicit repair only; no background daemon installed |
| Validation/CI | Separate Codex acceptance/mutation job | Existing Claude suite remains independent |

Each skill is accounted for:

| Treatment | Skills |
|---|---|
| Domain workflow/resource adaptation | api-contract-testing, browser-testing, ci-cd-templates, code-review-checklist, delivery, deployment-runbook, docker-deployment, experiment-loop, git-workflow, handoff, infrastructure-as-code, kubernetes-ops, library-docs, observability-stack, repo-context, security-scan, sre-runbooks, ui-guidelines, verified-handoff |
| Handwritten Codex runtime procedure | context-escalation, deep-analysis, deep-read, diverge, execute, investigate, multi-agent-orchestration, remote-triggers, scheduled-tasks, skill-creator, worktree-workflow |

All command templates: build-fix, checkpoint, commit-pr, compact, create-jira,
new-feature, optimize, quality-gate, resume-session, review-pr, save-session, tdd.
Review-PR, Jira, branching, compact and session commands receive explicit portability
rewrites. Commit/PR is exported from the provider-neutral canonical command, so both
editions share one publication contract; it and the other five retain domain steps with
invocation/path adaptation.

All agents: api-backend, architecture-planner, code-quality, database-architect,
devops-automation, documentation-maintainer, frontend-specialist, incident-commander,
meta-agent, performance-optimizer, security-auditor, sre-specialist, test-automation.
Meta-agent is rewritten so future generated agents use Codex TOML, not Claude Markdown.

Independent reviewers reproduced these baseline defects before implementation:

- `global-config/hooks/file-protection.sh:8` reads only file_path/filePath. A dummy
  Claude Edit targeting .env exits 2; a Codex apply_patch targeting .env exits 0.
  `post-edit-lint.sh:7` has the same payload mismatch. The Codex edition uses a new parser.
- `install.sh:365` deletes a same-named skill before copying. `install.sh:844` prunes
  foreign hook basenames and `install.sh:893` replaces whole event arrays. The Codex
  edition never invokes that installer and rejects foreign collisions.
- `observability/collector.py:350` expects Claude sessionId/message.usage fields.
  At `:120`, unknown models fall back to Claude pricing. The collector is not installed
  or represented as valid Codex telemetry.
- `.claude/commands/commit-pr.md:63` says not to wait for CI before merging, and `:35`
  injects an assistant footer contrary to repository attribution instructions. The
  Codex rewrite honored exact-head checks, selected scope and owner conventions. (Baseline
  finding; the canonical command was later rewritten provider-neutral and the Codex
  override removed.)

The existing Claude edition's defects are recorded here and preserved outside this
adaptation's write scope. Passing new adapter tests does not certify those mechanisms.

Dependency-safe follow-up for complete runtime coverage: first implement a versioned
Codex telemetry/event adapter with no inferred pricing; then add notification/status
integrations supported by each host; finally design explicitly authorized snapshots
and reconciliation that preserves ownership, hook trust and user customizations. Each
needs independent behavior tests at the resulting exact SHA before a parity claim.
