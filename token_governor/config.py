from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mode: str = "mock"
    database_url: str = "sqlite:///./token_governor.db"
    openai_compatible_base_url: str = "https://api.openai.com/v1"
    openai_compatible_api_key: str = "replace_me"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_api_key: str = "replace_me"
    anthropic_version: str = "2023-06-01"
    store_raw_messages: bool = False
    default_daily_budget_usd: float = 5.0
    default_monthly_budget_usd: float = 100.0
    default_max_single_request_usd: float = 1.0
    large_context_token_threshold: int = 50_000
    loop_request_count: int = 10
    loop_window_minutes: int = 15
    high_cost_single_request_warning_usd: float = 0.50
    expensive_models: tuple[str, ...] = ("gpt-4.1", "claude-sonnet")

    @property
    def sqlite_path(self) -> str:
        if self.database_url.startswith("sqlite:///"):
            return self.database_url.removeprefix("sqlite:///")
        if self.database_url.startswith("sqlite://"):
            return self.database_url.removeprefix("sqlite://")
        return self.database_url


def get_settings() -> Settings:
    _load_dotenv()
    expensive = tuple(
        item.strip() for item in os.getenv("EXPENSIVE_MODELS", "gpt-4.1,claude-sonnet").split(",") if item.strip()
    )
    return Settings(
        mode=os.getenv("TOKEN_GOVERNOR_MODE", "mock"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./token_governor.db"),
        openai_compatible_base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL", "https://api.openai.com/v1"),
        openai_compatible_api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", "replace_me"),
        anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "replace_me"),
        anthropic_version=os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
        store_raw_messages=_bool("STORE_RAW_MESSAGES", False),
        default_daily_budget_usd=float(os.getenv("DEFAULT_DAILY_BUDGET_USD", "5")),
        default_monthly_budget_usd=float(os.getenv("DEFAULT_MONTHLY_BUDGET_USD", "100")),
        default_max_single_request_usd=float(os.getenv("DEFAULT_MAX_SINGLE_REQUEST_USD", "1")),
        large_context_token_threshold=int(os.getenv("LARGE_CONTEXT_TOKEN_THRESHOLD", "50000")),
        loop_request_count=int(os.getenv("LOOP_REQUEST_COUNT", "10")),
        loop_window_minutes=int(os.getenv("LOOP_WINDOW_MINUTES", "15")),
        high_cost_single_request_warning_usd=float(os.getenv("HIGH_COST_SINGLE_REQUEST_WARNING_USD", "0.50")),
        expensive_models=expensive,
    )
