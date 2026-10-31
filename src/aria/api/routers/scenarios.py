"""Samples: incidents the console can build and triage, from real Loghub lines."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status

from aria.api.keys import VisitorKeyDep, check_provider, may_use_model, offline
from aria.api.schemas import (
    RunAccepted,
    SampleRunRequest,
    ScenarioOut,
    SizeChoiceOut,
    SizeOptionOut,
    links_for,
)
from aria.api.state import AppState, app_state
from aria.api.visitors import ViewerDep, make_room
from aria.config import get_app_config, get_settings
from aria.contracts.inputs import SampleRef, TriageRequest
from aria.contracts.run import RunStatus
from aria.data.scenarios import (
    SOURCES,
    LinePools,
    ScenarioBuilder,
    SizeChoice,
    loghub_dir,
)
from aria.observability.logging import get_logger
from aria.severity.samples import saved_sizes

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/scenarios", tags=["samples"])
State = Annotated[AppState, Depends(app_state)]


@lru_cache(maxsize=1)
def _builder() -> ScenarioBuilder:
    """The sample builder over this server's Loghub lines (the full samples when downloaded,
    else the small copies that ship with ARIA). Built once: reading the lines takes a moment.

    Its sizes are the ones ``aria seed`` rated the way a run rates them; without those (no seed,
    or the model, rules, catalog or lines changed since) they follow the samples' labels.
    """
    settings = get_settings()
    lines = loghub_dir(settings.data_dir)
    builder = ScenarioBuilder(LinePools.from_loghub(lines))
    sizes = saved_sizes(settings, get_app_config(), lines)
    if sizes is None:
        log.warning("samples.sizes_unrated", hint="run `aria seed` to rate the samples' sizes")
    else:
        builder.use_sizes(sizes)
    return builder


def _choice(
    choice: SizeChoice | None, *, unit: Literal["servers", "per_minute"]
) -> SizeChoiceOut | None:
    if choice is None:
        return None

    def label(n: int) -> str:
        if unit == "servers":
            return f"{n} server" if n == 1 else f"{n} servers"
        return f"{n} lines a minute"

    return SizeChoiceOut(
        question="How many servers?"
        if unit == "servers"
        else "How fast do the problem lines come?",
        unit=unit,
        default=choice.default,
        options=[SizeOptionOut(value=n, label=label(n)) for n in choice.values],
    )


def _listing() -> list[ScenarioOut]:
    builder = _builder()
    out: list[ScenarioOut] = []
    for key in builder.pools.available_modes():
        mode = builder.pools.modes[key]
        card = mode.card
        if card is None:
            continue
        sizes = builder.sample_sizes(key)
        out.append(
            ScenarioOut(
                id=key,
                title=card.title,
                technology=card.technology,
                source=card.source,
                source_name=SOURCES[card.source],
                summary=card.summary,
                system=mode.system,
                benign=mode.benign,
                headline=card.headline,
                tricky=card.trick is not None,
                preview=builder.preview(key),
                servers=_choice(sizes.servers, unit="servers"),
                rate=_choice(sizes.rate, unit="per_minute"),
            )
        )
    order = list(SOURCES)
    return sorted(out, key=lambda s: (order.index(s.source), not s.headline, s.title))


@router.get("", response_model=list[ScenarioOut])
async def list_scenarios() -> list[ScenarioOut]:
    """The samples this server can build, by where their logs come from. Each is made of real
    Loghub lines arranged into an incident, and offers a size only where the size changes how
    serious the incident is."""
    return await asyncio.to_thread(_listing)


def _size(choice: SizeChoice | None, given: int | None, noun: str) -> int | None:
    if given is None:
        return None
    if choice is None:
        detail = f"This sample has no {noun} to choose: its severity does not depend on it."
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if given not in choice.values:
        *rest, last = (str(v) for v in choice.values)
        detail = f"Choose the {noun} from {', '.join(rest)} or {last}."
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    return given


@router.post(
    "/{scenario_id}/runs", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted
)
async def run_scenario(
    scenario_id: str,
    state: State,
    visitor: VisitorKeyDep,
    viewer: ViewerDep,
    body: SampleRunRequest | None = None,
) -> RunAccepted:
    """Build a sample on this server and triage it as a run; follow it on ``links.stream``."""
    body = body or SampleRunRequest()
    check_provider(state, body.options.provider, visitor)
    async with make_room(state, viewer):
        options = body.options
        if not may_use_model(state, visitor, viewer.tag, options.use_llm):
            options = offline(options)
        builder = _builder()
        mode = builder.pools.modes.get(scenario_id)
        if mode is None or mode.card is None or scenario_id not in builder.pools.available_modes():
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no sample {scenario_id!r}")
        sizes = await asyncio.to_thread(builder.sample_sizes, scenario_id)
        servers = _size(sizes.servers, body.servers, "number of servers")
        rate = _size(sizes.rate, body.rate, "rate")
        scenario = await asyncio.to_thread(builder.sample, scenario_id, servers=servers, rate=rate)
        request = TriageRequest(
            system=scenario.system,
            logs=scenario.lines,
            synthetic=True,
            options=options,
            sample=SampleRef(
                id=scenario_id,
                servers=(servers or sizes.servers.default) if sizes.servers else None,
                rate=(rate or sizes.rate.default) if sizes.rate else None,
            ),
        )
        run_id = await asyncio.to_thread(
            state.runner.submit, request, trigger="sample", visitor=viewer.tag
        )
    if visitor is not None:
        state.runner.keys.hold(run_id, visitor)
    if state.inprocess:
        state.worker.execute(run_id)
    return RunAccepted(run_id=run_id, status=str(RunStatus.QUEUED), links=links_for(run_id))
