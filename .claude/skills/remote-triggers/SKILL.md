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
| Survives session exit | No (session-scoped) | Yes (persistent) |
| Runs while REPL idle | Yes | Yes (server-side) |
| Max duration | 7 days | Unlimited |
| Setup complexity | Low | Medium |
| Requires auth | No | Yes (OAuth) |

**Rule of thumb**: Use CronCreate for in-session monitoring. Use RemoteTrigger for anything that must persist.

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
Create a new trigger with a schedule and prompt.
```
RemoteTrigger: {
  action: "create",
  body: {
    name: "nightly-security-scan",
    cron: "0 2 * * *",
    prompt: "Run /security-scan on the entire codebase and report findings",
    enabled: true
  }
}
```

### update
Update an existing trigger (partial update).
```
RemoteTrigger: {
  action: "update",
  trigger_id: "my-trigger",
  body: { enabled: false }
}
```

### run
Manually trigger an immediate execution.
```
RemoteTrigger: { action: "run", trigger_id: "my-trigger" }
```

## Use Case Patterns

### Nightly Security Scan
```
RemoteTrigger create:
  name: "nightly-security-scan"
  cron: "0 2 * * *"
  prompt: "Run /security-scan and create a GitHub issue if critical vulnerabilities are found"
```

### Pre-Release Quality Gate
```
RemoteTrigger create:
  name: "pre-release-check"
  cron: "0 8 * * 1-5"
  prompt: "Check if there are open PRs targeting the release branch. Run /quality-gate on each."
```

### Dependency Update Monitor
```
RemoteTrigger create:
  name: "dep-monitor"
  cron: "0 9 * * 1"
  prompt: "Check for outdated dependencies and create a summary issue if updates are available"
```

## Best Practices

- Use descriptive trigger names — they appear in `list` output
- Start with `enabled: false` and test with `run` before enabling the schedule
- Avoid scheduling during peak hours — spread triggers across off-peak times
- Use `update` to disable triggers temporarily rather than deleting them
- Monitor trigger execution results — failed triggers may need prompt adjustments

## Related

- `scheduled-tasks` skill — Session-scoped scheduling with CronCreate (lighter weight)
- `/schedule` command — Higher-level wrapper for RemoteTrigger
- `experiment-loop` skill — Metric-driven optimization loops
