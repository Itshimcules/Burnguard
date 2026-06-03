from token_governor.pricing import estimate_cost, get_model_pricing


def test_pricing_calculation() -> None:
    assert get_model_pricing("gpt-4o-mini")["input_per_1m"] == 0.15
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == 0.75
