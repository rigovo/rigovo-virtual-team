"""PostgreSQL database adapter — production persistence backend.

Provides the same interface as ``sqlite_local.LocalDatabase`` so that
repositories (SqliteTaskRepository, etc.) work transparently with either
backend.

Key differences from SQLite adapter:
- ``?`` placeholder rewriting → ``%s``
- ``INSERT OR REPLACE`` → ``ON CONFLICT … DO UPDATE``
- Uses ``psycopg`` (psycopg 3) with dict_row factory
- Connection health check + automatic reconnect
- Graceful error messages when dsn/driver is missing
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2  # Must stay in sync with sqlite_local.SCHEMA_VERSION

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
    tier TEXT DEFAULT 'auto',
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
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    checkpoint_timeline TEXT,
    last_heartbeat DOUBLE PRECISION
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

# Tables and their columns for migration transfer (order matters for FKs)
_MIGRATION_TABLES = [
    "tasks",
    "cost_ledger",
    "audit_log",
    "memories",
    "team_cache",
    "agent_cache",
    "workspace_cache",
]


class PostgresDatabase:
    """Postgres adapter with a sqlite-compatible API used by repositories."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError(
                "Postgres DSN is required. Set RIGOVO_DB_URL in Settings → Storage "
                "or as an environment variable.\n"
                "Example: postgresql://user:pass@localhost:5432/rigovo"
            )
        self._dsn = dsn
        self._conn = None

    def _get_conn(self):
        if self._conn is not None:
            # Health check — reconnect if connection dropped
            try:
                self._conn.execute("SELECT 1")
                return self._conn
            except Exception:
                logger.warning("Postgres connection lost, reconnecting…")
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as e:
            raise RuntimeError(
                "Postgres backend requires psycopg.\n"
                "Install with:  pip install 'psycopg[binary]'\n"
                "Or:            pip install psycopg psycopg-binary"
            ) from e

        try:
            self._conn = psycopg.connect(self._dsn, row_factory=dict_row)
        except Exception as e:
            dsn_safe = _mask_dsn(self._dsn)
            raise RuntimeError(
                f"Cannot connect to PostgreSQL at {dsn_safe}.\n"
                f"Error: {e}\n\n"
                "Troubleshooting:\n"
                "  1. Verify the DSN is correct (postgresql://user:pass@host:port/dbname)\n"
                "  2. Ensure the PostgreSQL server is running\n"
                "  3. Check network/firewall allows connections\n"
                "  4. Verify the database exists: createdb rigovo"
            ) from e

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
        """Create schema and apply migrations.

        Called once on startup. Idempotent — safe to call multiple times.
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT MAX(version) AS version FROM schema_version")
                row = cur.fetchone()
                current_version = int(row["version"]) if row and row["version"] else 0
            except Exception:
                current_version = 0
                conn.rollback()  # Clear error state before DDL

            if current_version < SCHEMA_VERSION:
                # Split schema SQL into individual statements for Postgres
                for stmt in SCHEMA_SQL.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        try:
                            cur.execute(stmt)
                        except Exception as e:
                            # Some statements may already exist — safe to continue
                            logger.debug("Schema statement skipped: %s", e)
                            conn.rollback()
                cur.execute(
                    "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                    (SCHEMA_VERSION,),
                )
                conn.commit()
                logger.info("Postgres schema v%d applied", SCHEMA_VERSION)

            # Idempotent column migrations (safe on existing databases)
            for _col_sql in [
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tier TEXT DEFAULT 'auto'",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS custom_title TEXT",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS workspace_path TEXT",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS workspace_label TEXT",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS checkpoint_timeline TEXT",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_heartbeat DOUBLE PRECISION",
            ]:
                try:
                    cur.execute(_col_sql)
                    conn.commit()
                except Exception:
                    conn.rollback()  # Clear error state

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

    def test_connection(self) -> dict[str, Any]:
        """Test connectivity and return server info.

        Returns dict with 'ok', 'version', 'database', 'error' keys.
        Used by Settings UI to validate DSN before saving.

        **Contract:** Always returns all four keys — the UI depends on
        ``error`` being a string (not None/missing) on failure.
        """
        try:
            conn = self._get_conn()
            row = conn.execute("SELECT version() AS v, current_database() AS db").fetchone()
            return {
                "ok": True,
                "version": row["v"] if row else "unknown",
                "database": row["db"] if row else "unknown",
                "error": None,
            }
        except ImportError:
            return {
                "ok": False,
                "version": None,
                "database": None,
                "error": (
                    "PostgreSQL driver not installed. "
                    "Run: pip install 'psycopg[binary]' — then restart Rigovo."
                ),
            }
        except Exception as e:
            msg = str(e).strip()
            return {
                "ok": False,
                "version": None,
                "database": None,
                "error": msg if msg else "Connection failed — check DSN and server status.",
            }


def migrate_sqlite_to_postgres(sqlite_path: str, postgres_dsn: str) -> dict[str, Any]:
    """Migrate all data from a SQLite database to PostgreSQL.

    This is the one-click migration path for non-technical users who
    started with SQLite and later set up PostgreSQL.

    Steps:
    1. Open SQLite and read all rows from each table
    2. Connect to PostgreSQL and ensure schema exists
    3. Insert all rows with ON CONFLICT DO UPDATE (idempotent)
    4. Report counts

    Returns:
        {
            "ok": True/False,
            "tables": {"tasks": 42, "audit_log": 100, ...},
            "error": None or error string,
        }
    """
    import sqlite3

    result: dict[str, Any] = {"ok": False, "tables": {}, "error": None}

    # 1. Open SQLite
    try:
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
    except Exception as e:
        result["error"] = f"Cannot open SQLite database: {e}"
        return result

    # 2. Connect to PostgreSQL and ensure schema
    try:
        pg = PostgresDatabase(postgres_dsn)
        pg.initialize()
    except Exception as e:
        sqlite_conn.close()
        result["error"] = f"Cannot connect to PostgreSQL: {e}"
        return result

    # 3. Transfer each table
    for table in _MIGRATION_TABLES:
        try:
            # Read all rows from SQLite
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                result["tables"][table] = 0
                continue

            # Get column names from first row
            columns = list(rows[0].keys())

            # Build Postgres upsert SQL
            placeholders = ", ".join(["%s"] * len(columns))
            col_list = ", ".join(columns)
            update_cols = [c for c in columns if c.lower() != "id"]

            if update_cols:
                updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
                sql = (
                    f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                    f"ON CONFLICT (id) DO UPDATE SET {updates}"
                )
            else:
                sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING"

            # Insert rows in batches
            pg_conn = pg._get_conn()
            with pg_conn.cursor() as cur:
                for row in rows:
                    values = tuple(row[c] for c in columns)
                    try:
                        cur.execute(sql, values)
                    except Exception as e:
                        logger.warning("Skipping row in %s: %s", table, e)
                        pg_conn.rollback()
                        continue
                pg_conn.commit()

            result["tables"][table] = len(rows)
            logger.info("Migrated %d rows from %s", len(rows), table)

        except Exception as e:
            logger.warning("Table %s migration failed: %s", table, e)
            result["tables"][table] = -1  # -1 = error

    # 4. Transfer schema_version
    try:
        pg_conn = pg._get_conn()
        with pg_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                (SCHEMA_VERSION,),
            )
            pg_conn.commit()
    except Exception:
        pass

    sqlite_conn.close()

    # Check if any table had errors
    errors = [t for t, c in result["tables"].items() if c == -1]
    if errors:
        result["error"] = f"Some tables had errors: {', '.join(errors)}"
    else:
        result["ok"] = True

    return result


def _mask_dsn(dsn: str) -> str:
    """Mask password in DSN for safe logging."""
    if "@" in dsn:
        parts = dsn.rsplit("@", 1)
        return f"••••@{parts[1]}"
    return dsn[:10] + "••••" if len(dsn) > 10 else "••••"
