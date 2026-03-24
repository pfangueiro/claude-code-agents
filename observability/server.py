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
import time
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.expanduser("~/.claude/analytics/claude-obs.db")
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))

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


def get_db():
    """Open a read-only SQLite connection with performance pragmas."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
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

def api_summary(params):
    days = parse_int_param(params, "days", 14)
    cache_key = f"summary:{days}"

    def compute():
        conn = get_db()
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


def api_daily(params):
    days = parse_int_param(params, "days", 14)
    cache_key = f"daily:{days}"

    def compute():
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

    return _cached(cache_key, compute)


def api_projects(params):
    days = parse_int_param(params, "days", 14)
    cache_key = f"projects:{days}"

    def compute():
        conn = get_db()
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


def api_agents(params):
    days = parse_int_param(params, "days", 14)
    cache_key = f"agents:{days}"

    def compute():
        conn = get_db()
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


def api_models(params):
    days = parse_int_param(params, "days", 14)
    cache_key = f"models:{days}"

    def compute():
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


def api_sessions(params):
    days = parse_int_param(params, "days", 14)
    limit = max(1, min(parse_int_param(params, "limit", 25), 1000))
    offset = max(0, parse_int_param(params, "offset", 0))
    project_filter = params.get("project", [""])[0]
    search = params.get("search", [""])[0]
    conn = get_db()
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


def api_tools(params):
    """Top tools by usage count."""
    days = parse_int_param(params, "days", 14)
    cache_key = f"tools:{days}"

    def compute():
        conn = get_db()
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


def api_hooks(params):
    """Hook event counts by type."""
    days = parse_int_param(params, "days", 14)
    cache_key = f"hooks:{days}"

    def compute():
        conn = get_db()
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


def api_session_detail(params):
    """Full detail for a single session."""
    session_id = params.get("session_id", [""])[0]
    if not session_id:
        return {"error": "session_id required"}

    conn = get_db()
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
                self.send_json(500, {"error": "Query failed"})
                print(f"API error on {path}: {e}", file=sys.stderr)
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

    url = f"http://localhost:{port}"
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)

    print(f"Claude Code Observability Dashboard")
    print(f"  URL:      {url}")
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
