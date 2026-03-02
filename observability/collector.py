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
    # Opus 4.6
    "claude-opus-4-6": {
        "input": 15e-6,
        "output": 75e-6,
        "cache_read": 1.5e-6,
        "cache_create": 18.75e-6,
    },
    # Sonnet 4.6
    "claude-sonnet-4-6": {
        "input": 3e-6,
        "output": 15e-6,
        "cache_read": 0.3e-6,
        "cache_create": 3.75e-6,
    },
    # Haiku 4.5
    "claude-haiku-4-5-20251001": {
        "input": 0.8e-6,
        "output": 4e-6,
        "cache_read": 0.08e-6,
        "cache_create": 1e-6,
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


def estimate_cost(model, usage):
    """Calculate estimated cost in USD for an API call."""
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

    with open(schema_path) as f:
        conn.executescript(f.read())

    conn.commit()
    return conn


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


def process_jsonl_file(conn, jsonl_path, project, full_mode=False):
    """Process a single JSONL file, extracting all record types."""
    watermark = 0 if full_mode else get_watermark(conn, jsonl_path)
    file_size = os.path.getsize(jsonl_path)

    if watermark >= file_size:
        return 0  # Nothing new

    records_processed = 0
    session_data = {}  # Collect session metadata
    api_calls_batch = []
    agent_batch = []
    tool_batch = {}  # (session_id, tool_name) -> count
    turn_durations = []

    with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
        if watermark > 0:
            f.seek(watermark)

        while True:
            line = f.readline()
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
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

            # --- type: system, subtype: turn_duration ---
            elif rec_type == "system" and record.get("subtype") == "turn_duration":
                duration_ms = record.get("durationMs", 0)
                if session_id and duration_ms:
                    turn_durations.append((session_id, duration_ms))

                    # Count turns (tracked via UPDATE, not in-memory)
                    pass

            records_processed += 1

        final_pos = f.tell()

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

    # Update watermark
    set_watermark(conn, jsonl_path, final_pos)
    conn.commit()

    return records_processed


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

    for idx, jsonl_path in enumerate(jsonl_files, 1):
        if idx % 100 == 0 or idx == total_files:
            print(f"  Processing {idx}/{total_files}...", end="\r")

        slug = slug_from_path(jsonl_path, projects_dir)
        project = slug_map.get(slug, "unknown")
        records = process_jsonl_file(conn, jsonl_path, project, full_mode)
        total_records += records
        if records > 0:
            files_with_new_data += 1

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
