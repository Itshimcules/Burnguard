from __future__ import annotations

import json
from pathlib import Path

from .config import Settings, get_settings

# USD per 1M tokens. Prices drift — verify against provider pricing pages and
# override stale or missing entries via MODEL_PRICING_FILE without forking.
DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gpt-4.1": {"input_per_1m": 2.00, "output_per_1m": 8.00},
    "gpt-4.1-mini": {"input_per_1m": 0.40, "output_per_1m": 1.60},
    "gpt-4.1-nano": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gpt-5": {"input_per_1m": 1.25, "output_per_1m": 10.00},
    "gpt-5-mini": {"input_per_1m": 0.25, "output_per_1m": 2.00},
    "o3": {"input_per_1m": 2.00, "output_per_1m": 8.00},
    "o4-mini": {"input_per_1m": 1.10, "output_per_1m": 4.40},
    # Anthropic
    "claude-opus-4-8": {"input_per_1m": 5.00, "output_per_1m": 25.00},
    "claude-opus-4-7": {"input_per_1m": 5.00, "output_per_1m": 25.00},
    "claude-opus-4-6": {"input_per_1m": 5.00, "output_per_1m": 25.00},
    "claude-sonnet-4-6": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "claude-sonnet-4-5": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "claude-haiku-4-5": {"input_per_1m": 1.00, "output_per_1m": 5.00},
    # Demo aliases kept for seeded data and older configs
    "claude-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "claude-3-5-sonnet-latest": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "claude-3-7-sonnet-latest": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "mock-cheap": {"input_per_1m": 0.10, "output_per_1m": 0.20},
}
FALLBACK_MODEL_PRICING = {"input_per_1m": 1.00, "output_per_1m": 3.00}

_override_cache: dict[str, dict[str, dict[str, float]]] = {}


def _file_overrides(settings: Settings) -> dict[str, dict[str, float]]:
    path = settings.model_pricing_file
    if not path:
        return {}
    if path in _override_cache:
        return _override_cache[path]
    overrides: dict[str, dict[str, float]] = {}
    pricing_file = Path(path)
    if pricing_file.exists():
        try:
            data = json.loads(pricing_file.read_text())
        except json.JSONDecodeError:
            data = {}
        for model, entry in data.items() if isinstance(data, dict) else []:
            if isinstance(entry, dict) and "input_per_1m" in entry and "output_per_1m" in entry:
                overrides[str(model)] = {
                    "input_per_1m": float(entry["input_per_1m"]),
                    "output_per_1m": float(entry["output_per_1m"]),
                }
    _override_cache[path] = overrides
    return overrides


def clear_pricing_cache() -> None:
    _override_cache.clear()


def get_pricing_table(settings: Settings | None = None) -> dict[str, dict[str, float]]:
    settings = settings or get_settings()
    return {**DEFAULT_MODEL_PRICING, **_file_overrides(settings)}


def has_model_pricing(model: str, settings: Settings | None = None) -> bool:
    return model in get_pricing_table(settings)


def get_model_pricing(model: str, settings: Settings | None = None) -> dict[str, float]:
    return get_pricing_table(settings).get(model, FALLBACK_MODEL_PRICING)


def estimate_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    pricing = get_model_pricing(model)
    return round(
        (input_tokens / 1_000_000 * pricing["input_per_1m"])
        + (output_tokens / 1_000_000 * pricing["output_per_1m"]),
        6,
    )
