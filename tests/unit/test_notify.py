"""Outbound notifications: channel URLs from the environment only, signing, retries, idempotency."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from aria.config import CommsConfig
from aria.contracts.report import OutboundAction
from aria.notify import build_payload, send_action, sign

HOOK = "https://hooks.example.test/aria"


def action(kind: str = "webhook", **fields: object) -> OutboundAction:
    values: dict[str, object] = {
        "action_id": "act-123",
        "kind": kind,
        "audience": "stakeholders",
        "title": "SEV2 · Checkout errors",
        "body": "Checkout is failing for some users.",
        "status": "approved",
        "evidence_ids": ["E1"],
    }
    values.update(fields)
    return OutboundAction.model_validate(values)


async def test_unconfigured_channel_is_skipped_not_failed() -> None:
    out = await send_action(action("slack"), CommsConfig(), run_url="http://x/runs/1", environ={})
    assert out.status == "skipped"
    assert out.result == {"reason": "SLACK_WEBHOOK_URL is not set"}


async def test_plain_http_is_refused_except_on_localhost() -> None:
    env = {"ARIA_OUTBOUND_WEBHOOK_URL": "http://hooks.example.test/aria"}
    out = await send_action(action(), CommsConfig(), run_url="u", environ=env)
    assert out.status == "failed"
    assert "https" in out.result["error"]
    with respx.mock() as mock:
        mock.post("http://localhost:9000/hook").mock(return_value=httpx.Response(200))
        local = {"ARIA_OUTBOUND_WEBHOOK_URL": "http://localhost:9000/hook"}
        assert (
            await send_action(action(), CommsConfig(), run_url="u", environ=local)
        ).status == "sent"


async def test_generic_webhook_is_signed_and_retried_once_on_5xx() -> None:
    env = {"ARIA_OUTBOUND_WEBHOOK_URL": HOOK, "ARIA_OUTBOUND_WEBHOOK_SECRET": "k"}
    with respx.mock() as mock:
        route = mock.post(HOOK).mock(side_effect=[httpx.Response(503), httpx.Response(200)])
        out = await send_action(action(), CommsConfig(), run_url="http://x/runs/1", environ=env)
    assert out.status == "sent"
    assert route.call_count == 2
    request = route.calls[1].request
    body = json.loads(request.content)
    assert body["action_id"] == "act-123"
    assert body["run_url"] == "http://x/runs/1"
    assert request.headers["X-ARIA-Signature"] == sign(
        "k", request.headers["X-ARIA-Timestamp"], request.content
    )


async def test_client_errors_fail_without_retry_and_transport_errors_retry() -> None:
    env = {"ARIA_OUTBOUND_WEBHOOK_URL": HOOK}
    with respx.mock() as mock:
        route = mock.post(HOOK).mock(return_value=httpx.Response(400))
        out = await send_action(action(), CommsConfig(), run_url="u", environ=env)
        assert (out.status, out.result["error"], route.call_count) == ("failed", "HTTP 400", 1)
    with respx.mock() as mock:
        route = mock.post(HOOK).mock(side_effect=httpx.ConnectError("refused"))
        out = await send_action(action(), CommsConfig(), run_url="u", environ=env)
        assert out.status == "failed"
        assert out.result["error"].startswith("ConnectError")
        assert route.call_count == 2


async def test_already_sent_actions_are_never_resent() -> None:
    sent = action(status="sent")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(HOOK)
        out = await send_action(
            sent, CommsConfig(), run_url="u", environ={"ARIA_OUTBOUND_WEBHOOK_URL": HOOK}
        )
    assert out is sent
    assert not route.called


def test_slack_text_cannot_mention_everyone_or_link() -> None:
    hostile = action(
        "slack", title="SEV2 <!channel>", body="see <https://evil.example|the fix> & reply"
    )
    text = build_payload(hostile, run_url="http://x/runs/1")["text"]
    assert "<" not in text
    assert ">" not in text
    assert text == "*SEV2 &lt;!channel&gt;*\nsee &lt;https://evil.example|the fix&gt; &amp; reply"


@pytest.mark.parametrize("kind", ["slack", "teams", "status_page"])
def test_payload_shapes(kind: str) -> None:
    payload = build_payload(action(kind), run_url="http://x/runs/1")
    if kind == "slack":
        assert payload == {"text": "*SEV2 · Checkout errors*\nCheckout is failing for some users."}
    elif kind == "teams":
        card = payload["attachments"][0]["content"]
        assert card["type"] == "AdaptiveCard"
        assert card["actions"][0]["url"] == "http://x/runs/1"
    else:
        assert payload["kind"] == "status_page"
        assert payload["evidence_ids"] == ["E1"]
