# Codex edition

The Claude runtime scripts are preserved; documentation and its instruction template
now describe both integrations. This adapter builds **42 Codex workflow skills**
(30 skills and 12 executable command templates) and **13 native custom agents** from
the repository, with handwritten replacements for platform-dependent behavior.
Each native specialist also has a role-guide skill fallback, giving **55 total skill
directories: 42 workflows + 13 specialist guides**. 52 are implicitly invocable;
commit-pr, create-jira and new-feature stay explicit-only.
It provides workflow portability, not complete Claude runtime parity. See
[FEATURES.md](FEATURES.md) for every feature and remaining limitation.

Requirements: Python 3.11+, PyYAML 6.0.3 and Requests 2.34.2 (for the bundled health
checker). Use the same Python environment for
installation, updates and checks. A local environment avoids changing system Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r codex/requirements.txt
```

Native custom-agent support depends on the installed Codex version. Schema guidance
was checked against current official documentation; local CLI inspected: 0.162.1.

```bash
# Preview without writing anything (including no logs/lock).
./install-codex.sh --project /absolute/path/to/project --dry-run

# Install into one project. Existing config.toml/auth/MCP settings are untouched.
./install-codex.sh --project /absolute/path/to/project

# Alternatively install into default user discovery locations.
./install-codex.sh --user --dry-run
./install-codex.sh --user

# Inspect integrity, update, or remove only the adapter's unmodified owned files.
./install-codex.sh --project /absolute/path/to/project --check
./install-codex.sh --project /absolute/path/to/project
./install-codex.sh --project /absolute/path/to/project --uninstall
```

Project installs write `.agents/skills/sdlc-*`, `.codex/agents/*.toml`,
`.codex/framework/*`, and one managed block in `AGENTS.md`. User installs use
`~/.agents/skills/sdlc-*`, `~/.codex/agents`, `~/.codex/framework`, and a managed
block in `~/.codex/AGENTS.md`. A custom `CODEX_HOME` other than `~/.codex` is rejected
for user installation because its discovery layout is not verified; use the default
home, or `--project` for an explicit project install. No shell aliases, daemons, model
settings, credential changes, approval changes or hook trust are installed.

Files with foreign ownership, user modifications, ambiguous instruction markers or
symlink destinations cause a nonzero failure before target file writes. Updates and
uninstall preserve unrelated files and instruction content. An install lock detects
concurrent installers; an abandoned lock must be investigated rather than deleted
automatically. File writes are atomic and caught I/O failures roll back; a process
kill/power loss is not guaranteed to roll back a multi-file transaction. `--check`
reports missing/drifting output nonzero. Reinstall repairs missing owned files but
refuses to overwrite customized files. No unattended self-healing is claimed.

Invoke `$sdlc-execute`, `$sdlc-deep-read`, `$sdlc-review-pr` or `$sdlc-tdd`, or
describe the task naturally. The `sdlc-` prefix avoids names colliding with Codex
system skills. The original explicit-only policy is preserved for commit-pr,
create-jira and new-feature. Skills do not automatically fork, and model judgment
does not guarantee activation. Assign native specialists only when the host exposes
their agent types. Agent models inherit the active configuration; Claude model names
and cost assumptions are not converted into arbitrary OpenAI defaults.
If custom agent types are unavailable, load `$sdlc-agent-code-quality` (or the
appropriate guide) inline or pass it to an authorized generic worker. Role-guide
text does not enforce the native profile's sandbox. Local CLI prompt inspection
verified implicit skill discovery and exclusion of explicit-only commands; native
custom-role routing was not exposed by that host and is not claimed as verified.

Delivery: `$sdlc-delivery`, `$sdlc-repo-context` and `$sdlc-verified-handoff` are
exported from the shared portable skills with their scripts, and the managed AGENTS.md
block routes implementation outcomes through `$sdlc-delivery` with a default role pair
that explicit owner or project instructions override. `$sdlc-commit-pr` is now built
from the provider-neutral `.claude/commands/commit-pr.md`; no Codex-only override
remains, so both editions export one publication contract (commit, exact-candidate
checks and independent verdict, current-head confirmation, then authorized publication).
These are workflow procedures: loading one runs nothing, and no watcher, daemon,
auto-merge, scheduler or hook trust is added. Project instructions supply the base
branch, required checks and release policy.

The command adaptation fixes unsafe product assumptions: use the configured default
branch/Jira project, preserve the owner's attribution and authentication choice, and
verify required CI at the exact PR head before an authorized merge/release. Loading
a workflow does not authorize every external effect it describes.

MCP examples are in the installed `.codex/framework/mcp.example.toml` and source
[mcp.example.toml](mcp.example.toml). Entries are **disabled**. Review and merge only
the needed entries into trusted Codex configuration, verify package versions and
credentials, and inspect connected tool schemas. The installer does not download or
activate MCPs. Browser examples target ExecuteAutomation's Playwright server; other
servers can expose different APIs. Most domain examples are carried from the Claude
edition and are not an audit of every underlying library/version.

Status line (opt-in): Claude's custom statusline renderer reads Claude-specific JSON
on stdin and is not ported. Codex's terminal footer uses built-in item IDs instead;
the installed `.codex/framework/statusline.example.toml` lists, in priority order,
thread title, model with reasoning, context remaining, used tokens, five-hour and
weekly limits, Git branch, current directory, context window size, total input and
output tokens and Codex version. Token items are native session counters (used tokens
is the session total and is omitted while zero); unavailable values are omitted and
trailing items clip on narrow terminals, so not every item shows at every width. Use
`/statusline` to reorder or toggle items. Merge only its
`status_line` field into your existing `[tui]` table (do not add a second `[tui]`
and keep your other settings), or choose items live with `/statusline`; start a new
terminal session if the footer does not refresh. The installer never edits
`config.toml`. The managed instructions ask the model, when the host exposes a native
task-title rename capability, to title only the current task `SDLC | <short task>`
without replacing an owner-chosen title; this is model judgment, not a guaranteed
native event, and hosts without that capability keep their normal title. The marker
means framework guidance was loaded, not that checks, review or delivery passed.
Claude's health, duration and cost status output remains unported; no persistent
custom desktop status bar is claimed.

Optional hooks:

```bash
./install-codex.sh --project /absolute/path/to/project --hooks
# Then open native /hooks and review/trust the exact definitions in Codex.
```

This adds `.codex/hooks.json` only if foreign configuration does not occupy that path.
Nine supported events produce an allowlisted metadata log in
`.codex/framework/events.jsonl`. SessionStart checks owned file hashes; direct patches
to protected credential paths are denied; PostToolUse emits a quality-gate reminder or,
when a project has opted in, runs an approved post-edit lint (below). The
hook adapter handles add/update/delete/move destinations and symlink aliases. It is
**not a shell/MCP sandbox** and does not scan arbitrary command writes. Use native
sandbox/execpolicy for that boundary. There is no automatic lint *rewrite* (`--fix` is
never added), permission auto-approval, full conversation snapshot, desktop notification
or inferred cost. Hooks are local-runtime features and may be unavailable in cloud
orchestration. Updates preserve an installed hook edition and require native re-review if
definitions change. Uninstall leaves runtime metadata and saved notes for the owner to
retain or remove.

Opt-in post-edit lint (disabled until you create the registry):

- The installer ships `.codex/framework/lint.py` beside the hook but **never creates or
  trusts** the registry. Approval always comes from the single owner-global
  `~/.codex/framework/lint-projects.json`, for both user and project installs; a
  project-local registry is never consulted, so a repository cannot carry its own
  execution approval. Until the owner-global registry exists, a recognized-successful
  supported PostToolUse edit (`apply_patch`, `Write`, `Edit`) only produces the
  quality-gate reminder; non-edit events never run a command.
- A command runs only on a recognized positive edit result — the canonical apply_patch
  success text or a structured `{"success": true}`. An explicitly failed edit runs
  nothing and emits no feedback at all (no lint, no reminder). An unknown, missing or
  unrecognized result also runs nothing, but falls back to a manual quality-gate reminder
  that states no lint ran and does not assert the edit succeeded.
- Format: a JSON object with `version` `1` and a `projects` array; each project has an
  absolute canonical `root`, a `command` argv whose first element is an absolute
  executable, and an optional `timeout` in seconds (`1`–`30`, default `10`). The single
  owner-global `~/.codex/framework/lint-projects.json` approves projects for both user and
  project installs — there is no project-local registry. A copyable example:

  ```json
  {
    "version": 1,
    "projects": [
      {
        "root": "/home/you/project",
        "command": ["/usr/local/bin/npm", "run", "lint"],
        "timeout": 10
      }
    ]
  }
  ```

  The registry must be a regular file you own, without group/world write and with no
  symlink at it or any ancestor. A malformed, duplicate, unknown-version, unsafe,
  symlinked or unreadable registry runs nothing and returns a static notice.
- A lint runs only when the event's canonical cwd exactly equals an approved `root`.
  Approval starts at that root: a nested working directory under it is **not**
  automatically approved, and there is no ancestor matching or command autodetection.
- The approved argv runs directly (`shell=False`, no filename or template interpolation),
  with cwd set to the approved root and stdin/stdout/stderr discarded, inside its own
  POSIX process group. A timeout, or a leader that exits while background processes it
  started are still running, is reported as timed-out/incomplete — **never** as a pass —
  and the group is signalled `SIGTERM` then `SIGKILL` within a bounded grace. Cleanup is
  best effort and makes no containment promise: a process that escapes the group is not
  sandboxed, so the feedback claims only that a stop was signalled. The PostToolUse event
  timeout (40 s) exceeds the maximum child plus cleanup budget.
- A user-selected command trusts that project's own code and dependencies; it is **not**
  sandboxed or read-only. No argv, output, environment or patch content appears in the
  hook output or the evidence log — only a static status and the process exit code. A
  failure, timeout or incomplete run reports the status (and exit code on a plain failure)
  and states the edit was applied and not rolled back; it never claims the edit was
  reverted, and incomplete work is never reported as passed.

Validation:

```bash
python3 -m unittest discover -s tests/codex -v
python3 tests/codex/mutations.py
```

`unittest discover -s tests/codex` also loads every test in
`tests/delivery/test_resources.py` through a bridge module and runs the incremental
Claude delivery installer suite. Tests use isolated temporary projects and simulated
home layouts. They check real inventory, execution of the exported delivery scripts, YAML/TOML parsing, explicit invocation policy, resource execution, collision
and modification rejection, personal-file preservation, drift repair, symlink/traversal
rejection, rollback, native hook payloads and logging privacy. They also cover the
opt-in post-edit lint (the owner-global-only registry, recognized-success-only execution,
enabled/disabled, unapproved and nested roots, unsafe/malformed/symlinked/non-owned/
writable registries, literal shell metacharacters, failure privacy, timeout with a
grandchild, incomplete work from an early-exiting leader reported as not-passed, and
installed stdio operation) and the read-only `scripts/framework-status.py`
(not-installed/clean/drift/error states, requested-vs-installed scope mismatch,
before/after trees proving it writes nothing — including no source bytecode, and
JSON/exit-code shape). This is not an
authenticated end-to-end test across Codex desktop, IDE, CLI and cloud accounts.
When the Codex CLI is installed, a native prompt-input smoke test checks skill discovery
and managed instructions in an isolated home; otherwise that check is explicitly skipped.
CI runs the suite in a fresh virtual environment populated only from requirements.txt,
so undeclared resource dependencies cannot be hidden by the runner's installed packages.

Official references checked for this adaptation:

The 2026-10-12 laptop deployment and read-only cross-project/CLI tests are recorded in the
archived [GLOBAL-VALIDATION.md](../docs/archive/codex-2026-10-12/GLOBAL-VALIDATION.md) (a historical
snapshot, not a current check). Maintenance rules are in `../AGENTS.md` and architecture notes in
`../MEMORY.md`.

- [Skill discovery and invocation](https://learn.chatgpt.com/docs/build-skills)
- [Native custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [Native hook contracts and trust](https://learn.chatgpt.com/docs/hooks)
- [Claude plugin migration](https://developers.openai.com/plugins/guides/submit-claude-plugin)
