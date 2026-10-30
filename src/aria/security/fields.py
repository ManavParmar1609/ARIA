"""Short untrusted fields: alert names, labels and annotations, and run titles.

They come from whoever can reach a monitoring system, and they end up in run titles, report claims,
outbound drafts and model prompts, so they are cleaned like log lines first. Control codes are
dropped and secrets are redacted as soon as an alert arrives. When a run starts, IP and e-mail
addresses are pseudonymised with the run's key (so they match the run's log lines), and a value
that reads like an instruction to a model is withheld whole.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from aria.config import GuardrailConfig
from aria.contracts.inputs import AlertSignal, TriageRequest
from aria.security.injection import scan_line
from aria.security.redaction import Redactor, is_secret_name

WITHHELD = "(withheld)"
_SURROGATES = re.compile("[\ud800-\udfff]")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# Bidirectional overrides and isolates make text read in a different order than it is stored
# (a title that reads backwards in a chat message), so short fields drop them.
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")


def sanitize(text: str) -> str:
    """Make text safe to hash, store and show: lone surrogates (valid in JSON, not in UTF-8)
    become U+FFFD, and NUL bytes and terminal colour codes are dropped."""
    if "\x1b" in text:
        text = _ANSI.sub("", text)
    return _SURROGATES.sub("\ufffd", text).replace("\x00", "")


def strip_secrets(text: str) -> str:
    """Sanitise and redact secrets, keeping addresses (for intake, before a run has a key)."""
    return Redactor(pseudonymize_ips=False).redact(sanitize(text))


def clean_map(values: Mapping[str, str], clean: Callable[[str], str]) -> dict[str, str]:
    """Labels or annotations cleaned value by value; a secret-named one (``token``) is redacted."""
    return {sanitize(k): "[REDACTED]" if is_secret_name(k) else clean(v) for k, v in values.items()}


def one_line(text: str) -> str:
    """A field shown on one line (a title, a service name, an alert name) as one plain line: no
    line breaks for a heading to break on, and no bidirectional controls to reorder it."""
    return " ".join(_BIDI.sub("", text).split())


class _Cleaner:
    """Cleans one request's fields with the run's redactor, remembering what it withheld.

    Cleaning is idempotent: a request cleaned when its run was created comes through the plan
    step unchanged, and a withheld value is still reported as withheld."""

    def __init__(self, guard: GuardrailConfig, salt: bytes) -> None:
        self.guard = guard
        self.redactor = Redactor(pseudonymize_ips=guard.pseudonymize_ips, salt=salt)
        self.withheld = False

    def __call__(self, text: str) -> str:
        if text == WITHHELD:
            self.withheld = True
            return text
        text = _BIDI.sub("", sanitize(text))
        if self.guard.detect_injection and scan_line(text, 0) is not None:
            self.withheld = True
            return WITHHELD
        return self.redactor.redact(text) if self.guard.redact_pii else text


def clean_request(
    request: TriageRequest, guard: GuardrailConfig, salt: bytes
) -> tuple[TriageRequest, list[str]]:
    """The request with its title, service and alerts cleaned, and a note per alert it withheld
    text from. A title that reads like an instruction is dropped, so the report writes its own."""
    clean = _Cleaner(guard, salt)
    alerts: list[AlertSignal] = []
    notes: list[str] = []
    for alert in request.alerts:
        clean.withheld = False
        alerts.append(
            alert.model_copy(
                update={
                    "name": one_line(clean(alert.name)),
                    "labels": clean_map(alert.labels, clean),
                    "annotations": clean_map(alert.annotations, clean),
                }
            )
        )
        if clean.withheld:
            notes.append(f"alert {alert.fingerprint}: instruction-like text withheld")

    def optional(text: str | None) -> str | None:
        value = one_line(clean(text)) if text else text
        return None if value in (WITHHELD, "") else value

    ticket = request.ticket
    if ticket is not None:
        # Ticket fields are typed by people too: a location or symptom can hold a password.
        clean.withheld = False
        ticket = ticket.model_copy(
            update={
                name: optional(value)
                for name, value in ticket.model_dump().items()
                if isinstance(value, str)
            }
        )
        if clean.withheld:
            notes.append("ticket: instruction-like text withheld")
    cleaned = request.model_copy(
        update={
            "title": optional(request.title),
            "service": optional(request.service),
            "environment": optional(request.environment),
            "alerts": alerts,
            "ticket": ticket,
        }
    )
    return cleaned, notes
