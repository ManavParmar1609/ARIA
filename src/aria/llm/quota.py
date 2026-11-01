"""Keep each provider inside its rate limits, so no model refuses ARIA for a limit.

Hosted models limit each project per model: requests a minute, tokens a minute and requests a
day. Google's Gemini API starts the daily count again at midnight Pacific time. The providers on
one Gemini key are separate models with limits of their own, so the router spreads calls across
them, and this ledger keeps each one inside its own:

* **A one-minute window** of what was sent, for requests and for tokens: a token bucket whose
  tokens come back one minute (and a second, for the trip to the provider) after they were
  spent. No minute ever holds more than the limit, where a bucket that refills at a steady rate
  can let nearly twice the limit through around the turn of a minute.
* **A count of requests per day**, starting again at midnight in ``timezone``. Days are computed
  with zoneinfo, so the day a clock changes is 23 or 25 hours long, as Google's is.
* **Holds.** After a provider refuses for a limit it rests: for the time it asked (a per-minute
  limit or a busy provider), or until the next daily reset (a daily quota, a spending cap, no
  credit left), or until the moment its message names, if that is sooner.
* **Reservations.** A model-written triage sets aside the day's requests it will need before it
  starts, so other runs and questions cannot use them up halfway through it.

Each limit is cut by a safety margin. Every request counts, answered or not, since providers
count failed requests too. Counts and holds are saved to a small JSON file, replaced atomically,
so a restart remembers today's; reservations are not saved, since the runs that held them are
gone. Each process counts only its own requests: run one process per key, or give each process
its own share of the limits.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import threading
import time
import uuid
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from aria.config import LLMConfig, ProviderLimits
from aria.llm.base import Message, RateLimit
from aria.observability.logging import get_logger

log = get_logger(__name__)

WINDOW_S = 60.0
# A request sent at the end of our minute may reach the provider at the start of its next one:
# each request counts for one second longer than a minute.
GUARD_S = 1.0
FORMAT = 1
DEFAULT_MINUTE_HOLD_S = 60.0  # a per-minute refusal that says no wait
DEFAULT_OVERLOAD_HOLD_S = 15.0  # a busy provider (503, 529) that says no wait
# Admission errs high: models average about four characters a token, so three over-counts.
CHARS_PER_TOKEN = 3
TOKENS_PER_MESSAGE = 4
# Holds that last until a reset. A run's reservation passes over a provider resting for one of
# these; a short rest (a per-minute limit) lifts long before the run reaches its later calls.
LONG_HOLDS = frozenset({"day", "spend_cap", "no_credit"})

RefusalKind = Literal["hold", "day", "minute", "tokens", "too_large"]


def local_day(now: float, tz: ZoneInfo) -> str:
    """The date in ``tz`` at epoch second ``now``."""
    return datetime.fromtimestamp(now, tz).date().isoformat()


def next_reset(now: float, tz: ZoneInfo) -> float:
    """The next midnight in ``tz`` after epoch second ``now``, as epoch seconds."""
    today = datetime.fromtimestamp(now, tz).date()
    return datetime.combine(today + timedelta(days=1), clock_time(0), tzinfo=tz).timestamp()


_ZONE_NAMES = {"America/Los_Angeles": "Pacific"}


def back_in_words(back_at: float, *, now: float, tz: ZoneInfo) -> str:
    """When the shared models have room again, as a person would say it: "after midnight
    Pacific time (08:00 UTC)", "in about 12 minutes" or "at 17:00 UTC"."""
    utc = time.strftime("%H:%M UTC", time.gmtime(back_at))
    local = datetime.fromtimestamp(back_at, tz)
    if (local.hour, local.minute) == (0, 0):
        zone = _ZONE_NAMES.get(tz.key, tz.key)
        return f"after midnight {zone} time ({utc})"
    minutes = math.ceil(max(0.0, back_at - now) / 60)
    if minutes <= 90:
        return f"in about {minutes} minute{'s' if minutes != 1 else ''}"
    return f"at {utc}"


def offline_message(back_at: float, *, now: float, tz: ZoneInfo) -> str:
    """Why a triage that asked for a model ran offline, and when to try again."""
    return (
        "The site's shared models are at their limits for now, so ARIA ran this triage offline: "
        "the rules, the calibrated model and the grounded template wrote it. They have room "
        f"again {back_in_words(back_at, now=now, tz=tz)}."
    )


def effective(limit: int | None, margin: float) -> int | None:
    """A limit less the safety margin: never below one request for a limit that allows any."""
    if limit is None or limit == 0:
        return limit
    return max(1, math.floor(limit * (1 - margin)))


def request_tokens(
    messages: Sequence[Message], max_tokens: int, json_schema: Mapping[str, Any] | None = None
) -> int:
    """What one request may count against a tokens-a-minute limit, erring high: its prompt at
    three characters a token, a little for each message, the schema when it travels with the
    request, and every token the reply may use."""
    chars = sum(len(m.content) for m in messages)
    if json_schema is not None:
        chars += len(json.dumps(json_schema))
    return math.ceil(chars / CHARS_PER_TOKEN) + TOKENS_PER_MESSAGE * len(messages) + max_tokens


@dataclass(frozen=True)
class Limits:
    """A provider's limits after the safety margin; None means no limit."""

    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None


@dataclass
class _Sent:
    at: float
    tokens: int


@dataclass
class _State:
    limits: Limits | None
    sent: deque[_Sent] = field(default_factory=deque)
    day_requests: int = 0
    reserved: int = 0  # requests set aside today for runs in progress
    hold_until: float | None = None
    hold_kind: str | None = None
    hold_reason: str | None = None


@dataclass(frozen=True)
class Refusal:
    """No room for a request now: why, in plain words, and when there will be (None: never for
    this request)."""

    provider: str
    kind: RefusalKind
    reason: str
    retry_at: float | None


@dataclass
class Ticket:
    """A request the ledger let through and counted."""

    provider: str
    tokens: int
    sent: _Sent | None = None
    reserved: bool = False  # it used a run's reservation


@dataclass
class Reservation:
    """The day's requests set aside for one run, by provider. Each call the run makes on one of
    them uses one up; ``release`` returns what is left."""

    id: str
    held: dict[str, int]
    expires_at: float

    @property
    def calls(self) -> int:
        return sum(self.held.values())


@dataclass(frozen=True)
class Unreserved:
    """No room for a run's calls: the role that found none, and when there may be room."""

    role: str
    back_at: float


@dataclass(frozen=True)
class Capacity:
    """One provider's room now, for the capacity view: no secrets, only counts and times."""

    provider: str
    limits: Limits | None
    minute_requests_left: int | None
    minute_tokens_left: int | None
    day_requests_left: int | None
    day_requests_used: int
    day_requests_reserved: int
    minute_resets_at: float | None
    held_until: float | None
    hold_kind: str | None
    held_because: str | None


class QuotaLedger:
    """Per-provider rate-limit counts, holds and run reservations. Thread- and task-safe: every
    change happens under one lock, with no await inside it."""

    def __init__(
        self,
        limits: Mapping[str, ProviderLimits],
        *,
        margin: float = 0.1,
        timezone: str = "America/Los_Angeles",
        path: Path | str | None = None,
        clock: Callable[[], float] = time.time,
        reservation_ttl_s: float = 900.0,
    ) -> None:
        self.margin = margin
        self.tz = ZoneInfo(timezone)
        self.path = Path(path) if path is not None else None
        self.reservation_ttl_s = reservation_ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._io = threading.Lock()
        self._limits = {
            name: Limits(
                effective(cfg.rpm, margin), effective(cfg.tpm, margin), effective(cfg.rpd, margin)
            )
            for name, cfg in limits.items()
        }
        self._state = {name: _State(lim) for name, lim in self._limits.items()}
        self._reservations: dict[str, Reservation] = {}
        self._day = local_day(clock(), self.tz)
        self._version = 0  # bumped by every change worth saving
        self._saved = 0  # the version last written
        if self.path is not None:
            self._load()

    @classmethod
    def from_config(
        cls,
        config: LLMConfig,
        *,
        path: Path | str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> QuotaLedger:
        limits = {
            name: cfg.limits for name, cfg in config.providers.items() if cfg.limits is not None
        }
        quota = config.quota
        return cls(
            limits,
            margin=quota.margin,
            timezone=quota.timezone,
            path=path,
            clock=clock,
            reservation_ttl_s=quota.reservation_ttl_s,
        )

    # --- reading -------------------------------------------------------------------------------

    def now(self) -> float:
        return self._clock()

    def limited(self, name: str) -> bool:
        return name in self._limits

    def limits(self, name: str) -> Limits | None:
        return self._limits.get(name)

    def next_reset(self, now: float | None = None) -> float:
        return next_reset(self._clock() if now is None else now, self.tz)

    def held(self, name: str) -> tuple[float, str, str] | None:
        """When a resting provider may be asked again, the kind of limit and why, or None."""
        with self._lock:
            self._roll(self._clock())
            state = self._state.get(name)
            if state is None or state.hold_until is None:
                return None
            return state.hold_until, state.hold_kind or "", state.hold_reason or ""

    # --- admission -----------------------------------------------------------------------------

    def acquire(
        self, name: str, tokens: int, *, reservation: Reservation | None = None
    ) -> Ticket | Refusal:
        """Count one request to ``name`` of up to ``tokens`` tokens if it has room, else say why
        not and when it will. A run's ``reservation`` lets it use the day's requests set aside
        for it; minute limits apply to everyone alike."""
        with self._lock:
            now = self._clock()
            self._roll(now)
            state = self._state.get(name)
            if state is None:
                return Ticket(name, tokens)
            if state.hold_until is not None:
                return Refusal(
                    name,
                    "hold",
                    state.hold_reason or "it is resting after a refusal",
                    state.hold_until,
                )
            lim = state.limits
            if lim is None:
                return Ticket(name, tokens)
            mine = (
                reservation is not None
                and reservation.id in self._reservations
                and reservation.held.get(name, 0) > 0
            )
            if lim.rpd is not None:
                room = lim.rpd - state.day_requests - state.reserved + (1 if mine else 0)
                if room < 1:
                    return Refusal(
                        name,
                        "day",
                        "today's requests are used or set aside for runs in progress",
                        self.next_reset(now) if lim.rpd else None,
                    )
            if lim.rpm is not None and len(state.sent) >= lim.rpm:
                retry = (
                    state.sent[len(state.sent) - lim.rpm].at + WINDOW_S + GUARD_S
                    if lim.rpm
                    else None
                )
                return Refusal(name, "minute", "this minute's requests are used", retry)
            if lim.tpm is not None:
                if tokens > lim.tpm:
                    return Refusal(
                        name, "too_large", "the request is larger than a minute's tokens", None
                    )
                used = sum(sent.tokens for sent in state.sent)
                if used + tokens > lim.tpm:
                    return Refusal(
                        name,
                        "tokens",
                        "this minute's tokens are used",
                        self._tokens_free_at(state, used + tokens - lim.tpm),
                    )
            entry = _Sent(now, tokens)
            state.sent.append(entry)
            state.day_requests += 1
            if mine and reservation is not None:
                state.reserved -= 1
                reservation.held[name] -= 1
            self._version += 1
            return Ticket(name, tokens, entry, mine)

    @staticmethod
    def _tokens_free_at(state: _State, excess: int) -> float:
        """When enough of this minute's tokens have aged out of the window to free ``excess``."""
        freed, at = 0, 0.0
        for sent in state.sent:
            freed, at = freed + sent.tokens, sent.at
            if freed >= excess:
                break
        return at + WINDOW_S + GUARD_S

    def settle(self, ticket: Ticket, *, tokens: int | None) -> None:
        """Replace a request's estimated tokens with what the provider reported it used. Without
        a report (a failure, or a provider that counts nothing) the estimate stands."""
        if ticket.sent is None or tokens is None:
            return
        with self._lock:
            ticket.sent.tokens = max(0, int(tokens))

    def hold(self, name: str, limit: RateLimit) -> float:
        """Rest ``name`` after it refused for ``limit``; returns when it may be asked again."""
        with self._lock:
            now = self._clock()
            self._roll(now)
            named = limit.until if limit.until is not None and limit.until > now else None
            if limit.kind == "minute":
                until = named or now + (limit.retry_after or DEFAULT_MINUTE_HOLD_S)
            elif limit.kind == "overload":
                until = named or now + (limit.retry_after or DEFAULT_OVERLOAD_HOLD_S)
            else:
                # A daily quota, a spending cap or no credit: back at the next reset, or sooner
                # when the provider names the moment. A cap the owner raises meanwhile is tried
                # again at the reset, so a provider is never set aside for longer than a day.
                until = min(named or math.inf, self.next_reset(now))
            state = self._state.setdefault(name, _State(self._limits.get(name)))
            if state.hold_until is None or until > state.hold_until:
                state.hold_until, state.hold_kind, state.hold_reason = (
                    until,
                    limit.kind,
                    limit.detail,
                )
                self._version += 1
            return state.hold_until

    # --- reservations --------------------------------------------------------------------------

    def reserve(
        self, needs: Mapping[str, int], chains: Mapping[str, Sequence[str]]
    ) -> Reservation | Unreserved:
        """Set aside the day's requests for one run: ``needs`` counts its calls by role, and
        ``chains`` lists the providers that may take each role, in order. Each call goes to the
        first provider with a day's request to spare; one without a daily limit needs nothing
        set aside. All or nothing: when a call finds no room, nothing is set aside."""
        with self._lock:
            now = self._clock()
            self._roll(now)
            placed = self._plan(needs, chains, now)
            if isinstance(placed, Unreserved):
                return placed
            reservation = Reservation(uuid.uuid4().hex, dict(placed), now + self.reservation_ttl_s)
            for name, count in placed.items():
                self._state[name].reserved += count
            self._reservations[reservation.id] = reservation
            return reservation

    def check_run(
        self, needs: Mapping[str, int], chains: Mapping[str, Sequence[str]]
    ) -> float | None:
        """None when one more run of ``needs`` fits now, else when there may be room for it."""
        with self._lock:
            now = self._clock()
            self._roll(now)
            placed = self._plan(needs, chains, now)
            return placed.back_at if isinstance(placed, Unreserved) else None

    def runs_left(
        self, needs: Mapping[str, int], chains: Mapping[str, Sequence[str]], *, cap: int = 999
    ) -> int | None:
        """How many more runs of ``needs`` today's requests have room for (at most ``cap``), or
        None when no daily limit bounds them."""
        with self._lock:
            now = self._clock()
            self._roll(now)
            taken: Counter[str] = Counter()
            for runs in range(cap):
                placed = self._plan(needs, chains, now, taken)
                if isinstance(placed, Unreserved):
                    return runs
                if not placed and runs == 0:
                    return None
                taken.update(placed)
            return cap

    def _plan(
        self,
        needs: Mapping[str, int],
        chains: Mapping[str, Sequence[str]],
        now: float,
        already: Counter[str] | None = None,
    ) -> Counter[str] | Unreserved:
        taken: Counter[str] = Counter(already or {})
        for role, count in needs.items():
            chain = chains.get(role, ())
            for _ in range(count):
                spot = self._place(chain, taken, now)
                if spot is None:
                    return Unreserved(role, self._back_at(chain, taken, now))
                if spot:
                    taken[spot] += 1
        return taken - Counter(already or {})

    def _long_hold(self, state: _State, now: float) -> bool:
        return (
            state.hold_until is not None
            and state.hold_until > now
            and state.hold_kind in LONG_HOLDS
        )

    def _place(self, chain: Sequence[str], taken: Counter[str], now: float) -> str | None:
        """Where one call can go: a provider with a day's request to spare (its name), one with
        no daily limit or a role no provider takes ("": nothing to set aside), or nowhere."""
        if not chain:
            return ""
        for name in chain:
            state = self._state.get(name)
            if state is None:
                return ""
            if self._long_hold(state, now):
                continue
            lim = state.limits
            if lim is None or lim.rpd is None:
                return ""
            if state.day_requests + state.reserved + taken[name] < lim.rpd:
                return name
        return None

    def _back_at(self, chain: Sequence[str], taken: Counter[str], now: float) -> float:
        """When some provider in ``chain`` may have room again: as a hold ends or a run in
        progress gives back what it set aside, and at the latest at the next reset."""
        best = self.next_reset(now)
        for name in chain:
            state = self._state.get(name)
            if state is None:
                continue
            rpd = state.limits.rpd if state.limits is not None else None
            if rpd is not None and state.day_requests >= rpd:
                continue  # used up today (or allowed none): back at the reset at the earliest
            waits: list[float] = []
            if self._long_hold(state, now) and state.hold_until is not None:
                waits.append(state.hold_until)
            if rpd is not None and state.day_requests + state.reserved + taken[name] >= rpd:
                ends = [r.expires_at for r in self._reservations.values() if r.held.get(name)]
                if not ends:
                    continue  # this run's own calls fill it: back at the reset
                waits.append(min(ends))
            if waits:
                best = min(best, max(waits))
        return best

    def release(self, reservation: Reservation) -> int:
        """Give back what a run set aside and did not use; returns how many requests."""
        with self._lock:
            return self._drop(reservation)

    def _drop(self, reservation: Reservation) -> int:
        if self._reservations.pop(reservation.id, None) is None:
            return 0
        freed = 0
        for name, count in reservation.held.items():
            state = self._state.get(name)
            if state is not None and count > 0:
                state.reserved = max(0, state.reserved - count)
                freed += count
            reservation.held[name] = 0
        return freed

    # --- the day and the minute ----------------------------------------------------------------

    def _roll(self, now: float) -> None:
        """Start a new day at the reset, age requests out of the window, end holds that are over
        and drop reservations whose runs never came back for them."""
        day = local_day(now, self.tz)
        if day != self._day:
            self._day = day
            for state in self._state.values():
                state.day_requests = 0
            self._version += 1
        for state in self._state.values():
            while state.sent and now - state.sent[0].at >= WINDOW_S + GUARD_S:
                state.sent.popleft()
            if state.hold_until is not None and state.hold_until <= now:
                state.hold_until = state.hold_kind = state.hold_reason = None
                self._version += 1
        for reservation in [r for r in self._reservations.values() if r.expires_at <= now]:
            self._drop(reservation)

    # --- the capacity view ---------------------------------------------------------------------

    def capacity(self) -> list[Capacity]:
        """Every tracked provider's room now: the minute, the day and any hold."""
        with self._lock:
            now = self._clock()
            self._roll(now)
            out = []
            for name, state in sorted(self._state.items()):
                lim = state.limits or Limits()
                tokens = sum(sent.tokens for sent in state.sent)
                out.append(
                    Capacity(
                        provider=name,
                        limits=state.limits,
                        minute_requests_left=None
                        if lim.rpm is None
                        else max(0, lim.rpm - len(state.sent)),
                        minute_tokens_left=None if lim.tpm is None else max(0, lim.tpm - tokens),
                        day_requests_left=None
                        if lim.rpd is None
                        else max(0, lim.rpd - state.day_requests - state.reserved),
                        day_requests_used=state.day_requests,
                        day_requests_reserved=state.reserved,
                        minute_resets_at=state.sent[0].at + WINDOW_S + GUARD_S
                        if state.sent
                        else None,
                        held_until=state.hold_until,
                        hold_kind=state.hold_kind,
                        held_because=state.hold_reason,
                    )
                )
            return out

    # --- persistence ---------------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        providers: dict[str, Any] = {}
        for name, state in self._state.items():
            item: dict[str, Any] = {}
            if state.day_requests:
                item["day_requests"] = state.day_requests
            if state.sent:
                item["sent"] = [[round(s.at, 3), s.tokens] for s in state.sent]
            if state.hold_until is not None:
                item["hold"] = {
                    "until": state.hold_until,
                    "kind": state.hold_kind,
                    "reason": state.hold_reason,
                }
            if item:
                providers[name] = item
        return {"format": FORMAT, "timezone": self.tz.key, "day": self._day, "providers": providers}

    def save(self) -> bool:
        """Write the counts to ``path`` if they changed since the last write. The file is
        replaced atomically: a crash leaves the old one or the new one, never half of either."""
        if self.path is None:
            return False
        with self._lock:
            version = self._version
            if version == self._saved:
                return False
            data = self._snapshot()
        with self._io:
            if version <= self._saved:
                return False
            if self._write(self.path, data):
                self._saved = version
                return True
            return False

    async def persist(self) -> None:
        """``save`` off the event loop, when there is something new to save."""
        if self.path is not None and self._version != self._saved:
            await asyncio.to_thread(self.save)

    @staticmethod
    def _write(path: Path, data: dict[str, Any]) -> bool:
        temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(path)
        except OSError as exc:
            log.warning("quota.save_failed", path=str(path), error=str(exc)[:200])
            with contextlib.suppress(OSError):
                temp.unlink()
            return False
        return True

    def _load(self) -> None:
        """Take up today's counts and live holds from the file a previous process wrote."""
        assert self.path is not None  # noqa: S101 - the caller checks
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("quota.unreadable", path=str(self.path), error=str(exc)[:200])
            return
        if not isinstance(raw, dict) or raw.get("format") != FORMAT:
            return
        now = self._clock()
        today = raw.get("day") == self._day and raw.get("timezone") == self.tz.key
        for name, item in (raw.get("providers") or {}).items():
            if not isinstance(item, dict):
                continue
            try:
                self._restore(str(name), item, now=now, today=today)
            except (TypeError, ValueError, KeyError) as exc:
                log.warning("quota.entry_skipped", provider=str(name), error=str(exc)[:200])
        self._saved = self._version

    def _restore(self, name: str, item: dict[str, Any], *, now: float, today: bool) -> None:
        hold = item.get("hold")
        until = float(hold["until"]) if isinstance(hold, dict) else 0.0
        if name not in self._limits and until <= now:
            return  # no longer tracked, and nothing to remember about it
        state = self._state.setdefault(name, _State(self._limits.get(name)))
        if today:
            state.day_requests = int(item.get("day_requests") or 0)
        for at, tokens in item.get("sent") or []:
            if now - float(at) < WINDOW_S + GUARD_S:
                state.sent.append(_Sent(float(at), int(tokens)))
        if isinstance(hold, dict) and until > now:
            state.hold_until = until
            state.hold_kind = str(hold.get("kind") or "")
            state.hold_reason = str(hold.get("reason") or "")
