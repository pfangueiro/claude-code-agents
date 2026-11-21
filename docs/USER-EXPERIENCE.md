# Start building — recommended defaults

"Start building" is the default way both editions are asked to work with you. You describe
the result you want in your own words, and the assistant handles the technical choices.
You do not need to know the framework's agents, workflows or checks to get started.

The guidance comes from one canonical source, `.claude/rules/user-experience.md`. Claude
receives it as an installed rule. Codex receives it in the generated `rules.md` resource,
and a short pointer in the managed AGENTS.md block makes it apply to read-only questions
too. These are instructions to the model, not a setting, a profile or an enforced
mechanism. Your own and your project's instructions take precedence.

## How to use it

- Say what you want to end up with, for example "a page where customers can book a
  slot" or "find out why the export is slow".
- Expect a question only when something important is missing, a choice is hard to undo,
  or the next step needs your permission (for example publishing, deploying or sending
  messages).
- Expect short updates, a plain summary of what was done, and how to try it. Ask for
  files, commands or check details whenever you want them.

## What stays the same

- Evidence rules do not change. Checks follow the delivery skill's
  `references/acceptance-by-task.md`, missing required evidence is reported as INCOMPLETE,
  and substantial work still gets an independent review.
- Models and effort come from your configured settings unless the owner has set up the
  optional model policy. Nothing picks the most expensive model for you, and no speed or
  quality gain is claimed without a comparison.
- One account is enough. Nothing discovers accounts, logs in for you or changes billing.

## Optional features

Core workflows and checking guidance are on by default. The following features are
available when you choose to set them up, and nothing turns them on silently: analytics,
the watchdog, notifications, Codex hooks, the Codex footer and MCP examples, Codex
approved post-edit lint, the prompt/agent reference hook templates, the persistent
delivery controller, and unattended work or external effects. Each one keeps its own setup
steps in README, INSTALL or `codex/README.md`. There is no single switch that turns them
all on or off. Claude's existing core post-edit lint feedback stays as installed; it is
edit-time feedback, not acceptance evidence.

## Existing installations

- This guidance changes no personal configuration, and existing optional selections are
  preserved. Updating the framework is a separate step. Ask the assistant to "update the
  installed framework and preserve my settings": it uses the safe updater
  (`./framework update`), which shows a plan first, backs up affected files and never
  rewrites your personal settings ([details](FRAMEWORK-CONTROL.md#update-an-existing-installation)).
  The older manual procedure in [INSTALL.md](../INSTALL.md) remains, but its broad
  `install.sh --update` can replace same-name customizations and reconcile settings such as
  permissions, attribution, the status line and framework hook bindings.
- The Claude `CLAUDE.md` template is seed-only. A fresh install gets the outcome-first
  response preferences, but an existing `~/.claude/CLAUDE.md` is never overwritten. If you
  want the new preferences, edit your own file.

## Checking the framework and display preferences

When your request is about the framework itself, the assistant can use `./framework` in the
source checkout or the installed helper to show readiness and optional extras
([details](FRAMEWORK-CONTROL.md)). It is not run before every request. If you saved display
preferences (concise or full detail, reminders only about changes) or marked extras as
reviewed, they are respected where relevant, at most once per conversation; your own and
your project's instructions still win. They change presentation only: failures, blockers
and needed permissions are always shown, and saving them grants nothing.

## What is not implemented

These ideas came up as possibilities and are **not implemented**. Do not expect them:

- a setup wizard, feature menu or startup tour;
- a user profile switch, or a setting that changes these defaults (the helper's display
  preferences only change how its status is shown);
- an automatic first-use hint at session start, or a stored record that a hint was
  dismissed;
- any measured claim that these defaults make work faster or better.

The offline tests in `tests/codex/test_workflow_guidance.py` check that this guidance is
packaged and installed. They do not measure whether an agent follows it.
