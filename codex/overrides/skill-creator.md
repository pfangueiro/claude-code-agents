# Create a Codex skill

Use the installed Codex skill-creator when available. Otherwise create a directory
in an authorized `.agents/skills/` location containing SKILL.md with YAML `name`
and `description`. Name the folder after the skill (lowercase letters/digits/hyphens).

Define precise activation boundaries, preserve the user's scope, and keep instructions
focused on non-obvious workflow requirements. Put conditional detail in references;
include scripts only when deterministic execution adds value. Test scripts and meaningful
behavior in a temporary workspace. Do not use Claude-only `context: fork`, model aliases,
tool allowlists or slash-command argument interpolation as Codex metadata.

Skills guide the model; they do not grant external-write permission or restrict tools.
For native specialist agents, use `$meta-agent` or the custom-agent documentation.
