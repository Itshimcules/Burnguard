from __future__ import annotations

import httpx

from .config import Settings
from .models import UsageRecord


def should_alert(record: UsageRecord, settings: Settings) -> bool:
    if settings.alert_on_blocked and record.status == "blocked":
        return True
    return bool(settings.alert_on_warning_flags and record.warning_flags)


def _text(record: UsageRecord) -> str:
    flags = ", ".join(record.warning_flags) if record.warning_flags else "none"
    return (
        f"Burnguard {record.status} request: {record.owner or 'unknown'} / {record.project or 'unknown'} "
        f"used {record.model} in session {record.session_id}. "
        f"Cost=${record.estimated_cost_usd:.6f}; flags={flags}; reason={record.block_reason or 'n/a'}."
    )


async def send_alert(record: UsageRecord, settings: Settings) -> None:
    if not should_alert(record, settings):
        return
    text = _text(record)
    async with httpx.AsyncClient(timeout=10) as client:
        if settings.slack_webhook_url:
            await client.post(settings.slack_webhook_url, json={"text": text})
        if settings.discord_webhook_url:
            await client.post(settings.discord_webhook_url, json={"content": text})
