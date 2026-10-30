"""Units of work that started but never finished.

Many systems log each unit of work (an HDFS block write, a task attempt, a VM boot) as a series
of steps, and a unit that fails often logs no error at all: its steps simply stop. ARIA groups a
window's lines by the unit's ID (config/flows.yaml), learns from the window itself which steps
always come in equal numbers (every "Receiving block" has one "Received block"), and flags units
whose steps don't add up, or that took a step almost no other unit takes.

The step relations are mined without labels, from the window being triaged, in the spirit of
Lou et al., "Mining Invariants from Console Logs for System Problem Detection" (USENIX ATC
2010), restricted to the simplest invariant: two steps whose counts are equal. A window with too
few units to learn from is not checked, so the check stays silent rather than guess.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from aria.parsing.drain import WILDCARD

FLOWS_PATH = Path("config/flows.yaml")
MAX_UNIT_LINES = 12  # line indices kept per flagged unit, for evidence and the UI


@dataclass(frozen=True)
class UnitKind:
    id: str
    name: str
    plural: str
    hint: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class FlowSettings:
    kinds: tuple[UnitKind, ...]
    min_units: int = 30
    min_support: float = 0.95
    rare_share: float = 0.005
    settle_quantile: float = 0.999
    min_settle_s: float = 5.0
    probe_s: float = 60.0
    max_units: int = 20_000


@lru_cache(maxsize=4)
def load_flow_settings(path: Path = FLOWS_PATH) -> FlowSettings:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    kinds = tuple(
        UnitKind(
            id=str(item["id"]),
            name=str(item["name"]),
            plural=str(item.get("plural") or f"{item['name']}s"),
            hint=str(item.get("hint") or ""),
            pattern=re.compile(item["pattern"]),
        )
        for item in raw.get("kinds", [])
    )
    mining = raw.get("mining") or {}
    return FlowSettings(
        kinds=kinds,
        min_units=int(mining.get("min_units", 30)),
        min_support=float(mining.get("min_support", 0.95)),
        rare_share=float(mining.get("rare_share", 0.005)),
        settle_quantile=float(mining.get("settle_quantile", 0.999)),
        min_settle_s=float(mining.get("min_settle_s", 5.0)),
        probe_s=float(mining.get("probe_s", 60.0)),
        max_units=int(mining.get("max_units", 20_000)),
    )


@dataclass(slots=True)
class Step:
    """One parsed line, as the check needs it."""

    idx: int
    ts: datetime | None
    template_id: str
    template: str
    message: str


@dataclass(slots=True)
class Unit:
    kind: UnitKind
    key: str
    counts: Counter[str] = field(default_factory=Counter)
    lines: list[int] = field(default_factory=list)
    first: datetime | None = None
    last: datetime | None = None
    # When each step was last seen, for the settle time.
    seen: dict[str, datetime] = field(default_factory=dict)

    def add(self, step: Step) -> None:
        self.counts[step.template_id] += 1
        self.lines.append(step.idx)
        if step.ts is not None:
            self.first = step.ts if self.first is None else min(self.first, step.ts)
            self.last = step.ts if self.last is None else max(self.last, step.ts)
            self.seen[step.template_id] = max(step.ts, self.seen.get(step.template_id, step.ts))


@dataclass(frozen=True)
class StepPair:
    """Two steps whose counts are equal on almost every unit of a kind."""

    kind: str
    a: str
    b: str
    units: int
    support: float


@dataclass(frozen=True)
class BrokenUnit:
    kind: UnitKind
    key: str
    problem: Literal["mismatch", "unusual_step"]
    reason: str
    lines: tuple[int, ...]
    first: datetime | None
    last: datetime | None
    # Template ids: the step seen more often then the one seen less (mismatch), or the rare step.
    steps: tuple[str, ...] = ()


@dataclass
class FlowResult:
    units: dict[str, int] = field(default_factory=dict)  # units seen, by kind name
    checked: dict[str, int] = field(default_factory=dict)  # units judged, by kind name
    pairs: list[StepPair] = field(default_factory=list)
    broken: list[BrokenUnit] = field(default_factory=list)
    settle_s: dict[str, float] = field(default_factory=dict)
    templates: dict[str, str] = field(default_factory=dict)  # template id -> text
    checked_keys: set[str] = field(default_factory=set)  # every unit judged, for evaluations

    @property
    def n_checked(self) -> int:
        return sum(self.checked.values())

    @property
    def broken_ratio(self) -> float:
        return round(len(self.broken) / self.n_checked, 4) if self.n_checked else 0.0


def short_step(template: str, limit: int = 60) -> str:
    """A template as people read it: wildcards become ellipses, long ones are cut."""
    text = re.sub(r"\s+", " ", template.replace(WILDCARD, "…")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def group_units(steps: Sequence[Step], kinds: Sequence[UnitKind]) -> dict[str, dict[str, Unit]]:
    """Units by kind id, then by key. A line that names several units counts towards each."""
    units: dict[str, dict[str, Unit]] = {kind.id: {} for kind in kinds}
    for step in steps:
        for kind in kinds:
            if kind.hint and kind.hint not in step.message:
                continue
            for key in set(kind.pattern.findall(step.message)):
                bucket = units[kind.id]
                unit = bucket.get(key)
                if unit is None:
                    unit = bucket[key] = Unit(kind, key)
                unit.add(step)
    return units


def mine_pairs(
    units: Sequence[Unit], *, kind: str, min_units: int, min_support: float
) -> list[StepPair]:
    """Step pairs with equal counts on at least ``min_support`` of the units showing either."""
    holders: dict[str, set[int]] = defaultdict(set)
    for i, unit in enumerate(units):
        for template in unit.counts:
            holders[template].add(i)
    candidates = sorted(t for t, held in holders.items() if len(held) >= min_units)
    pairs = []
    for a, b in itertools.combinations(candidates, 2):
        related = holders[a] | holders[b]
        if len(related) < min_units:
            continue
        equal = sum(1 for i in related if units[i].counts[a] == units[i].counts[b])
        support = equal / len(related)
        if support >= min_support:
            pairs.append(StepPair(kind, a, b, len(related), round(support, 4)))
    return pairs


def _sample(units: Sequence[Unit], limit: int) -> list[Unit]:
    """At most ``limit`` units, spread evenly, so mining very large windows stays fast."""
    if len(units) <= limit:
        return list(units)
    stride = len(units) / limit
    return [units[int(i * stride)] for i in range(limit)]


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def _complete(unit: Unit, pairs: Sequence[StepPair]) -> bool:
    return all(unit.counts[p.a] == unit.counts[p.b] for p in pairs)


def _settle(units: Sequence[Unit], pairs: Sequence[StepPair], settings: FlowSettings) -> float:
    """How long complete units took, from their first line to their last paired step."""
    steps = {t for p in pairs for t in (p.a, p.b)}
    spans = [
        (max(u.seen[t] for t in steps if t in u.seen) - u.first).total_seconds()
        for u in units
        if u.first is not None and steps & u.seen.keys() and _complete(u, pairs)
    ]
    if not spans:
        return settings.min_settle_s
    return max(settings.min_settle_s, _quantile(spans, settings.settle_quantile))


def _core(units: Sequence[Unit], start: datetime, end: datetime, settle: float) -> list[Unit]:
    """Units seen from start to finish: they begin at least ``settle`` seconds after the window
    opens (no steps before it) and at least ``settle`` seconds before it closes (time to end)."""
    return [
        u
        for u in units
        if u.first is not None
        and (u.first - start).total_seconds() >= settle
        and (end - u.first).total_seconds() >= settle
    ]


def _mismatch(unit: Unit, pairs: Sequence[StepPair]) -> tuple[str, str] | None:
    """The pair the unit breaks worst, as (step seen more often, step seen less often)."""
    broken = [p for p in pairs if unit.counts[p.a] != unit.counts[p.b]]
    if not broken:
        return None
    worst = max(broken, key=lambda p: (abs(unit.counts[p.a] - unit.counts[p.b]), p.a, p.b))
    if unit.counts[worst.a] > unit.counts[worst.b]:
        return worst.a, worst.b
    return worst.b, worst.a


def check_flows(steps: Sequence[Step], settings: FlowSettings | None = None) -> FlowResult:
    """Group lines into units of work, learn which steps pair up, and flag units that break."""
    settings = settings or load_flow_settings()
    result = FlowResult(templates={s.template_id: s.template for s in steps})
    stamps = [s.ts for s in steps if s.ts is not None]
    start, end = (min(stamps), max(stamps)) if stamps else (None, None)
    for by_key in group_units(steps, settings.kinds).values():
        if not by_key:
            continue
        units = [by_key[k] for k in sorted(by_key)]
        kind = units[0].kind
        result.units[kind.name] = len(units)
        if len(units) < settings.min_units:
            continue

        def mine(pool: Sequence[Unit], kind: UnitKind = kind) -> list[StepPair]:
            return mine_pairs(
                _sample(pool, settings.max_units),
                kind=kind.name,
                min_units=settings.min_units,
                min_support=settings.min_support,
            )

        judged = units
        if start is not None and end is not None and all(u.first for u in units):
            # First pass: learn the pairs and the settle time from units that start a short
            # probe margin inside the window, which are most likely complete.
            margin = min(settings.probe_s, (end - start).total_seconds() / 4)
            inner = _core(units, start, end, margin)
            pairs = mine(inner if len(inner) >= settings.min_units else units)
            if not pairs:
                continue
            settle = _settle(inner or units, pairs, settings)
            judged = _core(units, start, end, settle)
            result.settle_s[kind.name] = round(settle, 1)
        pairs = mine(judged)
        if not pairs:
            continue
        paired = {t for p in pairs for t in (p.a, p.b)}
        checked = [u for u in judged if paired & u.counts.keys()]
        result.checked[kind.name] = len(checked)
        result.checked_keys.update(u.key for u in checked)
        result.pairs.extend(pairs)
        shown: Counter[str] = Counter()
        for unit in checked:
            shown.update(unit.counts.keys())
        rare = {t for t, n in shown.items() if n / len(checked) < settings.rare_share}
        for unit in checked:
            names = result.templates
            problem: Literal["mismatch", "unusual_step"] = "mismatch"
            mismatch = _mismatch(unit, pairs)
            if mismatch is not None:
                more, fewer = mismatch
                found: tuple[str, ...] = mismatch
                reason = (
                    f"{unit.counts[more]} × “{short_step(names[more])}” but "
                    f"{unit.counts[fewer]} × “{short_step(names[fewer])}”"
                )
            else:
                unusual = sorted(rare & unit.counts.keys())
                if not unusual:
                    continue
                problem, found = "unusual_step", (unusual[0],)
                reason = (
                    f"took a step few {kind.plural} take: “{short_step(names[unusual[0]])}” "
                    f"(on {shown[unusual[0]]} of {len(checked)})"
                )
            result.broken.append(
                BrokenUnit(
                    kind=kind,
                    key=unit.key,
                    problem=problem,
                    reason=reason,
                    lines=tuple(unit.lines[:MAX_UNIT_LINES]),
                    first=unit.first,
                    last=unit.last,
                    steps=found,
                )
            )
    result.broken.sort(
        key=lambda b: (b.first is None, b.first.timestamp() if b.first else 0.0, b.key)
    )
    return result


def pair_groups(pairs: Sequence[StepPair]) -> list[tuple[str, list[str]]]:
    """Steps that pair up, merged into groups (each kind's lifecycle), largest first."""
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(x: tuple[str, str]) -> tuple[str, str]:
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    for pair in pairs:
        parent[find((pair.kind, pair.a))] = find((pair.kind, pair.b))
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for node in list(parent):
        groups[find(node)].append(node[1])
    return sorted(
        ((root[0], sorted(members)) for root, members in groups.items()),
        key=lambda g: (-len(g[1]), g[0], g[1]),
    )
