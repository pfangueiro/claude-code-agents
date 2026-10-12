# Scheduled work in Codex

Schedule only when the user requested recurring work. Discover whether this host
exposes scheduling/automation tools and inspect their supported fields, timezone,
ownership, run environment and persistence. Claude's session `CronCreate` APIs
and seven-day lifetime are not a Codex contract.

When scheduling exists, define the executable prompt, repository/input selection,
read/write scope, authorization, cadence/timezone, output destination and failure
reporting. Create/update the schedule through the actual tool, inspect the returned
schedule and report its identifier and next run. A task definition must not imply
approval for deployment, messages, or live-data changes on future runs.

If this session cannot create schedules, state that no schedule was created. Provide
a concrete proposed automation or host scheduler command only if requested; do not
silently install launchd/cron entries or replace a recurring job with a polling loop.
