from datetime import datetime, timezone

from token_governor.budget import check_budget
from token_governor.db import create_virtual_key, init_db, insert_usage
from token_governor.models import UsageRecord, VirtualKey


def _key(conn, daily=1.0, monthly=10.0, max_request=1.0):
    key = VirtualKey(None, "tg_sk_test", "Test", "demo", ["gpt-4o-mini", "gpt-4.1"], daily, monthly, max_request)
    return create_virtual_key(conn, key)


def _record(key, cost):
    return UsageRecord(
        request_id=f"req_{cost}", timestamp=datetime.now(timezone.utc), virtual_key_id=key.id, virtual_key=key.key,
        owner=key.owner, project=key.project, session_id="s", provider="mock", model="gpt-4o-mini",
        estimated_input_tokens=1, estimated_output_tokens=1, total_tokens=2, estimated_cost_usd=cost,
        status="allowed", block_reason=None, latency_ms=1, route_path="/v1/chat/completions", user_agent=None,
        request_category="general_chat", warning_flags=[], prompt_hash="h", response_hash="r", prompt_preview="p", response_preview="r"
    )


def test_budget_blocks_daily_overage(conn):
    init_db(conn)
    key = _key(conn, daily=0.01)
    insert_usage(conn, _record(key, 0.02))
    decision = check_budget(conn, key, "gpt-4o-mini", 10, 10)
    assert not decision.allowed
    assert decision.reason == "daily_budget_exceeded"


def test_budget_blocks_max_single_request(conn):
    init_db(conn)
    key = _key(conn, max_request=0.001)
    decision = check_budget(conn, key, "gpt-4.1", 1_000_000, 1_000_000)
    assert not decision.allowed
    assert decision.reason == "max_single_request_exceeded"
