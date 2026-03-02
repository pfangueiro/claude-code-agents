-- Claude Code Observability - SQLite Schema
-- Applied automatically by collector.py on first run

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    project         TEXT NOT NULL,
    cwd             TEXT NOT NULL,
    git_branch      TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    duration_ms     INTEGER,
    claude_version  TEXT,
    total_turns     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS api_calls (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              TEXT NOT NULL REFERENCES sessions(session_id),
    project                 TEXT NOT NULL,
    model                   TEXT NOT NULL,
    input_tokens            INTEGER DEFAULT 0,
    output_tokens           INTEGER DEFAULT 0,
    cache_read_tokens       INTEGER DEFAULT 0,
    cache_creation_tokens   INTEGER DEFAULT 0,
    estimated_cost_usd      REAL DEFAULT 0,
    timestamp               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_activations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id),
    project         TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    description     TEXT,
    tool_use_id     TEXT UNIQUE,
    timestamp       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    project     TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    call_count  INTEGER DEFAULT 1,
    timestamp   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_state (
    jsonl_path      TEXT PRIMARY KEY,
    last_byte_pos   INTEGER DEFAULT 0,
    last_updated    TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_calls_project ON api_calls(project, timestamp);
CREATE INDEX IF NOT EXISTS idx_api_calls_session ON api_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_project ON agent_activations(project, agent_name);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project, started_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_usage_unique ON tool_usage(session_id, tool_name);
CREATE INDEX IF NOT EXISTS idx_api_calls_timestamp ON api_calls(timestamp);
