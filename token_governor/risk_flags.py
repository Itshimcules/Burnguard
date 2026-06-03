from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .config import Settings, get_settings
from .models import VirtualKey


def compute_warning_flags(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    prompt_hash: str | None,
    model: str,
    input_tokens: int,
    estimated_cost_usd: float,
    category: str,
    virtual_key: VirtualKey,
    daily_spend_usd: float,
    settings: Settings | None = None,
) -> list[str]:
    settings = settings or get_settings()
    flags: list[str] = []
    if input_tokens >= settings.large_context_token_threshold:
        flags.append("large_context")
    if prompt_hash:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_records WHERE session_id = ? AND prompt_hash = ?",
            (session_id, prompt_hash),
        ).fetchone()["n"]
        if count >= 1:
            flags.append("repeated_prompt")
    window_start = (datetime.now(timezone.utc) - timedelta(minutes=settings.loop_window_minutes)).isoformat()
    recent = conn.execute(
        "SELECT COUNT(*) AS n FROM usage_records WHERE session_id = ? AND timestamp >= ?",
        (session_id, window_start),
    ).fetchone()["n"]
    if recent + 1 >= settings.loop_request_count:
        flags.append("possible_loop")
    if model in settings.expensive_models:
        flags.append("expensive_model")
    if virtual_key.daily_budget_usd and daily_spend_usd >= virtual_key.daily_budget_usd * 0.8:
        flags.append("budget_near_limit")
    if estimated_cost_usd >= settings.high_cost_single_request_warning_usd:
        flags.append("high_cost_single_request")
    if category in {"test_output", "debugging"}:
        testish = conn.execute(
            """
            SELECT COUNT(*) AS n FROM usage_records
            WHERE session_id = ? AND request_category IN ('test_output', 'debugging')
            """,
            (session_id,),
        ).fetchone()["n"]
        if testish + 1 >= 3:
            flags.append("test_failure_loop")
    return flags
