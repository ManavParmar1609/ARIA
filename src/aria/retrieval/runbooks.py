"""Runbook library: Markdown files with YAML front matter (see ``runbooks/README.md``)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from sqlalchemy import delete, insert
from sqlalchemy.engine import Engine

from aria.db.engine import session_scope
from aria.db.models import RunbookRow

Risk = Literal["low", "medium", "high"]
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTION = re.compile(r"^## (.+)$", re.MULTILINE)
_NUMBERED = re.compile(r"^\d+\.\s+(.*)$")
_RISK_TAG = re.compile(r"\s*\[risk:\s*(low|medium|high)\]\s*$", re.IGNORECASE)
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Step:
    text: str
    risk: Risk = "low"


@dataclass(frozen=True)
class Runbook:
    slug: str
    title: str
    systems: tuple[str, ...]
    failure_modes: tuple[str, ...]
    risk: Risk
    when: str
    diagnose: tuple[Step, ...]
    mitigate: tuple[Step, ...]
    verify: tuple[Step, ...]
    escalate: str
    body: str
    path: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def generic(self) -> bool:
        return "*" in self.failure_modes

    def matches(self, system: str | None, failure_mode: str | None) -> bool:
        system_ok = "*" in self.systems or system is None or system in self.systems
        mode_ok = self.generic or failure_mode is None or failure_mode in self.failure_modes
        return system_ok and mode_ok

    def search_text(self) -> str:
        steps = " ".join(s.text for s in (*self.diagnose, *self.mitigate))
        return f"{self.title}. {' '.join(self.failure_modes)} {' '.join(self.systems)}. {self.when} {steps}"


def _steps(text: str) -> tuple[Step, ...]:
    steps: list[Step] = []
    for line in text.splitlines():
        match = _NUMBERED.match(line.strip())
        if not match:
            continue
        item = match.group(1).strip()
        tag = _RISK_TAG.search(item)
        risk: Risk = "low"
        if tag:
            risk = tag.group(1).lower()  # type: ignore[assignment]
            item = item[: tag.start()].rstrip()
        steps.append(Step(item, risk))
    return tuple(steps)


def parse_runbook(text: str, *, path: str = "") -> Runbook:
    match = _FRONT_MATTER.match(text.replace("\r\n", "\n"))
    if not match:
        msg = f"{path or 'runbook'}: missing YAML front matter"
        raise ValueError(msg)
    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()
    parts = _SECTION.split(body)
    sections = {parts[i].strip().lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    for required in ("slug", "title", "failure_modes"):
        if not meta.get(required):
            msg = f"{path or 'runbook'}: front matter needs {required}"
            raise ValueError(msg)
    risk = str(meta.get("risk", "low")).lower()
    if risk not in _RISK_ORDER:
        msg = f"{path}: risk must be low, medium or high"
        raise ValueError(msg)
    mitigate = _steps(sections.get("mitigate", ""))
    if not mitigate:
        msg = f"{path}: needs at least one numbered step under '## Mitigate'"
        raise ValueError(msg)
    return Runbook(
        slug=str(meta["slug"]),
        title=str(meta["title"]),
        systems=tuple(str(s) for s in meta.get("systems") or ["*"]),
        failure_modes=tuple(str(m) for m in meta["failure_modes"]),
        risk=risk,  # type: ignore[arg-type]
        when=" ".join(sections.get("when to use", "").split()),
        diagnose=_steps(sections.get("diagnose", "")),
        mitigate=mitigate,
        verify=_steps(sections.get("verify", "")),
        escalate=" ".join(sections.get("escalate", "").split()),
        body=body,
        path=path,
    )


@lru_cache(maxsize=4)
def load_runbooks(directory: Path = Path("runbooks")) -> dict[str, Runbook]:
    runbooks: dict[str, Runbook] = {}
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        runbook = parse_runbook(path.read_text(encoding="utf-8"), path=str(path))
        if runbook.slug in runbooks:
            msg = f"duplicate runbook slug {runbook.slug}"
            raise ValueError(msg)
        if runbook.slug != path.stem:
            msg = f"{path}: slug {runbook.slug!r} must match the file name"
            raise ValueError(msg)
        runbooks[runbook.slug] = runbook
    return runbooks


def sync_runbooks(engine: Engine, runbooks: dict[str, Runbook]) -> int:
    """Replace the runbooks table with the library on disk (the files are the source of truth)."""
    now = datetime.now(UTC)
    rows = [
        {
            "slug": rb.slug,
            "title": rb.title,
            "systems": list(rb.systems),
            "failure_modes": list(rb.failure_modes),
            "risk": rb.risk,
            "steps": [{"text": s.text, "risk": s.risk} for s in rb.mitigate],
            "body": rb.body,
            "updated_at": now,
        }
        for rb in runbooks.values()
    ]
    with session_scope(engine) as session:
        session.execute(delete(RunbookRow))
        if rows:
            session.execute(insert(RunbookRow), rows)
    return len(rows)


def max_risk(*risks: Risk) -> Risk:
    return max(risks, key=_RISK_ORDER.__getitem__) if risks else "low"
