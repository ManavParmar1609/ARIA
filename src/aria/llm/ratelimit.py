"""Read a provider's refusal: which limit it names, and how long it lasts.

An HTTP 429 means different things, and waiting helps with only some of them:

* Gemini answers ``RESOURCE_EXHAUSTED`` with ``QuotaFailure`` details whose quota id names the
  window (``GenerateRequestsPerDayPerProjectPerModel-FreeTier``, ``...PerMinute...``) and a
  ``RetryInfo`` delay. For a daily quota that delay does not help: the quota is back only at the
  next daily reset.
* OpenAI's ``insufficient_quota`` (and Anthropic's "credit balance is too low") means the account
  has no credit left: nothing returns until someone adds some.
* Anthropic sends ``retry-after`` with a rate limit and none when the organisation's spend limit
  is reached; its message may say when access returns ("You will regain access on ...").
* Groq and OpenAI name the window in the message ("requests per day (RPD)").
* A 503 or 529 is the provider being busy, not this account's limit.

The router turns the answer into a hold on the provider (aria.llm.quota) and its breaker.
"""

from __future__ import annotations

import email.utils
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from aria.llm.base import RateLimit

_RETRY_DELAY = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')
_PER_DAY = re.compile(r"per\s*_?day|daily|\(rpd\)|\(tpd\)", re.IGNORECASE)
_PER_MINUTE = re.compile(r"per\s*_?minute|\(rpm\)|\(tpm\)", re.IGNORECASE)
_SPEND = re.compile(
    r"spend(?:ing)?[\s_-]*(?:cap|limit)|usage limits?\b|monthly (?:spend|budget|cap)",
    re.IGNORECASE,
)
_NO_CREDIT = re.compile(
    r"insufficient_quota|insufficient[\s_]credits?|credit balance is too low", re.IGNORECASE
)
_REGAIN = re.compile(
    r"regain access on (\d{4}-\d{2}-\d{2})(?: at (\d{1,2}):(\d{2}) ?UTC)?", re.IGNORECASE
)
_LIMIT_STATUSES = frozenset({400, 402, 403, 429, 503, 529})


def retry_after_seconds(headers: Mapping[str, str], body: str, *, now: float) -> float | None:
    """How long the provider asked callers to wait: Retry-After (seconds or a date), or Gemini's
    RetryInfo delay in the body."""
    header = str(headers.get("retry-after", "")).strip()
    if header.replace(".", "", 1).isdigit():
        return float(header)
    if header:
        try:
            when = email.utils.parsedate_to_datetime(header)
        except (TypeError, ValueError):
            when = None
        if when is not None:
            return max(0.0, when.timestamp() - now)
    match = _RETRY_DELAY.search(body)
    return float(match.group(1)) if match else None


def _errors(body: str) -> list[dict[str, Any]]:
    """The error objects in a response body: OpenAI's and Anthropic's ``{"error": {...}}``, and
    Gemini's OpenAI-compatible endpoint's list of them."""
    try:
        data = json.loads(body)
    except ValueError:
        return []
    out: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else [data]:
        if isinstance(item, dict):
            error = item.get("error", item)
            if isinstance(error, dict):
                out.append(error)
    return out


def _quota_ids(errors: list[dict[str, Any]]) -> list[str]:
    """Gemini's QuotaFailure violations: the quota ids and metrics that ran out."""
    ids: list[str] = []
    for error in errors:
        for detail in error.get("details") or []:
            if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith(
                "QuotaFailure"
            ):
                continue
            for violation in detail.get("violations") or []:
                if isinstance(violation, dict):
                    ids += [
                        str(violation[k]) for k in ("quotaId", "quotaMetric") if violation.get(k)
                    ]
    return ids


def _regain(text: str) -> float | None:
    """The moment a spend-limit message says access returns, as epoch seconds."""
    match = _REGAIN.search(text)
    if match is None:
        return None
    day, hour, minute = match.group(1), match.group(2) or "0", match.group(3) or "0"
    try:
        moment = datetime.fromisoformat(day).replace(hour=int(hour), minute=int(minute), tzinfo=UTC)
    except ValueError:
        return None
    return moment.timestamp()


def classify(
    status: int,
    body: str,
    headers: Mapping[str, str],
    *,
    now: float,
    anthropic: bool = False,
) -> RateLimit | None:
    """The limit a refusal names, or None when it names none (a bad request, a bad key)."""
    if status not in _LIMIT_STATUSES:
        return None
    errors = _errors(body)
    words = " ".join(
        str(error.get(field, ""))
        for error in errors
        for field in ("code", "type", "status", "message")
    )
    text = words or body[:2_000]
    retry = retry_after_seconds(headers, body, now=now)
    codes = {str(error.get(k, "")).lower() for error in errors for k in ("code", "type")}
    if "insufficient_quota" in codes or _NO_CREDIT.search(text):
        return RateLimit("no_credit", "the account has no credit or quota left")
    until = _regain(text)
    if until is not None or (status in (400, 402, 403, 429) and _SPEND.search(text)):
        return RateLimit("spend_cap", "the account's spending cap is reached", until=until)
    if status in (503, 529):
        return RateLimit("overload", f"the provider is busy (HTTP {status})", retry_after=retry)
    if status != 429:
        return None
    ids = _quota_ids(errors)
    if any(_PER_DAY.search(i) for i in ids) or (not ids and _PER_DAY.search(text)):
        return RateLimit("day", "its daily quota is used up", retry_after=retry)
    if any(_PER_MINUTE.search(i) for i in ids) or (not ids and _PER_MINUTE.search(text)):
        return RateLimit("minute", "its per-minute limit is reached", retry_after=retry)
    if anthropic and retry is None:
        # Anthropic's rate limits always say when to retry; its spend limit does not.
        return RateLimit("spend_cap", "the account's spending limit is reached")
    return RateLimit("minute", "its rate limit is reached", retry_after=retry)
