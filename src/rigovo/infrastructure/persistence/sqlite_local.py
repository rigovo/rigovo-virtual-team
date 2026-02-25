"""SQLite local database — schema management and connection pool."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA_SQL = """\
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

-- Tasks (local execution state)
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT,
    team_id TEXT,
    description TEXT NOT NULL,
    task_type TEXT,
    complexity TEXT,
    status TEXT DEFAULT 'pending',
    current_checkpoint TEXT,
    approval_data TEXT,          -- JSON
    pipeline_steps TEXT,         -- JSON array
    total_tokens INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    retries INTEGER DEFAULT 0,
    langgraph_thread_id TEXT,
    rejected_at TEXT,
    user_feedback TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Cost ledger (granular per-agent-per-task tracking)
CREATE TABLE IF NOT EXISTS cost_ledger (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    team_id TEXT,
    agent_id TEXT,
    task_id TEXT,
    project_id TEXT,
    llm_model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Audit log (immutable action log)
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    team_id TEXT,
    agent_id TEXT,
    task_id TEXT,
    action_type TEXT NOT NULL,
    agent_role TEXT,
    summary TEXT,
    metadata TEXT,               -- JSON
    synced INTEGER DEFAULT 0,    -- 0=not synced, 1=synced to cloud
    created_at TEXT DEFAULT (datetime('now'))
);

-- Memories (local cache of workspace memories)
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_project_id TEXT,
    source_task_id TEXT,
    source_agent_id TEXT,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    embedding TEXT,              -- JSON array of floats
    usage_count INTEGER DEFAULT 0,
    cross_project_usage INTEGER DEFAULT 0,
    last_used_at TEXT,
    synced INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Team config cache (synced from cloud, used offline)
CREATE TABLE IF NOT EXISTS team_cache (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    domain TEXT,
    description TEXT,
    config TEXT,                 -- Full JSON config including agents
    is_active INTEGER DEFAULT 1,
    synced_at TEXT DEFAULT (datetime('now'))
);

-- Agent config cache
CREATE TABLE IF NOT EXISTS agent_cache (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    system_prompt TEXT,
    llm_model TEXT,
    tools TEXT,                  -- JSON
    custom_rules TEXT,           -- JSON
    enrichment_context TEXT,     -- JSON
    pipeline_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    stats TEXT,                  -- JSON
    synced_at TEXT DEFAULT (datetime('now'))
);

-- Workspace config cache
CREATE TABLE IF NOT EXISTS workspace_cache (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    plan TEXT DEFAULT 'free',
    synced_at TEXT DEFAULT (datetime('now'))
);

-- Sync queue (items pending cloud upload)
CREATE TABLE IF NOT EXISTS sync_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,   -- 'task', 'cost', 'audit', 'memory'
    entity_id TEXT NOT NULL,
    payload TEXT NOT NULL,       -- JSON
    attempts INTEGER DEFAULT 0,
    last_attempt_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON tasks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_cost_task ON cost_ledger(task_id);
CREATE INDEX IF NOT EXISTS idx_cost_workspace ON cost_ledger(workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_log(workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_unsynced ON audit_log(synced) WHERE synced = 0;
CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace_id);
CREATE INDEX IF NOT EXISTS idx_sync_queue_pending ON sync_queue(entity_type) WHERE attempts < 5;
"""


class LocalDatabase:
    """
    SQLite database for local-first operation.

    Stores task state, cost data, audit log, memories, and cached
    cloud configs. Everything needed to work offline.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path) if isinstance(db_path, str) else db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create database and apply schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()

        # Check if schema needs applying
        try:
            row = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            current_version = row[0] if row and row[0] else 0
        except sqlite3.OperationalError:
            current_version = 0

        if current_version < SCHEMA_VERSION:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
            logger.info("Database schema v%d applied at %s", SCHEMA_VERSION, self._db_path)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._get_conn().execute(sql, params)

    def executemany(self, sql: str, params_list: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        return self._get_conn().executemany(sql, params_list)

    def commit(self) -> None:
        if self._conn:
            self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self._get_conn().execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return self._get_conn().execute(sql, params).fetchall()
