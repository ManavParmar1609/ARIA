"""Semi-synthetic incident scenarios built from real Loghub lines.

Every line in a scenario is a real line from the official Loghub samples; the builder only picks
which lines, on which nodes, at what times. That gives labelled incident windows for systems
whose public samples are not contiguous, for the demo, for seeding incident memory and for
robustness tests. Every scenario is marked ``synthetic=True`` and reported separately from
results on contiguous real data.
"""

from __future__ import annotations

import random
import re
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from aria.contracts.base import Severity
from aria.data.labels import AlertRubric, label_window, load_rubric, tag_stats
from aria.data.loghub import LOGHUB_DIRS, LogRecord, format_raw_line, iter_structured_csv

CATALOG_PATH = Path("config/scenarios.yaml")
SCENARIO_EPOCH = datetime(2026, 3, 2, tzinfo=UTC)
FIXTURE_LINES = Path("tests/fixtures/loghub")  # the small Loghub copies that ship with ARIA

# Where a sample's logs come from, in the order the console lists them.
SOURCES: dict[str, str] = {
    "security": "Security and sign-ins",
    "web": "Web and cloud",
    "bigdata": "Big-data clusters",
    "hpc": "Supercomputers",
    "noise": "False alarms",
}

# Console samples: one fixed window per sample and size, so a sample reads the same every time.
SAMPLE_SEED = 7
SAMPLE_MINUTES = 8
SAMPLE_BACKGROUND_PER_MIN = 8.0
SAMPLE_SERVERS = 3  # for a sample whose severity does not depend on how many servers it hits
SAMPLE_RATE = 12  # incident lines a minute at the burst's peak, unless the visitor picks a rate
SERVER_STEPS = (2, 3, 4, 6, 8, 12, 16, 24, 32)
RATE_STEPS = (SAMPLE_RATE, 30, 60, 120, 160)


def loghub_dir(data_dir: Path) -> Path:
    """The Loghub samples when they have been downloaded, else the copies that ship with ARIA."""
    full = data_dir / "raw" / "loghub-2k"
    return full if full.is_dir() else FIXTURE_LINES


_PLURAL_AFTER_ONE = re.compile(r"\b1 ((?:[\w/-]+ )*?)(node|host|peer|client)s\b")


def _counted(template: str, nodes: int) -> str:
    """A scenario title with its count, singular for one: "1 compute node", not "1 compute
    nodes"."""
    title = template.format(nodes=nodes)
    return _PLURAL_AFTER_ONE.sub(r"1 \1\2", title) if nodes == 1 else title


@dataclass(frozen=True)
class Card:
    """How the console offers a failure mode as a sample: what happened, in plain words, with the
    technology underneath, grouped by where its logs come from."""

    title: str
    technology: str
    source: str
    summary: str
    headline: bool = False
    # A line that tries to talk ARIA out of the incident, which the injection guard should catch.
    trick: str | None = None
    # False where the logs' node field names something other than a server (ZooKeeper's threads),
    # so a choice of "how many servers" would not mean what it says.
    servers: bool = True


@dataclass(frozen=True)
class FailureMode:
    key: str
    system: str
    title: str
    runbook: str | None
    tags: tuple[str, ...] = ()
    pattern: re.Pattern[str] | None = None
    benign: bool = False
    base: Severity = Severity.SEV3
    escalate: tuple[dict[str, Any], ...] = ()
    card: Card | None = None

    @property
    def name(self) -> str:
        return self.key.split(".", 1)[1]


@dataclass
class Scenario:
    id: str
    failure_mode: str
    system: str
    title: str
    severity: Severity
    lines: list[str]
    records: list[LogRecord]
    nodes: list[str]
    start: datetime
    end: datetime
    incident_lines: int
    peak_rate_per_min: float
    runbook: str | None
    label_source: str
    label_detail: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = True


@dataclass(frozen=True)
class SizeChoice:
    """Sizes at which a sample's severity changes, smallest first; the first is the default."""

    values: tuple[int, ...]

    @property
    def default(self) -> int:
        return self.values[0]


@dataclass(frozen=True)
class SampleSizes:
    servers: SizeChoice | None = None
    rate: SizeChoice | None = None


def _card(key: str, spec: dict[str, Any] | None) -> Card | None:
    if spec is None:
        return None
    card = Card(**spec)
    if card.source not in SOURCES:
        msg = f"{key}: card source {card.source!r} is not one of {', '.join(SOURCES)}"
        raise ValueError(msg)
    return card


@lru_cache(maxsize=2)
def load_catalog(path: Path = CATALOG_PATH) -> dict[str, FailureMode]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["failure_modes"]
    modes: dict[str, FailureMode] = {}
    for key, spec in raw.items():
        severity = spec.get("severity") or {}
        modes[key] = FailureMode(
            key=key,
            system=spec["system"],
            title=spec["title"],
            runbook=spec.get("runbook"),
            tags=tuple(spec.get("tags", ())),
            pattern=re.compile(spec["match"]) if spec.get("match") else None,
            benign=bool(spec.get("benign", False)),
            base=Severity(severity.get("base", "SEV3")),
            escalate=tuple(severity.get("escalate", ())),
            card=_card(key, spec.get("card")),
        )
    return modes


class LinePools:
    """Real lines from the Loghub samples, grouped into background and per-failure pools."""

    def __init__(self, records: dict[str, list[LogRecord]], modes: dict[str, FailureMode]) -> None:
        self.modes = modes
        self.background: dict[str, list[LogRecord]] = {}
        self.incident: dict[str, list[LogRecord]] = defaultdict(list)
        self.nodes: dict[str, list[str]] = {}
        for system, recs in records.items():
            system_modes = [m for m in modes.values() if m.system == system]
            matched: set[int] = set()
            for mode in system_modes:
                for i, rec in enumerate(recs):
                    hit = (mode.tags and rec.label in mode.tags) or (
                        mode.pattern is not None and mode.pattern.search(rec.message)
                    )
                    if hit:
                        self.incident[mode.key].append(rec)
                        matched.add(i)
            self.background[system] = [
                rec
                for i, rec in enumerate(recs)
                if i not in matched and not rec.label and rec.level in (None, "DEBUG", "INFO")
            ]
            self.nodes[system] = sorted({rec.node for rec in recs if rec.node})

    @classmethod
    def from_loghub(
        cls, loghub_dir: Path, modes: dict[str, FailureMode] | None = None
    ) -> LinePools:
        modes = modes or load_catalog()
        wanted = {m.system for m in modes.values()}
        records: dict[str, list[LogRecord]] = {}
        for directory, system in LOGHUB_DIRS.items():
            path = loghub_dir / directory / f"{directory}_2k.log_structured.csv"
            if system in wanted and path.exists():
                records[system] = list(iter_structured_csv(system, path))
        return cls(records, modes)

    def available_modes(self) -> list[str]:
        return [
            key
            for key in self.modes
            if self.incident.get(key) and self.background.get(self.modes[key].system)
        ]


@lru_cache(maxsize=64)
def node_visible(system: str) -> bool:
    """Whether the system's raw line format names the host, so a node count is observable."""
    probe = LogRecord(
        system=system, line_no=1, message="probe", ts=SCENARIO_EPOCH, node="aria-node-probe"
    )
    return "aria-node-probe" in format_raw_line(probe)


def _policy_severity(
    mode: FailureMode, nodes: int, peak_rate: float
) -> tuple[Severity, dict[str, Any]]:
    """The scenario's label. A node-count escalation applies only where the logs show hosts.

    Some formats (HDFS, Hadoop, Apache, Proxifier) carry no host field, so a label that escalated
    on how many hosts were affected would depend on information no reader of the logs has.
    """
    severity = mode.base
    fired: list[dict[str, Any]] = []
    observable = node_visible(mode.system)
    for rule in mode.escalate:
        target = Severity(rule["to"])
        by_nodes = observable and nodes >= int(rule.get("nodes_at_least", 10**9))
        by_rate = peak_rate >= float(rule.get("rate_per_min_at_least", float("inf")))
        if by_nodes or by_rate:
            fired.append(rule)
            severity = severity.more_severe(target)
    return severity, {
        "policy": "scenario",
        "base": mode.base.value,
        "escalations": fired,
        "nodes": nodes,
        "nodes_observable": observable,
        "peak_rate_per_min": round(peak_rate, 2),
    }


Rating = Callable[[Scenario], Severity]


def _label(scenario: Scenario) -> Severity:
    return scenario.severity


class ScenarioBuilder:
    def __init__(self, pools: LinePools, rubric: AlertRubric | None = None) -> None:
        self.pools = pools
        self.rubric = rubric or load_rubric()
        self._sizes: dict[str, SampleSizes] = {}
        self._rating: Rating = _label

    def rate_with(self, rating: Rating) -> None:
        """Choose sample sizes by ``rating``, the severity a run gives a sample, instead of the
        sample's label: a visitor sees the run's rating, so a size must change that one
        (``aria.severity.samples``)."""
        self._rating = rating
        self._sizes.clear()

    def use_sizes(self, sizes: Mapping[str, SampleSizes]) -> None:
        """Sizes chosen earlier from the same inputs (``aria seed`` rates them and saves them)."""
        self._sizes.update(sizes)

    def _node_names(self, system: str, count: int, rng: random.Random) -> list[str]:
        known = self.pools.nodes.get(system) or []
        if len(known) >= count:
            return rng.sample(known, count)
        names = list(known) + [f"{system}-node-{i:03d}" for i in range(count - len(known))]
        return names[:count]

    def build(
        self,
        mode_key: str,
        *,
        seed: int,
        nodes: int = 3,
        duration_min: int = 20,
        background_per_min: float = 30.0,
        incident_per_min: float = 12.0,
        start: datetime | None = None,
        cover_nodes: bool = False,
    ) -> Scenario:
        """A window of background traffic with the failure mode's lines bursting through it.

        ``cover_nodes`` makes every one of the ``nodes`` show the failure at least once, so the
        spread the label rests on is the spread asked for (the console's samples; the
        evaluation leaves spread to chance).
        """
        mode = self.pools.modes[mode_key]
        rng = random.Random(f"{mode_key}:{seed}")
        start = start or SCENARIO_EPOCH + timedelta(hours=seed % 5000)
        node_names = self._node_names(mode.system, max(1, nodes), rng)
        background = self.pools.background[mode.system]
        incident_pool = self.pools.incident[mode_key]

        records: list[LogRecord] = []
        for minute in range(duration_min):
            for _ in range(_poisson(rng, background_per_min)):
                base = rng.choice(background)
                ts = start + timedelta(minutes=minute, seconds=rng.uniform(0, 60))
                records.append(replace(base, ts=ts, node=base.node or rng.choice(node_names)))

        # Incident lines ramp up after a quiet lead-in, peak, then taper (a realistic burst shape).
        onset = max(1, duration_min // 4)
        active = range(onset, duration_min)
        per_minute: dict[int, int] = {}
        for minute in active:
            phase = (minute - onset) / max(1, duration_min - onset - 1)
            intensity = 0.35 + 0.65 * (1 - abs(2 * phase - 1))  # triangle: up then down
            per_minute[minute] = _poisson(rng, incident_per_min * intensity)
        injected: list[LogRecord] = []
        for minute, count in per_minute.items():
            for _ in range(count):
                base = rng.choice(incident_pool)
                ts = start + timedelta(minutes=minute, seconds=rng.uniform(0, 60))
                injected.append(replace(base, ts=ts, node=rng.choice(node_names)))
        if cover_nodes and per_minute:
            for _ in range(len(node_names) - len(injected)):
                minute = rng.choice(list(per_minute))
                ts = start + timedelta(minutes=minute, seconds=rng.uniform(0, 60))
                injected.append(replace(rng.choice(incident_pool), ts=ts))
            picked = rng.sample(range(len(injected)), len(node_names))
            for node, index in zip(node_names, picked, strict=True):
                injected[index] = replace(injected[index], node=node)
        records.extend(injected)
        records.sort(key=lambda r: r.ts or start)
        for i, rec in enumerate(records, 1):
            rec.line_no = i

        peak = float(max(per_minute.values(), default=0))
        affected = sorted({r.node for r in injected if r.node})
        if mode.tags:
            stats = tag_stats(((r.label or "", r.node) for r in injected if r.label), self.rubric)
            severity, detail = label_window(stats, self.rubric)
            label_source = "bgl_alert_tags"
        else:
            severity, detail = _policy_severity(mode, len(affected), peak)
            label_source = "scenario_policy"
        end = start + timedelta(minutes=duration_min)
        return Scenario(
            id=f"scn-{mode_key.replace('.', '-')}-{seed}",
            failure_mode=mode.name,
            system=mode.system,
            title=_counted(mode.title, len(affected) or nodes),
            severity=severity,
            lines=[format_raw_line(r) for r in records],
            records=records,
            nodes=affected,
            start=start,
            end=end,
            incident_lines=len(injected),
            peak_rate_per_min=peak,
            runbook=mode.runbook,
            label_source=label_source,
            label_detail=detail,
        )

    # --- console samples ---------------------------------------------------------------------

    def sample(
        self, mode_key: str, *, servers: int | None = None, rate: int | None = None
    ) -> Scenario:
        """The console's sample of a failure mode, at the sizes asked for (or its defaults)."""
        sizes = self.sample_sizes(mode_key)
        if servers is None:
            servers = sizes.servers.default if sizes.servers else SAMPLE_SERVERS
        if rate is None:
            rate = sizes.rate.default if sizes.rate else SAMPLE_RATE
        return self._sample(mode_key, servers, rate)

    def _sample(self, mode_key: str, servers: int, rate: int) -> Scenario:
        scenario = self.build(
            mode_key,
            seed=SAMPLE_SEED,
            nodes=servers,
            duration_min=SAMPLE_MINUTES,
            background_per_min=SAMPLE_BACKGROUND_PER_MIN,
            incident_per_min=float(rate),
            cover_nodes=True,
        )
        card = self.pools.modes[mode_key].card
        return _with_trick(scenario, card.trick) if card and card.trick else scenario

    def sample_sizes(self, mode_key: str) -> SampleSizes:
        """The sizes a visitor may choose for a sample: how many servers, where the logs name
        servers and the count changes the severity, and how fast, where the rate does. A false
        alarm has neither: it needs no action at any size."""
        if mode_key not in self._sizes:
            mode = self.pools.modes[mode_key]
            servers: SizeChoice | None = None
            rate: SizeChoice | None = None
            if not mode.benign:
                named = mode.card is None or mode.card.servers
                if named and (mode.tags or node_visible(mode.system)):
                    servers = self._steps(mode_key, SERVER_STEPS, lambda n: (n, SAMPLE_RATE))
                at = servers.default if servers else SAMPLE_SERVERS
                rate = self._steps(mode_key, RATE_STEPS, lambda n: (at, n))
            self._sizes[mode_key] = SampleSizes(servers, rate)
        return self._sizes[mode_key]

    def _steps(self, mode_key: str, steps: tuple[int, ...], size: Any) -> SizeChoice | None:
        """The smallest of ``steps``, then each step at which the sample becomes more serious; None
        when none does (a choice that changes nothing teaches nothing). A bigger size rated less
        serious is left out: offering it would read as a mistake."""
        kept: list[int] = []
        worst: Severity | None = None
        for n in steps:
            severity = self._rating(self._sample(mode_key, *size(n)))
            if worst is None or severity.rank < worst.rank:
                kept.append(n)
                worst = severity
        return SizeChoice(tuple(kept)) if len(kept) > 1 else None

    def preview(self, mode_key: str, count: int = 3) -> list[str]:
        """A few of the real lines the sample is made of, as the log shows them."""
        seen: list[str] = []
        for rec in self.pools.incident[mode_key]:
            line = format_raw_line(rec)
            if line not in seen:
                seen.append(line)
            if len(seen) == count:
                break
        return seen

    def build_quiet(
        self, system: str, *, seed: int, duration_min: int = 20, background_per_min: float = 30.0
    ) -> Scenario:
        """A window with background traffic only: the SEV4 'nothing is wrong' case."""
        rng = random.Random(f"quiet:{system}:{seed}")
        start = SCENARIO_EPOCH + timedelta(hours=seed % 5000)
        nodes = self._node_names(system, 4, rng)
        records = [
            replace(
                rng.choice(self.pools.background[system]),
                ts=start + timedelta(minutes=m, seconds=rng.uniform(0, 60)),
            )
            for m in range(duration_min)
            for _ in range(_poisson(rng, background_per_min))
        ]
        for rec in records:
            rec.node = rec.node or rng.choice(nodes)
        records.sort(key=lambda r: r.ts or start)
        for i, rec in enumerate(records, 1):
            rec.line_no = i
        return Scenario(
            id=f"scn-quiet-{system}-{seed}",
            failure_mode="none",
            system=system,
            title=f"Routine {system} traffic",
            severity=Severity.SEV4,
            lines=[format_raw_line(r) for r in records],
            records=records,
            nodes=[],
            start=start,
            end=start + timedelta(minutes=duration_min),
            incident_lines=0,
            peak_rate_per_min=0.0,
            runbook=None,
            label_source="scenario_policy",
            label_detail={"policy": "quiet"},
        )

    def suite(self, *, seed: int, per_mode: int = 6, quiet_per_system: int = 2) -> list[Scenario]:
        """A varied benchmark: several scopes and rates per failure mode, plus quiet windows."""
        rng = random.Random(f"suite:{seed}")
        scenarios: list[Scenario] = []
        for key in self.pools.available_modes():
            for j in range(per_mode):
                scenarios.append(
                    self.build(
                        key,
                        seed=seed * 1000 + j,
                        nodes=rng.choice((1, 2, 3, 5, 8, 12, 30)),
                        duration_min=rng.choice((12, 20, 30)),
                        background_per_min=rng.uniform(15, 45),
                        incident_per_min=rng.choice((3.0, 8.0, 20.0, 60.0, 160.0)),
                    )
                )
        systems = sorted({self.pools.modes[k].system for k in self.pools.available_modes()})
        for system in systems:
            for j in range(quiet_per_system):
                scenarios.append(self.build_quiet(system, seed=seed * 1000 + 500 + j))
        return scenarios


def _with_trick(scenario: Scenario, message: str) -> Scenario:
    """The scenario with one more line in the middle of the burst, carrying ``message`` in the
    shape of the failure's own lines (an attacker's text in a field the log records)."""
    burst = [r for r in scenario.records if r.node in scenario.nodes and r.ts is not None]
    if not burst:
        return scenario
    model = burst[len(burst) // 2]
    trick = replace(model, message=message, label=None)
    records = sorted([*scenario.records, trick], key=lambda r: r.ts or scenario.start)
    records = [replace(r, line_no=i) for i, r in enumerate(records, 1)]
    return replace(scenario, records=records, lines=[format_raw_line(r) for r in records])


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method for small rates; normal approximation for large ones."""
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, round(rng.gauss(lam, lam**0.5)))
    limit, k, p = pow(2.718281828459045, -lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1
