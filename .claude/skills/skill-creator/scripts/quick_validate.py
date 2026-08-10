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
failure, not a pass. Template detection keys on file CONTENT, not on filename,
so renaming or relocating a generated example does not hide it. Frontmatter is
parsed with PyYAML, never scraped, so YAML that Claude Code would reject is
rejected here too; if PyYAML is missing the run fails rather than passing an
unverified skill.

Frontmatter constraints enforced here mirror the documented platform rules
(name: max length, lowercase letters/numbers/hyphens only, no XML tags, no
'anthropic'/'claude'; description: non-empty, max 1024 characters, no XML
tags). See:
https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices

Exit code 0 means loadable. An advisory warning (SKILL.md body over the
documented 500-line budget) is appended to the success message and does not
change the exit code, because an over-budget skill still loads.
"""

import os
import sys
import re
from pathlib import Path

try:
    import yaml
except ImportError:  # PyYAML absent — validation cannot verify, so it must fail.
    yaml = None

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

# Reserved words a name may not contain, per the documented frontmatter constraints.
# Compared against the already-lowercased name as substrings: 'claude-tools' and
# 'anthropic-helper' are both rejected by the platform, not just the bare words.
RESERVED_NAME_WORDS = ('anthropic', 'claude')

# Marker sentences copied verbatim from the bodies init_skill.py writes. Detection is
# CONTENT-based rather than path-based: the generated examples are recognized by what
# is inside them, so renaming scripts/example.py to scripts/helper.py — or moving it
# anywhere else in the skill — no longer hides an unfinished scaffold. Compared as
# bytes so a binary asset cannot raise a decode error and slip through on a
# technicality.
TEMPLATE_MARKERS = (
    b'This is a placeholder script',
    b'This is a placeholder for detailed reference documentation',
    b'This placeholder represents where asset files would be stored',
    b'Delete this entire "Structuring This Skill" section when done',
    b'[TODO: Replace with the first main section based on chosen structure]',
)

# init_skill.py (which defines those markers) and this validator (which lists them)
# necessarily contain the marker strings as literals, and both live in the
# skill-creator toolchain directory. Skip that one directory so validating
# skill-creator itself is not a guaranteed false positive. Resolved from __file__, so
# it is fixed by where the validator lives — a skill under validation cannot rename or
# symlink its way into the exemption.
_SELF_DIR = Path(__file__).resolve().parent

RESOURCE_DIRS = ('scripts', 'references', 'assets')

# A skill-relative path into one of the bundled resource directories.
_RESOURCE_PATH = (r'(?:\./)?(?:' + '|'.join(RESOURCE_DIRS) +
                  r')/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*')

# Constructs that ASSERT a bundled file is there, as opposed to prose that merely
# names a path. A markdown link or image is unambiguous; a bare or backticked path
# counts only when an instruction verb introduces it. Illustrative mentions
# ("**Example**: `scripts/rotate_pdf.py`") are deliberately out of scope: they name
# files the skill never claims to ship, and flagging them would make this check cry
# wolf on documentation-style skills until someone switches it off.
REFERENCE_PATTERNS = [
    re.compile(r'!?\[[^\]\n]*\]\(\s*(' + _RESOURCE_PATH + r')[^)\n]*\)'),
    re.compile(r'\b(?:see|read|run|use|using|execute|refer\s+to|consult|load|open)\s+'
               r'(?:the\s+)?`?(' + _RESOURCE_PATH + r')`?', re.IGNORECASE),
]

# Fenced blocks are sample code for the reader's own project, not claims about
# this skill's bundle, so they are excluded from reference scanning.
FENCE_RE = re.compile(r'^\s*(?:```|~~~)')

# The platform hard limit is 64 characters; 40 is this framework's stricter house
# style. Stricter is safe (nothing that passes here can breach the platform limit), so
# it stays as-is — loosening it to 64 would weaken a validator, not fix one.
MAX_NAME_LENGTH = 40
MIN_DESCRIPTION_LENGTH = 20
# Documented platform maximum for the description field. Over this the skill does not
# load, so it is a failure, not a warning.
MAX_DESCRIPTION_LENGTH = 1024
MIN_BODY_LENGTH = 50
# Documented budget: "Keep SKILL.md body under 500 lines for optimal performance."
# Advisory — an over-budget skill still loads, so this warns and does not fail.
MAX_BODY_LINES = 500


def _parse_frontmatter(frontmatter):
    """
    Parse the frontmatter block as YAML.

    Returns (mapping, None) on success, or (None, error_message) when the block
    is unparseable or is not a mapping. Never guesses: YAML that PyYAML rejects
    is a validation failure, because Claude Code would reject it too.
    """
    if yaml is None:
        return None, ("PyYAML is required to validate frontmatter but is not installed "
                      "— run 'pip install pyyaml' and re-run; refusing to pass an "
                      "unverified skill")
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError as err:
        detail = ' '.join(str(err).split())
        return None, f"Frontmatter is not valid YAML: {detail}"

    if data is None:
        return None, "Frontmatter is empty"
    if not isinstance(data, dict):
        return None, (f"Frontmatter must be a YAML mapping of fields, "
                      f"got {type(data).__name__}")
    return data, None


def _field(data, field):
    """
    Return (value, error_message) for a required top-level frontmatter field.

    A missing key and a present-but-empty key are distinct failures, so each
    keeps its own message. A non-string value is a failure rather than a
    coercion — a list or a number is not a name or a description.
    """
    if field not in data:
        return None, f"Missing '{field}' in frontmatter"
    value = data[field]
    if value is None:
        return '', None
    if not isinstance(value, str):
        return None, (f"Field '{field}' must be text, got "
                      f"{type(value).__name__}")
    return value.strip(), None


def _find_missing_references(body, skill_path):
    """
    Return the sorted skill-relative resource paths the body points at that are
    not present on disk.

    Only references outside fenced code blocks are considered — see
    REFERENCE_PATTERNS for what counts as a reference and why.
    """
    missing = set()
    in_fence = False
    for line in body.split('\n'):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for pattern in REFERENCE_PATTERNS:
            for raw in pattern.findall(line):
                rel = raw[2:] if raw.startswith('./') else raw
                if not (skill_path / rel).exists():
                    missing.add(rel)
    if in_fence:
        # Unbalanced fences: in_fence never closed, so every line after the stray fence was
        # skipped and this scan silently checked nothing. Fail closed — a validator that
        # quietly stops looking is the exact fail-open class this check exists to prevent.
        missing.add('<unbalanced code fence: body scan aborted — fix the ``` / ~~~ pairing>')
    return sorted(missing)


def _find_template_content(skill_path):
    """
    Return a failure message if any file in the skill still holds an unmodified
    init_skill.py template body, or None when the skill is clean.

    The whole skill tree is walked and matched on CONTENT, so a generated example is
    caught under any filename and in any directory. Symlinked directories are not
    followed (no traversal out of the skill, no cycles); symlinked files are read
    normally, so pointing at a template through a link does not hide it either.

    Fail-closed: a file that cannot be read is reported as a failure, because an
    unreadable file is an unchecked file.
    """
    for dirpath, dirnames, filenames in os.walk(skill_path, followlinks=False):
        here = Path(dirpath).resolve()
        if here == _SELF_DIR or _SELF_DIR in here.parents:
            dirnames[:] = []
            continue
        dirnames.sort()
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            try:
                data = path.read_bytes()
            except OSError as err:
                rel = os.path.relpath(path, skill_path)
                return (f"'{rel}' could not be read for template-placeholder "
                        f"validation: {err}")
            for marker in TEMPLATE_MARKERS:
                if marker in data:
                    rel = os.path.relpath(path, skill_path)
                    return (f"'{rel}' is still an unmodified init_skill.py template "
                            f"(contains \"{marker.decode()}\") — customize it or "
                            f"delete it")
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
    data, error = _parse_frontmatter(frontmatter)
    if error:
        return False, error
    name, error = _field(data, 'name')
    if error:
        return False, error
    description, error = _field(data, 'description')
    if error:
        return False, error

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
    reserved = next((word for word in RESERVED_NAME_WORDS if word in name), None)
    if reserved:
        return False, (f"Name '{name}' contains the reserved word '{reserved}' — "
                       f"names cannot contain 'anthropic' or 'claude'")
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
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return False, (f"Description is {len(description)} characters (max "
                       f"{MAX_DESCRIPTION_LENGTH}) — the skill will not load; move "
                       f"detail into the SKILL.md body")
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

    missing_refs = _find_missing_references(body, skill_path)
    if missing_refs:
        return False, ("SKILL.md references files that do not exist: "
                       f"{', '.join(missing_refs)}")

    template_content = _find_template_content(skill_path)
    if template_content:
        return False, template_content

    # --- 5. Advisory budget (does not fail: an over-budget skill still loads) ---
    body_lines = len(body.strip().splitlines())
    if body_lines > MAX_BODY_LINES:
        return True, (f"Skill is valid! Warning: SKILL.md body is {body_lines} lines, "
                      f"over the documented {MAX_BODY_LINES}-line budget — split "
                      f"detail into references/ files")

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
