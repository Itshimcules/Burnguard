from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_PREVIEW_CHARS = 200

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|api[_-]?key|authorization|password|secret|token)\s*[:=]\s*['\"]?[^\s,'\"}]+"), r"\1=[REDACTED]"),
    (re.compile(r"\b(?:sk|tg_sk|bg_sk|ant|or)-[A-Za-z0-9_\-]{8,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
)


def stable_hash(value: Any) -> str:
    """Return a deterministic hash for prompt/response comparison without storing raw text."""
    text = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")) if not isinstance(value, str) else value
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact_text(text: str) -> str:
    """Apply lightweight redaction for previews; raw storage is controlled separately."""
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def safe_preview(value: Any, max_chars: int = MAX_PREVIEW_CHARS) -> str:
    """Return a compact, redacted preview capped to max_chars."""
    text = json.dumps(value, default=str) if not isinstance(value, str) else value
    compact = " ".join(text.replace("\n", " ").split())
    return redact_text(compact)[:max_chars]
