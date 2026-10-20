# Installation — Claude Code and Codex

Both integrations are user-global by default and apply across projects for that user.
Choose one or install both from the same checkout; their runtime directories are separate.
Project instructions and alternate profiles can change effective behavior.

## Codex user-global installation

Use Python 3.11+ and the same Python environment for later updates/checks:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r codex/requirements.txt
./install-codex.sh --user --dry-run
./install-codex.sh --user
./install-codex.sh --user --check
```

Writes 55 skill bundles (42 workflows + 13 specialist guides) to `~/.agents/skills`,
13 specialist TOML definitions to `~/.codex/agents`, resources/ownership metadata to
`~/.codex/framework`, and a managed block in `~/.codex/AGENTS.md`. Existing config.toml, auth, MCP settings and personal
instruction content are preserved. User installation currently requires default CODEX_HOME.

| Operation | Codex command |
|---|---|
| Update after pulling source | `./install-codex.sh --user` |
| Check owned output/instruction state | `./install-codex.sh --user --check` |
| Remove unmodified owned output | `./install-codex.sh --user --uninstall` |
| Optional local evidence hooks | `./install-codex.sh --user --hooks`, then native `/hooks` review/trust |
| Explicit project-scoped alternative | `./install-codex.sh --project /absolute/path/to/project` |
| Read-only cross-integration status | `python3 scripts/framework-status.py [--json] [--project PATH] [--claude-home PATH]` |

Foreign/modified files, ambiguous instruction blocks and symlink destinations fail closed.
Updates do not silently heal owner customizations. MCP examples are disabled and hooks
are optional; installation does not activate either or bypass native trust. There is no
Codex watchdog/dashboard/statusline/snapshot parity claim. See [codex/README.md](codex/README.md),
[feature coverage](codex/FEATURES.md) and the archived [global validation](docs/archive/codex-2026-10-12/GLOBAL-VALIDATION.md).

`scripts/framework-status.py` reads the framework's own ownership manifests, the owned
files the existing `--check` logic compares, and the `~/.claude/.framework-version` marker
to report the repository SHA, each integration's installed source SHA and owned-integrity
state (`not_installed`/`clean`/`drift`/`error`), native CLI presence, whether optional
Codex hooks are configured (trust reported `UNKNOWN` — grant it in native `/hooks`) and
MCP connectivity (`UNKNOWN` — runtime discovery). It reports the source SHA of its own
repository, ignoring inherited Git selectors (`GIT_DIR`, `GIT_WORK_TREE`, …) so a foreign
repository in the environment cannot misattribute it, and it honors the requested scope —
`--project` against a user-scope install (or the reverse) is reported as an `error`, never
silently relabelled clean. It writes nothing — not even a Python `.pyc` into the source
tree — takes no lock, repairs nothing and never runs the broad installer, `validate.sh`, a
project script, the network or an MCP server, and it does not read `config.toml`,
`auth.json`, `settings.json` or secrets. Exit status is `0` (clean or not installed), `1`
(drift) or `2` (error). The Codex integrity check additionally needs the declared Codex
Python dependencies.

If the optional Codex hooks are installed, PostToolUse can run an **opt-in, user-approved**
post-edit lint. The installer ships the runner but never creates or trusts the registry;
approval always comes from the single owner-global `~/.codex/framework/lint-projects.json`
(for both user and project installs — a project-local file is never consulted), which you
add yourself (`{"version": 1, "projects": [{"root": "<abs canonical dir>", "command":
["<abs exe>", …], "timeout": 1-30}]}`). It runs the approved command only on a
recognized-successful edit whose canonical cwd exactly matches an approved root (a nested
directory is not approved), directly without a shell or `--fix`, bounded by a timeout in
its own process group; the hook reports only a status and exit code, and a timeout or a
leader that leaves background work running is reported as incomplete, never as passed.
Until the owner-global registry exists, PostToolUse just reminds you to run the quality
gate.

The remainder describes the Claude installer and its existing runtime.

## Install (one command, user-global)

Clone the repo and run the installer:

```bash
git clone git@github.com:pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh
```

That's it. Everything installs **once**, user-global to `~/.claude`. Claude Code natively loads `~/.claude/{agents,skills,commands,rules}`, so every project on your machine gets the agents automatically — there is no per-project step.

The **core** install includes: agents, skills, commands, rules, core hooks, statusline, output styles, and global settings. The observability dashboard, the hourly macOS watchdog daemon and desktop notifications are **opt-in**, each behind a positive flag (`--with-analytics`, `--with-watchdog`, `--with-notifications`); a bare install adds none of them. MCP servers are **not** registered — that is a manual, machine-specific step (see [MCP](#mcp-servers-are-not-auto-installed)).

**Not sure what it will touch?** `./install.sh --dry-run` prints every path it would write, resolved against your actual `$HOME`, and changes nothing.

## Commands

| Command | What it does |
|---------|-------------|
| `./install.sh` | Install core components user-global to `~/.claude` |
| `./install.sh [--with-analytics] [--with-watchdog] [--with-notifications]` | Add opt-in components (dashboard + `claude-obs` alias; macOS watchdog; notify hook). Default-off; may accompany any mode or stand alone; omitting a flag on an existing install preserves that component. |
| `./install.sh --dry-run` | Print every path **this selection** would touch. Makes no changes. |
| `./install.sh --update` | Non-interactive foreground reconcile of an existing install (the explicit repair path). Replaces framework-owned files so drift heals; preserves your own content. |
| `./install.sh --upgrade` | One-command migration from the old per-project layout: reconcile `~/.claude`, then confirm + tear down old per-project copies (snapshot-first) and self-verify. Run from inside your checkout. See [Upgrading from the old per-project framework](#upgrading-from-the-old-per-project-framework) below. |
| `./install.sh --migrate-legacy` | Marker-gated teardown-only mode, run explicitly (the observe-only watchdog does **not** run it). |
| `./install.sh --uninstall` | Remove the framework's own components. See [Uninstallation](#uninstallation). |
| `./install.sh --help` | Show all options |

## What Gets Installed

Most of it lands under `~/.claude/` and is loaded by Claude Code in every project:

```
~/.claude/
├── agents/                # 13 specialized agents
├── commands/              # 12 executable templates + directory README
├── skills/                # 30 modular knowledge packages
├── rules/                 # 7 instruction sets; permissions/hooks are separate mechanisms
├── lib/                   # Templates, patterns, coordination protocol, MCP guide
├── hooks/                 # 6 core command hooks (+ analytics/notify hooks when selected) + 2 reference configs
├── daemon/                # launchd watchdog — opt-in (--with-watchdog), macOS only
├── analytics/             # Observability dashboard (claude-obs alias) — opt-in (--with-analytics)
├── output-styles/
│   └── concise.md         # Code-first output style
├── statusline.sh          # Rich status bar — line-1 framework-status glyph (⚙<version> + ✓/⚠/?; no self-healing glyph)
├── settings.json          # Model, env, permissions, hook events (core wired by default), statusline
├── CLAUDE.md              # Personal coding preferences (created only if absent)
├── .framework-path        # Marker: where this checkout lives, read by the observer and installer
├── .framework-version     # Marker: installed version + source SHA
└── .watchdog-plist.sha    # Marker: sha of the loaded daemon plist
```

### Exactly what each path gets, and what happens on re-install

| Path | Contents | Re-install / `--update` behavior |
|---|---|---|
| `agents/`, `commands/`, `rules/`, `lib/` | The framework's `.md` / `.json` files | Each framework-owned file is **replaced** so drift heals. Framework files deleted from source are pruned. |
| `skills/` | 30 skill directories | Each framework skill directory is `rm -rf`'d and re-copied, so files deleted *inside* a skill heal too. |
| `hooks/` | 6 core `.sh` hooks (made executable) always, plus analytics/notify hooks when their flag is set; 2 reference `.json` configs | Framework hooks replaced. **Foreign hook files are preserved** (no broad prune); a retired framework hook is removed explicitly by name. `settings.json` bindings are reconciled by exact framework command path, so foreign bindings are kept. |
| `output-styles/concise.md` | Code-first output style | Written on a **bare install only** — `--update` does not reconcile it. |
| `statusline.sh` | Status bar script | Replaced **only when it differs from source** (byte-compare); skipped when identical. |
| `analytics/` | `collector.py`, `server.py`, `dashboard.html`, `schema.sql` | **Only with `--with-analytics`.** A customized copy is preserved, not overwritten. |
| `daemon/` | `claude-framework-watchdog.sh` | **Only with `--with-watchdog`.** Skipped entirely on non-macOS. |
| `settings.json` | See below | Seeded from the template only if the file is absent; otherwise **merged key-by-key**, never wholesale-replaced. |
| `CLAUDE.md` | Generated from `global-config/CLAUDE.md.template`, with your name and email taken from `git config` (it asks you to confirm) | **Only written if the file does not already exist.** Never overwritten, never touched by `--update`. |

### What the installer changes in `settings.json`

Only these keys are framework-owned. Everything else you have set is left untouched.

| Key | Policy |
|---|---|
| `.hooks` | Replace-on-drift, **per event**, matched by exact framework command path so **foreign bindings are preserved verbatim**. A fresh seed wires only the core events; the analytics events (`SubagentStart`/`SubagentStop`/`SessionEnd`) and the `Notification` event are added only with their flag. |
| `.permissions` | Replace-on-drift (whole block) — security-sensitive, so the framework owns it. |
| `.attribution` | Replace-on-drift. Keeps the commit trailer empty (no AI-attribution trailers) and restores the standard PR footer. |
| `.statusLine` | Replace-on-drift — points at `~/.claude/statusline.sh`. |
| `.env` | **Add-only.** Missing template keys are added and **your values are never overwritten** — with one exception: an **absent** `CLAUDE_CODE_EFFORT_LEVEL` is *not* seeded onto an existing settings object (leaving it absent keeps your native/owner effort default). The template's `xhigh` default lands only on a **fresh** settings file; an existing supported value (including empty) is preserved, and an unsupported value is reported but left unchanged. |

Want custom permissions, attribution, or a different statusline? Put them in
`~/.claude/settings.local.json`, which has higher precedence and is never reconciled.

### Written outside `~/.claude`

| Path | Why | Notes |
|---|---|---|
| `~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist` | Registers the hourly observe-only watchdog daemon (reports + backups, no repair) | **macOS only, `--with-watchdog`.** The source plist carries `__HOME__` placeholders; your `$HOME` is substituted at install time. |
| `~/.zshrc`, or `~/.bashrc` if no `.zshrc` exists | Appends a comment plus one line: `alias claude-obs="…"` | **Only with `--with-analytics`.** Idempotent — guarded by a `grep`, so it is added at most once. Nothing else in your shell rc is modified. |

### Created later, at runtime — not by the installer

- `~/.claude/analytics/framework-health.jsonl` — drift findings (action `manual_repair_required`), written by the observe-only checks
- `~/.claude/analytics/watchdog-alerts.jsonl`, `watchdog.log` — watchdog output (macOS, `--with-watchdog`)
- `~/.claude/analytics/agent-events.jsonl`, `session-summaries.jsonl`, `permission-audit.jsonl` — written by the analytics/permission hooks
- `~/.claude/analytics/claude-obs.db` — SQLite, built by `collector.py` when you run `claude-obs`
- `~/.claude/snapshots/` — daily repo/config/memory snapshots written by the watchdog when installed, 7-day retention
- `~/.claude/sessions/` — pre-compact auto-snapshots, 10 kept per project

### It is framework-scoped — your own content is preserved

`~/.claude/{agents,skills,commands,rules,lib}` is shared with anything **you** have put there.
The install manages exactly the **basenames** the framework currently ships or has explicitly
listed as retired: it replaces each shipped name and is only ever *eligible* to prune a
shipped-but-removed or explicitly-retired name. A personal skill, agent, command, rule or lib file
whose name is neither shipped nor retired is never a candidate — the orphan-prune cannot even reach
it. Preservation is by non-colliding **name**, not by origin, so two name collisions are the
exception: a personal file that shares a currently-shipped basename (e.g. your own
`code-quality.md`) is **overwritten** by the shipped copy, and one left at an explicitly-retired
framework name is **eligible for pruning**.

`~/.claude/hooks/` is also framework-scoped, and **foreign hooks are preserved**. The install copies
the current source hooks (core always; the analytics/notify hooks with their flag) and makes them
executable, but runs **no** broad "prune everything not in source" sweep: a `.sh`/`.json` whose name
the framework does not currently ship has no ownership proof and is **retained**, not removed (see
the `hooks/` row above). Retiring a framework hook is handled explicitly, by name. In
`settings.json`, framework hook events are reconciled by exact command path so foreign bindings are
kept verbatim, while the `.permissions` block is replaced wholesale on drift — put custom permissions
in `settings.local.json`.

Measured, not assumed. With a personal skill, agent, command and rule planted in a throwaway `HOME`,
two consecutive `./install.sh --update` runs left all four **byte-identical**, and the skills
directory held 27 framework + 1 personal. Separately, a working machine here carries 14 personal
skills alongside the framework's 27, and all 41 are present. (Both figures were measured when the
framework shipped 27 skills; it now ships 30.)

You can run the same check yourself before trusting it:

```bash
FAKE=$(mktemp -d); mkdir -p "$FAKE/.claude/skills/mine"; echo marker > "$FAKE/.claude/skills/mine/SKILL.md"
HOME="$FAKE" ./install.sh --update >/dev/null
cat "$FAKE/.claude/skills/mine/SKILL.md"     # -> marker
```

### MCP servers are not auto-installed

The installer ships an MCP **reference guide** at `~/.claude/lib/mcp-guide.md` and an example config
(`.mcp.json.example`) in the repo, but registers nothing. MCP configuration is machine-specific.
Add the servers you want yourself with `claude mcp add …` — the four this framework's skills expect
are listed in the [README](./README.md#mcp-integration).

### Prerequisites

`git` and `curl` are required. `jq` and `npx` are optional — `jq` is what reconciles
`settings.json`, so without it the hook/permission/statusline healing is skipped; `npx` is only used
by the MCP setup commands you run yourself.

## The background daemon (opt-in — `--with-watchdog`, macOS)

With `--with-watchdog` on macOS the install registers a `launchd` agent,
`com.claude-code-agents.framework-watchdog`, that runs **once an hour** (`StartInterval 3600`, plus
once at load). It is **observe-only**. Each cycle it:

1. runs `validate.sh --quick --json` (no `--heal`) and **records** any drift to
   `framework-health.jsonl` — it does **not** fork `install.sh`, migrate or repair;
2. runs `git fsck` on the checkout, logging corruption to `watchdog-alerts.jsonl`;
3. writes daily snapshots — a git bundle of the repo, a tarball of `~/.claude/hooks` +
   `settings.json`, and a separate tarball of project memory — to `~/.claude/snapshots/`;
4. prunes snapshots older than 7 days and caps the diagnostic JSONL logs.

It makes **no network requests** and runs as your user, not root. A bare install (no
`--with-watchdog`) registers no daemon.

```bash
launchctl list | grep claude-code-agents                                    # is it loaded?
tail -f ~/.claude/analytics/watchdog.log                                    # what is it doing?
tail -5 ~/.claude/analytics/framework-health.jsonl                          # drift findings
launchctl bootout gui/$(id -u)/com.claude-code-agents.framework-watchdog    # stop it (this boot)
rm -f ~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist  # stop it for good
```

Removing the plist disables the hourly checks and the daily snapshots. The SessionStart hook still
reports drift at session start, but neither path repairs it — run `./install.sh --update` yourself.

Full runbook — cadence, retention, restore commands, the settings-sync-wipe recovery mechanism:
**[SELF-HEALING.md](./SELF-HEALING.md)**.

## Platform support

| Capability | macOS | Linux / WSL |
|---|---|---|
| Agents, skills, commands, rules, lib | Yes | Yes |
| Core hooks, statusline, `settings.json` reconcile | Yes | Yes |
| Observability dashboard + `claude-obs` alias (`--with-analytics`) | Yes | Yes |
| SessionStart drift check (observe-only) | Yes | Yes |
| Hourly watchdog daemon (`--with-watchdog`) | **Yes** | **No** |
| Daily snapshots and 7-day retention (watchdog) | **Yes** | **No** |

The daemon is gated on `uname -s` being `Darwin`; on Linux and WSL `install_watchdog` prints
`Not macOS — skipping watchdog daemon` and returns. Nothing else differs.

**Nothing auto-heals on either platform.** The SessionStart check and the watchdog only **detect and
report** drift to `framework-health.jsonl`; repair is always an explicit `./install.sh --update`. The
watchdog's extra value on macOS is out-of-band visibility and backups: if something external
wholesale-rewrites `~/.claude/settings.json` and drops the `.hooks` block (which also removes the
SessionStart hook), the watchdog still runs independently of `settings.json`, records the drift and
keeps a `userconfig-*.tgz` snapshot — but you still recover by running `./install.sh --update`
yourself. Without the watchdog (Linux/WSL, or macOS without the flag) there is no out-of-band
observer at all. Symptom: the statusline disappears and hooks stop firing.

If you want a scheduled explicit reconcile, add your own cron entry (this runs the foreground
installer on your schedule — it is not background self-heal):

```cron
17 * * * * cd /path/to/claude-code-agents && ./install.sh --update >/dev/null 2>&1
```

## Update & migrate other machines

Updating is **explicit**: pull the source, then run the installer. The SessionStart check and the opt-in watchdog only **report** drift to `framework-health.jsonl` — neither forks the installer or reconciles on its own, and there is deliberately **no auto-pull**.

Full operational runbook — watchdog cadence, settings-sync-wipe recovery, and snapshot restore commands: **[SELF-HEALING.md](./SELF-HEALING.md)**.

```bash
cd claude-code-agents && git pull --ff-only    # 1. get the new source
./install.sh --update                          # 2. reconcile ~/.claude explicitly
```

`--update` re-copies the framework's shared set to `~/.claude` (replacing framework files so drift heals) while preserving your own `~/.claude/CLAUDE.md`, your non-colliding personal files, and settings (a personal file sharing a shipped or retired framework basename is the exception — see [framework-scoped](#it-is-framework-scoped--your-own-content-is-preserved) above).

**Optional — migrate old per-project `.claude/` copies.** If you previously deployed the framework into individual projects, create an opt-in marker that points the explicit migration commands at those projects:

```bash
echo 'LEGACY_PROJECTS_DIR=/absolute/path/to/your/projects' > ~/.claude/.framework-autonomy
```

With the marker set, an explicit `./install.sh --migrate-legacy` (or `--upgrade`) removes the framework's own shared-set subdirs from projects under that dir — **only when git-untracked** (never rewrites a repo's history), **framework-scoped** (your custom agents/skills are never touched), **snapshot-first** (to `~/.claude/snapshots/`), and idempotent. `--update` does **not** run legacy teardown — the marker is not a background-mutation grant, so an update leaves old project copies in place. No marker → nothing happens, and the observe-only watchdog never runs this either; you run `--migrate-legacy`/`--upgrade` yourself.

### Upgrading from the old per-project framework

If you used an **older version that copied `.claude/` into each project**, one command migrates you to the user-global layout — run it **from inside your checkout** (this is a **manual, checkout-local** command; the `curl | bash` one-liner derives its mode from the checkout and can't pass `--upgrade`):

```bash
cd ~/.claude-code-agents && ./install.sh --upgrade
```

`--upgrade` (1) reconciles `~/.claude` to the latest, then (2) finds old per-project `.claude/` copies, **shows a count and the list**, asks **once**, and — only if you confirm — removes them snapshot-first, then (3) self-verifies with `validate.sh --quick`. What it touches:

- Removes **only framework-named files** (`agents/skills/commands/rules/lib`), and **only when git-untracked**. Your **committed** repos, your **custom** agents/skills, and your personal `~/.claude/CLAUDE.md` are never touched. A snapshot is written to `~/.claude/snapshots/` first.
- It reconciles `~/.claude` **even if you decline** the teardown.
- **CI / non-interactive:** `./install.sh --upgrade --yes` or `CLAUDE_UPGRADE_ASSUME_YES=1 ./install.sh --upgrade`. Flags follow the mode (`--upgrade --yes`, not `--yes --upgrade`). With no terminal and no `--yes`, the teardown is **skipped** (nothing removed) and the exact re-run command is printed.

> **Do NOT `git reset --hard` or delete project `.claude` directories by hand to migrate.** `--upgrade` does it safely (untracked-only, snapshot-first). A manual `reset --hard` can destroy uncommitted work and is never required.

`--upgrade` (like `--update`) also resets `settings.json` `.attribution` to the framework value (empty commit trailer, standard PR footer). If you want a custom attribution, put it in `settings.local.json` (higher precedence).

## Safety properties

What the installer actually guarantees — and, just as importantly, what it does not.

- **Framework-scoped.** It only ever writes or deletes names the framework itself ships. Your own
  skills, agents, commands and rules in `~/.claude` are never candidates for deletion.
- **Idempotent.** Safe to run any number of times. Re-running is the normal way to heal drift.
- **Preview before writing.** `./install.sh --dry-run` lists every path it would touch and changes
  nothing.
- **Never clobbers your `CLAUDE.md`.** It is written once, only if absent, and never again.
- **Atomic, fail-closed settings edits.** Every `settings.json` mutation goes to a unique temp file
  and is only moved into place if it is non-empty and valid JSON — a failed edit leaves your file
  untouched rather than truncated.
- **Snapshot-first teardown.** The legacy-migration paths (`--upgrade`, `--migrate-legacy`) abort
  and remove nothing if the pre-teardown snapshot cannot be written and read back.
- **Concurrency-locked.** A `mkdir`-based lock (with stale-PID recovery) keeps a manual run from
  racing another run (or the hourly watchdog's validation, when installed) on `settings.json`.
- **Verified after install.** The bare install checks that `agents/`, `skills/`, `commands/`,
  `rules/`, `hooks/` and `settings.json` are present, and reports warnings if not.

**It does not take a backup of your existing install.** Framework-owned files are replaced in
place — that is how drift heals. Your own content is preserved because it is never touched, not
because it is copied somewhere first. The recovery path for the framework's own state is the
watchdog's daily snapshots under `~/.claude/snapshots/` (macOS, only when installed with
`--with-watchdog`), documented in
[SELF-HEALING.md](./SELF-HEALING.md#snapshot-restore-claudesnapshots).

## Installation Summary

After installation you'll see a component count and a quick-start block:

```
=== Installation Summary ===
┌─────────────────────────────┐
│ Components Installed:   ... │
│ Components Skipped:     ... │
└─────────────────────────────┘

Installed to: ~/.claude (user-global — active in every project)
```

Two counters only. The numbers vary with what already matched, so don't treat them as a checksum —
"skipped" means *already up to date or pruned*, not *failed*. Failures print as red `❌` lines above
the summary, and the bare install ends with an explicit verification block.

## Usage After Installation

Open any project with Claude Code and use natural language:

```
"Design a user authentication system"
"Check this code for security issues"
"Why is this query running slow?"
"Deploy this to production"
```

Agents auto-activate based on your words — no commands needed.

## What the observability dashboard reads

With `--with-analytics`, the install places a dashboard under `~/.claude/analytics/` and adds a
`claude-obs` alias (a bare install adds neither). Nothing runs until you invoke it.

When you do run it, `collector.py` reads **Claude Code's own session transcripts** —
`~/.claude/projects/**/*.jsonl`, across **every project on the machine**, not just this one — plus
the three JSONL streams the framework's hooks write (`agent-events.jsonl`, `session-summaries.jsonl`,
`permission-audit.jsonl`). It aggregates them into SQLite at `~/.claude/analytics/claude-obs.db`.
Those transcripts contain your prompts and Claude's responses, so treat that database as being as
sensitive as your session history.

It stays on your machine:

- `collector.py` makes **no network calls at all**.
- `server.py` binds `127.0.0.1:3141` — loopback only, not reachable from your network.
- The collector and server are Python stdlib only; they require no third-party packages and fetch nothing at runtime. Your data (the JSONL transcripts, the SQLite database, and the API that serves them) never leaves the machine.
- One browser-side exception: `dashboard.html` loads Chart.js from a CDN (`cdn.jsdelivr.net`), so rendering the charts needs your browser to reach that CDN. Offline, the page and its local API still work but the charts will not draw. No framework data is sent to the CDN.
- Nothing is uploaded, phoned home, or shared with the maintainer.

Delete `~/.claude/analytics/claude-obs.db` whenever you like; the next `claude-obs` run rebuilds it
from the transcripts. To opt out entirely, don't run `claude-obs` and delete the alias from your
shell rc.

The framework's hooks and the watchdog daemon likewise make no network requests. Threat model and
vulnerability reporting: **[SECURITY.md](./SECURITY.md)**.

## Troubleshooting

### Permission Denied
```bash
chmod +x install.sh
./install.sh
```

### Network Issues
The installer needs its adjacent source directories, so download the complete checkout:
```bash
git clone https://github.com/pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh
```

### Verification Failed
Reconcile the install:
```bash
./install.sh --update
```

## Uninstallation

```bash
./install.sh --dry-run     # optional: see exactly what is there
./install.sh --uninstall   # remove the framework
```

This is the supported path — prefer it to removing paths by hand. `--dry-run` and `--uninstall` read
the **same source-derived enumeration** of framework-owned paths, so the preview cannot drift from
the removal, and a name the framework does not ship can never be selected.

**Do not `rm -rf ~/.claude`.** That directory also holds your personal Claude Code data: your own
`CLAUDE.md`, `projects/` (every session transcript on the machine), `settings.json`, and any skills
or agents you wrote yourself.

### What `--uninstall` does, in order

1. Counts the framework paths actually present. If none, it exits without touching anything.
2. **Asks you to confirm**, reading your answer from the controlling terminal — never from stdin, so
   a piped `curl … | bash` can never be misread as consent. No terminal and no explicit flag → it
   **aborts and removes nothing**, printing the non-interactive form
   (`CLAUDE_UNINSTALL_ASSUME_YES=1 ./install.sh --uninstall`).
3. **Snapshots first:** a full tarball of `~/.claude` to
   `~/.claude/snapshots/preuninstall-<UTC-timestamp>.tgz`. **If the snapshot fails it aborts and
   removes nothing.**
4. Unloads and deletes the launchd plist (macOS) — daemon first, so it cannot reinstall the files
   mid-removal.
5. Deletes the framework's own files and any framework directory that is now empty. A directory
   still holding your content is left alone.
6. **Surgically edits `settings.json`** rather than deleting it: strips hook bindings pointing at
   `.claude/hooks/` and the framework `statusLine`, leaving `settings.json.pre-uninstall.bak`
   beside it. Leaving those bindings would be worse than doing nothing — every event would try to
   execute a script that no longer exists. (Without `jq` this step is skipped with a warning, and
   you remove them by hand.)
7. Prints the restore command: `tar -xzf <snapshot> -C "$HOME"`.

### Deliberately left behind

| Left behind | Why |
|---|---|
| `~/.claude/CLAUDE.md` | Yours — the installer only ever created it, personalized with your name |
| `~/.claude/projects/`, `todos/`, `sessions/` | Your session history and auto-snapshots |
| Personal skills / agents / commands / rules | Never framework-owned; not in the enumeration |
| `~/.claude/snapshots/` | Your recovery path — delete it yourself once you're sure |
| `~/.claude/analytics/*.jsonl`, `claude-obs.db` | Your usage data; delete if you want it gone |
| The `claude-obs` alias in `~/.zshrc` / `~/.bashrc` | Editing your shell rc during removal is riskier than leaving three inert lines |
| `~/.claude/output-styles/concise.md` | Not currently in the removal enumeration — delete it by hand if you want it gone |

To also clear the telemetry, snapshots and the shell alias:

```bash
rm -rf ~/.claude/analytics ~/.claude/snapshots ~/.claude/sessions ~/.claude/output-styles
# then delete the "# Claude Code Observability" block from ~/.zshrc (or ~/.bashrc)
```

### Verify it is gone (macOS)

`--uninstall` already unloads and removes the daemon; this just confirms it.

```bash
launchctl list | grep claude-code-agents   # expect no output
ls ~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist  # expect: No such file
```

If either still shows up:

```bash
launchctl bootout gui/$(id -u)/com.claude-code-agents.framework-watchdog 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist
```

### Manual removal (if you cannot run the installer)

```bash
rm -rf ~/.claude/agents ~/.claude/commands ~/.claude/skills \
       ~/.claude/rules ~/.claude/lib ~/.claude/hooks ~/.claude/daemon \
       ~/.claude/output-styles ~/.claude/statusline.sh \
       ~/.claude/.framework-path ~/.claude/.framework-version ~/.claude/.watchdog-plist.sha
```

> **Careful:** unlike `--uninstall`, this removes those directories **wholesale** — including any
> personal skills, agents, commands or rules you keep alongside the framework's. Check first with
> `ls ~/.claude/skills ~/.claude/agents`, and move anything of yours out before running it.

Then edit `~/.claude/settings.json` by hand to remove the framework's `hooks` and `statusLine`
blocks, and unload the daemon as shown above.

## Support & Updates

- **Repository**: github.com/pfangueiro/claude-code-agents
- **Issues**: Report problems in GitHub Issues
- **Updates**: Run `./install.sh --update` to get the latest version

---

*One install, user-global — the agents are available in every project on your machine.*
