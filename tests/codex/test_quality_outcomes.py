"""Offline checks of shared quality contracts and their exported behavior.

Reads canonical sources and builds the Codex edition in memory with framework.build();
receipt checks run the verified-handoff recorder against a disposable fixture. No
install, network or provider call. Assertions pin behavioral boundaries, not prose.
"""
import json
from pathlib import Path
import posixpath
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'codex'))
import framework

EVIDENCE = ROOT / '.claude/skills/verified-handoff/scripts/evidence.py'
QUALITY_SOURCES = ('.claude/agents/code-quality.md', '.claude/commands/review-pr.md',
                   '.claude/commands/quality-gate.md', '.claude/skills/code-review-checklist/SKILL.md',
                   '.claude/skills/delivery/references/acceptance-by-task.md')
# A report-template field that presents an uncalibrated score as a result.
SCORE_FIELD = re.compile(r'(?i)\*\*\s*(?:overall grade|maintainability index|confidence(?: score)?)\s*:\s*\*\*')


def score_fields(text: str) -> list[str]:
    return SCORE_FIELD.findall(text)


class ScoreFieldGuard(unittest.TestCase):
    def test_baseline_template_is_detected(self):
        # Negative control: the retired report template must trip the guard.
        baseline = '## Summary\n**Overall Grade:** B+\n**Maintainability Index:** 72\n'
        self.assertEqual(len(score_fields(baseline)), 2)

    def test_safe_counterexample_is_accepted(self):
        # Prohibiting a grade, or bolding an unrelated label, is not a score field.
        safe = ('Do not assign an overall letter grade, a synthetic maintainability index '
                'or an uncalibrated numeric confidence; otherwise say **not measured**.\n'
                '**Evidence basis:** source-proven\n')
        self.assertEqual(score_fields(safe), [])

    def test_quality_sources_and_exports_carry_no_score_fields(self):
        for rel in QUALITY_SOURCES:
            with self.subTest(source=rel):
                self.assertEqual(score_fields((ROOT / rel).read_text()), [])
        role = tomllib.loads(framework.build()['.codex/agents/code-quality.toml'].decode())
        self.assertEqual(score_fields(role['developer_instructions']), [])


class QualityContracts(unittest.TestCase):
    def test_code_quality_reports_scoped_evidence(self):
        body = (ROOT / '.claude/agents/code-quality.md').read_text()
        for concept in ('triggering', 'affected caller', 'source-proven', 'not measured'):
            self.assertIn(concept, body)
        # The requested scope is honored rather than defaulting to the last commit.
        self.assertNotIn('git log -1 --stat', body)

    def test_required_gaps_and_actual_failures_are_separate(self):
        body = (ROOT / '.claude/commands/quality-gate.md').read_text()
        for outcome in ('PASS', 'FAIL', 'INCOMPLETE', 'UNAVAILABLE', 'NOT_APPLICABLE'):
            self.assertIn(outcome, body)
        self.assertIn('declared completed scope', body)
        self.assertNotIn('safe to commit', body)
        self.assertNotIn('npx prettier', body)
        self.assertIn('dependencies', body)
        self.assertIn('even if formatting fails', body)


class SharedExports(unittest.TestCase):
    def setUp(self):
        self.files = framework.build()
        self.inv = framework.source_inventory()

    def test_both_editions_export_canonical_quality_commands(self):
        self.assertFalse((ROOT / 'codex/overrides/review-pr.md').exists())
        for name in ('review-pr', 'quality-gate'):
            with self.subTest(command=name):
                _, body = framework.frontmatter(ROOT / f'.claude/commands/{name}.md')
                exported = self.files[f'.agents/skills/sdlc-{name}/SKILL.md'].decode()
                self.assertIn(framework.adapt(body, self.inv), exported)
        review = self.files['.agents/skills/sdlc-review-pr/SKILL.md'].decode()
        for concept in ('base/head SHAs', 'safe counterexamples', 'trusted base', 'INCOMPLETE', 'Recheck the PR head'):
            self.assertIn(concept, review)
        self.assertIn('$sdlc-delivery', review)

    def test_code_quality_role_exports_canonical_body(self):
        _, body = framework.frontmatter(ROOT / '.claude/agents/code-quality.md')
        role = tomllib.loads(self.files['.codex/agents/code-quality.toml'].decode())
        self.assertIn(framework.adapt(body, self.inv), role['developer_instructions'])

    def test_delivery_references_export_and_links_resolve(self):
        prefix = '.agents/skills/sdlc-delivery/'
        skill = self.files[prefix + 'SKILL.md'].decode()
        for name in ('acceptance-by-task', 'repository-measurements'):
            rel = f'references/{name}.md'
            source = (ROOT / '.claude/skills/delivery' / rel).read_text()
            exported = self.files[prefix + rel].decode()
            self.assertEqual(exported, framework.adapt(source, self.inv))
            self.assertIn(rel, skill)
            for link in re.findall(r'\]\(([^)#\s]+\.md)\)', exported):
                target = posixpath.normpath(posixpath.join(prefix + 'references', link))
                self.assertIn(target, self.files, f'{rel}: unresolved link {link}')
            # Any bundled script or resource the reference names must actually ship.
            for resource in re.findall(r'\b((?:scripts|references)/[\w./-]+\.(?:py|md|json))\b', exported):
                shipped = [p for p in self.files if p.endswith('/' + resource)]
                self.assertTrue(shipped, f'{rel}: names unshipped {resource}')

    def test_acceptance_profiles_and_measurement_limits(self):
        prefix = '.agents/skills/sdlc-delivery/references/'
        profiles = self.files[prefix + 'acceptance-by-task.md'].decode()
        for kind in ('Feature', 'Bug fix', 'Refactor', 'Performance', 'Support investigation', 'Deployment'):
            self.assertIn(f'| {kind} |', profiles)
        limits = self.files[prefix + 'repository-measurements.md'].decode()
        for concept in ('Schema-valid', 'future refs', 'source/history', 'symlink/traversal'):
            self.assertIn(concept, limits)


class RequiredReceipts(unittest.TestCase):
    """A gate cannot reach PASS while a required receipt is missing or failed."""

    SOURCE = 'quality fixture tree'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='quality-receipts-')
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.project, self.evidence = base / 'fixture', base / 'evidence'
        self.project.mkdir()
        self.evidence.mkdir()
        (self.project / 'module.py').write_text('VALUE = 1\n')

    def run_evidence(self, *args):
        return subprocess.run([sys.executable, str(EVIDENCE), *args], capture_output=True, text=True, timeout=60)

    def declare(self, label, code):
        return {'label': label, 'cwd': str(self.project), 'sourceOnly': self.SOURCE,
                'command': {'executable': sys.executable, 'args': ['-c', code]},
                'resultFile': f'{label}/result.json'}

    def record(self, label, code):
        return self.run_evidence('run', '--cwd', str(self.project), '--out-dir', str(self.evidence / label),
                                 '--label', label, '--source-only', self.SOURCE, '--', sys.executable, '-c', code)

    def verify(self, checks):
        manifest = self.evidence / 'manifest.json'
        manifest.write_text(json.dumps({'checks': checks}))
        result = self.run_evidence('verify', '--manifest', str(manifest))
        report = json.loads(result.stdout)
        return result.returncode, report['outcome'], {c['label']: c for c in report['checks']}

    def test_missing_required_receipt_stays_pending(self):
        self.assertEqual(self.record('format', 'pass').returncode, 0)
        code, outcome, checks = self.verify([self.declare('format', 'pass'),
                                             self.declare('behavior', 'pass')])
        self.assertEqual((code, outcome), (3, 'pending'))
        self.assertEqual(checks['format']['status'], 'verified')
        self.assertEqual(checks['behavior']['reasons'], ['receipt-missing'])

    def test_complete_manifest_verifies(self):
        # Positive control: the same declaration verifies once every receipt exists.
        for label in ('format', 'behavior'):
            self.assertEqual(self.record(label, 'pass').returncode, 0)
        code, outcome, _ = self.verify([self.declare('format', 'pass'), self.declare('behavior', 'pass')])
        self.assertEqual((code, outcome), (0, 'verified'))

    def test_failed_required_check_is_rejected(self):
        failing = 'raise SystemExit(1)'
        self.assertEqual(self.record('format', 'pass').returncode, 0)
        self.assertEqual(self.record('behavior', failing).returncode, 1)
        code, outcome, checks = self.verify([self.declare('format', 'pass'), self.declare('behavior', failing)])
        self.assertEqual((code, outcome), (1, 'rejected'))
        self.assertIn('child-nonzero-exit', checks['behavior']['reasons'])


if __name__ == '__main__':
    unittest.main()
