"""The quota ledger: pacing, the Pacific day, persistence, reservations, and the owner's
requirement that a burst of runs never sends a model more than its configured limits."""

from __future__ import annotations

import asyncio
import json
import random
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from aria.config import Environment, ProviderKind, ProviderLimits, get_app_config
from aria.graph.workflow import expected_llm_calls
from aria.llm.base import Message, NoProviderAvailableError, RateLimit, Usage
from aria.llm.fake import FakeProvider
from aria.llm.quota import (
    QuotaLedger,
    Refusal,
    Reservation,
    Ticket,
    Unreserved,
    back_in_words,
    effective,
    local_day,
    next_reset,
    offline_message,
    request_tokens,
)
from aria.llm.router import LLMRouter

PACIFIC = ZoneInfo("America/Los_Angeles")
NOON = datetime(2026, 10, 30, 12, 0, tzinfo=PACIFIC).timestamp()
CHAINS = {"investigator": ["gemini", "gemini-lite"], "critic": ["gemini-lite", "gemini"]}


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)
        await asyncio.sleep(0)


def book(clock: Clock, path: Path | None = None, **limits: ProviderLimits) -> QuotaLedger:
    return QuotaLedger(limits, margin=0.0, clock=clock, path=path)


class Pick(BaseModel):
    choice: str


MESSAGES = [Message("system", "Pick one."), Message("user", "a or b?")]


def offline_stand_in() -> FakeProvider:
    """The offline stand-in, answering this file's task."""
    return FakeProvider(responders={"pick": lambda _ctx: {"choice": "offline"}})


class Recorder:
    """A real model (not the offline stand-in) that records when each request reached it and
    the tokens it would count for it."""

    kind = ProviderKind.OPENAI_COMPATIBLE

    def __init__(
        self, name: str, clock: Clock, *, latency: float = 0.4, rng: random.Random | None = None
    ) -> None:
        self.name, self.model = name, f"{name}-model"
        self.clock = clock
        self.latency = latency
        self.rng = rng
        self.received: list[tuple[float, int]] = []

    async def chat(self, messages: Sequence[Message], **_: Any) -> tuple[str, Usage]:
        prompt = sum(len(m.content) for m in messages) // 4  # what the provider counts
        output = 40
        self.received.append((self.clock(), prompt + output))
        jitter = self.rng.uniform(0.0, 1.5) if self.rng else 0.0
        await self.clock.sleep(self.latency + jitter)
        return '{"choice": "a"}', Usage(input_tokens=prompt, output_tokens=output)


# --- the minute ---------------------------------------------------------------------------------


def test_requests_are_paced_inside_a_sliding_minute() -> None:
    clock = Clock(NOON)
    ledger = book(clock, gemini=ProviderLimits(rpm=3))
    for second in range(3):
        clock.now = NOON + second
        assert isinstance(ledger.acquire("gemini", 10), Ticket)
    clock.now = NOON + 3
    refused = ledger.acquire("gemini", 10)
    assert isinstance(refused, Refusal)
    assert refused.kind == "minute"
    # The first request leaves the window a minute, and a second for its trip, after it went.
    assert refused.retry_at == NOON + 61
    clock.now = NOON + 60.5  # the provider may still count it in this minute
    assert isinstance(ledger.acquire("gemini", 10), Refusal)
    clock.now = refused.retry_at
    assert isinstance(ledger.acquire("gemini", 10), Ticket)
    assert isinstance(ledger.acquire("gemini", 10), Refusal)  # the second is still inside


def test_tokens_are_counted_reconciled_and_too_large_requests_refused() -> None:
    clock = Clock(NOON)
    ledger = book(clock, gemma=ProviderLimits(tpm=1_000))
    first = ledger.acquire("gemma", 600)
    assert isinstance(first, Ticket)
    refused = ledger.acquire("gemma", 600)
    assert isinstance(refused, Refusal)
    assert (refused.kind, refused.retry_at) == ("tokens", NOON + 61)
    ledger.settle(first, tokens=200)  # the provider reported fewer than the estimate
    assert isinstance(ledger.acquire("gemma", 600), Ticket)
    too_large = ledger.acquire("gemma", 1_001)
    assert isinstance(too_large, Refusal)
    assert (too_large.kind, too_large.retry_at) == ("too_large", None)


def test_admission_estimates_err_high_and_the_margin_keeps_a_share_spare() -> None:
    messages = [Message("system", "x" * 300), Message("user", "y" * 900)]
    estimate = request_tokens(messages, 500)
    assert estimate == 1_200 // 3 + 2 * 4 + 500
    assert estimate > 1_200 // 4 + 500  # above the four-characters-a-token estimate
    assert request_tokens(messages, 500, {"type": "object"}) > estimate  # the schema travels too
    assert [effective(n, 0.1) for n in (20, 5, 1, 0)] == [18, 4, 1, 0]
    assert effective(None, 0.1) is None


async def test_the_router_waits_briefly_for_a_minute_to_free_up_then_sends() -> None:
    """Pacing: a request that would pass the minute's limit waits for the window when room
    comes back soon, instead of falling back to a weaker model."""
    clock = Clock(NOON)
    config = get_app_config().llm.model_copy(update={"routing": {"default": ["gemini", "fake"]}})
    gemini = Recorder("gemini", clock)
    ledger = QuotaLedger({"gemini": ProviderLimits(rpm=2)}, margin=0.0, clock=clock)
    router = LLMRouter(
        config,
        providers={"gemini": gemini, "fake": offline_stand_in()},
        ledger=ledger,
        sleep=clock.sleep,
    )
    for _ in range(2):
        await router.structured("default", "pick", MESSAGES, Pick)
    clock.now = NOON + 57  # room comes back at NOON + 61, within the five-second wait
    result = await router.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "gemini"
    assert gemini.received[-1][0] >= NOON + 61
    clock.now = NOON + 62
    # The window now holds the paced request, and room for one more...
    assert (await router.structured("default", "pick", MESSAGES, Pick)).provider == "gemini"
    result = await router.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "fake"  # ...then the next is a minute away: it moves on
    assert result.attempts[0]["skipped"] == "minute"
    assert len(gemini.received) == 4


# --- the day ------------------------------------------------------------------------------------


def test_the_day_starts_again_at_midnight_pacific_not_utc() -> None:
    evening = datetime(2026, 10, 30, 16, 59, 30, tzinfo=PACIFIC).timestamp()
    clock = Clock(evening)
    ledger = book(clock, gemini=ProviderLimits(rpd=2))
    for _ in range(2):
        assert isinstance(ledger.acquire("gemini", 1), Ticket)
    clock.now = evening + 60  # midnight UTC has passed: Google's day has not
    refused = ledger.acquire("gemini", 1)
    assert isinstance(refused, Refusal)
    assert refused.kind == "day"
    midnight = datetime(2026, 10, 31, 0, 0, tzinfo=PACIFIC).timestamp()
    assert refused.retry_at == midnight
    clock.now = midnight - 1
    assert isinstance(ledger.acquire("gemini", 1), Refusal)
    clock.now = midnight
    assert isinstance(ledger.acquire("gemini", 1), Ticket)


def test_a_day_with_a_clock_change_lasts_25_or_23_hours() -> None:
    # Pacific clocks go back an hour at 02:00 on 1 November 2026 and forward at 02:00 on 8 March.
    autumn = datetime(2026, 11, 1, 0, 0, tzinfo=PACIFIC).timestamp()
    assert next_reset(autumn, PACIFIC) - autumn == 25 * 3600
    spring = datetime(2026, 3, 8, 0, 0, tzinfo=PACIFIC).timestamp()
    assert next_reset(spring, PACIFIC) - spring == 23 * 3600
    # Both 01:30s of 1 November are the same day; the next starts at midnight standard time.
    clock = Clock(autumn + 1.5 * 3600)  # 01:30 daylight time
    ledger = book(clock, gemini=ProviderLimits(rpd=2))
    assert isinstance(ledger.acquire("gemini", 1), Ticket)
    clock.now += 3600  # 01:30 again, standard time
    assert local_day(clock.now, PACIFIC) == "2026-11-01"
    assert isinstance(ledger.acquire("gemini", 1), Ticket)
    assert isinstance(ledger.acquire("gemini", 1), Refusal)
    clock.now = datetime(2026, 11, 2, 0, 0, tzinfo=PACIFIC).timestamp()
    assert clock.now - autumn == 25 * 3600
    assert isinstance(ledger.acquire("gemini", 1), Ticket)


def test_counts_and_holds_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "llm-quota.json"
    clock = Clock(NOON)
    limits = {"gemini": ProviderLimits(rpm=10, rpd=5), "gemma": ProviderLimits(rpd=100)}
    first = book(clock, path, **limits)
    for _ in range(3):
        assert isinstance(first.acquire("gemini", 50), Ticket)
    until = first.hold("gemma", RateLimit("day", "its daily quota is used up"))
    assert first.save()
    assert not first.save()  # nothing new to write
    assert not list(tmp_path.glob(".*.tmp"))  # replaced atomically: no partial file left
    clock.now += 30
    again = book(clock, path, **limits)
    room = {c.provider: c for c in again.capacity()}
    assert room["gemini"].day_requests_used == 3
    assert room["gemini"].minute_requests_left == 7  # this minute's requests came back too
    assert room["gemma"].held_until == until
    assert isinstance(again.acquire("gemma", 1), Refusal)
    assert isinstance(again.acquire("gemini", 1), Ticket)
    assert isinstance(again.acquire("gemini", 1), Ticket)
    assert isinstance(again.acquire("gemini", 1), Refusal)  # 5 today, across the restart
    clock.now = next_reset(clock.now, PACIFIC)
    tomorrow = book(clock, path, **limits)
    room = {c.provider: c for c in tomorrow.capacity()}
    assert room["gemini"].day_requests_used == 0  # a new day starts afresh
    assert room["gemma"].held_until is None  # its rest ended at the reset


def test_an_unreadable_file_starts_afresh_and_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "llm-quota.json"
    path.write_text("{not json", encoding="utf-8")
    clock = Clock(NOON)
    ledger = book(clock, path, gemini=ProviderLimits(rpd=5))
    assert isinstance(ledger.acquire("gemini", 1), Ticket)
    assert ledger.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["providers"]["gemini"]["day_requests"] == 1
    assert saved["timezone"] == "America/Los_Angeles"


# --- holds ----------------------------------------------------------------------------------------


def test_each_kind_of_refusal_rests_the_provider_for_as_long_as_it_lasts() -> None:
    clock = Clock(NOON)
    ledger = book(clock)
    reset = next_reset(NOON, PACIFIC)
    assert ledger.hold("a", RateLimit("minute", "x", retry_after=41)) == NOON + 41
    assert ledger.hold("b", RateLimit("minute", "x")) == NOON + 60
    # A daily quota is not cured by waiting its retry delay: it lasts until the reset.
    assert ledger.hold("c", RateLimit("day", "x", retry_after=41)) == reset
    assert ledger.hold("d", RateLimit("spend_cap", "x")) == reset
    assert ledger.hold("e", RateLimit("spend_cap", "x", until=NOON + 600)) == NOON + 600
    assert ledger.hold("f", RateLimit("spend_cap", "x", until=reset + 5 * 86_400)) == reset
    assert ledger.hold("g", RateLimit("no_credit", "x")) == reset
    assert ledger.hold("h", RateLimit("overload", "x")) == NOON + 15
    refused = ledger.acquire("c", 1)
    assert isinstance(refused, Refusal)
    assert (refused.kind, refused.retry_at) == ("hold", reset)
    clock.now = reset
    assert isinstance(ledger.acquire("c", 1), Ticket)


# --- reservations -------------------------------------------------------------------------------


def test_a_run_sets_aside_its_calls_and_others_cannot_take_them() -> None:
    clock = Clock(NOON)
    ledger = book(clock, gemini=ProviderLimits(rpd=3), **{"gemini-lite": ProviderLimits(rpd=1)})
    reservation = ledger.reserve({"investigator": 2, "critic": 1}, CHAINS)
    assert isinstance(reservation, Reservation)
    assert reservation.held == {"gemini": 2, "gemini-lite": 1}
    assert isinstance(ledger.acquire("gemini", 10), Ticket)  # the one left for everyone else
    for name in ("gemini", "gemini-lite"):
        refused = ledger.acquire(name, 10)
        assert isinstance(refused, Refusal)
        assert refused.kind == "day"
    for name in ("gemini", "gemini", "gemini-lite"):  # the run's own calls find their room
        ticket = ledger.acquire(name, 10, reservation=reservation)
        assert isinstance(ticket, Ticket)
        assert ticket.reserved
    assert reservation.calls == 0


def test_a_run_that_does_not_fit_sets_nothing_aside_and_says_when() -> None:
    clock = Clock(NOON)
    ledger = book(clock, gemini=ProviderLimits(rpd=1), **{"gemini-lite": ProviderLimits(rpd=1)})
    outcome = ledger.reserve({"investigator": 3}, CHAINS)
    assert isinstance(outcome, Unreserved)
    assert outcome.back_at == next_reset(NOON, PACIFIC)
    assert all(c.day_requests_reserved == 0 for c in ledger.capacity())  # all or nothing
    assert ledger.check_run({"investigator": 3}, CHAINS) == outcome.back_at
    assert ledger.check_run({"investigator": 2}, CHAINS) is None
    assert ledger.runs_left({"investigator": 1}, CHAINS) == 2


def test_released_and_lapsed_reservations_give_back_their_requests() -> None:
    clock = Clock(NOON)
    only = {"investigator": ["gemini"]}
    ledger = QuotaLedger(
        {"gemini": ProviderLimits(rpd=4)}, margin=0.0, clock=clock, reservation_ttl_s=60
    )
    first = ledger.reserve({"investigator": 2}, only)
    assert isinstance(first, Reservation)
    assert isinstance(ledger.acquire("gemini", 1, reservation=first), Ticket)
    assert ledger.release(first) == 1  # the call it did not make
    assert ledger.release(first) == 0
    second = ledger.reserve({"investigator": 3}, only)
    assert isinstance(second, Reservation)
    assert isinstance(ledger.reserve({"investigator": 1}, only), Unreserved)
    clock.now += 61  # its run never came back for it
    assert isinstance(ledger.reserve({"investigator": 1}, only), Reservation)


def test_a_long_rest_is_passed_over_but_a_short_one_is_not() -> None:
    limits = {"gemini": ProviderLimits(rpd=5), "gemini-lite": ProviderLimits(rpd=5)}
    clock = Clock(NOON)
    resting = book(clock, **limits)
    resting.hold("gemini", RateLimit("day", "its daily quota is used up"))
    placed = resting.reserve({"investigator": 2}, CHAINS)
    assert isinstance(placed, Reservation)
    assert placed.held == {"gemini-lite": 2}
    busy = book(clock, **limits)
    busy.hold("gemini", RateLimit("minute", "its per-minute limit is reached", retry_after=30))
    placed = busy.reserve({"investigator": 2}, CHAINS)
    assert isinstance(placed, Reservation)
    assert placed.held == {"gemini": 2}  # back long before the run's later calls


def test_a_run_is_told_the_soonest_moment_a_resting_model_comes_back() -> None:
    clock = Clock(NOON)
    ledger = book(clock, gemini=ProviderLimits(rpd=1))
    assert isinstance(ledger.acquire("gemini", 1), Ticket)  # its day is used
    # Claude counts nothing here, but rests until the moment its spend-limit message named.
    ledger.hold("claude", RateLimit("spend_cap", "x", until=NOON + 3_600))
    outcome = ledger.reserve({"reporter": 1}, {"reporter": ["gemini", "claude"]})
    assert isinstance(outcome, Unreserved)
    assert outcome.back_at == NOON + 3_600
    clock.now = NOON + 3_600
    assert isinstance(
        ledger.reserve({"reporter": 1}, {"reporter": ["gemini", "claude"]}), Reservation
    )


def test_a_model_without_daily_limits_needs_nothing_set_aside() -> None:
    ledger = book(Clock(NOON), gemini=ProviderLimits(rpm=10))
    reservation = ledger.reserve({"investigator": 5}, {"investigator": ["gemini", "claude"]})
    assert isinstance(reservation, Reservation)
    assert reservation.held == {}
    assert ledger.runs_left({"investigator": 5}, {"investigator": ["gemini"]}) is None
    # A role no model takes has nothing to set aside either.
    assert ledger.check_run({"comms": 1}, {"comms": []}) is None


def test_the_offline_reason_says_when_the_models_are_back_in_plain_words() -> None:
    reset = next_reset(NOON, PACIFIC)
    message = offline_message(reset, now=NOON, tz=PACIFIC)
    assert message.startswith("The site's shared models are at their limits for now")
    assert message.endswith("after midnight Pacific time (07:00 UTC).")
    assert back_in_words(NOON + 12 * 60, now=NOON, tz=PACIFIC) == "in about 12 minutes"
    assert back_in_words(NOON + 3 * 3600, now=NOON, tz=PACIFIC) == "at 22:00 UTC"


# --- the owner's requirement: a burst never passes any model's limits ---------------------------


def _worst_window(times: list[float], weights: list[int], span: float = 60.0) -> int:
    """The most any ``span``-second stretch holds, by weight."""
    pairs = sorted(zip(times, weights, strict=True))
    worst = 0
    for i, (end, _) in enumerate(pairs):
        worst = max(worst, sum(w for t, w in pairs[: i + 1] if t > end - span))
    return worst


async def test_a_burst_of_runs_never_sends_any_model_more_than_its_limits() -> None:
    """Many visitors at once, across midnight Pacific: every model in the Gemini pool stays
    within its configured requests a minute, tokens a minute and requests a day, while runs
    that find no room go offline and questions without a reservation fall back."""
    config = get_app_config()
    llm = config.llm
    pool = ("gemini", "gemini-lite", "gemini-lite-2", "gemma")
    start = datetime(2026, 10, 30, 23, 54, tzinfo=PACIFIC).timestamp()
    clock = Clock(start)
    rng = random.Random(7)
    recorders = {name: Recorder(name, clock, rng=rng) for name in pool}
    router = LLMRouter(
        llm,
        env=Environment.DEV,
        providers={**recorders, "fake": offline_stand_in()},
        ledger=QuotaLedger.from_config(llm, clock=clock),
        sleep=clock.sleep,
    )
    needs = expected_llm_calls(config)
    outcomes: Counter[str] = Counter()
    padding = "evidence line " * 120  # prompts big enough for Gemma's tokens-a-minute to bind

    async def run(i: int) -> None:
        reservation = router.reserve_run(needs)
        if isinstance(reservation, Unreserved):
            outcomes["offline"] += 1
            return
        view = router.for_run(reservation)
        try:
            for role, count in needs.items():
                for _ in range(count):
                    messages = [Message("system", padding), Message("user", f"run {i} {role}")]
                    try:
                        result = await view.structured(
                            role, "pick", messages, Pick, temperature=0.1, max_tokens=400
                        )
                    except NoProviderAvailableError:  # the severity choice has no stand-in
                        outcomes["fallback"] += 1
                        continue
                    outcomes["fallback" if result.provider == "fake" else "model"] += 1
        finally:
            router.release_run(reservation)
        outcomes["runs"] += 1

    async def ask(i: int) -> None:  # questions take no reservation: what is left over
        result = await router.structured(
            "ask", "pick", [Message("user", f"question {i}")], Pick, temperature=0.1
        )
        outcomes["asked_offline" if result.provider == "fake" else "asked"] += 1

    for wave in range(3):  # before midnight, across it, and on the new day
        await asyncio.gather(*(run(i) for i in range(40)), *(ask(i) for i in range(20)))
        clock.now = max(clock.now, start + (wave + 1) * 7 * 60)

    assert local_day(clock.now, PACIFIC) == "2026-10-31"  # the burst crossed midnight
    for name in pool:
        limits = llm.providers[name].limits
        assert limits is not None
        assert limits.rpm is not None
        assert limits.tpm is not None
        assert limits.rpd is not None
        received = recorders[name].received
        times = [t for t, _ in received]
        assert _worst_window(times, [1] * len(times)) <= limits.rpm, name
        assert _worst_window(times, [tokens for _, tokens in received]) <= limits.tpm, name
        per_day = Counter(local_day(t, PACIFIC) for t in times)
        assert max(per_day.values()) <= limits.rpd, name
    # The burst pressed on the limits that bind: every model's minute was full at some point,
    # the lite models used their whole (margin-cut) day, and the calls past the pool's room fell
    # back along the chain instead of going over.
    margin = llm.quota.margin
    for name in pool:
        limits = llm.providers[name].limits
        assert limits is not None
        times = [t for t, _ in recorders[name].received]
        assert _worst_window(times, [1] * len(times)) == effective(limits.rpm, margin), name
    lite = llm.providers["gemini-lite"].limits
    assert lite is not None
    lite_days = Counter(local_day(t, PACIFIC) for t, _ in recorders["gemini-lite"].received)
    assert max(lite_days.values()) == effective(lite.rpd, margin)
    assert outcomes["runs"] > 0
    assert outcomes["fallback"] + outcomes["asked_offline"] > 0
