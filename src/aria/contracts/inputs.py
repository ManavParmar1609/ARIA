"""What ARIA is asked to triage."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from aria.contracts.base import Contract


class AlertSignal(Contract):
    """An alert from a monitoring system, normalised across Alertmanager, Grafana and webhooks."""

    source: Literal["alertmanager", "grafana", "webhook", "scan", "manual"] = "manual"
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    fingerprint: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    status: Literal["firing", "resolved"] = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


# Impact and urgency as ServiceNow writes them; a bare digit or the word maps onto them.
_LEVELS = {"1": "1 - High", "2": "2 - Medium", "3": "3 - Low"}
_LEVEL_WORDS = {"high": "1", "medium": "2", "low": "3"}
_LEVEL_FORM = re.compile(r"([123])(?: - .+)?")  # the level digit is what the model reads


def _ticket_level(value: str | None) -> str | None:
    """'1 - High', '1' and 'High' -> '1 - High'; blank -> None; anything else is refused, so a
    level the model never learned is a 422, not a confident lowest priority."""
    text = " ".join((value or "").split())
    if not text:
        return None
    match = _LEVEL_FORM.fullmatch(text)
    digit = _LEVEL_WORDS.get(text.lower()) or (match.group(1) if match else None)
    if digit is None:
        msg = "must be 1 - High, 2 - Medium or 3 - Low (or 1, 2, 3, or High, Medium, Low)"
        raise ValueError(msg)
    return _LEVELS[digit]


class TicketContext(Contract):
    """ITSM ticket fields as they exist when a ticket is opened (ServiceNow-style)."""

    number: str | None = None
    category: str | None = None
    subcategory: str | None = None
    symptom: str | None = None
    cmdb_ci: str | None = None
    contact_type: str | None = None
    location: str | None = None
    assignment_group: str | None = None
    impact: str | None = None
    urgency: str | None = None
    opened_at: datetime | None = None
    knowledge: bool | None = None
    priority_confirmation: bool | None = None

    @field_validator("impact", "urgency")
    @classmethod
    def _known_level(cls, value: str | None) -> str | None:
        return _ticket_level(value)


class RunOptions(Contract):
    require_approval: bool = True
    use_llm: bool = True
    investigate: bool = True
    fanout: bool = True
    provider: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, ge=0)


class SampleRef(Contract):
    """The console sample a run's logs were built from, at the sizes chosen (None: no choice)."""

    id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    servers: Annotated[int, Field(ge=1, le=64)] | None = None
    rate: Annotated[int, Field(ge=1, le=1_000)] | None = None


class TriageRequest(Contract):
    """Input to a triage run. At least one of logs, window_id, alerts or ticket is required."""

    title: Annotated[str, StringConstraints(max_length=200)] | None = None
    # A system names a log format and a memory namespace: letters, digits, "_" and "-" only, and
    # no longer than the database columns that store it.
    system: Annotated[
        str, StringConstraints(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    ] = "generic"
    service: Annotated[str, StringConstraints(max_length=120)] | None = None
    environment: Annotated[str, StringConstraints(max_length=64)] | None = None
    logs: list[str] = Field(default_factory=list)
    window_id: str | None = None
    alerts: list[AlertSignal] = Field(default_factory=list)
    ticket: TicketContext | None = None
    options: RunOptions = Field(default_factory=RunOptions)
    # True when the logs come from a semi-synthetic scenario; reports and memory label it.
    synthetic: bool = False
    # The real incident these logs replay (aria.data.real), so a run can be checked against the
    # labels its experts gave. Set by the replay endpoint.
    replay_of: Annotated[str, StringConstraints(max_length=64)] | None = None
    # The console sample these logs were built from, so the incident page can offer the next size
    # and compare the two. Set by the samples endpoint.
    sample: SampleRef | None = None
    # Lines past the per-run cap. ARIA drops them when it records a run, so they are never stored,
    # and counts them here for the plan's note. It is not part of the published schema.
    logs_dropped: SkipJsonSchema[Annotated[int, Field(ge=0)]] = 0

    @model_validator(mode="after")
    def _has_something_to_triage(self) -> TriageRequest:
        lines = any(line.strip() for line in self.logs)
        if not (lines or self.window_id or self.alerts or self.ticket):
            msg = "provide logs (at least one non-blank line), a window_id, alerts or a ticket"
            raise ValueError(msg)
        return self
