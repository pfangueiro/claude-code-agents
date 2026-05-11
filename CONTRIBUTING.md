# Contributing to Claude Agents

Thanks for considering a contribution. This framework is meant to be shared and
improved by a team, so the contribution flow is intentionally light.

## Quick setup

```bash
git clone https://github.com/pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh --full /path/to/a/test/project   # deploy into a sandbox first
./validate.sh                                  # 188+ checks should pass clean
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

1. **`./validate.sh`** — must report `188+ Passed`, `0 Errors`, `0 Warnings`.
2. **`bash -n` syntax check** — every shell file you touched:
   ```bash
   bash -n install.sh validate.sh deploy-all.sh global-config/hooks/*.sh global-config/daemon/*.sh
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

## Deploying changes across local projects

After a merge, anyone using `deploy-all.sh` can roll the new version into every
`~/local-codebase/*/` project. The driver creates per-project backups, writes a
JSONL manifest, and continues on per-project errors by default. See the script's
`--help` for `--dry-run`, `--halt-on-error`, `--only <name>`.

## Self-healing safety net

The framework reconciles its own deployed state via:
- **SessionStart healthcheck** (`global-config/hooks/session-start-healthcheck.sh`)
- **launchd watchdog** (`global-config/daemon/claude-framework-watchdog.sh`)

If your change touches reconciliation logic, also verify that both still exit `0`
on clean state and log to `~/.claude/analytics/framework-health.jsonl` correctly.

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
