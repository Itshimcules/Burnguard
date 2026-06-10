from __future__ import annotations

DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gpt-4.1": {"input_per_1m": 2.00, "output_per_1m": 8.00},
    "claude-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "claude-3-5-sonnet-latest": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "claude-3-7-sonnet-latest": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "mock-cheap": {"input_per_1m": 0.10, "output_per_1m": 0.20},
}
FALLBACK_MODEL_PRICING = {"input_per_1m": 1.00, "output_per_1m": 3.00}


def has_model_pricing(model: str) -> bool:
    return model in DEFAULT_MODEL_PRICING


def get_model_pricing(model: str) -> dict[str, float]:
    return DEFAULT_MODEL_PRICING.get(model, FALLBACK_MODEL_PRICING)


def estimate_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    pricing = get_model_pricing(model)
    return round(
        (input_tokens / 1_000_000 * pricing["input_per_1m"])
        + (output_tokens / 1_000_000 * pricing["output_per_1m"]),
        6,
    )
