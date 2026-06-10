from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import Settings, get_settings
from .models import UsageRecord, VirtualKey


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dt(value: datetime | None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    db_path = settings.sqlite_path
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None puts sqlite3 in autocommit mode so the budget path
    # can manage an explicit BEGIN IMMEDIATE transaction itself.
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(settings)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    # executescript force-commits, which would break an explicit transaction
    # opened by the budget path — only run it when the schema is missing.
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_records'"
    ).fetchone()
    if exists:
        _ensure_usage_columns(conn)
        _ensure_virtual_key_columns(conn)
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS virtual_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            owner TEXT NOT NULL,
            project TEXT NOT NULL,
            allowed_models TEXT NOT NULL,
            daily_budget_usd REAL NOT NULL,
            monthly_budget_usd REAL NOT NULL,
            max_single_request_usd REAL NOT NULL,
            provider TEXT NOT NULL DEFAULT 'openai-compatible',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            requests_per_minute INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL UNIQUE,
            timestamp TEXT NOT NULL,
            virtual_key_id INTEGER,
            virtual_key TEXT,
            owner TEXT,
            project TEXT,
            session_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            estimated_input_tokens INTEGER NOT NULL,
            estimated_output_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            estimated_cost_usd REAL NOT NULL,
            status TEXT NOT NULL,
            block_reason TEXT,
            latency_ms INTEGER NOT NULL,
            route_path TEXT NOT NULL,
            user_agent TEXT,
            request_category TEXT NOT NULL,
            warning_flags TEXT NOT NULL,
            prompt_hash TEXT,
            response_hash TEXT,
            prompt_preview TEXT,
            response_preview TEXT,
            raw_messages TEXT,
            raw_response TEXT,
            github_repo TEXT,
            github_pr TEXT,
            tool_call_count INTEGER NOT NULL DEFAULT 0,
            tool_names TEXT,
            context_hash TEXT,
            FOREIGN KEY (virtual_key_id) REFERENCES virtual_keys(id)
        );
        CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_records(timestamp);
        CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_records(session_id);
        CREATE INDEX IF NOT EXISTS idx_usage_key_day ON usage_records(virtual_key_id, timestamp);
        """
    )
    _ensure_usage_columns(conn)
    _ensure_virtual_key_columns(conn)


def _ensure_virtual_key_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(virtual_keys)")}
    if "requests_per_minute" not in existing:
        conn.execute("ALTER TABLE virtual_keys ADD COLUMN requests_per_minute INTEGER NOT NULL DEFAULT 0")


def _ensure_usage_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(usage_records)")}
    columns = {
        "github_repo": "TEXT",
        "github_pr": "TEXT",
        "tool_call_count": "INTEGER NOT NULL DEFAULT 0",
        "tool_names": "TEXT",
        "context_hash": "TEXT",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE usage_records ADD COLUMN {name} {definition}")


def row_to_key(row: sqlite3.Row | None) -> VirtualKey | None:
    if row is None:
        return None
    return VirtualKey(
        id=row["id"],
        key=row["key"],
        owner=row["owner"],
        project=row["project"],
        allowed_models=json.loads(row["allowed_models"]),
        daily_budget_usd=row["daily_budget_usd"],
        monthly_budget_usd=row["monthly_budget_usd"],
        max_single_request_usd=row["max_single_request_usd"],
        provider=row["provider"],
        enabled=bool(row["enabled"]),
        created_at=_parse_dt(row["created_at"]),
        requests_per_minute=int(row["requests_per_minute"] or 0),
    )


def create_virtual_key(conn: sqlite3.Connection, key: VirtualKey) -> VirtualKey:
    init_db(conn)
    existing = get_virtual_key(conn, key.key)
    if existing:
        return existing
    cur = conn.execute(
        """
        INSERT INTO virtual_keys
        (key, owner, project, allowed_models, daily_budget_usd, monthly_budget_usd,
         max_single_request_usd, provider, enabled, created_at, requests_per_minute)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            key.key,
            key.owner,
            key.project,
            json.dumps(key.allowed_models),
            key.daily_budget_usd,
            key.monthly_budget_usd,
            key.max_single_request_usd,
            key.provider,
            int(key.enabled),
            _dt(key.created_at),
            key.requests_per_minute,
        ),
    )
    key.id = cur.lastrowid
    return key


def get_virtual_key(conn: sqlite3.Connection, api_key: str) -> VirtualKey | None:
    init_db(conn)
    return row_to_key(conn.execute("SELECT * FROM virtual_keys WHERE key = ?", (api_key,)).fetchone())


def list_virtual_keys(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    init_db(conn)
    return list(conn.execute("SELECT * FROM virtual_keys ORDER BY owner, project"))


def insert_usage(conn: sqlite3.Connection, record: UsageRecord) -> None:
    init_db(conn)
    conn.execute(
        """
        INSERT INTO usage_records
        (request_id, timestamp, virtual_key_id, virtual_key, owner, project, session_id, provider, model,
         estimated_input_tokens, estimated_output_tokens, total_tokens, estimated_cost_usd, status, block_reason,
         latency_ms, route_path, user_agent, request_category, warning_flags, prompt_hash, response_hash,
         prompt_preview, response_preview, raw_messages, raw_response, github_repo, github_pr, tool_call_count,
         tool_names, context_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.request_id,
            _dt(record.timestamp),
            record.virtual_key_id,
            record.virtual_key,
            record.owner,
            record.project,
            record.session_id,
            record.provider,
            record.model,
            record.estimated_input_tokens,
            record.estimated_output_tokens,
            record.total_tokens,
            record.estimated_cost_usd,
            record.status,
            record.block_reason,
            record.latency_ms,
            record.route_path,
            record.user_agent,
            record.request_category,
            json.dumps(record.warning_flags),
            record.prompt_hash,
            record.response_hash,
            record.prompt_preview,
            record.response_preview,
            json.dumps(record.raw_messages) if record.raw_messages is not None else None,
            json.dumps(record.raw_response) if record.raw_response is not None else None,
            record.github_repo,
            record.github_pr,
            record.tool_call_count,
            json.dumps(record.tool_names or []),
            record.context_hash,
        ),
    )


def spend_between(conn: sqlite3.Connection, virtual_key_id: int, start_iso: str, end_iso: str) -> float:
    init_db(conn)
    # 'pending' rows are in-flight reservations: counting them lets concurrent
    # requests see each other's estimated spend before the provider responds.
    row = conn.execute(
        """
        SELECT COALESCE(SUM(estimated_cost_usd), 0) AS spend
        FROM usage_records
        WHERE virtual_key_id = ? AND timestamp >= ? AND timestamp < ? AND status IN ('allowed', 'pending')
        """,
        (virtual_key_id, start_iso, end_iso),
    ).fetchone()
    return float(row["spend"] or 0)


def requests_since(conn: sqlite3.Connection, virtual_key_id: int, start_iso: str) -> int:
    init_db(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM usage_records WHERE virtual_key_id = ? AND timestamp >= ?",
        (virtual_key_id, start_iso),
    ).fetchone()
    return int(row["n"] or 0)


def set_virtual_key_enabled(conn: sqlite3.Connection, key_id: int, enabled: bool) -> None:
    init_db(conn)
    conn.execute("UPDATE virtual_keys SET enabled = ? WHERE id = ?", (int(enabled), key_id))


def get_virtual_key_by_id(conn: sqlite3.Connection, key_id: int) -> VirtualKey | None:
    init_db(conn)
    return row_to_key(conn.execute("SELECT * FROM virtual_keys WHERE id = ?", (key_id,)).fetchone())


def update_usage(conn: sqlite3.Connection, record: UsageRecord) -> None:
    init_db(conn)
    conn.execute(
        """
        UPDATE usage_records
        SET estimated_input_tokens = ?, estimated_output_tokens = ?, total_tokens = ?,
            estimated_cost_usd = ?, status = ?, block_reason = ?, latency_ms = ?,
            response_hash = ?, response_preview = ?, raw_response = ?,
            tool_call_count = ?, tool_names = ?
        WHERE request_id = ?
        """,
        (
            record.estimated_input_tokens,
            record.estimated_output_tokens,
            record.total_tokens,
            record.estimated_cost_usd,
            record.status,
            record.block_reason,
            record.latency_ms,
            record.response_hash,
            record.response_preview,
            json.dumps(record.raw_response) if record.raw_response is not None else None,
            record.tool_call_count,
            json.dumps(record.tool_names or []),
            record.request_id,
        ),
    )
