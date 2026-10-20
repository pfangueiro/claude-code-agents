#!/usr/bin/env python3
"""Focused tests for validate.sh's owner-customization PRESERVATION semantics.

These cover three consumer mismatches where the OBSERVE-ONLY validator used to
report a legitimate, installer-blessed state as drift (a fail-CLOSED false
positive), while still catching genuine corruption of the framework's own
bindings:

  1. env-key presence — an ABSENT ``CLAUDE_CODE_EFFORT_LEVEL`` is a deliberate
     owner/native-default preference that install.sh's add-only env reconcile
     preserves (it is never re-seeded onto an existing settings object) and the
     SessionStart healthcheck accepts. The quick-presence loop must NOT require
     it; an empty string is valid too; every OTHER template env key stays
     required.
  2. foreign hooks — a foreign hook the owner adds (either inside the canonical
     framework group or as an entirely separate group) is preserved verbatim by
     install.sh sync_hooks. The structural hook-drift check must compare only the
     FRAMEWORK-OWNED entries after projecting foreign ones out, yet still detect a
     MISSING / MODIFIED / DUPLICATED framework entry — and never adopt a
     basename look-alike (``/elsewhere/file-protection.sh``) in place of the real
     binding.
  3. corrupt settings — install.sh does NOT reseed a corrupt ``settings.json``; it
     preserves the file, writes a forensic copy and flags manual review. The
     validator's diagnostic must say so, not promise a reseed.

Everything runs the ACTUAL source install.sh ONCE into a DISPOSABLE HOME under the
system temp dir (with a stub ``launchctl`` on PATH and ``CLAUDE_WATCHDOG_RUN=1`` so
no real launchd job, service, cache or collector is ever touched), then exercises
the ACTUAL ``validate.sh --quick --json`` against mutated copies of the installed
settings.json. No real HOME, no network, no ``--heal`` gate. The validator is
observer-only, so a run must not alter the owner's settings bytes.

Reuses the disposable-HOME / stub-launchctl fixture helpers from
test_installer_options._Base.
"""

import json
import os
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_installer_options import _Base, _write_exec, INSTALL, REPO

VALIDATE = REPO / "validate.sh"


class _ValidatorFixture(_Base):
    """One real install shared across the preservation tests; each test runs the
    real validator against a mutated copy of the installed settings.json and the
    pristine bytes are restored before and after every test."""

    @classmethod
    def setUpClass(cls):
        cls._cls_tmp = tempfile.TemporaryDirectory(prefix="vp-")
        root = Path(cls._cls_tmp.name)
        cls._cls_home = root / "home"
        cls._cls_home.mkdir(parents=True)
        cls._cls_stubbin = root / "bin"
        cls._cls_stubbin.mkdir()
        cls._cls_root = root
        # launchctl is ALWAYS stubbed (exit 0): never touch the real one, and its
        # success makes validate.sh's macOS "daemon loaded" structural check PASS
        # without a real launchd job.
        _write_exec(
            cls._cls_stubbin / "launchctl",
            '#!/bin/bash\nprintf "%%s\\n" "$*" >> "%s"\nexit 0\n'
            % (root / "launchctl.calls"),
        )
        env = os.environ.copy()
        env["HOME"] = str(cls._cls_home)
        env["PATH"] = f"{cls._cls_stubbin}:{env.get('PATH', '')}"
        env.pop("CLAUDE_UPGRADE_ASSUME_YES", None)
        # Skip the post-register kickstart + /tmp statusline-cache rm.
        env["CLAUDE_WATCHDOG_RUN"] = "1"
        proc = subprocess.run(
            ["bash", str(INSTALL)],
            cwd=str(REPO),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise AssertionError(
                "fixture install.sh failed (rc=%d)\nSTDOUT:\n%s\nSTDERR:\n%s"
                % (proc.returncode, proc.stdout, proc.stderr)
            )
        settings = cls._cls_home / ".claude" / "settings.json"
        cls._pristine_bytes = settings.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls._cls_tmp.cleanup()

    def setUp(self):
        # Reuse _Base's helpers by pointing them at the shared fixture (do NOT call
        # _Base.setUp — that would build a second, empty temp HOME with no install).
        self.root = self._cls_root
        self.home = self._cls_home
        self.stubbin = self._cls_stubbin
        self.launchctl_log = self._cls_root / "launchctl.calls"
        self._restore_pristine()

    def tearDown(self):
        self._restore_pristine()

    # ---- helpers -----------------------------------------------------------
    def _restore_pristine(self):
        self._settings_path().write_bytes(self._pristine_bytes)

    def _pristine_settings(self):
        return json.loads(self._pristine_bytes.decode())

    def _validate(self):
        """Run the real ``validate.sh --quick --json`` against the current fixture
        settings. Returns (proc, parsed_json_or_None)."""
        env = self._env(watchdog_run=True)
        proc = subprocess.run(
            ["bash", str(VALIDATE), "--quick", "--json"],
            cwd=str(REPO),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = None
        return proc, data

    def _run_mutated(self, mutate):
        """Load pristine settings, apply ``mutate`` (in place), write, then validate."""
        data = self._pristine_settings()
        mutate(data)
        self._write_settings(data)
        return self._validate()

    @staticmethod
    def _msgs(data, *, level=None, contains=None):
        out = []
        for ev in (data or {}).get("events", []):
            if level is not None and ev.get("level") != level:
                continue
            if contains is not None and contains not in ev.get("msg", ""):
                continue
            out.append(ev.get("msg", ""))
        return out

    def _assertJson(self, proc, data):
        self.assertIsNotNone(
            data,
            msg=f"validate.sh did not emit JSON\nrc={proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )


class ValidatorPreservation(_ValidatorFixture):
    # ---- baseline ----------------------------------------------------------
    def test_fresh_core_quickvalidate_exits_zero(self):
        """A real fresh core install must pass --quick --json with zero errors, a
        complete result, and WITHOUT the validator mutating the owner's settings."""
        before = self._settings_path().read_bytes()
        proc, data = self._validate()
        self._assertJson(proc, data)
        self.assertEqual(
            proc.returncode, 0,
            msg=f"fresh core should exit 0\nerrors={data.get('errors')}\n"
            + "\n".join(self._msgs(data, level="fail")),
        )
        self.assertEqual(data["errors"], 0, msg="\n".join(self._msgs(data, level="fail")))
        self.assertTrue(data["complete"], msg="fresh core result must be complete")
        self.assertEqual(
            self._settings_path().read_bytes(), before,
            msg="validate.sh is observer-only — it must not modify settings.json",
        )

    # ---- effort-key presence (mismatch 1) ----------------------------------
    def test_absent_effort_key_is_not_drift(self):
        """Deleting CLAUDE_CODE_EFFORT_LEVEL (a preserved native-default choice) must
        NOT be reported as a missing env key, and must not fail validation."""
        proc, data = self._run_mutated(lambda d: d["env"].pop("CLAUDE_CODE_EFFORT_LEVEL"))
        self._assertJson(proc, data)
        self.assertEqual(
            self._msgs(data, level="fail", contains="env key missing: CLAUDE_CODE_EFFORT_LEVEL"),
            [],
            msg="absent effort key must not be flagged as drift",
        )
        self.assertEqual(proc.returncode, 0, msg="\n".join(self._msgs(data, level="fail")))
        self.assertEqual(data["errors"], 0, msg="\n".join(self._msgs(data, level="fail")))

    def test_empty_effort_value_is_valid(self):
        """An explicit empty-string effort value is a supported owner choice."""
        def mut(d):
            d["env"]["CLAUDE_CODE_EFFORT_LEVEL"] = ""
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(proc.returncode, 0, msg="\n".join(self._msgs(data, level="fail")))
        self.assertEqual(data["errors"], 0, msg="\n".join(self._msgs(data, level="fail")))

    def test_other_missing_env_key_still_fails(self):
        """Skipping the effort key must NOT weaken the check for every other required
        env key — a genuinely missing key is still an error."""
        proc, data = self._run_mutated(lambda d: d["env"].pop("BASH_DEFAULT_TIMEOUT_MS"))
        self._assertJson(proc, data)
        self.assertEqual(proc.returncode, 1, msg="a real missing env key must fail")
        self.assertTrue(
            self._msgs(data, level="fail", contains="env key missing: BASH_DEFAULT_TIMEOUT_MS"),
            msg="a missing non-effort env key must be reported",
        )

    # ---- foreign hook preservation (mismatch 2, positive) ------------------
    def test_foreign_hook_in_canonical_group_is_preserved(self):
        """A foreign hook added INSIDE the canonical PreToolUse group is a healthy
        owner customization — the framework-owned entry is intact, so no drift."""
        def mut(d):
            d["hooks"]["PreToolUse"][0]["hooks"].append(
                {"type": "command", "command": "~/.claude/hooks/owner-audit.sh", "timeout": 9}
            )
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(
            self._msgs(data, level="fail", contains="hook"), [],
            msg="a foreign hook in the canonical group must not be flagged as drift",
        )
        self.assertEqual(proc.returncode, 0, msg="\n".join(self._msgs(data, level="fail")))

    def test_foreign_hook_in_separate_group_is_preserved(self):
        """A foreign hook added as a SEPARATE PreToolUse group is likewise healthy."""
        def mut(d):
            d["hooks"]["PreToolUse"].append(
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "/opt/owner/foreign.sh", "timeout": 9}]}
            )
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(
            self._msgs(data, level="fail", contains="hook"), [],
            msg="a separate foreign group must not be flagged as drift",
        )
        self.assertEqual(proc.returncode, 0, msg="\n".join(self._msgs(data, level="fail")))

    # ---- framework-owned corruption (mismatch 2, negative) -----------------
    def test_duplicated_framework_hook_entry_fails(self):
        """A DUPLICATED framework entry (mixed with a foreign group) is drift and
        must still fail even though foreign entries are ignored."""
        def mut(d):
            d["hooks"]["PreToolUse"][0]["hooks"].append(
                {"type": "command", "command": "~/.claude/hooks/file-protection.sh", "timeout": 3}
            )
            d["hooks"]["PreToolUse"].append(
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "/opt/foreign.sh", "timeout": 9}]}
            )
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(proc.returncode, 1, msg="a duplicated framework hook entry must fail")
        self.assertTrue(
            self._msgs(data, level="fail", contains="framework-owned hook entries for event 'PreToolUse'"),
            msg="a duplicated own entry must be reported as drift",
        )

    def test_modified_framework_hook_metadata_fails(self):
        """MODIFYING a framework entry's metadata (timeout) is drift."""
        def mut(d):
            d["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 99
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(proc.returncode, 1, msg="a modified framework hook entry must fail")
        self.assertTrue(
            self._msgs(data, level="fail", contains="framework-owned hook entries for event 'PreToolUse'"),
            msg="a modified own entry must be reported as drift",
        )

    def test_basename_lookalike_is_not_adopted_for_missing_own(self):
        """If the real framework command is replaced by a foreign basename look-alike
        (different path), the owned entry is MISSING — the look-alike must not be
        adopted to satisfy it, so validation fails."""
        def mut(d):
            d["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "/elsewhere/file-protection.sh"
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(proc.returncode, 1, msg="a missing own entry must fail")
        self.assertTrue(
            self._msgs(data, level="fail", contains="framework-owned hook entries for event 'PreToolUse'"),
            msg="a basename look-alike must not be adopted as the framework binding",
        )

    # ---- corrupt-settings diagnostic (mismatch 3) --------------------------
    def test_corrupt_settings_message_reflects_preservation_not_reseed(self):
        """A non-object (corrupt) settings.json must fail with a diagnostic that
        matches install.sh's actual behavior: preserve + forensic copy + manual
        review — NOT a promise to reseed from the template."""
        # Write a valid-JSON-but-wrong-shape file (array) directly; _write_settings
        # would json-encode a dict, so bypass it for the non-object case.
        self._settings_path().write_text("[]")
        proc, data = self._validate()
        self._assertJson(proc, data)
        self.assertEqual(proc.returncode, 1, msg="a corrupt settings.json must fail")
        corrupt = self._msgs(data, level="fail", contains="not a valid JSON object")
        self.assertTrue(corrupt, msg="corrupt settings must be reported")
        msg = corrupt[0]
        self.assertIn("forensic copy", msg, msg="diagnostic must mention the forensic copy")
        self.assertIn("preserves", msg, msg="diagnostic must say the file is preserved")
        self.assertNotIn("reseed", msg, msg="installer does NOT reseed a corrupt settings.json")

    # ---- owned-entry shape consistency with SessionStart (mismatch 4) ------
    def test_owned_entry_missing_type_is_drift(self):
        """Dropping the ``type`` field from a canonical framework-owned entry is drift.
        The SessionStart healthcheck compares the FULL entry object, so the validator
        must too — it must NOT default a missing ``type`` back to ``command`` and pass,
        which would split the two consumers (healthcheck=drift, validator=healthy)."""
        proc, data = self._run_mutated(
            lambda d: d["hooks"]["PreToolUse"][0]["hooks"][0].pop("type")
        )
        self._assertJson(proc, data)
        self.assertEqual(
            proc.returncode, 1,
            msg="an owned entry with its type dropped must be reported as drift",
        )
        self.assertTrue(
            self._msgs(data, level="fail",
                       contains="framework-owned hook entries for event 'PreToolUse'"),
            msg="a dropped owned `type` must be drift, consistent with SessionStart's full-entry compare",
        )

    # ---- reverse (dropped-event) guard: exact-path ownership (IR-FINAL-001) -
    def test_foreign_dropped_event_absolute_lookalike_is_preserved(self):
        """A dropped event (Stop) bound to a FOREIGN command that merely shares a shipped
        hook's basename (/owner/custom/session-end.sh) is an owner customization the
        installer preserves verbatim — the reverse guard must key ownership on the EXACT
        path, so this must NOT be mis-flagged as a stale framework double-bind."""
        def mut(d):
            d["hooks"]["Stop"] = [
                {"matcher": "", "hooks": [
                    {"type": "command", "command": "/owner/custom/session-end.sh", "timeout": 5}]}
            ]
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(
            self._msgs(data, level="fail", contains="stale hook event 'Stop'"), [],
            msg="a foreign same-basename command must not be flagged as stale framework drift",
        )
        self.assertEqual(proc.returncode, 0, msg="\n".join(self._msgs(data, level="fail")))

    def test_foreign_dropped_event_tilde_nonhooks_is_preserved(self):
        """A dropped-event command under the owner's own ~ tree but NOT in ~/.claude/hooks
        (~/custom/session-end.sh) is equally foreign — the exact-path check must not adopt
        it as the framework binding."""
        def mut(d):
            d["hooks"]["Stop"] = [
                {"matcher": "", "hooks": [
                    {"type": "command", "command": "~/custom/session-end.sh", "timeout": 5}]}
            ]
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(
            self._msgs(data, level="fail", contains="stale hook event 'Stop'"), [],
            msg="a foreign ~-but-not-hooks command must not be flagged as stale framework drift",
        )
        self.assertEqual(proc.returncode, 0, msg="\n".join(self._msgs(data, level="fail")))

    def test_stale_framework_dropped_event_tilde_still_fails(self):
        """Negative control: a dropped event still bound to the REAL framework hook at
        ~/.claude/hooks/session-end.sh is a genuine stale double-bind and MUST still fail —
        the exact-path fix must not lose real stale detection."""
        def mut(d):
            d["hooks"]["Stop"] = [
                {"matcher": "", "hooks": [
                    {"type": "command", "command": "~/.claude/hooks/session-end.sh", "timeout": 5}]}
            ]
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(proc.returncode, 1, msg="a stale framework binding must fail")
        self.assertTrue(
            self._msgs(data, level="fail", contains="stale hook event 'Stop'"),
            msg="the stale framework Stop binding must be reported",
        )

    def test_stale_framework_dropped_event_home_expanded_still_fails(self):
        """Negative control: the $HOME-expanded twin of the framework path is equally
        owned and must also fail — ownership is recognised in both spellings."""
        home_cmd = str(self.home / ".claude" / "hooks" / "session-end.sh")

        def mut(d):
            d["hooks"]["Stop"] = [
                {"matcher": "", "hooks": [
                    {"type": "command", "command": home_cmd, "timeout": 5}]}
            ]
        proc, data = self._run_mutated(mut)
        self._assertJson(proc, data)
        self.assertEqual(proc.returncode, 1, msg="the HOME-expanded stale framework binding must fail")
        self.assertTrue(
            self._msgs(data, level="fail", contains="stale hook event 'Stop'"),
            msg="the $HOME-expanded framework Stop binding must be reported as stale",
        )


class ValidatorSelectionCompleteness(_ValidatorFixture):
    """AIRR-SELECT-01: on an EXISTING installed scope every optional component must resolve
    to an explicit enabled|disabled in ~/.claude/.framework-version. An absent field, an
    absent marker (core agents still present), a duplicate or an invalid value leaves the
    selection undecidable, so the --quick --json summary must be complete=false (watchdog ->
    UNKNOWN) — error-count 0 alone can never launder a partial scope into a green. A truly
    uninstalled HOME has no selection to resolve and stays complete=true."""

    def _marker_path(self):
        return self.home / ".claude" / ".framework-version"

    def _set_marker(self, new_text):
        """Overwrite (or, with new_text=None, remove) the install marker for one test and
        guarantee the pristine marker is restored afterwards (the fixture is class-scoped)."""
        p = self._marker_path()
        original = p.read_bytes() if p.exists() else None

        def restore():
            if original is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(original)

        self.addCleanup(restore)
        if new_text is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(new_text)

    def test_all_selection_fields_absent_is_incomplete(self):
        # Marker present but carrying NO analytics/notifications/watchdog lines.
        self._set_marker("version=3.2.0\nsha=x\nahead=0\ninstalled_at=t\n")
        proc, data = self._validate()
        self._assertJson(proc, data)
        self.assertFalse(
            data["complete"],
            msg="absent selection fields on an installed scope must be incomplete, not green",
        )

    def test_one_selection_field_absent_is_incomplete(self):
        # analytics + watchdog recorded, notifications missing → still undecidable.
        self._set_marker(
            "version=3.2.0\nsha=x\nahead=0\ninstalled_at=t\n"
            "analytics=disabled\nwatchdog=disabled\n"
        )
        proc, data = self._validate()
        self._assertJson(proc, data)
        self.assertFalse(
            data["complete"],
            msg="one absent selection field must mark the run incomplete",
        )

    def test_marker_absent_but_core_present_is_incomplete(self):
        # No marker at all, but ~/.claude/agents is still deployed → an installed scope whose
        # selection is wholly unknown; a honest run cannot certify it complete.
        self._set_marker(None)
        self.assertTrue((self.home / ".claude" / "agents").is_dir(), "fixture precondition")
        proc, data = self._validate()
        self._assertJson(proc, data)
        self.assertFalse(
            data["complete"],
            msg="an absent marker with core agents present must be incomplete",
        )

    def test_uninstalled_home_source_only_stays_complete(self):
        # Positive discriminator: a HOME with no marker AND no deployed agents is a source-only
        # (CI/clone) validation with no selection to resolve — the gate must NOT fire, so the
        # run stays complete even though quick mode flags "not installed".
        with tempfile.TemporaryDirectory(prefix="vp-empty-") as empty:
            env = self._env(watchdog_run=True)
            env["HOME"] = empty
            proc = subprocess.run(
                ["bash", str(VALIDATE), "--quick", "--json"],
                cwd=str(REPO), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
            )
            data = json.loads(proc.stdout)
            self.assertTrue(
                data["complete"],
                msg="an uninstalled source-only HOME must stay complete (no selection to resolve)",
            )


class ValidatorWatchdogSelection(_ValidatorFixture):
    """IR-FINAL finding 3: the watchdog runtime expectations (launchd daemon loaded +
    a snapshot newer than 48h) were checked UNCONDITIONALLY. On a core default-off
    install the watchdog is deliberately not selected, so those probes/warnings
    mis-report a healthy minimal install as degraded. They must be gated on the
    watchdog selection: disabled -> skip silently (no probe, no warning); selected ->
    retained with its positive controls."""

    def _rewrite_marker(self, **components):
        """Rewrite ~/.claude/.framework-version keeping every non-component line and
        setting analytics/notifications/watchdog to the given values; restored after."""
        p = self.home / ".claude" / ".framework-version"
        original = p.read_bytes() if p.exists() else None

        def restore():
            if original is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(original)

        self.addCleanup(restore)
        keys = set(components)
        lines = []
        if original is not None:
            for ln in original.decode().splitlines():
                if ln.split("=", 1)[0] not in keys:
                    lines.append(ln)
        lines.extend(f"{k}={v}" for k, v in components.items())
        p.write_text("\n".join(lines) + "\n")

    def _new_watchdog_probes(self, before):
        """launchctl stub calls referencing the framework-watchdog made since ``before``."""
        return [c for c in self._launchctl_calls()[len(before):] if "framework-watchdog" in c]

    def test_disabled_watchdog_skips_probe_and_snapshot_advisory(self):
        """watchdog=disabled: no launchctl daemon probe, no daemon event, no snapshot
        advisory — and the run still completes with zero errors."""
        self._rewrite_marker(analytics="disabled", notifications="disabled", watchdog="disabled")
        before = self._launchctl_calls()
        proc, data = self._validate()
        self._assertJson(proc, data)
        self.assertEqual(
            self._new_watchdog_probes(before), [],
            msg="a disabled watchdog must not probe launchctl for the daemon",
        )
        self.assertEqual(
            self._msgs(data, contains="framework-watchdog daemon"), [],
            msg="a disabled watchdog must emit no daemon loaded/not-loaded event",
        )
        self.assertEqual(
            self._msgs(data, contains="snapshot"), [],
            msg="a disabled watchdog must emit no snapshot advisory",
        )
        self.assertEqual(data["errors"], 0, msg="\n".join(self._msgs(data, level="fail")))
        self.assertTrue(data["complete"], msg="an all-recorded selection must stay complete")

    def test_selected_watchdog_retains_probe_and_snapshot_advisory(self):
        """Positive control — watchdog=enabled: the daemon probe and snapshot advisory
        are RETAINED (the gate must not over-skip them)."""
        self._rewrite_marker(analytics="disabled", notifications="disabled", watchdog="enabled")
        before = self._launchctl_calls()
        proc, data = self._validate()
        self._assertJson(proc, data)
        self.assertTrue(
            self._msgs(data, contains="snapshot"),
            msg="a selected watchdog must retain the snapshot advisory check",
        )
        if platform.system() == "Darwin":
            self.assertTrue(
                self._new_watchdog_probes(before),
                msg="a selected watchdog must probe launchctl for the daemon on macOS",
            )
            self.assertTrue(
                self._msgs(data, contains="framework-watchdog daemon"),
                msg="a selected watchdog must emit a daemon loaded/not-loaded event on macOS",
            )


if __name__ == "__main__":
    unittest.main()
