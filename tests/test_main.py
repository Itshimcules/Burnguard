from fastapi.testclient import TestClient

import token_governor.main as main_module
from token_governor.config import Settings
from token_governor.db import connect, create_virtual_key, init_db
from token_governor.main import app
from token_governor.models import VirtualKey


def test_dashboard_pages_render(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'dashboard.db'}"
    test_settings = Settings(database_url=database_url)
    monkeypatch.setattr(main_module, "settings", test_settings)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_dashboard", "Dashboard", "demo", ["gpt-4o-mini"], 5, 100, 1))
        conn.commit()

    client = TestClient(app)

    overview = client.get("/")
    assert overview.status_code == 200
    assert "mock mode" in overview.text
    assert 'aria-current="page">Overview' in overview.text
    assert "Start a clean demo" in overview.text
    assert "No usage recorded yet." in overview.text

    keys = client.get("/keys")
    assert keys.status_code == 200
    assert 'aria-current="page">Keys' in keys.text

    sessions = client.get("/sessions")
    assert sessions.status_code == 200
    assert 'aria-current="page">Sessions' in sessions.text
    assert "No sessions yet." in sessions.text

    requests = client.get("/requests")
    assert requests.status_code == 200
    assert 'aria-current="page">Requests' in requests.text
    assert "No requests yet." in requests.text

    missing_session = client.get("/sessions/missing")
    assert missing_session.status_code == 200
    assert 'aria-current="page">Sessions' in missing_session.text
    assert "No requests recorded for this session." in missing_session.text


def test_chat_completions_rejects_streaming_requests():
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "message": "Streaming is not supported in this MVP.",
            "type": "unsupported_feature",
        }
    }


def test_responses_api_mock_request_is_metered(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'responses.db'}"
    test_settings = Settings(database_url=database_url)
    monkeypatch.setattr(main_module, "settings", test_settings)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_responses", "Responses", "demo", ["gpt-4o-mini"], 5, 100, 1))
        conn.commit()

    client = TestClient(app)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer tg_sk_responses", "X-Token-Governor-Session": "responses-session"},
        json={"model": "gpt-4o-mini", "input": "Write a short function.", "max_output_tokens": 64},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["usage"]["input_tokens"] > 0
    with connect(test_settings) as conn:
        row = conn.execute("SELECT route_path, status, session_id FROM usage_records").fetchone()
    assert row["route_path"] == "/v1/responses"
    assert row["status"] == "allowed"
    assert row["session_id"] == "responses-session"


def test_hermes_style_chat_completion_request_is_metered(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'hermes.db'}"
    test_settings = Settings(database_url=database_url)
    monkeypatch.setattr(main_module, "settings", test_settings)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_hermes", "Hermes", "agent-demo", ["gpt-4o-mini"], 5, 100, 1))
        conn.commit()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer tg_sk_hermes",
            "X-Token-Governor-Session": "hermes-agent-session",
            "User-Agent": "Hermes-Agent/1.0",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Confirm Burnguard metering in one sentence."}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["usage"]["prompt_tokens"] > 0
    with connect(test_settings) as conn:
        row = conn.execute("SELECT route_path, status, session_id, user_agent, model FROM usage_records").fetchone()
    assert row["route_path"] == "/v1/chat/completions"
    assert row["status"] == "allowed"
    assert row["session_id"] == "hermes-agent-session"
    assert row["user_agent"] == "Hermes-Agent/1.0"
    assert row["model"] == "gpt-4o-mini"


def test_usage_exports_metrics_and_pr_tool_metadata(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'roadmap.db'}"
    test_settings = Settings(database_url=database_url)
    monkeypatch.setattr(main_module, "settings", test_settings)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_roadmap", "Roadmap", "demo", ["gpt-4o-mini"], 5, 100, 1))
        conn.commit()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer tg_sk_roadmap",
            "X-Token-Governor-Session": "pr-session",
            "X-Token-Governor-GitHub-Repo": "Itshimcules/Burnguard",
            "X-Token-Governor-GitHub-PR": "8",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": "Review token_governor/main.py and tests/test_main.py."},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
                },
            ],
            "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
        },
    )

    assert response.status_code == 200
    with connect(test_settings) as conn:
        row = conn.execute("SELECT github_repo, github_pr, tool_call_count, tool_names, context_hash FROM usage_records").fetchone()
    assert row["github_repo"] == "Itshimcules/Burnguard"
    assert row["github_pr"] == "8"
    assert row["tool_call_count"] == 1
    assert "read_file" in row["tool_names"]
    assert row["context_hash"]

    json_export = client.get("/exports/usage.json")
    assert json_export.status_code == 200
    assert json_export.json()["records"][0]["github_pr"] == "8"

    csv_export = client.get("/exports/usage.csv")
    assert csv_export.status_code == 200
    assert "github_pr" in csv_export.text
    assert "read_file" in csv_export.text

    report = client.get("/reports/pull-requests")
    assert report.status_code == 200
    assert report.json()["pull_requests"][0]["github_repo"] == "Itshimcules/Burnguard"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "burnguard_requests_allowed_total 1.0" in metrics.text


def test_blocked_request_sends_webhook_alert(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'alerts.db'}"
    test_settings = Settings(database_url=database_url, slack_webhook_url="https://example.invalid/slack")
    monkeypatch.setattr(main_module, "settings", test_settings)
    seen = []

    async def fake_send_alert(record, settings):
        seen.append((record.status, record.block_reason, settings.slack_webhook_url))

    monkeypatch.setattr(main_module, "send_alert", fake_send_alert)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_alert", "Alert", "demo", ["gpt-4.1"], 5, 100, 0.000001))
        conn.commit()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer tg_sk_alert"},
        json={"model": "gpt-4.1", "messages": [{"role": "user", "content": "Use a large request."}], "max_tokens": 1000},
    )

    assert response.status_code == 402
    assert seen == [("blocked", "max_single_request_exceeded", "https://example.invalid/slack")]


def test_responses_api_rejects_streaming_requests():
    client = TestClient(app)

    response = client.post(
        "/v1/responses",
        json={"model": "gpt-4o-mini", "stream": True, "input": "hello"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "message": "Streaming is not supported in this MVP.",
            "type": "unsupported_feature",
        }
    }


def test_openclaw_style_responses_request_is_metered(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'openclaw.db'}"
    test_settings = Settings(database_url=database_url)
    monkeypatch.setattr(main_module, "settings", test_settings)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_openclaw", "OpenClaw", "agent-demo", ["gpt-4o-mini"], 5, 100, 1))
        conn.commit()

    client = TestClient(app)
    response = client.post(
        "/v1/responses",
        headers={
            "Authorization": "Bearer tg_sk_openclaw",
            "X-Token-Governor-Session": "openclaw-agent-session",
            "User-Agent": "OpenClaw/1.0",
        },
        json={
            "model": "gpt-4o-mini",
            "input": "Confirm Burnguard metering in one sentence.",
            "max_output_tokens": 64,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["usage"]["input_tokens"] > 0
    with connect(test_settings) as conn:
        row = conn.execute("SELECT route_path, status, session_id, user_agent, model FROM usage_records").fetchone()
    assert row["route_path"] == "/v1/responses"
    assert row["status"] == "allowed"
    assert row["session_id"] == "openclaw-agent-session"
    assert row["user_agent"] == "OpenClaw/1.0"
    assert row["model"] == "gpt-4o-mini"


def test_anthropic_messages_mock_request_accepts_x_api_key_and_is_metered(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'anthropic.db'}"
    test_settings = Settings(database_url=database_url)
    monkeypatch.setattr(main_module, "settings", test_settings)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_anthropic", "Anthropic", "demo", ["claude-sonnet"], 5, 100, 1, provider="anthropic"))
        conn.commit()

    client = TestClient(app)
    response = client.post(
        "/v1/messages",
        headers={"X-Api-Key": "tg_sk_anthropic", "X-Token-Governor-Session": "anthropic-session"},
        json={
            "model": "claude-sonnet",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "Write a short function."}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "message"
    assert body["usage"]["input_tokens"] > 0
    with connect(test_settings) as conn:
        row = conn.execute("SELECT route_path, provider, status, session_id FROM usage_records").fetchone()
    assert row["route_path"] == "/v1/messages"
    assert row["provider"] == "anthropic"
    assert row["status"] == "allowed"
    assert row["session_id"] == "anthropic-session"


def test_anthropic_messages_rejects_streaming_requests():
    client = TestClient(app)

    response = client.post(
        "/v1/messages",
        json={"model": "claude-sonnet", "max_tokens": 64, "stream": True, "messages": []},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "message": "Streaming is not supported in this MVP.",
            "type": "unsupported_feature",
        }
    }


def test_chat_completions_rejects_streaming_requested_as_string():
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "stream": "true", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "unsupported_feature"


def test_malformed_json_returns_openai_shaped_400():
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer tg_sk_demo", "Content-Type": "application/json"},
        content="not json",
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["message"]


def test_unknown_key_returns_openai_shaped_401(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'auth401.db'}"
    test_settings = Settings(database_url=database_url)
    monkeypatch.setattr(main_module, "settings", test_settings)

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer tg_sk_does_not_exist"},
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["type"] == "authentication_error"
    assert body["error"]["code"] == "invalid_api_key"


def test_disallowed_model_returns_openai_shaped_403(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'auth403.db'}"
    test_settings = Settings(database_url=database_url)
    monkeypatch.setattr(main_module, "settings", test_settings)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_limited", "Limited", "demo", ["gpt-4o-mini"], 5, 100, 1))
        conn.commit()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer tg_sk_limited"},
        json={"model": "gpt-4.1", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "model_not_allowed"


def test_unreachable_alert_webhook_does_not_break_blocked_response(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'deadhook.db'}"
    test_settings = Settings(database_url=database_url, slack_webhook_url="http://127.0.0.1:9/unreachable")
    monkeypatch.setattr(main_module, "settings", test_settings)
    with connect(test_settings) as conn:
        init_db(conn)
        create_virtual_key(conn, VirtualKey(None, "tg_sk_deadhook", "Deadhook", "demo", ["gpt-4.1"], 5, 100, 0.000001))
        conn.commit()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer tg_sk_deadhook"},
        json={"model": "gpt-4.1", "messages": [{"role": "user", "content": "Use a large request."}], "max_tokens": 1000},
    )

    assert response.status_code == 402
    assert response.json()["error"]["type"] == "budget_exceeded"
