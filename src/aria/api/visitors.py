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

import hashlib
import re
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status

from aria.api.security import Principal
from aria.api.state import AppState, app_state, current_principal

ANONYMOUS = "anonymous"
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")

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
    if session_id is not None and not _SESSION_ID.fullmatch(session_id):
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
