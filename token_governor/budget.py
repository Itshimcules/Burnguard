from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from .db import spend_between
from .models import VirtualKey
from .pricing import estimate_cost


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str | None
    estimated_request_cost: float
    daily_spend: float
    monthly_spend: float
    details: dict[str, float | str]


def day_bounds(now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def month_bounds(now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()


def check_budget(conn: sqlite3.Connection, virtual_key: VirtualKey, model: str, input_tokens: int, estimated_output_tokens: int = 0) -> BudgetDecision:
    request_cost = estimate_cost(model, input_tokens, estimated_output_tokens)
    day_start, day_end = day_bounds()
    month_start, month_end = month_bounds()
    daily_spend = spend_between(conn, virtual_key.id or -1, day_start, day_end)
    monthly_spend = spend_between(conn, virtual_key.id or -1, month_start, month_end)
    projected_daily_spend = daily_spend + request_cost
    projected_monthly_spend = monthly_spend + request_cost
    details = {
        "daily_budget_usd": virtual_key.daily_budget_usd,
        "daily_spend_usd": round(daily_spend, 6),
        "projected_daily_spend_usd": round(projected_daily_spend, 6),
        "monthly_budget_usd": virtual_key.monthly_budget_usd,
        "monthly_spend_usd": round(monthly_spend, 6),
        "projected_monthly_spend_usd": round(projected_monthly_spend, 6),
        "max_single_request_usd": virtual_key.max_single_request_usd,
        "estimated_request_cost_usd": request_cost,
    }
    if request_cost > virtual_key.max_single_request_usd:
        return BudgetDecision(False, "max_single_request_exceeded", request_cost, daily_spend, monthly_spend, details)
    if projected_daily_spend > virtual_key.daily_budget_usd:
        return BudgetDecision(False, "daily_budget_exceeded", request_cost, daily_spend, monthly_spend, details)
    if projected_monthly_spend > virtual_key.monthly_budget_usd:
        return BudgetDecision(False, "monthly_budget_exceeded", request_cost, daily_spend, monthly_spend, details)
    return BudgetDecision(True, None, request_cost, daily_spend, monthly_spend, details)
