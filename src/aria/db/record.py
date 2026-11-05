"""The decision record: append and read, nothing else.

Every decision ARIA or a person takes (a review, an edit, a publish, a message sent, a blind
check, a recalibration, a model swap, a purge, a deletion) is one entry in ``decision_record``.
An entry's hash is SHA-256 over a canonical JSON of its own fields and the previous entry's
hash, so changing, removing or reordering any entry breaks every hash after it, and ``verify``
names the first break. Database triggers refuse UPDATE and DELETE on the table, and this module
has no function that does either.

Writers never fork the chain: the sequence number is the primary key, so two writers that read
the same tail cannot both insert the next entry. The loser reads the new tail and tries again,
as ``repository.append_event`` does. A decision that cannot be recorded raises ``RecordError``
after an error-level log line; no caller may swallow it quietly.

The chain shows tampering; it does not prevent it. Whoever administers the database can drop
the triggers and rewrite every entry and hash from the one they change onward. Anchoring the
newest hash (``ChainCheck.head_hash``) somewhere they cannot reach catches that too.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from aria.contracts.base import JsonDict, utcnow
from aria.contracts.record import GENESIS, ChainCheck, DecisionRecord, RecordKind
from aria.db.engine import session_scope
from aria.db.models import DecisionRecordRow
from aria.observability.logging import get_logger
from aria.security.redaction import Redactor

log = get_logger(__name__)

# Tries at the tail before giving up: enough for a burst of writers on one database. The pauses
# between them add up to well under a second.
ATTEMPTS = 25
# Free text in a payload (a reviewer's comment or note) is kept to this many characters.
TEXT_CHARS = 500


class RecordError(RuntimeError):
    """A decision was not recorded. The caller fails loudly rather than carrying on."""


# --- hashing ---------------------------------------------------------------------------------------


def canonical(fields: Mapping[str, Any]) -> bytes:
    """One byte string for one set of fields, whatever order they came in."""
    return json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def stamp(ts: datetime) -> str:
    """The moment as the hash sees it: naive UTC, written to the microsecond.

    Entries are written to the whole second (``moment``), because the hash must be recomputable
    from what the database hands back: SQLite keeps microseconds, but SQL Server's DATETIME
    keeps 1/300 of a second and would round a finer moment, breaking every entry's hash.
    """
    utc = ts.astimezone(UTC) if ts.tzinfo is not None else ts
    return utc.replace(tzinfo=None).isoformat(timespec="microseconds")


def moment() -> datetime:
    """Now, to the whole second: a moment every database stores exactly as hashed."""
    return utcnow().replace(microsecond=0)


def entry_hash(
    *,
    seq: int,
    ts: datetime,
    kind: str,
    run_id: str | None,
    actor: str,
    payload: Mapping[str, Any],
    prev_hash: str,
) -> str:
    return hashlib.sha256(
        canonical(
            {
                "seq": seq,
                "ts": stamp(ts),
                "kind": kind,
                "run_id": run_id,
                "actor": actor,
                "payload": payload,
                "prev_hash": prev_hash,
            }
        )
    ).hexdigest()


def make_entry(
    *,
    seq: int,
    ts: datetime,
    kind: RecordKind,
    run_id: str | None,
    actor: str,
    payload: JsonDict,
    prev_hash: str,
) -> DecisionRecord:
    """An entry with its hash, from fields already made JSON-safe and redacted."""
    digest = entry_hash(
        seq=seq, ts=ts, kind=kind, run_id=run_id, actor=actor, payload=payload, prev_hash=prev_hash
    )
    return DecisionRecord(
        seq=seq,
        ts=ts,
        kind=kind,
        run_id=run_id,
        actor=actor,
        payload=payload,
        prev_hash=prev_hash,
        hash=digest,
    )


# --- payloads ------------------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, set | frozenset):
        return sorted(str(v) for v in value)
    return str(value)


def jsonable(payload: Mapping[str, Any]) -> JsonDict:
    """The payload as it comes back from a JSON column, so the hash is the same both ways."""
    plain: JsonDict = json.loads(json.dumps(dict(payload), default=_plain, allow_nan=False))
    return plain


def redacted(value: Any, redactor: Redactor) -> Any:
    """Every string in ``value``, with secrets removed and addresses pseudonymised."""
    if isinstance(value, str):
        return redactor.redact(value)
    if isinstance(value, dict):
        return {str(k): redacted(v, redactor) for k, v in value.items()}
    if isinstance(value, list):
        return [redacted(v, redactor) for v in value]
    return value


def clipped(text: str | None) -> str | None:
    """Free text a person wrote, kept to a size a record can hold."""
    if text is None:
        return None
    return text if len(text) <= TEXT_CHARS else text[: TEXT_CHARS - 1] + "…"


# --- append and read ---------------------------------------------------------------------------


def append(
    engine: Engine,
    *,
    kind: RecordKind,
    actor: str,
    run_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    redactor: Redactor | None = None,
) -> DecisionRecord:
    """Record one decision at the tail of the chain.

    ``actor`` is a reviewer's display name, ``cli`` or ``system``: never a key. The payload holds
    the decision's facts, never a log line; every string in it is redacted first, with the run's
    pseudonyms when the caller passes the run's ``Redactor``. Raises ``RecordError`` when the
    entry could not be written, after logging ``record.failed``.
    """
    clean = redactor or Redactor()
    facts = redacted(jsonable(payload or {}), clean)
    who = clean.redact(actor)[:120]
    problem: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            with session_scope(engine) as session:
                seq, prev_hash = _tail(session)
                entry = make_entry(
                    seq=seq,
                    ts=moment(),
                    kind=kind,
                    run_id=run_id,
                    actor=who,
                    payload=facts,
                    prev_hash=prev_hash,
                )
                session.add(DecisionRecordRow(**entry.model_dump()))
        except (IntegrityError, OperationalError) as exc:
            # Another writer took this seq, or the database was busy: read the tail again, after
            # a pause that grows with each try, so a burst of writers spreads out.
            problem = exc
            time.sleep(0.001 * attempt)
            continue
        except Exception as exc:
            log.exception("record.failed", kind=kind, run_id=run_id, actor=who)
            msg = f"could not record the {kind} decision: {exc}"
            raise RecordError(msg) from exc
        log.info("record.appended", seq=entry.seq, kind=kind, run_id=run_id, actor=who)
        return entry
    log.error("record.failed", kind=kind, run_id=run_id, actor=who, error=str(problem))
    msg = f"could not record the {kind} decision after {ATTEMPTS} attempts: {problem}"
    raise RecordError(msg) from problem


def _tail(session: Session) -> tuple[int, str]:
    """The next sequence number and the hash it chains to: the newest entry's, or the genesis
    hash when the record is empty."""
    tail = session.execute(
        select(DecisionRecordRow.seq, DecisionRecordRow.hash)
        .order_by(DecisionRecordRow.seq.desc())
        .limit(1)
    ).first()
    return (0, GENESIS) if tail is None else (int(tail[0]) + 1, str(tail[1]))


def _as_entry(row: DecisionRecordRow) -> DecisionRecord:
    return DecisionRecord(
        seq=row.seq,
        ts=row.ts,
        kind=row.kind,  # type: ignore[arg-type]
        run_id=row.run_id,
        actor=row.actor,
        payload=dict(row.payload),
        prev_hash=row.prev_hash,
        hash=row.hash,
    )


def list_entries(
    engine: Engine, *, run_id: str | None = None, after: int = -1, limit: int = 200
) -> list[DecisionRecord]:
    """Entries in chain order: one run's, or every run's and the ones with no run."""
    with session_scope(engine) as session:
        stmt = select(DecisionRecordRow).where(DecisionRecordRow.seq > after)
        if run_id is not None:
            stmt = stmt.where(DecisionRecordRow.run_id == run_id)
        rows = session.scalars(stmt.order_by(DecisionRecordRow.seq).limit(limit))
        return [_as_entry(row) for row in rows]


def check(entries: Iterable[DecisionRecord]) -> ChainCheck:
    """Walk entries in chain order and report the first one that does not hold.

    An entry holds when its sequence number follows the one before it, its previous hash is that
    entry's hash (the genesis hash for the first), and its own hash matches its fields.
    """
    expected, prev, count = 0, GENESIS, 0
    for entry in entries:
        count += 1
        if entry.seq != expected:
            return _broken(expected, f"entry {expected} is missing", count)
        if entry.prev_hash != prev:
            return _broken(
                entry.seq, f"entry {entry.seq} does not chain to the entry before it", count
            )
        if entry.hash != entry_hash(**entry.model_dump(exclude={"hash"})):
            return _broken(entry.seq, f"entry {entry.seq} does not match its own hash", count)
        expected, prev = entry.seq + 1, entry.hash
    return ChainCheck(ok=True, length=count, head_hash=prev if count else None, checked_at=utcnow())


def _broken(seq: int, problem: str, count: int) -> ChainCheck:
    return ChainCheck(
        ok=False, length=count, first_broken=seq, problem=problem, checked_at=utcnow()
    )


def verify(engine: Engine, *, batch: int = 1_000) -> ChainCheck:
    """Walk the whole record, a batch of rows at a time, and say whether it holds."""
    with session_scope(engine) as session:
        rows = session.scalars(
            select(DecisionRecordRow)
            .order_by(DecisionRecordRow.seq)
            .execution_options(yield_per=batch)
        )
        return check(_as_entry(row) for row in rows)
