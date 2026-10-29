"""Evidence registry: every citable fact gets an id (E1, E2, ...) when it is produced."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from aria.contracts.base import Evidence, EvidenceKind


class EvidenceStore:
    """Allocates evidence ids and keeps the evidence in insertion order.

    Graph nodes rebuild a store from the evidence list in state, add to it, and return the new
    items; ids continue from the highest one already used, so they stay unique across nodes.
    """

    def __init__(self, existing: Iterable[Evidence] = ()) -> None:
        self._items: dict[str, Evidence] = {}
        self._next = 1
        for item in existing:
            self._items[item.id] = item
            self._next = max(self._next, int(item.id[1:]) + 1)
        self._new: list[Evidence] = []

    def add(
        self,
        kind: EvidenceKind,
        title: str,
        *,
        source: str,
        detail: str = "",
        data: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> str:
        evidence = Evidence(
            id=f"E{self._next}",
            kind=kind,
            title=title[:200],
            detail=detail[:4_000],
            source=source,
            data=data or {},
            ts=ts,
        )
        self._next += 1
        self._items[evidence.id] = evidence
        self._new.append(evidence)
        return evidence.id

    def get(self, evidence_id: str) -> Evidence | None:
        return self._items.get(evidence_id)

    def __contains__(self, evidence_id: object) -> bool:
        return evidence_id in self._items

    def __len__(self) -> int:
        return len(self._items)

    def all(self) -> list[Evidence]:
        return list(self._items.values())

    def new_items(self) -> list[Evidence]:
        """Evidence added since this store was built (what a node returns as its update)."""
        return list(self._new)

    def by_kind(self, *kinds: EvidenceKind) -> list[Evidence]:
        return [item for item in self._items.values() if item.kind in kinds]
