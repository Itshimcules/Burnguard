from token_governor.privacy import safe_preview, stable_hash


def test_stable_hash_is_deterministic_for_structured_values() -> None:
    left = {"messages": [{"role": "user", "content": "hello"}]}
    right = {"messages": [{"content": "hello", "role": "user"}]}
    assert stable_hash(left) == stable_hash(right)


def test_safe_preview_redacts_common_secrets_and_caps_length() -> None:
    preview = safe_preview("Authorization: Bearer sk-testsecret123456789 email dev@example.com " + "x" * 300)
    assert "sk-testsecret" not in preview
    assert "dev@example.com" not in preview
    assert "[REDACTED" in preview
    assert len(preview) == 200


def test_safe_preview_redacts_burnguard_virtual_keys() -> None:
    preview = safe_preview("use tg_sk_demo and tg_sk_codex_project_a please")
    assert "tg_sk_demo" not in preview
    assert "tg_sk_codex_project_a" not in preview
    assert "[REDACTED_KEY]" in preview
