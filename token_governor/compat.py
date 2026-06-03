from __future__ import annotations


def is_streaming_request(payload: dict) -> bool:
    return payload.get("stream") is True
