# Contributing to Claude Agents

Thanks for considering a contribution. This framework is meant to be shared and
improved by a team, so the contribution flow is intentionally light.

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

- Branch off `main`. No long-lived feature branches.
- Use a topic prefix matching the [conventional-commits](https://www.conventionalcommits.org/) scope you'll use in the commit:
  - `feat/<scope>` — user-visible new capability
  - `fix/<scope>` — bug fix
  - `docs/<scope>` — documentation only
  - `chore/<scope>` — internal cleanup
  - `refactor/<scope>` — restructure without behavior change
- Open a PR against `main`. CI (`.github/workflows/validate.yml`) runs `./validate.sh` on every PR.
- One reviewer minimum before merge. Squash-merge is the default.

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

1. **`./validate.sh`** — must report `0 Errors`, `0 Warnings` (all checks Passed; count auto-discovered).
2. **`bash -n` syntax check** — every shell file you touched:
   ```bash
   bash -n install.sh validate.sh quick-install.sh global-config/hooks/*.sh global-config/daemon/*.sh
   ```
3. **Healthcheck round-trip** — if you changed `session-start-healthcheck.sh`:
   ```bash
   ~/.claude/hooks/session-start-healthcheck.sh && echo OK
   ```
4. **Drift-and-heal test** — if you touched `sync_hooks` or any reconciler. This is a gap test:
   inject the drift, confirm the heal, restore. Do it in a **throwaway `HOME`**, not your real one:
   ```bash
   FAKE=$(mktemp -d)
   HOME="$FAKE" ./install.sh --update >/dev/null      # seed an isolated install
   jq 'del(.env.CLAUDE_CODE_EFFORT_LEVEL)' "$FAKE/.claude/settings.json" | sponge "$FAKE/.claude/settings.json"
   HOME="$FAKE" ./install.sh --update >/dev/null
   jq -r '.env.CLAUDE_CODE_EFFORT_LEVEL' "$FAKE/.claude/settings.json"   # -> "xhigh"
   ```
   **Know which drift shapes your reconciler actually heals, and do not assume.** The policies
   differ per key, and they are not interchangeable:

   | Key | Missing | Drifted value |
   |---|---|---|
   | `.hooks`, `.permissions`, `.attribution`, `.statusLine` | restored | **restored** (replace-on-drift) |
   | `.env.*` | restored | **not restored** — the env merge is *add-only*, so your values survive |

   So the missing-key test above passes, while `CLAUDE_CODE_EFFORT_LEVEL="low"` survives an
   `--update` unchanged. That is intentional for `.env`. If you change any of it, gap-test **both
   columns** — a reconciler that adds a missing key but ignores a wrong one heals nothing in
   practice, and you cannot tell the two apart without running them.
5. **Run what your docs tell users to run.** If your change documents a command, execute it, then
   re-run `./validate.sh` and check `git status` **including ignored files**. Running a shipped
   Python script once dropped a `__pycache__/` into the source tree, turned `validate.sh --quick`
   red on a clean checkout, and handed the watchdog drift it could not heal — an hourly loop caused
   by following the README. See [FAILURE-MODES.md §8](./docs/FAILURE-MODES.md#8-following-the-documentation-must-not-break-the-framework).

## Adding components

| Component | Where it lives | Required parts |
|---|---|---|
| **Agent** | `.claude/agents/<name>.md` | YAML frontmatter with `name`, `description`, `tools`; add row to CLAUDE.md agents table; add patch function in `install.sh` if it might appear in older CLAUDE.md installs |
| **Skill** | `.claude/skills/<name>/SKILL.md` | YAML frontmatter with `name`, `description`; add category line in CLAUDE.md Skills section |
| **Command** | `.claude/commands/<name>.md` | YAML frontmatter with `description`, `argument-hint`; add bullet in CLAUDE.md Developer Workflow Commands |
| **Rule** | `.claude/rules/<name>.md` | Plain markdown; no frontmatter required — rules are always-on |
| **Hook** | `global-config/hooks/<name>.sh` | Shell script; wire into `global-config/settings.json.template` `.hooks.<Event>`; document in CLAUDE.md Hooks section |

After any of the above, run `./validate.sh` — it auto-discovers and validates the new component.

## Updating an installation

The framework installs once, user-global, to `~/.claude`, so it applies to every
project on the machine. After pulling a new version, run `./install.sh --update` to
reconcile `~/.claude` — or let the self-healing watchdog / SessionStart healthcheck
reconcile it automatically.

## Self-healing safety net

The framework reconciles its own deployed state via:
- **SessionStart healthcheck** (`global-config/hooks/session-start-healthcheck.sh`)
- **launchd watchdog** (`global-config/daemon/claude-framework-watchdog.sh`)

If your change touches reconciliation logic, also verify that both still exit `0`
on clean state and log to `~/.claude/analytics/framework-health.jsonl` correctly.
Full runbook: **[SELF-HEALING.md](./SELF-HEALING.md)**.

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
