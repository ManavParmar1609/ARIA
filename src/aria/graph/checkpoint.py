"""A LangGraph checkpointer on ARIA's own database (SQLite locally, Azure SQL in production).

Every super-step of a triage run is saved, so a run survives a restart, pauses for human review
(``interrupt``) for as long as it takes, and can be inspected, replayed or forked from any past
step (time travel).

Layout follows LangGraph's reference savers: a checkpoint row holds the checkpoint without its
channel values, and each channel value is stored once per version in ``lg_blobs``. A large input
(thousands of log lines) is therefore written once, not into every checkpoint.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    writes_sort_key,
)
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine

from aria.db.engine import session_scope
from aria.db.models import CheckpointBlobRow, CheckpointRow, CheckpointWriteRow


def _ids(config: RunnableConfig) -> tuple[str, str]:
    configurable = config["configurable"]
    return str(configurable["thread_id"]), str(configurable.get("checkpoint_ns", ""))


class SqlCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(self, engine: Engine, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.engine = engine

    # --- versions ------------------------------------------------------------------------------

    def get_next_version(self, current: str | int | None, channel: None) -> str:  # noqa: ARG002
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current  # versions written by integer-versioned savers
        else:
            current_v = int(current.split(".")[0])
        return f"{current_v + 1:032}.{random.random():016}"  # noqa: S311 - tie-breaker, not security

    # --- reads ---------------------------------------------------------------------------------

    def _load_blobs(
        self, session: Any, thread_id: str, ns: str, versions: dict[str, Any]
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for channel, version in versions.items():
            blob = session.get(CheckpointBlobRow, (thread_id, ns, channel, str(version)))
            if blob is None or blob.type == "empty":
                continue
            values[channel] = self.serde.loads_typed((blob.type, blob.blob or b""))
        return values

    def _tuple(
        self, session: Any, row: CheckpointRow, writes: list[CheckpointWriteRow]
    ) -> CheckpointTuple:
        config: RunnableConfig = {
            "configurable": {
                "thread_id": row.thread_id,
                "checkpoint_ns": row.checkpoint_ns,
                "checkpoint_id": row.checkpoint_id,
            }
        }
        parent: RunnableConfig | None = None
        if row.parent_checkpoint_id:
            parent = {
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.parent_checkpoint_id,
                }
            }
        ordered = sorted(writes, key=lambda w: writes_sort_key(w.task_path, w.task_id, w.idx))
        checkpoint: Checkpoint = self.serde.loads_typed((row.type or "msgpack", row.checkpoint))
        checkpoint = {
            **checkpoint,
            "channel_values": self._load_blobs(
                session,
                row.thread_id,
                row.checkpoint_ns,
                dict(checkpoint.get("channel_versions", {})),
            ),
        }
        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=self.serde.loads_typed(
                (row.metadata_type or "msgpack", row.checkpoint_metadata)
            ),
            parent_config=parent,
            pending_writes=[
                (w.task_id, w.channel, self.serde.loads_typed((w.type or "msgpack", w.value)))
                for w in ordered
            ],
        )

    def _writes_for(self, session: Any, row: CheckpointRow) -> list[CheckpointWriteRow]:
        return list(
            session.scalars(
                select(CheckpointWriteRow).where(
                    CheckpointWriteRow.thread_id == row.thread_id,
                    CheckpointWriteRow.checkpoint_ns == row.checkpoint_ns,
                    CheckpointWriteRow.checkpoint_id == row.checkpoint_id,
                )
            )
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, ns = _ids(config)
        checkpoint_id = get_checkpoint_id(config)
        with session_scope(self.engine) as session:
            stmt = select(CheckpointRow).where(
                CheckpointRow.thread_id == thread_id, CheckpointRow.checkpoint_ns == ns
            )
            if checkpoint_id:
                stmt = stmt.where(CheckpointRow.checkpoint_id == checkpoint_id)
            else:
                stmt = stmt.order_by(CheckpointRow.checkpoint_id.desc()).limit(1)
            row = session.scalars(stmt).first()
            if row is None:
                return None
            return self._tuple(session, row, self._writes_for(session, row))

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002 - LangGraph's parameter name
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        with session_scope(self.engine) as session:
            stmt = select(CheckpointRow)
            if config is not None:
                configurable = config["configurable"]
                stmt = stmt.where(CheckpointRow.thread_id == str(configurable["thread_id"]))
                if configurable.get("checkpoint_ns") is not None:
                    stmt = stmt.where(
                        CheckpointRow.checkpoint_ns == str(configurable["checkpoint_ns"])
                    )
                if checkpoint_id := get_checkpoint_id(config):
                    stmt = stmt.where(CheckpointRow.checkpoint_id == checkpoint_id)
            if before is not None and (before_id := get_checkpoint_id(before)):
                stmt = stmt.where(CheckpointRow.checkpoint_id < before_id)
            stmt = stmt.order_by(CheckpointRow.checkpoint_id.desc())
            results: list[CheckpointTuple] = []
            for row in session.scalars(stmt):
                found = self._tuple(session, row, self._writes_for(session, row))
                if filter and not all(found.metadata.get(k) == v for k, v in filter.items()):
                    continue
                results.append(found)
                if limit is not None and len(results) >= limit:
                    break
        yield from results

    # --- writes --------------------------------------------------------------------------------

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, ns = _ids(config)
        parent_id = config["configurable"].get("checkpoint_id")
        stripped: dict[str, Any] = dict(checkpoint)
        values: dict[str, Any] = dict(stripped.pop("channel_values", None) or {})
        type_, blob = self.serde.dumps_typed(stripped)
        meta_type, meta_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        with session_scope(self.engine) as session:
            for channel, version in new_versions.items():
                if channel in values:
                    value_type, value_blob = self.serde.dumps_typed(values[channel])
                else:
                    value_type, value_blob = "empty", b""
                session.merge(
                    CheckpointBlobRow(
                        thread_id=thread_id,
                        checkpoint_ns=ns,
                        channel=channel,
                        version=str(version),
                        type=value_type,
                        blob=value_blob,
                    )
                )
            session.merge(
                CheckpointRow(
                    thread_id=thread_id,
                    checkpoint_ns=ns,
                    checkpoint_id=checkpoint["id"],
                    parent_checkpoint_id=parent_id,
                    type=type_,
                    checkpoint=blob,
                    metadata_type=meta_type,
                    checkpoint_metadata=meta_blob,
                )
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, ns = _ids(config)
        checkpoint_id = str(config["configurable"]["checkpoint_id"])
        with session_scope(self.engine) as session:
            for idx, (channel, value) in enumerate(writes):
                write_idx = WRITES_IDX_MAP.get(channel, idx)
                key = (thread_id, ns, checkpoint_id, task_id, write_idx)
                if write_idx >= 0 and session.get(CheckpointWriteRow, key) is not None:
                    continue  # regular writes are idempotent; special ones (errors, interrupts) replace
                type_, blob = self.serde.dumps_typed(value)
                session.merge(
                    CheckpointWriteRow(
                        thread_id=thread_id,
                        checkpoint_ns=ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        idx=write_idx,
                        channel=channel,
                        type=type_,
                        value=blob,
                        task_path=task_path,
                    )
                )

    # --- thread management ---------------------------------------------------------------------

    def delete_thread(self, thread_id: str) -> None:
        with session_scope(self.engine) as session:
            session.execute(
                delete(CheckpointWriteRow).where(CheckpointWriteRow.thread_id == thread_id)
            )
            session.execute(
                delete(CheckpointBlobRow).where(CheckpointBlobRow.thread_id == thread_id)
            )
            session.execute(delete(CheckpointRow).where(CheckpointRow.thread_id == thread_id))

    def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        """Copy a run's full history to a new thread: the basis of forking a run."""
        with session_scope(self.engine) as session:
            if session.scalars(
                select(CheckpointRow).where(CheckpointRow.thread_id == target_thread_id)
            ).first():
                msg = f"thread {target_thread_id} already exists"
                raise ValueError(msg)
            for row in session.scalars(
                select(CheckpointRow).where(CheckpointRow.thread_id == source_thread_id)
            ):
                session.add(
                    CheckpointRow(
                        thread_id=target_thread_id,
                        checkpoint_ns=row.checkpoint_ns,
                        checkpoint_id=row.checkpoint_id,
                        parent_checkpoint_id=row.parent_checkpoint_id,
                        type=row.type,
                        checkpoint=row.checkpoint,
                        metadata_type=row.metadata_type,
                        checkpoint_metadata=row.checkpoint_metadata,
                    )
                )
            for blob in session.scalars(
                select(CheckpointBlobRow).where(CheckpointBlobRow.thread_id == source_thread_id)
            ):
                session.add(
                    CheckpointBlobRow(
                        thread_id=target_thread_id,
                        checkpoint_ns=blob.checkpoint_ns,
                        channel=blob.channel,
                        version=blob.version,
                        type=blob.type,
                        blob=blob.blob,
                    )
                )
            for write in session.scalars(
                select(CheckpointWriteRow).where(CheckpointWriteRow.thread_id == source_thread_id)
            ):
                session.add(
                    CheckpointWriteRow(
                        thread_id=target_thread_id,
                        checkpoint_ns=write.checkpoint_ns,
                        checkpoint_id=write.checkpoint_id,
                        task_id=write.task_id,
                        idx=write.idx,
                        channel=write.channel,
                        type=write.type,
                        value=write.value,
                        task_path=write.task_path,
                    )
                )

    def prune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        if strategy == "delete":
            for thread_id in thread_ids:
                self.delete_thread(thread_id)
            return
        if strategy != "keep_latest":
            msg = f"unknown prune strategy {strategy!r}"
            raise ValueError(msg)
        with session_scope(self.engine) as session:
            for thread_id in thread_ids:
                rows = list(
                    session.scalars(
                        select(CheckpointRow)
                        .where(CheckpointRow.thread_id == thread_id)
                        .order_by(CheckpointRow.checkpoint_ns, CheckpointRow.checkpoint_id.desc())
                    )
                )
                latest: dict[str, str] = {}
                for row in rows:
                    latest.setdefault(row.checkpoint_ns, row.checkpoint_id)
                keep: set[tuple[str, str, str]] = set()
                for row in rows:
                    if latest[row.checkpoint_ns] == row.checkpoint_id:
                        stripped = self.serde.loads_typed((row.type or "msgpack", row.checkpoint))
                        keep |= {
                            (row.checkpoint_ns, c, str(v))
                            for c, v in stripped.get("channel_versions", {}).items()
                        }
                        continue
                    session.execute(
                        delete(CheckpointWriteRow).where(
                            CheckpointWriteRow.thread_id == thread_id,
                            CheckpointWriteRow.checkpoint_ns == row.checkpoint_ns,
                            CheckpointWriteRow.checkpoint_id == row.checkpoint_id,
                        )
                    )
                    session.delete(row)
                for blob in session.scalars(
                    select(CheckpointBlobRow).where(CheckpointBlobRow.thread_id == thread_id)
                ):
                    if (blob.checkpoint_ns, blob.channel, blob.version) not in keep:
                        session.delete(blob)

    # --- async: run the sync implementation in a worker thread ---------------------------------

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        items = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, thread_id)

    async def acopy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        await asyncio.to_thread(self.copy_thread, source_thread_id, target_thread_id)

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        await asyncio.to_thread(lambda: self.prune(thread_ids, strategy=strategy))
