from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool | None = False

    model_config = {"extra": "allow"}


class ErrorResponse(BaseModel):
    error: dict[str, Any]
