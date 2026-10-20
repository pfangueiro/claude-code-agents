#!/usr/bin/env python3
"""Focused tests for install.sh optional-component opt-in flags (automation slice 2)
and the SessionStart hook's selected-component alignment + safe marker-path read.

Everything runs the ACTUAL source (install.sh and session-start-healthcheck.sh) in a
DISPOSABLE HOME under the system temp dir, with a stub `launchctl` (and, for the one
macOS registration case, stub `uname`/`dscl`) on PATH so no real launchd job, service,
notification or collector is ever touched. No real HOME, no network.

Scope covered (slice-2 checks):
  * fresh-default     — no flags => core only; no analytics/notify/watchdog effects; no launchctl
  * positive-opt-ins  — each flag / all three install exactly their component; analytics never runs collector
  * parser            — any order; reject unknown / duplicate flag / more-than-one-mode
  * dry-run           — truthful selected paths, ZERO writes (even with no ~/.claude)
  * legacy-preserve   — plain update preserves existing optional extras + foreign same-event hooks,
                        does not recreate missing counterparts, calls no launchctl
  * no implicit migration — a .framework-autonomy marker does NOT trigger teardown on update
  * selection marker  — enabled|disabled|unknown fields recorded in ~/.claude/.framework-version
  * SessionStart hook — selected-component alignment (optional-off is not drift), embedded-space
                        marker path resolves, and an unresolved marker emits exactly one unknown.

The separate worker owns the watchdog daemon script and tests/codex/test_background_health.py;
this file does not touch those.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install.sh"
HOOK = REPO / "global-config" / "hooks" / "session-start-healthcheck.sh"
HEALTH_REL = ".claude/analytics/framework-health.jsonl"


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="slice2-")
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True)
        self.stubbin = self.root / "bin"
        self.stubbin.mkdir()
        self.launchctl_log = self.root / "launchctl.calls"
        # launchctl is ALWAYS stubbed: it must never invoke the real one.
        _write_exec(
            self.stubbin / "launchctl",
            '#!/bin/bash\nprintf "%s\\n" "$*" >> "{log}"\n'
            "exit 0\n".format(log=self.launchctl_log),
        )

    def tearDown(self):
        self._tmp.cleanup()

    # ---- helpers -----------------------------------------------------------
    def _env(self, *, darwin=False, fake_realhome=False, watchdog_run=False):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["PATH"] = f"{self.stubbin}:{env.get('PATH', '')}"
        # Deterministic: never let the installer append an alias to the tester's rc.
        env.pop("CLAUDE_UPGRADE_ASSUME_YES", None)
        if watchdog_run:
            # Skip the post-register kickstart + /tmp statusline-cache rm; registration
            # (launchctl bootstrap + plist) still runs so we can assert it.
            env["CLAUDE_WATCHDOG_RUN"] = "1"
        if darwin:
            _write_exec(
                self.stubbin / "uname",
                '#!/bin/bash\n[ "$1" = "-s" ] && { echo Darwin; exit 0; }\n'
                'exec /usr/bin/uname "$@"\n',
            )
        if fake_realhome:
            # Make install_watchdog's machine-global real-home guard pass against the
            # disposable HOME (so registration proceeds under the stub launchctl).
            _write_exec(
                self.stubbin / "dscl",
                f'#!/bin/bash\necho "NFSHomeDirectory: {self.home}"\n',
            )
        return env

    def _run(self, args, *, env=None, check_rc=None):
        env = env or self._env()
        proc = subprocess.run(
            ["bash", str(INSTALL), *args],
            cwd=str(REPO),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
        if check_rc is not None:
            self.assertEqual(
                proc.returncode, check_rc,
                msg=f"args={args}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )
        return proc

    def _run_hook(self, env=None):
        env = env or self._env()
        return subprocess.run(
            ["bash", str(HOOK)],
            cwd=str(REPO),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )

    def _launchctl_calls(self):
        if not self.launchctl_log.exists():
            return []
        return [ln for ln in self.launchctl_log.read_text().splitlines() if ln.strip()]

    def _marker(self):
        f = self.home / ".claude" / ".framework-version"
        out = {}
        if f.exists():
            for line in f.read_text().splitlines():
                k, sep, v = line.partition("=")
                if sep:
                    out[k] = v
        return out

    def _settings_events(self):
        f = self.home / ".claude" / "settings.json"
        data = json.loads(f.read_text())
        return set(data.get("hooks", {}).keys())

    def _health_events(self):
        f = self.home / HEALTH_REL
        events = []
        if f.exists():
            for line in f.read_text().splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def _hooks_present(self):
        d = self.home / ".claude" / "hooks"
        return {p.name for p in d.iterdir()} if d.exists() else set()

    @staticmethod
    def _tree_fingerprint(root: Path):
        """Recursive {relpath: sha256|'DIR'|'LINK'} snapshot for byte-equality checks."""
        fp = {}
        if not root.exists():
            return fp
        for p in sorted(root.rglob("*")):
            rel = str(p.relative_to(root))
            if p.is_symlink():
                fp[rel] = "LINK:" + os.readlink(p)
            elif p.is_dir():
                fp[rel] = "DIR"
            else:
                fp[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        return fp

    # ---- settings.json read/write -----------------------------------------
    def _settings_path(self):
        return self.home / ".claude" / "settings.json"

    def _read_settings(self):
        return json.loads(self._settings_path().read_text())

    def _write_settings(self, data):
        self._settings_path().write_text(json.dumps(data, indent=2))

    @staticmethod
    def _event_commands(groups):
        """All hook commands across every group in one settings hook-event array."""
        return [h.get("command") for g in groups for h in g.get("hooks", [])]

    # ---- function-level harness (source install.sh helpers in isolation) ---
    def _funcs_copy(self):
        """A copy of install.sh with the trailing `main` invocation removed, so sourcing it
        DEFINES the helper functions without running the installer. SCRIPT_DIR is re-pointed
        by the driver to the real repo so template lookups resolve."""
        text = INSTALL.read_text()
        marker = "\n# Run main\n"
        idx = text.rfind(marker)
        stripped = text[:idx] + "\n" if idx != -1 else text
        p = self.root / "install_funcs.sh"
        p.write_text(stripped)
        return p

    def _run_driver(self, body, env=None):
        """Run a bash driver that sources the (main-stripped) installer helpers and then
        executes `body`. `set --` clears positional args before sourcing so the installer's
        top-level arg parser sees nothing; SCRIPT_DIR is pointed at the real repo."""
        env = env or self._env()
        funcs = self._funcs_copy()
        driver = self.root / "driver.sh"
        driver.write_text(
            "#!/bin/bash\nset --\nsource '{funcs}'\nset +e\nSCRIPT_DIR='{repo}'\n{body}\n".format(
                funcs=funcs, repo=REPO, body=body
            )
        )
        return subprocess.run(
            ["bash", str(driver)], cwd=str(REPO), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=60,
        )

    def _jqless_env(self):
        """An env whose PATH exposes every tool EXCEPT jq, via a symlink farm mirroring the
        real PATH minus any `jq`. Lets the ACTUAL installer run with jq genuinely absent."""
        farm = self.root / "jqless-bin"
        farm.mkdir(exist_ok=True)
        seen = set()
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not d or not os.path.isdir(d):
                continue
            try:
                entries = os.listdir(d)
            except OSError:
                continue
            for name in entries:
                if name == "jq" or name in seen:
                    continue
                srcp = os.path.join(d, name)
                if not os.access(srcp, os.X_OK):
                    continue
                try:
                    (farm / name).symlink_to(srcp)
                    seen.add(name)
                except OSError:
                    pass
        env = self._env()
        env["PATH"] = f"{self.stubbin}:{farm}"
        return env


class FreshDefault(_Base):
    def test_no_flags_is_core_only_no_optional_effects(self):
        self._run([], check_rc=0)
        hooks = self._hooks_present()
        # Core hooks present; optional-component hooks absent.
        self.assertIn("session-start-healthcheck.sh", hooks)
        self.assertIn("file-protection.sh", hooks)
        for optional in ("agent-tracker.sh", "session-end.sh", "notify.sh"):
            self.assertNotIn(optional, hooks, f"{optional} must not install by default")
        # No analytics assets, no claude-obs alias, no watchdog daemon.
        self.assertFalse((self.home / ".claude" / "analytics" / "collector.py").exists())
        self.assertFalse((self.home / ".claude" / "daemon").exists())
        # Settings wires no optional events.
        events = self._settings_events()
        for ev in ("Notification", "SubagentStart", "SubagentStop", "SessionEnd"):
            self.assertNotIn(ev, events)
        self.assertIn("SessionStart", events)
        self.assertIn("PreToolUse", events)
        # Marker records all three disabled (deliberate default-off).
        self.assertEqual(self._marker().get("analytics"), "disabled")
        self.assertEqual(self._marker().get("watchdog"), "disabled")
        self.assertEqual(self._marker().get("notifications"), "disabled")
        # launchctl was never invoked.
        self.assertEqual(self._launchctl_calls(), [])


class PositiveOptIns(_Base):
    def test_analytics_only_installs_assets_hooks_events_no_collector(self):
        # Give the tester a shell rc so the alias has somewhere to land.
        (self.home / ".zshrc").write_text("")
        proc = self._run(["--with-analytics"], check_rc=0)
        hooks = self._hooks_present()
        self.assertIn("agent-tracker.sh", hooks)
        self.assertIn("session-end.sh", hooks)
        self.assertNotIn("notify.sh", hooks)  # notifications not selected
        self.assertTrue((self.home / ".claude" / "analytics" / "collector.py").exists())
        self.assertIn("SubagentStart", self._settings_events())
        self.assertIn("SessionEnd", self._settings_events())
        self.assertNotIn("Notification", self._settings_events())
        self.assertIn("claude-obs", (self.home / ".zshrc").read_text())
        self.assertEqual(self._marker().get("analytics"), "enabled")
        self.assertEqual(self._marker().get("notifications"), "disabled")
        # Selection NEVER runs the collector: no claude-obs.db and no python collector call.
        self.assertFalse((self.home / ".claude" / "analytics" / "claude-obs.db").exists())
        self.assertNotIn("collector.py;", proc.stdout.replace("\n", " ").lower()
                         .replace("installed analytics collector.py", ""))
        # launchctl untouched (watchdog not selected).
        self.assertEqual(self._launchctl_calls(), [])

    def test_notifications_only_installs_notify_hook_and_event(self):
        self._run(["--with-notifications"], check_rc=0)
        self.assertIn("notify.sh", self._hooks_present())
        self.assertNotIn("agent-tracker.sh", self._hooks_present())
        self.assertIn("Notification", self._settings_events())
        self.assertNotIn("SubagentStart", self._settings_events())
        self.assertEqual(self._marker().get("notifications"), "enabled")
        self.assertEqual(self._marker().get("analytics"), "disabled")
        self.assertEqual(self._launchctl_calls(), [])

    def test_all_three_on_macos_registers_watchdog_via_launchctl(self):
        env = self._env(darwin=True, fake_realhome=True, watchdog_run=True)
        self._run(["--with-analytics", "--with-notifications", "--with-watchdog"],
                  env=env, check_rc=0)
        hooks = self._hooks_present()
        for h in ("agent-tracker.sh", "session-end.sh", "notify.sh"):
            self.assertIn(h, hooks)
        self.assertTrue((self.home / ".claude" / "daemon" / "claude-framework-watchdog.sh").exists())
        self.assertTrue((self.home / "Library" / "LaunchAgents"
                         / "com.claude-code-agents.framework-watchdog.plist").exists())
        self.assertEqual(self._marker().get("watchdog"), "enabled")
        calls = " ".join(self._launchctl_calls())
        self.assertIn("bootstrap", calls, msg=f"launchctl calls: {calls!r}")

    def test_watchdog_flag_on_non_macos_skips_launchctl(self):
        # Force non-Darwin: install_watchdog must early-skip without any launchctl call.
        _write_exec(self.stubbin / "uname",
                    '#!/bin/bash\n[ "$1" = "-s" ] && { echo Linux; exit 0; }\n'
                    'exec /usr/bin/uname "$@"\n')
        env = self._env()
        self._run(["--with-watchdog"], env=env, check_rc=0)
        self.assertEqual(self._launchctl_calls(), [])
        # Still recorded as selected in the marker.
        self.assertEqual(self._marker().get("watchdog"), "enabled")


class Parser(_Base):
    def test_unknown_option_rejected(self):
        p = self._run(["--bogus"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("unknown option", p.stderr.lower())

    def test_duplicate_flag_rejected(self):
        p = self._run(["--with-analytics", "--with-analytics"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("more than once", p.stderr.lower())

    def test_more_than_one_mode_rejected(self):
        p = self._run(["--update", "--upgrade"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("more than one mode", p.stderr.lower())

    def test_flags_accepted_in_any_order_with_mode(self):
        # Flag before a mode and after a mode both parse (dry-run writes nothing).
        before = self._run(["--with-analytics", "--dry-run"], check_rc=0)
        after = self._run(["--dry-run", "--with-analytics"], check_rc=0)
        for p in (before, after):
            self.assertIn("analytics=on", p.stdout)


class DryRun(_Base):
    def _assert_no_writes(self, args):
        before = self._tree_fingerprint(self.home)
        p = self._run(args, check_rc=0)
        after = self._tree_fingerprint(self.home)
        self.assertEqual(before, after, msg=f"dry-run wrote to HOME for args={args}")
        return p

    def test_default_dry_run_writes_nothing_and_omits_optional(self):
        # Empty HOME (no ~/.claude at all): dry-run must create nothing.
        p = self._assert_no_writes(["--dry-run"])
        self.assertFalse((self.home / ".claude").exists())
        self.assertIn("analytics=off", p.stdout)
        self.assertNotIn("/analytics/collector.py", p.stdout)
        self.assertNotIn("framework-watchdog.sh", p.stdout)

    def test_selected_dry_run_writes_nothing_but_lists_selected(self):
        p = self._assert_no_writes(["--dry-run", "--with-analytics", "--with-watchdog"])
        self.assertIn("analytics=on", p.stdout)
        self.assertIn("watchdog=on", p.stdout)
        self.assertIn("/analytics/collector.py", p.stdout)
        self.assertIn("framework-watchdog.sh", p.stdout)
        # Still zero launchctl calls from a dry run.
        self.assertEqual(self._launchctl_calls(), [])


class LegacyPreservation(_Base):
    def _install_analytics_notifications(self):
        (self.home / ".zshrc").write_text("")
        self._run(["--with-analytics", "--with-notifications"], check_rc=0)

    def test_plain_update_preserves_optional_extras_and_foreign_hook(self):
        self._install_analytics_notifications()
        # Inject a FOREIGN Notification binding (the owner's own, not framework's notify.sh).
        settings = self.home / ".claude" / "settings.json"
        data = json.loads(settings.read_text())
        data["hooks"]["Notification"] = [
            {"hooks": [{"type": "command", "command": "~/my-own-notify.sh", "timeout": 4}]}
        ]
        settings.write_text(json.dumps(data, indent=2))

        at_before = hashlib.sha256(
            (self.home / ".claude" / "hooks" / "agent-tracker.sh").read_bytes()
        ).hexdigest()

        # Plain update, NO flags.
        self.launchctl_log.unlink(missing_ok=True)
        self._run(["--update"], check_rc=0)

        hooks = self._hooks_present()
        self.assertIn("agent-tracker.sh", hooks)
        self.assertIn("session-end.sh", hooks)
        self.assertTrue((self.home / ".claude" / "analytics" / "collector.py").exists())
        # Foreign Notification entry untouched (notifications still enabled here, but the
        # framework never replaces a FOREIGN binding — only its own; it is preserved verbatim).
        data2 = json.loads(settings.read_text())
        cmd = data2["hooks"]["Notification"][0]["hooks"][0]["command"]
        self.assertEqual(cmd, "~/my-own-notify.sh")
        # agent-tracker unchanged byte-for-byte.
        at_after = hashlib.sha256(
            (self.home / ".claude" / "hooks" / "agent-tracker.sh").read_bytes()
        ).hexdigest()
        self.assertEqual(at_before, at_after)
        # Marker selection preserved.
        self.assertEqual(self._marker().get("analytics"), "enabled")
        # No launchctl during a plain update.
        self.assertEqual(self._launchctl_calls(), [])

    def test_update_does_not_recreate_a_deleted_optional_counterpart(self):
        self._install_analytics_notifications()
        # Owner removed an analytics hook; a plain update must NOT recreate it.
        (self.home / ".claude" / "hooks" / "session-end.sh").unlink()
        self._run(["--update"], check_rc=0)
        self.assertFalse((self.home / ".claude" / "hooks" / "session-end.sh").exists())

    def test_autonomy_marker_does_not_trigger_migration_on_update(self):
        self._run([], check_rc=0)  # fresh install
        # Build a fake legacy project tree carrying a framework-owned agent, UNTRACKED.
        legacy = self.root / "legacy"
        proj = legacy / "proj1" / ".claude" / "agents"
        proj.mkdir(parents=True)
        src_agent = next((REPO / ".claude" / "agents").glob("*.md"))
        (proj / src_agent.name).write_text(src_agent.read_text())
        (self.home / ".claude" / ".framework-autonomy").write_text(
            f"LEGACY_PROJECTS_DIR={legacy}\n"
        )
        self.launchctl_log.unlink(missing_ok=True)
        self._run(["--update"], check_rc=0)
        # Legacy copy must still be there (no implicit teardown on update).
        self.assertTrue((proj / src_agent.name).exists())
        snaps = self.home / ".claude" / "snapshots"
        teardown_snaps = list(snaps.glob("preteardown-*")) if snaps.exists() else []
        self.assertEqual(teardown_snaps, [], "update must not run a legacy teardown")


class SelectionMarker(_Base):
    def test_fresh_flag_then_update_carries_selection_forward(self):
        self._run(["--with-analytics"], check_rc=0)
        self.assertEqual(self._marker().get("analytics"), "enabled")
        self._run(["--update"], check_rc=0)  # no flag
        self.assertEqual(self._marker().get("analytics"), "enabled")  # carried forward

    def test_legacy_marker_without_fields_becomes_unknown_not_enabled(self):
        # Simulate a pre-slice-2 marker (only version/sha) with analytics artifacts present.
        claude = self.home / ".claude"
        (claude / "analytics").mkdir(parents=True)
        (claude / "analytics" / "collector.py").write_text("# legacy\n")
        claude.joinpath(".framework-version").write_text(
            "version=3.2.0\nsha=deadbee\nahead=0\ninstalled_at=2026-01-01T00:00:00Z\n"
        )
        # Plain update, no flag: artifact presence must NOT be read as consent → unknown.
        self._run(["--update"], check_rc=0)
        self.assertEqual(self._marker().get("analytics"), "unknown")
        # The legacy collector.py is preserved (byte-for-byte), not overwritten.
        self.assertEqual((claude / "analytics" / "collector.py").read_text(), "# legacy\n")


class SessionStartHookSelection(_Base):
    """The SessionStart hook must align its checks with the recorded selection and read
    the framework-path marker safely (embedded spaces; unresolved → one honest unknown)."""

    def test_fresh_default_install_is_healthy_no_optional_false_drift(self):
        self._run([], check_rc=0)
        self._run_hook()
        events = self._health_events()
        results = [e for e in events if e.get("event") == "healthcheck_result"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "healthy", msg=json.dumps(results[0]))
        self.assertEqual(results[0]["drift"], 0)
        # No drift was logged for the absent optional hooks/events.
        drift = [e for e in events if e.get("event") == "drift_detected"]
        self.assertEqual(drift, [], msg=f"unexpected drift: {drift}")

    def test_enabled_component_missing_hook_is_flagged_as_drift(self):
        # With analytics ENABLED, a removed analytics hook IS drift (enabled ⇒ checked).
        self._run(["--with-analytics"], check_rc=0)
        (self.home / ".claude" / "hooks" / "agent-tracker.sh").unlink()
        self._run_hook()
        events = self._health_events()
        drift_checks = [e.get("check") for e in events if e.get("event") == "drift_detected"]
        self.assertIn("hook_missing", drift_checks)
        result = [e for e in events if e.get("event") == "healthcheck_result"][-1]
        self.assertEqual(result["status"], "drift")

    def test_disabled_component_missing_hook_is_not_drift(self):
        # Fresh default (analytics disabled): agent-tracker.sh is absent by design → not drift.
        self._run([], check_rc=0)
        self._run_hook()
        events = self._health_events()
        for e in events:
            if e.get("event") == "drift_detected":
                self.assertNotIn(
                    e.get("check"), ("hook_missing", "hook_wiring"),
                    msg=f"optional-off wrongly reported drift: {e}",
                )

    def test_marker_path_with_embedded_spaces_resolves(self):
        # A valid framework checkout path containing a space must NOT be corrupted.
        spaced = self.root / "My Framework Repo"
        (spaced / ".claude" / "agents").mkdir(parents=True)
        (spaced / ".claude" / "agents" / "dummy.md").write_text("# dummy\n")
        claude = self.home / ".claude"
        (claude / "analytics").mkdir(parents=True)
        claude.joinpath(".framework-path").write_text(str(spaced) + "\n")
        self._run_hook()
        results = [e for e in self._health_events() if e.get("event") == "healthcheck_result"]
        self.assertEqual(len(results), 1)
        # Resolved: the terminal result is NOT the unresolved-marker sentinel.
        self.assertNotEqual(results[0].get("reason"), "framework_path_unresolved")

    def test_missing_marker_emits_exactly_one_unknown(self):
        (self.home / ".claude" / "analytics").mkdir(parents=True)
        # No .framework-path at all.
        self._run_hook()
        results = [e for e in self._health_events() if e.get("event") == "healthcheck_result"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "unknown")
        self.assertEqual(results[0]["reason"], "framework_path_unresolved")
        self.assertEqual(results[0]["checks"], 0)
        self.assertEqual(results[0]["scope"], "sessionstart_drift_checks")

    def test_empty_marker_emits_one_unknown(self):
        claude = self.home / ".claude"
        (claude / "analytics").mkdir(parents=True)
        claude.joinpath(".framework-path").write_text("")
        self._run_hook()
        results = [e for e in self._health_events() if e.get("event") == "healthcheck_result"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["reason"], "framework_path_unresolved")


class CoreEventForeignPreservation(_Base):
    """sync_hooks must MERGE a core hook event — reconcile only the framework's own hook
    entries while preserving foreign groups, foreign sub-entries inside a mixed group, and
    group matchers — never wholesale-replace the whole .hooks[event] array (AIR-001)."""

    FP = "~/.claude/hooks/file-protection.sh"

    def test_update_preserves_foreign_separate_group_in_core_event(self):
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["PreToolUse"].append(
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "~/owner/audit.sh", "timeout": 2}]}
        )
        self._write_settings(data)
        self._run(["--update"], check_rc=0)
        groups = self._read_settings()["hooks"]["PreToolUse"]
        cmds = self._event_commands(groups)
        self.assertIn("~/owner/audit.sh", cmds, "foreign separate group was dropped")
        self.assertEqual(cmds.count(self.FP), 1, "framework binding must appear exactly once")

    def test_update_preserves_foreign_subhook_in_mixed_core_group(self):
        self._run([], check_rc=0)
        data = self._read_settings()
        # Mix a foreign sub-entry INTO the framework PreToolUse group (shared matcher).
        data["hooks"]["PreToolUse"][0]["hooks"].append(
            {"type": "command", "command": "~/owner/extra.sh", "timeout": 9}
        )
        self._write_settings(data)
        self._run(["--update"], check_rc=0)
        groups = self._read_settings()["hooks"]["PreToolUse"]
        cmds = self._event_commands(groups)
        self.assertIn("~/owner/extra.sh", cmds, "foreign sub-entry in a mixed group was dropped")
        self.assertEqual(cmds.count(self.FP), 1)
        self.assertIn("Write|Edit|Read", [g.get("matcher") for g in groups],
                      "group matcher metadata was lost")

    def test_update_retains_foreign_hook_file_in_hooks_dir(self):
        # The broad orphan-hook-file prune is removed: a hook file with no ownership proof
        # (not a current source basename) must be RETAINED, not deleted, on a plain update.
        self._run([], check_rc=0)
        foreign = self.home / ".claude" / "hooks" / "owner-custom.sh"
        foreign.write_text("# owner hook\n")
        self._run(["--update"], check_rc=0)
        self.assertTrue(foreign.exists(), "foreign hook file was pruned")
        self.assertEqual(foreign.read_text(), "# owner hook\n")

    def test_update_core_binding_single_and_idempotent(self):
        self._run([], check_rc=0)
        self._run(["--update"], check_rc=0)
        self._run(["--update"], check_rc=0)
        cmds = self._event_commands(self._read_settings()["hooks"]["PreToolUse"])
        self.assertEqual(cmds.count(self.FP), 1,
                         "repeated updates must not duplicate the canonical binding")

    def test_update_prunes_stale_framework_event_but_keeps_foreign_subentry(self):
        # An off-template event carrying BOTH a stale framework hook and a foreign hook keeps
        # the foreign one; only the framework entry is stripped (never the whole event).
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["Stop"] = [
            {"hooks": [{"type": "command", "command": self.FP, "timeout": 3}]},
            {"hooks": [{"type": "command", "command": "~/owner/stop.sh", "timeout": 3}]},
        ]
        self._write_settings(data)
        self._run(["--update"], check_rc=0)
        stop = self._read_settings()["hooks"].get("Stop")
        self.assertIsNotNone(stop, "whole off-template event deleted despite a foreign binding")
        cmds = self._event_commands(stop)
        self.assertIn("~/owner/stop.sh", cmds)
        self.assertNotIn(self.FP, cmds, "stale framework hook not stripped from off-template event")

    def test_update_leaves_purely_foreign_offtemplate_event_untouched(self):
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["Stop"] = [
            {"hooks": [{"type": "command", "command": "/owner/only-mine.sh", "timeout": 3}]}
        ]
        self._write_settings(data)
        self._run(["--update"], check_rc=0)
        stop = self._read_settings()["hooks"].get("Stop")
        self.assertEqual(self._event_commands(stop), ["/owner/only-mine.sh"])


class EffortLevelCompat(_Base):
    """An existing CLAUDE_CODE_EFFORT_LEVEL must be preserved, not force-healed to the
    template default. max/auto are documented supported env values (AIR-COMPAT-01)."""

    def _set_effort(self, val):
        data = self._read_settings()
        data["env"]["CLAUDE_CODE_EFFORT_LEVEL"] = val
        self._write_settings(data)

    def _effort(self):
        return self._read_settings()["env"].get("CLAUDE_CODE_EFFORT_LEVEL")

    def test_update_preserves_supported_effort_values(self):
        self._run([], check_rc=0)
        for val in ("max", "auto", "high", "low"):
            with self.subTest(effort=val):
                self._set_effort(val)
                p = self._run(["--update"], check_rc=0)
                self.assertEqual(self._effort(), val, f"update overwrote effort {val!r}")
                self.assertNotIn("Healed invalid CLAUDE_CODE_EFFORT_LEVEL", p.stdout)

    def test_update_preserves_invalid_effort_and_reports_manual(self):
        self._run([], check_rc=0)
        self._set_effort("ultra9000")
        p = self._run(["--update"], check_rc=0)
        self.assertEqual(self._effort(), "ultra9000", "invalid value must be left unchanged")
        self.assertNotIn("Healed invalid CLAUDE_CODE_EFFORT_LEVEL", p.stdout)
        self.assertIn("unsupported value", p.stdout)
        # The arbitrary raw value is never echoed back into installer output.
        self.assertNotIn("ultra9000", p.stdout)

    def test_hook_accepts_max_and_auto_without_false_drift(self):
        self._run([], check_rc=0)
        for val in ("max", "auto"):
            with self.subTest(effort=val):
                (self.home / HEALTH_REL).unlink(missing_ok=True)
                self._set_effort(val)
                self._run_hook()
                drift = [e.get("check") for e in self._health_events()
                         if e.get("event") == "drift_detected"]
                self.assertNotIn("effort_value", drift, f"{val} wrongly flagged as effort drift")

    def test_update_preserves_absent_effort_and_hook_accepts_absence(self):
        # AIRR-001: a settings.json that INTENTIONALLY omits CLAUDE_CODE_EFFORT_LEVEL must
        # stay omitted after a plain update (not force-seeded to the template's xhigh), and
        # the SessionStart hook must treat that absence as a valid native default, not drift.
        self._run([], check_rc=0)
        data = self._read_settings()
        self.assertEqual(data["env"].get("CLAUDE_CODE_EFFORT_LEVEL"), "xhigh",
                         "fresh install should carry the template default")
        del data["env"]["CLAUDE_CODE_EFFORT_LEVEL"]
        self._write_settings(data)
        p = self._run(["--update"], check_rc=0)
        self.assertNotIn("CLAUDE_CODE_EFFORT_LEVEL", self._read_settings()["env"],
                         "absent effort key was re-inserted on update")
        self.assertNotIn("Added env var CLAUDE_CODE_EFFORT_LEVEL", p.stdout)
        # Hook: absence is healthy — neither an env-key nor an effort-value drift.
        (self.home / HEALTH_REL).unlink(missing_ok=True)
        self._run_hook()
        events = self._health_events()
        for e in (e for e in events if e.get("event") == "drift_detected"):
            self.assertNotIn(e.get("check"), ("env_key", "effort_value"),
                             msg=f"absent effort wrongly flagged as drift: {e}")
        result = [e for e in events if e.get("event") == "healthcheck_result"][-1]
        self.assertEqual(result["status"], "healthy", msg=json.dumps(result))

    def test_update_preserves_empty_effort_value(self):
        # An explicitly EMPTY effort value is a supported owner choice: preserved verbatim,
        # never reported as unsupported and never overwritten.
        self._run([], check_rc=0)
        self._set_effort("")
        p = self._run(["--update"], check_rc=0)
        self.assertEqual(self._effort(), "", "empty effort value was not preserved")
        self.assertNotIn("unsupported value", p.stdout)
        self.assertNotIn("Added env var CLAUDE_CODE_EFFORT_LEVEL", p.stdout)

    def test_update_still_adds_other_missing_env_key(self):
        # Negative control: the effort-specific skip must NOT disable the generic add-only
        # merge — any OTHER template env key that is missing is still added back.
        self._run([], check_rc=0)
        data = self._read_settings()
        del data["env"]["MAX_THINKING_TOKENS"]
        self._write_settings(data)
        p = self._run(["--update"], check_rc=0)
        self.assertIn("MAX_THINKING_TOKENS", self._read_settings()["env"],
                      "a non-effort missing env key was not re-added")
        self.assertIn("Added env var MAX_THINKING_TOKENS", p.stdout)


class SessionStartForeignHookHealth(_Base):
    """AIRR-002: Check 3 must verify the framework's OWN canonical hook binding is present
    exactly once (deep structural match on matcher/command/timeout) while ALLOWING preserved
    foreign groups/sub-entries in the same event — never convicting a correctly merged owner
    customization as drift, yet still catching a missing, modified or duplicated binding."""

    FP = "~/.claude/hooks/file-protection.sh"

    def _pretooluse_wiring_drift(self):
        return [e for e in self._health_events()
                if e.get("event") == "drift_detected"
                and e.get("check") == "hook_wiring"
                and e.get("expected_event") == "PreToolUse"]

    def _result(self):
        return [e for e in self._health_events()
                if e.get("event") == "healthcheck_result"][-1]

    def test_preserved_foreign_groups_through_update_stay_healthy(self):
        # Positive: a mixed foreign sub-entry + a separate foreign group + a foreign hook
        # file, carried through a real --update (the installer preserves all three), then
        # health-checked — the owned binding is intact so the run must be healthy.
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["PreToolUse"][0]["hooks"].append(
            {"type": "command", "command": "~/owner/mixed-check.sh", "timeout": 7})
        data["hooks"]["PreToolUse"].append(
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "~/owner/separate-check.sh", "timeout": 2}]})
        self._write_settings(data)
        (self.home / ".claude" / "hooks" / "owner-custom.sh").write_text("# owner hook\n")
        self._run(["--update"], check_rc=0)
        # Sanity: the merge kept both foreign bindings AND exactly one canonical binding.
        cmds = self._event_commands(self._read_settings()["hooks"]["PreToolUse"])
        self.assertIn("~/owner/mixed-check.sh", cmds)
        self.assertIn("~/owner/separate-check.sh", cmds)
        self.assertEqual(cmds.count(self.FP), 1)
        # Health: no PreToolUse wiring drift; whole run healthy.
        (self.home / HEALTH_REL).unlink(missing_ok=True)
        self._run_hook()
        self.assertEqual(self._pretooluse_wiring_drift(), [],
                         msg="preserved foreign PreToolUse groups wrongly reported as drift")
        self.assertEqual(self._result()["status"], "healthy", msg=json.dumps(self._result()))

    def test_missing_framework_binding_is_wiring_drift(self):
        # Negative control: the canonical framework group is absent (only a foreign group
        # remains) → a genuine missing-binding drift must still fire.
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["PreToolUse"] = [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "~/owner/only.sh", "timeout": 2}]}]
        self._write_settings(data)
        (self.home / HEALTH_REL).unlink(missing_ok=True)
        self._run_hook()
        drift = self._pretooluse_wiring_drift()
        self.assertNotEqual(drift, [], msg="missing framework PreToolUse binding not detected")
        self.assertEqual(drift[-1].get("actual"), "missing")
        self.assertEqual(self._result()["status"], "drift")

    def test_modified_framework_binding_is_wiring_drift(self):
        # Negative control: the binding is present by basename but MODIFIED (timeout
        # changed) → its canonical shape is absent → drift (basename alone is not ownership).
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 999
        self._write_settings(data)
        (self.home / HEALTH_REL).unlink(missing_ok=True)
        self._run_hook()
        self.assertNotEqual(self._pretooluse_wiring_drift(), [],
                            msg="modified framework PreToolUse binding not detected")
        self.assertEqual(self._result()["status"], "drift")

    def test_duplicated_framework_binding_is_wiring_drift(self):
        # Negative control: the canonical framework group appears TWICE → duplicate drift.
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["PreToolUse"].append(
            {"matcher": "Write|Edit|Read", "hooks": [
                {"type": "command", "command": self.FP, "timeout": 3}]})
        self._write_settings(data)
        (self.home / HEALTH_REL).unlink(missing_ok=True)
        self._run_hook()
        drift = self._pretooluse_wiring_drift()
        self.assertNotEqual(drift, [], msg="duplicated framework binding not detected")
        self.assertEqual(drift[-1].get("actual"), "duplicate")
        self.assertEqual(self._result()["status"], "drift")

    def test_foreign_subentry_inside_canonical_group_stays_healthy(self):
        # C2C observation case 1 (foreign-added-to-canonical-group): a foreign sub-entry
        # appended INSIDE the canonical PreToolUse group — exactly what the installer's own
        # mixed-group merge produces. The framework's file-protection.sh binding is still
        # present with its canonical matcher/command/timeout, so the run must be HEALTHY.
        # A whole-GROUP deep-equality check wrongly convicts this (the group no longer equals
        # the single-entry template group); the owned ENTRY must be matched while the foreign
        # sub-entry is projected out.
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["PreToolUse"][0]["hooks"].append(
            {"type": "command", "command": "/usr/bin/true"})
        self._write_settings(data)
        (self.home / HEALTH_REL).unlink(missing_ok=True)
        self._run_hook()
        self.assertEqual(self._pretooluse_wiring_drift(), [],
                         msg="foreign sub-entry inside the canonical group wrongly reported as drift")
        self.assertEqual(self._result()["status"], "healthy", msg=json.dumps(self._result()))

    def test_duplicated_owned_guard_across_mixed_groups_is_wiring_drift(self):
        # C2C observation case 2 (duplicate-canonical-mixed-group): the canonical group PLUS a
        # SECOND group carrying the SAME owned guard alongside a foreign sub-entry. The owned
        # guard therefore runs TWICE. A whole-GROUP check sees only one exact-group match and
        # passes the run healthy, letting an extra owned binding hide behind the valid group;
        # counting the owned ENTRY across all matching-matcher groups must report DRIFT
        # (duplicate).
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["PreToolUse"].append(
            {"matcher": "Write|Edit|Read", "hooks": [
                {"type": "command", "command": self.FP, "timeout": 3},
                {"type": "command", "command": "/usr/bin/true"}]})
        self._write_settings(data)
        (self.home / HEALTH_REL).unlink(missing_ok=True)
        self._run_hook()
        drift = self._pretooluse_wiring_drift()
        self.assertNotEqual(drift, [],
                            msg="duplicated owned guard across mixed groups not detected")
        self.assertEqual(drift[-1].get("actual"), "duplicate")
        self.assertEqual(self._result()["status"], "drift")

    def test_extra_modified_owned_entry_beside_valid_is_wiring_drift(self):
        # C2D observation case (extra-modified-owned): the canonical PreToolUse group stays
        # INTACT, but a SECOND group with the SAME matcher re-runs the SAME owned command with
        # a MODIFIED timeout. The valid binding satisfies an exact-match count, so counting only
        # EXACT owned entries lets the extra modified twin hide — the run is reported healthy
        # while the owned guard actually runs twice with divergent metadata. Comparing the owned
        # MULTISET (full entry shape) against the template catches the extra owned tuple. This
        # must agree with validate.sh, which already fails this case.
        self._run([], check_rc=0)
        data = self._read_settings()
        data["hooks"]["PreToolUse"].append(
            {"matcher": "Write|Edit|Read", "hooks": [
                {"type": "command", "command": self.FP, "timeout": 999}]})
        self._write_settings(data)
        (self.home / HEALTH_REL).unlink(missing_ok=True)
        self._run_hook()
        drift = self._pretooluse_wiring_drift()
        self.assertNotEqual(drift, [],
                            msg="an extra modified owned entry beside the valid binding was not detected")
        self.assertEqual(self._result()["status"], "drift")


class SessionStartReadabilityGate(_Base):
    """A present-but-malformed template or settings file is UNKNOWN, never a fresh green
    with a couple of empty-comparison checks counted as completed (AIR-002)."""

    def _fake_repo(self, template_text):
        repo = self.root / "fakerepo"
        (repo / ".claude" / "agents").mkdir(parents=True)
        (repo / ".claude" / "agents" / "dummy.md").write_text("# dummy\n")
        (repo / "global-config").mkdir(parents=True)
        (repo / "global-config" / "settings.json.template").write_text(template_text)
        return repo

    def _deploy(self, repo, settings_text):
        claude = self.home / ".claude"
        (claude / "analytics").mkdir(parents=True)
        (claude / "agents").mkdir(parents=True)
        (claude / "agents" / "dummy.md").write_text("# dummy\n")  # match source: no shared-set drift
        (claude / "settings.json").write_text(settings_text)
        claude.joinpath(".framework-path").write_text(str(repo) + "\n")
        claude.joinpath(".framework-version").write_text(
            "version=3.2.0\nsha=x\nahead=0\ninstalled_at=t\n"
            "analytics=disabled\nwatchdog=disabled\nnotifications=disabled\n"
        )

    def test_malformed_template_and_settings_report_unknown_not_healthy(self):
        repo = self._fake_repo("{")           # malformed template
        self._deploy(repo, "{")               # malformed settings
        before = (self.home / ".claude" / "settings.json").read_bytes()
        self._run_hook()
        results = [e for e in self._health_events() if e.get("event") == "healthcheck_result"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "unknown",
                         msg=f"unreadable config reported as: {results[0]}")
        self.assertIn(results[0]["reason"], ("template_unreadable", "settings_unreadable"))
        # The malformed settings is preserved byte-for-byte (the hook never writes).
        self.assertEqual((self.home / ".claude" / "settings.json").read_bytes(), before)

    def test_valid_json_wrong_shape_settings_is_unknown(self):
        # Valid JSON but not an object (an array) must not pass as a readable settings object.
        repo = self._fake_repo((REPO / "global-config" / "settings.json.template").read_text())
        self._deploy(repo, "[]")
        self._run_hook()
        results = [e for e in self._health_events() if e.get("event") == "healthcheck_result"]
        self.assertEqual(results[-1]["status"], "unknown")
        self.assertEqual(results[-1]["reason"], "settings_unreadable")


class SessionStartSelectionTriState(_Base):
    """absent / duplicate / invalid selection fields are UNKNOWN, not silently disabled,
    so an ambiguous or corrupt marker never produces a fresh green (AIR-003)."""

    def _result(self):
        return [e for e in self._health_events()
                if e.get("event") == "healthcheck_result"][-1]

    def test_duplicate_marker_field_is_unknown(self):
        self._run([], check_rc=0)
        marker = self.home / ".claude" / ".framework-version"
        marker.write_text(marker.read_text() + "analytics=disabled\n")  # duplicate key → ambiguous
        self._run_hook()
        r = self._result()
        self.assertEqual(r["status"], "unknown", msg=json.dumps(r))
        self.assertEqual(r["reason"], "analytics_selection_unknown")

    def test_absent_marker_field_is_unknown(self):
        self._run([], check_rc=0)
        marker = self.home / ".claude" / ".framework-version"
        kept = [ln for ln in marker.read_text().splitlines()
                if not ln.startswith("notifications=")]
        marker.write_text("\n".join(kept) + "\n")  # drop the notifications field entirely
        self._run_hook()
        self.assertEqual(self._result()["status"], "unknown")

    def test_invalid_marker_value_is_unknown(self):
        self._run([], check_rc=0)
        marker = self.home / ".claude" / ".framework-version"
        marker.write_text(marker.read_text().replace("watchdog=disabled", "watchdog=maybe"))
        self._run_hook()
        r = self._result()
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["reason"], "watchdog_selection_unknown")

    def test_all_disabled_fresh_marker_is_healthy(self):
        # Control: the fresh-default marker (all three explicitly disabled) IS healthy.
        self._run([], check_rc=0)
        self._run_hook()
        self.assertEqual(self._result()["status"], "healthy")


class SessionStartSelectedAssets(_Base):
    """An explicitly ENABLED component with a missing required payload is drift — existence
    checks only, never a hash claim against possibly-customized bytes (AIR-004 + gap 4)."""

    def _results(self):
        return self._health_events()

    def test_enabled_analytics_missing_asset_is_drift(self):
        (self.home / ".zshrc").write_text("")
        self._run(["--with-analytics"], check_rc=0)
        (self.home / ".claude" / "analytics" / "collector.py").unlink()
        self._run_hook()
        events = self._results()
        drift = [e.get("check") for e in events if e.get("event") == "drift_detected"]
        self.assertIn("analytics_asset", drift)
        result = [e for e in events if e.get("event") == "healthcheck_result"][-1]
        self.assertEqual(result["status"], "drift")

    def test_enabled_analytics_present_assets_no_false_drift(self):
        (self.home / ".zshrc").write_text("")
        self._run(["--with-analytics"], check_rc=0)
        self._run_hook()
        events = self._results()
        drift = [e.get("check") for e in events if e.get("event") == "drift_detected"]
        self.assertNotIn("analytics_asset", drift)
        result = [e for e in events if e.get("event") == "healthcheck_result"][-1]
        self.assertEqual(result["status"], "healthy", msg=json.dumps(result))

    def test_disabled_analytics_absent_asset_is_not_drift(self):
        # Fresh default: analytics disabled → collector.py legitimately absent → not drift.
        self._run([], check_rc=0)
        self._run_hook()
        drift = [e.get("check") for e in self._results() if e.get("event") == "drift_detected"]
        self.assertNotIn("analytics_asset", drift)

    @unittest.skipUnless(sys.platform == "darwin", "watchdog daemon is macOS-only")
    def test_enabled_watchdog_missing_daemon_is_drift_on_macos(self):
        self._run([], check_rc=0)  # fresh: watchdog disabled, daemon absent
        marker = self.home / ".claude" / ".framework-version"
        marker.write_text(marker.read_text().replace("watchdog=disabled", "watchdog=enabled"))
        self._run_hook()
        events = self._results()
        drift = [e.get("check") for e in events if e.get("event") == "drift_detected"]
        self.assertIn("watchdog_asset", drift)


class SeedWithoutJq(_Base):
    """Seeding settings.json without jq must FAIL CLOSED — never raw-copy the unfiltered
    template, which would wire optional hook events that were never selected (AIR-005)."""

    def test_seed_helper_without_jq_fails_closed(self):
        body = (
            'command() { if [ "$1" = "-v" ] && [ "$2" = "jq" ]; then return 1; fi; '
            'builtin command "$@"; }\n'
            'mkdir -p "$HOME/.claude/hooks"\n'
            'printf "#!/bin/bash\\necho notify\\n" > "$HOME/.claude/hooks/notify.sh"\n'
            'SEL_ANALYTICS=0; SEL_NOTIFICATIONS=0; SEL_WATCHDOG=0\n'
            '_seed_settings_from_template "$HOME/.claude/settings.json"; echo "SEED_RC=$?"\n'
        )
        p = self._run_driver(body)
        self.assertIn("SEED_RC=1", p.stdout, msg=f"STDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
        self.assertFalse(self._settings_path().exists(), "settings.json seeded without jq")
        self.assertIn("without jq", p.stdout)
        # The pre-existing optional hook script is left exactly as it was.
        self.assertTrue((self.home / ".claude" / "hooks" / "notify.sh").exists())

    def test_actual_update_without_jq_does_not_wire_optional_bindings(self):
        env = self._jqless_env()
        self.assertIsNone(shutil.which("jq", path=env["PATH"]), "jq leaked into jqless PATH")
        hooks = self.home / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "notify.sh").write_text("# owner notify\n")  # pre-existing optional script
        # No settings.json present → the update would otherwise reseed it.
        p = self._run(["--update"], env=env)
        # Fail-closed: either no settings.json at all, or one with NO optional events wired.
        if self._settings_path().exists():
            events = set(self._read_settings().get("hooks", {}).keys())
            for ev in ("Notification", "SubagentStart", "SubagentStop", "SessionEnd"):
                self.assertNotIn(ev, events, "optional event wired without jq / without a flag")
        self.assertIn("without jq", p.stdout)
        self.assertEqual((self.home / ".claude" / "hooks" / "notify.sh").read_text(),
                         "# owner notify\n", "pre-existing optional script altered")


class PreserveCustomSymlinkSafety(_Base):
    """_install_preserving_custom must refuse a symlink destination (even dangling) and a
    symlinked ancestor, never following it to write outside the intended tree (AIR-006)."""

    def test_refuses_dangling_symlink_destination(self):
        ext = self.root / "external"
        ext.mkdir()
        target = ext / "outside-target"          # must NEVER be created
        src = self.root / "srcasset.txt"
        src.write_text("new asset\n")
        dst = self.home / ".claude" / "analytics" / "collector.py"
        body = (
            'mkdir -p "$HOME/.claude/analytics"\n'
            f'ln -s "{target}" "{dst}"\n'          # dangling symlink destination
            f'_install_preserving_custom "{src}" "{dst}" "analytics collector.py"; echo "RC=$?"\n'
        )
        p = self._run_driver(body)
        self.assertIn("RC=0", p.stdout, msg=f"STDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
        self.assertFalse(target.exists(), "wrote THROUGH a dangling symlink, outside ~/.claude")
        self.assertTrue(dst.is_symlink(), "symlink destination was not preserved")
        self.assertIn("symlink", p.stdout)

    def test_refuses_symlinked_ancestor_directory(self):
        ext = self.root / "external"
        (ext / "realanalytics").mkdir(parents=True)
        src = self.root / "srcasset.txt"
        src.write_text("new\n")
        body = (
            'mkdir -p "$HOME/.claude"\n'
            f'ln -s "{ext / "realanalytics"}" "$HOME/.claude/analytics"\n'   # analytics dir is a symlink
            f'_install_preserving_custom "{src}" "$HOME/.claude/analytics/collector.py" "lbl"; echo "RC=$?"\n'
        )
        p = self._run_driver(body)
        self.assertIn("RC=0", p.stdout)
        self.assertFalse((ext / "realanalytics" / "collector.py").exists(),
                         "wrote through a symlinked ancestor directory")
        self.assertIn("symlinked directory", p.stdout)

    def test_preserve_custom_controls(self):
        src = self.root / "srcasset.txt"
        src.write_text("framework bytes\n")
        body = (
            'mkdir -p "$HOME/.claude/analytics"\n'
            f'_install_preserving_custom "{src}" "$HOME/.claude/analytics/a.py" "a"; echo "C1=$?"\n'
            f'cp "{src}" "$HOME/.claude/analytics/b.py"\n'
            f'_install_preserving_custom "{src}" "$HOME/.claude/analytics/b.py" "b"; echo "C2=$?"\n'
            'printf "owner edit\\n" > "$HOME/.claude/analytics/c.py"\n'
            f'_install_preserving_custom "{src}" "$HOME/.claude/analytics/c.py" "c"; echo "C3=$?"\n'
        )
        p = self._run_driver(body)
        a = self.home / ".claude" / "analytics" / "a.py"
        c = self.home / ".claude" / "analytics" / "c.py"
        self.assertEqual(a.read_text(), "framework bytes\n", "absent dest was not created")
        self.assertEqual(c.read_text(), "owner edit\n", "differing custom file was overwritten")
        self.assertIn("Installed", p.stdout)
        self.assertIn("already up to date", p.stdout)
        self.assertIn("Preserved existing", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
