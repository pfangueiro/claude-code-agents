# Framework control: status, settings and update

`./framework` is one entry point in the framework **source checkout**. It brings together
three things: a read-only readiness view, display preferences for that view, and the safe
updater for an existing installation. It is a file in this checkout, not a command on your
PATH. Nothing installs an alias, a startup hook, a schedule or a service, and nothing here
changes models, approval or sandbox policy, hook trust, accounts or native configuration.

## Quick commands

```bash
./framework                         # same as ./framework status
./framework status --detail full    # every component and extra, plus the source folder
./framework status --json           # structured output for scripts and agents
./framework settings                # optional extras and how to change each one
./framework settings --set-detail full
./framework settings --acknowledge claude.analytics
./framework settings --review       # guided; interactive terminal only
./framework update --help           # the safe updater's own commands and options
```

From any other folder, run the installed helper. It offers `status` and `settings` only; it
cannot update and does not compare with the source:

```bash
python3 ~/.claude/lib/framework_settings.py         # Claude install
python3 ~/.codex/framework/settings.py              # Codex user install
python3 /abs/project/.codex/framework/settings.py --project /abs/project   # Codex project install
```

The helper prints its own exact invocation in its hints. It reads the checkout location from
`~/.claude/.framework-path` as plain data (it never runs or imports anything there); pass
`--source PATH` to show another folder. An agent can locate the checkout the same way and run
`./framework` there for you.

## Status (read-only)

Status never writes, never prompts and never creates a preferences file. It has two parts.

**1. Installed files against their own install records.** One headline:

| Headline | Meaning |
|---|---|
| Framework files ready | Every installed part that has a per-file record matches it |
| Installed - not fully checked | Something is installed without a per-file record (the broad Claude install) |
| Needs attention | A file changed or is missing, a record is unusable, or a preferences file was refused |
| Not installed | No install record was found |

- Claude delivery files are compared with `~/.claude/.sdlc-delivery/manifest.json`.
- Codex files are compared with their manifest, but only inside the Codex installer's own
  namespaces: its exact set of `.codex/framework` resources, plus the `sdlc-` skill folders,
  the `.codex/agents/*.toml` agent files and the optional `hooks.json`. A manifest that names
  anything else (for example the private lint
  approval list, runtime evidence or the manifest itself) is refused before any file is
  read. Codex is Ready only when the managed `AGENTS.md` block also matches its recorded
  checksum and the recorded hook choice matches a verified `hooks.json`.
- The broad Claude install has no per-file record, so it is always "Not checked", never
  Ready. `./validate.sh --quick` checks installed integrity for that part.

Optional extras keep separate states: On, Off, Unknown, Not checked, Needs setup,
Unavailable and Needs attention. Claude analytics, watchdog and notifications come from the
selection recorded at install; a missing or odd value is Unknown, never Off. A file that
merely exists is **Not checked**, never On: an approval list for Codex lint (its entries are
not read), an active model policy (its evaluations and approvals are checked by the
delivery model-policy tool) and a controller binding (the controller validates it when it
runs). AI sign-in, model runs, MCP connections and the host status line are always reported
as not checked; an install record or a CLI on PATH proves none of them.

**2. Compared with this checkout** (only `./framework`, not the installed helper). This uses
the existing `scripts/framework-status.py`: Codex and Claude delivery files either match
this checkout, differ from it, could not be compared, or are not installed. The broad Claude
install is not compared file by file; its marker records an abbreviated commit, which does
not prove the installed bytes. If the Codex or Claude delivery install record already needs
attention in part 1, the comparison is not run at all (that checker would trust the same
record): it is reported as not completed and status exits `2`. Fix the installed files first.

**Folders.** Status checks `~/.claude` (or `--claude-home PATH`) and the Codex install in
`~/.codex` (or `--project PATH`). If `CLAUDE_CONFIG_DIR` or `CODEX_HOME` names another
folder, status says which default folder it checked instead; it never prints those values
and never treats another folder as the default.

**Exit status** of `./framework status`: `0` nothing needs attention; `1` something needs
attention or differs from this checkout; `2` a check could not complete or reported an
error, or a usage error. The installed helper alone exits `0` or `1` for status, and `2`
for a usage error or a refused preference change.

## Settings and display preferences

`settings` shows each optional extra with what it does, its current state and the honest
way to change it (an installer flag, a native step such as Codex `/hooks`, or an owner
policy). It switches nothing on or off itself.

Display preferences live in one private file, `~/.config/sdlc/framework-preferences.json`
(owner-only, inside owner-only folders). They hold the status detail level
(`concise` or `full`), the reminder mode (`changes-only` or `off`) and which extras you
reviewed as enabled or disabled. They only shape presentation: they grant no permission
and hold no account, credential, model identifier or operational switch.

- The file is written only by an explicit settings option (`--set-detail`,
  `--set-reminders`, `--acknowledge`, `--acknowledge-all`, `--forget`) or after you
  confirm at the end of `--review`. `--review` runs only on an interactive terminal; `--json`,
  CI and other non-interactive runs never prompt.
- A malformed, symlinked, shared or unexpectedly owned file is refused and left untouched;
  defaults are shown and the refusal is reported as needing attention.
- A save replaces the file atomically only if it still holds the bytes that were read.
- Reminders are about changes only: an extra you reviewed as enabled that is now off (or
  the reverse). An extra never reviewed produces no reminder. The "new optional extras"
  notice appears only after an earlier completed review (`--acknowledge-all` or a finished
  `--review`) of an older catalog; saving a display preference or acknowledging one extra
  never triggers it.
- Quiet or concise output never hides a failure: "Needs attention" items are always shown.

## Update an existing installation

`./framework update` runs the safe updater, `scripts/framework_update.py` (Python 3.11 or
newer), with the arguments you pass. It is the preferred way to bring an **existing**
user-global installation up to the commit this checkout has checked out. It is not a first
installation: fresh installs remain `./install.sh` and `./install-codex.sh --user`.

**The easy way.** Ask the agent: *"Update the installed framework and preserve my
settings."* It should update the checkout through the reviewed steps below, make a plan,
show you what would change, and apply it only after you agree.

**1. Update the source checkout separately.** The updater never pulls, checks out or
installs a new edition. Bring this checkout to a revision of `main` that was reviewed and
whose CI passed, using the inspect-before-pull part of
[INSTALL.md step 1](../INSTALL.md#1-preview-from-a-clean-checkout) (an empty
`git status --short`, the pre-pull checks, then `git pull --ff-only`). Planning refuses a
checkout with any staged, untracked, ignored or modified file in the paths it reads.

**If planning refuses your checkout.** The clean-source check also covers ignored files in
the paths the updater reads, such as a project's native settings or history, editor
metadata or compiled caches. These are often your personal files. The refusal is still
legitimate: a file there could be copied or built into your installation, so the check is
not weakened and not every unknown file is harmless. A refusal does **not** mean you should
delete local settings, caches or project overrides. Ask the agent instead: *"Use a clean
source checkout and preserve my local settings."* It should use a separate clean checkout
or Git worktree of this repository at the reviewed GitHub `main` commit, leave your
original checkout and its ignored files unchanged, and run the quick plan and apply
commands below from that clean checkout. The framework never creates this checkout itself.

**Keeping that clean checkout.** One retained checkout on the host is enough, for example
`~/.local/share/sdlc-framework/source`, detached at the reviewed commit. That location is an
operator convention, not an installer default or a service. Both integrations stay one
user-global installation; the checkout is not a project copy. When Claude is updated from
there, `~/.claude/.framework-path` names that folder, so keep it while the installation or
watchdog uses it. A Codex-only user can remember the path or pass it with `--source`. The
location is plain data, never permission to run something there. For a later update,
confirm that the new GitHub `main` commit was reviewed and its CI passed, advance the clean
checkout to it as a separate step (the updater never pulls), then plan and apply. Copy
nothing from private configuration, caches, accounts or controller state into it or to
another machine.

**2. Plan (read-only).**

```bash
plan_dir=$(mktemp -d)    # a new owner-only (0700) folder outside Git
./framework update plan --out "$plan_dir/plan.json"
```

`plan` writes nothing to your installation. It prints a `PLAN_READY` document
(`executed: false`) naming the source commit, the target home, the editions, every file it
would write or remove, notes and limits; `--out` also saves it as a new owner-only (0600)
file. The folder must be a private (0700) folder you own and the file must not exist yet;
use a fresh `mktemp -d` folder rather than changing the permissions of an existing personal
folder. Options:

- `--edition claude|codex|both` restricts the update. By default every integration that is
  already installed is updated; selecting one that is not installed is refused (nothing is
  newly installed).
- `--source PATH` plans from another clean checkout (default: this one).
- `--home PATH` targets another home-shaped folder (default: your home).
- Codex planning loads `codex/framework.py`, so run it in the Python environment of the
  Codex install (see INSTALL.md).

**3. Apply the reviewed plan.**

```bash
./framework update apply --plan "$plan_dir/plan.json"
```

`apply` first checks that the checkout is still clean and still at the commit the plan
names, before it runs any code from the checkout. Under a lock it then recomputes the whole
plan and refuses unless the target, editions, operations and fingerprint all still match.
If anything differs, nothing is written: plan again and review the new plan. Exit status:
`0` PLAN_READY or PASS, `1` FAIL, `2` INCOMPLETE.

What an apply does, in order:

- **Claude.** When the delivery manifest exists, the delivery update is forecast first.
  When the broad install marker exists, `install.sh --update` (no optional flags) then runs
  only in a private, disposable staging home holding copies, never against your live home.
  Same-byte hook files missing their executable bits get a mode-only repair. A Codex-only
  update (`--edition codex`) never runs the Claude installer.
- **Codex.** The checkout's own hash-owned planner runs against your logical home after
  every manifest path is proven to be a framework resource. Your recorded hook choice is
  kept (with hook commands that name your home); a manifest whose hook choice contradicts
  its file list is refused. Your own text in `~/.codex/AGENTS.md` outside the managed block
  is kept.
- **Backup and log.** Before the first write it copies every file it will replace or remove
  to `~/.sdlc-framework-update/backups/<time>-<pid>/`, verifies each copy, and keeps an
  owner-private operation log (`operations.jsonl`) there of each actual attempt and outcome.
  It then rechecks every guarded input, writes files before the manifests and markers that
  describe them, and verifies the result.
- **On failure** it rolls back only what this run wrote. A path another writer changed
  afterwards is not overwritten; it is listed for manual recovery from the backup. A
  partial backup is kept and its location reported. If every change was written and
  verified but the log could not record its final step, the changes are kept and the
  result is INCOMPLETE, not PASS.

It never rewrites `settings.json` (it refuses if the broad installer would change it),
`CLAUDE.md`, Codex configuration, accounts or optional choices (analytics, watchdog,
notifications and Codex hooks are preserved, never switched on). It grants no hook trust,
activates no model policy, discovers no account, starts no service, controller or schedule,
and creates no preferences file. It refuses rather than guesses on forecast drift, locally
modified or foreign files, name collisions, install history it cannot prove, unsupported
layouts and symbolic links in the home, plan or output paths (root-owned system aliases
such as `/tmp` or `/var` on macOS are the one exception). Older framework Codex entries it
does not recognize can cause a refusal. Retired framework paths without byte proof are
retained and listed, never deleted automatically. Do not restore a backup by unpacking an
arbitrary archive over your home; ask the agent to compare the listed files first.

The broad `./install.sh --update` is still available and still behaves as before: it
replaces same-name framework files with no backup and reconciles framework settings keys
(permissions, attribution, the status line and framework hook bindings). It is the
dangerous manual alternative; use it only through the procedure in INSTALL.md.

## Limits

- Status compares installed files with their own records and, in the checkout, with this
  checkout. It does not prove that the host signs in, that models run, that MCP servers
  connect or that Codex hooks are trusted.
- Optional extras selected earlier (analytics, watchdog, notifications, Codex hooks) are
  preserved by updates. Their selection is reported, but that does not show their files
  match the current source.
- Supported status inspection targets are the default `~/.claude` and `~/.codex` installs,
  plus `--claude-home PATH` and explicit `--project PATH` Codex installs. A custom
  `CLAUDE_CONFIG_DIR` or `CODEX_HOME` is never treated as the default. The updater supports
  only existing user-global installs in `<home>/.claude` and `<home>/.codex` (your home, or
  `--home PATH`): Codex project installs and a custom `CODEX_HOME` are refused, and a
  `CLAUDE_CONFIG_DIR` naming another folder is reported and never updated. Check the target
  the plan names before applying.
- Updating does not check that hooks are trusted, that you are signed in, that models run
  or that MCP servers connect. No speedup, quality gain or runtime parity is claimed.
- Locks and freshness checks are cooperative. They do not stop another program you run
  at the same moment from writing the same files, and a multi-file change is not atomic
  if the machine loses power or the process is killed. If something goes wrong, keep
  any backup the updater reports and ask the agent to compare before restoring.
- Preference saves are single-file atomic replacements with an old-bytes check; they do
  not defeat a concurrent writer between that check and the replacement.
- No performance or quality gain is claimed for any of this.
