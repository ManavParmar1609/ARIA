"""Text helpers shared by the report writer, the investigator and Ask ARIA."""

from __future__ import annotations

import re

_SEVERITY_PREFIX = re.compile(r"^SEV[1-4]\s*·\s*")
_LAST_WORD = re.compile(r"\S+$")
_TRAILING_NUMBER = re.compile(r"[\d.,:]+$")


def headline(title: str) -> str:
    """A report title without the severity it leads with ("SEV3 · ")."""
    return _SEVERITY_PREFIX.sub("", title)


def clip(text: str, limit: int) -> str:
    """``text`` in at most ``limit`` characters, cut between words and marked with an ellipsis:
    a cut inside a word could leave part of a number ("50010" as "500") that no evidence holds,
    and a report quoting it would fail its own grounding check."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if not text[limit - 1].isspace():
        word = _LAST_WORD.search(head)
        if word is not None and word.start() > limit // 2:
            head = head[: word.start()]
        else:  # one very long word: at least never end on part of a number
            head = _TRAILING_NUMBER.sub("", head)
    return head.rstrip() + "…"
