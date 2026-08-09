#!/usr/bin/env python3
"""
Quick validation script for skills - minimal version

Usage:
    quick_validate.py <skill_directory>

Checks performed (the contract advertised in skill-creator/SKILL.md, Step 5):
  1. YAML frontmatter format and required fields
  2. Skill naming conventions and directory structure
  3. Description completeness and quality
  4. File organization and resource references

Fail-closed: a check that cannot verify its subject reports failure, never
success. Unfilled template content (a '[TODO: ...]' description, an untouched
init_skill.py example file, a body with no instructions) is a validation
failure, not a pass.
"""

import sys
import re
from pathlib import Path

# Values that are unmistakably unfilled template slots rather than real content.
# Matched case-insensitively against the frontmatter description.
PLACEHOLDER_PATTERNS = [
    r'\[\s*(?:todo|tbd|fixme|xxx|describe|description|placeholder|insert|your)\b',
    r'<\s*(?:todo|tbd|fixme|describe|description|placeholder|insert|your)\b',
    r'\btodo\s*:',
    r'^\s*todo\b',
    r'\btbd\b',
    r'\bfixme\b',
    r'\blorem(?:\s+ipsum)?\b',
]

# Whole-name matches only, so real names such as 'todo-scanner' are unaffected.
TEMPLATE_NAMES = {
    'skill-name', 'my-skill', 'my-new-skill', 'new-skill', 'example-skill',
    'placeholder', 'placeholder-skill', 'todo', 'tbd', 'untitled',
    'untitled-skill', 'changeme', 'change-me', 'your-skill', 'your-skill-name',
}

# Files init_skill.py generates as examples, keyed to a marker sentence unique
# to the untouched template. Present + unmodified means the skill was never
# finished.
TEMPLATE_RESOURCES = [
    ('scripts/example.py', 'This is a placeholder script'),
    ('references/api_reference.md', 'This is a placeholder for detailed reference documentation'),
    ('assets/example_asset.txt', 'This placeholder represents where asset files would be stored'),
]

RESOURCE_DIRS = ('scripts', 'references', 'assets')

MAX_NAME_LENGTH = 40
MIN_DESCRIPTION_LENGTH = 20
MIN_BODY_LENGTH = 50


def _extract_field(frontmatter, field):
    """
    Return the value of a top-level frontmatter key.

    Returns None when the key is absent, and '' when it is present but empty.
    Handles plain scalars, quoted scalars, and block scalars ('|' / '>').
    """
    lines = frontmatter.split('\n')
    for idx, line in enumerate(lines):
        match = re.match(r'^' + re.escape(field) + r':[ \t]*(.*)$', line)
        if not match:
            continue

        value = match.group(1).strip()

        # Block scalar: the value is the indented lines that follow.
        if re.fullmatch(r'[|>][-+]?\d*', value):
            block = []
            for following in lines[idx + 1:]:
                if following.strip() and not following[:1].isspace():
                    break
                block.append(following.strip())
            value = ' '.join(part for part in block if part).strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1].strip()

        return value
    return None


def _find_placeholder(text):
    """Return the placeholder marker found in text, or None."""
    for pattern in PLACEHOLDER_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(0).strip()
    return None


def validate_skill(skill_path):
    """Basic validation of a skill"""
    skill_path = Path(skill_path)

    # --- 1. Structure and frontmatter ------------------------------------
    if not skill_path.is_dir():
        return False, f"Skill path is not a directory: {skill_path}"

    # Check SKILL.md exists
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False, "SKILL.md not found"
    if not skill_md.is_file():
        return False, "SKILL.md is not a regular file"

    # Read and validate frontmatter
    try:
        content = skill_md.read_text()
    except (OSError, UnicodeDecodeError) as err:
        return False, f"SKILL.md could not be read: {err}"

    if not content.startswith('---'):
        return False, "No YAML frontmatter found"

    # Extract frontmatter
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format"

    frontmatter = match.group(1)
    body = content[match.end():]

    # Check required fields
    name = _extract_field(frontmatter, 'name')
    if name is None:
        return False, "Missing 'name' in frontmatter"
    description = _extract_field(frontmatter, 'description')
    if description is None:
        return False, "Missing 'description' in frontmatter"

    # --- 2. Naming conventions and directory structure -------------------
    if not name:
        return False, "Field 'name' is empty"
    # Check naming convention (hyphen-case: lowercase with hyphens)
    if not re.match(r'^[a-z0-9-]+$', name):
        return False, f"Name '{name}' should be hyphen-case (lowercase letters, digits, and hyphens only)"
    if name.startswith('-') or name.endswith('-') or '--' in name:
        return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens"
    if len(name) > MAX_NAME_LENGTH:
        return False, f"Name '{name}' is {len(name)} characters (max {MAX_NAME_LENGTH})"
    if name in TEMPLATE_NAMES:
        return False, f"Name '{name}' is an unfilled template placeholder — give the skill a real name"
    if name != skill_path.resolve().name:
        return False, (f"Name '{name}' must match the skill directory name "
                       f"'{skill_path.resolve().name}' exactly")

    # --- 3. Description completeness and quality -------------------------
    if not description:
        return False, "Field 'description' is empty — describe what the skill does and when to use it"
    # Check for angle brackets
    if '<' in description or '>' in description:
        return False, "Description cannot contain angle brackets (< or >)"
    placeholder = _find_placeholder(description)
    if placeholder:
        return False, (f"Description is an unfilled template placeholder (found '{placeholder}') "
                       f"— replace it with a real description")
    if len(description) < MIN_DESCRIPTION_LENGTH:
        return False, (f"Description is too short ({len(description)} characters, "
                       f"minimum {MIN_DESCRIPTION_LENGTH}) to explain what the skill does and when to use it")
    if ' ' not in description:
        return False, "Description must be a sentence explaining what the skill does and when to use it"

    # --- 4. File organization and resource references --------------------
    if len(body.strip()) < MIN_BODY_LENGTH:
        return False, "SKILL.md has no instructions after the frontmatter"
    body_placeholder = re.search(r'\[\s*TODO\b', body, re.IGNORECASE)
    if body_placeholder:
        return False, "SKILL.md still contains unfilled '[TODO: ...]' template sections"

    for dir_name in RESOURCE_DIRS:
        resource_dir = skill_path / dir_name
        if not resource_dir.exists():
            continue
        if not resource_dir.is_dir():
            return False, f"'{dir_name}' exists but is not a directory"
        if not any(resource_dir.iterdir()):
            return False, f"Resource directory '{dir_name}/' is empty — add files or delete it"

    for rel_path, marker in TEMPLATE_RESOURCES:
        resource = skill_path / rel_path
        if not resource.is_file():
            continue
        try:
            if marker in resource.read_text():
                return False, (f"'{rel_path}' is still the unmodified init_skill.py example "
                               f"— customize it or delete it")
        except (OSError, UnicodeDecodeError):
            return False, f"'{rel_path}' could not be read for template-placeholder validation"

    return True, "Skill is valid!"

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in ('-h', '--help'):
        print(__doc__.strip())
        sys.exit(0)

    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
