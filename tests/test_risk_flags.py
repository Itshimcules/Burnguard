from datetime import datetime, timezone

from token_governor.config import Settings
from token_governor.db import create_virtual_key, init_db, insert_usage
from token_governor.models import UsageRecord, VirtualKey
from token_governor.risk_flags import compute_warning_flags


def _key(conn):
    return create_virtual_key(conn, VirtualKey(None, "tg_sk_risk", "Risk", "demo", ["gpt-4o-mini"], 5, 100, 1))


def _record(key, request_id, prompt_hash="same", category="general_chat"):
    return UsageRecord(
        request_id=request_id, timestamp=datetime.now(timezone.utc), virtual_key_id=key.id, virtual_key=key.key,
        owner=key.owner, project=key.project, session_id="loop", provider="mock", model="gpt-4o-mini",
        estimated_input_tokens=1, estimated_output_tokens=1, total_tokens=2, estimated_cost_usd=0.0,
        status="allowed", block_reason=None, latency_ms=1, route_path="/v1/chat/completions", user_agent=None,
        request_category=category, warning_flags=[], prompt_hash=prompt_hash, response_hash="r", prompt_preview="p", response_preview="r"
    )


def test_repeated_prompt_flag_works(conn):
    init_db(conn)
    key = _key(conn)
    insert_usage(conn, _record(key, "req_one", prompt_hash="abc"))
    flags = compute_warning_flags(conn, session_id="loop", prompt_hash="abc", model="gpt-4o-mini", input_tokens=10, estimated_cost_usd=0.01, category="general_chat", virtual_key=key, daily_spend_usd=0)
    assert "repeated_prompt" in flags


def test_possible_loop_flag_works(conn):
    init_db(conn)
    key = _key(conn)
    for i in range(2):
        insert_usage(conn, _record(key, f"req_loop_{i}", prompt_hash=str(i)))
    settings = Settings(loop_request_count=3, loop_window_minutes=15)
    flags = compute_warning_flags(conn, session_id="loop", prompt_hash="new", model="gpt-4o-mini", input_tokens=10, estimated_cost_usd=0.01, category="general_chat", virtual_key=key, daily_spend_usd=0, settings=settings)
    assert "possible_loop" in flags


def test_repeated_context_flag_works(conn):
    init_db(conn)
    key = _key(conn)
    for idx in range(2):
        record = _record(key, f"req_context_{idx}", prompt_hash=f"context-{idx}")
        record.context_hash = "same-files"
        insert_usage(conn, record)

    flags = compute_warning_flags(
        conn,
        session_id="loop",
        prompt_hash="new",
        model="gpt-4o-mini",
        input_tokens=10,
        estimated_cost_usd=0.01,
        category="general_chat",
        virtual_key=key,
        daily_spend_usd=0,
        context_hash="same-files",
    )

    assert "repeated_context" in flags
