"""PostgreSQL database adapter — production persistence backend."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

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
    approval_data TEXT,
    pipeline_steps TEXT,
    total_tokens INTEGER DEFAULT 0,
    total_cost_usd DOUBLE PRECISION DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    retries INTEGER DEFAULT 0,
    langgraph_thread_id TEXT,
    rejected_at TEXT,
    user_feedback TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

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
    cost_usd DOUBLE PRECISION NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    team_id TEXT,
    agent_id TEXT,
    task_id TEXT,
    action_type TEXT NOT NULL,
    agent_role TEXT,
    summary TEXT,
    metadata TEXT,
    synced INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_project_id TEXT,
    source_task_id TEXT,
    source_agent_id TEXT,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    embedding TEXT,
    usage_count INTEGER DEFAULT 0,
    cross_project_usage INTEGER DEFAULT 0,
    last_used_at TEXT,
    synced INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_cache (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    domain TEXT,
    description TEXT,
    config TEXT,
    is_active INTEGER DEFAULT 1,
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_cache (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    system_prompt TEXT,
    llm_model TEXT,
    tools TEXT,
    custom_rules TEXT,
    enrichment_context TEXT,
    pipeline_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    stats TEXT,
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_cache (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    plan TEXT DEFAULT 'free',
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_queue (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    last_attempt_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON tasks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_cost_task ON cost_ledger(task_id);
CREATE INDEX IF NOT EXISTS idx_cost_workspace ON cost_ledger(workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_log(workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id);
CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace_id);
CREATE INDEX IF NOT EXISTS idx_sync_queue_entity_type ON sync_queue(entity_type);
"""


class PostgresDatabase:
    """Postgres adapter with a sqlite-compatible API used by repositories."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("Postgres DSN is required (set RIGOVO_DB_URL)")
        self._dsn = dsn
        self._conn = None

    def _get_conn(self):
        if self._conn is not None:
            return self._conn

        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as e:
            raise RuntimeError(
                "Postgres backend requires psycopg. Install with: pip install 'psycopg[binary]'"
            ) from e

        self._conn = psycopg.connect(self._dsn, row_factory=dict_row)
        return self._conn

    @staticmethod
    def _convert_placeholders(sql: str) -> str:
        # Repositories use sqlite-style '?' placeholders.
        return sql.replace("?", "%s")

    @staticmethod
    def _rewrite_insert_or_replace(sql: str) -> str:
        # Convert SQLite upsert form into Postgres ON CONFLICT upsert.
        pattern = re.compile(
            r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+([a-zA-Z0-9_]+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)\s*$",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.match(sql.strip())
        if not match:
            return sql

        table = match.group(1)
        columns = [c.strip() for c in match.group(2).split(",")]
        values_expr = match.group(3).strip()

        update_cols = [c for c in columns if c.lower() != "id"]
        if not update_cols:
            return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values_expr}) ON CONFLICT (id) DO NOTHING"

        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        return (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values_expr}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}"
        )

    def _normalize_sql(self, sql: str) -> str:
        sql = self._rewrite_insert_or_replace(sql)
        return self._convert_placeholders(sql)

    def initialize(self) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT MAX(version) AS version FROM schema_version")
                row = cur.fetchone()
                current_version = int(row["version"]) if row and row["version"] else 0
            except Exception:
                current_version = 0

            if current_version < SCHEMA_VERSION:
                cur.execute(SCHEMA_SQL)
                cur.execute(
                    "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                    (SCHEMA_VERSION,),
                )
                conn.commit()
                logger.info("Postgres schema v%d applied", SCHEMA_VERSION)

    def execute(self, sql: str, params: tuple[Any, ...] = ()):
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(self._normalize_sql(sql), params)
        return cur

    def executemany(self, sql: str, params_list: list[tuple[Any, ...]]):
        conn = self._get_conn()
        cur = conn.cursor()
        cur.executemany(self._normalize_sql(sql), params_list)
        return cur

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()):
        cur = self.execute(sql, params)
        return cur.fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()):
        cur = self.execute(sql, params)
        return cur.fetchall()

    def commit(self) -> None:
        conn = self._get_conn()
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
