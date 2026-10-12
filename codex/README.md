# Codex edition

The Claude runtime scripts are preserved; documentation and its instruction template
now describe both integrations. This adapter builds **39 Codex workflow skills**
(27 skills and 12 executable command templates) and **13 native custom agents** from
the repository, with handwritten replacements for platform-dependent behavior.
Each native specialist also has a role-guide skill fallback, giving **52 total skill
directories: 39 workflows + 13 specialist guides**.
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
block in `~/.codex/AGENTS.md`. Custom CODEX_HOME is currently rejected for user
installation; project installation is available. No shell aliases, daemons, model
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

Optional hooks:

```bash
./install-codex.sh --project /absolute/path/to/project --hooks
# Then open native /hooks and review/trust the exact definitions in Codex.
```

This adds `.codex/hooks.json` only if foreign configuration does not occupy that path.
Nine supported events produce an allowlisted metadata log in
`.codex/framework/events.jsonl`. SessionStart checks owned file hashes; direct patches
to protected credential paths are denied; PostToolUse prompts a quality gate. The
hook adapter handles add/update/delete/move destinations and symlink aliases. It is
**not a shell/MCP sandbox** and does not scan arbitrary command writes. Use native
sandbox/execpolicy for that boundary. There is no automatic lint rewrite, permission
auto-approval, full conversation snapshot, desktop notification or inferred cost.
Hooks are local-runtime features and may be unavailable in cloud orchestration. Updates
preserve an installed hook edition and require native re-review if definitions change.
Uninstall leaves runtime metadata and saved notes for the owner to retain or remove.

Validation:

```bash
python3 -m unittest discover -s tests/codex -v
python3 tests/codex/mutations.py
```

Tests use isolated temporary projects and simulated home layouts. They check real
inventory, YAML/TOML parsing, explicit invocation policy, resource execution, collision
and modification rejection, personal-file preservation, drift repair, symlink/traversal
rejection, rollback, native hook payloads and logging privacy. This is not an authenticated
end-to-end test across Codex desktop, IDE, CLI and cloud accounts.
When the Codex CLI is installed, a native prompt-input smoke test checks skill discovery
and managed instructions in an isolated home; otherwise that check is explicitly skipped.
CI runs the suite in a fresh virtual environment populated only from requirements.txt,
so undeclared resource dependencies cannot be hidden by the runner's installed packages.

Official references checked for this adaptation:

Actual laptop deployment and read-only cross-project/CLI tests are recorded in
[GLOBAL-VALIDATION.md](GLOBAL-VALIDATION.md). Maintenance rules are in `../AGENTS.md`
and architecture notes in `../MEMORY.md`.

- [Skill discovery and invocation](https://learn.chatgpt.com/docs/build-skills)
- [Native custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [Native hook contracts and trust](https://learn.chatgpt.com/docs/hooks)
- [Claude plugin migration](https://developers.openai.com/plugins/guides/submit-claude-plugin)
