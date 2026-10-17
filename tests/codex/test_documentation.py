"""Guard current README local links: every relative file link resolves and every
same-page heading anchor matches a real heading. Discovered by `unittest discover -s
tests/codex` (test*.py). Scope is intentionally narrow — README local links only, not a
general Markdown linter and not cross-file fragments.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / 'README.md'

# Every link/image target `](...)`, robust to nested image links like `[![alt](img)](#anchor)`.
TARGET = re.compile(r'\]\(([^)]+)\)')
HEADING = re.compile(r'^#{1,6}\s+(.*?)\s*$')


def heading_slugs(markdown):
    """GitHub-style heading anchors, including the -1/-2 suffixes GitHub adds to duplicates."""
    seen, slugs = {}, set()
    for line in markdown.splitlines():
        m = HEADING.match(line)
        if not m:
            continue
        base = re.sub(r'\s+', '-', re.sub(r'[^\w\s-]', '', m.group(1).replace('`', '').strip().lower()))
        n = seen.get(base, 0)
        seen[base] = n + 1
        slugs.add(base if n == 0 else f'{base}-{n}')
    return slugs


def local_targets(markdown):
    for raw in TARGET.findall(markdown):
        target = raw.split(' ', 1)[0].strip()  # drop any `"title"` suffix
        if not target or target.startswith(('http://', 'https://', 'mailto:', 'tel:')):
            continue
        yield target


class ReadmeLinks(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding='utf-8')
        self.slugs = heading_slugs(self.text)

    def test_readme_local_links_resolve(self):
        broken = []
        for target in local_targets(self.text):
            path, _, frag = target.partition('#')
            if not path:  # same-page anchor
                if frag not in self.slugs:
                    broken.append(f'{target} (no heading anchor #{frag})')
                continue
            rel = path[2:] if path.startswith('./') else path
            resolved = Path(rel) if rel.startswith('/') else (ROOT / rel)
            if not resolved.exists():
                broken.append(f'{target} (missing file {path})')
        self.assertEqual(broken, [], f'Broken README local links: {broken}')

    def test_negative_control_known_bad_fragment(self):
        # Reproduction at base SHA: the MCP badge linked `#-mcp-integration`, which has no
        # matching heading. The checker must reject that exact fragment, or it is asleep.
        self.assertNotIn('-mcp-integration', self.slugs)
        self.assertNotIn('](#-mcp-integration)', self.text)

    def test_valid_target_control(self):
        # `## MCP Integration` yields the slug `mcp-integration`; the corrected badge uses it.
        self.assertIn('mcp-integration', self.slugs)
        self.assertIn('](#mcp-integration)', self.text)


if __name__ == '__main__':
    unittest.main()
