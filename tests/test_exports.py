from datetime import datetime, timedelta, timezone

from token_governor.db import create_virtual_key, init_db, insert_usage
from token_governor.exports import ExportFilters, SESSION_EXPORT_COLUMNS, request_rows, session_rows, to_csv
from token_governor.models import UsageRecord, VirtualKey


def _key(conn):
    return create_virtual_key(conn, VirtualKey(None, "bg_sk_export", "Export", "analytics", ["gpt-4o-mini"], 5, 100, 1))


def _record(key, request_id: str, session_id: str, status: str = "allowed", flags: list[str] | None = None, minutes_ago: int = 0):
    return UsageRecord(
        request_id=request_id,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        virtual_key_id=key.id,
        virtual_key=key.key,
        owner=key.owner,
        project=key.project,
        session_id=session_id,
        provider="mock",
        model="gpt-4o-mini",
        estimated_input_tokens=100,
        estimated_output_tokens=50,
        total_tokens=150,
        estimated_cost_usd=0.01,
        status=status,
        block_reason="daily_budget_exceeded" if status == "blocked" else None,
        latency_ms=25,
        route_path="/v1/chat/completions",
        user_agent="pytest",
        request_category="code_generation",
        warning_flags=flags or [],
        prompt_hash=f"prompt-{request_id}",
        response_hash=f"response-{request_id}",
        prompt_preview="Write code",
        response_preview="Done",
    )


def test_request_export_filters_rows(conn):
    init_db(conn)
    key = _key(conn)
    insert_usage(conn, _record(key, "req_export_1", "session-a"))
    insert_usage(conn, _record(key, "req_export_2", "session-b", status="blocked"))

    rows = request_rows(conn, ExportFilters(session_id="session-b"))

    assert len(rows) == 1
    assert rows[0]["request_id"] == "req_export_2"
    assert rows[0]["block_reason"] == "daily_budget_exceeded"


def test_session_export_aggregates_and_csv(conn):
    init_db(conn)
    key = _key(conn)
    insert_usage(conn, _record(key, "req_export_1", "session-a", flags=["possible_loop"], minutes_ago=2))
    insert_usage(conn, _record(key, "req_export_2", "session-a", status="blocked", flags=["budget_near_limit"], minutes_ago=1))

    rows = session_rows(conn, ExportFilters(session_id="session-a"))
    csv_text = to_csv(rows, SESSION_EXPORT_COLUMNS)

    assert rows[0]["request_count"] == 2
    assert rows[0]["blocked_requests"] == 1
    assert rows[0]["total_tokens"] == 300
    assert "possible_loop" in rows[0]["warning_flags"]
    assert "budget_near_limit" in rows[0]["warning_flags"]
    assert csv_text.startswith("session_id,owner,project")
    assert "session-a" in csv_text
