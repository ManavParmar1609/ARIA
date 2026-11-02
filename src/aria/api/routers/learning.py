"""What ARIA learns from and how it measures itself: reviews and reviewers, calibration,
evaluation, tickets."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from aria.api.reviewers import reviewer_stats
from aria.api.schemas import (
    BlindCase,
    BlindCheckOut,
    BlindPattern,
    BlindRating,
    BlindReveal,
    CalibrationOut,
    DriftOut,
    FeedbackOut,
    ReviewerOut,
    ReviewersOut,
    ReviewOut,
    SystemDrift,
)
from aria.api.security import Principal
from aria.api.state import AppState, app_state, current_principal
from aria.api.visitors import ViewerDep
from aria.contracts.base import Severity
from aria.contracts.inputs import TicketContext, TriageRequest
from aria.contracts.parsing import ParsedBatch
from aria.contracts.severity import SeverityAssessment, TicketAssessment
from aria.db import record
from aria.db import repository as repo
from aria.graph.runner import RunNotFoundError
from aria.severity.drift import MIN_RUNS, level_drift
from aria.severity.recalibration import reviewed_examples, reviews_in

router = APIRouter(prefix="/api/v1", tags=["learning"])
State = Annotated[AppState, Depends(app_state)]
Caller = Annotated[Principal, Depends(current_principal)]
BLIND_PATTERNS = 8  # the patterns a blind check shows: errors first, then the most frequent

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
    await asyncio.to_thread(services.severity.refresh)  # the worker may have recalibrated
    engine, model = services.engine, services.severity.model
    rows = await asyncio.to_thread(repo.list_feedback, engine, limit=limit)
    reviewed = len(await asyncio.to_thread(reviewed_examples, engine, model)) if model else 0
    in_model = reviews_in(model) if model else 0
    meta = model.metadata if model else {}
    config = services.config.severity
    blind = len(await asyncio.to_thread(repo.feedback_of, engine, "blind_check"))
    return FeedbackOut(
        calibration=CalibrationOut(
            model_version=model.version if model else None,
            trained_version=model.trained_version if model else None,
            recalibrated=bool(meta.get("recalibrated_from")),
            reviews_in_model=in_model,
            reviewed=reviewed,
            pending=max(0, reviewed - in_model),
            recalibrate_after=config.recalibrate_after,
            check_interval_s=config.recalibrate_check_s,
            coverage_before=meta.get("coverage_before"),
            coverage_after=meta.get("coverage_after"),
            per_level=bool(model and model.calibrations),
            blind_checks=blind,
            adapted_on=int((meta.get("aci") or {}).get("checks", 0)),
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


@router.get("/reviewers", response_model=ReviewersOut)
async def reviewers(
    state: State, limit: Annotated[int, Query(ge=1, le=10_000)] = 2_000
) -> ReviewersOut:
    """How each person reviews: how often they approve a report without editing it, how often
    they set a level other than ARIA's, and the median time from a run pausing for review to
    their decision. From the newest ``limit`` reviews ARIA keeps; reviews of a visitor's own
    runs on a shared demo are not kept, so they are not counted."""
    rows = await asyncio.to_thread(repo.review_decisions, state.services.engine, limit=limit)
    moments = [row["decided_at"] for row in rows if row["decided_at"] is not None]
    return ReviewersOut(
        reviewers=[
            ReviewerOut(
                reviewer=stats.reviewer,
                decisions=stats.decisions,
                approved_as_is=stats.approved_as_is,
                edited=stats.edited,
                rejected=stats.rejected,
                level_changed=stats.level_changed,
                timed=len(stats.waits_s),
                median_wait_s=stats.median_wait_s,
            )
            for stats in reviewer_stats(rows)
        ],
        decisions=len(rows),
        since=min(moments) if moments else None,
        limit=limit,
    )


async def _decided(state: AppState, run_id: str) -> tuple[ParsedBatch, SeverityAssessment, Any]:
    """A run's parsed logs, ARIA's assessment and its request, or 404."""
    try:
        snapshot = await state.runner.snapshot(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run") from exc
    values = snapshot.values
    if not values.get("batch") or not values.get("severity"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this run has no severity to check yet")
    return (
        ParsedBatch.model_validate(values["batch"]),
        SeverityAssessment.model_validate(values["severity"]),
        TriageRequest.model_validate(values["request"]),
    )


def _case(run_id: str, batch: ParsedBatch) -> BlindCase:
    features = batch.features
    patterns = sorted(batch.templates, key=lambda t: (not t.error_like, -t.count))
    return BlindCase(
        run_id=run_id,
        system=batch.system,
        lines=features.n_events,
        error_lines=features.error_events,
        warning_lines=int(features.level_counts.get("WARN", 0))
        + int(features.level_counts.get("WARNING", 0)),
        nodes=features.distinct_nodes,
        minutes=round(features.duration_s / 60, 1),
        patterns=[
            BlindPattern(
                template=t.template[:400], count=t.count, error_like=t.error_like, new=t.novel
            )
            for t in patterns[:BLIND_PATTERNS]
        ],
    )


@router.get("/blind-check", response_model=BlindCheckOut)
async def blind_check(state: State, viewer: ViewerDep) -> BlindCheckOut:
    """A recent incident, picked at random, to rate before seeing ARIA's level.

    Only what the logs showed comes back: no level, set, report or title (a title opens with the
    level). On a shared demo a visitor may try it, but only a key-holder's ratings recalibrate.
    """
    engine = state.services.engine
    candidates = await asyncio.to_thread(repo.blind_check_candidates, engine)
    checks = len(await asyncio.to_thread(repo.feedback_of, engine, "blind_check"))
    counted = viewer.tag is None
    for run_id in random.sample(candidates, k=min(len(candidates), 5)):
        try:
            batch, _, _ = await _decided(state, run_id)
        except HTTPException:
            continue  # a run whose state is gone: try another
        return BlindCheckOut(case=_case(run_id, batch), checks=checks, counted=counted)
    return BlindCheckOut(case=None, checks=checks, counted=counted)


@router.post("/blind-check/{run_id}", response_model=BlindReveal)
async def rate_blind(
    run_id: str, body: BlindRating, state: State, caller: Caller, viewer: ViewerDep
) -> BlindReveal:
    """Record a blind rating and show what ARIA decided. A key-holder's rating recalibrates."""
    services = state.services
    run = await asyncio.to_thread(repo.get_run, services.engine, run_id)
    if run is None or run.get("visitor") is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
    batch, assessment, request = await _decided(state, run_id)
    counted = viewer.tag is None
    if counted:
        facts = {
            "to": str(body.severity),
            "aria": str(assessment.severity),
            "set": [str(s) for s in assessment.prediction_set],
            "calibration": assessment.calibration,
            "model_version": assessment.model_version,
        }
        await asyncio.to_thread(
            repo.save_feedback,
            services.engine,
            run_id,
            "blind_check",
            {**facts, "model_row": services.severity.model_row(batch.features, request.alerts)},
            author=caller.name,
        )
        # On the decision record straight after: a rating that recalibrates ARIA is a decision.
        await asyncio.to_thread(
            record.append,
            services.engine,
            kind="blind_check",
            actor=caller.name,
            run_id=run_id,
            payload={**facts, "held": body.severity in assessment.prediction_set},
        )
    checks = len(await asyncio.to_thread(repo.feedback_of, services.engine, "blind_check"))
    return BlindReveal(
        run_id=run_id,
        yours=body.severity,
        aria=assessment.severity,
        prediction_set=assessment.prediction_set,
        held=body.severity in assessment.prediction_set,
        agreed=body.severity == assessment.severity,
        counted=counted,
        checks=checks,
    )


@router.get("/drift", response_model=DriftOut)
async def drift(state: State) -> DriftOut:
    """Per system, whether the levels ARIA decided lately differ from the ones it decided before
    by more than chance (see aria.severity.drift). Needs no labels."""
    levels = await asyncio.to_thread(repo.decided_levels, state.services.engine)
    systems = {system: level_drift(values) for system, values in sorted(levels.items())}
    return DriftOut(
        min_runs=MIN_RUNS,
        systems=[
            SystemDrift(system=system, **result) for system, result in systems.items() if result
        ],
        too_few_runs=sorted(system for system, result in systems.items() if result is None),
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
            "the ticket model is not trained: download the UCI incident log "
            "(`aria data download --source uci-incidents`), then run `aria train tickets`",
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
