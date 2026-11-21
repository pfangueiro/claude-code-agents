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
the watchdog, notifications, Codex hooks, the Codex footer and MCP examples, the post-edit
lint, the prompt/agent reference hook templates, the persistent delivery controller, and
unattended work or external effects. Each one keeps its own setup steps in README,
INSTALL or `codex/README.md`. There is no single switch that turns them all on or off.

## Existing installations

- Your saved choices are preserved. Updates do not reset settings or ask the setup
  questions again.
- The Claude `CLAUDE.md` template is seed-only. A fresh install gets the outcome-first
  response preferences, but an existing `~/.claude/CLAUDE.md` is never overwritten. If you
  want the new preferences, edit your own file.

## What is not implemented

These ideas came up as possibilities and are **not implemented**. Do not expect them:

- a setup wizard, feature menu or startup tour;
- a user profile switch or settings registry for these defaults;
- an automatic first-use hint at session start, or a stored record that a hint was
  dismissed;
- any measured claim that these defaults make work faster or better.

The offline tests in `tests/codex/test_workflow_guidance.py` check that this guidance is
packaged and installed. They do not measure whether an agent follows it.
