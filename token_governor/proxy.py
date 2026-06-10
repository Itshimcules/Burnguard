from __future__ import annotations

import time
import uuid
from typing import Any

import json

import httpx

from .config import Settings, get_settings


class UpstreamError(Exception):
    """Upstream provider returned an error response that should be passed through verbatim."""

    def __init__(self, status_code: int, body: dict):
        super().__init__(f"Upstream returned HTTP {status_code}")
        self.status_code = status_code
        self.body = body


def parse_error_body(raw: bytes | str) -> dict:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"error": {"message": text[:500] or "Upstream provider error", "type": "upstream_error"}}


def raise_for_upstream(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise UpstreamError(response.status_code, parse_error_body(response.content))


def _text_length(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        total = 0
        text_keys = {"text", "content", "input", "input_text", "output_text", "system"}
        metadata_keys = {"role", "type", "id", "name", "status", "stop_reason", "stop_sequence"}
        for key, item in value.items():
            if key in text_keys or isinstance(item, (dict, list)):
                total += _text_length(item)
            elif key not in metadata_keys and not isinstance(item, (int, float, bool)):
                total += _text_length(item)
        return total
    if isinstance(value, list):
        return sum(_text_length(item) for item in value)
    return len(str(value))


def estimate_text_tokens(value: Any) -> int:
    chars = _text_length(value)
    return max(1, chars // 4) if chars else 0


def estimate_message_tokens(messages: list[dict] | None) -> int:
    if not messages:
        return 0
    chars = 0
    for message in messages:
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        chars += _text_length(content)
    return max(1, chars // 4)


def estimate_response_input_tokens(payload: dict) -> int:
    token_sources: list[Any] = [payload.get("input")]
    if payload.get("instructions"):
        token_sources.append(payload["instructions"])
    return estimate_text_tokens(token_sources)


def estimate_anthropic_input_tokens(payload: dict) -> int:
    token_sources: list[Any] = [payload.get("messages")]
    if payload.get("system"):
        token_sources.append(payload["system"])
    return estimate_text_tokens(token_sources)


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def mock_chat_completion(payload: dict, input_tokens: int) -> tuple[dict, int, int]:
    output_text = "Burnguard mock response: request allowed and metered without calling a paid provider."
    output_tokens = max(12, len(output_text) // 4)
    model = payload.get("model", "mock-cheap")
    response = {
        "id": f"chatcmpl_mock_{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": output_text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens, "total_tokens": input_tokens + output_tokens},
    }
    return response, input_tokens, output_tokens


def mock_response(payload: dict, input_tokens: int) -> tuple[dict, int, int]:
    output_text = "Burnguard mock response: Responses API request allowed and metered without calling a paid provider."
    output_tokens = max(12, len(output_text) // 4)
    model = payload.get("model", "mock-cheap")
    response = {
        "id": f"resp_mock_{uuid.uuid4().hex[:12]}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model,
        "output_text": output_text,
        "output": [
            {
                "id": f"msg_mock_{uuid.uuid4().hex[:12]}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output_text, "annotations": []}],
            }
        ],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens},
    }
    return response, input_tokens, output_tokens


def mock_anthropic_message(payload: dict, input_tokens: int) -> tuple[dict, int, int]:
    output_text = "Burnguard mock response: Anthropic Messages request allowed and metered without calling a paid provider."
    output_tokens = max(12, len(output_text) // 4)
    model = payload.get("model", "claude-sonnet")
    response = {
        "id": f"msg_mock_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": output_text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    return response, input_tokens, output_tokens


async def forward_chat_completion(payload: dict, settings: Settings | None = None) -> tuple[dict, int, int]:
    settings = settings or get_settings()
    input_tokens = estimate_message_tokens(payload.get("messages"))
    if settings.mode == "mock":
        return mock_chat_completion(payload, input_tokens)

    url = settings.openai_compatible_base_url.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=_headers(settings.openai_compatible_api_key), json=payload)
        raise_for_upstream(response)
        data = response.json()
    usage = data.get("usage", {})
    return data, int(usage.get("prompt_tokens", input_tokens)), int(usage.get("completion_tokens", 0))


async def forward_response(payload: dict, settings: Settings | None = None) -> tuple[dict, int, int]:
    settings = settings or get_settings()
    input_tokens = estimate_response_input_tokens(payload)
    if settings.mode == "mock":
        return mock_response(payload, input_tokens)

    url = settings.openai_compatible_base_url.rstrip("/") + "/responses"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=_headers(settings.openai_compatible_api_key), json=payload)
        raise_for_upstream(response)
        data = response.json()
    usage = data.get("usage", {})
    return data, int(usage.get("input_tokens", input_tokens)), int(usage.get("output_tokens", 0))


async def forward_anthropic_message(payload: dict, settings: Settings | None = None) -> tuple[dict, int, int]:
    settings = settings or get_settings()
    input_tokens = estimate_anthropic_input_tokens(payload)
    if settings.mode == "mock":
        return mock_anthropic_message(payload, input_tokens)

    url = settings.anthropic_base_url.rstrip("/") + "/messages"
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": settings.anthropic_version,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        raise_for_upstream(response)
        data = response.json()
    usage = data.get("usage", {})
    return data, int(usage.get("input_tokens", input_tokens)), int(usage.get("output_tokens", 0))
