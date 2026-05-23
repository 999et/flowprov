"""Optional Slack notification on drift events."""
from __future__ import annotations

import logging

import httpx

from flowprov.config import get_settings

log = logging.getLogger(__name__)


async def maybe_send_slack(
    *, flow_id: str, node_id: str, severity: str, explanation: str, execution_id: int
) -> None:
    settings = get_settings()
    if not settings.slack_webhook_url:
        return

    emoji = "🚨" if severity == "fail" else "⚠️"
    text = (
        f"{emoji} *flowprov drift {severity.upper()}*\n"
        f"• flow: `{flow_id}`\n"
        f"• node: `{node_id}`\n"
        f"• execution: `{execution_id}`\n"
        f"• detail: {explanation}"
    )
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(settings.slack_webhook_url, json={"text": text})
