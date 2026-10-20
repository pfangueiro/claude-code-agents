"""Background-health scripts are OBSERVE-ONLY: they report framework health and
keep backups, but they never repair, migrate, reseed, or run the analytics
collector in the background.

These tests drive the EXACT source scripts (no re-implementation) against a
disposable HOME and a disposable framework repo. Autonomy is probed with poison
stubs: an `install.sh` that records its invocation and fails, and a
`collector.py` that records its invocation. A single executed stub fails the
test. Health admission is probed with a stub validator whose stdout, stderr and
exit code are controlled byte-for-byte, so the watchdog's strict JSON admission
is exercised across malformed/noisy/multiple JSON, invalid counts, rc/result
disagreement, missing tools and an absent validator. No real HOME, no launchctl,
no service calls, no network.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
WATCHDOG = ROOT / 'global-config/daemon/claude-framework-watchdog.sh'
SESSION_HOOK = ROOT / 'global-config/hooks/session-start-healthcheck.sh'

BASH = shutil.which('bash') or '/bin/bash'
HAVE_JQ = shutil.which('jq') is not None

# Tools the scripts invoke by name; the farm symlinks these so a PATH without jq
# can be simulated while every other command the scripts need stays available.
FARM_TOOLS = [
    'bash', 'sh', 'env', 'date', 'cat', 'tr', 'sed', 'head', 'tail', 'mkdir',
    'rm', 'mv', 'ln', 'ls', 'wc', 'find', 'stat', 'git', 'tar', 'basename',
    'grep', 'awk', 'sort', 'cut', 'dirname', 'touch', 'chmod', 'cp', 'mktemp',
    'printf', 'true', 'false', 'perl', 'sleep', 'uniq', 'shasum', 'sha256sum',
]


class BackgroundHealthBase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(__import__('tempfile').mkdtemp(prefix='codex-bg-health-')).resolve()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.base = self._tmp
        self.home = self.base / 'home'
        self.repo = self.base / 'repo'
        self.claude = self.home / '.claude'
        self.analytics = self.claude / 'analytics'
        self.snapshots = self.claude / 'snapshots'
        # repo/.claude/agents is what install.sh's marker validation requires.
        (self.repo / '.claude' / 'agents').mkdir(parents=True)
        self.analytics.mkdir(parents=True)
        (self.claude / '.framework-path').write_text(str(self.repo) + '\n')

    # -- fixtures -----------------------------------------------------------
    def poison_installer(self):
        """An install.sh that records invocation and fails. Must never run."""
        sentinel = self.base / 'INSTALL_CALLED'
        p = self.repo / 'install.sh'
        p.write_text('#!/usr/bin/env bash\n'
                     f'printf "called %s\\n" "$*" >> "{sentinel}"\n'
                     'exit 7\n')
        p.chmod(0o755)
        return sentinel

    def poison_collector(self):
        """A collector.py that records invocation. Must never run."""
        sentinel = self.base / 'COLLECTOR_CALLED'
        p = self.analytics / 'collector.py'
        p.write_text('#!/usr/bin/env python3\n'
                     f'open(r"{sentinel}", "a").write("called\\n")\n')
        return sentinel

    def write_validator(self, stdout='', exit_code=0, stderr='', repo=None):
        """A validate.sh emitting exact stdout/stderr bytes and a fixed rc.

        `repo` targets a specific checkout (defaults to self.repo) so a
        space-containing repository path can be exercised end to end.
        """
        repo = repo or self.repo
        out_file = repo / '_vout'
        err_file = repo / '_verr'
        out_file.write_text(stdout)
        err_file.write_text(stderr)
        p = repo / 'validate.sh'
        p.write_text('#!/usr/bin/env bash\n'
                     f'cat "{out_file}"\n'
                     f'cat "{err_file}" 1>&2\n'
                     f'exit {int(exit_code)}\n')
        p.chmod(0o755)
        return p

    def write_self_killing_validator(self, stdout):
        """A validate.sh that prints a full, valid summary and THEN SIGKILLs
        itself. The captured exit code is a real 137 (128 + SIGKILL), proving
        the wrapper admits on the actual child status, not a faked `exit 137`."""
        out_file = self.repo / '_vout'
        out_file.write_text(stdout)
        p = self.repo / 'validate.sh'
        p.write_text('#!/usr/bin/env bash\n'
                     f'cat "{out_file}"\n'
                     'kill -KILL $$\n')
        p.chmod(0o755)
        return p

    def set_autonomy_marker(self):
        (self.claude / '.framework-autonomy').write_text('enabled\n')

    def write_version_marker(self, **fields):
        """Write ~/.claude/.framework-version with explicit selection fields.

        A fresh-core fixture tags analytics/watchdog/notifications=disabled so the
        test asserts the DELIBERATE default-off state, never a legacy marker whose
        missing fields read as unknown. Fields are plain key=value data (never eval'd).
        """
        lines = ['version=9.9.9\n']
        for key, val in fields.items():
            lines.append('%s=%s\n' % (key, val))
        (self.claude / '.framework-version').write_text(''.join(lines))

    def farm_path(self, include_jq=True):
        farm = self.base / ('farm-jq' if include_jq else 'farm-nojq')
        farm.mkdir(exist_ok=True)
        tools = list(FARM_TOOLS)
        if include_jq:
            tools.append('jq')
        for tool in tools:
            src = shutil.which(tool)
            if src:
                link = farm / tool
                if not link.exists():
                    os.symlink(src, link)
        return str(farm)

    # -- runners ------------------------------------------------------------
    def _run(self, script, path=None):
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        env['GIT_CEILING_DIRECTORIES'] = str(self.base)
        if path is not None:
            env['PATH'] = path
        return subprocess.run([BASH, str(script)], capture_output=True,
                              text=True, env=env, cwd=str(self.base), timeout=120)

    def run_watchdog(self, path=None):
        return self._run(WATCHDOG, path=path)

    def run_session_hook(self, path=None):
        return self._run(SESSION_HOOK, path=path)

    # -- assertions / readers ----------------------------------------------
    def events(self, name, log='framework-health.jsonl'):
        f = self.analytics / log
        out = []
        if f.exists():
            for line in f.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get('event') == name:
                    out.append(obj)
        return out

    def latest(self, name, log='framework-health.jsonl'):
        found = self.events(name, log=log)
        return found[-1] if found else None

    def assert_no_autonomy(self, install_sentinel, collector_sentinel):
        self.assertFalse(install_sentinel.exists(),
                         'install.sh was invoked by a background health script')
        self.assertFalse(collector_sentinel.exists(),
                         'collector.py was invoked by a background health script')
        # The retired heal/migration/regen event names must never be emitted.
        for banned in ('heal_triggered', 'heal_succeeded', 'heal_failed',
                       'deferred_regen_success', 'deferred_regen_skipped'):
            self.assertEqual(self.events(banned), [],
                             f'retired event {banned!r} was emitted')
            self.assertEqual(self.events(banned, log='watchdog-alerts.jsonl'), [])


# ===========================================================================
# Watchdog: strict validator admission
# ===========================================================================
@unittest.skipUnless(HAVE_JQ, 'jq required for admission (present on target)')
class WatchdogAdmission(BackgroundHealthBase):
    def _result(self, stdout, exit_code, stderr=''):
        self.write_validator(stdout=stdout, exit_code=exit_code, stderr=stderr)
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)  # nonblocking transport
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr, 'no validation_result event emitted')
        return vr

    def test_rc0_zero_errors_is_healthy(self):
        vr = self._result('{"checks":7,"errors":0,"warnings":2,"events":[]}', 0)
        self.assertEqual(vr['status'], 'healthy')
        self.assertEqual(vr['exit_code'], 0)
        self.assertEqual(vr['checks'], 7)
        self.assertEqual(vr['errors'], 0)

    def test_rc1_positive_errors_is_drift(self):
        vr = self._result('{"checks":7,"errors":3,"warnings":0,"events":[]}', 1)
        self.assertEqual(vr['status'], 'drift')
        self.assertEqual(vr['exit_code'], 1)
        self.assertEqual(vr['errors'], 3)

    def test_rc1_zero_errors_is_unknown_not_healthy(self):
        vr = self._result('{"checks":7,"errors":0,"warnings":0,"events":[]}', 1)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'rc_result_disagreement')

    def test_rc0_positive_errors_is_unknown_not_coerced_to_zero(self):
        vr = self._result('{"checks":7,"errors":4,"warnings":0,"events":[]}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'rc_result_disagreement')
        # The real error count is retained, never silently zeroed.
        self.assertEqual(vr['errors'], 4)

    def test_empty_output_is_unknown(self):
        vr = self._result('', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'empty_output')
        self.assertNotIn('errors', vr)

    def test_malformed_json_is_unknown(self):
        vr = self._result('{not json at all', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertNotIn('errors', vr)

    def test_noisy_output_is_unknown(self):
        vr = self._result('warming up...\n{"checks":7,"errors":0,"warnings":0}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'not_single_json_object')

    def test_multiple_json_objects_is_unknown(self):
        vr = self._result('{"checks":7,"errors":0,"warnings":0}\n'
                          '{"checks":1,"errors":0,"warnings":0}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'not_single_json_object')

    def test_missing_counts_is_unknown(self):
        vr = self._result('{"errors":0,"warnings":0}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'invalid_or_missing_counts')

    def test_string_count_is_unknown(self):
        vr = self._result('{"checks":"7","errors":0,"warnings":0}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'invalid_or_missing_counts')

    def test_bool_count_is_unknown(self):
        vr = self._result('{"checks":true,"errors":0,"warnings":0}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'invalid_or_missing_counts')

    def test_negative_count_is_unknown(self):
        vr = self._result('{"checks":7,"errors":-1,"warnings":0}', 1)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'invalid_or_missing_counts')

    def test_float_count_is_unknown(self):
        vr = self._result('{"checks":7.5,"errors":0,"warnings":0}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'invalid_or_missing_counts')

    def test_zero_checks_is_unknown_not_healthy(self):
        vr = self._result('{"checks":0,"errors":0,"warnings":0}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'zero_checks')

    def test_absent_validator_is_unknown_with_null_exit_code(self):
        # No validate.sh written at all.
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'validator_absent')
        self.assertIsNone(vr['exit_code'])  # JSON null

    def test_missing_jq_is_unknown_not_healthy(self):
        # A healthy-looking summary must still be UNKNOWN when jq is unavailable
        # to parse/validate it — transport success is never health.
        self.write_validator('{"checks":7,"errors":0,"warnings":0}', 0)
        res = self.run_watchdog(path=self.farm_path(include_jq=False))
        self.assertEqual(res.returncode, 0, res.stderr)
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'jq_missing')

    # -- issue 1: internally impossible count totals -----------------------
    def test_impossible_warnings_total_is_unknown(self):
        # checks1/errors0/warnings99 at rc0 previously certified HEALTHY. The
        # real validator counts every WARN as a CHECK, so warnings > checks is
        # internally impossible and must never be admitted as health evidence.
        vr = self._result('{"checks":1,"errors":0,"warnings":99}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'inconsistent_counts')
        self.assertEqual(vr['exit_code'], 0)       # real rc preserved
        self.assertEqual(vr['checks'], 1)          # real counts preserved
        self.assertEqual(vr['errors'], 0)
        self.assertEqual(vr['warnings'], 99)

    def test_impossible_errors_total_is_unknown(self):
        # errors > checks at rc1 previously certified DRIFT; it is impossible.
        vr = self._result('{"checks":1,"errors":8,"warnings":0}', 1)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'inconsistent_counts')
        self.assertEqual(vr['exit_code'], 1)
        self.assertEqual(vr['errors'], 8)

    def test_counts_sum_equal_to_checks_is_consistent_control(self):
        # Boundary control: errors + warnings == checks is CONSISTENT, so a
        # genuine rc1/errors>0 run is still admitted as drift (not over-rejected).
        vr = self._result('{"checks":2,"errors":1,"warnings":1}', 1)
        self.assertEqual(vr['status'], 'drift')
        self.assertEqual(vr['reason'], 'validation_errors')

    # -- issue 2: interrupted / undocumented exit codes --------------------
    def test_validator_signaled_after_valid_output_is_unknown_not_drift(self):
        # A REAL SIGKILL (137), not a faked `exit 137`: the validator prints a
        # complete, valid, drift-looking summary and THEN kills itself. An
        # interrupted run is incomplete -> UNKNOWN, never a completed drift.
        self.write_self_killing_validator('{"checks":1,"errors":1,"warnings":0}')
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)  # wrapper stays nonblocking
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'validator_signaled')
        self.assertEqual(vr['exit_code'], 137)   # 128 + SIGKILL(9): real child status
        self.assertEqual(vr['errors'], 1)        # real count retained, not hidden

    def test_unexpected_exit_code_2_is_unknown_not_drift(self):
        # rc not in {0,1} is an undocumented/faulted exit -> UNKNOWN even though
        # the summary prints positive errors (previously mislabeled drift).
        vr = self._result('{"checks":5,"errors":2,"warnings":0}', 2)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'unexpected_exit_code')
        self.assertEqual(vr['exit_code'], 2)
        self.assertEqual(vr['errors'], 2)

    def test_unexpected_exit_code_91_is_unknown(self):
        vr = self._result('{"checks":5,"errors":0,"warnings":0}', 91)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'unexpected_exit_code')
        self.assertEqual(vr['exit_code'], 91)

    # -- validator-declared completeness (the `complete` admission flag) ---
    def test_complete_true_rc0_is_healthy_and_emits_complete(self):
        vr = self._result('{"checks":7,"errors":0,"warnings":0,"complete":true}', 0)
        self.assertEqual(vr['status'], 'healthy')
        self.assertTrue(vr['complete'])

    def test_absent_complete_is_compat_healthy_with_complete_true(self):
        # A legacy summary WITHOUT the field is admitted (compat) and the emitted
        # event still stamps complete:true so the statusline can require it for green.
        vr = self._result('{"checks":7,"errors":0,"warnings":0}', 0)
        self.assertEqual(vr['status'], 'healthy')
        self.assertTrue(vr['complete'])

    def test_complete_false_rc0_zero_errors_is_unknown_not_healthy(self):
        # complete:false means the validator could not finish its scope: UNKNOWN even
        # though rc0/errors0 look healthy, with the real rc/counts preserved.
        vr = self._result('{"checks":7,"errors":0,"warnings":0,"complete":false}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'validator_incomplete')
        self.assertFalse(vr['complete'])
        self.assertEqual(vr['exit_code'], 0)
        self.assertEqual(vr['checks'], 7)

    def test_complete_invalid_type_is_unknown(self):
        vr = self._result('{"checks":7,"errors":0,"warnings":0,"complete":"yes"}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'invalid_complete')
        self.assertFalse(vr['complete'])

    def test_complete_null_is_unknown_not_compat(self):
        # An explicit null is present-but-non-boolean -> invalid, never compat-true.
        vr = self._result('{"checks":7,"errors":0,"warnings":0,"complete":null}', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'invalid_complete')

    def test_complete_true_rc1_errors_is_drift_with_complete_true(self):
        vr = self._result('{"checks":7,"errors":2,"warnings":0,"complete":true}', 1)
        self.assertEqual(vr['status'], 'drift')
        self.assertTrue(vr['complete'])
        self.assertEqual(vr['errors'], 2)

    def test_every_unknown_outcome_stamps_complete_false(self):
        # Any UNKNOWN verdict (here: malformed JSON) carries complete:false.
        vr = self._result('{garbage', 0)
        self.assertEqual(vr['status'], 'unknown')
        self.assertFalse(vr['complete'])


# ===========================================================================
# Watchdog: repository-marker resolution (issue 3)
# ===========================================================================
class WatchdogRepoResolution(BackgroundHealthBase):
    """An unresolved source marker must still record exactly one terminal
    `validation_result` (unknown, exit_code null, qualified reason) instead of
    exiting silently, and a valid repo path containing spaces must resolve and
    actually run the validator (no `tr -d '[:space:]'` corruption)."""

    def test_missing_marker_emits_unknown_not_silent(self):
        (self.claude / '.framework-path').unlink()
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr, 'unresolved repo must still record one result')
        self.assertEqual(vr['status'], 'unknown')
        self.assertIsNone(vr['exit_code'])          # JSON null — no run happened
        self.assertEqual(vr['reason'], 'framework_path_marker_missing')
        self.assertNotIn('checks', vr)              # no counts when nothing ran

    def test_empty_marker_emits_unknown(self):
        (self.claude / '.framework-path').write_text('\n')
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'framework_path_empty')
        self.assertIsNone(vr['exit_code'])

    def test_invalid_marker_path_emits_unknown(self):
        bogus = self.base / 'not-a-framework'
        bogus.mkdir()
        (self.claude / '.framework-path').write_text(str(bogus) + '\n')
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'framework_path_invalid')
        self.assertIsNone(vr['exit_code'])

    @unittest.skipIf(os.geteuid() == 0,
                     'root bypasses file-mode perms; cannot simulate unreadable')
    def test_unreadable_marker_emits_unknown(self):
        marker = self.claude / '.framework-path'
        marker.write_text(str(self.repo) + '\n')
        marker.chmod(0o000)
        try:
            res = self.run_watchdog()
        finally:
            marker.chmod(0o600)  # let cleanup remove the tree
        self.assertEqual(res.returncode, 0, res.stderr)
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr)
        self.assertEqual(vr['status'], 'unknown')
        self.assertEqual(vr['reason'], 'framework_path_unreadable')
        self.assertIsNone(vr['exit_code'])

    @unittest.skipUnless(HAVE_JQ, 'jq required to run the stub validator admission')
    def test_space_path_marker_resolves_and_runs_validator(self):
        # A valid repo whose path contains a space must survive resolution and
        # the stub validator must actually run (admitting a real control result).
        spaced = self.base / 'repo with spaces'
        (spaced / '.claude' / 'agents').mkdir(parents=True)
        (self.claude / '.framework-path').write_text(str(spaced) + '\n')
        self.write_validator('{"checks":3,"errors":0,"warnings":0}', 0, repo=spaced)
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        vr = self.latest('validation_result')
        self.assertIsNotNone(vr, 'a valid spaced repo path must resolve and run')
        self.assertEqual(vr['status'], 'healthy')
        self.assertEqual(vr['reason'], 'ok')
        self.assertEqual(vr['checks'], 3)


# ===========================================================================
# Watchdog: diagnostic JSONL serialization (issue 4 / BH-05)
# ===========================================================================
@unittest.skipUnless(HAVE_JQ, 'jq required to JSON-encode diagnostics')
class WatchdogDiagnosticSerialization(BackgroundHealthBase):
    def _raw_lines(self, log='framework-health.jsonl'):
        f = self.analytics / log
        if not f.exists():
            return []
        return [ln for ln in f.read_text().splitlines() if ln.strip()]

    def test_validate_quick_line_valid_json_with_backslashes(self):
        # stderr carries a literal backslash-q, a newline, quotes and a trailing
        # backslash — exactly the bytes a quote/newline-only escaper turned into
        # invalid JSONL. EVERY health-log line must still parse as JSON.
        self.write_validator('{"checks":4,"errors":0,"warnings":1}', 0,
                             stderr='bad \\q escape\nline2 "quoted" end\\')
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        for line in self._raw_lines():
            json.loads(line)  # raises on the old malformed diagnostic line (RED)
        vq = self.latest('validate_quick')
        self.assertIsNotNone(vq)
        self.assertEqual(vq['exit_code'], 0)
        self.assertIn('\\q', vq['stderr'])        # backslash preserved faithfully
        self.assertIn('"quoted"', vq['stderr'])    # quotes preserved
        self.assertIn('\n', vq['stderr'])          # newline preserved as real \n
        self.assertTrue(vq['stderr'].endswith('\\'))  # trailing backslash kept
        # The verdict itself is unaffected and still valid/healthy.
        self.assertEqual(self.latest('validation_result')['status'], 'healthy')

    def test_validate_quick_jq_absent_is_typed_metadata_only(self):
        # Without jq there is no safe string encoder, so the diagnostic degrades
        # to typed numeric metadata — never raw, unescaped diagnostic text.
        self.write_validator('{"checks":4,"errors":0,"warnings":0}', 0,
                             stderr='raw \\q "danger" text')
        res = self.run_watchdog(path=self.farm_path(include_jq=False))
        self.assertEqual(res.returncode, 0, res.stderr)
        for line in self._raw_lines():
            json.loads(line)  # every line valid, including the typed fallback
        vq = self.latest('validate_quick')
        self.assertIsNotNone(vq)
        self.assertNotIn('stdout', vq)     # no raw text fields
        self.assertNotIn('stderr', vq)
        self.assertIn('stderr_bytes', vq)  # typed metadata instead
        self.assertEqual(vq['exit_code'], 0)


# ===========================================================================
# Watchdog + SessionStart: no autonomous background mutation
# ===========================================================================
class NoBackgroundMutation(BackgroundHealthBase):
    @unittest.skipUnless(HAVE_JQ, 'jq required')
    def test_watchdog_drift_does_not_heal(self):
        inst = self.poison_installer()
        coll = self.poison_collector()
        self.write_validator('{"checks":7,"errors":2,"warnings":0,"events":[]}', 1)
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assert_no_autonomy(inst, coll)
        vr = self.latest('validation_result')
        self.assertEqual(vr['status'], 'drift')  # honest, not repaired, not hidden
        self.assertEqual(vr['errors'], 2)

    @unittest.skipUnless(HAVE_JQ, 'jq required')
    def test_watchdog_malformed_never_runs_installer(self):
        inst = self.poison_installer()
        coll = self.poison_collector()
        self.write_validator('{garbage', 0)
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assert_no_autonomy(inst, coll)
        self.assertEqual(self.latest('validation_result')['status'], 'unknown')

    def test_watchdog_autonomy_marker_does_not_reenable_mutation(self):
        # A pre-existing legacy autonomy marker is NOT a background-mutation grant.
        inst = self.poison_installer()
        coll = self.poison_collector()
        self.set_autonomy_marker()
        self.write_validator('{"checks":7,"errors":9,"warnings":0,"events":[]}', 1)
        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assert_no_autonomy(inst, coll)

    def test_sessionstart_drift_reports_manual_repair_not_heal(self):
        inst = self.poison_installer()
        # Deployed hook differs from source -> hook_hash drift.
        srchooks = self.repo / 'global-config' / 'hooks'
        srchooks.mkdir(parents=True)
        (srchooks / 'sample.sh').write_text('# source A\n')
        dsthooks = self.claude / 'hooks'
        dsthooks.mkdir(parents=True)
        (dsthooks / 'sample.sh').write_text('# deployed B (drifted)\n')
        res = self.run_session_hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(inst.exists(), 'session hook forked a heal')
        drifts = self.events('drift_detected')
        self.assertTrue(drifts, 'expected a drift_detected event')
        for d in drifts:
            self.assertEqual(d.get('action'), 'manual_repair_required')
            self.assertNotEqual(d.get('action'), 'trigger_heal')
        self.assertEqual(self.latest('healthcheck_result')['status'], 'drift')

    def test_sessionstart_autonomy_marker_does_not_fork_heal(self):
        inst = self.poison_installer()
        self.set_autonomy_marker()
        srchooks = self.repo / 'global-config' / 'hooks'
        srchooks.mkdir(parents=True)
        (srchooks / 'sample.sh').write_text('# source A\n')
        dsthooks = self.claude / 'hooks'
        dsthooks.mkdir(parents=True)
        (dsthooks / 'sample.sh').write_text('# deployed B\n')
        res = self.run_session_hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(inst.exists())
        # Deterministic evidence (independent of the retired detached fork's
        # timing): the observe-only hook emits healthcheck_result and labels
        # drift for manual repair; it never spawns a heal on an autonomy marker.
        hr = self.latest('healthcheck_result')
        self.assertIsNotNone(hr, 'observe-only hook must emit a healthcheck_result')
        self.assertEqual(hr['status'], 'drift')
        for d in self.events('drift_detected'):
            self.assertEqual(d.get('action'), 'manual_repair_required')


# ===========================================================================
# SessionStart: honest observe-only verdict
# ===========================================================================
class SessionStartVerdict(BackgroundHealthBase):
    def _template(self):
        gc = self.repo / 'global-config'
        gc.mkdir(parents=True, exist_ok=True)
        tmpl = {
            'env': {'CLAUDE_CODE_EFFORT_LEVEL': 'xhigh', 'FOO': 'bar'},
            'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'x'}]}]},
            'statusLine': {'type': 'command', 'command': 'y'},
        }
        (gc / 'settings.json.template').write_text(json.dumps(tmpl, indent=2))
        return tmpl

    @unittest.skipUnless(HAVE_JQ, 'jq required')
    def test_clean_install_is_healthy_without_analytics_payloads(self):
        tmpl = self._template()
        # Tag the fixture as a DELIBERATE fresh-core install: analytics / watchdog /
        # notifications explicitly disabled, so the healthy verdict reflects an
        # intended default-off state and not a hidden legacy/unknown marker.
        self.write_version_marker(analytics='disabled', watchdog='disabled',
                                  notifications='disabled')
        # Settings identical to template -> env/wiring/statusline all clean.
        (self.claude / 'settings.json').write_text(json.dumps(tmpl, indent=2))
        srchooks = self.repo / 'global-config' / 'hooks'
        srchooks.mkdir(parents=True, exist_ok=True)
        (srchooks / 'sample.sh').write_text('# identical\n')
        dsthooks = self.claude / 'hooks'
        dsthooks.mkdir(parents=True)
        (dsthooks / 'sample.sh').write_text('# identical\n')
        # Deliberately NO collector.py / server.py / claude-obs.db present.
        res = self.run_session_hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        hr = self.latest('healthcheck_result')
        self.assertIsNotNone(hr)
        self.assertEqual(hr['status'], 'healthy')
        self.assertGreater(hr['checks'], 0)
        self.assertEqual(hr['drift'], 0)
        # Absent analytics on a fresh minimal install is NOT drift or repair.
        self.assertEqual(self.events('drift_detected'), [])
        self.assertEqual(self.events('analytics_missing'), [])
        self.assertEqual(self.events('deferred_regen_skipped'), [])

    def test_missing_jq_yields_unknown_not_healthy(self):
        tmpl = self._template()
        # Tag the fixture with the 3 explicit disabled selection fields so the ONLY
        # reason the run is unknown is the missing jq tool — without this, an absent
        # optional-component field folds to an unknown SELECTION and (first-wins)
        # masks jq_missing, so the test would assert the wrong reason.
        self.write_version_marker(analytics='disabled', watchdog='disabled',
                                  notifications='disabled')
        (self.claude / 'settings.json').write_text(json.dumps(tmpl, indent=2))
        res = self.run_session_hook(path=self.farm_path(include_jq=False))
        self.assertEqual(res.returncode, 0, res.stderr)
        hr = self.latest('healthcheck_result')
        self.assertIsNotNone(hr)
        self.assertEqual(hr['status'], 'unknown')
        self.assertEqual(hr['reason'], 'jq_missing')

    def test_no_marker_emits_one_qualified_unknown(self):
        # No .framework-path marker: the observe-only hook must NOT exit silently
        # (an absent result would leave an older green unqualified downstream). It
        # records exactly ONE scope-qualified healthcheck_result(unknown, checks=0)
        # so a consumer sees "could not check", never a stale pass. Hook transport
        # still exits 0 (nonblocking).
        (self.claude / '.framework-path').unlink()
        res = self.run_session_hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        results = self.events('healthcheck_result')
        self.assertEqual(len(results), 1, 'exactly one terminal result expected')
        hr = results[0]
        self.assertEqual(hr['status'], 'unknown')
        self.assertEqual(hr['scope'], 'sessionstart_drift_checks')
        self.assertEqual(hr['checks'], 0)
        self.assertEqual(hr['reason'], 'framework_path_unresolved')


# ===========================================================================
# Watchdog: authorized backups/retention remain intact
# ===========================================================================
@unittest.skipUnless(HAVE_JQ and shutil.which('git') and shutil.which('tar'),
                     'git+tar required for backup behavior')
class BackupsIntact(BackgroundHealthBase):
    def test_userconfig_and_bundle_snapshots_still_created(self):
        # Make the repo a real git repo so the bundle snapshot has refs.
        env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True,
                       capture_output=True, env=env, timeout=30)
        (self.repo / 'README').write_text('x\n')
        for args in (['add', 'README'],
                     ['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'init']):
            subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                           capture_output=True, env=env, timeout=30)
        # Backup inputs present under HOME.
        (self.claude / 'settings.json').write_text('{}\n')
        (self.claude / 'hooks').mkdir()
        (self.claude / 'hooks' / 'h.sh').write_text('# hook\n')
        self.write_validator('{"checks":3,"errors":0,"warnings":0,"events":[]}', 0)

        res = self.run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        tgz = list(self.snapshots.glob('userconfig-*.tgz'))
        bundle = list(self.snapshots.glob('claude-code-agents-*.bundle'))
        self.assertTrue(tgz, 'userconfig tarball backup was not created')
        self.assertTrue(bundle, 'git bundle snapshot was not created')
        self.assertEqual(self.latest('validation_result')['status'], 'healthy')


if __name__ == '__main__':
    unittest.main()
