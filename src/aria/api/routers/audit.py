"""The decision record: a run's entries, and whether the whole chain still holds."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from aria.api.schemas import RunId
from aria.api.state import AppState, app_state
from aria.api.visitors import ViewerDep
from aria.contracts.record import ChainCheck, DecisionRecord
from aria.db import record
from aria.db import repository as repo

router = APIRouter(prefix="/api/v1", tags=["audit"])
State = Annotated[AppState, Depends(app_state)]
MAX_SEQ = 2**53  # a cursor past this cannot be stored, or read exactly in JavaScript


@router.get("/audit/verify", response_model=ChainCheck)
async def verify_record(state: State) -> ChainCheck:
    """Walk the decision record from its first entry and say whether every link holds: how
    long it is, the first entry that breaks it (if any) and the newest hash, to anchor
    elsewhere. It reads every entry, so call it on a schedule, not on every page view."""
    return await asyncio.to_thread(record.verify, state.services.engine)


@router.get("/runs/{run_id}/record", response_model=list[DecisionRecord])
async def run_record(
    run_id: RunId,
    state: State,
    viewer: ViewerDep,
    after: Annotated[int, Query(ge=-1, le=MAX_SEQ)] = -1,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 200,
) -> list[DecisionRecord]:
    """A run's decisions, oldest first: each review, edit, publish, message sent and blind check,
    with who made it and the hashes that chain it to the rest of the record."""
    engine = state.services.engine
    run = await asyncio.to_thread(repo.get_run, engine, run_id)
    if run is None or not viewer.can_see(run):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return await asyncio.to_thread(
        record.list_entries, engine, run_id=run_id, after=after, limit=limit
    )
