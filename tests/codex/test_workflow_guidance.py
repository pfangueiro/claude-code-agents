"""Semantic-boundary checks for the workflow-guidance remediation (AR-002/003/004/005).

Offline only: reads canonical Claude source and builds the Codex edition in memory
with framework.build(); it never installs, writes a real home, creates an issue,
pushes, or contacts a provider. Each test asserts an intentional behavioral
boundary, not a verbatim copy of the new prose.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'codex'))
import framework as f

OWNED_RULES = ('security', 'verification', 'fix-quality', 'anti-anchoring', 'framework-integrity')


def source(rel: str) -> str:
    return (f.REPO / rel).read_text()


def command_frontmatter(name: str) -> tuple[dict, str]:
    return f.frontmatter(f.REPO / f'.claude/commands/{name}.md')


class ExecuteProportionality(unittest.TestCase):
    """AR-004: proportional decomposition, no fixed quotas; AR-002: regression-first bug fixes."""

    def setUp(self):
        self.skill = source('.claude/skills/execute/SKILL.md')
        self.matrix = source('.claude/skills/execute/references/agent-selection.md')

    def test_no_fixed_decomposition_quotas(self):
        # The four quotas the audit flagged as contradicting proportional delivery must be gone.
        self.assertNotRegex(self.skill, r'[Mm]inimum\s+3\s+tasks')
        self.assertNotRegex(self.skill, r'(?:≤|<=|at most)\s*3\s*files|targets?\s*≤?\s*3\s*files')
        self.assertNotRegex(self.skill, r'three files per task|at most three files')
        self.assertNotIn('if a task has "and" in it, split it', self.skill)
        self.assertNotIn('File creation is separate from file modification', self.skill)

    def test_decomposition_is_sized_by_responsibility_and_duration(self):
        # Proportional criteria replace the quotas, and the <30 min + independent-check
        # invariants the lane must preserve are still present.
        self.assertRegex(self.skill, r'responsib')
        self.assertRegex(self.skill, r'depend')
        self.assertRegex(self.skill, r'30\s*min')
        self.assertRegex(self.skill, r'acceptance')
        # The independent Phase-5 verifier gate (also guarded by validate.sh) stays.
        self.assertRegex(self.skill, r'independent (?:acceptance check|verifier)')

    def test_bug_fix_regression_oracle_precedes_the_fix(self):
        # AR-002: the canonical guidance must schedule the failing regression test BEFORE
        # the fix and no longer claim all test authoring follows code.
        self.assertNotIn('Test-writing is a separate task from code-writing', self.skill)
        self.assertNotIn('Code implementation → Test writing (tests depend on code)', self.matrix)
        self.assertNotIn('After implementation tasks complete — tests depend on code being written',
                         self.matrix)
        for text in (self.skill, self.matrix):
            self.assertRegex(text, r'regression')
            self.assertRegex(text, r'(?is)bug fix.*before|before.*fix|RED')
        # Additional coverage / independent acceptance still come after the fix.
        self.assertRegex(self.skill, r'(?is)coverage|acceptance')

    def test_agent_matrix_still_enumerates_every_agent(self):
        # validate.sh enforces this too; mirror it so an edit that drops a heading fails here.
        have = sorted(p.stem for p in (f.REPO / '.claude/agents').glob('*.md'))
        doc = sorted(re.findall(r'^### ([a-z-]+)', self.matrix, re.M))
        self.assertTrue(have)
        self.assertEqual(set(have) - set(doc), set(), 'agent matrix omits a shipped agent')


class ProviderNeutralCommands(unittest.TestCase):
    """AR-003: new-feature / create-jira portable, explicit-only, honest without a connector."""

    def test_new_feature_discovers_base_and_drops_hardcoded_master_and_proj(self):
        meta, body = command_frontmatter('new-feature')
        self.assertIs(meta.get('disable-model-invocation'), True)  # explicit-only preserved
        self.assertNotIn('Base branch is always', body)
        self.assertNotIn('Ticket number (PROJ-XXX) is MANDATORY', body)
        self.assertNotRegex(body, r'checkout master|pull origin master')
        self.assertNotRegex(meta['description'], r'master')
        # Base is discovered from project policy / origin HEAD instead of assumed.
        self.assertRegex(body, r'origin/HEAD|default branch|configured base|project')
        # Uncommitted work is preserved, not implicitly stashed/reset.
        self.assertRegex(body, r'(?is)uncommitted|dirty|preserve')

    def test_create_jira_is_tenant_neutral_and_drafts_without_connector(self):
        meta, body = command_frontmatter('create-jira')
        self.assertIs(meta.get('disable-model-invocation'), True)  # explicit-only preserved
        for leak in ('JMIA', 'JPT Portal', 'create-jira-issue.mjs', 'customfield_12000',
                     'jira_instances', 'users_acl'):
            self.assertNotIn(leak, body)
        # Discover the real capability; if none, report not-created and hand back the draft.
        self.assertRegex(body, r'(?is)discover|configured|capability')
        self.assertRegex(body, r'(?is)draft|no issue was created|not created')


class SingleNeutralSource(unittest.TestCase):
    """AR-003: the two Codex overrides are retired once the canonical bodies are neutral."""

    def setUp(self):
        self.files = f.build()

    def test_jira_and_new_feature_overrides_removed(self):
        self.assertFalse((f.REPO / 'codex/overrides/new-feature.md').exists())
        self.assertFalse((f.REPO / 'codex/overrides/create-jira.md').exists())

    def test_codex_edition_still_exports_neutral_bodies_from_canonical(self):
        feature = self.files['.agents/skills/sdlc-new-feature/SKILL.md'].decode()
        self.assertNotRegex(feature, r'checkout master|pull origin master|Base branch is always')
        self.assertRegex(feature, r'origin/HEAD|default branch|configured base|project')
        jira = self.files['.agents/skills/sdlc-create-jira/SKILL.md'].decode()
        for leak in ('JMIA', 'JPT Portal', 'create-jira-issue.mjs', 'jira_instances'):
            self.assertNotIn(leak, jira)
        self.assertRegex(jira, r'(?is)draft|no issue was created|not created')
        # Explicit-only packaging survives the override removal for both commands.
        for name in ('new-feature', 'create-jira'):
            policy = yaml.safe_load(
                self.files[f'.agents/skills/sdlc-{name}/agents/openai.yaml'].decode())
            self.assertIs(policy['policy']['allow_implicit_invocation'], False)


class UiGuidelinesExplicitOnly(unittest.TestCase):
    """AR-005 / make-optional: the app-specific UI skill is opt-in, not implicitly invoked."""

    def setUp(self):
        self.meta, self.body = f.frontmatter(f.REPO / '.claude/skills/ui-guidelines/SKILL.md')

    def test_frontmatter_is_explicit_only(self):
        self.assertIs(self.meta.get('disable-model-invocation'), True)

    def test_scope_narrowed_but_domain_knowledge_preserved(self):
        # Correct stack named; open-ended "build any visual component" implicit trigger gone.
        self.assertIn('Ant Design', self.meta['description'])
        self.assertNotIn('User asks to build/create/add', self.body)
        # The chart / non-Ant / accessibility exclusions and recipes are retained.
        self.assertRegex(self.body, r'(?i)chart')
        self.assertRegex(self.body, r'(?i)accessibility')
        self.assertRegex(self.body, r'App\.useApp')

    def test_codex_bundle_is_default_inert(self):
        files = f.build()
        policy = yaml.safe_load(
            files['.agents/skills/sdlc-ui-guidelines/agents/openai.yaml'].decode())
        self.assertIs(policy['policy']['allow_implicit_invocation'], False)


class ExplicitBundleInventory(unittest.TestCase):
    """AR-005: four explicit-only bundles, 51 implicit out of 55 total skill bundles."""

    def test_counts(self):
        files = f.build()
        bundles = {m.group(1) for k in files
                   if (m := re.fullmatch(r'\.agents/skills/([^/]+)/SKILL\.md', k))}
        explicit = {m.group(1) for k in files
                    if (m := re.fullmatch(r'\.agents/skills/([^/]+)/agents/openai\.yaml', k))}
        self.assertEqual(len(bundles), 55)
        self.assertEqual(explicit,
                         {'sdlc-commit-pr', 'sdlc-create-jira', 'sdlc-new-feature', 'sdlc-ui-guidelines'})
        self.assertEqual(len(bundles) - len(explicit), 51)


class NewFeatureBranchSequence(unittest.TestCase):
    """GIR-001/003: the branch is named and collision-checked BEFORE a single
    creation, and the base-refresh fetch cannot move a local branch.

    Source-ordering assertions pin the corrected recipe; a disposable Git fixture
    reproduces the behavior (the reviewed-SHA double-create fails; the corrected
    check-then-single-create succeeds). GIR-003 adds a two-repository fixture that
    proves a plain fetch can force-update a local branch under a custom refspec
    while the constrained fetch does not. Offline: private temp repos, no network/push.
    """

    CREATE = r'git checkout -b'
    COLLISION = r'git (?:show-ref --verify|rev-parse --verify)[^\n]*<branch>'

    def setUp(self):
        self.body = source('.claude/commands/new-feature.md')

    def _step(self, n: int) -> str:
        m = re.search(rf'(?s)\n{n}\. \*\*.*?(?=\n{n + 1}\. \*\*)', self.body)
        self.assertIsNotNone(m, f'could not locate numbered step {n}')
        return m.group(0)

    def test_exactly_one_branch_creating_command(self):
        # One create only — not one in the base-update step and another when naming.
        self.assertEqual(len(re.findall(self.CREATE, self.body)), 1,
                         'the procedure must create the branch exactly once')

    def test_collision_check_precedes_branch_creation(self):
        create = re.search(self.CREATE, self.body)
        collision = re.search(self.COLLISION, self.body)
        self.assertIsNotNone(create, 'no branch-creation command found')
        self.assertIsNotNone(collision, 'no name/collision check found')
        self.assertLess(collision.start(), create.start(),
                        'branch is created before its name/collision is validated')

    def test_base_update_step_performs_no_branch_mutation(self):
        # Step 4 resolves/freezes the base only; it must not create or switch a branch.
        step4 = self._step(4)
        self.assertNotRegex(step4, self.CREATE)
        self.assertNotRegex(step4, r'(?i)create the \w*\s*branch')
        # It still freezes an exact base commit for the single later creation.
        self.assertRegex(step4, r'git rev-parse --verify')

    def test_default_branch_fallback_asks_rather_than_assuming_current_branch(self):
        # The arbitrary "else the checked-out default branch" assumption must be gone;
        # unknown default => ask, never silently branch off whatever is checked out.
        self.assertNotRegex(self.body, r'(?i)else the checked-out')
        step3 = self._step(3)
        self.assertRegex(step3, r'origin/HEAD')
        self.assertRegex(step3, r'(?is)not.*known|ask')

    # --- behavioral reproduction on a disposable, offline Git fixture ---

    def _git(self, cwd, *args):
        env = dict(os.environ,
                   GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null',
                   GIT_TERMINAL_PROMPT='0',
                   GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@e',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@e')
        return subprocess.run(('git', *args), cwd=cwd, env=env,
                              capture_output=True, text=True)

    def _main_only_fixture(self):
        if not shutil.which('git'):
            self.skipTest('git not available')
        d = tempfile.mkdtemp(prefix='nf-seq-')
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self._git(d, 'init', '-q')
        (Path(d) / 'README.md').write_text('base\n')
        self._git(d, 'add', 'README.md')
        self._git(d, 'commit', '-q', '-m', 'base')
        self._git(d, 'branch', '-M', 'main')
        sha = self._git(d, 'rev-parse', 'HEAD').stdout.strip()
        # Local stand-ins for a remote default branch + origin/HEAD; no network.
        self._git(d, 'update-ref', 'refs/remotes/origin/main', sha)
        self._git(d, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        return d, sha

    def test_fixture_double_create_recipe_is_the_defect(self):
        # Negative control: the reviewed-SHA order (create, then "collision check", then
        # create again) self-collides and fails — this is what the guard protects against.
        repo, base = self._main_only_fixture()
        first = self._git(repo, 'checkout', '-b', 'feature/example', base)
        self.assertEqual(first.returncode, 0)
        selfclash = self._git(repo, 'rev-parse', '--verify', 'feature/example')
        self.assertEqual(selfclash.returncode, 0)  # sees its own freshly-made branch
        again = self._git(repo, 'checkout', '-b', 'feature/example', base)
        self.assertEqual(again.returncode, 128)
        self.assertIn('already exists', again.stderr)

    def test_fixture_check_then_single_create_succeeds(self):
        # Corrected order: freeze base, check collision BEFORE mutating, create once.
        repo, base = self._main_only_fixture()
        precheck = self._git(repo, 'show-ref', '--verify', '--quiet',
                             'refs/heads/feature/example')
        self.assertNotEqual(precheck.returncode, 0)  # absent => safe to create
        created = self._git(repo, 'checkout', '-b', 'feature/example', base)
        self.assertEqual(created.returncode, 0, created.stderr)
        heads = self._git(repo, 'for-each-ref', '--format=%(refname:short)',
                         'refs/heads/').stdout.split()
        self.assertEqual(set(heads), {'main', 'feature/example'})  # exactly one created
        self.assertEqual(self._git(repo, 'rev-parse', 'feature/example').stdout.strip(),
                         base)  # branched from the frozen base SHA

    # --- GIR-003: the base-refresh fetch must not move a local branch ---
    #
    # A configured remote.origin.fetch can target refs/heads/* and force-update a
    # local branch, so a plain `git fetch origin` cannot be promised as "origin/*
    # only". The corrected step constrains the fetch to write FETCH_HEAD only (empty
    # --refmap= plus a no-destination refspec) and freezes the base from FETCH_HEAD.

    def _all_refs(self, repo) -> dict:
        out = self._git(repo, 'for-each-ref',
                        '--format=%(refname) %(objectname)').stdout
        return dict(line.split() for line in out.splitlines() if line)

    def _custom_refspec_fixture(self):
        """Downstream repo whose origin is a local-path upstream and whose
        remote.origin.fetch maps the remote main onto a *local* owner branch.
        Returns (downstream_dir, owner_saved_sha_before, upstream_main_sha)."""
        if not shutil.which('git'):
            self.skipTest('git not available')
        root = tempfile.mkdtemp(prefix='nf-fetch-')
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        upstream = Path(root) / 'upstream'
        downstream = Path(root) / 'downstream'
        upstream.mkdir()
        downstream.mkdir()
        # Upstream main advances to a commit the downstream owner branch never had.
        self._git(upstream, 'init', '-q')
        (upstream / 'f.txt').write_text('upstream-1\n')
        self._git(upstream, 'add', 'f.txt')
        self._git(upstream, 'commit', '-q', '-m', 'upstream base')
        self._git(upstream, 'branch', '-M', 'main')
        (upstream / 'f.txt').write_text('upstream-2\n')
        self._git(upstream, 'add', 'f.txt')
        self._git(upstream, 'commit', '-q', '-m', 'upstream advance')
        upstream_main = self._git(upstream, 'rev-parse', 'main').stdout.strip()
        # Downstream keeps its own main (checked out) plus an owner-saved branch.
        self._git(downstream, 'init', '-q')
        (downstream / 'g.txt').write_text('downstream\n')
        self._git(downstream, 'add', 'g.txt')
        self._git(downstream, 'commit', '-q', '-m', 'downstream base')
        self._git(downstream, 'branch', '-M', 'main')
        self._git(downstream, 'branch', 'owner-saved')
        owner_before = self._git(downstream, 'rev-parse', 'owner-saved').stdout.strip()
        # Nonstandard mapping: fetching 'main' force-updates the LOCAL owner branch.
        self._git(downstream, 'remote', 'add', 'origin', str(upstream))
        self._git(downstream, 'config', 'remote.origin.fetch',
                  '+refs/heads/main:refs/heads/owner-saved')
        return downstream, owner_before, upstream_main

    def test_base_step_drops_false_fetch_guarantee_and_names_safe_form(self):
        # The unconditional "origin/* only, never a local branch" promise is gone,
        # replaced by the constrained fetch form: empty refmap, FETCH_HEAD freeze,
        # and the configured-refspec hazard acknowledged rather than denied.
        step4 = self._step(4)
        self.assertNotRegex(step4, r'(?is)updates\s+`?origin/\*`?\s+only')
        self.assertNotRegex(step4, r'(?is)never rewrites or force-updates a local branch')
        self.assertIn('--refmap=', step4)
        self.assertRegex(step4, r'FETCH_HEAD')
        self.assertRegex(step4, r'(?i)remote\.origin\.fetch|configured[^\n]*refspec')

    def test_fixture_plain_fetch_can_move_a_local_branch_under_custom_refspec(self):
        # Negative control / executable proof the old guarantee was false: a plain
        # `git fetch origin` moves an existing local branch under a custom refspec.
        repo, owner_before, upstream_main = self._custom_refspec_fixture()
        self.assertNotEqual(owner_before, upstream_main)
        res = self._git(repo, 'fetch', 'origin')
        self.assertEqual(res.returncode, 0, res.stderr)
        owner_after = self._git(repo, 'rev-parse', 'owner-saved').stdout.strip()
        self.assertEqual(owner_after, upstream_main)   # local branch force-updated
        self.assertNotEqual(owner_after, owner_before)

    def test_fixture_constrained_fetch_preserves_all_refs_and_freezes_correct_sha(self):
        # The corrected fetch form writes only FETCH_HEAD: every preexisting ref is
        # untouched, and the frozen base equals the upstream tip.
        repo, owner_before, upstream_main = self._custom_refspec_fixture()
        before = self._all_refs(repo)
        res = self._git(repo, 'fetch', '--no-tags', '--no-prune', '--no-prune-tags',
                        '--recurse-submodules=no', '--refmap=', 'origin', 'refs/heads/main')
        self.assertEqual(res.returncode, 0, res.stderr)
        after = self._all_refs(repo)
        self.assertEqual(before, after, 'constrained fetch must not move any ref')
        self.assertEqual(after.get('refs/heads/owner-saved'), owner_before)
        frozen = self._git(repo, 'rev-parse', '--verify',
                           'FETCH_HEAD^{commit}').stdout.strip()
        self.assertEqual(frozen, upstream_main)


class RulesAreGuidanceNotInviolable(unittest.TestCase):
    """AR-005: canonical rule openings are authorized-scope guidance, not absolute enforcement."""

    def test_owned_rules_drop_inviolable_openings(self):
        for name in OWNED_RULES:
            text = source(f'.claude/rules/{name}.md')
            self.assertNotIn('always enforced', text.lower(), name)
            self.assertNotRegex(text, r'cannot be overridden')

    def test_meaningful_requirements_preserved(self):
        self.assertRegex(source('.claude/rules/security.md'), r'parameterized quer')
        self.assertRegex(source('.claude/rules/verification.md'), r'(?is)regression|failing test')
        self.assertRegex(source('.claude/rules/fix-quality.md'), r'root cause')
        self.assertRegex(source('.claude/rules/anti-anchoring.md'), r'[Tt]rap')

    def test_framework_integrity_is_checks_and_explicit_repair_not_daemon_autoheal(self):
        text = source('.claude/rules/framework-integrity.md')
        self.assertNotRegex(text, r'must trigger auto-heal')
        self.assertNotIn('enforced by the daemon', text)
        self.assertNotRegex(text, r'reconciled automatically')
        # Explicit, opt-in posture instead of an always-installed daemon.
        self.assertRegex(text, r'(?i)explicit')
        self.assertRegex(text, r'(?i)optional|opt-in')

    def test_framework_integrity_names_real_checkers_not_phantom_install_check(self):
        # GIR-002: the broad Claude install.sh has no --check arm (it rejects it as an
        # unknown option), so the rule must not advertise "the installer's --check".
        text = source('.claude/rules/framework-integrity.md')
        self.assertNotRegex(text, r"installer'?s?\s+`?--check`?")
        self.assertNotRegex(text, r'install\.sh\s+`?--check`?')
        # It must instead name the read-only checkers each edition actually ships.
        self.assertIn('validate.sh', text)
        self.assertRegex(text, r'install-delivery\.py --check')
        # Codex's checker requires an explicit scope (framework.py main() makes
        # --user/--project a required mutually-exclusive group); the bare
        # `install-codex.sh --check` is itself an invalid phantom form, so pin the
        # valid scoped syntax the rule actually documents.
        self.assertRegex(text, r'install-codex\.sh --user --check')


if __name__ == '__main__':
    unittest.main()
