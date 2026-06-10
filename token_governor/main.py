from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from csv import DictWriter
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .alerts import send_alert
from .attribution import count_tool_calls, extract_tool_names, file_context_hash
from .auth import AuthError, ModelNotAllowedError, validate_virtual_key
from .budget import check_budget
from .classifier import classify_request
from .config import get_settings
from .db import connect, init_db, insert_usage, list_virtual_keys
from .models import UsageRecord, VirtualKey
from .pricing import estimate_cost
from .privacy import safe_preview, stable_hash
from .proxy import (
    estimate_anthropic_input_tokens,
    estimate_message_tokens,
    estimate_response_input_tokens,
    forward_anthropic_message,
    forward_chat_completion,
    forward_response,
)
from .risk_flags import compute_warning_flags

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    with connect(settings) as conn:
        init_db(conn)
    yield


app = FastAPI(title="Burnguard", description="Guardrails for shared LLM API usage", version="0.1.0", lifespan=lifespan)
package_dir = Path(__file__).parent
templates = Jinja2Templates(directory=str(package_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(package_dir / "static")), name="static")

Forwarder = Callable[[dict, Any], Awaitable[tuple[dict, int, int]]]


@dataclass(frozen=True)
class MeteredRequestSpec:
    payload: dict
    route_path: str
    model: str
    session_id: str
    prompt_material: Any
    category_material: Any
    input_tokens: int
    estimated_output_tokens: int
    forwarder: Forwarder
    github_repo: str | None = None
    github_pr: str | None = None
    tool_names: list[str] | None = None
    context_hash: str | None = None


def _unsupported_streaming_response() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "message": "Streaming is not supported in this MVP.",
                "type": "unsupported_feature",
            }
        },
    )


async def _read_payload(request: Request) -> dict | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "Request body must be a valid JSON object.",
                    "type": "invalid_request_error",
                }
            },
        )
    return payload


def _wants_streaming(payload: dict) -> bool:
    value = payload.get("stream")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _auth_error_response(exc: AuthError) -> JSONResponse:
    if isinstance(exc, ModelNotAllowedError):
        status_code, error_type, code = 403, "invalid_request_error", "model_not_allowed"
    else:
        status_code, error_type, code = 401, "authentication_error", "invalid_api_key"
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": str(exc), "type": error_type, "code": code}},
    )


def _response_text(response: dict) -> str:
    if response.get("output_text"):
        return str(response["output_text"])
    content = response.get("content")
    if isinstance(content, list):
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
        if text_parts:
            return "\n".join(text_parts)
    try:
        return str(response["choices"][0]["message"]["content"])
    except Exception:
        return json.dumps(response, default=str)[:200]


def _usage_record(
    *,
    request_id: str,
    started: float,
    route_path: str,
    virtual_key: VirtualKey | None,
    session_id: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    status: str,
    block_reason: str | None,
    user_agent: str | None,
    category: str,
    warning_flags: list[str],
    prompt_hash: str | None,
    response_hash: str | None,
    prompt_preview: str | None,
    response_preview: str | None,
    raw_messages: Any | None = None,
    raw_response: Any | None = None,
    github_repo: str | None = None,
    github_pr: str | None = None,
    tool_call_count: int = 0,
    tool_names: list[str] | None = None,
    context_hash: str | None = None,
) -> UsageRecord:
    return UsageRecord(
        request_id=request_id,
        timestamp=datetime.now(timezone.utc),
        virtual_key_id=virtual_key.id if virtual_key else None,
        virtual_key=virtual_key.key if virtual_key else None,
        owner=virtual_key.owner if virtual_key else None,
        project=virtual_key.project if virtual_key else None,
        session_id=session_id,
        provider=provider,
        model=model,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=cost,
        status=status,
        block_reason=block_reason,
        latency_ms=int((time.perf_counter() - started) * 1000),
        route_path=route_path,
        user_agent=user_agent,
        request_category=category,
        warning_flags=warning_flags,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        prompt_preview=prompt_preview,
        response_preview=response_preview,
        raw_messages=raw_messages,
        raw_response=raw_response,
        github_repo=github_repo,
        github_pr=github_pr,
        tool_call_count=tool_call_count,
        tool_names=tool_names,
        context_hash=context_hash,
    )


async def _handle_metered_request(spec: MeteredRequestSpec, authorization: str | None, user_agent: str | None) -> JSONResponse:
    started = time.perf_counter()
    request_id = f"tg_req_{uuid.uuid4().hex}"
    prompt_hash = stable_hash(spec.prompt_material)
    category = classify_request(spec.category_material)
    prompt_preview = safe_preview(spec.prompt_material)
    raw_prompt = spec.prompt_material if settings.store_raw_messages else None

    with connect(settings) as conn:
        init_db(conn)
        try:
            virtual_key = validate_virtual_key(conn, authorization, model=spec.model)
        except AuthError as exc:
            record = _usage_record(
                request_id=request_id,
                started=started,
                route_path=spec.route_path,
                virtual_key=None,
                session_id=spec.session_id,
                provider="unknown",
                model=spec.model,
                input_tokens=spec.input_tokens,
                output_tokens=0,
                cost=0,
                status="blocked",
                block_reason="auth_failed",
                user_agent=user_agent,
                category=category,
                warning_flags=[],
                prompt_hash=prompt_hash,
                response_hash=None,
                prompt_preview=prompt_preview,
                response_preview=None,
                raw_messages=raw_prompt,
                github_repo=spec.github_repo,
                github_pr=spec.github_pr,
                tool_names=spec.tool_names,
                context_hash=spec.context_hash,
            )
            insert_usage(conn, record)
            conn.commit()
            await send_alert(record, settings)
            return _auth_error_response(exc)

        decision = check_budget(conn, virtual_key, spec.model, spec.input_tokens, spec.estimated_output_tokens)
        flags = compute_warning_flags(
            conn,
            session_id=spec.session_id,
            prompt_hash=prompt_hash,
            model=spec.model,
            input_tokens=spec.input_tokens,
            estimated_cost_usd=decision.estimated_request_cost,
            category=category,
            virtual_key=virtual_key,
            daily_spend_usd=decision.daily_spend,
            context_hash=spec.context_hash,
            settings=settings,
        )
        if not decision.allowed:
            record = _usage_record(
                request_id=request_id,
                started=started,
                route_path=spec.route_path,
                virtual_key=virtual_key,
                session_id=spec.session_id,
                provider=virtual_key.provider,
                model=spec.model,
                input_tokens=spec.input_tokens,
                output_tokens=0,
                cost=decision.estimated_request_cost,
                status="blocked",
                block_reason=decision.reason,
                user_agent=user_agent,
                category=category,
                warning_flags=flags,
                prompt_hash=prompt_hash,
                response_hash=None,
                prompt_preview=prompt_preview,
                response_preview=None,
                raw_messages=raw_prompt,
                github_repo=spec.github_repo,
                github_pr=spec.github_pr,
                tool_names=spec.tool_names,
                context_hash=spec.context_hash,
            )
            insert_usage(conn, record)
            conn.commit()
            await send_alert(record, settings)
            return JSONResponse(
                status_code=402,
                content={
                    "error": {
                        "message": "Request blocked by Burnguard budget policy.",
                        "type": "budget_exceeded",
                        "details": decision.details,
                    }
                },
            )

    try:
        provider_response, actual_input, actual_output = await spec.forwarder(spec.payload, settings)
        status = "allowed"
        block_reason = None
    except Exception as exc:
        provider_response = {"error": {"message": str(exc), "type": "provider_error"}}
        actual_input = spec.input_tokens
        actual_output = 0
        status = "errored"
        block_reason = "provider_error"

    response_text = _response_text(provider_response)
    tool_names = sorted(set((spec.tool_names or []) + extract_tool_names(provider_response)))
    tool_call_count = count_tool_calls(spec.payload, provider_response)
    cost = estimate_cost(spec.model, actual_input, actual_output)
    # Reuse the key validated before forwarding: re-validating here would 500
    # (and drop the usage record) if the key was disabled mid-request.
    with connect(settings) as conn:
        init_db(conn)
        record = _usage_record(
            request_id=request_id,
            started=started,
            route_path=spec.route_path,
            virtual_key=virtual_key,
            session_id=spec.session_id,
            provider=virtual_key.provider,
            model=spec.model,
            input_tokens=actual_input,
            output_tokens=actual_output,
            cost=cost,
            status=status,
            block_reason=block_reason,
            user_agent=user_agent,
            category=category,
            warning_flags=flags,
            prompt_hash=prompt_hash,
            response_hash=stable_hash(response_text),
            prompt_preview=prompt_preview,
            response_preview=safe_preview(response_text),
            raw_messages=raw_prompt,
            raw_response=provider_response if settings.store_raw_messages else None,
            github_repo=spec.github_repo,
            github_pr=spec.github_pr,
            tool_call_count=tool_call_count,
            tool_names=tool_names,
            context_hash=spec.context_hash,
        )
        insert_usage(conn, record)
        conn.commit()
    await send_alert(record, settings)
    return JSONResponse(status_code=200 if status == "allowed" else 502, content=provider_response)


def _correlation(repo_header: str | None, pr_header: str | None) -> tuple[str | None, str | None]:
    repo = repo_header.strip() if repo_header else None
    pr = pr_header.strip() if pr_header else None
    return repo or None, pr or None


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    session_header: str | None = Header(default=None, alias="X-Token-Governor-Session"),
    github_repo: str | None = Header(default=None, alias="X-Token-Governor-GitHub-Repo"),
    github_pr: str | None = Header(default=None, alias="X-Token-Governor-GitHub-PR"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
) -> JSONResponse:
    payload = await _read_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    if _wants_streaming(payload):
        return _unsupported_streaming_response()

    messages = payload.get("messages", [])
    repo, pr = _correlation(github_repo, github_pr)
    spec = MeteredRequestSpec(
        payload=payload,
        route_path=str(request.url.path),
        model=payload.get("model", "unknown"),
        session_id=session_header or f"session_{uuid.uuid4().hex[:12]}",
        prompt_material=messages,
        category_material=messages,
        input_tokens=estimate_message_tokens(messages),
        estimated_output_tokens=int(payload.get("max_tokens") or 512),
        forwarder=forward_chat_completion,
        github_repo=repo,
        github_pr=pr,
        tool_names=extract_tool_names(payload),
        context_hash=file_context_hash(messages),
    )
    return await _handle_metered_request(spec, authorization, user_agent)


@app.post("/v1/responses")
async def responses(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    session_header: str | None = Header(default=None, alias="X-Token-Governor-Session"),
    github_repo: str | None = Header(default=None, alias="X-Token-Governor-GitHub-Repo"),
    github_pr: str | None = Header(default=None, alias="X-Token-Governor-GitHub-PR"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
) -> JSONResponse:
    payload = await _read_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    if _wants_streaming(payload):
        return _unsupported_streaming_response()

    prompt_material = {"instructions": payload.get("instructions"), "input": payload.get("input")}
    repo, pr = _correlation(github_repo, github_pr)
    spec = MeteredRequestSpec(
        payload=payload,
        route_path=str(request.url.path),
        model=payload.get("model", "unknown"),
        session_id=session_header or f"session_{uuid.uuid4().hex[:12]}",
        prompt_material=prompt_material,
        category_material=[payload.get("instructions"), payload.get("input")],
        input_tokens=estimate_response_input_tokens(payload),
        estimated_output_tokens=int(payload.get("max_output_tokens") or 512),
        forwarder=forward_response,
        github_repo=repo,
        github_pr=pr,
        tool_names=extract_tool_names(payload),
        context_hash=file_context_hash(prompt_material),
    )
    return await _handle_metered_request(spec, authorization, user_agent)


@app.post("/v1/messages")
async def anthropic_messages(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    session_header: str | None = Header(default=None, alias="X-Token-Governor-Session"),
    github_repo: str | None = Header(default=None, alias="X-Token-Governor-GitHub-Repo"),
    github_pr: str | None = Header(default=None, alias="X-Token-Governor-GitHub-PR"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
) -> JSONResponse:
    payload = await _read_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    if _wants_streaming(payload):
        return _unsupported_streaming_response()

    prompt_material = {"system": payload.get("system"), "messages": payload.get("messages", [])}
    bearer = authorization or (f"Bearer {x_api_key}" if x_api_key else None)
    repo, pr = _correlation(github_repo, github_pr)
    spec = MeteredRequestSpec(
        payload=payload,
        route_path=str(request.url.path),
        model=payload.get("model", "unknown"),
        session_id=session_header or f"session_{uuid.uuid4().hex[:12]}",
        prompt_material=prompt_material,
        category_material=[payload.get("system"), payload.get("messages", [])],
        input_tokens=estimate_anthropic_input_tokens(payload),
        estimated_output_tokens=int(payload.get("max_tokens") or 512),
        forwarder=forward_anthropic_message,
        github_repo=repo,
        github_pr=pr,
        tool_names=extract_tool_names(payload),
        context_hash=file_context_hash(prompt_material),
    )
    return await _handle_metered_request(spec, bearer, user_agent)


def _csv_flags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _rows(sql: str, params: tuple = ()) -> list[Any]:
    with connect(settings) as conn:
        init_db(conn)
        return list(conn.execute(sql, params))


def _scalar(sql: str, params: tuple = ()) -> float:
    rows = _rows(sql, params)
    if not rows:
        return 0.0
    return float(rows[0][0] or 0)


def _record_dict(row: Any) -> dict[str, Any]:
    return {
        "request_id": row["request_id"],
        "timestamp": row["timestamp"],
        "owner": row["owner"],
        "project": row["project"],
        "session_id": row["session_id"],
        "provider": row["provider"],
        "model": row["model"],
        "status": row["status"],
        "block_reason": row["block_reason"],
        "route_path": row["route_path"],
        "estimated_input_tokens": row["estimated_input_tokens"],
        "estimated_output_tokens": row["estimated_output_tokens"],
        "total_tokens": row["total_tokens"],
        "estimated_cost_usd": row["estimated_cost_usd"],
        "request_category": row["request_category"],
        "warning_flags": _csv_flags(row["warning_flags"]),
        "github_repo": row["github_repo"],
        "github_pr": row["github_pr"],
        "tool_call_count": row["tool_call_count"],
        "tool_names": _csv_flags(row["tool_names"]),
    }


def _usage_export_rows(limit: int = 1000) -> list[Any]:
    bounded = max(1, min(limit, 10_000))
    return _rows("SELECT * FROM usage_records ORDER BY timestamp DESC LIMIT ?", (bounded,))


def _prom_metric(name: str, value: float, help_text: str, metric_type: str = "gauge") -> str:
    return f"# HELP {name} {help_text}\n# TYPE {name} {metric_type}\n{name} {value}\n"


def _today_start() -> str:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc).isoformat()


def _month_start() -> str:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()


def _display_time(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


templates.env.globals["format_time"] = _display_time
templates.env.globals["gateway_mode"] = lambda: settings.mode


@app.get("/")
def index(request: Request):
    today = _today_start()
    month = _month_start()
    context = {
        "request": request,
        "total_today": _scalar("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_records WHERE timestamp >= ? AND status='allowed'", (today,)),
        "total_month": _scalar("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_records WHERE timestamp >= ? AND status='allowed'", (month,)),
        "requests_today": int(_scalar("SELECT COUNT(*) FROM usage_records WHERE timestamp >= ?", (today,))),
        "top_users": _rows("SELECT owner, SUM(estimated_cost_usd) spend FROM usage_records GROUP BY owner ORDER BY spend DESC LIMIT 5"),
        "top_projects": _rows("SELECT project, SUM(estimated_cost_usd) spend FROM usage_records GROUP BY project ORDER BY spend DESC LIMIT 5"),
        "top_sessions": _rows("SELECT session_id, SUM(estimated_cost_usd) spend, COUNT(*) requests FROM usage_records GROUP BY session_id ORDER BY spend DESC LIMIT 5"),
        "top_models": _rows("SELECT model, SUM(estimated_cost_usd) spend FROM usage_records GROUP BY model ORDER BY spend DESC LIMIT 5"),
        "blocked": _rows("SELECT * FROM usage_records WHERE status='blocked' ORDER BY timestamp DESC LIMIT 10"),
        "categories": _rows("SELECT request_category, COUNT(*) count, SUM(estimated_cost_usd) spend FROM usage_records GROUP BY request_category ORDER BY count DESC"),
        "recent_flags": _rows("SELECT session_id, model, warning_flags, timestamp FROM usage_records WHERE warning_flags != '[]' ORDER BY timestamp DESC LIMIT 10"),
        "parse_flags": _csv_flags,
    }
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/keys")
def keys(request: Request):
    with connect(settings) as conn:
        init_db(conn)
        rows = list_virtual_keys(conn)
        spends = {row["id"]: _scalar("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_records WHERE virtual_key_id=? AND status='allowed'", (row["id"],)) for row in rows}
    return templates.TemplateResponse(request, "keys.html", {"request": request, "keys": rows, "spends": spends})


@app.get("/sessions")
def sessions(request: Request):
    rows = _rows(
        """
        SELECT session_id, owner, project, COUNT(*) requests, SUM(estimated_cost_usd) spend,
               MAX(timestamp) last_seen, SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) blocked
        FROM usage_records GROUP BY session_id ORDER BY last_seen DESC
        """
    )
    return templates.TemplateResponse(request, "sessions.html", {"request": request, "sessions": rows})


@app.get("/sessions/{session_id}")
def session_detail(request: Request, session_id: str):
    rows = _rows("SELECT * FROM usage_records WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
    prompt_counts: dict[str, int] = {}
    for row in rows:
        if row["prompt_hash"]:
            prompt_counts[row["prompt_hash"]] = prompt_counts.get(row["prompt_hash"], 0) + 1
    context = {
        "request": request,
        "session_id": session_id,
        "records": rows,
        "total_cost": sum(float(row["estimated_cost_usd"] or 0) for row in rows),
        "request_count": len(rows),
        "model_usage": _rows("SELECT model, COUNT(*) count, SUM(estimated_cost_usd) spend FROM usage_records WHERE session_id=? GROUP BY model", (session_id,)),
        "category_breakdown": _rows("SELECT request_category, COUNT(*) count FROM usage_records WHERE session_id=? GROUP BY request_category", (session_id,)),
        "repeated_prompt_count": sum(1 for count in prompt_counts.values() if count > 1),
        "parse_flags": _csv_flags,
    }
    return templates.TemplateResponse(request, "session_detail.html", context)


@app.get("/requests")
def requests_page(request: Request):
    rows = _rows("SELECT * FROM usage_records ORDER BY timestamp DESC LIMIT 100")
    return templates.TemplateResponse(request, "requests.html", {"request": request, "records": rows, "parse_flags": _csv_flags})


@app.get("/exports/usage.json")
def export_usage_json(limit: int = 1000) -> JSONResponse:
    return JSONResponse({"records": [_record_dict(row) for row in _usage_export_rows(limit)]})


@app.get("/exports/usage.csv")
def export_usage_csv(limit: int = 1000) -> StreamingResponse:
    rows = [_record_dict(row) for row in _usage_export_rows(limit)]
    output = StringIO()
    fieldnames = [
        "request_id",
        "timestamp",
        "owner",
        "project",
        "session_id",
        "provider",
        "model",
        "status",
        "block_reason",
        "route_path",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "request_category",
        "warning_flags",
        "github_repo",
        "github_pr",
        "tool_call_count",
        "tool_names",
    ]
    writer = DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "warning_flags": ",".join(row["warning_flags"]), "tool_names": ",".join(row["tool_names"])})
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=burnguard-usage.csv"})


@app.get("/reports/pull-requests")
def pull_request_report() -> JSONResponse:
    rows = _rows(
        """
        SELECT github_repo, github_pr, COUNT(*) requests, SUM(estimated_cost_usd) spend,
               SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) blocked,
               MAX(timestamp) last_seen
        FROM usage_records
        WHERE github_pr IS NOT NULL AND github_pr != ''
        GROUP BY github_repo, github_pr
        ORDER BY spend DESC
        """
    )
    return JSONResponse(
        {
            "pull_requests": [
                {
                    "github_repo": row["github_repo"],
                    "github_pr": row["github_pr"],
                    "requests": row["requests"],
                    "spend": round(float(row["spend"] or 0), 6),
                    "blocked": row["blocked"],
                    "last_seen": row["last_seen"],
                }
                for row in rows
            ]
        }
    )


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    allowed = _scalar("SELECT COUNT(*) FROM usage_records WHERE status='allowed'")
    blocked = _scalar("SELECT COUNT(*) FROM usage_records WHERE status='blocked'")
    errored = _scalar("SELECT COUNT(*) FROM usage_records WHERE status='errored'")
    spend = _scalar("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_records WHERE status='allowed'")
    tokens = _scalar("SELECT COALESCE(SUM(total_tokens),0) FROM usage_records")
    content = "".join(
        [
            _prom_metric("burnguard_requests_allowed_total", allowed, "Allowed Burnguard requests.", "counter"),
            _prom_metric("burnguard_requests_blocked_total", blocked, "Blocked Burnguard requests.", "counter"),
            _prom_metric("burnguard_requests_errored_total", errored, "Errored Burnguard requests.", "counter"),
            _prom_metric("burnguard_estimated_spend_usd_total", spend, "Estimated allowed request spend in USD.", "counter"),
            _prom_metric("burnguard_tokens_total", tokens, "Estimated total tokens processed by Burnguard.", "counter"),
        ]
    )
    return PlainTextResponse(content, media_type="text/plain; version=0.0.4")
