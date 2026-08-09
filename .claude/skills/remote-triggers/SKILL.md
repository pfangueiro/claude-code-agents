---
name: remote-triggers
description: Cross-session automation using RemoteTrigger API. Create, manage, and run scheduled remote agents that execute on cron schedules and survive session exit. Auto-activates on remote trigger, scheduled agent, cross-session, persistent schedule, automated agent, trigger API.
---

# Remote Triggers

Create and manage remote agent triggers that execute on schedules and survive session exit.

## When to Use

- **Persistent schedules**: Tasks that must run even after the session ends
- **Cross-session automation**: Recurring code reviews, automated deploys, health checks
- **Scheduled agents**: Run specific prompts on cron schedules in the background
- **Team automation**: Set up shared triggers that benefit the whole team

## How It Differs from CronCreate

| Feature | CronCreate | RemoteTrigger |
|---------|-----------|---------------|
| Survives session exit | No (session-only, in-memory) | Yes (server-side routine) |
| Runs while REPL idle | Yes | Yes (server-side) |
| Lifetime | Recurring jobs auto-expire after 7 days | No documented expiry; removed only at https://claude.ai/code/routines |
| Minimum interval | Any (5-field cron, per-minute) | **1 hour** — `*/30 * * * *` is rejected |
| Timezone | User's local time | **UTC** |
| Runs where | The user's local session | Isolated cloud session with its own git checkout — no local files, services, or env vars |
| Setup complexity | Low | Medium (needs `environment_id` + a full `job_config`) |
| Requires auth | No | Yes — OAuth injected in-process by the tool, never exposed |

**Rule of thumb**: Use CronCreate for in-session monitoring. Use RemoteTrigger for anything that must persist. For sub-hourly or event-driven watching, use neither — see `Monitor` in the `scheduled-tasks` skill.

## Tool: RemoteTrigger

**Actions:**

### list
List all configured triggers.
```
RemoteTrigger: { action: "list" }
```

### get
Get details of a specific trigger.
```
RemoteTrigger: { action: "get", trigger_id: "my-trigger" }
```

### create
Create a routine. There is **no** top-level `cron` or `prompt` field — the schedule field is `cron_expression`, and the prompt is carried inside `job_config`.

**Required:** `name`, exactly ONE of `cron_expression` / `run_once_at`, and `job_config`.

```json
{
  "action": "create",
  "body": {
    "name": "nightly-security-scan",
    "cron_expression": "0 2 * * *",
    "enabled": true,
    "job_config": {
      "ccr": {
        "environment_id": "<environment id>",
        "session_context": {
          "model": "claude-sonnet-5",
          "sources": [
            {"git_repository": {"url": "https://github.com/<org>/<repo>"}}
          ],
          "allowed_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
        },
        "events": [
          {"data": {
            "uuid": "<fresh lowercase v4 uuid>",
            "session_id": "",
            "type": "user",
            "parent_tool_use_id": null,
            "message": {"content": "Run /security-scan on the entire codebase and report findings", "role": "user"}
          }}
        ]
      }
    }
  }
}
```

**Field notes:**
- `cron_expression` — 5-field cron in **UTC**, minimum interval **1 hour**
- `run_once_at` — RFC3339 UTC timestamp in the future; fires once, then auto-disables. Mutually exclusive with `cron_expression`
- `job_config.ccr.environment_id` — required; selects the cloud environment to run in
- `job_config.ccr.events[0].data.message.content` — **this is where the prompt goes**
- `events[].data.uuid` — generate a fresh lowercase v4 UUID per routine
- `enabled` — optional, defaults to `true`
- `mcp_connections` — optional, `[{"connector_uuid": "...", "name": "...", "url": "https://..."}]`; `name` must match `[a-zA-Z0-9_-]` (no dots or spaces)

The response appends the server-parsed run time and the routine's claude.ai URL — relay both to the user.

### update
Update an existing routine (partial update — send only the fields that change).
```
RemoteTrigger: {
  action: "update",
  trigger_id: "my-trigger",
  body: { enabled: false }
}
```
Updatable fields: `name`, `cron_expression`, `run_once_at`, `enabled`, `job_config`, `mcp_connections`, and `clear_mcp_connections` (boolean, drops all MCP connections).

### run
Manually trigger an immediate execution. Body is optional.
```
RemoteTrigger: { action: "run", trigger_id: "my-trigger" }
```

### create_webhook_trigger
Attach an event source (for example a GitHub event) to an **existing** routine, so the routine fires on that event instead of a schedule. The body names the source and scope (such as a repository), the event list, a structured filter, and the `routine_trigger_id` to fire; the server validates the shape and rejects worker credentials. A webhook trigger has no schedule, so the response carries only the routine's claude.ai link.

### delete
Not available. There is no delete action — remove routines at https://claude.ai/code/routines, or use `update` with `enabled: false` to pause one.

## Execution Constraints

Routines do not run on the user's machine. Each fire spawns an isolated cloud session in Anthropic's infrastructure with its own git checkout:

- **No local access** — no local files, local services, or local environment variables. The cloud agent starts with zero context, so the prompt must be fully self-contained.
- **The repo comes from `sources`** — the agent sees whatever `job_config.ccr.session_context.sources[].git_repository.url` points at, nothing else.
- **UTC only** — `cron_expression` and `run_once_at` are always UTC. Convert from the user's local time and confirm the conversion with them.
- **Minimum interval is 1 hour** — sub-hourly crons are rejected. Use `CronCreate` or `Monitor` for anything faster.
- **Tool, not curl** — `RemoteTrigger` injects the OAuth token in-process; it is never exposed.

## Use Case Patterns

Each pattern uses the full `create` body above; only `name`, `cron_expression`, and the prompt at `job_config.ccr.events[0].data.message.content` differ. All three respect the 1-hour minimum interval and are expressed in UTC.

### Nightly Security Scan
- `name`: `nightly-security-scan`
- `cron_expression`: `0 2 * * *` (02:00 UTC)
- prompt: "Run /security-scan and create a GitHub issue if critical vulnerabilities are found"

### Pre-Release Quality Gate
- `name`: `pre-release-check`
- `cron_expression`: `0 8 * * 1-5` (08:00 UTC, weekdays)
- prompt: "Check if there are open PRs targeting the release branch. Run /quality-gate on each."

### Dependency Update Monitor
- `name`: `dep-monitor`
- `cron_expression`: `0 9 * * 1` (09:00 UTC, Mondays)
- prompt: "Check for outdated dependencies and create a summary issue if updates are available"

## Best Practices

- Use descriptive trigger names — they appear in `list` output
- Test a routine with `action: "run"` before relying on its schedule
- Avoid scheduling during peak hours — spread triggers across off-peak times
- Use `update` with `enabled: false` to pause a routine — this is the only in-tool way to stop one, since there is no delete action
- Relay the claude.ai routine URL from the `create`/`update` response — that is where execution results appear, and failed runs usually mean the prompt needs to be more self-contained

## Related

- `scheduled-tasks` skill — Session-scoped scheduling with CronCreate (lighter weight)
- `/schedule` command — Higher-level wrapper for RemoteTrigger
- `experiment-loop` skill — Metric-driven optimization loops
