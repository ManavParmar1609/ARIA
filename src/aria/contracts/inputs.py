"""What ARIA is asked to triage."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

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


class RunOptions(Contract):
    require_approval: bool = True
    use_llm: bool = True
    investigate: bool = True
    fanout: bool = True
    provider: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, ge=0)


class TriageRequest(Contract):
    """Input to a triage run. At least one of logs, window_id, alerts or ticket is required."""

    title: Annotated[str, StringConstraints(max_length=200)] | None = None
    system: Annotated[str, StringConstraints(min_length=1, max_length=64)] = "generic"
    service: str | None = None
    environment: str | None = None
    logs: list[str] = Field(default_factory=list)
    window_id: str | None = None
    alerts: list[AlertSignal] = Field(default_factory=list)
    ticket: TicketContext | None = None
    options: RunOptions = Field(default_factory=RunOptions)

    @model_validator(mode="after")
    def _has_something_to_triage(self) -> TriageRequest:
        if not (self.logs or self.window_id or self.alerts or self.ticket):
            msg = "provide logs, a window_id, alerts or a ticket"
            raise ValueError(msg)
        return self
