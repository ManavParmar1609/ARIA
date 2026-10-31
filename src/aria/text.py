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


# Failure modes as people write them (the console's own list, web/src/lib/failure-modes.ts); the
# rest read fine with spaces for underscores.
_FAILURE_WORDS = {
    "auth_failures": "authentication failures",
    "bruteforce": "brute-force attempts",
    "dns_resolution": "DNS resolution",
    "hdfs_lease_renewal": "HDFS lease renewal",
    "mod_jk_worker_error": "mod_jk worker errors",
    "psu_failure": "PSU failure",
    "resourcemanager_unreachable": "ResourceManager unreachable",
    "unfinished_work": "work that stops partway",
}


def failure_words(mode: str) -> str:
    """A failure mode in words: "bruteforce" reads "brute-force attempts"."""
    return _FAILURE_WORDS.get(mode, mode.replace("_", " "))
