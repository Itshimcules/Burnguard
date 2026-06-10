from token_governor.pricing import estimate_cost, get_model_pricing


def test_pricing_calculation() -> None:
    assert get_model_pricing("gpt-4o-mini")["input_per_1m"] == 0.15
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == 0.75


def test_claude_sonnet_alias_uses_anthropic_demo_pricing() -> None:
    assert estimate_cost("claude-3-5-sonnet-latest", 1_000_000, 1_000_000) == 18.0


def test_pricing_file_overrides_defaults(tmp_path, monkeypatch):
    import json

    from token_governor.config import Settings
    from token_governor.pricing import clear_pricing_cache, get_model_pricing, has_model_pricing

    pricing_file = tmp_path / "pricing.json"
    pricing_file.write_text(json.dumps({
        "gpt-4o-mini": {"input_per_1m": 9.0, "output_per_1m": 18.0},
        "my-internal-model": {"input_per_1m": 0.5, "output_per_1m": 1.0},
    }))
    settings = Settings(model_pricing_file=str(pricing_file))
    clear_pricing_cache()
    try:
        assert get_model_pricing("gpt-4o-mini", settings)["input_per_1m"] == 9.0
        assert has_model_pricing("my-internal-model", settings)
        assert not has_model_pricing("unknown-model", settings)
    finally:
        clear_pricing_cache()


def test_real_model_pricing_entries_exist():
    from token_governor.pricing import DEFAULT_MODEL_PRICING

    for model in ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5", "gpt-4o", "gpt-5"]:
        assert model in DEFAULT_MODEL_PRICING
