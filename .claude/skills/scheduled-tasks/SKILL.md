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

## When NOT to Use a Cron

`CronCreate` re-runs a prompt at fixed wall-clock intervals. It is the wrong instrument for short waits and live watching — cron polls on a schedule and cannot fire mid-query, so it will not notice an event until its next tick. Reach for these instead:

| Need | Instrument |
|------|-----------|
| **One** notification when a condition becomes true ("tell me when the build finishes", "when the server is ready") | `Bash` with `run_in_background`, running a command that exits once the condition holds: `until grep -q "Ready in" dev.log; do sleep 0.5; done` |
| **One per occurrence**, as it happens ("tell me every time an ERROR line appears") | `Monitor` — each stdout line of a long-running script becomes an event, streamed in real time |
| **One per occurrence until a known end** (emit each CI step, stop when the run completes) | `Monitor` with a command that emits lines and then exits |
| Waiting a few seconds or minutes inside a task | `Monitor` with an until-loop — foreground `sleep` is blocked in `Bash` |
| Anything that must outlive the session | `RemoteTrigger` (`remote-triggers` skill) |

Use a cron only for genuinely periodic work on a wall-clock cadence. Note that an unbounded `Monitor` command (`tail -f`, `while true`) stays armed until its timeout, so use `Bash` + `run_in_background` when one notification is all that is wanted.

## Tools

### CronCreate
Schedule a recurring or one-shot prompt.

**Parameters:**
- `cron` (required) — Standard 5-field cron expression: `minute hour day-of-month month day-of-week`
- `prompt` (required) — The prompt to execute at each fire time
- `recurring` (optional, default: true) — `false` for one-shot reminders
- `durable` — **accepted but inert.** The tool schema states it "has no effect — durable persistence is not available. All jobs are session-only (in-memory, gone when this Claude session ends)." Do not pass it and do not treat it as persistence.

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

- **Session-only — treat persistence as unavailable**: as the live `CronCreate` schema reports it, jobs live only in this Claude session, nothing is written to disk, and every job is gone when Claude exits. Durable persistence is **feature-gated**: the `durable` parameter is real and the CLI ships an implementation behind it, but when the gate is off the schema states plainly that it "has no effect". **Read the `durable` description in the live schema before relying on it** — if it says "has no effect", it does. For scheduling that must survive session exit, use `RemoteTrigger` (see the `remote-triggers` skill) rather than betting on a gate.
- **Idle-only firing**: Jobs only fire while the REPL is idle (not mid-query)
- **7-day max**: Recurring tasks auto-expire after 7 days — they fire one final time, then are deleted. Tell the user about the 7-day limit when scheduling a recurring job.
- **Jitter**: Recurring tasks may fire up to 10% of their period late (max 15 min); one-shot tasks landing on `:00` or `:30` may fire up to 90s *early*

## Patterns

### Poll CI Status
```
CronCreate:
  cron: "*/3 * * * *"
  prompt: "Check the CI status of the current branch with `gh run list --branch $(git branch --show-current) --limit 1` and notify me if it completed or failed"
```
For a *single* CI run that is already in flight, prefer `Monitor` with a poll loop that exits when the run reaches a terminal state — it reports each check as it lands instead of waking the agent every 3 minutes indefinitely.

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

### Surviving a Restart

Not possible with a cron under the current schema — a job is gone the moment Claude exits, and `durable` reports "has no effect" while its gate is off. Do not promise the user persistence on the strength of that parameter; check the live schema text if it matters. Anything that must outlive the session belongs in `RemoteTrigger` (`remote-triggers` skill).

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
