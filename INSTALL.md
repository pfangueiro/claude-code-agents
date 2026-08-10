# Claude Agents - Installation Guide

## Install (one command, user-global)

Clone the repo and run the installer:

```bash
git clone git@github.com:pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh
```

That's it. Everything installs **once**, user-global to `~/.claude`. Claude Code natively loads `~/.claude/{agents,skills,commands,rules}`, so every project on your machine gets the agents automatically — there is no per-project step.

The install includes: agents, skills, commands, rules, hooks, statusline, output styles, the observability dashboard, and global settings. It also registers an hourly background daemon on macOS. MCP servers are **not** registered — that is a manual, machine-specific step (see [MCP](#mcp-servers-are-not-auto-installed)).

**Not sure what it will touch?** `./install.sh --dry-run` prints every path it would write, resolved against your actual `$HOME`, and changes nothing.

## Commands

| Command | What it does |
|---------|-------------|
| `./install.sh` | Install everything user-global to `~/.claude` |
| `./install.sh --dry-run` | Print every path the install would touch. Makes no changes. |
| `./install.sh --update` | Non-interactive reconcile of an existing install (the self-heal path). Replaces framework-owned files so drift heals; preserves your own content. |
| `./install.sh --upgrade` | One-command migration from the old per-project layout: reconcile `~/.claude`, then confirm + tear down old per-project copies (snapshot-first) and self-verify. Run from inside your checkout. See [Upgrading from the old per-project framework](#upgrading-from-the-old-per-project-framework) below. |
| `./install.sh --migrate-legacy` | Marker-gated teardown-only mode (the watchdog runs this every cycle; also runnable manually for an immediate migration). |
| `./install.sh --uninstall` | Remove the framework's own components. See [Uninstallation](#uninstallation). |
| `./install.sh --help` | Show all options |

## What Gets Installed

Most of it lands under `~/.claude/` and is loaded by Claude Code in every project:

```
~/.claude/
├── agents/                # 13 specialized agents
├── commands/              # 13 slash commands
├── skills/                # 27 modular knowledge packages
├── rules/                 # 6 auto-enforced rule sets
├── lib/                   # Templates, patterns, coordination protocol, MCP guide
├── hooks/                 # 9 command hooks + 2 reference configs
├── daemon/                # launchd watchdog — macOS only
├── analytics/             # Observability dashboard (claude-obs alias)
├── output-styles/
│   └── concise.md         # Code-first output style
├── statusline.sh          # Rich status bar — line-1 framework-status glyph (⚙<version> + ✓/⟳/⚠)
├── settings.json          # Model, env, permissions, 10 hook events, statusline
├── CLAUDE.md              # Personal coding preferences (created only if absent)
├── .framework-path        # Marker: where this checkout lives, read by the self-heal paths
├── .framework-version     # Marker: installed version + source SHA
└── .watchdog-plist.sha    # Marker: sha of the loaded daemon plist
```

### Exactly what each path gets, and what happens on re-install

| Path | Contents | Re-install / `--update` behavior |
|---|---|---|
| `agents/`, `commands/`, `rules/`, `lib/` | The framework's `.md` / `.json` files | Each framework-owned file is **replaced** so drift heals. Framework files deleted from source are pruned. |
| `skills/` | 27 skill directories | Each framework skill directory is `rm -rf`'d and re-copied, so files deleted *inside* a skill heal too. |
| `hooks/` | 9 `.sh` scripts (made executable) + 2 reference `.json` configs | Replaced. Hook files no longer in source are pruned, as are stale `settings.json` hook-event bindings that point at a framework script. |
| `output-styles/concise.md` | Code-first output style | Written on a **bare install only** — `--update` does not reconcile it. |
| `statusline.sh` | Status bar script | Replaced **only when it differs from source** (byte-compare); skipped when identical. |
| `analytics/` | `collector.py`, `server.py`, `dashboard.html`, `schema.sql` | Replaced. |
| `daemon/` | `claude-framework-watchdog.sh` | Replaced. **Skipped entirely on non-macOS.** |
| `settings.json` | See below | Seeded from the template only if the file is absent; otherwise **merged key-by-key**, never wholesale-replaced. |
| `CLAUDE.md` | Generated from `global-config/CLAUDE.md.template`, with your name and email taken from `git config` (it asks you to confirm) | **Only written if the file does not already exist.** Never overwritten, never touched by `--update`. |

### What the installer changes in `settings.json`

Only these keys are framework-owned. Everything else you have set is left untouched.

| Key | Policy |
|---|---|
| `.hooks` | Replace-on-drift, **per event**. Each of the 10 template events is compared and restored if it differs. Off-template events are pruned only if they invoke a framework hook script. |
| `.permissions` | Replace-on-drift (whole block) — security-sensitive, so the framework owns it. |
| `.attribution` | Replace-on-drift. Keeps the commit trailer empty (no AI-attribution trailers) and restores the standard PR footer. |
| `.statusLine` | Replace-on-drift — points at `~/.claude/statusline.sh`. |
| `.env` | **Add-only.** Missing template keys are added; **your values are never overwritten.** |

Want custom permissions, attribution, or a different statusline? Put them in
`~/.claude/settings.local.json`, which has higher precedence and is never reconciled.

### Written outside `~/.claude`

| Path | Why | Notes |
|---|---|---|
| `~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist` | Registers the hourly self-heal daemon | **macOS only.** The source plist carries `__HOME__` placeholders; your `$HOME` is substituted at install time. |
| `~/.zshrc`, or `~/.bashrc` if no `.zshrc` exists | Appends a comment plus one line: `alias claude-obs="…"` | Idempotent — guarded by a `grep`, so it is added at most once. Nothing else in your shell rc is modified. |

### Created later, at runtime — not by the installer

- `~/.claude/analytics/framework-health.jsonl` — drift and self-heal events
- `~/.claude/analytics/watchdog-alerts.jsonl`, `watchdog.log` — daemon output (macOS)
- `~/.claude/analytics/agent-events.jsonl`, `session-summaries.jsonl`, `permission-audit.jsonl` — written by hooks
- `~/.claude/analytics/claude-obs.db` — SQLite, built by `collector.py` when you run `claude-obs`
- `~/.claude/snapshots/` — daily repo/config/memory snapshots written by the daemon, 7-day retention
- `~/.claude/sessions/` — pre-compact auto-snapshots, 10 kept per project

### It is framework-scoped — your own content is preserved

`~/.claude/{agents,skills,commands,rules,lib}` is shared with anything **you** have put there.
The install is fail-closed about this: a copy only ever replaces a file the framework itself ships,
and the orphan-prune is only ever *eligible* to remove a name the framework currently ships or has
explicitly listed as retired. A personal skill, agent, command, or rule is never a candidate for
deletion — the check cannot even reach it.

Measured, not assumed. With a personal skill, agent, command and rule planted in a throwaway `HOME`,
two consecutive `./install.sh --update` runs left all four **byte-identical**, and the skills
directory held 27 framework + 1 personal. Separately, a working machine here carries 14 personal
skills alongside the framework's 27, and all 41 are present.

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

## The background daemon (macOS)

On macOS the install registers a `launchd` agent, `com.claude-code-agents.framework-watchdog`, that
runs **once an hour** (`StartInterval 3600`, plus once at load). Each cycle it:

1. runs `validate.sh --quick --json`, and forks `install.sh --update` if it reports drift;
2. runs `git fsck` on the checkout, logging corruption to `watchdog-alerts.jsonl`;
3. writes daily snapshots — a git bundle of the repo, a tarball of `~/.claude/hooks` +
   `settings.json`, and a separate tarball of project memory — to `~/.claude/snapshots/`;
4. prunes snapshots older than 7 days and caps the diagnostic JSONL logs.

It makes **no network requests** and runs as your user, not root.

```bash
launchctl list | grep claude-code-agents                                    # is it loaded?
tail -f ~/.claude/analytics/watchdog.log                                    # what is it doing?
tail -5 ~/.claude/analytics/framework-health.jsonl                          # drift/heal events
launchctl bootout gui/$(id -u)/com.claude-code-agents.framework-watchdog    # stop it (this boot)
rm -f ~/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist  # stop it for good
```

Removing the plist disables the hourly reconcile and the daily snapshots. The SessionStart hook
keeps healing drift at session start.

Full runbook — cadence, retention, restore commands, the settings-sync-wipe recovery mechanism:
**[SELF-HEALING.md](./SELF-HEALING.md)**.

## Platform support

| Capability | macOS | Linux / WSL |
|---|---|---|
| Agents, skills, commands, rules, lib | Yes | Yes |
| Hooks, statusline, `settings.json` reconcile | Yes | Yes |
| Observability dashboard + `claude-obs` alias | Yes | Yes |
| SessionStart self-heal hook | Yes | Yes |
| Hourly watchdog daemon | **Yes** | **No** |
| Daily snapshots and 7-day retention | **Yes** | **No** |

The daemon is gated on `uname -s` being `Darwin`; on Linux and WSL `install_watchdog` prints
`Not macOS — skipping watchdog daemon` and returns. Nothing else differs.

**What you lose on Linux/WSL:** drift is detected and healed **only at session start**. There is no
out-of-band recovery and no automatic snapshots. That matters for one specific failure: if something
external wholesale-rewrites `~/.claude/settings.json` and drops the `.hooks` block, it also removes
the SessionStart hook — which is the thing that would have healed it. On macOS the watchdog runs
independently of `settings.json` and recovers this; on Linux/WSL you recover it by running
`./install.sh --update` by hand. Symptom: the statusline disappears and hooks stop firing.

Consider a cron entry as a substitute:

```cron
17 * * * * cd /path/to/claude-code-agents && ./install.sh --update >/dev/null 2>&1
```

## Update & migrate other machines

The framework is **self-updating**: after a `git pull` on any machine, the SessionStart healthcheck and the launchd watchdog automatically fork `install.sh --update` to reconcile `~/.claude` — you don't have to run the installer by hand. `git pull` is the one deliberate trigger (there is deliberately **no auto-pull**).

Full operational runbook — watchdog cadence, settings-sync-wipe recovery, and snapshot restore commands: **[SELF-HEALING.md](./SELF-HEALING.md)**.

```bash
cd claude-code-agents && git pull --ff-only    # the one manual step; the rest is autonomous
./install.sh --update                          # optional: reconcile now instead of waiting for self-heal
```

`--update` re-copies the framework's shared set to `~/.claude` (replacing framework files so drift heals) while preserving your own `~/.claude/CLAUDE.md`, personal skills, and settings.

**Optional — autonomously migrate old per-project `.claude/` copies.** If you previously deployed the framework into individual projects, create an opt-in marker so `--update` migrates them to user-global for you:

```bash
echo 'LEGACY_PROJECTS_DIR=/absolute/path/to/your/projects' > ~/.claude/.framework-autonomy
```

With the marker set, the framework removes its own shared-set subdirs from projects under that dir — **only when git-untracked** (never rewrites a repo's history), **framework-scoped** (your custom agents/skills are never touched), **snapshot-first** (to `~/.claude/snapshots/`), and idempotent. No marker → nothing happens. The watchdog re-runs this every cycle, so setting the marker migrates old copies within the hour; run `./install.sh --migrate-legacy` to do it immediately.

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
  racing the hourly watchdog on `settings.json`.
- **Verified after install.** The bare install checks that `agents/`, `skills/`, `commands/`,
  `rules/`, `hooks/` and `settings.json` are present, and reports warnings if not.

**It does not take a backup of your existing install.** Framework-owned files are replaced in
place — that is how drift heals. Your own content is preserved because it is never touched, not
because it is copied somewhere first. The recovery path for the framework's own state is the
daemon's daily snapshots under `~/.claude/snapshots/` (macOS), documented in
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

The install places a dashboard under `~/.claude/analytics/` and adds a `claude-obs` alias. Nothing
runs until you invoke it.

When you do run it, `collector.py` reads **Claude Code's own session transcripts** —
`~/.claude/projects/**/*.jsonl`, across **every project on the machine**, not just this one — plus
the three JSONL streams the framework's hooks write (`agent-events.jsonl`, `session-summaries.jsonl`,
`permission-audit.jsonl`). It aggregates them into SQLite at `~/.claude/analytics/claude-obs.db`.
Those transcripts contain your prompts and Claude's responses, so treat that database as being as
sensitive as your session history.

It stays on your machine:

- `collector.py` makes **no network calls at all**.
- `server.py` binds `127.0.0.1:3141` — loopback only, not reachable from your network.
- Both are Python stdlib only; no third-party packages, nothing fetched at runtime.
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
Download the script locally:
```bash
curl -sSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/install.sh > install.sh
chmod +x install.sh
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
