# Contributing to Claude Agents

Thanks for considering a contribution. This framework is meant to be shared and
improved by a team, so the contribution flow is intentionally light.

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
Include `Co-Authored-By:` trailers for collaborative work.

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
4. **Drift-and-heal test** — if you touched `sync_hooks` or any reconciler:
   ```bash
   jq 'del(.env.CLAUDE_CODE_EFFORT_LEVEL)' ~/.claude/settings.json | sponge ~/.claude/settings.json
   ./install.sh --update
   jq -r '.env.CLAUDE_CODE_EFFORT_LEVEL' ~/.claude/settings.json  # should print "high"
   ```

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
