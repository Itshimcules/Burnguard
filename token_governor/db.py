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
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
            created_at TEXT NOT NULL
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
            FOREIGN KEY (virtual_key_id) REFERENCES virtual_keys(id)
        );
        CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_records(timestamp);
        CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_records(session_id);
        CREATE INDEX IF NOT EXISTS idx_usage_key_day ON usage_records(virtual_key_id, timestamp);
        """
    )


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
         max_single_request_usd, provider, enabled, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
         prompt_preview, response_preview, raw_messages, raw_response)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ),
    )


def spend_between(conn: sqlite3.Connection, virtual_key_id: int, start_iso: str, end_iso: str) -> float:
    init_db(conn)
    row = conn.execute(
        """
        SELECT COALESCE(SUM(estimated_cost_usd), 0) AS spend
        FROM usage_records
        WHERE virtual_key_id = ? AND timestamp >= ? AND timestamp < ? AND status = 'allowed'
        """,
        (virtual_key_id, start_iso, end_iso),
    ).fetchone()
    return float(row["spend"] or 0)
