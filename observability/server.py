#!/usr/bin/env python3
"""
Claude Code Observability - Dashboard Server

Serves the dashboard UI and JSON API from a local SQLite database.

Usage:
    python3 server.py                    # Serve on localhost:3141
    python3 server.py --port 8080        # Custom port
    python3 server.py --open             # Auto-open browser
    python3 server.py --db /path/to.db   # Custom DB path
"""

import hmac
import json
import os
import secrets
import sqlite3
import sys
import time
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.expanduser("~/.claude/analytics/claude-obs.db")
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))

# Hostnames that identify this loopback server. Requests whose Origin or Host
# names anything else are rejected (defends the local API against DNS-rebinding
# and foreign-origin browser reads). The server only ever binds 127.0.0.1.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# The only files served over HTTP. Everything else — the SQLite DB, its -wal/-shm
# sidecars, the raw JSONL event logs, server.py/schema.sql, and directory listings —
# returns 404 even to an authenticated client. Replaces the old directory-wide
# SimpleHTTPRequestHandler fallback that exposed the whole analytics directory.
UI_ASSETS = {
    "/": "dashboard.html",
    "/dashboard.html": "dashboard.html",
}

# Simple TTL cache (30 seconds)
_cache = {}
_CACHE_TTL = 30


def _cached(key, fn):
    """Return cached result or compute and cache."""
    now = time.time()
    if key in _cache and now - _cache[key][0] < _CACHE_TTL:
        return _cache[key][1]
    result = fn()
    _cache[key] = (now, result)
    return result


def get_db(db_path):
    """Open a read-only SQLite connection with performance pragmas."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def rows_to_dicts(rows):
    """Convert sqlite3.Row objects to plain dicts."""
    return [dict(row) for row in rows]


_ALLOWED_COLUMNS = frozenset({
    "timestamp", "started_at", "a.timestamp", "s.started_at",
    "d.date", "he.timestamp", "ag.timestamp",
})


def day_filter_clause(column, days):
    """Return a SQL WHERE clause for day-range filtering."""
    if column not in _ALLOWED_COLUMNS:
        raise ValueError(f"Disallowed column: {column}")
    days = max(0, min(int(days), 3650))  # Clamp to 10 years max
    if days <= 0:
        return ""
    return f" AND {column} >= datetime('now', '-{days} days') "


def parse_int_param(params, name, default):
    """Safely parse an integer query parameter, returning default on bad input."""
    try:
        return int(params.get(name, [str(default)])[0])
    except (ValueError, IndexError):
        return default


# ---------------------------------------------------------------------------
# API endpoint handlers
# ---------------------------------------------------------------------------

def api_summary(params, db_path):
    days = parse_int_param(params, "days", 14)
    cache_key = f"{db_path}|summary:{days}"

    def compute():
        conn = get_db(db_path)
        try:
            dfc = day_filter_clause("timestamp", days)

            row = conn.execute(f"""
                SELECT
                    COALESCE(SUM(estimated_cost_usd), 0) as total_cost,
                    COALESCE(SUM(input_tokens), 0) as total_input,
                    COALESCE(SUM(output_tokens), 0) as total_output,
                    COALESCE(SUM(cache_read_tokens), 0) as total_cache_read,
                    COALESCE(SUM(cache_creation_tokens), 0) as total_cache_create
                FROM api_calls WHERE 1=1 {dfc}
            """).fetchone()

            total_cost = row["total_cost"]
            total_input = row["total_input"] + row["total_cache_read"] + row["total_cache_create"]
            total_output = row["total_output"]
            total_cache_read = row["total_cache_read"]

            session_dfc = day_filter_clause("started_at", days)
            s_row = conn.execute(f"""
                SELECT COUNT(*) as cnt, COUNT(DISTINCT project) as proj_cnt
                FROM sessions WHERE 1=1 {session_dfc}
            """).fetchone()

            agent_dfc = day_filter_clause("timestamp", days)
            agent_count = conn.execute(
                f"SELECT COUNT(*) FROM agent_activations WHERE 1=1 {agent_dfc}"
            ).fetchone()[0]

            # Cache efficiency
            cache_efficiency = 0
            if total_input > 0:
                cache_efficiency = round(total_cache_read / total_input * 100, 1)

            # Cost per 1K tokens
            total_all_tokens = total_input + total_output
            cost_per_1k = round(total_cost / (total_all_tokens / 1000), 4) if total_all_tokens > 0 else 0

            # Previous period comparison for trends
            prev_cost = 0
            prev_sessions = 0
            prev_agents = 0
            if days > 0:
                prev_clause = f"AND timestamp >= datetime('now', '-{days * 2} days') AND timestamp < datetime('now', '-{days} days')"
                prev_cost = conn.execute(
                    f"SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM api_calls WHERE 1=1 {prev_clause}"
                ).fetchone()[0]
                prev_s_clause = f"AND started_at >= datetime('now', '-{days * 2} days') AND started_at < datetime('now', '-{days} days')"
                prev_sessions = conn.execute(
                    f"SELECT COUNT(*) FROM sessions WHERE 1=1 {prev_s_clause}"
                ).fetchone()[0]
                prev_a_clause = f"AND timestamp >= datetime('now', '-{days * 2} days') AND timestamp < datetime('now', '-{days} days')"
                prev_agents = conn.execute(
                    f"SELECT COUNT(*) FROM agent_activations WHERE 1=1 {prev_a_clause}"
                ).fetchone()[0]

            def trend_pct(current, previous):
                if previous == 0:
                    return None
                return round((current - previous) / previous * 100, 1)

            return {
                "total_cost": round(total_cost, 2),
                "session_count": s_row["cnt"],
                "project_count": s_row["proj_cnt"],
                "agent_count": agent_count,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cache_read_tokens": total_cache_read,
                "cache_efficiency": cache_efficiency,
                "cost_per_1k": cost_per_1k,
                "trends": {
                    "cost": trend_pct(total_cost, prev_cost),
                    "sessions": trend_pct(s_row["cnt"], prev_sessions),
                    "agents": trend_pct(agent_count, prev_agents),
                },
            }
        finally:
            conn.close()

    return _cached(cache_key, compute)


def api_daily(params, db_path):
    days = parse_int_param(params, "days", 14)
    cache_key = f"{db_path}|daily:{days}"

    def compute():
        conn = get_db(db_path)
        try:
            dfc = day_filter_clause("timestamp", days)
            rows = conn.execute(f"""
                SELECT
                    DATE(timestamp) as date,
                    ROUND(SUM(estimated_cost_usd), 4) as cost,
                    SUM(input_tokens + cache_read_tokens + cache_creation_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    COUNT(DISTINCT session_id) as sessions
                FROM api_calls
                WHERE 1=1 {dfc}
                GROUP BY DATE(timestamp)
                ORDER BY date
            """).fetchall()
            return rows_to_dicts(rows)
        finally:
            conn.close()

    return _cached(cache_key, compute)


def api_projects(params, db_path):
    days = parse_int_param(params, "days", 14)
    cache_key = f"{db_path}|projects:{days}"

    def compute():
        conn = get_db(db_path)
        try:
            dfc = day_filter_clause("a.timestamp", days)
            # Single query with LEFT JOIN for top agent — eliminates N+1
            rows = conn.execute(f"""
                SELECT
                    a.project,
                    ROUND(SUM(a.estimated_cost_usd), 4) as cost,
                    COUNT(DISTINCT a.session_id) as sessions,
                    MAX(a.timestamp) as last_active,
                    SUM(a.input_tokens + a.output_tokens + a.cache_read_tokens + a.cache_creation_tokens) as total_tokens,
                    (SELECT ag.agent_name FROM agent_activations ag
                     WHERE ag.project = a.project {day_filter_clause("ag.timestamp", days)}
                     GROUP BY ag.agent_name ORDER BY COUNT(*) DESC LIMIT 1) as top_agent
                FROM api_calls a
                WHERE 1=1 {dfc}
                GROUP BY a.project
                ORDER BY cost DESC
            """).fetchall()
            return rows_to_dicts(rows)
        finally:
            conn.close()

    return _cached(cache_key, compute)


def api_agents(params, db_path):
    days = parse_int_param(params, "days", 14)
    cache_key = f"{db_path}|agents:{days}"

    def compute():
        conn = get_db(db_path)
        try:
            dfc = day_filter_clause("timestamp", days)
            rows = conn.execute(f"""
                SELECT
                    agent_name,
                    COUNT(*) as activation_count,
                    COUNT(DISTINCT project) as projects_used_in,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status != 'completed' THEN 1 ELSE 0 END) as failed,
                    ROUND(AVG(duration_ms), 0) as avg_duration_ms
                FROM agent_activations
                WHERE 1=1 {dfc}
                GROUP BY agent_name
                ORDER BY activation_count DESC
            """).fetchall()
            return rows_to_dicts(rows)
        finally:
            conn.close()

    return _cached(cache_key, compute)


def api_models(params, db_path):
    days = parse_int_param(params, "days", 14)
    cache_key = f"{db_path}|models:{days}"

    def compute():
        conn = get_db(db_path)
        try:
            dfc = day_filter_clause("timestamp", days)
            rows = conn.execute(f"""
                SELECT
                    model,
                    COUNT(*) as call_count,
                    ROUND(SUM(estimated_cost_usd), 4) as cost,
                    SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) as token_count
                FROM api_calls
                WHERE model != '<synthetic>' AND 1=1 {dfc}
                GROUP BY model
                ORDER BY cost DESC
            """).fetchall()

            total_cost = sum((dict(r)["cost"] or 0) for r in rows) or 1
            results = []
            for row in rows:
                d = dict(row)
                d["pct"] = round(d["cost"] / total_cost * 100, 1)
                results.append(d)
            return results
        finally:
            conn.close()

    return _cached(cache_key, compute)


def api_sessions(params, db_path):
    days = parse_int_param(params, "days", 14)
    limit = max(1, min(parse_int_param(params, "limit", 25), 1000))
    offset = max(0, parse_int_param(params, "offset", 0))
    project_filter = params.get("project", [""])[0]
    search = params.get("search", [""])[0]
    conn = get_db(db_path)
    try:
        dfc = day_filter_clause("s.started_at", days)
        clauses = []
        query_params = []

        if project_filter:
            clauses.append("s.project = ?")
            query_params.append(project_filter)

        if search:
            clauses.append("s.project LIKE ?")
            query_params.append(f"%{search}%")

        where_extra = (" AND " + " AND ".join(clauses)) if clauses else ""

        # Single query with JOINs — eliminates N+1
        rows = conn.execute(f"""
            SELECT
                s.session_id,
                s.project,
                s.started_at,
                s.duration_ms,
                s.total_turns,
                s.claude_version,
                s.git_branch,
                COALESCE(ac.cost, 0) as cost,
                COALESCE(ac.model, '') as model,
                COALESCE(ag.agents, '') as agents
            FROM sessions s
            LEFT JOIN (
                SELECT session_id,
                    ROUND(SUM(estimated_cost_usd), 4) as cost,
                    MAX(model) as model
                FROM api_calls GROUP BY session_id
            ) ac ON ac.session_id = s.session_id
            LEFT JOIN (
                SELECT session_id, GROUP_CONCAT(DISTINCT agent_name) as agents
                FROM agent_activations GROUP BY session_id
            ) ag ON ag.session_id = s.session_id
            WHERE 1=1 {dfc} {where_extra}
            ORDER BY s.started_at DESC
            LIMIT ? OFFSET ?
        """, query_params + [limit, offset]).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            d["agents"] = d["agents"].split(",") if d["agents"] else []
            results.append(d)
        return results
    finally:
        conn.close()


def api_tools(params, db_path):
    """Top tools by usage count."""
    days = parse_int_param(params, "days", 14)
    cache_key = f"{db_path}|tools:{days}"

    def compute():
        conn = get_db(db_path)
        try:
            dfc = day_filter_clause("timestamp", days)
            rows = conn.execute(f"""
                SELECT
                    tool_name,
                    SUM(call_count) as total_calls,
                    COUNT(DISTINCT session_id) as sessions
                FROM tool_usage
                WHERE 1=1 {dfc}
                GROUP BY tool_name
                ORDER BY total_calls DESC
                LIMIT 20
            """).fetchall()
            return rows_to_dicts(rows)
        finally:
            conn.close()

    return _cached(cache_key, compute)


def api_hooks(params, db_path):
    """Hook event counts by type."""
    days = parse_int_param(params, "days", 14)
    cache_key = f"{db_path}|hooks:{days}"

    def compute():
        conn = get_db(db_path)
        try:
            dfc = day_filter_clause("he.timestamp", days)
            rows = conn.execute(f"""
                SELECT
                    event_type,
                    COUNT(*) as count,
                    MAX(timestamp) as latest
                FROM hook_events he
                WHERE 1=1 {dfc}
                GROUP BY event_type
                ORDER BY count DESC
            """).fetchall()
            return rows_to_dicts(rows)
        finally:
            conn.close()

    return _cached(cache_key, compute)


def api_session_detail(params, db_path):
    """Full detail for a single session."""
    session_id = params.get("session_id", [""])[0]
    if not session_id:
        return {"error": "session_id required"}

    conn = get_db(db_path)
    try:
        # Session metadata
        session = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not session:
            return {"error": "Session not found"}

        result = dict(session)

        # Cost by model
        models = conn.execute("""
            SELECT model, COUNT(*) as calls,
                ROUND(SUM(estimated_cost_usd), 4) as cost,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cache_read_tokens) as cache_read_tokens
            FROM api_calls WHERE session_id = ?
            GROUP BY model ORDER BY cost DESC
        """, (session_id,)).fetchall()
        result["models"] = rows_to_dicts(models)

        # Agents used
        agents = conn.execute("""
            SELECT agent_name, description, status, duration_ms, timestamp
            FROM agent_activations WHERE session_id = ?
            ORDER BY timestamp
        """, (session_id,)).fetchall()
        result["agents"] = rows_to_dicts(agents)

        # Tools used
        tools = conn.execute("""
            SELECT tool_name, call_count
            FROM tool_usage WHERE session_id = ?
            ORDER BY call_count DESC
        """, (session_id,)).fetchall()
        result["tools"] = rows_to_dicts(tools)

        # Total cost
        cost_row = conn.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM api_calls WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        result["total_cost"] = round(cost_row[0], 4)

        return result
    finally:
        conn.close()


# Route map
API_ROUTES = {
    "/api/summary": api_summary,
    "/api/daily": api_daily,
    "/api/projects": api_projects,
    "/api/agents": api_agents,
    "/api/models": api_models,
    "/api/sessions": api_sessions,
    "/api/tools": api_tools,
    "/api/hooks": api_hooks,
    "/api/session-detail": api_session_detail,
}


def _parse_port(text):
    """Return the integer port for an ASCII-decimal ``text`` in range, else None.

    Only bytes ``0-9`` are accepted, so ``str.isdigit`` false-positives (Unicode
    superscripts, full-width digits that ``int`` would still parse) cannot slip a
    bogus port through. Empty, signed or out-of-range strings return None.
    """
    if not text or not all(c in "0123456789" for c in text):
        return None
    try:
        port = int(text)
    except ValueError:
        # An all-digit run thousands of characters long trips CPython's
        # int-string conversion digit limit (ValueError on 3.11+). A real port
        # is at most five digits, so such input is never a valid port: reject it
        # here instead of letting the exception escape parse_host_authority and
        # abort the request before the Host/Origin check can answer 403.
        return None
    return port if 0 <= port <= 65535 else None


def parse_host_authority(value):
    """Parse a Host-header authority into ``(hostname_lower, port_or_None)``.

    Returns None for anything that is not a clean ``host`` or ``host:port`` (or the
    bracketed ``[ipv6]`` / ``[ipv6]:port`` form): userinfo, a path/garbage suffix, a
    missing/non-numeric/out-of-range port, an unterminated or trailing-garbage IPv6
    bracket, or embedded whitespace/slashes. This is the narrow authority grammar
    this loopback server accepts, not a general URL parser.
    """
    if value is None:
        return None
    value = value.strip()
    if not value or "@" in value:  # userinfo is never valid in a Host header
        return None
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None  # unterminated IPv6 literal
        hostname = value[1:end]
        rest = value[end + 1:]
        if rest == "":
            port = None
        elif rest.startswith(":"):
            port = _parse_port(rest[1:])
            if port is None:
                return None
        else:
            return None  # garbage after the bracket, e.g. [::1]evil.invalid
    elif value.count(":") > 1:
        return None  # a bare (unbracketed) IPv6 authority is not accepted here
    elif ":" in value:
        hostname, _, port_str = value.partition(":")
        port = _parse_port(port_str)
        if port is None:
            return None
    else:
        hostname = value
        port = None
    if not hostname or "/" in hostname or any(c.isspace() for c in hostname):
        return None
    return hostname.lower(), port


class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the dashboard UI and JSON API for a single loopback client.

    Security boundary:
      - Origin/Host must name this loopback server (rejects foreign-origin browser
        reads and DNS-rebinding), checked on every GET/HEAD including static assets.
      - /api/* requires the per-launch capability token in an Authorization header;
        there is no no-auth default. The token is never written to logs.
      - Only the assets in UI_ASSETS are served; everything else returns 404, so the
        colocated SQLite DB and raw JSONL logs are not reachable over HTTP.
    """

    server_version = "ClaudeObs/1.0"

    # Bounded per-connection read timeout. With ThreadingHTTPServer each
    # connection runs in its own (daemon) thread, so a client that opens a
    # socket and never sends a request no longer blocks other clients — but it
    # would otherwise hold that thread and its fd for the server's whole life.
    # This timeout reclaims an idle/half-open connection: the handler's socket
    # read raises socket.timeout, which BaseHTTPRequestHandler turns into a
    # clean connection close. It is comfortably above any real dashboard
    # request, so legitimate requests and keep-alive polling are unaffected.
    timeout = 30

    def _bound_port(self):
        """The real TCP port this server is listening on (resolved even for --port 0)."""
        return self.server.server_address[1]

    def _port_ok(self, port):
        """True when an authority port matches the bound port.

        A missing port is only the implicit ``http`` default (80); this loopback
        dashboard never runs there by default, so an omitted port is accepted only
        if the server genuinely bound 80.
        """
        if port is None:
            return self._bound_port() == 80
        return port == self._bound_port()

    def _host_allowed(self):
        """Require an explicit, well-formed loopback Host authority at the bound port.

        Rejects duplicate Host headers, foreign/garbage authorities, wrong ports and
        malformed IPv6 suffixes. A missing Host is tolerated only for HTTP/1.0, which
        predates the required header; HTTP/1.1 must send one.
        """
        hosts = self.headers.get_all("Host") or []
        if len(hosts) > 1:
            return False  # ambiguous/smuggled duplicate Host — reject
        if not hosts:
            return self.request_version == "HTTP/1.0"
        parsed = parse_host_authority(hosts[0])
        if parsed is None:
            return False
        hostname, port = parsed
        return hostname in LOOPBACK_HOSTS and self._port_ok(port)

    def _accepted_origins(self):
        """Exact Origin strings this server accepts: http + loopback alias + bound port.

        Building the small exact set (rather than parsing) means wrong scheme, wrong
        port, userinfo, a path/query/fragment or any trailing garbage all fail by not
        matching — no permissive URL parsing to be fooled by.
        """
        port = self._bound_port()
        origins = {f"http://{h}:{port}" for h in ("localhost", "127.0.0.1", "[::1]")}
        if port == 80:
            origins.update(f"http://{h}" for h in ("localhost", "127.0.0.1", "[::1]"))
        return origins

    def _origin_allowed(self):
        origins = self.headers.get_all("Origin") or []
        if not origins:
            return True  # same-origin GET/HEAD frequently omit Origin
        if len(origins) > 1:
            return False  # duplicate Origin headers are never legitimate
        return origins[0].strip() in self._accepted_origins()

    def _token_valid(self):
        expected = getattr(self.server, "auth_token", None)
        if not expected:
            return False  # fail closed — never serve the API without a token
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return hmac.compare_digest(header[len(prefix):], expected)

    def do_GET(self):
        self._handle(include_body=True)

    def do_HEAD(self):
        self._handle(include_body=False)

    def _handle(self, include_body):
        if not self._host_allowed() or not self._origin_allowed():
            self.send_json(403, {"error": "Forbidden origin or host"}, include_body)
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path in API_ROUTES:
            if not self._token_valid():
                self.send_json(401, {"error": "Missing or invalid capability token"}, include_body)
                return
            params = parse_qs(parsed.query)
            db_path = getattr(self.server, "db_path", DB_PATH)
            try:
                result = API_ROUTES[path](params, db_path)
                self.send_json(200, result, include_body)
            except Exception as e:
                self.send_json(500, {"error": "Query failed"}, include_body)
                print(f"API error on {path}: {e}", file=sys.stderr)
            return

        asset = UI_ASSETS.get(path)
        if asset:
            self.serve_asset(asset, include_body)
            return

        self.send_json(404, {"error": "Not found"}, include_body)

    def serve_asset(self, filename, include_body):
        # filename comes only from the fixed UI_ASSETS allowlist, never from the
        # request path, so there is no traversal surface here.
        try:
            with open(os.path.join(DASHBOARD_DIR, filename), "rb") as fh:
                body = fh.read()
        except OSError:
            self.send_json(404, {"error": "Not found"}, include_body)
            return
        ctype = "text/html; charset=utf-8" if filename.endswith(".html") else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def send_json(self, status, data, include_body=True):
        # No Access-Control-Allow-Origin: responses are for the same-origin UI only.
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress request logging — keeps the capability token out of any log.
        pass


def build_server(host="127.0.0.1", port=3141, token=None, db_path=None):
    """Construct the dashboard HTTP server bound to a loopback address.

    ``token`` is the per-launch capability required on every API request; when not
    supplied a fresh high-entropy one is generated. Tests inject a known fixture
    token here (never via a CLI flag) so there is no unauthenticated path to ship.

    Uses the stdlib ``ThreadingHTTPServer`` (one daemon thread per connection) so a
    client that opens a socket without sending a request — browsers routinely
    pre-open connections — cannot stall every other request behind a single-threaded
    accept loop. The loopback bind, auth, Origin/Host and asset allowlist are
    unchanged; only request dispatch is now concurrent.
    """
    httpd = ThreadingHTTPServer((host, port), DashboardHandler)
    httpd.auth_token = token if token is not None else secrets.token_urlsafe(32)
    httpd.db_path = db_path if db_path is not None else DB_PATH
    return httpd


def format_launch_url(host, port, token):
    """Build the launch URL that carries the capability in the fragment (#token=…).

    The fragment is never sent in an HTTP request line or query string, so the token
    stays out of server access logs; the dashboard JS reads it from location.hash.
    """
    hostname = "127.0.0.1" if host in ("0.0.0.0", "", None) else host
    return f"http://{hostname}:{port}/#token={token}"


def main():
    port = 3141
    host = "127.0.0.1"
    auto_open = False
    global DB_PATH

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                print(f"Invalid port: {args[i + 1]}", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--open":
            auto_open = True
            i += 1
        elif args[i] == "--db" and i + 1 < len(args):
            DB_PATH = args[i + 1]
            i += 2
        elif args[i] in ("--help", "-h"):
            print(__doc__.strip())
            sys.exit(0)
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}", file=sys.stderr)
        print("Run collector.py first to ingest JSONL data.", file=sys.stderr)
        sys.exit(1)

    token = secrets.token_urlsafe(32)
    server = build_server(host, port, token=token, db_path=DB_PATH)
    actual_port = server.server_address[1]  # resolves the real port when --port 0
    url = format_launch_url(host, actual_port, token)

    print(f"Claude Code Observability Dashboard")
    print(f"  URL:      {url}")
    print(f"  (open the URL above — it carries a per-launch access token after '#', valid until this server stops)")
    print(f"  Database: {DB_PATH}")
    print(f"  Endpoints: {len(API_ROUTES)} API routes")
    print(f"  Cache TTL: {_CACHE_TTL}s")
    print(f"  Press Ctrl+C to stop\n")

    if auto_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
