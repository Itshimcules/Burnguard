from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

REQUEST_EXPORT_COLUMNS = [
    "request_id",
    "timestamp",
    "virtual_key",
    "owner",
    "project",
    "session_id",
    "provider",
    "model",
    "estimated_input_tokens",
    "estimated_output_tokens",
    "total_tokens",
    "estimated_cost_usd",
    "status",
    "block_reason",
    "latency_ms",
    "route_path",
    "user_agent",
    "request_category",
    "warning_flags",
    "prompt_hash",
    "response_hash",
    "prompt_preview",
    "response_preview",
]

SESSION_EXPORT_COLUMNS = [
    "session_id",
    "owner",
    "project",
    "request_count",
    "total_tokens",
    "estimated_cost_usd",
    "blocked_requests",
    "errored_requests",
    "first_seen",
    "last_seen",
    "models",
    "categories",
    "warning_flags",
]


@dataclass(frozen=True)
class ExportFilters:
    session_id: str | None = None
    owner: str | None = None
    project: str | None = None
    status: str | None = None
    model: str | None = None
    limit: int = 1000

    def bounded_limit(self) -> int:
        return min(max(self.limit, 1), 10_000)


def _parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_array(values: set[str]) -> str:
    return json.dumps(sorted(value for value in values if value))


def request_rows(conn: sqlite3.Connection, filters: ExportFilters | None = None) -> list[dict[str, Any]]:
    filters = filters or ExportFilters()
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("session_id", filters.session_id),
        ("owner", filters.owner),
        ("project", filters.project),
        ("status", filters.status),
        ("model", filters.model),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT {', '.join(REQUEST_EXPORT_COLUMNS)}
        FROM usage_records
        {where}
        ORDER BY timestamp DESC
        LIMIT ?
    """
    params.append(filters.bounded_limit())
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def session_rows(conn: sqlite3.Connection, filters: ExportFilters | None = None) -> list[dict[str, Any]]:
    filters = filters or ExportFilters()
    requests = request_rows(conn, ExportFilters(**{**filters.__dict__, "limit": 10_000}))
    sessions: dict[str, dict[str, Any]] = {}
    for row in reversed(requests):
        session_id = str(row["session_id"])
        item = sessions.setdefault(
            session_id,
            {
                "session_id": session_id,
                "owner": row["owner"],
                "project": row["project"],
                "request_count": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "blocked_requests": 0,
                "errored_requests": 0,
                "first_seen": row["timestamp"],
                "last_seen": row["timestamp"],
                "models": set(),
                "categories": set(),
                "warning_flags": set(),
            },
        )
        item["request_count"] += 1
        item["total_tokens"] += int(row["total_tokens"] or 0)
        item["estimated_cost_usd"] = round(float(item["estimated_cost_usd"]) + float(row["estimated_cost_usd"] or 0), 6)
        item["blocked_requests"] += 1 if row["status"] == "blocked" else 0
        item["errored_requests"] += 1 if row["status"] == "errored" else 0
        item["first_seen"] = min(str(item["first_seen"]), str(row["timestamp"]))
        item["last_seen"] = max(str(item["last_seen"]), str(row["timestamp"]))
        item["models"].add(str(row["model"] or ""))
        item["categories"].add(str(row["request_category"] or ""))
        item["warning_flags"].update(_parse_json_list(row["warning_flags"]))
    exported = []
    for item in sessions.values():
        exported.append(
            {
                **item,
                "models": _json_array(item["models"]),
                "categories": _json_array(item["categories"]),
                "warning_flags": _json_array(item["warning_flags"]),
            }
        )
    exported.sort(key=lambda item: str(item["last_seen"]), reverse=True)
    return exported[: filters.bounded_limit()]


def to_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()
