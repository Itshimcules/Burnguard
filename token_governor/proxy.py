from __future__ import annotations

import time
import uuid

import httpx

from .config import Settings, get_settings



def estimate_message_tokens(messages: list[dict] | None) -> int:
    if not messages:
        return 0
    chars = 0
    for message in messages:
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        chars += len(str(content))
    return max(1, chars // 4)


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


async def forward_chat_completion(payload: dict, settings: Settings | None = None) -> tuple[dict, int, int]:
    settings = settings or get_settings()
    input_tokens = estimate_message_tokens(payload.get("messages"))
    if settings.mode == "mock":
        return mock_chat_completion(payload, input_tokens)

    url = settings.openai_compatible_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_compatible_api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    usage = data.get("usage", {})
    return data, int(usage.get("prompt_tokens", input_tokens)), int(usage.get("completion_tokens", 0))
