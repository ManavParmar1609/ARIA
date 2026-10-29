"""What ARIA learns from and how it measures itself: reviews, calibration, evaluation, tickets."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from aria.api.schemas import CalibrationOut, FeedbackOut, ReviewOut
from aria.api.state import AppState, app_state
from aria.contracts.base import Severity
from aria.contracts.inputs import TicketContext
from aria.contracts.severity import TicketAssessment
from aria.db import repository as repo
from aria.severity.recalibration import reviewed_examples, reviews_in

router = APIRouter(prefix="/api/v1", tags=["learning"])
State = Annotated[AppState, Depends(app_state)]

# Fresh results from `make eval` when they exist, else the copy committed with the release.
EVAL_RESULTS = (Path("reports/eval/all.json"), Path("docs/eval-results.json"))


def _severity(value: Any) -> Severity | None:
    try:
        return Severity(str(value))
    except ValueError:
        return None


@router.get("/feedback", response_model=FeedbackOut)
async def feedback(state: State, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> FeedbackOut:
    """Human reviews (the active-learning queue) and where model recalibration stands."""
    services = state.services
    engine, model = services.engine, services.severity.model
    rows = await asyncio.to_thread(repo.list_feedback, engine, limit=limit)
    reviewed = len(await asyncio.to_thread(reviewed_examples, engine, model)) if model else 0
    in_model = reviews_in(model) if model else 0
    meta = model.metadata if model else {}
    config = services.config.severity
    return FeedbackOut(
        calibration=CalibrationOut(
            model_version=model.version if model else None,
            trained_version=str(meta.get("trained_version", model.version)) if model else None,
            recalibrated=bool(meta.get("recalibrated_from")),
            reviews_in_model=in_model,
            reviewed=reviewed,
            pending=max(0, reviewed - in_model),
            recalibrate_after=config.recalibrate_after,
            check_interval_s=config.recalibrate_check_s,
            coverage_before=meta.get("coverage_before"),
            coverage_after=meta.get("coverage_after"),
        ),
        reviews=[
            ReviewOut(
                run_id=row["run_id"],
                decision=str(row["value"].get("decision", "")),
                from_severity=_severity(row["value"].get("from")),
                to_severity=_severity(row["value"].get("to")),
                reviewer=row["author"],
                comment=row["comment"],
                failure_mode=row["value"].get("failure_mode"),
                used_for_recalibration=row["used"],
                created_at=row["created_at"],
            )
            for row in rows
        ],
    )


@router.get("/eval")
async def evaluation() -> dict[str, Any]:
    """The latest evaluation results: what `make eval` measured, and on what data."""
    for path in EVAL_RESULTS:
        if path.is_file():
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            results: dict[str, Any] = json.loads(text)
            return results
    raise HTTPException(status.HTTP_404_NOT_FOUND, "no evaluation results yet: run `make eval`")


@router.post("/tickets/assess", response_model=TicketAssessment)
async def assess_ticket(ticket: TicketContext, state: State) -> TicketAssessment:
    """Priority and SLA-breach risk for an ITSM ticket, from the model trained on UCI history."""
    models = state.services.tickets
    if models is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the ticket model is not trained: ingest the UCI incident log "
            "(`aria data ingest`), then run `aria train tickets`",
        )
    prediction = await asyncio.to_thread(models.predict, ticket)
    return TicketAssessment(
        predicted_priority=prediction.priority,
        severity=prediction.severity,
        probabilities=prediction.probabilities,
        prediction_set=prediction.prediction_set,
        sla_breach_risk=prediction.sla_breach_risk,
        model_version=models.version,
    )
