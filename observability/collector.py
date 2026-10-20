#!/usr/bin/env python3
"""
Claude Code Observability - JSONL Collector

Scans ~/.claude/projects/**/*.jsonl and ingests session data into SQLite.
Incremental: tracks byte position per file, only processes new data on re-run.

Usage:
    python3 collector.py                  # Default: ~/.claude/analytics/claude-obs.db
    python3 collector.py --db /path/to.db # Custom DB path
    python3 collector.py --full           # Re-ingest everything (ignore watermarks)
"""

import json
import glob
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Cost model (USD per token)
# ---------------------------------------------------------------------------
MODEL_PRICES = {
    # --- Current models (per the claude-api model table, 2026) ---
    # Opus tier is $5/$25 input/output (Opus dropped from the old $15/$75).
    # cache_read = 0.1x input, cache_create = 1.25x input (5-min TTL).
    "claude-opus-4-8": {
        "input": 5e-6,
        "output": 25e-6,
        "cache_read": 0.5e-6,
        "cache_create": 6.25e-6,
    },
    "claude-opus-4-7": {
        "input": 5e-6,
        "output": 25e-6,
        "cache_read": 0.5e-6,
        "cache_create": 6.25e-6,
    },
    "claude-opus-4-6": {
        "input": 5e-6,
        "output": 25e-6,
        "cache_read": 0.5e-6,
        "cache_create": 6.25e-6,
    },
    # Sonnet 5 — $3/$15
    "claude-sonnet-5": {
        "input": 3e-6,
        "output": 15e-6,
        "cache_read": 0.3e-6,
        "cache_create": 3.75e-6,
    },
    # Fable 5 — $10/$50
    "claude-fable-5": {
        "input": 10e-6,
        "output": 50e-6,
        "cache_read": 1e-6,
        "cache_create": 12.5e-6,
    },
    # Sonnet 4.6 — $3/$15
    "claude-sonnet-4-6": {
        "input": 3e-6,
        "output": 15e-6,
        "cache_read": 0.3e-6,
        "cache_create": 3.75e-6,
    },
    # Haiku 4.5 — $1/$5 (alias + dated ID)
    "claude-haiku-4-5": {
        "input": 1e-6,
        "output": 5e-6,
        "cache_read": 0.1e-6,
        "cache_create": 1.25e-6,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1e-6,
        "output": 5e-6,
        "cache_read": 0.1e-6,
        "cache_create": 1.25e-6,
    },
    # Older model IDs (keep for backward compat with historical logs)
    "claude-sonnet-4-5-20250514": {
        "input": 3e-6,
        "output": 15e-6,
        "cache_read": 0.3e-6,
        "cache_create": 3.75e-6,
    },
    "claude-3-5-sonnet-20241022": {
        "input": 3e-6,
        "output": 15e-6,
        "cache_read": 0.3e-6,
        "cache_create": 3.75e-6,
    },
    "claude-sonnet-4-5-20250929": {
        "input": 3e-6,
        "output": 15e-6,
        "cache_read": 0.3e-6,
        "cache_create": 3.75e-6,
    },
    "claude-3-5-haiku-20241022": {
        "input": 0.8e-6,
        "output": 4e-6,
        "cache_read": 0.08e-6,
        "cache_create": 1e-6,
    },
}

# Fallback price for unknown models (use Sonnet pricing as default)
DEFAULT_PRICE = {
    "input": 3e-6,
    "output": 15e-6,
    "cache_read": 0.3e-6,
    "cache_create": 3.75e-6,
}


_warned_models = set()


def estimate_cost(model, usage):
    """Calculate estimated cost in USD for an API call."""
    if model and model not in MODEL_PRICES and model not in _warned_models:
        print(f"  WARNING: Unknown model '{model}', using Sonnet pricing", file=sys.stderr)
        _warned_models.add(model)
    prices = MODEL_PRICES.get(model, DEFAULT_PRICE)
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_create = usage.get("cache_creation_input_tokens", 0) or 0

    cost = (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
        + cache_read * prices["cache_read"]
        + cache_create * prices["cache_create"]
    )
    return round(cost, 8)


def project_from_cwd(cwd):
    """Extract project name from the working directory path (lowercase)."""
    if not cwd:
        return "unknown"
    return (os.path.basename(cwd.rstrip("/")) or "unknown").lower()


def build_slug_project_map(projects_dir):
    """Build a mapping from slug directory name to canonical project name.

    Each slug dir under ~/.claude/projects/ groups all sessions for one project.
    We read the first user record's cwd to get the real project name, then
    lowercase-normalize to avoid case-variant duplicates (e.g. MyProject vs myproject).
    """
    slug_map = {}

    for entry in sorted(os.listdir(projects_dir)):
        slug_path = os.path.join(projects_dir, entry)
        if not os.path.isdir(slug_path):
            continue

        project_name = None

        # Scan top-level JSONL files for the first user record with cwd
        try:
            jsonl_files = [
                f for f in os.listdir(slug_path)
                if f.endswith(".jsonl") and os.path.isfile(os.path.join(slug_path, f))
            ]
        except OSError:
            continue

        for fname in jsonl_files[:10]:  # Check up to 10 files
            fpath = os.path.join(slug_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if record.get("type") == "user" and record.get("cwd"):
                            project_name = project_from_cwd(record["cwd"])
                            break
                if project_name:
                    break
            except OSError:
                continue

        # Store mapping (fallback to slug itself if no user record found)
        slug_map[entry] = project_name or entry

    return slug_map


def slug_from_path(jsonl_path, projects_dir):
    """Extract the slug directory name from a JSONL file path."""
    rel = os.path.relpath(jsonl_path, projects_dir)
    return rel.split(os.sep)[0]


def init_db(db_path):
    """Initialize the SQLite database from schema.sql."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # schema.sql FIRST so base tables exist before migrate_schema tries to
    # ALTER them or CREATE INDEX on their columns. On fresh DBs (first run
    # or watchdog regen after delete) the old order failed with
    # "no such table: main.sessions" and aborted leaving only a partial DB.
    with open(schema_path) as f:
        conn.executescript(f.read())

    migrate_schema(conn)

    conn.commit()
    return conn


def migrate_schema(conn):
    """Add columns that may be missing from older schemas."""
    migrations = [
        ("agent_activations", "duration_ms", "INTEGER"),
        ("agent_activations", "status", "TEXT DEFAULT 'completed'"),
    ]
    for table, col, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e) and "no such table" not in str(e):
                raise

    # Create hook_events table if missing (added in v2.4)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS hook_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_type TEXT NOT NULL, "
        "session_id TEXT, "
        "tool_name TEXT, "
        "data TEXT, "
        "timestamp TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hook_events_type "
        "ON hook_events(event_type, timestamp)"
    )
    # skill_activations table: per-skill invocation counts (skill name from Skill tool input.skill),
    # so skill pruning can be data-backed the way agent pruning already is.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS skill_activations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT NOT NULL, "
        "project TEXT NOT NULL, "
        "skill_name TEXT NOT NULL, "
        "tool_use_id TEXT UNIQUE, "
        "timestamp TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_project "
        "ON skill_activations(project, skill_name)"
    )
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_status "
            "ON agent_activations(status)"
        )
    except sqlite3.OperationalError:
        pass  # Table may not exist yet on fresh DB — schema.sql will create it
    # daily_summary table (added in v2.7)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS daily_summary ("
        "date TEXT NOT NULL, project TEXT NOT NULL, "
        "total_cost REAL DEFAULT 0, total_sessions INTEGER DEFAULT 0, "
        "total_input_tokens INTEGER DEFAULT 0, total_output_tokens INTEGER DEFAULT 0, "
        "total_cache_read_tokens INTEGER DEFAULT 0, total_agent_activations INTEGER DEFAULT 0, "
        "PRIMARY KEY (date, project))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hook_events_timestamp ON hook_events(timestamp)"
    )
    conn.commit()


class ShrinkDetectedError(Exception):
    """Raised when a JSONL file shrank below its stored byte watermark.

    A file smaller than its last ingested position was truncated, rotated or
    replaced since the previous run. Neither recovery is safe for incremental
    collection: resuming at 0 replays the retained prefix and double-counts its
    API usage/costs (api_calls carry no replay identity and tool counts are
    additive on conflict), while skipping silently drops the new content. So the
    collector refuses and leaves the existing database, history and watermark
    untouched; rebuilding the database is an explicit owner action via --full,
    which clears and re-ingests from scratch and never happens automatically.
    """

    def __init__(self, path):
        self.path = path
        super().__init__(
            f"{path} shrank below its last ingested position "
            f"(truncated, rotated or replaced). Re-run with --full to rebuild "
            f"the database from scratch."
        )


def get_watermark(conn, jsonl_path):
    """Get the last ingested byte position for a file."""
    row = conn.execute(
        "SELECT last_byte_pos FROM ingestion_state WHERE jsonl_path = ?",
        (jsonl_path,),
    ).fetchone()
    return row[0] if row else 0


def set_watermark(conn, jsonl_path, byte_pos):
    """Update the ingested byte position for a file."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO ingestion_state (jsonl_path, last_byte_pos, last_updated) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(jsonl_path) DO UPDATE SET last_byte_pos=excluded.last_byte_pos, "
        "last_updated=excluded.last_updated",
        (jsonl_path, byte_pos, now),
    )


def resume_watermark(conn, path, file_size, full_mode):
    """Return the byte offset to resume ingestion from for ``path``.

    In ``--full`` mode ingestion always restarts at 0 (``main`` has already cleared
    the database, so there is nothing to double-count). Otherwise the stored byte
    watermark is returned for normal append-only growth.

    A file smaller than its stored watermark was truncated, rotated or replaced.
    There is no safe incremental recovery — resuming at 0 would replay the retained
    prefix and inflate counts/costs, and keeping the stale offset would silently
    skip the new content — so this raises ``ShrinkDetectedError`` before any write.
    The caller surfaces it as a nonzero CLI exit telling the owner to rebuild with
    ``--full``; the database, history and watermark are left untouched.
    """
    if full_mode:
        return 0
    watermark = get_watermark(conn, path)
    if watermark > file_size:
        raise ShrinkDetectedError(path)
    return watermark


def read_complete_records(f, start_pos):
    """Yield ``(record, pos_after)`` for each complete line of a JSONL file.

    ``f`` must be a **binary** file handle. Reading bytes is what makes ``f.tell()``
    a true byte offset: a text ``TextIOWrapper`` paused between a CR and its LF
    returns an opaque decoder cookie far larger than the file, which later overflows
    the SQLite integer watermark. Binary ``readline`` splits only on ``b"\\n"``, so a
    ``\\r\\n`` terminator (or a bare ``\\r`` awaiting its ``\\n``) is handled by the
    ``strip`` below rather than by newline translation, and ``pos_after`` is always a
    byte offset. Each complete line is decoded as UTF-8 (undecodable bytes replaced)
    only after it is read, so multi-byte content split across the resume boundary is
    held, not corrupted.

    Resumes at ``start_pos`` and walks forward one line at a time. ``record`` is the
    parsed object, or ``None`` for a complete-but-malformed line whose bytes should
    still be consumed. ``pos_after`` is the byte offset immediately after the line;
    the caller advances its watermark only to yielded ``pos_after`` values, so it
    never moves past bytes it did not fully consume.

    A trailing line with no newline terminator that fails to parse is treated as an
    in-progress append: the generator stops without yielding it, leaving the
    watermark before it so a later pass ingests the finished record exactly once. A
    trailing line with no newline that parses is accepted as a finished file's last
    line (object-per-line JSONL never leaves a partial object that parses as valid
    JSON, so a parseable unterminated tail is complete, not half-written).
    """
    f.seek(start_pos)
    while True:
        line = f.readline()
        if not line:
            return
        pos_after = f.tell()
        has_newline = line.endswith(b"\n")
        stripped = line.decode("utf-8", "replace").strip()
        if not stripped:
            if has_newline:
                # blank separator line — consume it and continue
                yield None, pos_after
                continue
            # trailing whitespace with no terminator may be a partial write — hold
            return
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            if has_newline:
                # a complete row that will never parse — skip it, but consume its
                # bytes so one bad line cannot block the rest of the file forever
                yield None, pos_after
                continue
            # no terminator and unparseable — writer is mid-append; stop and hold
            return
        yield record, pos_after
        if not has_newline:
            return


def process_jsonl_file(conn, jsonl_path, project, full_mode=False):
    """Process a single JSONL file, extracting all record types."""
    file_size = os.path.getsize(jsonl_path)
    watermark = resume_watermark(conn, jsonl_path, file_size, full_mode)

    if watermark >= file_size:
        return 0  # Nothing new

    records_processed = 0
    session_data = {}  # Collect session metadata
    api_calls_batch = []
    agent_batch = []
    skill_batch = []
    tool_batch = {}  # (session_id, tool_name) -> count
    turn_durations = []

    safe_pos = watermark
    with open(jsonl_path, "rb") as f:
        for record, pos_after in read_complete_records(f, watermark):
            safe_pos = pos_after
            if record is None:
                continue

            rec_type = record.get("type")
            if not rec_type:
                continue

            session_id = record.get("sessionId", "")
            cwd = record.get("cwd", "")
            timestamp = record.get("timestamp", "")

            # --- type: user (first record with parentUuid=null) ---
            if rec_type == "user" and session_id:
                if session_id not in session_data:
                    session_data[session_id] = {
                        "project": project,
                        "cwd": cwd,
                        "git_branch": record.get("gitBranch"),
                        "started_at": timestamp,
                        "claude_version": record.get("version"),
                        "ended_at": timestamp,
                        "total_turns": 0,
                    }
                else:
                    # Update ended_at with latest timestamp
                    if timestamp > session_data[session_id].get("ended_at", ""):
                        session_data[session_id]["ended_at"] = timestamp

            # --- type: assistant (API call + possible tool_use) ---
            elif rec_type == "assistant":
                msg = record.get("message", {})
                model = msg.get("model", "")
                usage = msg.get("usage", {})

                if model and usage:
                    cost = estimate_cost(model, usage)
                    api_calls_batch.append((
                        session_id,
                        project,
                        model,
                        usage.get("input_tokens", 0) or 0,
                        usage.get("output_tokens", 0) or 0,
                        usage.get("cache_read_input_tokens", 0) or 0,
                        usage.get("cache_creation_input_tokens", 0) or 0,
                        cost,
                        timestamp,
                    ))

                # Update session ended_at
                if session_id in session_data and timestamp:
                    if timestamp > session_data[session_id].get("ended_at", ""):
                        session_data[session_id]["ended_at"] = timestamp

                # Check for agent/subagent activations (Task or Agent tool_use)
                contents = msg.get("content", [])
                if isinstance(contents, list):
                    for block in contents:
                        if not isinstance(block, dict):
                            continue

                        if block.get("type") == "tool_use":
                            tool_name = block.get("name", "")

                            # Track tool usage
                            if tool_name and session_id:
                                key = (session_id, project, tool_name)
                                tool_batch[key] = tool_batch.get(key, 0) + 1

                            # Agent/Task activation
                            if tool_name in ("Task", "Agent"):
                                tool_input = block.get("input", {})
                                agent_name = tool_input.get("subagent_type", "general-purpose")
                                description = tool_input.get("description", "")
                                tool_use_id = block.get("id")

                                agent_batch.append((
                                    session_id,
                                    project,
                                    agent_name,
                                    description,
                                    tool_use_id,
                                    timestamp,
                                ))

                            # Skill activation (the invoked skill name is in input.skill)
                            elif tool_name == "Skill":
                                skill_name = block.get("input", {}).get("skill", "")
                                if skill_name and session_id:
                                    skill_batch.append((
                                        session_id,
                                        project,
                                        skill_name,
                                        block.get("id"),
                                        timestamp,
                                    ))

            # --- type: system, subtype: turn_duration ---
            elif rec_type == "system" and record.get("subtype") == "turn_duration":
                duration_ms = record.get("durationMs", 0)
                if session_id and duration_ms:
                    turn_durations.append((session_id, duration_ms))

                    # Count turns (tracked via UPDATE, not in-memory)
                    pass

            records_processed += 1

    final_pos = safe_pos

    # --- Write to database ---

    # Upsert sessions
    for sid, sdata in session_data.items():
        conn.execute(
            "INSERT INTO sessions (session_id, project, cwd, git_branch, started_at, "
            "ended_at, claude_version, total_turns) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "ended_at = MAX(sessions.ended_at, excluded.ended_at)",
            (
                sid,
                sdata["project"],
                sdata["cwd"],
                sdata["git_branch"],
                sdata["started_at"],
                sdata["ended_at"],
                sdata["claude_version"],
                sdata["total_turns"],
            ),
        )

    # Insert API calls
    if api_calls_batch:
        conn.executemany(
            "INSERT INTO api_calls (session_id, project, model, input_tokens, "
            "output_tokens, cache_read_tokens, cache_creation_tokens, "
            "estimated_cost_usd, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            api_calls_batch,
        )

    # Insert agent activations (dedup by tool_use_id)
    for agent_row in agent_batch:
        try:
            conn.execute(
                "INSERT INTO agent_activations (session_id, project, agent_name, "
                "description, tool_use_id, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                agent_row,
            )
        except sqlite3.IntegrityError:
            pass  # Duplicate tool_use_id, skip

    # Insert skill activations (dedup by tool_use_id)
    for skill_row in skill_batch:
        try:
            conn.execute(
                "INSERT INTO skill_activations (session_id, project, skill_name, "
                "tool_use_id, timestamp) VALUES (?, ?, ?, ?, ?)",
                skill_row,
            )
        except sqlite3.IntegrityError:
            pass  # Duplicate tool_use_id, skip

    # Upsert tool usage (unique on session_id + tool_name)
    for (sid, proj, tname), count in tool_batch.items():
        # Use latest timestamp from session or now
        ts = session_data.get(sid, {}).get("ended_at", datetime.now(timezone.utc).isoformat())
        conn.execute(
            "INSERT INTO tool_usage (session_id, project, tool_name, call_count, timestamp) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, tool_name) DO UPDATE SET "
            "call_count = tool_usage.call_count + excluded.call_count, "
            "timestamp = excluded.timestamp",
            (sid, proj, tname, count, ts),
        )

    # Update session durations and turn counts from turn_duration records
    for sid, dur_ms in turn_durations:
        conn.execute(
            "UPDATE sessions SET "
            "duration_ms = COALESCE(duration_ms, 0) + ?, "
            "total_turns = COALESCE(total_turns, 0) + 1 "
            "WHERE session_id = ?",
            (dur_ms, sid),
        )

    # Update watermark and commit atomically
    set_watermark(conn, jsonl_path, final_pos)
    conn.commit()

    return records_processed


def populate_daily_summary(conn):
    """Pre-aggregate daily totals for fast dashboard queries."""
    conn.execute("DELETE FROM daily_summary")
    conn.execute("""
        INSERT INTO daily_summary (date, project, total_cost, total_sessions,
            total_input_tokens, total_output_tokens, total_cache_read_tokens,
            total_agent_activations)
        SELECT
            DATE(a.timestamp) as date,
            a.project,
            COALESCE(SUM(a.estimated_cost_usd), 0),
            COUNT(DISTINCT a.session_id),
            COALESCE(SUM(a.input_tokens), 0),
            COALESCE(SUM(a.output_tokens), 0),
            COALESCE(SUM(a.cache_read_tokens), 0),
            (SELECT COUNT(*) FROM agent_activations ag
             WHERE ag.project = a.project AND DATE(ag.timestamp) = DATE(a.timestamp))
        FROM api_calls a
        GROUP BY DATE(a.timestamp), a.project
    """)
    conn.commit()


def ingest_agent_events(conn, events_file, full_mode=False):
    """Ingest real-time agent events from hook-generated JSONL.

    The agent-tracker.sh hook writes start/stop events to this file.
    We merge them into the agent_activations table, adding duration
    and status data that batch JSONL processing cannot provide.
    """
    if not os.path.exists(events_file):
        return 0

    file_size = os.path.getsize(events_file)
    watermark = resume_watermark(conn, events_file, file_size, full_mode)
    if watermark >= file_size:
        return 0

    records = 0
    safe_pos = watermark
    with open(events_file, "rb") as f:
        for event, pos_after in read_complete_records(f, watermark):
            safe_pos = pos_after
            if event is None:
                continue

            event_type = event.get("event")
            session_id = event.get("session_id", "")
            agent_type = event.get("agent_type", "unknown")
            description = event.get("description", "")
            timestamp = event.get("timestamp", "")

            if event_type == "agent_start":
                conn.execute(
                    "INSERT INTO hook_events (event_type, session_id, tool_name, "
                    "data, timestamp) VALUES (?, ?, ?, ?, ?)",
                    ("agent_start", session_id, agent_type, description, timestamp),
                )

                # Also insert into agent_activations with status='started'
                # so the stop handler can match and update with duration
                try:
                    conn.execute(
                        "INSERT INTO agent_activations (session_id, project, "
                        "agent_name, description, status, timestamp) "
                        "VALUES (?, ?, ?, ?, 'started', ?)",
                        (session_id, "hook-event", agent_type, description, timestamp),
                    )
                except sqlite3.IntegrityError:
                    pass  # Duplicate, skip

            elif event_type == "agent_stop":
                duration_ms = event.get("duration_ms", 0)
                status = event.get("status", "completed")

                # Log the stop event
                conn.execute(
                    "INSERT INTO hook_events (event_type, session_id, tool_name, "
                    "data, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (
                        "agent_stop",
                        session_id,
                        agent_type,
                        json.dumps({"duration_ms": duration_ms, "status": status}),
                        timestamp,
                    ),
                )

                # Update the most recent matching activation with duration/status
                row = conn.execute(
                    "SELECT id FROM agent_activations "
                    "WHERE session_id = ? AND agent_name = ? AND status = 'started' "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (session_id, agent_type),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE agent_activations SET duration_ms = ?, status = ? "
                        "WHERE id = ?",
                        (duration_ms, status, row[0]),
                    )

            records += 1

    final_pos = safe_pos
    set_watermark(conn, events_file, final_pos)
    conn.commit()
    return records


def ingest_hook_events(conn, jsonl_file, event_type, full_mode=False):
    """Ingest generic hook event JSONL files (permission audit, session summaries)."""
    if not os.path.exists(jsonl_file):
        return 0

    file_size = os.path.getsize(jsonl_file)
    watermark = resume_watermark(conn, jsonl_file, file_size, full_mode)
    if watermark >= file_size:
        return 0

    records = 0
    safe_pos = watermark
    with open(jsonl_file, "rb") as f:
        for event, pos_after in read_complete_records(f, watermark):
            safe_pos = pos_after
            if event is None:
                continue

            conn.execute(
                "INSERT INTO hook_events (event_type, session_id, tool_name, "
                "data, timestamp) VALUES (?, ?, ?, ?, ?)",
                (
                    event.get("event", event_type),
                    event.get("session_id", ""),
                    event.get("tool", ""),
                    json.dumps(event),
                    event.get("timestamp", ""),
                ),
            )
            records += 1

    final_pos = safe_pos
    set_watermark(conn, jsonl_file, final_pos)
    conn.commit()
    return records


def find_jsonl_files(base_dir):
    """Find all JSONL files under ~/.claude/projects/, including subagent dirs."""
    pattern = os.path.join(base_dir, "**", "*.jsonl")
    return sorted(glob.glob(pattern, recursive=True))


def main():
    # Parse args
    db_path = os.path.expanduser("~/.claude/analytics/claude-obs.db")
    full_mode = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        elif args[i] == "--full":
            full_mode = True
            i += 1
        elif args[i] in ("--help", "-h"):
            print(__doc__.strip())
            sys.exit(0)
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    # Ensure output directory exists
    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)

    projects_dir = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(projects_dir):
        print(f"No projects directory found at {projects_dir}", file=sys.stderr)
        sys.exit(1)

    if full_mode:
        print("Full re-ingestion mode: removing old database...")
        if os.path.exists(db_path):
            os.remove(db_path)
        # Also remove WAL/SHM files
        for suffix in ("-wal", "-shm"):
            path = db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    # Initialize database (creates fresh if --full removed it)
    conn = init_db(db_path)

    # Run schema migrations for existing databases
    migrate_schema(conn)

    # Build slug → project mapping
    slug_map = build_slug_project_map(projects_dir)
    print(f"Mapped {len(slug_map)} project slug(s)")

    # Find and process all JSONL files
    jsonl_files = find_jsonl_files(projects_dir)
    total_files = len(jsonl_files)
    total_records = 0
    files_with_new_data = 0

    start_time = time.time()
    print(f"Found {total_files} JSONL files to scan")

    try:
        for idx, jsonl_path in enumerate(jsonl_files, 1):
            if idx % 100 == 0 or idx == total_files:
                print(f"  Processing {idx}/{total_files}...", end="\r")

            slug = slug_from_path(jsonl_path, projects_dir)
            project = slug_map.get(slug, "unknown")
            records = process_jsonl_file(conn, jsonl_path, project, full_mode)
            total_records += records
            if records > 0:
                files_with_new_data += 1

        # Ingest hook-generated event files (real-time agent tracking, audits)
        analytics_dir = os.path.expanduser("~/.claude/analytics")
        hook_event_files = {
            "agent-events.jsonl": "agent_event",
            "session-summaries.jsonl": "session_end",
            "permission-audit.jsonl": "permission_request",
        }
        hook_records = 0
        for fname, etype in hook_event_files.items():
            fpath = os.path.join(analytics_dir, fname)
            if fname == "agent-events.jsonl":
                hook_records += ingest_agent_events(conn, fpath, full_mode)
            else:
                hook_records += ingest_hook_events(conn, fpath, etype, full_mode)
    except ShrinkDetectedError as exc:
        # A truncated/rotated/replaced file cannot be reconciled incrementally
        # without replaying or dropping owner data. Refuse here (nothing was
        # written for that file), name it, and exit nonzero so no partial or
        # inflated summary count is ever claimed. Rebuilding is explicit: --full.
        conn.close()
        print(file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "  Incremental collection refuses rather than replay or drop data. "
            "Run:\n      python3 collector.py --full",
            file=sys.stderr,
        )
        sys.exit(1)

    if hook_records > 0:
        print(f"\n  Hook events ingested: {hook_records}")

    # Populate daily summary for fast dashboard queries
    populate_daily_summary(conn)

    elapsed = time.time() - start_time

    # Print summary stats
    session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    api_count = conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
    agent_count = conn.execute("SELECT COUNT(*) FROM agent_activations").fetchone()[0]
    total_cost = conn.execute(
        "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM api_calls"
    ).fetchone()[0]

    print(f"\n{'=' * 50}")
    print(f"Ingestion complete in {elapsed:.1f}s")
    print(f"  Files scanned:      {total_files}")
    print(f"  Files with new data: {files_with_new_data}")
    print(f"  Records processed:  {total_records}")
    print(f"  Sessions:           {session_count}")
    print(f"  API calls:          {api_count}")
    print(f"  Agent activations:  {agent_count}")
    print(f"  Total est. cost:    ${total_cost:.2f}")
    print(f"  Database:           {db_path}")

    conn.close()


if __name__ == "__main__":
    main()
