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

    assert client.get("/").status_code == 200
    assert client.get("/keys").status_code == 200
    assert client.get("/sessions").status_code == 200
    assert client.get("/requests").status_code == 200


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
