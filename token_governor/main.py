from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import AuthError, validate_virtual_key
from .budget import check_budget
from .classifier import classify_request
from .config import get_settings
from .db import connect, init_db, insert_usage, list_virtual_keys
from .exports import ExportFilters, REQUEST_EXPORT_COLUMNS, SESSION_EXPORT_COLUMNS, request_rows, session_rows, to_csv
from .models import UsageRecord
from .pricing import estimate_cost
from .privacy import safe_preview, stable_hash
from .compat import is_streaming_request
from .proxy import estimate_message_tokens, forward_chat_completion
from .risk_flags import compute_warning_flags

settings = get_settings()
app = FastAPI(title="Burnguard", description="Guardrails for shared LLM API usage", version="0.1.0")
package_dir = Path(__file__).parent
templates = Jinja2Templates(directory=str(package_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(package_dir / "static")), name="static")


@app.on_event("startup")
def startup() -> None:
    with connect(settings) as conn:
        init_db(conn)


def _response_text(response: dict) -> str:
    try:
        return str(response["choices"][0]["message"]["content"])
    except Exception:
        return json.dumps(response, default=str)[:200]


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


def _export_filters(
    session_id: str | None = None,
    owner: str | None = None,
    project: str | None = None,
    status: str | None = None,
    model: str | None = None,
    limit: int = 1000,
) -> ExportFilters:
    return ExportFilters(
        session_id=session_id,
        owner=owner,
        project=project,
        status=status,
        model=model,
        limit=limit,
    )


def _today_start() -> str:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc).isoformat()


def _month_start() -> str:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    session_header: str | None = Header(default=None, alias="X-Burnguard-Session"),
    legacy_session_header: str | None = Header(default=None, alias="X-Token-Governor-Session"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
) -> JSONResponse:
    started = time.perf_counter()
    request_id = f"bg_req_{uuid.uuid4().hex}"
    payload = await request.json()
    if is_streaming_request(payload):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "Streaming is not supported in this MVP.",
                    "type": "unsupported_feature",
                }
            },
        )
    model = payload.get("model", "unknown")
    messages = payload.get("messages", [])
    session_id = session_header or legacy_session_header or f"session_{uuid.uuid4().hex[:12]}"
    prompt_hash = stable_hash(messages)
    category = classify_request(messages)
    input_tokens = estimate_message_tokens(messages)

    with connect(settings) as conn:
        init_db(conn)
        try:
            virtual_key = validate_virtual_key(conn, authorization, model=model)
        except AuthError as exc:
            record = UsageRecord(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc),
                virtual_key_id=None,
                virtual_key=None,
                owner=None,
                project=None,
                session_id=session_id,
                provider="unknown",
                model=model,
                estimated_input_tokens=input_tokens,
                estimated_output_tokens=0,
                total_tokens=input_tokens,
                estimated_cost_usd=0,
                status="blocked",
                block_reason="auth_failed",
                latency_ms=int((time.perf_counter() - started) * 1000),
                route_path=str(request.url.path),
                user_agent=user_agent,
                request_category=category,
                warning_flags=[],
                prompt_hash=prompt_hash,
                response_hash=None,
                prompt_preview=safe_preview(messages),
                response_preview=None,
                raw_messages=messages if settings.store_raw_messages else None,
            )
            insert_usage(conn, record)
            conn.commit()
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        estimated_output = int(payload.get("max_tokens") or 512)
        decision = check_budget(conn, virtual_key, model, input_tokens, estimated_output)
        flags = compute_warning_flags(
            conn,
            session_id=session_id,
            prompt_hash=prompt_hash,
            model=model,
            input_tokens=input_tokens,
            estimated_cost_usd=decision.estimated_request_cost,
            category=category,
            virtual_key=virtual_key,
            daily_spend_usd=decision.daily_spend,
            settings=settings,
        )
        if not decision.allowed:
            record = UsageRecord(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc),
                virtual_key_id=virtual_key.id,
                virtual_key=virtual_key.key,
                owner=virtual_key.owner,
                project=virtual_key.project,
                session_id=session_id,
                provider=virtual_key.provider,
                model=model,
                estimated_input_tokens=input_tokens,
                estimated_output_tokens=0,
                total_tokens=input_tokens,
                estimated_cost_usd=decision.estimated_request_cost,
                status="blocked",
                block_reason=decision.reason,
                latency_ms=int((time.perf_counter() - started) * 1000),
                route_path=str(request.url.path),
                user_agent=user_agent,
                request_category=category,
                warning_flags=flags,
                prompt_hash=prompt_hash,
                response_hash=None,
                prompt_preview=safe_preview(messages),
                response_preview=None,
                raw_messages=messages if settings.store_raw_messages else None,
            )
            insert_usage(conn, record)
            conn.commit()
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
        provider_response, actual_input, actual_output = await forward_chat_completion(payload, settings)
        status = "allowed"
        block_reason = None
    except Exception as exc:
        provider_response = {"error": {"message": str(exc), "type": "provider_error"}}
        actual_input = input_tokens
        actual_output = 0
        status = "errored"
        block_reason = "provider_error"

    response_text = _response_text(provider_response)
    cost = estimate_cost(model, actual_input, actual_output)
    with connect(settings) as conn:
        init_db(conn)
        virtual_key = validate_virtual_key(conn, authorization, model=model)
        record = UsageRecord(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            virtual_key_id=virtual_key.id,
            virtual_key=virtual_key.key,
            owner=virtual_key.owner,
            project=virtual_key.project,
            session_id=session_id,
            provider=virtual_key.provider,
            model=model,
            estimated_input_tokens=actual_input,
            estimated_output_tokens=actual_output,
            total_tokens=actual_input + actual_output,
            estimated_cost_usd=cost,
            status=status,
            block_reason=block_reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
            route_path=str(request.url.path),
            user_agent=user_agent,
            request_category=category,
            warning_flags=flags,
            prompt_hash=prompt_hash,
            response_hash=stable_hash(response_text),
            prompt_preview=safe_preview(messages),
            response_preview=safe_preview(response_text),
            raw_messages=messages if settings.store_raw_messages else None,
            raw_response=provider_response if settings.store_raw_messages else None,
        )
        insert_usage(conn, record)
        conn.commit()
    return JSONResponse(status_code=200 if status == "allowed" else 502, content=provider_response)


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
    return templates.TemplateResponse("index.html", context)


@app.get("/keys")
def keys(request: Request):
    with connect(settings) as conn:
        init_db(conn)
        rows = list_virtual_keys(conn)
        spends = {row["id"]: _scalar("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_records WHERE virtual_key_id=? AND status='allowed'", (row["id"],)) for row in rows}
    return templates.TemplateResponse("keys.html", {"request": request, "keys": rows, "spends": spends})


@app.get("/sessions")
def sessions(request: Request):
    rows = _rows(
        """
        SELECT session_id, owner, project, COUNT(*) requests, SUM(estimated_cost_usd) spend,
               MAX(timestamp) last_seen, SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) blocked
        FROM usage_records GROUP BY session_id ORDER BY last_seen DESC
        """
    )
    return templates.TemplateResponse("sessions.html", {"request": request, "sessions": rows})


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
    return templates.TemplateResponse("session_detail.html", context)


@app.get("/requests")
def requests_page(request: Request):
    rows = _rows("SELECT * FROM usage_records ORDER BY timestamp DESC LIMIT 100")
    return templates.TemplateResponse("requests.html", {"request": request, "records": rows, "parse_flags": _csv_flags})


@app.get("/exports/requests.json")
def export_requests_json(
    session_id: str | None = None,
    owner: str | None = None,
    project: str | None = None,
    status: str | None = None,
    model: str | None = None,
    limit: int = 1000,
) -> JSONResponse:
    with connect(settings) as conn:
        init_db(conn)
        rows = request_rows(conn, _export_filters(session_id, owner, project, status, model, limit))
    return JSONResponse({"data": rows, "count": len(rows)})


@app.get("/exports/requests.csv")
def export_requests_csv(
    session_id: str | None = None,
    owner: str | None = None,
    project: str | None = None,
    status: str | None = None,
    model: str | None = None,
    limit: int = 1000,
) -> Response:
    with connect(settings) as conn:
        init_db(conn)
        rows = request_rows(conn, _export_filters(session_id, owner, project, status, model, limit))
    return Response(
        content=to_csv(rows, REQUEST_EXPORT_COLUMNS),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=burnguard-requests.csv"},
    )


@app.get("/exports/sessions.json")
def export_sessions_json(
    session_id: str | None = None,
    owner: str | None = None,
    project: str | None = None,
    status: str | None = None,
    model: str | None = None,
    limit: int = 1000,
) -> JSONResponse:
    with connect(settings) as conn:
        init_db(conn)
        rows = session_rows(conn, _export_filters(session_id, owner, project, status, model, limit))
    return JSONResponse({"data": rows, "count": len(rows)})


@app.get("/exports/sessions.csv")
def export_sessions_csv(
    session_id: str | None = None,
    owner: str | None = None,
    project: str | None = None,
    status: str | None = None,
    model: str | None = None,
    limit: int = 1000,
) -> Response:
    with connect(settings) as conn:
        init_db(conn)
        rows = session_rows(conn, _export_filters(session_id, owner, project, status, model, limit))
    return Response(
        content=to_csv(rows, SESSION_EXPORT_COLUMNS),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=burnguard-sessions.csv"},
    )

