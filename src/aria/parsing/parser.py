"""The Parser agent's deterministic core, written as map (shards) and reduce (merge).

Map: each shard is guarded (line caps), scanned for prompt injection, redacted, parsed with the
system's line format and template-mined with Drain.
Reduce: shard templates are unified with a second Drain pass over the templates themselves, then
template statistics, window features and evidence are computed over all lines.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aria.config import GuardrailConfig
from aria.contracts.base import EvidenceKind
from aria.contracts.parsing import (
    GuardReport,
    InjectionFinding,
    LogEvent,
    ParsedBatch,
    RedactionSummary,
    TemplateStat,
)
from aria.data.loghub import LogRecord, parse_raw_line
from aria.evidence import EvidenceStore
from aria.parsing.drain import Drain, drain_for, template_id
from aria.parsing.features import ERROR_LEVELS, FeatureInput, compute_features
from aria.parsing.signals import WARN, line_rank
from aria.security.injection import scan_line
from aria.security.redaction import Redactor, new_salt

MAX_TEMPLATE_EVIDENCE = 12
MAX_LINE_EVIDENCE = 15
MAX_INJECTION_EVIDENCE = 5
QUARANTINE_FLAG = "injection_suspect"
QUARANTINE_TEMPLATE = "<quarantined: possible prompt injection>"


@dataclass(slots=True)
class ParsedLine:
    idx: int
    record: LogRecord
    shard_template: str
    template: str = ""
    template_id: str = ""
    flags: list[str] = field(default_factory=list)


@dataclass
class ShardResult:
    system: str
    offset: int
    lines: list[ParsedLine]
    injections: list[InjectionFinding]
    redactions: dict[str, int]
    pseudonyms: set[str]
    truncated: int
    dropped: int


@dataclass
class ParseOutput:
    batch: ParsedBatch
    lines: list[ParsedLine]  # analysed lines; quarantined ones are excluded
    evidence_ids: list[str]
    quarantined: list[ParsedLine] = field(default_factory=list)


def split_shards(lines: Sequence[str], shards: int) -> list[tuple[int, list[str]]]:
    shards = max(1, min(shards, len(lines) or 1))
    size = -(-len(lines) // shards) if lines else 0
    return (
        [(i, list(lines[i : i + size])) for i in range(0, len(lines), size)] if size else [(0, [])]
    )


def parse_shard(
    lines: Sequence[str],
    *,
    system: str,
    offset: int,
    guard: GuardrailConfig,
    salt: bytes,
    dropped: int = 0,
) -> ShardResult:
    redactor = Redactor(pseudonymize_ips=guard.pseudonymize_ips, salt=salt)
    drain = drain_for(system)
    parsed: list[ParsedLine] = []
    injections: list[InjectionFinding] = []
    truncated = 0
    for i, raw in enumerate(lines):
        idx = offset + i
        line_text = raw
        if len(line_text) > guard.max_line_chars:
            line_text, truncated = line_text[: guard.max_line_chars], truncated + 1
        flags: list[str] = []
        if guard.detect_injection and (finding := scan_line(line_text, idx)) is not None:
            injections.append(finding)
            flags.append(QUARANTINE_FLAG)
        text = redactor.redact(line_text) if guard.redact_pii else line_text
        if text != line_text:
            flags.append("redacted")
        record = parse_raw_line(system, text, idx + 1)
        if QUARANTINE_FLAG in flags:
            # Quarantined lines never reach the template miner, so they cannot reshape the
            # templates (or the features) computed from the genuine lines.
            parsed.append(
                ParsedLine(idx=idx, record=record, shard_template=QUARANTINE_TEMPLATE, flags=flags)
            )
            continue
        cluster = drain.add(record.message)
        parsed.append(
            ParsedLine(idx=idx, record=record, shard_template=str(id(cluster)), flags=flags)
        )
    # Resolve shard-local cluster references to final shard templates.
    final = {str(id(c)): c.template for c in drain.clusters}
    for line in parsed:
        line.shard_template = final.get(line.shard_template, line.shard_template)
    return ShardResult(
        system,
        offset,
        parsed,
        injections,
        dict(redactor.counts),
        set(redactor.pseudonyms),
        truncated,
        dropped,
    )


def _unify_templates(
    shards: Sequence[ShardResult], system: str, known_templates: Iterable[str]
) -> tuple[dict[str, str], set[str]]:
    """Map shard templates to merged templates; return the set of novel template ids."""
    merger: Drain = drain_for(system)
    shard_templates = sorted(
        {line.shard_template for shard in shards for line in shard.lines} - {QUARANTINE_TEMPLATE}
    )
    owners = {t: merger.add(t) for t in shard_templates}
    mapping = {t: c.template for t, c in owners.items()}
    mapping[QUARANTINE_TEMPLATE] = QUARANTINE_TEMPLATE
    known = drain_for(system)
    known.seed(known_templates)
    novel = (
        {
            template_id(system, t)
            for t in set(mapping.values()) - {QUARANTINE_TEMPLATE}
            if known.match(t) is None
        }
        if known.clusters
        else set()
    )
    return mapping, novel


def merge_shards(
    shards: Sequence[ShardResult],
    *,
    system: str,
    evidence: EvidenceStore,
    known_templates: Iterable[str] = (),
    context_lines: int = 120,
    n_raw_lines: int | None = None,
) -> ParseOutput:
    history = sorted(set(known_templates))
    mapping, novel_ids = _unify_templates(shards, system, history)
    every_line = sorted(
        (line for shard in shards for line in shard.lines), key=lambda line: line.idx
    )
    for line in every_line:
        line.template = mapping[line.shard_template]
        line.template_id = template_id(system, line.template)
    quarantined = [line for line in every_line if QUARANTINE_FLAG in line.flags]
    lines = [line for line in every_line if QUARANTINE_FLAG not in line.flags]

    features = compute_features(
        [
            FeatureInput(
                pl.record.ts,
                pl.record.node,
                pl.record.component,
                pl.record.level,
                pl.record.message,
                pl.template_id,
            )
            for pl in lines
        ],
        system=system,
        novel_template_ids=novel_ids,
    )

    by_template: dict[str, list[ParsedLine]] = defaultdict(list)
    for line in lines:
        by_template[line.template_id].append(line)

    evidence_ids: list[str] = []
    window = evidence.add(
        EvidenceKind.FEATURE,
        f"{features.n_events} events, {features.error_events} errors ({features.error_ratio:.1%}) over {features.duration_s / 60:.1f} min",
        source="parser",
        detail=f"{features.n_templates} templates; {features.events_per_min:.1f} events/min; levels {features.level_counts}",
        data=features.model_dump(
            include={
                "n_events",
                "error_events",
                "error_ratio",
                "duration_s",
                "events_per_min",
                "n_templates",
                "level_counts",
            }
        ),
    )
    evidence_ids.append(window)
    if features.burst_score > 0:
        evidence_ids.append(
            evidence.add(
                EvidenceKind.FEATURE,
                f"Error burst: peak {features.peak_errors_per_min:.0f} errors/min (burst score {features.burst_score:.1f})",
                source="parser",
                data={
                    "burst_score": features.burst_score,
                    "peak_errors_per_min": features.peak_errors_per_min,
                    "persistence_s": features.persistence_s,
                },
            )
        )
    if features.error_nodes:
        evidence_ids.append(
            evidence.add(
                EvidenceKind.FEATURE,
                f"Errors on {features.error_nodes} of {features.distinct_nodes} nodes",
                source="parser",
                data={
                    "error_nodes": features.error_nodes,
                    "distinct_nodes": features.distinct_nodes,
                    "node_spread": features.node_spread,
                    "critical_components": features.critical_components,
                },
            )
        )

    if features.warn_nodes:
        evidence_ids.append(
            evidence.add(
                EvidenceKind.FEATURE,
                f"Warnings on {features.warn_nodes} of {features.distinct_nodes} nodes",
                source="parser",
                data={
                    "warn_nodes": features.warn_nodes,
                    "distinct_nodes": features.distinct_nodes,
                    "peak_warnings_per_min": features.peak_warnings_per_min,
                },
            )
        )

    def error_count(tid: str) -> int:
        return sum(1 for pl in by_template[tid] if pl.record.level in ERROR_LEVELS)

    def warning_count(tid: str) -> int:
        return sum(1 for pl in by_template[tid] if pl.record.level == WARN)

    def new_warnings(tid: str) -> int:
        # Without a history to judge novelty against, every warning may be the news.
        return warning_count(tid) if tid in novel_ids or not history else 0

    def rank(tid: str) -> tuple[int, ...]:
        # Errors first, then warnings the history has never shown, then other warnings.
        novel = tid in novel_ids
        return (
            -error_count(tid),
            -new_warnings(tid),
            -warning_count(tid),
            -novel,
            -len(by_template[tid]),
        )

    ranked = sorted(by_template, key=rank)
    templates: list[TemplateStat] = []
    template_evidence = 0
    for tid in ranked:
        members = by_template[tid]
        levels = Counter(pl.record.level or "UNKNOWN" for pl in members)
        stamps = [pl.record.ts for pl in members if pl.record.ts]
        error_like = any(pl.record.level in ERROR_LEVELS for pl in members)
        new_warning = new_warnings(tid) > 0
        components = Counter(pl.record.component for pl in members if pl.record.component)
        ev_id = ""
        if template_evidence < MAX_TEMPLATE_EVIDENCE and (
            error_like or new_warning or template_evidence < 3
        ):
            ev_id = evidence.add(
                EvidenceKind.TEMPLATE,
                f"{len(members)}x {members[0].template[:140]}",
                source="parser",
                detail=f"example: {members[0].record.message[:400]}",
                data={
                    "template_id": tid,
                    "count": len(members),
                    "levels": dict(levels),
                    "nodes": len({pl.record.node for pl in members if pl.record.node}),
                    "novel": tid in novel_ids,
                },
                ts=min(stamps) if stamps else None,
            )
            evidence_ids.append(ev_id)
            template_evidence += 1
        templates.append(
            TemplateStat(
                template_id=tid,
                template=members[0].template,
                count=len(members),
                levels=dict(levels),
                nodes=len({pl.record.node for pl in members if pl.record.node}),
                first_ts=min(stamps) if stamps else None,
                last_ts=max(stamps) if stamps else None,
                error_like=error_like,
                novel=tid in novel_ids,
                components=[c for c, _ in components.most_common(3)],
                sample_idx=[pl.idx for pl in members[:5]],
                evidence_id=ev_id or window,
            )
        )

    def strength(pl: ParsedLine) -> int:
        return line_rank(pl.record.level, novel=pl.template_id in novel_ids)

    signal = [by_template[tid] for tid in ranked if error_count(tid) or new_warnings(tid)][
        :MAX_LINE_EVIDENCE
    ]
    for members in signal:
        line = min(members, key=lambda pl: (strength(pl), pl.idx))  # first error, else warning
        evidence_ids.append(
            evidence.add(
                EvidenceKind.LOG,
                f"line {line.idx + 1}: {line.record.message[:150]}",
                source="parser",
                detail=line.record.message[:1000],
                data={
                    "line": line.idx + 1,
                    "node": line.record.node,
                    "component": line.record.component,
                    "level": line.record.level,
                    "template_id": line.template_id,
                },
                ts=line.record.ts,
            )
        )
    injections = [f for shard in shards for f in shard.injections]
    for finding in injections[:MAX_INJECTION_EVIDENCE]:
        evidence_ids.append(  # noqa: PERF401 - evidence.add allocates ids in order
            evidence.add(
                EvidenceKind.LOG,
                f"Possible prompt injection in line {finding.line_idx + 1}",
                source="guardrail",
                detail=finding.excerpt,
                data={
                    "line": finding.line_idx + 1,
                    "patterns": finding.pattern,
                    "score": finding.score,
                },
            )
        )

    # Context for reviewers and agents: errors, then new warnings, warnings, other new lines and
    # the rest, each group in log order. (Redaction flags say nothing about the problem.)
    keep = sorted(lines, key=lambda pl: (strength(pl), pl.idx))[:context_lines]
    keep += quarantined[:MAX_INJECTION_EVIDENCE]  # shown to reviewers, flagged, never analysed
    keep.sort(key=lambda pl: pl.idx)
    redactions: Counter[str] = Counter()
    for shard in shards:
        redactions.update(shard.redactions)
    batch = ParsedBatch(
        system=system,
        n_raw_lines=n_raw_lines if n_raw_lines is not None else len(lines),
        events=[
            LogEvent(
                idx=pl.idx,
                line_no=pl.record.line_no,
                ts=pl.record.ts,
                node=pl.record.node,
                component=pl.record.component,
                level=pl.record.level,
                message=pl.record.message[:2_000],
                template_id=pl.template_id,
                flags=pl.flags,
            )
            for pl in keep
        ],
        templates=templates,
        features=features,
        guard=GuardReport(
            redactions=RedactionSummary(
                counts=dict(redactions),
                pseudonyms=len(set().union(*(s.pseudonyms for s in shards))),
            ),
            injections=injections,
            truncated_lines=sum(s.truncated for s in shards),
            dropped_lines=sum(s.dropped for s in shards),
        ),
        shards=len(shards),
        template_history=len(history),
    )
    return ParseOutput(batch=batch, lines=lines, evidence_ids=evidence_ids, quarantined=quarantined)


def parse_lines(
    raw_lines: Sequence[str],
    *,
    system: str,
    guard: GuardrailConfig,
    evidence: EvidenceStore,
    known_templates: Iterable[str] = (),
    context_lines: int = 120,
    shards: int = 1,
    salt: bytes | None = None,
) -> ParseOutput:
    """Parse a batch in-process (the graph fans the same steps out with Send).

    ``salt`` keys the pseudonyms; pass a fixed value only for reproducible evaluations.
    """
    dropped = max(0, len(raw_lines) - guard.max_lines)
    capped = list(raw_lines[: guard.max_lines])
    salt = salt or new_salt()  # one key per run, shared by every shard, so pseudonyms agree
    results = [
        parse_shard(
            chunk,
            system=system,
            offset=offset,
            guard=guard,
            salt=salt,
            dropped=dropped if offset == 0 else 0,
        )
        for offset, chunk in split_shards(capped, shards)
    ]
    return merge_shards(
        results,
        system=system,
        evidence=evidence,
        known_templates=known_templates,
        context_lines=context_lines,
        n_raw_lines=len(raw_lines),
    )


# --- shard transport (graph fan-out) -------------------------------------------------------------


def shard_to_payload(shard: ShardResult) -> dict[str, Any]:
    """A JSON-shaped shard result, so parallel graph workers can return it through state."""
    return {
        "system": shard.system,
        "offset": shard.offset,
        "lines": [
            {
                "idx": line.idx,
                "shard_template": line.shard_template,
                "flags": line.flags,
                "line_no": line.record.line_no,
                "message": line.record.message,
                "ts": line.record.ts.isoformat() if line.record.ts else None,
                "node": line.record.node,
                "component": line.record.component,
                "level": line.record.level,
                "level_raw": line.record.level_raw,
            }
            for line in shard.lines
        ],
        "injections": [f.model_dump() for f in shard.injections],
        "redactions": shard.redactions,
        "pseudonyms": sorted(shard.pseudonyms),
        "truncated": shard.truncated,
        "dropped": shard.dropped,
    }


def shard_from_payload(data: dict[str, Any]) -> ShardResult:
    lines = [
        ParsedLine(
            idx=int(item["idx"]),
            record=LogRecord(
                system=data["system"],
                line_no=int(item["line_no"]),
                message=item["message"],
                ts=datetime.fromisoformat(item["ts"]) if item.get("ts") else None,
                node=item.get("node"),
                component=item.get("component"),
                level=item.get("level"),
                level_raw=item.get("level_raw"),
            ),
            shard_template=item["shard_template"],
            flags=list(item.get("flags") or []),
        )
        for item in data["lines"]
    ]
    return ShardResult(
        system=data["system"],
        offset=int(data["offset"]),
        lines=lines,
        injections=[InjectionFinding.model_validate(f) for f in data.get("injections", [])],
        redactions=dict(data.get("redactions") or {}),
        pseudonyms=set(data.get("pseudonyms") or []),
        truncated=int(data.get("truncated", 0)),
        dropped=int(data.get("dropped", 0)),
    )
