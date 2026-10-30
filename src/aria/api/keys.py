"""A visitor's own model key, read from a request's headers.

``X-Model-Provider`` names the kind of key (``claude``, ``gemini``, ``openai`` or ``nvidia``: the
kinds ``visitor_keys`` lists in config/aria.yaml) and ``X-Model-Key`` carries it. This server takes
them only when ``ARIA_VISITOR_KEYS=true`` and runs execute in this process, since a key is never
written anywhere a separate worker could read it. Errors here never repeat the key.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from aria.api.state import AppState, app_state
from aria.llm.visitor import VisitorKey, parse_key


def accepted_kinds(state: AppState) -> list[str]:
    """The kinds of key visitors may send to this server: none unless the feature is on and runs
    execute in this process."""
    return state.services.config.llm.visitor_keys.accepted() if state.inprocess else []


async def visitor_key(
    state: Annotated[AppState, Depends(app_state)],
    provider: Annotated[
        str | None,
        Header(
            alias="X-Model-Provider",
            description="The kind of key in X-Model-Key: claude, gemini, openai or nvidia.",
        ),
    ] = None,
    key: Annotated[
        str | None,
        Header(
            alias="X-Model-Key",
            description=(
                "Your own model key, used for this request's run or question only and never "
                "stored. Accepted when the server sets ARIA_VISITOR_KEYS=true."
            ),
        ),
    ] = None,
) -> VisitorKey | None:
    if key is None or not key.strip():
        return None
    kinds = accepted_kinds(state)
    if not kinds:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This server does not take visitors' own model keys. Send the request without "
            "X-Model-Key, or ask its operator to set ARIA_VISITOR_KEYS=true.",
        )
    kind = (provider or "").strip().lower()
    if kind not in kinds:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Name the key's provider in X-Model-Provider: {', '.join(kinds)}.",
        )
    secret = parse_key(key)
    if secret is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "X-Model-Key does not look like an API key: it should be 20 to 200 letters, digits, "
            "dots, dashes or underscores.",
        )
    return VisitorKey(kind, secret)


VisitorKeyDep = Annotated[VisitorKey | None, Depends(visitor_key)]
