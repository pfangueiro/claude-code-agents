# Codex multi-agent orchestration

Use the collaboration tools that are actually exposed, after confirming delegation
is authorized. Custom specialists are standalone TOML files in `.codex/agents/`
or `~/.codex/agents/`; a description guides selection, not deterministic keyword routing.
If this host does not expose native custom types, use the sdlc-agent-<name> skill
as an inline role procedure or as the task instructions of an authorized generic worker.
This fallback does not enforce a native profile's sandbox or tool policy.

- Define the DAG and each task's input SHA, outputs, write scope and acceptance checks.
- Batch independent research; synthesize and independently verify reports before coding.
- Spawn with the actual host schema. CLI `spawn_agent`/`send_input`/`wait_agent`
  and hosted `collaboration.*` are different APIs; discover names and arguments.
- Do not send Claude `subagent_type`, `run_in_background`, `team_name`, `isolation`
  or model aliases to Codex. Available context-sharing and model controls depend on
  the host. Give fresh reviewers only raw evidence and the acceptance criteria.
- Workers share the filesystem. Prepare disjoint Git worktrees for parallel writes
  and pass their absolute paths to workers. Tool restrictions need supported sandbox
  or server policy; a sentence in an agent prompt is not an access-control boundary.
- Wait using the native completion mechanism; handle user steering and report progress.
- Maintain dependencies using a plan tool or an explicit task ledger. Claude's shared
  task-list persistence and implicit team lifecycle are not assumed.
- Reconcile changes sequentially, then run integration checks at the resulting SHA.

Inherit the selected model by default. Security and incident work needs careful
verification and suitable capabilities, not an untranslated `opus` setting.
