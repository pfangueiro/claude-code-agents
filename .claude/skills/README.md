# Claude Skills System

Welcome to the Claude Skills directory! This directory contains modular, self-contained packages that extend Claude's capabilities with specialized knowledge, workflows, and tools.

There are 30 source skills. This is also the canonical source for portable Codex domain
procedures. `../../codex/overrides/` supplies runtime replacements; the builder creates
42 workflow skills (30 + 12 command templates) and 13 specialist-guide fallbacks under
`~/.agents/skills/sdlc-*`. Use [Codex setup](../../codex/README.md) and
[coverage](../../codex/FEATURES.md). Edit source, rebuild, and verify both editions;
do not edit a generated install as if it were canonical source.

`delivery`, `repo-context` and `verified-handoff` are provider-neutral and export to
both editions unchanged apart from invocation syntax. Their scripts are tested by
`tests/delivery/test_resources.py`, which `tests/codex` discovery loads. To update only
these skills, the delivery rule and `commit-pr` in an existing Claude home, run
`python3 scripts/install-delivery.py --dry-run` from the repository root, then rerun it
without `--dry-run`.

## What Are Skills?

Skills are different from the agents in `.claude/agents/`:

| **Agents** | **Skills** |
|------------|------------|
| Specialized executors for SDLC/SSDLC tasks | Modular knowledge packages |
| Selected or delegated by model judgment from their descriptions, or named explicitly | Loaded when the model judges them relevant, or invoked explicitly |
| Perform specific workflows (testing, deployment, security) | Provide specialized knowledge, tools, and resources |
| Examples: test-automation, security-auditor | Examples: git-workflow, deployment-runbook, delivery |

**Think of it this way:**
- **Agents** = Specialized workers who execute tasks
- **Skills** = Domain expertise and tools that extend capabilities

## Skills in This Directory

### skill-creator
The `skill-creator` skill provides comprehensive guidance and tools for creating new skills. It includes:

- **SKILL.md**: Complete guide on skill creation methodology
- **scripts/init_skill.py**: Creates new skill from template
- **scripts/package_skill.py**: Validates and packages skills for distribution
- **scripts/quick_validate.py**: Quick validation tool

## Creating a New Skill

### Quick Start

```bash
# 1. Initialize a new skill
python .claude/skills/skill-creator/scripts/init_skill.py my-new-skill --path .claude/skills

# 2. Edit the generated SKILL.md and add your content
# 3. Add any scripts, references, or assets as needed

# 4. Validate the skill
python .claude/skills/skill-creator/scripts/quick_validate.py .claude/skills/my-new-skill

# 5. Package the skill (optional - for distribution)
python .claude/skills/skill-creator/scripts/package_skill.py .claude/skills/my-new-skill
```

### When to Create a Skill

Create a skill when you need to:

1. **Provide specialized domain knowledge**
   - Example: Company-specific schemas, APIs, business logic
   - Example: Brand guidelines, design systems

2. **Bundle reusable resources**
   - Example: PDF manipulation scripts that get rewritten repeatedly
   - Example: Frontend boilerplate templates
   - Example: Database schema documentation

3. **Define specialized workflows**
   - Example: Multi-step financial reporting process
   - Example: Custom deployment procedures

4. **Integrate with specific tools/formats**
   - Example: Working with DOCX files
   - Example: BigQuery operations
   - Example: Image editing workflows

### Skill Anatomy

Every skill follows this structure:

```
my-skill/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description)
│   └── Markdown instructions
└── Optional resources:
    ├── scripts/       - Executable code (Python/Bash/etc.)
    ├── references/    - Documentation loaded into context
    └── assets/        - Files used in output (templates, images)
```

### The 6-Step Creation Process

The skill-creator follows this proven methodology:

1. **Understanding**: Gather concrete examples of how the skill will be used
2. **Planning**: Identify reusable resources (scripts, references, assets)
3. **Initialize**: Run `init_skill.py` to generate template
4. **Edit**: Complete SKILL.md and add resources
5. **Package**: Validate and package with `package_skill.py`
6. **Iterate**: Test, identify inefficiencies, improve

## Integration with Agent System

Skills and agents work together:

### Agents Use Skills
Agents can leverage skills for specialized knowledge:

```
Example: the code-quality agent applies the code-review-checklist
skill when reviewing a change.
```

### Skills Enhance Agents
Skills provide domain-specific tools that agents can utilize:

```
Example: the devops-automation agent follows the deployment-runbook
skill and its health-check scripts.
```

### Progressive Disclosure
Skills use a three-level loading system to manage context:

1. **Metadata** (always loaded): Name + description (~100 words)
2. **SKILL.md body** (when skill triggers): <5k words
3. **Bundled resources** (as needed): Scripts, references, assets

## Example Layouts (Not Shipped)

Generic layouts for skills you might write yourself. None of these ships with this framework:

### PDF Editor Skill
```
pdf/
├── SKILL.md                          # Workflow guidance
├── scripts/
│   ├── fill_fillable_fields.py       # Fill PDF forms
│   ├── extract_form_field_info.py    # Extract form data
│   └── convert_pdf_to_images.py      # PDF to images
└── references/
    └── api_documentation.md          # PDF library docs
```

### Frontend Builder Skill
```
frontend-builder/
├── SKILL.md                     # Build instructions
└── assets/
    └── hello-world/             # Boilerplate React/HTML
        ├── index.html
        ├── app.js
        └── styles.css
```

### Brand Guidelines Skill
```
brand-guidelines/
├── SKILL.md                # Brand usage guide
├── references/
│   └── style_guide.md      # Detailed guidelines
└── assets/
    ├── logo.png            # Company logo
    └── slides.pptx         # Presentation template
```

## Best Practices

### DO:
- Write SKILL.md in imperative/infinitive form (verb-first instructions)
- Keep SKILL.md lean - move detailed docs to references/
- Use scripts/ for code that gets rewritten repeatedly
- Include concrete examples in SKILL.md
- Make descriptions specific about when to use the skill

### DON'T:
- Duplicate information between SKILL.md and references/
- Write in second person ("you should...")
- Include unnecessary resource directories
- Make descriptions too vague or generic

## Getting Help

1. **Read the skill-creator SKILL.md**: Complete guide at `.claude/skills/skill-creator/SKILL.md`
2. **Check examples**: Browse https://claudeskills.info for real-world skills
3. **Use the validation tools**: Run `quick_validate.py` to catch issues early

## Resources

- **Claude Skills Hub**: https://claudeskills.info
- **Anthropic Skills Repository**: https://github.com/anthropics/skills
- **Skill Creator Documentation**: `.claude/skills/skill-creator/SKILL.md`

---

**Ready to create your first skill?**

```bash
python .claude/skills/skill-creator/scripts/init_skill.py my-first-skill --path .claude/skills
```
