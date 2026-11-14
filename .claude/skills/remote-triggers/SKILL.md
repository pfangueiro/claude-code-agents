---
name: remote-triggers
description: Create, inspect, update or run cloud scheduled tasks (formerly routines) and remote triggers where the session exposes such a tool, by discovering its live schema and account scope first and then carrying out the concrete action the owner's existing authorization actually covers (create, update, run, send or deploy are distinct effects). Relevant to work that must run without an open local session. Selection is model judgment, not keyword activation.
---

# Remote Triggers and Cloud Scheduled Tasks

Work that must run without an open local session can sometimes run as a cloud scheduled
task (formerly called a routine) or remote trigger. This skill is a procedure for doing
that honestly. It implements no scheduler and assumes no tool exists.

**Authoritative references:** the official
[cloud scheduled tasks](https://code.claude.com/docs/en/routines) and
[scheduled tasks](https://code.claude.com/docs/en/scheduled-tasks) documentation. Limits
such as minimum interval, timezone, expiry, quotas and supported actions depend on the
runtime and can change between versions. Read the current docs and the **live tool
schema** before acting. Where this skill and the live source disagree, the live source
wins.

## Choose the instrument

| Need | Instrument | Notes |
|---|---|---|
| Periodic prompt while a local session runs | Session cron (`scheduled-tasks` skill) | Fires only while that session runs. Which tasks are restored on resume, and their expiry, follow the current docs for the installed version. |
| One wait or event inside the current task | Background command or `Monitor`, where exposed | See `scheduled-tasks` |
| Scheduled work on the owner's own machine without an open session | Desktop scheduled task, where available and authorized | Runs on that machine with its local access, as the Desktop docs describe. |
| Work that must run without this machine | Cloud scheduled task or CI schedule, where available and authorized | Runs in the environment the task is configured for: Anthropic-managed cloud by default, or an organization self-hosted environment. **Discover** that environment's checkout, connectors, credentials and access boundary; do not assume either. The default cloud environment works on a fresh clone and cannot reach this laptop's files, services or env vars. |
| Local multi-task delivery on this machine | The optional `delivery` controller (`scripts/controller.py`) | A foreground local process the owner starts and keeps running. It is not a scheduler, and a default cloud task cannot reach its private local state. |

## Procedure

1. **Authority must cover the actual action.** Creating, updating, running now, disabling,
   removing, sending a message from, or deploying through a routine are distinct effects.
   Proceed when the owner's instructions already authorize the concrete action and its
   scope: an explicit request in this session or a prior one counts, and so does an
   explicit invocation of this skill or `/schedule` with a concrete request. Do not
   invent authority: permission for one effect does not imply another, and sending
   messages, deploying or touching live data needs the owner to have asked for it. An
   approved recurring routine's schedule and scope cover the runs that schedule produces;
   individual scheduled runs need no fresh approval, but changing the schedule, prompt or
   scope does. Loading this skill grants nothing and never, by itself, calls for an extra
   confirmation. An explicit owner instruction takes precedence over this skill.
2. **Discover the capability.** Check whether this session actually exposes a routine or
   remote-trigger tool (for example `RemoteTrigger`). Read its live schema: the actions it
   offers, required fields, how the schedule and prompt are expressed, and what it returns.
   Never build a payload from memory or from an older example. If no such tool is exposed,
   say so and stop. Do not emulate one with curl or an API token.
3. **Establish scope.** Identify which account, organization and execution environment
   (Anthropic-managed or self-hosted) the task will run under, and what that environment
   can reach. Identify which repository sources (a fresh checkout), connectors, credentials
   and tools it receives, and what it may publish (issues, PRs, messages). Do not assume an
   MCP connector is connected.
   Discover it, or leave it out. Ask the owner only for material scope or authority that is
   actually missing (for example which account or repository, or whether the routine may
   publish), never to re-confirm what was already requested.
4. **Assemble the complete request.** Build the name, the trigger or schedule as the tool
   expresses it (with timezone), a fully self-contained prompt, the source repository, the
   environment and the expected outputs. Do not hardcode a model. Use the tool's default
   unless the owner names one. Show it before acting only when a material detail is
   missing or the owner asked to review first, and then show the complete, reviewable
   request with the question, not a partial draft.
5. **Execute the authorized action.** Run exactly that action through the tool. Do not
   widen it to effects the authorization does not cover.
6. **Record the receipt.** Report the identifier, the next run time and the link exactly as
   the tool returned them. A routine exists only once the tool has confirmed it.
7. **Change deliberately.** Disabling, editing, running now or removing a routine is a
   distinct effect under the same rule as step 1: proceed when the owner's authorization
   covers it. Use the action the live schema offers, or the provider UI the docs name, and
   record its result.

## Reporting

- State created, updated, ran or **not created**, with the tool's own response as
  evidence.
- A successful create is not a successful run. A run's outcome comes from its own result,
  not from the schedule.
- Never claim a schedule, message or deployment that the tool did not confirm.

## Related

- `scheduled-tasks`: session cron and one-event waits.
- `delivery`: implementation outcomes, including the optional local controller.
- `/schedule` (where available and authorized): the native higher-level routine workflow.
