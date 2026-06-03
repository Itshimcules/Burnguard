from fastapi.testclient import TestClient

from token_governor.main import app


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
