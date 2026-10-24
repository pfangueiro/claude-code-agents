# 🎓 Skills System - Quick Start Guide

One repository supplies both integrations. Claude uses `./install.sh` and
`~/.claude/skills`; Codex uses `./install-codex.sh --user` and `~/.agents/skills`.
Codex requires Python 3.11+/PyYAML for building/installing; see [INSTALL.md](INSTALL.md).
No project-by-project copying is needed with the default user profile.

Codex workflow names are prefixed, for example `$sdlc-code-review-checklist` and
`$sdlc-execute`. The adapter supplies 42 workflows plus 13 specialist guides (55
skill directories: 51 implicitly invocable, 4 explicit-only) and 13 native agent definitions. Use a guide
if native custom roles are unavailable. Selection uses model judgment; a skill is not an
access policy.

## What Are Skills?

Skills are modular knowledge packages that extend Claude's capabilities with domain-specific expertise. Agents are task executors that the model selects or delegates to by judgment, or that you name explicitly.

| **Agents** | **Skills** |
|------------|------------|
| Execute SDLC workflows | Provide domain expertise |
| Model-selected from descriptions, or named explicitly | Loaded when judged relevant, or invoked explicitly |
| Examples: test-automation, security-auditor | Examples: git-workflow, deployment-runbook |

## Included Skills

The Claude source contains 30 skills. These four are introductory examples:

### 1. skill-creator
**Purpose:** Create new skills
**Use when:** Building custom skills for your organization

```bash
python3 .claude/skills/skill-creator/scripts/init_skill.py my-skill --path .claude/skills
```

### 2. git-workflow
**Purpose:** Git best practices and branching strategies
**Use when:** Working with git, creating commits, managing branches

**Includes:**
- Conventional Commits guidelines
- Git Flow, GitHub Flow, Trunk-Based Development
- PR templates and merge conflict resolution

### 3. code-review-checklist
**Purpose:** Systematic code review framework
**Use when:** Reviewing PRs, establishing quality standards

**Includes:**
- 10-category review checklist
- OWASP Top 10 security considerations
- Performance anti-patterns
- Complements code-quality agent

### 4. deployment-runbook
**Purpose:** Deployment procedures and health checks
**Use when:** Deploying to production, performing rollbacks

**Includes:**
- Blue-green, canary, rolling deployment strategies
- Health check automation (Python script included)
- Rollback procedures
- Complements devops-automation agent

## Creating Your First Skill

### Step 1: Initialize
```bash
python3 .claude/skills/skill-creator/scripts/init_skill.py company-api --path .claude/skills
```

### Step 2: Edit SKILL.md
Update the generated `SKILL.md` with your content:
- Description: When to use this skill
- Domain knowledge: APIs, schemas, procedures
- Examples and best practices

### Step 3: Add Resources (Optional)
- `scripts/` - Python/Bash scripts for automation
- `references/` - Documentation loaded into context
- `assets/` - Templates, boilerplate, files for output

### Step 4: Validate
```bash
python3 .claude/skills/skill-creator/scripts/quick_validate.py .claude/skills/company-api
```

### Step 5: Use It
Reference your skill in conversations, and it will be loaded automatically when relevant.

## Skill Anatomy

```
my-skill/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description)
│   └── Markdown instructions
└── Optional bundled resources:
    ├── scripts/       - Executable automation
    ├── references/    - Loaded into context
    └── assets/        - Used in output
```

## Agent + Skill Power Combos

Combine agents with skills for maximum effectiveness:

| **Agent** | **+** | **Skill** | **=** | **Result** |
|-----------|-------|-----------|-------|------------|
| code-quality | + | code-review-checklist | = | Systematic code reviews with your standards |
| devops-automation | + | deployment-runbook | = | Safe deployments with your procedures |
| security-auditor | + | security-scan | = | Findings backed by secrets, dependency and OWASP checks |
| test-automation | + | browser-testing | = | E2E coverage through the Playwright MCP |

## Best Practices

### DO:
- ✅ Write SKILL.md in imperative form ("To do X, run Y")
- ✅ Keep SKILL.md focused, move details to references/
- ✅ Use scripts/ for code that gets rewritten repeatedly
- ✅ Include concrete examples in your skills
- ✅ Make skill descriptions specific about when to use them

### DON'T:
- ❌ Duplicate information between SKILL.md and references/
- ❌ Write in second person ("you should...")
- ❌ Create unnecessary resource directories
- ❌ Use vague descriptions like "helps with things"

## Common Use Cases

### 1. Company-Specific Knowledge
```
company-api/
├── SKILL.md              # When to use internal APIs
├── references/
│   ├── auth.md           # Authentication patterns
│   ├── endpoints.md      # API endpoints reference
│   └── schemas.md        # Data schemas
```

### 2. Deployment Procedures
```
deployment/
├── SKILL.md              # Deployment workflows
├── scripts/
│   ├── health_check.py   # Automated health checks
│   └── rollback.sh       # Emergency rollback
└── references/
    └── runbook.md        # Detailed procedures
```

### 3. Brand Guidelines
```
brand-guidelines/
├── SKILL.md              # Brand usage guide
├── references/
│   └── style_guide.md    # Detailed guidelines
└── assets/
    ├── logo.png          # Brand assets
    └── templates/        # Document templates
```

## Progressive Disclosure

Skills use a three-level loading system:

1. **Metadata** (always loaded): Name + description (~100 words)
2. **SKILL.md** (when skill triggers): Full instructions (<5k words)
3. **Resources** (as needed): Scripts, references, assets

This keeps context efficient while providing rich functionality.

## Package and Share

Once your skill is ready, package it for distribution:

```bash
# Creates my-skill.zip
python3 .claude/skills/skill-creator/scripts/package_skill.py .claude/skills/my-skill

# Share with your team
# They can extract to their .claude/skills/ directory
```

## More Resources

- **Full Documentation**: `.claude/skills/README.md`
- **Skill Creator Guide**: `.claude/skills/skill-creator/SKILL.md`
- **Examples**: Browse included skills for patterns
- **Claude Skills Hub**: https://claudeskills.info

## Need Help?

1. Read `.claude/skills/skill-creator/SKILL.md` for the complete 6-step process
2. Look at existing skills (git-workflow, code-review-checklist) as examples
3. Run `quick_validate.py` to catch issues early
4. Check https://github.com/anthropics/skills for community skills

---

**Remember:** Skills extend what Claude knows, while agents execute what Claude does. Together, they create a powerful, extensible development system!
