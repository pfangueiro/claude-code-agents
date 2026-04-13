---
name: scheduled-tasks
description: Schedule recurring or one-shot tasks using CronCreate/CronDelete/CronList. Auto-activates on schedule, recurring, cron, periodic, poll, remind, every N minutes, timer, interval, check every.
---

# Scheduled Tasks

Schedule recurring or one-shot prompts using Claude Code's built-in cron tools.

## When to Use

- Poll CI/CD pipeline status at intervals
- Set reminders during long-running work
- Periodic quality checks (lint, test, build)
- Monitor external resources or services
- Recurring data collection or reporting

## Tools

### CronCreate
Schedule a recurring or one-shot prompt.

**Parameters:**
- `cron` (required) — Standard 5-field cron expression: `minute hour day-of-month month day-of-week`
- `prompt` (required) — The prompt to execute at each fire time
- `recurring` (optional, default: true) — `false` for one-shot reminders
- `durable` (optional, default: false) — `true` to persist across session restarts

**Returns:** Job ID for managing the schedule.

### CronDelete
Cancel a scheduled job by its ID.

### CronList
List all active scheduled jobs in the current session.

## Cron Expression Syntax

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-7, 0 and 7 = Sunday)
│ │ │ │ │
* * * * *
```

**Common patterns:**
- `*/5 * * * *` — Every 5 minutes
- `7 * * * *` — Every hour at :07
- `3 9 * * 1-5` — Weekdays at 9:03am
- `57 8 * * *` — Daily at ~9am (avoid :00 for load distribution)

**One-shot (pinned):**
- `30 14 15 4 *` — Once at 2:30pm on April 15

## Constraints

- **Session-scoped**: Jobs only fire while the REPL is idle (not mid-query)
- **7-day max**: Recurring tasks auto-expire after 7 days
- **No persistence by default**: Jobs are lost when Claude exits unless `durable: true`
- **Jitter**: Recurring tasks may fire up to 10% of their period late (max 15 min)

## Patterns

### Poll CI Status
```
CronCreate:
  cron: "*/3 * * * *"
  prompt: "Check the CI status of the current branch with `gh run list --branch $(git branch --show-current) --limit 1` and notify me if it completed or failed"
```

### Periodic Quality Check
```
CronCreate:
  cron: "7 * * * *"
  prompt: "Run the linter and type checker. If there are new errors since the last check, show them to me"
```

### One-Shot Reminder
```
CronCreate:
  cron: "30 14 1 4 *"   (pinned to specific date/time)
  prompt: "Remind me to check the deploy status"
  recurring: false
```

## Sleep/Resume for Autonomous Monitoring

Agents can self-suspend and resume without user prompts using combinations of cron and sleep patterns:

### Periodic Wake-Check-Sleep
```
CronCreate:
  cron: "*/10 * * * *"
  prompt: "Check CI status for the current branch. If build failed, alert the user. Otherwise, do nothing."
```
The agent wakes every 10 minutes, checks status, and goes back to idle. Each wake-up costs one API call.

### Durable Scheduling (Survives Restart)
```
CronCreate:
  cron: "0 9 * * 1-5"
  prompt: "Run the test suite and report any failures"
  durable: true    # persisted to ~/.claude/scheduled_tasks.json
```
Durable crons reload on next session start — true persistent scheduling.

## Best Practices

- Avoid `:00` and `:30` minute marks — pick off-minutes to reduce API load spikes
- Keep prompts focused and actionable — the scheduled prompt runs with full agent context
- Use `CronList` to audit active jobs before creating new ones
- Clean up with `CronDelete` when a monitoring task is no longer needed
- For one-shot reminders, always set `recurring: false`

## Related

- `/loop` skill — Higher-level recurring task wrapper
- `/schedule` skill — Remote agent triggers (survives session exit)
- `experiment-loop` skill — Metric-driven optimization with iteration
