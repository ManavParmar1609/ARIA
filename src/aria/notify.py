"""Outbound notifications for approved actions: Slack, Microsoft Teams and a generic webhook.

Nothing here runs unless a reviewer approved the action. Webhook URLs come only from the
environment variables named in config, never from a request or from model output, so a run
cannot redirect a message. An action whose channel has no URL configured is marked ``skipped``
rather than failed. Every delivery carries the action id as an idempotency key, the generic
webhook is HMAC-signed when a secret is configured, and the publisher never resends an action
already marked ``sent``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from aria import __version__
from aria.config import CommsConfig
from aria.contracts.report import OutboundAction
from aria.observability.logging import get_logger

log = get_logger(__name__)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def channel_env(kind: str, comms: CommsConfig) -> str:
    """The environment variable holding the URL for an action kind."""
    if kind == "slack":
        return comms.slack_webhook_env
    if kind == "teams":
        return comms.teams_webhook_env
    return comms.generic_webhook_env  # webhook, status_page and ticket_draft


def _safe_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS)


def build_payload(action: OutboundAction, *, run_url: str) -> dict[str, Any]:
    if action.kind == "slack":
        return {"text": action.payload.get("text") or f"*{action.title}*\n{action.body}"}
    if action.kind == "teams":
        card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": [
                {"type": "TextBlock", "text": action.title, "weight": "Bolder", "wrap": True},
                {"type": "TextBlock", "text": action.body, "wrap": True},
            ],
            "actions": [{"type": "Action.OpenUrl", "title": "Open in ARIA", "url": run_url}],
        }
        return {
            "type": "message",
            "attachments": [
                {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
            ],
        }
    return {
        "action_id": action.action_id,
        "kind": action.kind,
        "audience": action.audience,
        "title": action.title,
        "body": action.body,
        "evidence_ids": action.evidence_ids,
        "run_url": run_url,
    }


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + digest.hexdigest()


async def send_action(
    action: OutboundAction,
    comms: CommsConfig,
    *,
    run_url: str,
    client: httpx.AsyncClient | None = None,
    environ: dict[str, str] | None = None,
) -> OutboundAction:
    """Deliver one approved action and return it with its new status and the result."""
    env = os.environ if environ is None else environ
    if action.status == "sent":
        return action
    variable = channel_env(action.kind, comms)
    url = env.get(variable, "").strip()
    if not url:
        return action.model_copy(
            update={"status": "skipped", "result": {"reason": f"{variable} is not set"}}
        )
    if not _safe_url(url):
        return action.model_copy(
            update={"status": "failed", "result": {"error": f"{variable} must be an https URL"}}
        )
    body = json.dumps(build_payload(action, run_url=run_url), separators=(",", ":")).encode()
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": action.action_id,
        "User-Agent": f"aria/{__version__}",
    }
    secret = env.get(comms.generic_webhook_secret_env, "")
    if secret and variable == comms.generic_webhook_env:
        timestamp = str(int(time.time()))
        headers["X-ARIA-Timestamp"] = timestamp
        headers["X-ARIA-Signature"] = sign(secret, timestamp, body)
    own = client is None
    http = client or httpx.AsyncClient(timeout=comms.timeout_s)
    try:
        for attempt in (1, 2):
            try:
                response = await http.post(url, content=body, headers=headers)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    return _failed(action, f"{type(exc).__name__}: {exc}")
                continue
            if response.status_code >= 500 and attempt == 1:
                continue
            if response.is_success:
                log.info("notify.sent", action_id=action.action_id, kind=action.kind)
                return action.model_copy(
                    update={"status": "sent", "result": {"status_code": response.status_code}}
                )
            return _failed(action, f"HTTP {response.status_code}")
        return _failed(action, "no response")  # pragma: no cover - the loop always returns
    finally:
        if own:
            await http.aclose()


def _failed(action: OutboundAction, error: str) -> OutboundAction:
    log.warning("notify.failed", action_id=action.action_id, kind=action.kind, error=error)
    return action.model_copy(update={"status": "failed", "result": {"error": error[:300]}})
