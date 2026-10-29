"""A LangGraph Store on ARIA's database: long-term memory shared across runs.

ARIA keeps reviewer feedback here (for example "reviewers raised this failure mode from SEV3
to SEV2 twice"), keyed by namespace such as ``("feedback", system, failure_mode)``. The severity
agent reads it in later runs and cites it as evidence. Search is lexical (no vector index), with
exact-match filters on top-level value fields.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)
from sqlalchemy import delete, or_, select
from sqlalchemy.engine import Engine

from aria.db.engine import session_scope
from aria.db.models import StoreItemRow

SEP = "\x1f"  # unit separator: cannot appear in normal namespace labels
_WORD = re.compile(r"[a-z0-9_]{2,}")
_LIKE_SPECIAL = re.compile(r"[\\%_]")


def _ns(namespace: tuple[str, ...]) -> str:
    return SEP.join(namespace)


def _unns(value: str) -> tuple[str, ...]:
    return tuple(value.split(SEP)) if value else ()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqlStore(BaseStore):
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _get(self, session: Any, op: GetOp) -> Item | None:
        row = session.get(StoreItemRow, (_ns(op.namespace), op.key))
        if row is None:
            return None
        return Item(
            value=dict(row.value),
            key=row.key,
            namespace=op.namespace,
            created_at=_aware(row.created_at),
            updated_at=_aware(row.updated_at),
        )

    def _put(self, session: Any, op: PutOp) -> None:
        ns = _ns(op.namespace)
        if op.value is None:
            session.execute(
                delete(StoreItemRow).where(StoreItemRow.namespace == ns, StoreItemRow.key == op.key)
            )
            return
        row = session.get(StoreItemRow, (ns, op.key))
        now = datetime.now(UTC)
        if row is None:
            session.add(
                StoreItemRow(
                    namespace=ns, key=op.key, value=dict(op.value), created_at=now, updated_at=now
                )
            )
        else:
            row.value = dict(op.value)
            row.updated_at = now

    def _search(self, session: Any, op: SearchOp) -> list[SearchItem]:
        prefix = _ns(op.namespace_prefix)
        stmt = select(StoreItemRow).order_by(StoreItemRow.updated_at.desc())
        if prefix:
            pattern = _LIKE_SPECIAL.sub(r"\\\g<0>", prefix + SEP) + "%"
            stmt = stmt.where(
                or_(
                    StoreItemRow.namespace == prefix,
                    StoreItemRow.namespace.like(pattern, escape="\\"),
                )
            )
        matched = []
        terms = set(_WORD.findall((op.query or "").lower()))
        for row in session.scalars(stmt):
            namespace = _unns(row.namespace)
            if op.filter and not all(row.value.get(k) == v for k, v in op.filter.items()):
                continue
            score = None
            if terms:
                text = set(_WORD.findall(json.dumps(row.value, default=str).lower()))
                score = len(terms & text) / len(terms)
                if score == 0:
                    continue
            matched.append(
                SearchItem(
                    namespace=namespace,
                    key=row.key,
                    value=dict(row.value),
                    created_at=_aware(row.created_at),
                    updated_at=_aware(row.updated_at),
                    score=score,
                )
            )
        if terms:
            matched.sort(key=lambda item: -(item.score or 0.0))
        return matched[op.offset : op.offset + op.limit]

    def _list_namespaces(self, session: Any, op: ListNamespacesOp) -> list[tuple[str, ...]]:
        namespaces = sorted({_unns(ns) for ns in session.scalars(select(StoreItemRow.namespace))})
        for condition in op.match_conditions or ():
            path = tuple(condition.path)
            if condition.match_type == "prefix":
                namespaces = [
                    n
                    for n in namespaces
                    if all(p in ("*", n[i] if i < len(n) else None) for i, p in enumerate(path))
                ]
            else:
                namespaces = [
                    n
                    for n in namespaces
                    if len(n) >= len(path)
                    and all(p in ("*", n[len(n) - len(path) + i]) for i, p in enumerate(path))
                ]
        if op.max_depth is not None:
            namespaces = sorted({n[: op.max_depth] for n in namespaces})
        return namespaces[op.offset : op.offset + op.limit]

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        results: list[Result] = []
        with session_scope(self.engine) as session:
            for op in ops:
                if isinstance(op, GetOp):
                    results.append(self._get(session, op))
                elif isinstance(op, PutOp):
                    self._put(session, op)
                    results.append(None)
                elif isinstance(op, SearchOp):
                    results.append(self._search(session, op))
                else:  # ListNamespacesOp, the last member of the Op union
                    results.append(self._list_namespaces(session, op))
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        materialised = list(ops)
        return await asyncio.to_thread(self.batch, materialised)
