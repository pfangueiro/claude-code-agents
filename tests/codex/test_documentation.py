"""Guard current README local links: every relative file link resolves and every
same-page heading anchor matches a real *rendered* heading. Discovered by `unittest
discover -s tests/codex` (test*.py). Scope is intentionally narrow — README local links
only, not a general Markdown linter and not cross-file fragments.

Fenced code regions (``` and ~~~ blocks) are ignored for both heading and target
extraction: a `#` line inside a code sample is not a rendered heading anchor, and a
`](...)` inside one is an illustrative example, not a real link. Behavior is proven on
self-contained fixtures (see ``CheckerControls``) so a legitimate future edit to the live
README — such as removing the MCP badge — does not trip a control.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / 'README.md'

# Every link/image target `](...)`, robust to nested image links like `[![alt](img)](#anchor)`.
TARGET = re.compile(r'\]\(([^)]+)\)')
HEADING = re.compile(r'^#{1,6}\s+(.*?)\s*$')
# A fenced code block opens/closes on a line whose first non-space run is >=3 backticks
# or >=3 tildes (CommonMark). Indentation up to the block is tolerated via lstrip.
FENCE = re.compile(r'^(`{3,}|~{3,})')


def strip_fenced_code(markdown):
    """Return `markdown` with every fenced code region removed.

    A fence opens on a line whose first non-space run is a backtick or tilde run of
    length >= 3 (an info string after it, e.g. ```` ```markdown ````, is allowed) and
    closes on a later line made up solely of the same fence character (length >= 3).
    The opening line, the content, and the closing line are all dropped, so headings and
    link targets shown inside code samples are not mistaken for rendered Markdown.
    """
    kept, fence_char = [], None
    for line in markdown.splitlines():
        stripped = line.lstrip()
        match = FENCE.match(stripped)
        if fence_char is None:
            if match:
                fence_char = match.group(1)[0]
                continue  # drop the opening fence line
            kept.append(line)
            continue
        # Inside a fence: close only on a bare run of the same fence character.
        if match and match.group(1)[0] == fence_char and set(stripped.rstrip()) == {fence_char}:
            fence_char = None
        # Drop every in-fence line, including the closing one.
    return '\n'.join(kept)


def heading_slugs(markdown):
    """GitHub-style heading anchors, including the -1/-2 suffixes GitHub adds to duplicates.

    Headings inside fenced code are excluded — they produce no rendered anchor.
    """
    seen, slugs = {}, set()
    for line in strip_fenced_code(markdown).splitlines():
        m = HEADING.match(line)
        if not m:
            continue
        base = re.sub(r'\s+', '-', re.sub(r'[^\w\s-]', '', m.group(1).replace('`', '').strip().lower()))
        n = seen.get(base, 0)
        seen[base] = n + 1
        slugs.add(base if n == 0 else f'{base}-{n}')
    return slugs


def local_targets(markdown):
    """Yield local link/image targets, skipping absolute URLs and any inside a code fence."""
    for raw in TARGET.findall(strip_fenced_code(markdown)):
        target = raw.split(' ', 1)[0].strip()  # drop any `"title"` suffix
        if not target or target.startswith(('http://', 'https://', 'mailto:', 'tel:')):
            continue
        yield target


def broken_local_links(markdown, root):
    """Return the unresolved local links in `markdown`.

    Same-page `#anchor` links with no matching rendered heading, and relative file links
    whose path does not exist under `root`, are reported; everything else resolves.
    """
    slugs = heading_slugs(markdown)
    broken = []
    for target in local_targets(markdown):
        path, _, frag = target.partition('#')
        if not path:  # same-page anchor
            if frag not in slugs:
                broken.append(f'{target} (no heading anchor #{frag})')
            continue
        rel = path[2:] if path.startswith('./') else path
        resolved = Path(rel) if rel.startswith('/') else (root / rel)
        if not resolved.exists():
            broken.append(f'{target} (missing file {path})')
    return broken


class ReadmeLinks(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding='utf-8')

    def test_readme_local_links_resolve(self):
        broken = broken_local_links(self.text, ROOT)
        self.assertEqual(broken, [], f'Broken README local links: {broken}')


class CheckerControls(unittest.TestCase):
    """Exercise the checker on self-contained fixtures, not the live README, so a
    legitimate future README edit does not reject a control. Each fixture isolates one
    behavior the guard must have."""

    def test_rejects_original_bad_fragment(self):
        # Base-SHA reproduction: the MCP badge linked `#-mcp-integration` while the only
        # heading was `## MCP Integration` (slug `mcp-integration`). The guard must flag
        # the bad fragment and accept the correct one.
        bad = '# Title\n\n## MCP Integration\n\n[badge](#-mcp-integration)\n'
        self.assertEqual(
            broken_local_links(bad, ROOT),
            ['#-mcp-integration (no heading anchor #-mcp-integration)'],
        )
        good = '# Title\n\n## MCP Integration\n\n[badge](#mcp-integration)\n'
        self.assertEqual(broken_local_links(good, ROOT), [])

    def test_valid_heading_target_resolves(self):
        fixture = '# Alpha\n\n## Beta Section\n\n[jump](#beta-section)\n'
        self.assertEqual(broken_local_links(fixture, ROOT), [])

    def test_rejects_link_to_fenced_only_heading(self):
        # A heading that exists only inside a fenced code block is not a rendered anchor,
        # so a link to it must be flagged broken. This is the fence-stripping fix and the
        # exact scenario the saved `probe-fenced-heading.py` reruns.
        fixture = '# Real\n\n[broken](#phantom)\n\n```markdown\n# Phantom\n```\n'
        self.assertEqual(
            broken_local_links(fixture, ROOT),
            ['#phantom (no heading anchor #phantom)'],
        )

    def test_fenced_link_target_not_flagged(self):
        # Symmetric to the heading case: a file link shown inside a code sample is
        # illustrative, not a real link, so a nonexistent path there is not reported.
        fixture = '# Real\n\n```markdown\n[example](./does-not-exist.md)\n```\n'
        self.assertEqual(broken_local_links(fixture, ROOT), [])


if __name__ == '__main__':
    unittest.main()
