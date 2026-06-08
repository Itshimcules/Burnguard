from token_governor.pricing import estimate_cost, get_model_pricing


def test_pricing_calculation() -> None:
    assert get_model_pricing("gpt-4o-mini")["input_per_1m"] == 0.15
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == 0.75


def test_claude_sonnet_alias_uses_anthropic_demo_pricing() -> None:
    assert estimate_cost("claude-3-5-sonnet-latest", 1_000_000, 1_000_000) == 18.0
