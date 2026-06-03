from __future__ import annotations

import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone

from .classifier import classify_request
from .config import get_settings
from .db import connect, create_virtual_key, init_db, insert_usage
from .models import UsageRecord, VirtualKey
from .pricing import estimate_cost
from .privacy import safe_preview, stable_hash


def make_key(owner: str, project: str) -> str:
    slug = f"{owner}_{project}".lower().replace(" ", "_").replace("-", "_")
    return f"tg_sk_{slug}_{uuid.uuid4().hex[:6]}"


def create_key(args: argparse.Namespace) -> None:
    settings = get_settings()
    key_value = args.key or make_key(args.owner, args.project)
    allowed_models = [item.strip() for item in args.allowed_models.split(",") if item.strip()]
    key = VirtualKey(
        id=None,
        key=key_value,
        owner=args.owner,
        project=args.project,
        allowed_models=allowed_models,
        daily_budget_usd=args.daily_budget,
        monthly_budget_usd=args.monthly_budget,
        max_single_request_usd=args.max_request,
        provider=args.provider,
        enabled=not args.disabled,
    )
    with connect(settings) as conn:
        init_db(conn)
        created = create_virtual_key(conn, key)
        conn.commit()
    print(f"Created virtual key: {created.key}")


def _usage(
    key: VirtualKey,
    session_id: str,
    prompt: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    status: str = "allowed",
    block_reason: str | None = None,
    minutes_ago: int = 0,
    flags: list[str] | None = None,
) -> UsageRecord:
    category = classify_request(prompt)
    cost = estimate_cost(model, input_tokens, output_tokens)
    return UsageRecord(
        request_id=f"tg_req_demo_{uuid.uuid4().hex}",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        virtual_key_id=key.id,
        virtual_key=key.key,
        owner=key.owner,
        project=key.project,
        session_id=session_id,
        provider=key.provider,
        model=model,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=cost,
        status=status,
        block_reason=block_reason,
        latency_ms=random.randint(120, 1800),
        route_path="/v1/chat/completions",
        user_agent="burnguard-demo/0.1",
        request_category=category,
        warning_flags=flags or [],
        prompt_hash=stable_hash(prompt),
        response_hash=stable_hash("demo response" + prompt),
        prompt_preview=safe_preview(prompt),
        response_preview="Demo assistant response preview.",
    )


def seed_demo(_: argparse.Namespace) -> None:
    settings = get_settings()
    keys = [
        VirtualKey(None, "tg_sk_demo", "Stephan", "demo", ["gpt-4o-mini", "gpt-4.1"], 5, 100, 1),
        VirtualKey(None, "tg_sk_codex_project_a", "Codex Agent", "project-a", ["gpt-4o-mini", "gpt-4.1"], 3, 50, 0.75),
        VirtualKey(None, "tg_sk_marketing_test", "Marketing", "content-test", ["gpt-4o-mini"], 2, 25, 0.25),
    ]
    with connect(settings) as conn:
        init_db(conn)
        conn.execute("DELETE FROM usage_records")
        for key in keys:
            create_virtual_key(conn, key)
        saved = {row["key"]: row for row in conn.execute("SELECT * FROM virtual_keys")}
        hydrated = []
        for key in keys:
            row = saved[key.key]
            key.id = row["id"]
            hydrated.append(key)

        normal = hydrated[0]
        runaway = hydrated[1]
        marketing = hydrated[2]
        records = [
            _usage(normal, "demo-session-1", "Write a Python function that adds two numbers.", "gpt-4o-mini", 120, 80, minutes_ago=90),
            _usage(normal, "demo-session-1", "Plan a small FastAPI endpoint for a health check.", "gpt-4o-mini", 220, 140, minutes_ago=80),
            _usage(marketing, "content-demo-1", "Draft README documentation for a local developer tool.", "gpt-4o-mini", 420, 260, minutes_ago=70),
        ]
        loop_prompt = "pytest failed test traceback error: AssertionError in tests/test_gateway.py"
        for idx in range(12):
            flags = []
            if idx >= 1:
                flags.append("repeated_prompt")
            if idx >= 9:
                flags.append("possible_loop")
            if idx >= 2:
                flags.append("test_failure_loop")
            records.append(
                _usage(
                    runaway,
                    "codex-runaway-001",
                    loop_prompt,
                    "gpt-4.1",
                    18000 + idx * 450,
                    1200,
                    minutes_ago=30 - idx,
                    flags=flags + ["expensive_model", "large_context"] if idx >= 6 else flags + ["expensive_model"],
                )
            )
        records.append(
            _usage(
                runaway,
                "codex-runaway-001",
                "Implement another patch with huge context attached.",
                "gpt-4.1",
                140000,
                0,
                status="blocked",
                block_reason="max_single_request_exceeded",
                minutes_ago=5,
                flags=["large_context", "expensive_model", "high_cost_single_request", "possible_loop"],
            )
        )
        for record in records:
            insert_usage(conn, record)
        conn.commit()
    print("Seeded demo data with 3 virtual keys, normal usage, a runaway session, and a blocked request.")
    print("Try: uvicorn token_governor.main:app --reload")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m token_governor")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-key", help="Create a local virtual API key")
    create.add_argument("--owner", required=True)
    create.add_argument("--project", required=True)
    create.add_argument("--daily-budget", type=float, default=get_settings().default_daily_budget_usd)
    create.add_argument("--monthly-budget", type=float, default=get_settings().default_monthly_budget_usd)
    create.add_argument("--max-request", type=float, default=get_settings().default_max_single_request_usd)
    create.add_argument("--allowed-models", default="gpt-4o-mini,gpt-4.1,claude-sonnet")
    create.add_argument("--provider", default="openai-compatible")
    create.add_argument("--key")
    create.add_argument("--disabled", action="store_true")
    create.set_defaults(func=create_key)
    seed = sub.add_parser("seed-demo", help="Seed fake keys and usage data")
    seed.set_defaults(func=seed_demo)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
