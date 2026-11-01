"""Text helpers shared by the report writer, the investigator and Ask ARIA."""

from __future__ import annotations

import re

_SEVERITY_PREFIX = re.compile(r"^SEV[1-4]\s*·\s*")
_LAST_WORD = re.compile(r"\S+$")
_TRAILING_NUMBER = re.compile(r"[\d.,:]+$")
_WILDCARD = re.compile(r"<\*>")
# A first word that is plain lower-case letters, so capitalising it changes no name.
_PLAIN_WORD = re.compile(r"[a-z]+(?=[\s,:;]|$)")


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


# Failure modes as people write them (the console's own list, web/src/lib/failure-modes.ts); the
# rest read fine with spaces for underscores.
_FAILURE_WORDS = {
    "auth_failures": "authentication failures",
    "bruteforce": "brute-force attempts",
    "hdfs_lease_renewal": "HDFS lease renewal",
    "mod_jk_worker_error": "mod_jk worker errors",
    "psu_failure": "PSU failure",
    "resourcemanager_unreachable": "ResourceManager unreachable",
    "unfinished_work": "work that stops partway",
}


def failure_words(mode: str) -> str:
    """A failure mode in words: "bruteforce" reads "brute-force attempts"."""
    return _FAILURE_WORDS.get(mode, mode.replace("_", " "))


def plain_template(template: str) -> str:
    """A log pattern as people read it: each part that varies (``<*>``) becomes "…"."""
    return _WILDCARD.sub("…", template)


def sentence_start(text: str) -> str:
    """``text`` with its first letter capitalised when it opens with a plain word. A name such as
    ``payments.Gateway`` or ``eth0`` keeps its exact spelling."""
    return text[:1].upper() + text[1:] if _PLAIN_WORD.match(text) else text
