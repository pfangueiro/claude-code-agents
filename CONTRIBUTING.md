# Contributing to the shared SDLC framework

Thanks for considering a contribution. This framework is meant to be shared and
improved by a team, so the contribution flow is intentionally light.

One repository supplies both integrations. Claude domain sources remain in `.claude/`;
Codex runtime replacements live in `codex/overrides/`. Read [AGENTS.md](AGENTS.md) and
[MEMORY.md](MEMORY.md) before changing shared behavior. Generated installations are
outputs, not checked-in canonical sources.

> **Read [docs/FAILURE-MODES.md](./docs/FAILURE-MODES.md) before you write a check, a guard, a gate,
> or a fix.** It documents the nine defect classes that actually shipped in this repository across
> six rounds of execution-based stress testing — with the real examples, including the guards that
> could not fail and the CI that could not pass. The same shapes keep coming back; recognising them
> is most of the work.

## Quick setup

```bash
git clone https://github.com/pfangueiro/claude-code-agents.git
cd claude-code-agents
HOME="$(mktemp -d)" ./install.sh               # try a full install into a throwaway HOME first (never touches your real ~/.claude)
./install.sh                                   # then install for real, once, user-global into ~/.claude
./validate.sh                                  # all checks should pass clean (count auto-discovered)
```

## Branching + PRs

For Codex development, use Python 3.11+ with `codex/requirements.txt`, then run
`python3 -m unittest discover -s tests/codex -v` and `python3 tests/codex/mutations.py`.
An isolated native CLI discovery test runs when Codex is installed; CI explicitly skips
that native test when no CLI exists. Do not call that skip an end-to-end pass.

- Branch off `main`. No long-lived feature branches.
- Use a topic prefix matching the [conventional-commits](https://www.conventionalcommits.org/) scope you'll use in the commit:
  - `feat/<scope>` — user-visible new capability
  - `fix/<scope>` — bug fix
  - `docs/<scope>` — documentation only
  - `chore/<scope>` — internal cleanup
  - `refactor/<scope>` — restructure without behavior change
- Open a PR against `main`. On every PR, CI (`.github/workflows/validate.yml`) runs `./validate.sh`, the gap
  mutation suite, the Codex adapter tests and mutation controls, and the shell-syntax and YAML checks.
- One reviewer minimum before merge, following [Review and acceptance](#review-and-acceptance).
  Squash-merge is the default.

## Commit messages

Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`).
Include scope when relevant: `feat(install):`, `fix(hooks):`, `docs(README):`.

**No attribution trailers.** Do not add `Co-Authored-By:` or any assistant/AI trailer — commits are
authored by their author. This is enforced in config, not just convention: `install.sh` reconciles
`settings.json` `.attribution.commit` back to empty on every install and `--update`, and
`validate.sh --quick` asserts it on the live file.

Add the CHANGELOG bullet **in the same commit as the change**, citing the SHA. Changelog lag is this
repository's single most recurring audit finding.

## The two hard rules

Everything else here is a preference. These two are not.

### 1. Every guard must be gap-tested

Not "reviewed". Not "should catch it". **Injected, observed, restored:**

1. Introduce the defect the guard exists to catch.
2. Run the guard. Confirm it **FAILS**, and that the message names the real problem.
3. Restore the tree.
4. Run the guard again. Confirm it **PASSES**.
5. Put both outcomes in the commit message.

A guard you have only seen pass is a guard you have not tested. The dominant defect class in this
codebase is verification that always reports success — found in all six review rounds, twice inside
guards written specifically to prevent it. See
[FAILURE-MODES.md §1](./docs/FAILURE-MODES.md#1-fail-open-verification--gates-that-cannot-fail).

Corollaries, each earned the hard way:

- Prefer a guard that **executes the artifact** over one that greps for a string suggesting the
  artifact is correct. A grep is a proxy, and proxies drift.
- A guard must ship **in the same commit as the repair it demands**. Never merge a guard that fails
  on the current tree, and never narrow a guard to make it green.
- Changing an artifact's exit codes, output format, or paths means re-running the gap test of every
  guard that watches it. A later repair once made an earlier guard's detection branch unreachable —
  both commits green, same day.

### 2. A fix without a guard is incomplete

An unguarded fix silently regresses, and nobody finds out until the next full review round. If you
repaired something, add the check that fails when it comes back — in the same PR.

If a defect genuinely cannot be guarded, say so explicitly in the PR and add it to the CHANGELOG's
*Known open* section. Carried forward deliberately is fine. Carried forward silently is not.

## What to test before opening a PR

1. **`./validate.sh`** — zero errors in the applicable environment. Fresh/CI environments
   can warn that the user-global Claude install is absent; distinguish those expected
   skips from a failing installed-state invariant. Also run `bash tests/gap/run.sh --prove --jobs 4`.
2. **`bash -n` syntax check** — every shell file you touched:
   ```bash
   bash -n install.sh validate.sh quick-install.sh global-config/hooks/*.sh global-config/daemon/*.sh
   ```
3. **Healthcheck round-trip** — if you changed `session-start-healthcheck.sh`, run the deployed copy
   from a throwaway install, never against your real `HOME`:
   ```bash
   FAKE=$(mktemp -d); HOME="$FAKE" ./install.sh --update >/dev/null
   HOME="$FAKE" "$FAKE/.claude/hooks/session-start-healthcheck.sh" && echo OK
   ```
4. **Drift-and-reconcile test** — if you touched `sync_hooks` or any reconciler. This is a gap test:
   inject the drift, confirm that an explicit `--update` reconciles it, then restore. Do it in a
   **throwaway `HOME`**, not your real one:
   ```bash
   FAKE=$(mktemp -d)
   HOME="$FAKE" ./install.sh --update >/dev/null      # seed an isolated install
   S="$FAKE/.claude/settings.json"; T=$(mktemp "$FAKE/settings.XXXXXX")
   jq 'del(.statusLine) | del(.env.BASH_DEFAULT_TIMEOUT_MS) | del(.env.CLAUDE_CODE_EFFORT_LEVEL)' "$S" > "$T" && mv "$T" "$S"
   HOME="$FAKE" ./install.sh --update >/dev/null
   jq -c '[.statusLine.command, .env.BASH_DEFAULT_TIMEOUT_MS, (.env | has("CLAUDE_CODE_EFFORT_LEVEL"))]' "$S"
   # -> ["~/.claude/statusline.sh","60000",false]
   ```
   **Know which drift shapes your reconciler actually reconciles. Do not assume.** The policies
   differ per key, and they are not interchangeable:

   | Key | Missing | Drifted value |
   |---|---|---|
   | `.hooks` (framework bindings, by exact command path), `.permissions`, `.attribution`, `.statusLine` | restored | **restored** (replace-on-drift; foreign hook bindings are kept) |
   | `.env.*` except `CLAUDE_CODE_EFFORT_LEVEL` | restored | **not restored** — the env merge is *add-only*, so your values survive |
   | `.env.CLAUDE_CODE_EFFORT_LEVEL` | **left absent** on an existing settings file (only a fresh seed carries `xhigh`) | **not restored**; an unsupported value is reported, never rewritten |

   So the test above restores the status line and the timeout, and the deleted effort level
   stays absent. `CLAUDE_CODE_EFFORT_LEVEL="low"` also survives an `--update` unchanged. Both are
   intentional. If you change any of this, gap-test **every row and both columns**: a reconciler
   that adds a missing key but ignores a wrong one repairs nothing in practice, and you cannot
   tell the two apart without running them.
5. **Run what your docs tell users to run.** If your change documents a command, execute it, then
   re-run `./validate.sh` and check `git status` **including ignored files**. Running a shipped
   Python script once dropped a `__pycache__/` into the source tree, turned `validate.sh --quick`
   red on a clean checkout and, under the since-retired self-heal watchdog, caused an hourly loop
   just because someone followed the README. See [FAILURE-MODES.md §8](./docs/FAILURE-MODES.md#8-following-the-documentation-must-not-break-the-framework).

## Adding components

| Component | Where it lives | Required parts |
|---|---|---|
| **Agent** | `.claude/agents/<name>.md` | YAML frontmatter with `name`, `description`, `tools`; add row to CLAUDE.md agents table; add the name to the `AGENTS` array in `install.sh` (the installer copies and prunes only listed agents) and a `### <name>` entry in `.claude/skills/execute/references/agent-selection.md` (validated) |
| **Skill** | `.claude/skills/<name>/SKILL.md` | YAML frontmatter with `name`, `description`; add category line in CLAUDE.md Skills section |
| **Command** | `.claude/commands/<name>.md` | YAML frontmatter with `description`, `argument-hint`; add bullet in CLAUDE.md Developer Workflow Commands |
| **Rule** | `.claude/rules/<name>.md` | Plain markdown; no frontmatter required — rules are always-on |
| **Hook** | `global-config/hooks/<name>.sh` | Shell script; wire into `global-config/settings.json.template` `.hooks.<Event>`; document in CLAUDE.md Hooks section |

After any of the above, run `./validate.sh` — it auto-discovers and validates the new component.
For shared changes, verify Codex outputs too: native roles, skill metadata, explicit-only
policy, resource references and runtime overrides. Do not translate Claude tool
allowlists or model aliases into invented Codex settings.

## Updating an installation

The framework installs once, user-global, so it applies to every project on the machine.
Updates are explicit and run in the foreground. Pull, then follow
[Upgrading an existing installation](INSTALL.md#upgrading-an-existing-installation):
the delivery manifest first (if it exists), the broad `./install.sh --update` second, Codex
`./install-codex.sh --user` separately, then the read-only checks. Nothing reconciles
automatically. The broad installer replaces same-name files; the delivery and Codex
installers refuse customized or foreign files instead of overwriting them.

## Observe-only health checks

The SessionStart healthcheck (`global-config/hooks/session-start-healthcheck.sh`) and the
opt-in launchd watchdog (`global-config/daemon/claude-framework-watchdog.sh`) only observe.
They log findings to `~/.claude/analytics/framework-health.jsonl` (drift as
`manual_repair_required`, the watchdog verdict as `validation_result`), and they never run an
installer or repair anything. If your change touches them or the statusline, verify in a
disposable `HOME` that clean state is still reported as clean and drift as drift. Also run the
guards that protect the observe-only contract: `bash tests/gap/run.sh --prove --jobs 4`, and
`python3 -m unittest discover -s tests/codex -v` (which includes the background-health and
health-status tests). Full runbook: **[SELF-HEALING.md](./SELF-HEALING.md)**.

## Review and acceptance

The canonical procedures are `.claude/rules/verification.md`, `.claude/rules/code-quality.md`,
`/review-pr`, `/quality-gate`, `code-review-checklist` and
`.claude/skills/delivery/references/acceptance-by-task.md`. In short:

- Report concrete findings with their evidence class: runtime-reproduced, source-proven,
  unverified hypothesis or nonblocking suggestion. Do not use grades or invented metrics.
- Name the exact base and head SHA you reviewed. A new commit needs a new verdict.
- Report PASS, FAIL or INCOMPLETE for the declared scope. A required check that did not run
  is INCOMPLETE, and unknown is not zero.
- Reviewers do not review their own implementation. Implement, review, merge, deploy and
  release are separate states, and each needs its own authorization.

## Code style

See `.claude/rules/code-quality.md` for the always-on style rules. Highlights:
- Read before modify (Read tool before Edit; grep before refactor).
- Functions should do one thing. Prefer early returns.
- Default to no comments unless they encode non-obvious *why*.
- Bash: `set -uo pipefail`, guard `((var++))` with `|| true` under `set -e`,
  prefer `mkdir`-based locks over PID files where SIGKILL recovery matters.

## Privacy

This repo is public. Don't introduce hardcoded user-specific paths
(`/Users/<name>/...`), personal project names, or machine hostnames. Use
`$HOME`, `${USER}`, or `__HOME__` placeholders. See v2.9.4 CHANGELOG entry for
prior cleanup precedent.
