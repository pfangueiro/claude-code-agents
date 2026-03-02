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

import json
import os
import sqlite3
import sys
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.expanduser("~/.claude/analytics/claude-obs.db")
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))


def get_db():
    """Open a read-only SQLite connection."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_dicts(rows):
    """Convert sqlite3.Row objects to plain dicts."""
    return [dict(row) for row in rows]


_ALLOWED_COLUMNS = frozenset({
    "timestamp", "started_at", "a.timestamp", "s.started_at",
})


def day_filter_clause(column, days):
    """Return a SQL WHERE clause for day-range filtering."""
    if column not in _ALLOWED_COLUMNS:
        raise ValueError(f"Disallowed column: {column}")
    if days <= 0:
        return ""
    return f" AND {column} >= datetime('now', '-{int(days)} days') "


def parse_int_param(params, name, default):
    """Safely parse an integer query parameter, returning default on bad input."""
    try:
        return int(params.get(name, [str(default)])[0])
    except (ValueError, IndexError):
        return default


# ---------------------------------------------------------------------------
# API endpoint handlers
# ---------------------------------------------------------------------------

def api_summary(params):
    days = parse_int_param(params, "days", 14)
    conn = get_db()
    try:
        dfc = day_filter_clause("timestamp", days)

        total_cost = conn.execute(
            f"SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM api_calls WHERE 1=1 {dfc}"
        ).fetchone()[0]

        total_input = conn.execute(
            f"SELECT COALESCE(SUM(input_tokens + cache_read_tokens + cache_creation_tokens), 0) FROM api_calls WHERE 1=1 {dfc}"
        ).fetchone()[0]

        total_output = conn.execute(
            f"SELECT COALESCE(SUM(output_tokens), 0) FROM api_calls WHERE 1=1 {dfc}"
        ).fetchone()[0]

        session_dfc = day_filter_clause("started_at", days)
        session_count = conn.execute(
            f"SELECT COUNT(*) FROM sessions WHERE 1=1 {session_dfc}"
        ).fetchone()[0]

        project_count = conn.execute(
            f"SELECT COUNT(DISTINCT project) FROM sessions WHERE 1=1 {session_dfc}"
        ).fetchone()[0]

        agent_dfc = day_filter_clause("timestamp", days)
        agent_count = conn.execute(
            f"SELECT COUNT(*) FROM agent_activations WHERE 1=1 {agent_dfc}"
        ).fetchone()[0]

        return {
            "total_cost": round(total_cost, 2),
            "session_count": session_count,
            "project_count": project_count,
            "agent_count": agent_count,
            "input_tokens": total_input,
            "output_tokens": total_output,
        }
    finally:
        conn.close()


def api_daily(params):
    days = parse_int_param(params, "days", 14)
    conn = get_db()
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


def api_projects(params):
    days = parse_int_param(params, "days", 14)
    conn = get_db()
    try:
        dfc = day_filter_clause("a.timestamp", days)

        rows = conn.execute(f"""
            SELECT
                a.project,
                ROUND(SUM(a.estimated_cost_usd), 4) as cost,
                COUNT(DISTINCT a.session_id) as sessions,
                MAX(a.timestamp) as last_active,
                SUM(a.input_tokens + a.output_tokens + a.cache_read_tokens + a.cache_creation_tokens) as total_tokens
            FROM api_calls a
            WHERE 1=1 {dfc}
            GROUP BY a.project
            ORDER BY cost DESC
        """).fetchall()

        # Add top agent per project
        results = []
        for row in rows:
            d = dict(row)
            agent_dfc = day_filter_clause("timestamp", days)
            top_agent = conn.execute(f"""
                SELECT agent_name, COUNT(*) as cnt
                FROM agent_activations
                WHERE project = ? {agent_dfc}
                GROUP BY agent_name
                ORDER BY cnt DESC
                LIMIT 1
            """, (d["project"],)).fetchone()

            d["top_agent"] = dict(top_agent)["agent_name"] if top_agent else None
            results.append(d)

        return results
    finally:
        conn.close()


def api_agents(params):
    days = parse_int_param(params, "days", 14)
    conn = get_db()
    try:
        dfc = day_filter_clause("timestamp", days)

        rows = conn.execute(f"""
            SELECT
                agent_name,
                COUNT(*) as activation_count,
                COUNT(DISTINCT project) as projects_used_in
            FROM agent_activations
            WHERE 1=1 {dfc}
            GROUP BY agent_name
            ORDER BY activation_count DESC
        """).fetchall()

        return rows_to_dicts(rows)
    finally:
        conn.close()


def api_models(params):
    days = parse_int_param(params, "days", 14)
    conn = get_db()
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

        total_cost = sum(dict(r)["cost"] for r in rows) or 1
        results = []
        for row in rows:
            d = dict(row)
            d["pct"] = round(d["cost"] / total_cost * 100, 1)
            results.append(d)

        return results
    finally:
        conn.close()


def api_sessions(params):
    days = parse_int_param(params, "days", 14)
    limit = max(0, min(parse_int_param(params, "limit", 50), 1000))
    project_filter = params.get("project", [""])[0]
    conn = get_db()
    try:
        dfc = day_filter_clause("s.started_at", days)
        project_clause = ""
        query_params = []

        if project_filter:
            project_clause = " AND s.project = ? "
            query_params.append(project_filter)

        query_params.append(limit)

        rows = conn.execute(f"""
            SELECT
                s.session_id,
                s.project,
                s.started_at,
                s.duration_ms,
                s.total_turns,
                s.claude_version,
                COALESCE((SELECT ROUND(SUM(estimated_cost_usd), 4) FROM api_calls WHERE session_id = s.session_id), 0) as cost,
                COALESCE((SELECT model FROM api_calls WHERE session_id = s.session_id ORDER BY timestamp DESC LIMIT 1), '') as model
            FROM sessions s
            WHERE 1=1 {dfc} {project_clause}
            ORDER BY s.started_at DESC
            LIMIT ?
        """, query_params).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            # Get agents used in this session
            agents = conn.execute(
                "SELECT DISTINCT agent_name FROM agent_activations WHERE session_id = ?",
                (d["session_id"],),
            ).fetchall()
            d["agents"] = [dict(a)["agent_name"] for a in agents]
            results.append(d)

        return results
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
}


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves the dashboard and JSON API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DASHBOARD_DIR, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Serve dashboard at root
        if path == "/" or path == "":
            self.path = "/dashboard.html"
            return super().do_GET()

        # API routes
        if path in API_ROUTES:
            params = parse_qs(parsed.query)
            try:
                result = API_ROUTES[path](params)
                self.send_json(200, result)
            except Exception as e:
                self.send_json(500, {"error": str(e)})
            return

        # Static files
        return super().do_GET()

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress request logging for cleaner output
        pass


def main():
    port = 3141
    auto_open = False
    global DB_PATH

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
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

    url = f"http://localhost:{port}"
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)

    print(f"Claude Code Observability Dashboard")
    print(f"  URL:      {url}")
    print(f"  Database: {DB_PATH}")
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
