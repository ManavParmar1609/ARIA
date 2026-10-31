"""Each visitor's own incidents on a shared public demo.

With ``ARIA_VISITOR_SCOPE=true``, a server without API keys keeps its visitors apart. The console
gives every browser a private session id (an HttpOnly cookie) and sends it as ``X-Visitor-Id``. A
run records a hash of that id, never the id itself, and a visitor sees their own runs plus the
examples: runs the server started itself (seeded, scanned or sent with an API key). Examples stay
as they are for the next visitor, so nobody may review, resend or delete one; forking makes a
visitor their own copy. Callers that send no id share one anonymous space, and callers with an
API key see every run, as on a server without scoping.
"""

from __future__ import annotations

import asyncio
import hashlib
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status

from aria.api.security import VISITOR_ID, Principal
from aria.api.state import AppState, app_state, current_principal
from aria.db import repository as repo

ANONYMOUS = "anonymous"

EXAMPLE_STAYS = (
    "This example is shared by every visitor, so it stays as it is. "
    "Make your own copy to review it, send its messages or delete it."
)


@dataclass(frozen=True)
class Viewer:
    """Whose runs a request may see: one visitor's (``tag``), or every run when ``tag`` is None."""

    tag: str | None = None

    def can_see(self, run: dict[str, Any]) -> bool:
        return self.tag is None or run.get("visitor") in (None, self.tag)

    def is_example(self, run: dict[str, Any]) -> bool:
        """A run every visitor sees and none may change."""
        return self.tag is not None and run.get("visitor") is None

    def refuse_example(self, run: dict[str, Any]) -> None:
        if self.is_example(run):
            raise HTTPException(status.HTTP_403_FORBIDDEN, EXAMPLE_STAYS)


SEES_ALL = Viewer()  # a server without scoping, or a caller with an API key


# One lock per visitor while they have a start in progress; unused ones go with the last holder.
_ROOMS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


@asynccontextmanager
async def make_room(state: AppState, viewer: Viewer) -> AsyncIterator[None]:
    """Refuse a visitor's new triage while their share is already waiting or running: with one
    queue for everyone, a visitor's pile of pastes would hold up every other visitor's next one.

    Record the run inside it. A visitor's starts take turns through it, so several that arrive
    together cannot all pass the count before any of them is recorded. The turns are kept in this
    process, which is all a demo server runs.
    """
    most = state.services.settings.max_active_runs_per_visitor
    if not most or viewer.tag is None:
        yield
        return
    lock = _ROOMS.get(viewer.tag)
    if lock is None:
        lock = _ROOMS[viewer.tag] = asyncio.Lock()
    async with lock:
        active = await asyncio.to_thread(repo.active_runs, state.services.engine, viewer.tag)
        if active >= most:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"You already have {active} triages queued or running. Start another once one "
                "of them is ready for review.",
            )
        yield


def visitor_tag(session_id: str | None) -> str:
    """What a run records for a session id. A hash, so the database never holds an id that would
    let someone act as its visitor. Without an id, the caller is in the shared anonymous space."""
    if not session_id:
        return ANONYMOUS
    return "v-" + hashlib.sha256(session_id.encode()).hexdigest()[:32]


def viewer_for(scoped: bool, caller: Principal, session_id: str | None) -> Viewer:
    """Whose runs this caller sees: every run unless the server keeps visitors apart and the
    caller has no API key. A malformed session id is refused rather than shared."""
    if not scoped or caller.authenticated:
        return Viewer()
    session_id = (session_id or "").strip() or None
    if session_id is not None and not VISITOR_ID.fullmatch(session_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "X-Visitor-Id should be 16 to 64 letters, digits, dashes or underscores.",
        )
    return Viewer(visitor_tag(session_id))


async def current_viewer(
    state: Annotated[AppState, Depends(app_state)],
    caller: Annotated[Principal, Depends(current_principal)],
    session_id: Annotated[
        str | None,
        Header(
            alias="X-Visitor-Id",
            description=(
                "A private session id: 16 to 64 letters, digits, dashes or underscores. On a server "
                "with ARIA_VISITOR_SCOPE=true you see the runs you started with it, plus the "
                "examples. The console sends one for you."
            ),
        ),
    ] = None,
) -> Viewer:
    return viewer_for(state.services.settings.visitor_scope, caller, session_id)


ViewerDep = Annotated[Viewer, Depends(current_viewer)]
