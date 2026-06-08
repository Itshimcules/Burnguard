from fastapi.testclient import TestClient

import token_governor.main as main_module
from token_governor.config import Settings
from token_governor.db import connect, create_virtual_key, init_db
from token_governor.main import app
from token_governor.models import VirtualKey


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
