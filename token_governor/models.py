from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class VirtualKey:
    id: int | None
    key: str
    owner: str
    project: str
    allowed_models: list[str]
    daily_budget_usd: float
    monthly_budget_usd: float
    max_single_request_usd: float
    provider: str = "openai-compatible"
    enabled: bool = True
    created_at: datetime | None = None


@dataclass
class UsageRecord:
    request_id: str
    timestamp: datetime
    virtual_key_id: int | None
    virtual_key: str | None
    owner: str | None
    project: str | None
    session_id: str
    provider: str
    model: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    status: str
    block_reason: str | None
    latency_ms: int
    route_path: str
    user_agent: str | None
    request_category: str
    warning_flags: list[str]
    prompt_hash: str | None
    response_hash: str | None
    prompt_preview: str | None
    response_preview: str | None
    raw_messages: Any | None = None
    raw_response: Any | None = None
