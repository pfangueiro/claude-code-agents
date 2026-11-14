# Persistent delivery controller: operator guide

This guide describes the controller as its source in this tree implements it: the operator
CLI (`controller.py`), input boundary, ledger, request inbox, routing, shared process
lifecycle, native provider adapters, check runner, effects library and the engine
(`controller_engine.py` with `controller_engine_io.py`) that `run`, `recover` and
`cleanup-workspaces` load. It states what the code does. It does not report test, CI,
review or native-smoke outcomes, and it makes no claim about unattended operation,
throughput, uptime or agent quality.

The controller is an optional resource inside the existing `delivery` skill. It adds no
skill, command or agent: inventory is unchanged at 30 skills, 12 command templates and 13
agents (Codex: 55 bundles). Both installers export it with the rest of the skill.

## What it is and is not

It is a local, single-host, single-repository operator CLI. It carries one owner-approved
plan through implementation, checks, independent review, sequential integration and,
when separately authorized, publication. A durable SQLite ledger records every step. Its
loop is durable across restarts of the process, but it runs only while you start and keep
running that process.

It is **not**:

- A daemon, service or scheduler. Install, update, `setup` and loading the skill create no
  launchd/systemd unit, cron entry, background session or watcher. `run` works only in the
  foreground of the process you start, and `run --background` does not daemonize.
- An account manager. It never discovers accounts, logs in, checks or renews
  authentication, reads credential or provider config contents, or changes models,
  billing, account policy, permissions, approval, sandbox or trust. What it does do is
  choose which of your owner-allowlisted profiles launches each attempt, under the routing
  your saved policy approved (section 1, Accounts and profiles).
- A sandbox or signature system. Policy, plan and authority files are same-user owner
  declarations protected by private-file checks. They are not cryptographic signatures and
  not a boundary against code running as the same OS user or as root.
- A release or deployment tool. Release and deployment are not implemented.
- A remote or multi-machine executor. Running it on other hosts, virtual machines or remote
  workers is not implemented, and this guide documents none.

The opt-in framework integrity watchdog (`./install.sh --with-watchdog`) is a different
thing. It observes drift and keeps backups, and it never executes tasks. Its default-off
status, and that of analytics and notifications, is unchanged.

## Requirements

- POSIX host (macOS or Linux), Python 3.11 or newer, and native `git`. The effects library
  states Git 2.38 or newer. Automatic merge also needs a `gh` whose `pr merge --help`
  documents `--match-head-commit`.
- Native CLIs for each profile you configure. Their interfaces were checked at Claude Code
  2.1.323 and Codex 0.169.0. A newer version is reported, not assumed compatible.
- Your own working credentials, quota and project tools. The controller supplies none of
  them.

## Where it lives

| Install | Controller path |
|---|---|
| Claude, user-global | `~/.claude/skills/delivery/scripts/controller.py` |
| Codex, user-global | `~/.agents/skills/sdlc-delivery/scripts/controller.py` |

The runtime identity covers the controller files, the delivery skill text and references,
the sibling `verified-handoff` (`sdlc-verified-handoff` for Codex) `evidence.py`, and the
edition. A state directory is bound to the runtime that created it. Keep using that same
copy. Running another copy shows a context HOLD. The runtime directory must be reached
without symlinks: if the path resolves through a symlink, the runtime is refused.

The examples below use `CTL` for whichever copy you chose:

```bash
CTL="$HOME/.claude/skills/delivery/scripts/controller.py"
python3 "$CTL" --help
```

## Outcomes

Every command ends with one line on stderr: `PASS` (exit 0), `FAIL` (exit 1) or
`INCOMPLETE` (exit 2). INCOMPLETE means a required step did not run, for example a lock
held by a running controller, unsettled owned work, a hold, or an engine file that is
missing or fails to load (`runtime_missing`, `runtime_unavailable`). Absent checks are not
zero. A native CLI exiting 0 is never acceptance by itself.

## 1. Minimal setup (once per repository)

Pick a state directory **outside** the repository and its Git directory. Its parent must
exist. The controller creates the state directory itself with mode 0700.

```bash
mkdir -p -m 700 "$HOME/.local/state/sdlc-controller"
python3 "$CTL" setup --repo /absolute/path/to/repo \
  --state "$HOME/.local/state/sdlc-controller/<repo-name>"
```

`setup` asks the policy questions once, prints the full policy as JSON with a summary, and
writes nothing unless you type `create`. Invalid answers are re-asked without being
echoed. It writes:

- in `--state`: the policy snapshot, the ledger and later the request inbox
  (directory 0700, files 0600)
- in the repository's **Git common directory** (not the work tree): a binding file
  (`sdlc-controller.binding`) and a lock file (`sdlc-controller.lock`). These give one
  controller authority per repository.

If `--state` already holds state, `setup` prints the recorded policy and changes nothing.
The same is true after any installer update: an update preserves the recorded policy,
asks no question and at most prints a note that setup is available. Setup never asks again
and never overwrites. To change policy, see section 6.

The non-interactive equivalent is `init --policy <file> --state <dir>`. The policy file must
be owner-only (0600), outside the repository, single-link and reached without symlinks,
under parent directories that are not group- or world-writable. On macOS, `/tmp` is a
symlink, so files under it are refused. Re-running `init` with the same policy verifies it.
A different policy is refused (`policy_changed`).

### Policy questions

| Field | Meaning |
|---|---|
| `profiles` (1-16) | Each one is `id`, `provider` (`claude`/`codex`), absolute `executable` outside the repo, `config_dir` and `roles` (`implement`, `review` or both). Every profile is explicitly owner-allowlisted. |
| `config_dir` | The account directory the native CLI uses. Blank means `$CLAUDE_CONFIG_DIR` or `~/.claude` (Codex: `$CODEX_HOME` or `~/.codex`), resolved once and frozen into the policy. Only its existence is checked. It must not be your home directory or inside the repo, and two profiles may not share one. |
| `auto_route` | Off: only the first owner-ordered profile allowed a role is considered, and a blocked pin is reported rather than replaced. On: for each attempt the router picks among the eligible profiles, with no per-task or per-profile question. |
| `max_parallel` (1-16) | Your global concurrency choice across all profiles, including local checks. |
| `review_reserve` | Slots kept for review (less than `max_parallel`; needs a review-capable profile). |
| `limits` | `max_attempts` (per task and role), `attempt_seconds`, `max_total_seconds` (per plan), `max_no_progress`. `max_cost_usd` must be `null`. |
| `allowed_checks` | Up to 64 check IDs, each an exact argv JSON array. |
| `instruction_paths` | Repository-relative instruction files whose **committed** bytes form the rules identity. |
| `effects` | Any of `commit`, `integrate` (local) and `push`, `pr`, `merge` (external). |
| `delivery` | `null` disables every external effect. Otherwise a frozen target: `remote`, credential-free `remote_url`, `github_repo`, `base_branch`, `branch_prefix` (ends in `/`), `required_checks`, `merge_method` (`merge`/`squash`). |
| `execution_enabled` | Default `n`. While false, the ledger refuses every claim. |
| `background_enabled` | Default `n`. A separate owner consent that `run --background` checks. It is stored as policy only; nothing is installed or started. |

**Monetary caps are not supported.** No cost is measured, and `max_cost_usd` accepts only
`null`. Attempts, wall-clock time and no-progress streaks bound the work. The ledger
docstring gives the per-lane dispatch bound: `max_attempts * (1 + L)`, where L is the
number of profiles allowed that role.

**Checks are literal.** `argv[0]` must be an absolute existing executable. Arguments are
literal strings with no shell parsing. Arguments that look like credentials are refused
(a heuristic only). The controller never guesses or discovers check commands. A task may
reference only declared check IDs.

**Uncommitted instruction files block identity.** If an `instruction_paths` file differs
from `HEAD`, setup, submit and run refuse (`dirty_instructions`). Commit the file first.

### Accounts and profiles

- One Claude account is enough. A single profile with `implement,review` works: every
  attempt is a **fresh native session**, so roles are sessions, not accounts. More than one
  concurrent session on the same profile is limited only by your `max_parallel`.
- More profiles are opt-in. You may configure up to 16 owner-authorized profiles. Extra
  profiles are never mandatory and never discovered: only the ones you listed exist for
  the controller.
- With `auto_route` on, the controller picks the profile for every attempt by itself.
  Each dispatch considers every listed profile allowed that role and launches a fresh
  native session on one that is usable now. A profile observed available comes first, and
  among those the one with the lowest active load. A profile whose availability is unknown
  or not yet observed is used only when no observed-available profile is usable, and that
  real bounded attempt is its probe. Held, rate-limited or cooling-down profiles are
  skipped until their evidence allows them again. Ready tasks can therefore run at once on
  different eligible profiles. Work still needs ready tasks whose dependencies are accepted
  and integrated, and it stays within `max_parallel`, the ledger's scope, resource and
  budget checks, and `review_reserve`, which keeps slots from implementation while checked
  work waits for review.
- Your saved policy and the plan authority are the approval for this routing. Choosing or
  changing the profile for a task asks no question and needs no further approval, and your
  existing authorizations stay valid.
- With `auto_route` off, each role is pinned to the first owner-ordered profile allowed
  it. When that profile is held, rate-limited or cooling down, the role waits and the
  block is reported. Another profile is never substituted.
- Routing uses actual native observations. For Claude, that is the `rate_limit_event`
  status and reset in the stream. Unknown availability is never treated as zero use or as
  available. The next real bounded task is the probe. Codex quota events have no verified
  shape and are not captured, so there is no quota parity between providers.
- A routing observation is recorded at the attempt's actual end: the validated `endedAt`
  of its finalized lifecycle record, kept separately from the time the engine harvested
  the result. Evidence order is that end time, never arrival order. Without a valid
  `endedAt` nothing is recorded (`lifecycle_end_unknown`) and no time is substituted, so a
  delayed result cannot pose as newer than an operator refresh.
- Profile IDs are aliases for directories you authorized. Separate profiles do not prove
  separate quota or independent accounts.
- An auth or permission failure holds that profile until you queue an explicit refresh:
  `refresh-profile --state <dir> --profile <id> --actor <name>`. A refresh does not log in
  or verify anything. It lets the next real task probe again.
- An optional Codex review profile uses your existing Codex authentication. It is not
  another Claude account. Adding or removing a profile later is a policy change (section 6).

## 2. Statement of work and authority

Policy and approval are separate files. A **plan** (statement of work) says what to do. An
**authority** declaration approves exactly one plan digest and the effects it may use.

Plan fields (all required): `version` (1), `id`, `objective`, `input_revision`, exact
`base_sha`, and `tasks`. Each task has `id`, `objective`, `kind` (`feature`, `bugfix`,
`refactor`, `investigation`), `depends_on`, `write_scope` (repository-relative; a
directory entry ends in `/`; only `investigation` may be empty), `resources`, `checks`
(declared IDs) and `acceptance` (one or more criteria). Dependencies must exist and form no
cycle. Task IDs must be unique across every plan in the state. Tasks whose write scopes or
resources overlap are serialized.

This plan is an untested illustrative template. Replace every placeholder:

```json
{
  "version": 1,
  "id": "<plan-id>",
  "objective": "<what the whole plan must achieve>",
  "input_revision": "<issue, request or document revision>",
  "base_sha": "<full commit SHA>",
  "tasks": [
    {"id": "<task-a>", "objective": "<...>", "kind": "bugfix", "depends_on": [],
     "write_scope": ["src/<module>/"], "resources": [], "checks": ["<check-id>"],
     "acceptance": ["<observable criterion>"]},
    {"id": "<task-b>", "objective": "<...>", "kind": "feature", "depends_on": ["<task-a>"],
     "write_scope": ["tests/<module>/"], "resources": [], "checks": ["<check-id>"],
     "acceptance": ["<observable criterion>"]}
  ]
}
```

Print the canonical digest, then write the authority yourself:

```bash
python3 "$CTL" digest --plan /absolute/plan.json --policy /absolute/private/policy.json
```

The authority file is also an untested template. It must be 0600, outside the repository,
and pass the same private-file checks as the policy:

```json
{"version": 1, "plan_digest": "<digest output>", "effects": ["commit", "integrate"],
 "authorizer": "<who approves>", "approved_at": "<UTC timestamp ending in Z>"}
```

- The controller never creates or auto-approves authority, and never takes approval from
  worker output.
- `effects` cannot widen the policy effects. External effects need a policy `delivery`
  target.
- `approved_at` may not be more than 5 minutes in the future.
- A changed plan needs a new plan ID. A known ID with different content is refused.

## 3. Submit, run and status

```bash
python3 "$CTL" submit --state <dir> --plan /absolute/plan.json --authority /absolute/private/authority.json
python3 "$CTL" run --state <dir>              # foreground; Ctrl-C requests STOP
python3 "$CTL" run --state <dir> --once       # one pass
python3 "$CTL" status --state <dir> [--json]  # read-only
```

What `run` does:

- It takes the repository lease (the lock in the Git common directory). If another
  controller holds it, it prints `another controller holds this repository; nothing ran`
  and ends INCOMPLETE.
- Before dispatching anything, it settles every unresolved attempt, effect and controller
  query left by an earlier run (section 4). A released native session that is still alive
  is re-attached; other live owned processes are stopped and settled.
- It then loops: consume pending requests, advance admitted plans, and wait
  `--poll-seconds` (default 5, range 0.5-3600) when idle. `--once` returns after a pass in
  which nothing is running and nothing changed.
- Its outcome is PASS only when every current admitted plan passed every gate, including
  the whole-candidate review and any requested publication stage. FAIL means a recorded
  failing check or review, or an exhausted attempt budget. Everything else (STOP, a hold,
  waiting, nothing admitted) is INCOMPLETE.
- If the runtime or rules identity changes while it runs, nothing new starts, running work
  settles, and it ends INCOMPLETE until a reconcile (section 5).

- `submit` and `refresh-profile` validate their input and **queue** one immutable private
  request. They take no lock, so they work while a controller runs. A request is pending
  until a controller that holds the repository lease admits it through the ledger.
  Requests stay pending under STOP.
- The states are distinct and reported separately: **queued, admitted** (recorded, not
  started), **executed** (a native attempt or check ran), **verified** (a v1 check receipt
  and a fresh independent review at the exact result SHA), **integrated, published,
  merged**.
- `run --background` is still this foreground process. The flag only asserts that the
  policy has `background_enabled`. Supervising it, for example from a terminal multiplexer
  you start yourself, is your own explicit choice. Nothing in this framework sets that up.
- `status` shows control and fence, the context epoch with any HOLD, runtime/rules identity
  match, profiles, stale plans, task and request counts, unresolved attempts (including
  `unknown`), unresolved effects, workspaces not removed and charged seconds. Monetary cost
  is shown as not measured.

### How work flows

- The original checkout is never a worker workspace. Each task runs in a controller-owned
  linked worktree under `--state`, on a branch the controller creates. A dependent task's
  base includes its accepted dependencies.
- A fresh linked worktree holds committed files only. Ignored or untracked files, such as
  local secrets, `.env` or local settings, are not copied. Native project trust,
  permissions and settings for that path come from the native CLI's own rules and can differ
  from your main checkout. A missing or denied prerequisite ends the attempt as an
  availability hold or INCOMPLETE. The controller never adds a bypass flag. It never passes
  model, effort, permission, approval, sandbox, resume or trust flags.
- Overrides a worktree would silently lose block execution. If the repository has an
  untracked `CLAUDE.local.md`, `.claude/settings.local.json` or `AGENTS.override.md`, or a
  directory above the repository (and not above the state's worktrees) holds `CLAUDE.md`,
  `CLAUDE.local.md`, `AGENTS.md` or `AGENTS.override.md`, every plan is held INCOMPLETE
  (`native_override_unsupported`). No weaker defaults are substituted.
- The worker leaves its changes uncommitted. The controller checks the branch, HEAD and
  `write_scope`, then commits through its `task.commit` effect. Changes outside the scope
  hold the task for the owner (`scope_violation`).
- An `investigation` task that changes nothing succeeds with its execution base as the
  result. Integration then observes that result as already contained in the checkpoint and
  records a confirmed, journalled `integrate` effect without running a command or creating
  an empty commit. Its contribution is recorded like any other, and the whole candidate
  still needs fresh union checks and a fresh whole-result review.
- A task whose earlier result was not accepted is rebound at the current checkpoint. Its
  old worktree and commit are kept; unexpected changes in that worktree hold the task.
- Declared checks run as owned local processes and are recorded as `verified-handoff` v1
  receipts bound to the exact SHA. A finished process is not a verdict.
- Accepted tasks integrate **sequentially** into one plan-owned private integration
  worktree per context epoch, using a normal `git merge --ff-only` or `--no-ff` with hooks
  running. A stopped merge is preserved for you to resolve. Reset, clean, stash and
  checkout of your work are never used.
- After every accepted task is integrated, a derived whole candidate is recorded. It needs
  its own run of the union of all declared checks and a fresh review of plan
  origin..result. Task reviews never approve the combined tree.
- An earlier `integrate` or candidate effect is reused only when it belongs to the current
  plan workspace and checkpoint. Anything else is never adopted: foreign or drifted state
  is held.

## 4. Pause, STOP and recovery

```bash
python3 "$CTL" pause  --state <dir>   # block new claims (refused while stopped)
python3 "$CTL" stop   --state <dir>   # durable STOP: blocks claims, releases and effects
python3 "$CTL" resume --state <dir>   # explicit owner action; the only way to clear STOP
python3 "$CTL" recover --state <dir>  # settle positively owned work only
```

- The first SIGINT, SIGTERM or SIGHUP to `run` records a durable STOP. A second signal
  exits immediately.
- On STOP, `run` asks its owned work to stop, waits for it to settle and ends INCOMPLETE.
  Nothing is rolled back, and nothing new starts until an explicit `resume`.
- STOP also reaches an effect that is running synchronously. While an effect command
  settles, the engine polls the durable control about every quarter second, so a STOP
  written by another CLI process cancels it within that interval plus the helper's bounded
  drain. An unreadable control or an identity change also cancels it (fail closed). An
  interrupted mutation settles `unknown` and is never replayed.
- A control change clears no unresolved attempt or effect. The command prints what is still
  held.
- `recover` works under a context HOLD. It stops live owned processes (it does not
  re-attach them), settles what it can, and ends PASS only when no owned attempt, effect or
  query remains unresolved; otherwise INCOMPLETE. It never executes tasks, admits
  requests, clears STOP, reconciles or removes a workspace.

What recovery records:

- Every effect journals its intent with a random token naming a private evidence root
  that is created before the intent is recorded. If that root is missing, the token is
  missing or invalid, the root is unsafe, unreadable or empty, holds anything other than
  the effect's own call directories, or a call directory lacks its first record, the
  effect is held `unknown`. Lost evidence is never read as "nothing ran", never observed as
  a fresh start and never retried.
- For a remote effect whose provider reads can lag (`pr.create`, `pr.merge`), or an
  external mutation that may already have run, absence proves nothing: only a fresh
  positive observation resolves it.
- An attempt whose process cannot be finalized stays `unknown` and is never blindly
  retried. An implementation attempt whose `task.commit` is still unresolved stays open
  until that commit is observed; it is never re-implemented.
- Effects are at-least-once attempts with observation-based deduplication, not
  exactly-once. Cleanup acts only on processes, commands and effects the controller can
  prove it owns. Escaped descendant processes are handled best effort; there is no process
  containment guarantee.

### Removing managed worktrees

```bash
python3 "$CTL" stop --state <dir>
python3 "$CTL" cleanup-workspaces --state <dir> --plan-id <id> --actor <name>
```

`cleanup-workspaces` is the only command that removes a worktree. `recover`, STOP, idle
polling and every other path never do.

- It needs a durable STOP (otherwise FAIL `control_required`, nothing removed) and one
  explicit plan ID. It works under a context HOLD and never clears STOP, resumes or
  reconciles. If STOP is cleared while it runs, it stops with INCOMPLETE.
- It first settles owned work, then refuses while any attempt or effect of that plan is
  unsettled.
- It selects only worktrees whose creation the ledger journal confirmed for that plan, with
  the branch, path, common directory and expected HEAD the journal records (the creation,
  the last confirmed `task.commit`, or the recorded integration checkpoint), never the
  current HEAD. Each removal is its own journalled, strict `worktree.remove` effect.
- A worktree is retained, with a named reason, when it is dirty, has untracked or ignored
  content, holds a controller review-evidence bundle, is foreign-owned, symlinked or
  unreadable, has a moved HEAD or unknown ref, or its journal does not match. Nothing is
  forced, cleaned, reset or rebased.
- Branches, commits, raw logs, receipts and ledger history are always kept.
- It ends PASS only when every selected worktree of the plan is confirmed removed;
  otherwise INCOMPLETE with the retained paths.
- Removing a plan's integration worktree is final for that plan in that context epoch.
  Do not run it on an unfinished plan of the current context and expect `resume` to
  continue it: that plan can continue only after a later reconcile records a new context
  (an unchanged policy and identity append none) and you readmit it.

## 5. Updates

Ordinary source updates are `./install.sh --update`, `scripts/install-delivery.py` and
`./install-codex.sh --user`. They replace the skill files, including the controller
scripts. They never touch `--state`, the Git-directory binding, your private policy or
authority files, history or STOP. They ask no policy questions, discover or enable no
accounts, and install no service or schedule. A completed `./install.sh --update` prints a
short informational note about the controller; a run that backs off because another
install holds the lock prints none.

If the update changed the runtime bytes, or you changed committed instruction files or
the policy, the recorded context no longer matches. `status` shows `HOLD`, and `submit`,
`run` and `readmit` refuse (`identity_changed`). Only `recover`, `cleanup-workspaces` and
read-only commands work until you reconcile.

Preferred sequence for an update or policy change with an unfinished plan:

```bash
python3 "$CTL" stop --state <dir>
python3 "$CTL" recover --state <dir>                        # settle live owned attempts and effects
# install the update now, or prepare the new policy file (section 6)
python3 "$CTL" reconcile --state <dir> --actor <name>       # or add --policy /absolute/new-policy.json
python3 "$CTL" cleanup-workspaces --state <dir> --plan-id <id> --actor <name>
python3 "$CTL" digest --plan /absolute/plan.json --policy /absolute/private/policy.json
# write a NEW authority for that unchanged digest, approved after the reconcile
python3 "$CTL" readmit --state <dir> --plan-id <id> --authority /absolute/private/new-authority.json --actor <name>
python3 "$CTL" resume --state <dir>
python3 "$CTL" run --state <dir>
```

- `reconcile` needs STOP and no unresolved attempts or effects. It appends a new context
  epoch, keeps STOP and all earlier history, and makes every earlier plan stale. An
  unchanged policy and identity append nothing.
- `readmit` holds (`held: attempts N, effects N, workspaces N`, INCOMPLETE) while the plan
  has unsettled attempts or effects or any controller-created worktree without a confirmed
  removal. That is why the scoped cleanup comes first. A retained worktree keeps the hold
  until you resolve its named reason yourself; never delete worktrees or edit the ledger
  to work around it.
- Readmission needs a **new** authority for the unchanged plan digest, approved no earlier
  than the new epoch (`authority_stale` otherwise). A changed scope or objective needs a
  new plan ID.
- After readmission, every unpublished task loses its binding and acceptance; counters,
  results, receipts, effects and history are kept. Checks and a fresh review must be earned
  again in the new context, and an unpublished candidate of the earlier context is
  superseded.
- A task whose result was preserved (implemented or checked) is rebound at its **original**
  execution base and dependencies, never at a newer checkpoint, and only when Git proves
  that base still exists and contains the plan origin and every dependency result, every
  dependency is accepted and integrated with exactly that result, and the journal proves
  the result is the single-parent `task.commit` of that binding inside `write_scope` (or
  the base itself for a no-change investigation). A new worktree is created at that exact
  result, and its checks and a fresh review rerun. Nothing is re-implemented, rebased,
  cherry-picked or reset. If the proof fails, the task is held with a named reason
  (`preserved_result_unproven`, `preserved_result_dependency_changed`,
  `preserved_result_base_missing`, `preserved_result_base_unproven`).
- `resume` is a separate explicit owner action; neither `reconcile` nor `readmit` clears
  STOP.

## 6. Changing policy

1. Copy your policy to a **new** private file (0600, outside the repository) and edit the
   copy.
2. Follow the section 5 sequence, passing `reconcile --policy /absolute/new-policy.json`.

Never edit the policy snapshots, `ledger.sqlite3` or request files inside `--state`, and
never edit the binding in the Git directory. Re-running `setup` does not change policy.

The current ledger schema is the only supported one. State written by an earlier
pre-release ledger schema is refused (`unsupported_schema`). There is no migration or reset
path, and none is documented here. Keep such a directory as evidence.

## 7. Publication and merge

Automatic external publication (`push`, `pr`, `merge`) needs all of the following:

- the effect allowed in policy **and** in the plan authority, against the frozen
  `delivery` target. Branches must sit inside `branch_prefix`, and a worker-supplied remote,
  repository or base that differs is refused.
- a current, accepted, **integrated whole candidate**
- an approving review of that frozen candidate by an **owner-configured Codex profile**,
  from a released, successful attempt in the current context. This is an actual Codex
  decision, not a Python check, and no local check substitutes for it. One fresh Codex
  whole-candidate review can also serve as the independent review. A Claude review never
  substitutes. The ledger records which configured profile reviewed and cannot prove that
  a native Codex ran.

Without a configured, eligible Codex profile, local acceptance and integration still work
and are kept. Publication ends INCOMPLETE (`codex_review_required` or another named
block), and the controller writes an attended handoff record in the state's `handoffs`
directory. No cross-provider review is faked. This executor does not support role
overrides.

`merge` is conservative:

- It needs non-empty `required_checks` passing at the exact head, plus fresh reads of the
  base and head.
- It also needs readable **classic** branch protection with strict status checks and
  enforced admins, and the merge queue proven off.
- Ruleset-only governance, a merge queue, or unreadable or loose protection holds as
  INCOMPLETE without mutating anything.
- There is no `--admin`, `--auto`, rebase, force or hook skip. After the merge, the merged
  commit's parents and tree are verified.
- GitHub has no compare-and-swap on the base. A foreign push or a governance change inside
  that window shows up as an identity mismatch and is not rolled back. Upstream governance
  is assumed to stay stable.

Merge, release and deployment remain separately authorized states. The controller
implements neither release nor deployment.

## Verification for maintainers

The engine's black-box scenarios live in `tests/codex/test_controller_engine.py` and drive
only the operator CLI against disposable repositories, state and synthetic native
executables. Before a controller change is published, maintainers run the repository
checks at the exact commit (`python3 -m unittest discover -s tests/codex -v`,
`python3 tests/codex/mutations.py`, `./validate.sh`, `bash tests/gap/run.sh`), an
independent review of that commit and, for runtime claims, a native smoke run with real
CLIs in a disposable repository. This guide records none of those outcomes; report only
checks that actually ran.

## Limits

- Same-user private files give integrity against accidents, not authenticity or tamper
  resistance. The controller is not an OS sandbox. Declared checks and native CLIs execute
  project code with your permissions.
- There is no exactly-once delivery, no process containment guarantee, no network or shared
  SQLite, and no distributed or SLO guarantee. Agent quality, throughput and uptime have
  not been benchmarked.
- Cost: `max_cost_usd` is `null` only. Native cost and quota are recorded only where the
  native stream provides them.
- Retention: worktrees, branches, commits, raw logs, receipts, handoff records and ledger
  history are kept. Nothing is pruned automatically; the only removal is the explicit
  `cleanup-workspaces` of section 4.
- Results depend on available machines, credentials, quota and project tools.
- Scheduling is separate. The controller is not a session cron, a Desktop scheduled task
  or a cloud scheduled task (formerly routines). See the `scheduled-tasks` and
  `remote-triggers` skills and the official
  [scheduled tasks](https://code.claude.com/docs/en/scheduled-tasks) and
  [cloud scheduled tasks](https://code.claude.com/docs/en/routines) documentation. A cloud
  scheduled task in the default Anthropic-managed environment works on a fresh clone and
  cannot reach this machine's files or this controller state. A self-hosted environment
  reaches only what that environment provides, so discover it rather than assume.
