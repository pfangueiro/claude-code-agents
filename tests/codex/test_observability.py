"""Observability lane regression tests: CR-01, CR-03, CR-04, HTTP-01 and the
four independent-review findings OBS-IR01..04.

Everything runs against disposable temp directories and synthetic fixtures — no
real ~/.claude home, no real analytics DB, and no outbound browser/network calls.
The dashboard HTTP cases bind an ephemeral loopback listener (127.0.0.1:0) and are
joined/shut down in tearDown. The capability token is injected as a fixture through
build_server(), never via a CLI flag, so no unauthenticated path is exercised.

  - CR-01: the shipped hook writers must emit one compact JSON object per line and
           round-trip through the collector (quoted/newline values, completed
           activation + duration).
  - CR-03: an incomplete trailing JSON record must not advance the watermark; once
           the writer finishes it, the collector ingests it exactly once.
  - OBS-IR01: a file that shrank below its watermark (truncation/rotation/replace)
           must not replay the retained prefix or silently skip; the collector
           refuses with ShrinkDetectedError and leaves the DB/watermark untouched
           until an explicit --full rebuild.
  - OBS-IR02: JSONL boundaries are read as true byte offsets, so a CRLF stream
           paused after a CR cannot persist an opaque text cookie / overflow the
           SQLite watermark; literal multi-byte UTF-8 tails are held then ingested.
  - OBS-IR03 / HTTP-01: wildcard CORS removed; Origin/Host validated as a strict
           loopback authority at the bound port (wrong port/scheme/userinfo/path,
           bracket-suffix, duplicate/missing Host all 403 for GET and HEAD); API
           behind a capability token; only UI assets served (DB/logs/source/
           traversal return 404).
  - OBS-IR04: the dashboard's auth bootstrap (token capture + fragment cleanup)
           runs before any Chart.js/CDN code, so a blocked CDN cannot leave the
           capability in the URL/history.
  - SRV-IDLE: build_server() uses ThreadingHTTPServer, so a connection opened
           without sending a request (browsers routinely pre-open sockets) no longer
           serializes the listener. A concurrent asset GET, a token-bearing API call
           and a token-less API call all complete (200/200/401) while the idle socket
           stays open; a plain single-threaded HTTPServer blocks them (negative
           control). Auth stays gated and the per-request read-only SQLite
           connections run across threads with no shared-handle error.
  - SRV-PORT: a Host authority whose port is thousands of ASCII digits long no longer
           trips an uncaught int-conversion ValueError that aborted the connection;
           _parse_port returns None so GET and HEAD get a clean 403 (no 500, no
           disconnect) and the server keeps serving, while the accepted port grammar
           and range are unchanged.
"""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
OBS_DIR = ROOT / "observability"
HOOKS_DIR = ROOT / "global-config" / "hooks"
PY = sys.executable
JQ = shutil.which("jq")
NODE = shutil.which("node")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load_module("obs_collector", OBS_DIR / "collector.py")
server = load_module("obs_server", OBS_DIR / "server.py")


def assistant_line(session="s1", model="claude-opus-4-8", inp=10, out=5, ts="2026-01-01T00:00:00Z", extra=None):
    """One complete assistant transcript record as a compact JSON string (no newline)."""
    rec = {
        "type": "assistant",
        "sessionId": session,
        "timestamp": ts,
        "message": {"model": model, "usage": {"input_tokens": inp, "output_tokens": out}},
    }
    if extra:
        rec["message"][extra[0]] = extra[1]
    return json.dumps(rec)


# ---------------------------------------------------------------------------
# CR-01 — hook writers emit compact JSONL and round-trip through the collector
# ---------------------------------------------------------------------------

@unittest.skipIf(JQ is None, "jq is required by the hook writers")
class HookRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="obs-hooks-")
        self.home = Path(self.tmp.name).resolve()
        self.analytics = self.home / ".claude" / "analytics"
        self.analytics.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, script, payload, *args):
        env = dict(os.environ, HOME=str(self.home))
        proc = subprocess.run(
            ["bash", str(HOOKS_DIR / script), *args],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def lines(self, name):
        raw = (self.analytics / name).read_text(encoding="utf-8")
        return [ln for ln in raw.split("\n") if ln.strip()]

    def test_writers_are_compact_one_object_per_line(self):
        # A description carrying both a quote and a newline is the exact case that
        # pretty-printed jq would split across physical lines and corrupt.
        desc = 'first line\nsecond "quoted" line'
        self.run_hook("agent-tracker.sh", {"session_id": "s1", "subagent_type": "code-quality", "description": desc}, "start")
        self.run_hook("agent-tracker.sh", {"session_id": "s1", "subagent_type": "code-quality", "duration_ms": 1234, "status": "completed"}, "stop")
        self.run_hook("session-end.sh", {"session_id": "s1", "cwd": "/tmp/proj"})
        self.run_hook("smart-guard.sh", {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "s1"})

        agent_lines = self.lines("agent-events.jsonl")
        self.assertEqual(len(agent_lines), 2, "start+stop must be exactly two physical lines")
        start, stop = json.loads(agent_lines[0]), json.loads(agent_lines[1])
        self.assertEqual(start["event"], "agent_start")
        self.assertEqual(start["description"], desc)  # newline/quote preserved as escapes
        self.assertEqual(stop["event"], "agent_stop")
        self.assertEqual(stop["duration_ms"], 1234)  # numeric, not a string

        summary_lines = self.lines("session-summaries.jsonl")
        self.assertEqual(len(summary_lines), 1)
        self.assertEqual(json.loads(summary_lines[0])["event"], "session_end")

        audit_lines = self.lines("permission-audit.jsonl")
        self.assertEqual(len(audit_lines), 1)
        audit = json.loads(audit_lines[0])
        self.assertEqual(audit["event"], "permission_request")
        self.assertEqual(audit["tool"], "Bash")

    def test_collector_ingests_hook_output(self):
        self.run_hook("agent-tracker.sh", {"session_id": "s1", "subagent_type": "code-quality", "description": "work"}, "start")
        self.run_hook("agent-tracker.sh", {"session_id": "s1", "subagent_type": "code-quality", "duration_ms": 1234, "status": "completed"}, "stop")
        self.run_hook("session-end.sh", {"session_id": "s1", "cwd": "/tmp/proj"})

        db = self.home / "obs.db"
        conn = collector.init_db(str(db))
        try:
            collector.ingest_agent_events(conn, str(self.analytics / "agent-events.jsonl"))
            collector.ingest_hook_events(conn, str(self.analytics / "session-summaries.jsonl"), "session_end")

            counts = dict(conn.execute(
                "SELECT event_type, COUNT(*) FROM hook_events GROUP BY event_type"
            ).fetchall())
            self.assertEqual(counts.get("agent_start"), 1)
            self.assertEqual(counts.get("agent_stop"), 1)
            self.assertEqual(counts.get("session_end"), 1)

            row = conn.execute(
                "SELECT status, duration_ms FROM agent_activations "
                "WHERE agent_name = 'code-quality'"
            ).fetchone()
            self.assertEqual(row[0], "completed")
            self.assertEqual(row[1], 1234)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# CR-03 / CR-04 — collector watermark robustness
# ---------------------------------------------------------------------------

class WatermarkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="obs-wm-")
        self.base = Path(self.tmp.name).resolve()
        self.path = self.base / "transcript.jsonl"
        self.conn = collector.init_db(str(self.base / "obs.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def process(self):
        return collector.process_jsonl_file(self.conn, str(self.path), "proj")

    def api_count(self, where="", params=()):
        sql = "SELECT COUNT(*) FROM api_calls"
        if where:
            sql += " WHERE " + where
        return self.conn.execute(sql, params).fetchone()[0]

    def watermark(self):
        return collector.get_watermark(self.conn, str(self.path))

    def write(self, data, mode="w"):
        with open(self.path, mode, encoding="utf-8") as f:
            f.write(data)

    def write_bytes(self, data, mode="wb"):
        with open(self.path, mode) as f:
            f.write(data)

    def total_cost(self):
        return self.conn.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM api_calls"
        ).fetchone()[0]

    def test_incomplete_trailing_record_is_not_consumed_then_ingested_once(self):
        full = assistant_line()
        partial, tail = full[:-3], full[-3:]  # split before the closing "}}" + value
        self.assertNotEqual(tail, "")

        self.write(partial)  # no newline, truncated JSON — an in-progress append
        self.assertEqual(self.process(), 0)
        self.assertEqual(self.api_count(), 0)
        self.assertEqual(self.watermark(), 0, "watermark must not advance past a partial record")

        self.write(tail + "\n", mode="a")  # writer finishes the record
        self.process()
        self.assertEqual(self.api_count(), 1, "finished record ingested exactly once")

    def test_append_and_idempotent_rerun(self):
        self.write(assistant_line(ts="2026-01-01T00:00:00Z") + "\n")
        self.write(assistant_line(ts="2026-01-01T00:01:00Z") + "\n", mode="a")
        self.process()
        self.assertEqual(self.api_count(), 2)

        self.process()  # unchanged rerun
        self.assertEqual(self.api_count(), 2, "unchanged rerun must not duplicate")

        self.write(assistant_line(ts="2026-01-01T00:02:00Z") + "\n", mode="a")
        self.process()
        self.assertEqual(self.api_count(), 3, "only the appended record is added")

    def test_final_valid_line_without_newline_and_non_ascii(self):
        line = assistant_line(extra=("note", "café ☕ 测试"))  # multi-byte, valid, no newline
        self.write(line)
        self.process()
        self.assertEqual(self.api_count(), 1)
        self.assertEqual(self.watermark(), os.path.getsize(self.path),
                         "byte watermark must match file size across multi-byte content")

    def test_malformed_complete_line_is_skipped_not_blocking(self):
        self.write("{not valid json}\n" + assistant_line() + "\n")
        self.process()
        self.assertEqual(self.api_count(), 1, "the valid line after a bad one is still ingested")
        self.assertEqual(self.watermark(), os.path.getsize(self.path))

    # --- OBS-IR01: shrink refuses rather than replaying or dropping data --------
    def test_prefix_preserving_truncation_refuses_without_inflation(self):
        # Ingest A+B, then shorten the file to just its retained first record.
        self.write(assistant_line(session="s1", ts="2026-01-01T00:00:00Z") + "\n")
        self.write(assistant_line(session="s1", ts="2026-01-01T00:01:00Z") + "\n", mode="a")
        self.process()
        self.assertEqual(self.api_count(), 2)
        cost_before = self.total_cost()
        wm_before = self.watermark()

        self.write(assistant_line(session="s1", ts="2026-01-01T00:00:00Z") + "\n")  # back to A only
        self.assertLess(os.path.getsize(self.path), wm_before, "must shrink below the watermark")

        with self.assertRaises(collector.ShrinkDetectedError):
            self.process()
        # No replay of the retained prefix, no cost inflation, nothing written.
        self.assertEqual(self.api_count(), 2, "retained prefix must not be replayed")
        self.assertEqual(self.total_cost(), cost_before, "cost must not inflate on shrink")
        self.assertEqual(self.watermark(), wm_before, "watermark preserved — no write on refusal")

    def test_distinct_shorter_replacement_also_refuses(self):
        self.write(assistant_line(session="old-session-aaaaaaaaaaaaaaaaaaaa", ts="2026-01-01T00:00:00Z") + "\n")
        self.write(assistant_line(session="old-session-aaaaaaaaaaaaaaaaaaaa", ts="2026-01-01T00:01:00Z") + "\n", mode="a")
        self.process()
        self.assertEqual(self.api_count(), 2)
        wm_before = self.watermark()

        # A strictly shorter, entirely different file is still a shrink → refuse.
        self.write(assistant_line(session="s2", ts="2026-02-02T00:00:00Z") + "\n")
        self.assertLess(os.path.getsize(self.path), wm_before)
        with self.assertRaises(collector.ShrinkDetectedError):
            self.process()
        self.assertEqual(self.api_count("session_id = ?", ("s2",)), 0,
                         "nothing is ingested on refusal — no partial, no silent skip")
        self.assertEqual(self.watermark(), wm_before)

    def test_full_mode_rebuilds_past_a_shrink(self):
        # --full is the explicit owner path: it resumes at 0 without raising (in a
        # real run main() has already cleared the DB, so there is no double count).
        self.write(assistant_line(session="s1", ts="2026-01-01T00:00:00Z") + "\n")
        self.write(assistant_line(session="s1", ts="2026-01-01T00:01:00Z") + "\n", mode="a")
        self.process()
        self.write(assistant_line(session="s2", ts="2026-02-02T00:00:00Z") + "\n")
        size = os.path.getsize(self.path)
        self.assertEqual(
            collector.resume_watermark(self.conn, str(self.path), size, True), 0,
            "--full must bypass the shrink refusal",
        )
        collector.process_jsonl_file(self.conn, str(self.path), "proj", full_mode=True)
        self.assertEqual(self.api_count("session_id = ?", ("s2",)), 1)
        self.assertEqual(self.watermark(), size)

    # --- OBS-IR02: true byte offsets, no text-decoder cookie / overflow ---------
    def test_crlf_terminator_lands_byte_watermark(self):
        self.write_bytes((assistant_line(ts="2026-01-01T00:00:00Z") + "\r\n").encode("utf-8"))
        self.process()
        self.assertEqual(self.api_count(), 1)
        self.assertEqual(self.watermark(), os.path.getsize(self.path),
                         "CRLF line must leave a byte-offset watermark equal to the file size")

    def test_cr_tail_awaiting_lf_no_overflow_then_single_ingest(self):
        # A complete record followed by a bare CR models a CRLF stream paused between
        # CR and LF. The old text-mode tell() returned an opaque cookie > 2**63 that
        # overflowed the SQLite watermark; the binary reader yields a real offset.
        rec = assistant_line(session="s1", ts="2026-01-01T00:00:00Z")
        self.write_bytes((rec + "\r").encode("utf-8"))
        size_cr = os.path.getsize(self.path)
        self.process()  # must not raise OverflowError
        self.assertEqual(self.api_count(), 1, "the complete record before the CR is ingested")
        self.assertEqual(self.watermark(), size_cr, "watermark is a real byte offset, not a cookie")

        # Writer completes the terminator and appends a second record.
        self.write_bytes(("\n" + assistant_line(session="s1", ts="2026-01-01T00:01:00Z") + "\n").encode("utf-8"), mode="ab")
        self.process()
        self.assertEqual(self.api_count(), 2, "second record ingested once — the first is not replayed")
        self.assertEqual(self.watermark(), os.path.getsize(self.path))

    def test_literal_utf8_partial_tail_held_then_completed(self):
        # Genuine multi-byte bytes (ensure_ascii=False), truncated mid-record, then
        # finished on the next pass. The partial tail is held; the completed record
        # lands a byte watermark equal to the file size.
        record = json.dumps({
            "type": "assistant", "sessionId": "s1", "timestamp": "2026-01-01T00:00:00Z",
            "message": {"model": "claude-opus-4-8",
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                        "note": "café ☕ 测试"},
        }, ensure_ascii=False).encode("utf-8")
        self.write_bytes(record[:-4])  # cut inside the record, no newline
        self.process()
        self.assertEqual(self.api_count(), 0, "truncated record is held, not ingested")
        self.assertEqual(self.watermark(), 0, "watermark stays before an in-progress record")

        self.write_bytes(record[-4:] + b"\n", mode="ab")
        self.process()
        self.assertEqual(self.api_count(), 1)
        self.assertEqual(self.watermark(), os.path.getsize(self.path),
                         "byte watermark equals file size across literal multi-byte content")


# ---------------------------------------------------------------------------
# HTTP-01 — dashboard HTTP privacy boundary
# ---------------------------------------------------------------------------

class _IdleSignalingHandler(server.DashboardHandler):
    """DashboardHandler that signals once a connection is inside its handler.

    Used only by the single-threaded negative-control server in the idle-socket
    test: the probe waits on ``self.server.accepted_event`` so it knows the idle
    connection provably occupies the server's one worker before it opens a second
    connection — removing the accept-order race without a sleep. Behaviour is
    otherwise identical to DashboardHandler.
    """

    def setup(self):
        super().setup()
        event = getattr(self.server, "accepted_event", None)
        if event is not None:
            event.set()


def get_status(port, path, timeout, host=None, auth=None, origin=None):
    """GET ``path`` and return the HTTP status, or None if it did not complete within
    ``timeout`` (the connection blocked). A dropped connection propagates so a server
    crash surfaces as a test error rather than a silent None."""
    hdrs = {}
    if host is not None:
        hdrs["Host"] = host
    if auth is not None:
        hdrs["Authorization"] = f"Bearer {auth}"
    if origin is not None:
        hdrs["Origin"] = origin
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path, headers=hdrs)
        resp = conn.getresponse()
        resp.read()
        return resp.status
    except (socket.timeout, TimeoutError):
        return None
    finally:
        conn.close()


class DashboardHttpTest(unittest.TestCase):
    TOKEN = "fixture-capability-token"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="obs-http-")
        self.base = Path(self.tmp.name).resolve()
        self.db = self.base / "claude-obs.db"
        conn = collector.init_db(str(self.db))
        conn.execute(
            "INSERT INTO sessions (session_id, project, cwd, started_at) VALUES (?, ?, ?, ?)",
            ("sess-1", "demo", "/secret/workdir", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO api_calls (session_id, project, model, input_tokens, output_tokens, "
            "estimated_cost_usd, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sess-1", "demo", "claude-opus-4-8", 100, 50, 0.01, "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        self.httpd = server.build_server("127.0.0.1", 0, token=self.TOKEN, db_path=str(self.db))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def request(self, method, path, headers=None, host=None, auth=None, origin=None):
        hdrs = dict(headers or {})
        if host is not None:
            hdrs["Host"] = host
        if auth is not None:
            hdrs["Authorization"] = f"Bearer {auth}"
        if origin is not None:
            hdrs["Origin"] = origin
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, headers=hdrs)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, dict(resp.getheaders()), body
        finally:
            conn.close()

    def raw_status(self, request_lines):
        """Send a hand-built request (full control over Host/duplicates) → status int."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            sock.sendall(("\r\n".join(request_lines) + "\r\n\r\n").encode("latin-1"))
            buf = b""
            while b"\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            status_line = buf.split(b"\r\n", 1)[0].decode("latin-1")
            return int(status_line.split()[1])
        finally:
            sock.close()

    # --- authentication -----------------------------------------------------
    def test_api_requires_token(self):
        # days=0 == "All", so the fixture session is not filtered out by the window.
        status, headers, body = self.request("GET", "/api/sessions?days=0", auth=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers, "wildcard CORS must be gone")
        data = json.loads(body)
        self.assertTrue(any(row["project"] == "demo" for row in data))

    def test_api_without_token_is_401(self):
        status, headers, _ = self.request("GET", "/api/sessions")
        self.assertEqual(status, 401)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_api_with_wrong_token_is_401(self):
        status, _, _ = self.request("GET", "/api/sessions", auth="not-the-token")
        self.assertEqual(status, 401)

    def test_session_detail_is_token_gated_and_functional(self):
        status, _, body = self.request("GET", "/api/session-detail?session_id=sess-1", auth=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["cwd"], "/secret/workdir")
        status, _, _ = self.request("GET", "/api/session-detail?session_id=sess-1")
        self.assertEqual(status, 401)

    # --- origin / host ------------------------------------------------------
    def test_foreign_origin_rejected(self):
        status, headers, _ = self.request("GET", "/api/sessions", auth=self.TOKEN, origin="http://evil.example")
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_foreign_host_rejected(self):
        status, _, _ = self.request("GET", "/api/sessions", auth=self.TOKEN, host="evil.example")
        self.assertEqual(status, 403)

    def test_loopback_origin_allowed(self):
        status, _, _ = self.request("GET", "/api/sessions", auth=self.TOKEN, origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual(status, 200)

    # --- OBS-IR03: strict loopback authority at the bound port ------------------
    def test_exact_loopback_origin_allowed_get_and_head(self):
        for host in ("127.0.0.1", "localhost"):
            for method in ("GET", "HEAD"):
                status, _, _ = self.request(method, "/", origin=f"http://{host}:{self.port}")
                self.assertEqual(status, 200, f"{method} exact origin http://{host}:{self.port} must be allowed")

    def test_wrong_authority_origins_rejected_get_and_head(self):
        bad_origins = [
            f"http://127.0.0.1:{self.port + 1}",            # wrong port
            "http://127.0.0.1:1",                           # wrong port
            f"https://127.0.0.1:{self.port}",               # wrong scheme
            "ftp://127.0.0.1",                              # foreign scheme
            f"http://user@127.0.0.1:{self.port}",           # userinfo
            f"http://127.0.0.1:{self.port}/evil",           # path suffix
            f"http://127.0.0.1:{self.port}?x=1",            # query suffix
            "http://127.0.0.1",                             # no port (bound port != 80)
            "http://evil.example",                          # foreign host
        ]
        for origin in bad_origins:
            for method in ("GET", "HEAD"):
                status, _, _ = self.request(method, "/", origin=origin)
                self.assertEqual(status, 403, f"{method} origin {origin} must be 403")

    def test_wrong_authority_hosts_rejected(self):
        bad_hosts = [
            "127.0.0.1:1",                      # wrong port
            f"127.0.0.1:{self.port + 1}",       # wrong port
            "127.0.0.1:99999",                  # out-of-range port
            "127.0.0.1:0x50",                   # non-decimal port
            "127.0.0.1:",                       # empty port
            "[::1]evil.invalid",                # garbage after IPv6 bracket
            "127.0.0.1/evil",                   # path garbage in authority
            "evil.example",                     # foreign host
            f"evil.example:{self.port}",        # foreign host at right port
        ]
        for host in bad_hosts:
            status, _, _ = self.request("GET", "/", host=host)
            self.assertEqual(status, 403, f"Host {host} must be 403")

    def test_bound_port_host_allowed(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            status, _, _ = self.request("GET", "/", host=host)
            self.assertEqual(status, 200, f"Host {host} at the bound port must be allowed")

    def test_duplicate_host_header_rejected(self):
        status = self.raw_status([
            "GET / HTTP/1.1",
            f"Host: 127.0.0.1:{self.port}",
            f"Host: 127.0.0.1:{self.port}",
            "Connection: close",
        ])
        self.assertEqual(status, 403, "ambiguous duplicate Host must be rejected")

    def test_missing_host_on_http11_rejected(self):
        status = self.raw_status(["GET / HTTP/1.1", "Connection: close"])
        self.assertEqual(status, 403, "HTTP/1.1 must carry a Host header")

    def test_valid_headers_without_token_still_401(self):
        # Origin/Host gate passes; the API still fails closed without a token.
        status, _, _ = self.request("GET", "/api/sessions?days=0", origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual(status, 401)
        status, _, _ = self.request("HEAD", "/api/sessions?days=0", origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual(status, 401)

    # --- static allowlist ---------------------------------------------------
    def test_dashboard_served_without_token(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn(b"<title>", body)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        status, _, _ = self.request("GET", "/dashboard.html")
        self.assertEqual(status, 200)

    def test_static_origin_gated(self):
        status, _, _ = self.request("GET", "/", origin="http://evil.example")
        self.assertEqual(status, 403)

    def test_non_ui_paths_return_404(self):
        for path in ("/server.py", "/schema.sql", "/collector.py", "/claude-obs.db",
                     "/claude-obs.db-wal", "/../server.py", "/."):
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404, f"{path} must not be served")

    # --- HEAD ---------------------------------------------------------------
    def test_head_is_gated(self):
        status, _, body = self.request("HEAD", "/api/sessions")
        self.assertEqual(status, 401)
        self.assertEqual(body, b"")
        status, _, _ = self.request("HEAD", "/server.py")
        self.assertEqual(status, 404)
        status, headers, body = self.request("HEAD", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    # --- SRV-IDLE: a never-speaking connection must not stall the listener -----
    def test_idle_socket_blocks_single_threaded_server_negative_control(self):
        # NEGATIVE CONTROL: a plain single-threaded HTTPServer (the type shipped at
        # the input SHA) serializes connections — an accepted socket that sends no
        # request blocks a concurrent GET until it closes. This reproduces the defect
        # and proves the threaded-server regression below actually discriminates.
        from http.server import HTTPServer
        accepted = threading.Event()
        baseline = HTTPServer(("127.0.0.1", 0), _IdleSignalingHandler)
        baseline.auth_token = self.TOKEN
        baseline.db_path = str(self.db)
        baseline.accepted_event = accepted
        # The probe's GET is deliberately abandoned; the server may try to answer it
        # after the client has given up, writing to a closed socket. Silence that
        # expected teardown error so it does not print a spurious traceback.
        baseline.handle_error = lambda request, client_address: None
        bport = baseline.server_address[1]
        bthread = threading.Thread(target=baseline.serve_forever, daemon=True)
        bthread.start()

        idle = None
        try:
            idle = socket.create_connection(("127.0.0.1", bport), timeout=5)
            self.assertTrue(accepted.wait(5),
                            "idle connection must be accepted into the single worker")
            blocked = get_status(bport, "/", timeout=1.5, host=f"127.0.0.1:{bport}")
            self.assertIsNone(
                blocked,
                "single-threaded HTTPServer must block a GET while an idle socket is open",
            )
        finally:
            if idle is not None:
                idle.close()  # release the blocked handler so serve_forever can stop
            baseline.shutdown()  # safe only after the idle socket is closed
            baseline.server_close()
            bthread.join(timeout=5)

    def test_idle_socket_does_not_block_threaded_server(self):
        # build_server() returns a ThreadingHTTPServer (self.httpd). With an idle,
        # never-speaking connection held open, concurrent requests must still
        # complete: a static asset (200), a token-bearing API call (200), a second
        # token-bearing API call (200 — exercises the per-request read-only SQLite
        # connections across threads with no shared-handle error), and a token-less
        # API call (401 — auth stays gated). On the single-threaded server every one
        # of these would time out to None.
        self.assertIsInstance(self.httpd, server.ThreadingHTTPServer)
        idle = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        results = {}

        def probe(key, path, auth):
            results[key] = get_status(
                self.port, path, timeout=5, host=f"127.0.0.1:{self.port}", auth=auth
            )

        threads = [
            threading.Thread(target=probe, args=("asset", "/", None)),
            threading.Thread(target=probe, args=("api_ok", "/api/sessions?days=0", self.TOKEN)),
            threading.Thread(target=probe, args=("api_ok2", "/api/summary?days=0", self.TOKEN)),
            threading.Thread(target=probe, args=("api_noauth", "/api/sessions?days=0", None)),
        ]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            self.assertFalse(
                any(t.is_alive() for t in threads),
                "requests must complete concurrently, not block on the idle socket",
            )
            # The idle socket is STILL open here — assert that before releasing it.
            self.assertEqual(idle.getpeername()[0], "127.0.0.1",
                             "idle connection must remain open throughout")
            self.assertEqual(results["asset"], 200)
            self.assertEqual(results["api_ok"], 200)
            self.assertEqual(results["api_ok2"], 200)
            self.assertEqual(results["api_noauth"], 401, "auth stays gated under concurrency")
        finally:
            idle.close()

    # --- SRV-PORT: an oversized all-digit port is a clean 403, not a crash -----
    def test_oversized_port_host_is_rejected_not_crash(self):
        # A Host authority whose port is thousands of ASCII digits long tripped an
        # uncaught int-conversion ValueError that aborted the connection
        # (RemoteDisconnected) instead of answering. It must now be a clean 403 for
        # both GET and HEAD — no 500, no dropped connection.
        oversized = "127.0.0.1:" + ("5" * 5000)
        for method in ("GET", "HEAD"):
            status, _, _ = self.request(method, "/", host=oversized)
            self.assertEqual(status, 403, f"{method} with an oversized port must be a clean 403")
        # Recovery: a valid Host on a fresh request still works — the server survived.
        status, _, _ = self.request("GET", "/", host=f"127.0.0.1:{self.port}")
        self.assertEqual(status, 200, "server must keep serving after the oversized-port request")

    def test_parse_port_rejects_oversized_and_preserves_grammar(self):
        # The fix: an oversized all-digit run returns None instead of raising.
        self.assertIsNone(server._parse_port("5" * 5000))
        self.assertIsNone(server._parse_port("9" * 100), "huge but under the digit limit: out of range")
        # Grammar and range are otherwise unchanged (the shipped HTTP controls stay valid).
        self.assertEqual(server._parse_port("0"), 0)
        self.assertEqual(server._parse_port("80"), 80)
        self.assertEqual(server._parse_port("65535"), 65535)   # max valid port
        self.assertEqual(server._parse_port("00080"), 80)      # leading zeros preserved
        self.assertIsNone(server._parse_port("65536"))         # one past the range
        self.assertIsNone(server._parse_port("99999"))         # five digits, out of range
        self.assertIsNone(server._parse_port(""))
        self.assertIsNone(server._parse_port("-1"))
        self.assertIsNone(server._parse_port("8o80"))

    # --- launch URL / port 0 ------------------------------------------------
    def test_port_zero_reports_real_port(self):
        self.assertGreater(self.port, 0)

    def test_launch_url_carries_token_in_fragment(self):
        url = server.format_launch_url("127.0.0.1", self.port, self.TOKEN)
        self.assertEqual(url, f"http://127.0.0.1:{self.port}/#token={self.TOKEN}")
        self.assertNotIn("?token=", url, "token must never be a query param")


# ---------------------------------------------------------------------------
# OBS-IR04 — dashboard auth bootstrap must not depend on the Chart.js CDN
# ---------------------------------------------------------------------------

@unittest.skipIf(NODE is None, "node is required to evaluate the dashboard bootstrap")
class DashboardBootstrapTest(unittest.TestCase):
    """Evaluate the committed inline-script prefix in a Node VM (no browser/network).

    The real risk: if the token capture / fragment cleanup sat after Chart.js
    initialization, a blocked or offline CDN (no Chart global) would throw before the
    capability was removed from the URL/history. These cases prove the bootstrap runs
    first and is independent of Chart availability and of sessionStorage access.
    """

    BOOTSTRAP_JS = r"""
const vm = require('vm');
const source = JSON.parse(process.argv[1]);
const results = [];
for (const scenario of ['chart-absent', 'chart-present', 'storage-blocked']) {
  let replaced = false;
  const storage = {};
  const context = {
    window: { location: { hash: '#token=SYNTHETIC_TOKEN', pathname: '/', search: '' } },
    history: { replaceState: () => { replaced = true; } },
    sessionStorage: {
      setItem: (k, v) => { if (scenario === 'storage-blocked') throw new Error('blocked'); storage[k] = v; },
      getItem: () => null,
    },
  };
  if (scenario === 'chart-present') context.Chart = { defaults: { font: {} } };
  let error = null;
  try { vm.runInNewContext(source, context); } catch (e) { error = e.name; }
  results.push({ scenario, error, fragmentRemoved: replaced, tokenStored: storage['claude-obs-token'] === 'SYNTHETIC_TOKEN' });
}
process.stdout.write(JSON.stringify(results));
"""

    def _bootstrap(self):
        html = (OBS_DIR / "dashboard.html").read_text(encoding="utf-8")
        prefix = html.split("<script>")[1].split("// API helpers.")[0]
        proc = subprocess.run(
            [NODE, "-e", self.BOOTSTRAP_JS, json.dumps(prefix)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return {r["scenario"]: r for r in json.loads(proc.stdout)}

    def test_fragment_cleanup_independent_of_chart_cdn(self):
        results = self._bootstrap()

        # CDN blocked/offline (no Chart): bootstrap must still run — no throw, the
        # fragment is removed and the token captured. This is the OBS-IR04 fix.
        absent = results["chart-absent"]
        self.assertIsNone(absent["error"], "auth bootstrap must not throw when Chart.js is absent")
        self.assertTrue(absent["fragmentRemoved"], "fragment must be cleaned without Chart.js")
        self.assertTrue(absent["tokenStored"])

        # Chart present: unchanged capture behavior.
        present = results["chart-present"]
        self.assertTrue(present["fragmentRemoved"])
        self.assertTrue(present["tokenStored"])

        # sessionStorage blocked: the fragment is still cleaned (storage write is
        # best-effort and swallowed), so the capability never lingers in history.
        self.assertTrue(results["storage-blocked"]["fragmentRemoved"])


if __name__ == "__main__":
    unittest.main()
