from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator

import httpx

from .config import Settings
from .proxy import UpstreamError, parse_error_body

# Route kinds: "chat" (OpenAI Chat Completions), "responses" (OpenAI Responses),
# "anthropic" (Anthropic Messages).
STREAM_KINDS = {"chat", "responses", "anthropic"}


class StreamUsage:
    """Accumulates token usage and response text from relayed SSE chunks."""

    def __init__(self, kind: str, fallback_input_tokens: int):
        self.kind = kind
        self.fallback_input_tokens = fallback_input_tokens
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self._text_parts: list[str] = []
        self._line_buffer = ""

    def feed(self, chunk: bytes) -> None:
        self._line_buffer += chunk.decode("utf-8", errors="replace")
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                self._handle_event(obj)

    def _handle_event(self, obj: dict) -> None:
        if self.kind == "chat":
            usage = obj.get("usage")
            if isinstance(usage, dict):
                self.input_tokens = int(usage.get("prompt_tokens") or self.input_tokens or 0) or self.input_tokens
                self.output_tokens = int(usage.get("completion_tokens") or 0)
            for choice in obj.get("choices") or []:
                delta = choice.get("delta") if isinstance(choice, dict) else None
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    self._text_parts.append(delta["content"])
        elif self.kind == "responses":
            if obj.get("type") == "response.output_text.delta" and isinstance(obj.get("delta"), str):
                self._text_parts.append(obj["delta"])
            if obj.get("type") == "response.completed":
                usage = (obj.get("response") or {}).get("usage")
                if isinstance(usage, dict):
                    self.input_tokens = int(usage.get("input_tokens") or 0) or self.input_tokens
                    self.output_tokens = int(usage.get("output_tokens") or 0)
        elif self.kind == "anthropic":
            if obj.get("type") == "message_start":
                usage = (obj.get("message") or {}).get("usage")
                if isinstance(usage, dict) and usage.get("input_tokens") is not None:
                    self.input_tokens = int(usage["input_tokens"])
            if obj.get("type") == "message_delta":
                usage = obj.get("usage")
                if isinstance(usage, dict) and usage.get("output_tokens") is not None:
                    self.output_tokens = int(usage["output_tokens"])
            if obj.get("type") == "content_block_delta":
                delta = obj.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("text"), str):
                    self._text_parts.append(delta["text"])

    @property
    def response_text(self) -> str:
        return "".join(self._text_parts)

    @property
    def final_input_tokens(self) -> int:
        return self.input_tokens if self.input_tokens is not None else self.fallback_input_tokens

    @property
    def final_output_tokens(self) -> int:
        if self.output_tokens is not None:
            return self.output_tokens
        return max(1, len(self.response_text) // 4) if self.response_text else 0


def _sse(data: dict, event: str | None = None) -> bytes:
    prefix = f"event: {event}\n" if event else ""
    return (prefix + "data: " + json.dumps(data) + "\n\n").encode("utf-8")


MOCK_STREAM_TEXT = "Burnguard mock streaming response: request allowed and metered without calling a paid provider."


async def _mock_chat_stream(payload: dict, input_tokens: int) -> AsyncIterator[bytes]:
    model = payload.get("model", "mock-cheap")
    completion_id = f"chatcmpl_mock_{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    base = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model}
    words = MOCK_STREAM_TEXT.split(" ")
    yield _sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]})
    for idx in range(0, len(words), 4):
        text = " ".join(words[idx:idx + 4]) + (" " if idx + 4 < len(words) else "")
        yield _sse({**base, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]})
    output_tokens = max(12, len(MOCK_STREAM_TEXT) // 4)
    yield _sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    yield _sse({**base, "choices": [], "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}})
    yield b"data: [DONE]\n\n"


async def _mock_responses_stream(payload: dict, input_tokens: int) -> AsyncIterator[bytes]:
    model = payload.get("model", "mock-cheap")
    response_id = f"resp_mock_{uuid.uuid4().hex[:12]}"
    output_tokens = max(12, len(MOCK_STREAM_TEXT) // 4)
    response_obj = {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model,
        "output_text": MOCK_STREAM_TEXT,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens},
    }
    yield _sse({"type": "response.created", "response": {**response_obj, "status": "in_progress", "output_text": ""}}, event="response.created")
    words = MOCK_STREAM_TEXT.split(" ")
    for idx in range(0, len(words), 4):
        text = " ".join(words[idx:idx + 4]) + (" " if idx + 4 < len(words) else "")
        yield _sse({"type": "response.output_text.delta", "delta": text}, event="response.output_text.delta")
    yield _sse({"type": "response.completed", "response": response_obj}, event="response.completed")


async def _mock_anthropic_stream(payload: dict, input_tokens: int) -> AsyncIterator[bytes]:
    model = payload.get("model", "claude-sonnet")
    message_id = f"msg_mock_{uuid.uuid4().hex[:12]}"
    output_tokens = max(12, len(MOCK_STREAM_TEXT) // 4)
    yield _sse(
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": input_tokens, "output_tokens": 1},
            },
        },
        event="message_start",
    )
    yield _sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}, event="content_block_start")
    words = MOCK_STREAM_TEXT.split(" ")
    for idx in range(0, len(words), 4):
        text = " ".join(words[idx:idx + 4]) + (" " if idx + 4 < len(words) else "")
        yield _sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}, event="content_block_delta")
    yield _sse({"type": "content_block_stop", "index": 0}, event="content_block_stop")
    yield _sse({"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": output_tokens}}, event="message_delta")
    yield _sse({"type": "message_stop"}, event="message_stop")


def _proxy_request(kind: str, payload: dict, settings: Settings) -> tuple[str, dict[str, str], dict]:
    if kind == "anthropic":
        url = settings.anthropic_base_url.rstrip("/") + "/messages"
        headers = {
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": settings.anthropic_version,
            "Content-Type": "application/json",
        }
        return url, headers, payload
    headers = {"Authorization": f"Bearer {settings.openai_compatible_api_key}", "Content-Type": "application/json"}
    if kind == "responses":
        return settings.openai_compatible_base_url.rstrip("/") + "/responses", headers, payload
    body = dict(payload)
    # Ask the upstream to include usage in the final chunk so metering is exact.
    body.setdefault("stream_options", {"include_usage": True})
    return settings.openai_compatible_base_url.rstrip("/") + "/chat/completions", headers, body


async def open_stream(kind: str, payload: dict, settings: Settings, usage: StreamUsage, mock_input_tokens: int) -> AsyncIterator[bytes]:
    """Open an SSE stream for the route kind. Raises UpstreamError before the first
    chunk if the upstream rejects the request, so the caller can pass the error
    through with its original status code."""
    if settings.mode == "mock":
        mock = {
            "chat": _mock_chat_stream,
            "responses": _mock_responses_stream,
            "anthropic": _mock_anthropic_stream,
        }[kind]
        inner = mock(payload, mock_input_tokens)

        async def mock_relay() -> AsyncIterator[bytes]:
            async for chunk in inner:
                usage.feed(chunk)
                yield chunk

        return mock_relay()

    url, headers, body = _proxy_request(kind, payload, settings)
    client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10))
    try:
        request = client.build_request("POST", url, headers=headers, json=body)
        response = await client.send(request, stream=True)
        if response.status_code >= 400:
            raw = await response.aread()
            await response.aclose()
            raise UpstreamError(response.status_code, parse_error_body(raw))
    except UpstreamError:
        await client.aclose()
        raise
    except Exception:
        await client.aclose()
        raise

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                usage.feed(chunk)
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return relay()


def stream_media_type(kind: str) -> str:
    return "text/event-stream"


def route_kind(route_path: str) -> str:
    return {
        "/v1/chat/completions": "chat",
        "/v1/responses": "responses",
        "/v1/messages": "anthropic",
    }[route_path]


__all__ = [
    "StreamUsage",
    "open_stream",
    "route_kind",
    "stream_media_type",
    "STREAM_KINDS",
    "MOCK_STREAM_TEXT",
]
