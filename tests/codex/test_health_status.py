"""Health STATUS surfaces are honest and fail-closed.

Two consumer surfaces read the observe-only health stream and must never invent
a green verdict:

  * ``global-config/statusline.sh`` — the ⚙<version> glyph. It may show ✓ ONLY
    from a recent, admitted FULL ``validation_result`` (status healthy, complete
    true, exit_code 0, errors 0, internally consistent counts). A version marker
    alone, a scope-qualified SessionStart ``healthcheck_result``, a
    ``complete:false`` run, stale/future/malformed evidence, or no evidence at
    all are all ``?`` (unknown); a current drift or a recent corruption alert is
    ``⚠``. The cache is keyed by $HOME so two sandboxes that share one UID can
    never read each other's verdict.
  * ``validate.sh`` — the ``--json`` summary carries an additive ``complete``
    boolean (true only when the predeclared scope finished), ``--heal`` is
    retired (rejected BEFORE any check or installer run), and an unknown flag
    fails closed.

These tests drive the EXACT source scripts against a disposable HOME. No real
HOME, no installer run, no network, no service calls.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]
STATUSLINE = ROOT / 'global-config/statusline.sh'
VALIDATE = ROOT / 'validate.sh'

BASH = shutil.which('bash') or '/bin/bash'
HAVE_JQ = shutil.which('jq') is not None

_ANSI = re.compile(r'\033\[[0-9;]*m')


def _iso(delta_seconds):
    """ISO-8601 Z timestamp offset from now (negative = past, positive = future)."""
    ts = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return ts.strftime('%Y-%m-%dT%H:%M:%SZ')


class _HealthHome(unittest.TestCase):
    """A disposable HOME with a ~/.claude/analytics health stream."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix='codex-health-status-')).resolve()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.home = self._tmp / 'home'
        self.claude = self.home / '.claude'
        self.analytics = self.claude / 'analytics'
        self.analytics.mkdir(parents=True)

    def write_marker(self, version='9.9.9', **fields):
        lines = ['version=%s\n' % version]
        for key, val in fields.items():
            lines.append('%s=%s\n' % (key, val))
        (self.claude / '.framework-version').write_text(''.join(lines))

    # The watchdog/hook emit COMPACT JSONL ("event":"validation_result"), and the
    # statusline greps for exactly that compact substring. Emit the same compact
    # form (no spaces after separators) so the fixtures match what ships.
    def write_health(self, *records):
        f = self.analytics / 'framework-health.jsonl'
        f.write_text(''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in records))

    # Some fixtures need RAW lines the compact writer cannot express: a spaced
    # (pretty-separated) but valid record, or a recognizably malformed/truncated one.
    def write_health_lines(self, *lines):
        f = self.analytics / 'framework-health.jsonl'
        f.write_text(''.join(line + '\n' for line in lines))

    def write_alerts(self, *records):
        f = self.analytics / 'watchdog-alerts.jsonl'
        f.write_text(''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in records))


@unittest.skipUnless(HAVE_JQ, 'jq required (statusline parses its stdin with jq)')
class StatuslineHealthGlyph(_HealthHome):
    # A Claude Code statusline stdin payload with the minimum fields the renderer reads.
    STDIN = ('{"model":{"display_name":"M"},"cwd":"/x",'
             '"context_window":{"used_percentage":1}}')

    def glyph(self, home=None):
        home = home or self.home
        env = dict(os.environ)
        env['HOME'] = str(home)
        res = subprocess.run([BASH, str(STATUSLINE)], input=self.STDIN,
                             capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        line1 = (res.stdout.splitlines() or [''])[0]
        clean = _ANSI.sub('', line1)
        if '⚙' not in clean:
            return None  # no framework segment rendered at all
        # Segment is "⚙<version> <glyph>"; the glyph is its last whitespace token.
        return clean.split('⚙')[-1].split()[-1]

    # -- the only way to green: a recent admitted FULL validation_result --------
    def _green_vr(self, ts_delta=-60, **over):
        rec = {'event': 'validation_result', 'source': 'watchdog',
               'status': 'healthy', 'exit_code': 0, 'reason': 'ok',
               'complete': True, 'checks': 200, 'errors': 0, 'warnings': 3,
               'ts': _iso(ts_delta)}
        rec.update(over)
        return rec

    def test_version_marker_alone_is_unknown_not_green(self):
        # A version marker with NO health evidence must NOT render ✓ — the core
        # false signal this retirement removed (a marker is not a verdict).
        self.write_marker()
        self.assertEqual(self.glyph(), '?')

    def test_recent_admitted_validation_result_is_green(self):
        self.write_marker()
        self.write_health(self._green_vr())
        self.assertEqual(self.glyph(), '✓')

    def test_complete_false_validation_result_is_not_green(self):
        # rc0/errors0 that LOOKS healthy but declared complete:false (scope not
        # finished) must never be laundered into a green glyph.
        self.write_marker()
        self.write_health(self._green_vr(complete=False))
        self.assertEqual(self.glyph(), '?')

    def test_nonzero_errors_breaks_green_even_if_status_healthy(self):
        self.write_marker()
        self.write_health(self._green_vr(errors=2))
        self.assertEqual(self.glyph(), '?')

    def test_inconsistent_counts_break_green(self):
        # errors+warnings must not exceed checks; an impossible summary is unknown.
        self.write_marker()
        self.write_health(self._green_vr(checks=1, warnings=50))
        self.assertEqual(self.glyph(), '?')

    def test_stale_validation_result_is_unknown(self):
        # Older than the freshness window (2.5x the hourly cadence) -> ? not ✓.
        self.write_marker()
        self.write_health(self._green_vr(ts_delta=-11000))
        self.assertEqual(self.glyph(), '?')

    def test_future_dated_validation_result_is_unknown(self):
        # A clock-skew / forged future timestamp is not fresh evidence.
        self.write_marker()
        self.write_health(self._green_vr(ts_delta=99999))
        self.assertEqual(self.glyph(), '?')

    def test_drift_validation_result_is_warn(self):
        self.write_marker()
        self.write_health(self._green_vr(status='drift', exit_code=1,
                                         errors=4, warnings=0))
        self.assertEqual(self.glyph(), '⚠')

    def test_only_last_validation_result_counts_no_fallback_to_earlier(self):
        # A later unknown/invalid line must NOT fall back to an earlier green.
        self.write_marker()
        self.write_health(self._green_vr(ts_delta=-120),
                          self._green_vr(ts_delta=-30, complete=False))
        self.assertEqual(self.glyph(), '?')

    # -- a scope-qualified SessionStart result can never certify green ----------
    def test_sessionstart_healthy_alone_cannot_certify_green(self):
        self.write_marker()
        self.write_health({'event': 'healthcheck_result',
                           'status': 'healthy', 'scope': 'sessionstart_drift_checks',
                           'checks': 5, 'drift': 0, 'reason': 'ok', 'ts': _iso(-60)})
        self.assertEqual(self.glyph(), '?')

    def test_newer_sessionstart_drift_overrides_older_full_green(self):
        self.write_marker()
        self.write_health(
            self._green_vr(ts_delta=-300),
            {'event': 'healthcheck_result', 'status': 'drift',
             'scope': 'sessionstart_drift_checks', 'checks': 5, 'drift': 2,
             'reason': 'x', 'ts': _iso(-60)})
        self.assertEqual(self.glyph(), '⚠')

    # -- corruption alerts: allowlisted & recent trump to ⚠ ---------------------
    def test_recent_corruption_alert_trumps_green(self):
        self.write_marker()
        self.write_health(self._green_vr())
        self.write_alerts({'event': 'git_fsck_error', 'ts': _iso(-60)})
        self.assertEqual(self.glyph(), '⚠')

    def test_retired_heal_failed_alert_is_ignored(self):
        # heal_* alerts are historical/retired and NOT on the current allowlist;
        # a green verdict must survive a stray legacy alert line.
        self.write_marker()
        self.write_health(self._green_vr())
        self.write_alerts({'event': 'heal_failed', 'ts': _iso(-60)})
        self.assertEqual(self.glyph(), '✓')

    # -- $HOME-fingerprinted cache: no cross-HOME green leak --------------------
    def test_cache_is_isolated_per_home_no_green_leak(self):
        # HOME A renders ✓ and writes its cache. A SEPARATE HOME B (same UID, same
        # /tmp) with only a version marker must still render ? — a /tmp-per-UID
        # cache would have leaked A's green into B.
        self.write_marker()
        self.write_health(self._green_vr())
        self.assertEqual(self.glyph(), '✓')

        home_b = self._tmp / 'home_b'
        (home_b / '.claude' / 'analytics').mkdir(parents=True)
        (home_b / '.claude' / '.framework-version').write_text('version=9.9.9\n')
        self.assertEqual(self.glyph(home=home_b), '?')

    # -- C3-IR01: the LATEST appended record governs, never a fallback to old green --
    # The retired bug let a later record be skipped (literal compact-JSON grep could
    # not see a spaced/malformed line) or lose a strict epoch `>` (epoch 0 from an
    # invalid stamp, or a same-second tie), silently reverting the glyph to the earlier
    # green. Selection is now whitespace-tolerant and by physical append order; an
    # inadmissible latest record fails closed to ?.

    def test_later_spaced_validation_unknown_does_not_revert_to_green(self):
        # A newer, VALID but whitespace-formatted validation_result (unknown /
        # complete:false) is the latest record -> ?, never the earlier compact green.
        green = json.dumps(self._green_vr(ts_delta=-120), separators=(',', ':'))
        spaced_unknown = json.dumps(self._green_vr(ts_delta=-30, status='unknown',
                                                   complete=False))  # default spacing
        self.write_marker()
        self.write_health_lines(green, spaced_unknown)
        self.assertEqual(self.glyph(), '?')

    def test_later_spaced_malformed_validation_fails_closed(self):
        # A recognizable-but-malformed later validation line (truncated JSON) is the
        # latest candidate and must fail closed to ?, not scan back to the green.
        green = json.dumps(self._green_vr(ts_delta=-120), separators=(',', ':'))
        malformed = '{"event": "validation_result", "status":"unknown"'
        self.write_marker()
        self.write_health_lines(green, malformed)
        self.assertEqual(self.glyph(), '?')

    def test_later_healthcheck_unknown_invalid_ts_does_not_revert_to_green(self):
        # A later healthcheck_result unknown with an UNPARSEABLE ts gets epoch 0; the
        # retired strict `>` let the earlier green win. Append order makes the HC the
        # latest record -> ? (and an invalid stamp is inadmissible anyway).
        self.write_marker()
        self.write_health(self._green_vr(ts_delta=-60),
                          {'event': 'healthcheck_result', 'status': 'unknown',
                           'scope': 'sessionstart_drift_checks', 'ts': 'not-a-date'})
        self.assertEqual(self.glyph(), '?')

    def test_later_healthcheck_unknown_same_second_ts_does_not_revert_to_green(self):
        # Same-second timestamp as the earlier green: the retired strict `>` tie-break
        # kept the green. The HC is appended later, so append order makes it latest -> ?.
        same = _iso(-60)
        self.write_marker()
        self.write_health(self._green_vr(ts=same),
                          {'event': 'healthcheck_result', 'status': 'unknown',
                           'scope': 'sessionstart_drift_checks', 'ts': same})
        self.assertEqual(self.glyph(), '?')


class ValidatorHealthContract(unittest.TestCase):
    """validate.sh: --heal retired, unknown flags fail closed, --json completeness."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix='codex-validate-contract-')).resolve()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.home = self._tmp / 'home'
        self.home.mkdir(parents=True)

    def _run(self, *args, cwd=None):
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        return subprocess.run([BASH, str(VALIDATE), *args], capture_output=True,
                              text=True, env=env, cwd=str(cwd or ROOT), timeout=120)

    def _json(self, res):
        lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, 'no stdout to parse as JSON\n' + res.stderr)
        return json.loads(lines[-1])

    # -- --heal is retired: rejected BEFORE any check or installer run ----------
    def test_heal_is_rejected_and_runs_no_installer(self):
        # Scratch dir with a POISON install.sh: if --heal were still honored it
        # would run the installer and drop the sentinel. Rejection happens in the
        # argument loop before any file is touched, so the sentinel never appears.
        scratch = self._tmp / 'scratch'
        scratch.mkdir()
        shutil.copy2(VALIDATE, scratch / 'validate.sh')
        sentinel = scratch / 'INSTALL_CALLED'
        poison = scratch / 'install.sh'
        poison.write_text('#!/usr/bin/env bash\nprintf called >> "%s"\nexit 0\n' % sentinel)
        poison.chmod(0o755)

        res = self._run('--heal', cwd=scratch)
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn('retired', res.stderr.lower())
        self.assertFalse(sentinel.exists(),
                         '--heal invoked the installer (laundering path not retired)')
        # No validation summary was produced: it exited before running anything.
        self.assertNotIn('Validation Summary', res.stdout)

    def test_heal_with_json_also_rejected_no_json_emitted(self):
        # The retirement must hold on the JSON path too: no laundered summary.
        res = self._run('--heal', '--json')
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertNotIn('{', res.stdout)

    def test_unknown_flag_fails_closed(self):
        res = self._run('--definitely-not-a-flag')
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn('unknown argument', res.stderr.lower())

    # -- --json completeness: additive, honest, fail-closed on ambiguity --------
    def test_json_emits_complete_boolean(self):
        res = self._run('--json')
        summary = self._json(res)
        self.assertIn('complete', summary)
        self.assertIsInstance(summary['complete'], bool)

    def test_not_installed_home_is_complete_true(self):
        # A clean CI/empty HOME validates source only and makes no installed-runtime
        # claim: that is a COMPLETE run (true), not an incomplete one.
        res = self._run('--json')
        self.assertTrue(self._json(res)['complete'])

    def test_all_disabled_marker_is_complete_true(self):
        # Fresh default-off core (3 components explicitly disabled) is complete.
        (self.home / '.claude').mkdir(parents=True)
        (self.home / '.claude' / '.framework-version').write_text(
            'version=9.9.9\nanalytics=disabled\nwatchdog=disabled\nnotifications=disabled\n')
        self.assertTrue(self._json(self._run('--json'))['complete'])

    def test_ambiguous_marker_makes_run_incomplete(self):
        # An unparseable component selection (bad value -> unknown) cannot be
        # certified: the run is complete:false (watchdog will read it as UNKNOWN),
        # never silently green. errors are incidental here; only `complete` matters.
        (self.home / '.claude').mkdir(parents=True)
        (self.home / '.claude' / '.framework-version').write_text(
            'version=9.9.9\nwatchdog=bogus\nanalytics=disabled\nnotifications=disabled\n')
        self.assertFalse(self._json(self._run('--json'))['complete'])


if __name__ == '__main__':
    unittest.main()
