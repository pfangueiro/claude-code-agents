#!/usr/bin/env python3
"""
Skill Initializer - Creates a new skill from template

Usage:
    init_skill.py <skill-name> --path <path> [--description <text>]

Examples:
    init_skill.py my-new-skill --path skills/public
    init_skill.py my-api-helper --path skills/private
    init_skill.py custom-skill --path /custom/location

The skill name and the optional description are validated BEFORE anything is
written. A skill whose frontmatter breaks the documented constraints cannot be
loaded, so scaffolding one only defers the failure to a point where it is
harder to diagnose.
"""

import re
import sys
from pathlib import Path


# Frontmatter constraints Claude Code enforces when loading a skill. Source:
# https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
#   name        — max 64 characters; lowercase letters, numbers and hyphens only;
#                 no XML tags; no reserved words "anthropic" / "claude"
#   description — non-empty; max 1024 characters; no XML tags
PLATFORM_MAX_NAME_LENGTH = 64
PLATFORM_MAX_DESCRIPTION_LENGTH = 1024
RESERVED_NAME_WORDS = ('anthropic', 'claude')

# quick_validate.py, the validator this skill ships, is stricter than the platform on
# name length and hyphen hygiene. Emitting a name it rejects just moves the failure
# one step downstream, so its rules are enforced here too.
VALIDATOR_MAX_NAME_LENGTH = 40

DEFAULT_DESCRIPTION = (
    "[TODO: Complete and informative explanation of what the skill does and when to "
    "use it. Include WHEN to use this skill - specific scenarios, file types, or "
    "tasks that trigger it.]"
)


SKILL_TEMPLATE = """---
name: {skill_name}
description: "{description}"
---

# {skill_title}

## Overview

[TODO: 1-2 sentences explaining what this skill enables]

## Structuring This Skill

[TODO: Choose the structure that best fits this skill's purpose. Common patterns:

**1. Workflow-Based** (best for sequential processes)
- Works well when there are clear step-by-step procedures
- Example: DOCX skill with "Workflow Decision Tree" → "Reading" → "Creating" → "Editing"
- Structure: ## Overview → ## Workflow Decision Tree → ## Step 1 → ## Step 2...

**2. Task-Based** (best for tool collections)
- Works well when the skill offers different operations/capabilities
- Example: PDF skill with "Quick Start" → "Merge PDFs" → "Split PDFs" → "Extract Text"
- Structure: ## Overview → ## Quick Start → ## Task Category 1 → ## Task Category 2...

**3. Reference/Guidelines** (best for standards or specifications)
- Works well for brand guidelines, coding standards, or requirements
- Example: Brand styling with "Brand Guidelines" → "Colors" → "Typography" → "Features"
- Structure: ## Overview → ## Guidelines → ## Specifications → ## Usage...

**4. Capabilities-Based** (best for integrated systems)
- Works well when the skill provides multiple interrelated features
- Example: Product Management with "Core Capabilities" → numbered capability list
- Structure: ## Overview → ## Core Capabilities → ### 1. Feature → ### 2. Feature...

Patterns can be mixed and matched as needed. Most skills combine patterns (e.g., start with task-based, add workflow for complex operations).

Delete this entire "Structuring This Skill" section when done - it's just guidance.]

## [TODO: Replace with the first main section based on chosen structure]

[TODO: Add content here. See examples in existing skills:
- Code samples for technical skills
- Decision trees for complex workflows
- Concrete examples with realistic user requests
- References to scripts/templates/references as needed]

## Resources

This skill includes example resource directories that demonstrate how to organize different types of bundled resources:

### scripts/
Executable code (Python/Bash/etc.) that can be run directly to perform specific operations.

**Examples from other skills:**
- PDF skill: `fill_fillable_fields.py`, `extract_form_field_info.py` - utilities for PDF manipulation
- DOCX skill: `document.py`, `utilities.py` - Python modules for document processing

**Appropriate for:** Python scripts, shell scripts, or any executable code that performs automation, data processing, or specific operations.

**Note:** Scripts may be executed without loading into context, but can still be read by Claude for patching or environment adjustments.

### references/
Documentation and reference material intended to be loaded into context to inform Claude's process and thinking.

**Examples from other skills:**
- Product management: `communication.md`, `context_building.md` - detailed workflow guides
- BigQuery: API reference documentation and query examples
- Finance: Schema documentation, company policies

**Appropriate for:** In-depth documentation, API references, database schemas, comprehensive guides, or any detailed information that Claude should reference while working.

### assets/
Files not intended to be loaded into context, but rather used within the output Claude produces.

**Examples from other skills:**
- Brand styling: PowerPoint template files (.pptx), logo files
- Frontend builder: HTML/React boilerplate project directories
- Typography: Font files (.ttf, .woff2)

**Appropriate for:** Templates, boilerplate code, document templates, images, icons, fonts, or any files meant to be copied or used in the final output.

---

**Any unneeded directories can be deleted.** Not every skill requires all three types of resources.
"""

EXAMPLE_SCRIPT = '''#!/usr/bin/env python3
"""
Example helper script for {skill_name}

This is a placeholder script that can be executed directly.
Replace with actual implementation or delete if not needed.

Example real scripts from other skills:
- pdf/scripts/fill_fillable_fields.py - Fills PDF form fields
- pdf/scripts/convert_pdf_to_images.py - Converts PDF pages to images
"""

def main():
    print("This is an example script for {skill_name}")
    # TODO: Add actual script logic here
    # This could be data processing, file conversion, API calls, etc.

if __name__ == "__main__":
    main()
'''

EXAMPLE_REFERENCE = """# Reference Documentation for {skill_title}

This is a placeholder for detailed reference documentation.
Replace with actual reference content or delete if not needed.

Example real reference docs from other skills:
- product-management/references/communication.md - Comprehensive guide for status updates
- product-management/references/context_building.md - Deep-dive on gathering context
- bigquery/references/ - API references and query examples

## When Reference Docs Are Useful

Reference docs are ideal for:
- Comprehensive API documentation
- Detailed workflow guides
- Complex multi-step processes
- Information too lengthy for main SKILL.md
- Content that's only needed for specific use cases

## Structure Suggestions

### API Reference Example
- Overview
- Authentication
- Endpoints with examples
- Error codes
- Rate limits

### Workflow Guide Example
- Prerequisites
- Step-by-step instructions
- Common patterns
- Troubleshooting
- Best practices
"""

EXAMPLE_ASSET = """# Example Asset File

This placeholder represents where asset files would be stored.
Replace with actual asset files (templates, images, fonts, etc.) or delete if not needed.

Asset files are NOT intended to be loaded into context, but rather used within
the output Claude produces.

Example asset files from other skills:
- Brand guidelines: logo.png, slides_template.pptx
- Frontend builder: hello-world/ directory with HTML/React boilerplate
- Typography: custom-font.ttf, font-family.woff2
- Data: sample_data.csv, test_dataset.json

## Common Asset Types

- Templates: .pptx, .docx, boilerplate directories
- Images: .png, .jpg, .svg, .gif
- Fonts: .ttf, .otf, .woff, .woff2
- Boilerplate code: Project directories, starter files
- Icons: .ico, .svg
- Data files: .csv, .json, .xml, .yaml

Note: This is a text placeholder. Actual assets can be any file type.
"""


def title_case_skill_name(skill_name):
    """Convert hyphenated skill name to Title Case for display."""
    return ' '.join(word.capitalize() for word in skill_name.split('-'))


def validate_skill_name(skill_name):
    """
    Return an error message if skill_name cannot be used, or None if it is usable.

    Ordered platform-fatal rules first, then the stricter house rules quick_validate.py
    applies, so the reported error is the most consequential one.

    The character-set rule is also what makes the name safe as a path segment: '/',
    '\\' and '.' are all outside [a-z0-9-], so 'skills/../etc' and '../escape' are
    rejected here and can never reach the mkdir.
    """
    if not skill_name or not skill_name.strip():
        return "Skill name is empty"
    if len(skill_name) > PLATFORM_MAX_NAME_LENGTH:
        return (f"Skill name is {len(skill_name)} characters (max "
                f"{PLATFORM_MAX_NAME_LENGTH}) — the skill would not load")
    if re.search(r'<[^>]*>', skill_name):
        return "Skill name cannot contain XML tags"
    if not re.match(r'^[a-z0-9-]+$', skill_name):
        return (f"Skill name '{skill_name}' must contain only lowercase letters, "
                f"numbers and hyphens")
    reserved = next((word for word in RESERVED_NAME_WORDS if word in skill_name), None)
    if reserved:
        return (f"Skill name '{skill_name}' contains the reserved word '{reserved}' "
                f"— names cannot contain 'anthropic' or 'claude'")
    if skill_name.startswith('-') or skill_name.endswith('-') or '--' in skill_name:
        return (f"Skill name '{skill_name}' cannot start or end with a hyphen, or "
                f"contain consecutive hyphens")
    if len(skill_name) > VALIDATOR_MAX_NAME_LENGTH:
        return (f"Skill name is {len(skill_name)} characters — quick_validate.py "
                f"rejects anything over {VALIDATOR_MAX_NAME_LENGTH}")
    return None


def validate_description(description):
    """
    Return an error message if description cannot be used, or None if it is usable.

    Beyond the documented platform rules, double quotes, backslashes and newlines are
    rejected: the template writes the description as a double-quoted YAML scalar, and
    any of those three would produce frontmatter that no longer parses. Refusing is
    honest; silently mangling the text is not.
    """
    if description is None:
        return None
    if not description.strip():
        return "Description is empty"
    if len(description) > PLATFORM_MAX_DESCRIPTION_LENGTH:
        return (f"Description is {len(description)} characters (max "
                f"{PLATFORM_MAX_DESCRIPTION_LENGTH}) — the skill would not load")
    if '<' in description or '>' in description:
        return "Description cannot contain XML tags (or the characters < and >)"
    if '"' in description or '\\' in description or '\n' in description:
        return ('Description cannot contain a double quote, a backslash or a newline '
                '— it is written as a quoted YAML scalar; write it into SKILL.md '
                'directly instead')
    return None


def validate_output_path(path):
    """Return an error message if path cannot host a skill directory, else None."""
    if not path or not path.strip():
        return "Output path is empty"
    parent = Path(path).expanduser()
    if parent.exists() and not parent.is_dir():
        return f"Output path exists but is not a directory: {parent}"
    return None


def init_skill(skill_name, path, description=None):
    """
    Initialize a new skill directory with template SKILL.md.

    Args:
        skill_name: Name of the skill
        path: Path where the skill directory should be created
        description: Optional frontmatter description; the TODO placeholder is used
            when omitted

    Returns:
        Path to created skill directory, or None if error

    Nothing is written until the name, path and description all validate, so a
    rejected invocation leaves no half-built skill behind.
    """
    for error in (validate_skill_name(skill_name),
                  validate_output_path(path),
                  validate_description(description)):
        if error:
            print(f"❌ Error: {error}")
            return None

    # Determine skill directory path
    skill_dir = Path(path).resolve() / skill_name

    # Check if directory already exists
    if skill_dir.exists():
        print(f"❌ Error: Skill directory already exists: {skill_dir}")
        return None

    # Create skill directory
    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
        print(f"✅ Created skill directory: {skill_dir}")
    except Exception as e:
        print(f"❌ Error creating directory: {e}")
        return None

    # Create SKILL.md from template
    skill_title = title_case_skill_name(skill_name)
    skill_content = SKILL_TEMPLATE.format(
        skill_name=skill_name,
        skill_title=skill_title,
        description=description if description else DEFAULT_DESCRIPTION
    )

    skill_md_path = skill_dir / 'SKILL.md'
    try:
        skill_md_path.write_text(skill_content)
        print("✅ Created SKILL.md")
    except Exception as e:
        print(f"❌ Error creating SKILL.md: {e}")
        return None

    # Create resource directories with example files
    try:
        # Create scripts/ directory with example script
        scripts_dir = skill_dir / 'scripts'
        scripts_dir.mkdir(exist_ok=True)
        example_script = scripts_dir / 'example.py'
        example_script.write_text(EXAMPLE_SCRIPT.format(skill_name=skill_name))
        example_script.chmod(0o755)
        print("✅ Created scripts/example.py")

        # Create references/ directory with example reference doc
        references_dir = skill_dir / 'references'
        references_dir.mkdir(exist_ok=True)
        example_reference = references_dir / 'api_reference.md'
        example_reference.write_text(EXAMPLE_REFERENCE.format(skill_title=skill_title))
        print("✅ Created references/api_reference.md")

        # Create assets/ directory with example asset placeholder
        assets_dir = skill_dir / 'assets'
        assets_dir.mkdir(exist_ok=True)
        example_asset = assets_dir / 'example_asset.txt'
        example_asset.write_text(EXAMPLE_ASSET)
        print("✅ Created assets/example_asset.txt")
    except Exception as e:
        print(f"❌ Error creating resource directories: {e}")
        return None

    # Print next steps
    print(f"\n✅ Skill '{skill_name}' initialized successfully at {skill_dir}")
    print("\nNext steps:")
    print("1. Edit SKILL.md to complete the TODO items and update the description")
    print("2. Customize or delete the example files in scripts/, references/, and assets/")
    print("3. Run the validator when ready to check the skill structure")

    return skill_dir


def parse_args(argv):
    """
    Return (skill_name, path, description) for a well-formed invocation, else None.

    description is None when --description was not supplied.
    """
    if len(argv) < 4 or argv[2] != '--path':
        return None
    rest = argv[4:]
    if rest and (len(rest) != 2 or rest[0] != '--description'):
        return None
    return argv[1], argv[3], (rest[1] if rest else None)


def main():
    parsed = parse_args(sys.argv)
    if parsed is None:
        print("Usage: init_skill.py <skill-name> --path <path> [--description <text>]")
        print("\nSkill name requirements:")
        print("  - Hyphen-case identifier (e.g., 'data-analyzer')")
        print("  - Lowercase letters, digits, and hyphens only")
        print("  - No XML tags; cannot contain 'anthropic' or 'claude'")
        print(f"  - Max {VALIDATOR_MAX_NAME_LENGTH} characters "
              f"(platform limit is {PLATFORM_MAX_NAME_LENGTH})")
        print("  - Must match directory name exactly")
        print("\nDescription requirements (when --description is given):")
        print(f"  - Non-empty, max {PLATFORM_MAX_DESCRIPTION_LENGTH} characters")
        print("  - No XML tags, double quotes, backslashes or newlines")
        print("\nExamples:")
        print("  init_skill.py my-new-skill --path skills/public")
        print("  init_skill.py my-api-helper --path skills/private")
        print("  init_skill.py custom-skill --path /custom/location")
        sys.exit(1)

    skill_name, path, description = parsed

    print(f"🚀 Initializing skill: {skill_name}")
    print(f"   Location: {path}")
    print()

    result = init_skill(skill_name, path, description)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
