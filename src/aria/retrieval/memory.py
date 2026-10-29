"""Incident memory: past incidents, how they were resolved, and how often they recur.

Rows live in the ``incidents`` table. Each published ARIA run adds one (source ``run``); the
seeded history is built from the semi-synthetic scenario suite (source ``curated``,
``synthetic=True``) so retrieval works before any real incident exists. Repeat history is
computed, not stored: a failure mode's occurrences and first/last seen dates aggregate every row
with the same system and failure mode.

Embeddings are stored with the id of the model that produced them. When the configured
embedding provider changes, stale vectors are recomputed, so an index never mixes models.
"""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import numpy as np
from sqlalchemy import select
from sqlalchemy.engine import Engine

from aria.contracts.base import Severity
from aria.db.engine import session_scope
from aria.db.models import IncidentRow
from aria.observability.logging import get_logger
from aria.retrieval.hybrid import Document, Hit, HybridIndex

log = get_logger(__name__)
Source = Literal["memory", "curated", "run"]


def run_incident_id(run_id: str) -> str:
    """The memory id of the incident a published run becomes (``run-20261029-ab`` -> ``inc-...``)."""
    return f"inc-{run_id.removeprefix('run-')}"


@dataclass
class MemoryIncident:
    id: str
    title: str
    system: str
    failure_mode: str
    severity: Severity
    summary: str
    resolution: str
    signature: str = ""
    components: list[str] = field(default_factory=list)
    runbook_slug: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    occurrences: int = 1
    affected_nodes: int = 0
    mttr_minutes: float | None = None
    source: Source = "memory"
    synthetic: bool = False
    report_id: str | None = None

    def document(self) -> Document:
        mode = self.failure_mode.replace("_", " ")
        text = (
            f"{self.title}. {mode} on {self.system}. Components: {', '.join(self.components)}. "
            f"{self.signature} {self.summary}"
        )
        meta = {
            "system": self.system,
            "failure_mode": self.failure_mode,
            "severity": str(self.severity),
        }
        return Document(self.id, text, meta)

    @classmethod
    def from_row(cls, row: IncidentRow) -> MemoryIncident:
        return cls(
            id=row.id,
            title=row.title,
            system=row.system,
            failure_mode=row.failure_mode,
            severity=Severity(row.severity),
            summary=row.summary,
            resolution=row.resolution,
            signature=row.signature,
            components=list(row.components or []),
            runbook_slug=row.runbook_slug,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            occurrences=row.occurrences,
            affected_nodes=row.affected_nodes,
            mttr_minutes=row.mttr_minutes,
            source=row.source,  # type: ignore[arg-type]
            synthetic=row.synthetic,
            report_id=row.report_id,
        )

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title[:300],
            "system": self.system,
            "components": self.components,
            "failure_mode": self.failure_mode,
            "severity": str(self.severity),
            "summary": self.summary,
            "signature": self.signature,
            "resolution": self.resolution,
            "runbook_slug": self.runbook_slug,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "occurrences": self.occurrences,
            "affected_nodes": self.affected_nodes,
            "mttr_minutes": self.mttr_minutes,
            "source": self.source,
            "synthetic": self.synthetic,
            "report_id": self.report_id,
        }


@dataclass
class RepeatHistory:
    occurrences: int
    first_seen: datetime | None
    last_seen: datetime | None
    mttr_minutes: float | None


class IncidentMemory:
    def __init__(
        self, engine: Engine, embedder: Any = None, *, rrf_k: int = 60, query_timeout_s: float = 6.0
    ) -> None:
        self.engine = engine
        self.embedder = embedder
        self.rrf_k = rrf_k
        # A slow embedding API must not stall triage: past this, search is lexical-only.
        self.query_timeout_s = query_timeout_s
        self.incidents: dict[str, MemoryIncident] = {}
        self.index = HybridIndex([], rrf_k=rrf_k)
        self._lock = asyncio.Lock()
        self._groups: dict[tuple[str, str], list[MemoryIncident]] = {}

    @property
    def embedding_model(self) -> str | None:
        return getattr(self.embedder, "model", None) if self.embedder is not None else None

    async def refresh(self) -> None:
        """Reload memory from the database and rebuild the index, re-embedding stale rows."""
        async with self._lock:
            with session_scope(self.engine) as session:
                rows = list(session.scalars(select(IncidentRow).order_by(IncidentRow.id)))
                incidents = [MemoryIncident.from_row(r) for r in rows]
                stored = {r.id: (r.embedding, r.embedding_model) for r in rows}
            vectors = await self._vectors(incidents, stored)
            self.incidents = {i.id: i for i in incidents}
            self.index = HybridIndex(
                [i.document() for i in incidents],
                vectors,
                embedding_model=self.embedding_model,
                rrf_k=self.rrf_k,
            )
            groups: dict[tuple[str, str], list[MemoryIncident]] = defaultdict(list)
            for incident in incidents:
                groups[(incident.system, incident.failure_mode)].append(incident)
            self._groups = dict(groups)

    async def _vectors(
        self,
        incidents: Sequence[MemoryIncident],
        stored: dict[str, tuple[bytes | None, str | None]],
    ) -> np.ndarray | None:
        model = self.embedding_model
        if self.embedder is None or model is None or not incidents:
            return None
        vectors: list[np.ndarray | None] = []
        missing: list[int] = []
        for i, incident in enumerate(incidents):
            blob, blob_model = stored.get(incident.id, (None, None))
            if blob and blob_model == model:
                vectors.append(np.frombuffer(blob, dtype=np.float32))
            else:
                vectors.append(None)
                missing.append(i)
        if missing:
            try:
                fresh = await self.embedder.embed(
                    [incidents[i].document().text for i in missing], input_type="passage"
                )
            except Exception as exc:
                log.warning("memory.embed_failed", error=str(exc)[:200])
                return None
            with session_scope(self.engine) as session:
                for i, vector in zip(missing, fresh, strict=True):
                    array = np.asarray(vector, dtype=np.float32)
                    vectors[i] = array
                    row = session.get(IncidentRow, incidents[i].id)
                    if row is not None:
                        row.embedding = array.tobytes()
                        row.embedding_model = model
        dims = {len(v) for v in vectors if v is not None}
        if len(dims) != 1:
            return None
        matrix = np.vstack([v for v in vectors if v is not None]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    async def query_vector(self, text: str) -> np.ndarray | None:
        if self.embedder is None or self.index.vectors is None:
            return None
        try:
            (vector,) = await asyncio.wait_for(
                self.embedder.embed([text], input_type="query"), timeout=self.query_timeout_s
            )
        except TimeoutError:
            log.warning("memory.query_embed_timeout", timeout_s=self.query_timeout_s)
            return None
        except Exception as exc:  # any provider failure: fall back to lexical search
            log.warning("memory.query_embed_failed", error=str(exc)[:200])
            return None
        array = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(array))
        return array / norm if norm else None

    async def search(
        self, query: str, *, system: str | None = None, candidates: int = 12
    ) -> list[tuple[MemoryIncident, Hit]]:
        vector = await self.query_vector(query)
        hits = self.index.search(
            query,
            query_vector=vector,
            candidates=candidates,
            where=(lambda meta: meta["system"] == system) if system else None,
        )
        return [(self.incidents[h.id], h) for h in hits if h.id in self.incidents]

    def get(self, incident_id: str) -> MemoryIncident | None:
        return self.incidents.get(incident_id)

    def history(self, incident: MemoryIncident) -> RepeatHistory:
        group = self._groups.get((incident.system, incident.failure_mode), [incident])
        firsts = [i.first_seen for i in group if i.first_seen]
        lasts = [i.last_seen for i in group if i.last_seen]
        mttrs = [i.mttr_minutes for i in group if i.mttr_minutes is not None]
        return RepeatHistory(
            occurrences=sum(max(1, i.occurrences) for i in group),
            first_seen=min(firsts) if firsts else None,
            last_seen=max(lasts) if lasts else None,
            mttr_minutes=round(float(np.median(mttrs)), 1) if mttrs else None,
        )

    async def remember(self, incident: MemoryIncident) -> MemoryIncident:
        """Store a new incident (for example a published report) and refresh the index."""
        with session_scope(self.engine) as session:
            existing = session.get(IncidentRow, incident.id)
            values = incident.to_row()
            if existing is None:
                session.add(IncidentRow(**values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.embedding = None  # text changed; re-embed on refresh
        await self.refresh()
        return self.incidents[incident.id]

    async def bulk_insert(self, incidents: Sequence[MemoryIncident]) -> int:
        with session_scope(self.engine) as session:
            for incident in incidents:
                session.merge(IncidentRow(**incident.to_row()))
        await self.refresh()
        return len(incidents)


def recency_weight(
    last_seen: datetime | None, now: datetime, half_life_days: float = 180.0
) -> float:
    """Exponential decay used to prefer recent analogues when scores tie."""
    if last_seen is None:
        return 0.5
    age_days = max(0.0, (now - last_seen).total_seconds() / 86_400)
    return math.pow(0.5, age_days / half_life_days)
