---
name: scheduled-tasks
description: Schedule recurring or one-shot prompts with Claude Code's native cron tools (CronCreate/CronDelete/CronList) where the session exposes them, and choose a better instrument for one-event waits or work that must run without an open session. Relevant to schedules, recurring or periodic checks, polling, reminders, and intervals. Selection is model judgment, not keyword activation.
---

# Scheduled Tasks

Schedule recurring or one-shot prompts using Claude Code's native cron tools.

**Authoritative reference:** the official [scheduled tasks documentation](https://code.claude.com/docs/en/scheduled-tasks). Behavior summarized here was checked against it on 2026-11-14 and can change between Claude Code versions. Where this skill and the live docs or live tool schema disagree, the live source wins.

**Tool availability is not guaranteed.** The tool names below (`CronCreate`, `Monitor`, `RemoteTrigger`, and so on) reflect particular Claude Code versions, settings and permissions. Check which tools the current session actually offers before relying on one, and never describe a tool the session does not expose as if it exists.

**Never schedule silently.** Creating a cron job, a cloud/Desktop schedule, a CI workflow or any background service is an action the user must approve. Before creating one, tell the user the cadence, the expiry, what each run will do, and how to cancel it. This skill implements no scheduler, daemon or service of its own.

## When to Use

- Poll CI/CD pipeline status at intervals
- Set reminders during long-running work
- Periodic quality checks (lint, test, build)
- Monitor external resources or services
- Recurring data collection or reporting

## When NOT to Use a Cron

`CronCreate` re-runs a prompt at wall-clock times. It is the wrong instrument for short waits and live watching: cron fires on a schedule and not mid-turn, so it will not notice an event until a later fire. If the session exposes them, reach for these instead:

| Need | Instrument |
|------|-----------|
| **One** notification when a condition becomes true ("tell me when the build finishes", "when the server is ready") | `Bash` with `run_in_background`, running a command that exits once the condition holds: `until grep -q "Ready in" dev.log; do sleep 0.5; done` |
| **One per occurrence**, as it happens ("tell me every time an ERROR line appears") | `Monitor`, where available: each stdout line of a long-running script becomes an event |
| **One per occurrence until a known end** (emit each CI step, stop when the run completes) | `Monitor`, where available, with a command that emits lines and then exits |
| Waiting a few seconds or minutes inside a task | A background until-loop (`Monitor` or `Bash` + `run_in_background`), not a foreground `sleep` |
| Work that must run without an open session | A cloud, Desktop or GitHub Actions schedule. See [Work that must outlive the session](#work-that-must-outlive-the-session) |

Use a cron only for genuinely periodic work on a wall-clock cadence. An unbounded `Monitor` command (`tail -f`, `while true`) stays armed until its timeout, so use `Bash` + `run_in_background` when one notification is all that is wanted. Background `Bash` commands and monitors are **not** restarted when a session is resumed.

## Tools

### CronCreate
Schedule a recurring or one-shot prompt.

**Parameters** (read the live tool schema; parameters and their descriptions vary by version):
- `cron` (required): standard 5-field cron expression `minute hour day-of-month month day-of-week`
- `prompt` (required): the prompt to run at each fire time
- `recurring` (optional, default: true): `false` for one-shot reminders
- `durable` (if present): older observed schemas described this parameter as having no effect. Do not assume either way. Read its description in the live schema, and check the docs for what persistence the current version actually provides.

**Returns:** Job ID for managing the schedule.

### CronDelete
Cancel a scheduled job by its ID.

### CronList
List the scheduled jobs in the current session.

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
- `*/5 * * * *`: every 5 minutes
- `7 * * * *`: every hour at :07
- `3 9 * * 1-5`: weekdays at 9:03am
- `57 8 * * *`: daily at ~9am (avoid :00 for load distribution)

**One-shot (pinned):**
- `30 14 15 4 *`: once at 2:30pm on April 15

## Constraints

All of these come from the [official docs](https://code.claude.com/docs/en/scheduled-tasks) as checked on 2026-11-14. Re-check before you promise anything to the user.

- **Fires only while Claude is running and idle**: jobs fire between turns, not mid-turn, and only while the Claude Code process is running.
- **Resume restores cron jobs, with limits**: jobs created with `CronCreate` are restored when the session is resumed with `--resume` or `--continue`. Recurring jobs that have expired and one-shots whose time has passed are not restored. A restored recurring job does **not** catch up on fires it missed while the session was closed. A self-paced `/loop` is not restored.
- **Closing the session stops firing**: nothing fires while no session is running. Native background sessions can keep a session alive without a terminal, but supervisor, crash and machine-restart limits still apply, so this is not a guarantee of continuous execution.
- **7-day max**: recurring tasks expire after 7 days. They fire one final time and are then deleted. Tell the user about this limit when you schedule a recurring job.
- **Jitter**: fire times are deliberately offset from the nominal cron time. Recurring jobs can run late, and one-shots pinned to `:00` or `:30` can run slightly early. The bounds have changed between versions, so do not hardcode a formula. Link the user to the [current jitter rules](https://code.claude.com/docs/en/scheduled-tasks) and report the next-run time the tool actually gives you.

## Patterns

Each pattern below needs the user's approval before you create it (see **Never schedule silently** above).

### Poll CI Status
```
CronCreate:
  cron: "*/3 * * * *"
  prompt: "Check the CI status of the current branch with `gh run list --branch $(git branch --show-current) --limit 1` and notify me if it completed or failed"
```
For a *single* CI run that is already in progress, prefer a background poll loop (`Monitor` if available) that exits when the run reaches a terminal state. It reports each check as it finishes instead of waking the agent every 3 minutes indefinitely.

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

## Periodic Wake-Check While the Session Runs

While the session is running, a recurring job lets the agent check something periodically without the user prompting it:

```
CronCreate:
  cron: "*/10 * * * *"
  prompt: "Check CI status for the current branch. If build failed, alert the user. Otherwise, do nothing."
```
The agent wakes about every 10 minutes (subject to jitter), checks status, and goes idle again. Each wake-up costs one model call.

### Work that must outlive the session

A session cron can be restored on resume (see Constraints), but it does not fire while no session runs, and it does not catch up on fires it missed. For work that must run regardless of an open session, the [official docs](https://code.claude.com/docs/en/scheduled-tasks) describe cloud, Desktop and GitHub Actions options. Before you propose one, find out whether it is available in the user's environment, what authentication it needs, and whether the owner has authorized it. Do not assume a `RemoteTrigger` or similar tool exists. Do not claim a schedule exists until you have actually created it and seen it confirmed.

## Best Practices

- Avoid `:00` and `:30` minute marks. Pick off-minutes to reduce load spikes
- Keep prompts focused and actionable. The scheduled prompt runs with full agent context
- Run `CronList` to check existing jobs before creating new ones
- Clean up with `CronDelete` when a monitoring task is no longer needed
- For one-shot reminders, always set `recurring: false`

## Related

- `/loop` skill (where available): higher-level recurring wrapper. A self-paced loop is not restored on resume
- `/schedule` skill (where available and authorized): cloud-scheduled agents that do not depend on an open session
- `experiment-loop` skill: metric-driven optimization with iteration
