"""The injection guard against public prompt-injection benchmarks it was never tuned on.

The edge-case suite measures the guard on attacks this project wrote, so its recall is an upper
bound. Here the attacks come from others: BIPIA's and InjecAgent's indirect injections (text an
attacker plants where a model will read it), Meta's CyberSecEval 2 prompt-injection cases, the
hijacking attacks Tensor Trust players wrote, a curated collection from Giskard, and jailbreak
prompts collected in the wild. Each attack is flattened to one line, hidden in the same carriers
as the edge-case suite (a message, a username, a request path, a user agent, a job error) in a
system's own log format, and parsed by the production parser on its own.

Over-defence is measured the same way on NotInject: benign sentences that use the words
injections use ("ignore", "override"). And every real log line the other evaluations read (the
Loghub samples, the HDFS cut, the full BGL log, the Hadoop jobs) is scanned exactly as the
parser scans it, to count false alarms on real traffic.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.data.loghub import format_raw_line, iter_structured_csv
from aria.evals import metrics as m
from aria.evals.edge import SYSTEMS, _carrier, _render
from aria.evidence import EvidenceStore
from aria.parsing.parser import parse_lines
from aria.security.fields import sanitize
from aria.security.injection import scan_line

RAW = Path("data/raw")
SEED = 2027


@dataclass(frozen=True)
class Text:
    source: str
    group: str
    text: str


def _flat(text: str) -> str:
    return " ".join(text.split())


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def attacks(raw: Path = RAW) -> dict[str, list[Text]]:
    """Every downloaded benchmark's attacks, by source; a source not downloaded is left out."""
    out: dict[str, list[Text]] = {}
    bipia = raw / "bipia" / "benchmark"
    if (bipia / "text_attack_test.json").exists():
        out["bipia"] = [
            Text("bipia", f"{kind}: {group}", _flat(text))
            for kind in ("text", "code")
            for group, texts in _json(bipia / f"{kind}_attack_test.json").items()
            for text in texts
        ]
    injecagent = raw / "injecagent" / "data"
    if (injecagent / "attacker_cases_dh.jsonl").exists():
        out["injecagent"] = [
            Text("injecagent", kind, _flat(row["Attacker Instruction"]))
            for kind, name in (("direct harm", "dh"), ("data stealing", "ds"))
            for row in _jsonl(injecagent / f"attacker_cases_{name}.jsonl")
        ]
    cse = raw / "cyberseceval-pi" / "CybersecurityBenchmarks" / "datasets" / "prompt_injection"
    if (cse / "prompt_injection.json").exists():
        out["cyberseceval"] = [
            Text(
                "cyberseceval",
                "English" if row.get("speaking_language", "English") == "English" else "other",
                _flat(row["user_input"]),
            )
            for row in _json(cse / "prompt_injection.json")
        ]
    tensor = raw / "tensor-trust" / "benchmarks" / "hijacking-robustness" / "v1"
    if (tensor / "hijacking_robustness_dataset.jsonl").exists():
        out["tensor_trust"] = [
            Text("tensor_trust", "hijacking", _flat(row["attack"]))
            for row in _jsonl(tensor / "hijacking_robustness_dataset.jsonl")
            if row.get("attack", "").strip()
        ]
    giskard = raw / "giskard-injections" / "prompt_injections.csv"
    if giskard.exists():
        with giskard.open(encoding="utf-8", newline="") as handle:
            out["giskard"] = [
                Text("giskard", row.get("group") or "other", _flat(row["prompt"]))
                for row in csv.DictReader(handle)
            ]
    jailbreak = raw / "jailbreak-llms" / "data" / "prompts" / "jailbreak_prompts_2023_12_25.csv"
    if jailbreak.exists():
        csv.field_size_limit(1 << 24)
        with jailbreak.open(encoding="utf-8", newline="") as handle:
            out["jailbreaks"] = [
                Text("jailbreaks", row.get("platform") or "other", _flat(row["prompt"]))
                for row in csv.DictReader(handle)
                if row.get("jailbreak", "True") == "True" and row["prompt"].strip()
            ]
    return out


def benign(raw: Path = RAW) -> list[Text]:
    """NotInject's benign sentences, grouped by how many injection words each one uses."""
    root = raw / "notinject" / "datasets"
    return [
        Text(
            "notinject",
            f"{count} trigger word{'s' if count != 'one' else ''}",
            _flat(row["prompt"]),
        )
        for count in ("one", "two", "three")
        if (root / f"NotInject_{count}.json").exists()
        for row in _json(root / f"NotInject_{count}.json")
    ]


def _flagged(items: Sequence[Text], *, seed: int) -> list[bool]:
    """Each text hidden in a log carrier and parsed on its own, as the edge-case suite does."""
    rng = random.Random(seed)  # noqa: S311 - a reproducible corpus, not security
    guard = GuardrailConfig()
    out = []
    for i, item in enumerate(items):
        system = rng.choice(SYSTEMS)
        line = _render(rng, system, _carrier(rng, item.text), i)
        parsed = parse_lines([line], system=system, guard=guard, evidence=EvidenceStore())
        out.append(bool(parsed.batch.guard.injections))
    return out


def _rate(hits: int, n: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "n": n,
        "flagged": hits,
        "rate": round(hits / max(1, n), 4),
        "ci95": m.exact_interval(hits, n),
    }
    if hits == 0 and n:
        # The exact 95% upper bound for none in n, as "one in": too small to round to a rate.
        out["upper_one_in"] = round(1 / (1 - 0.025 ** (1 / n)))
    return out


def _real_lines(raw: Path) -> Iterator[tuple[str, Iterable[str]]]:
    """The real log corpora the other evaluations read, as raw lines (the parsing evaluation
    counts its own flags on the Loghub samples)."""
    hdfs = next(raw.glob("hdfs-100k/**/HDFS_100k.log_structured.csv"), None)
    if hdfs is not None:
        yield "hdfs", (format_raw_line(r) for r in iter_structured_csv("hdfs", hdfs))
    bgl = next((p for p in (raw / "loghub-bgl").rglob("BGL.log") if p.is_file()), None)
    if bgl is not None:
        with bgl.open(encoding="utf-8", errors="replace") as handle:
            yield "bgl", handle
    hadoop = sorted((raw / "loghub-hadoop").rglob("container_*.log"))
    if hadoop:
        yield (
            "hadoop",
            (
                line
                for path in hadoop
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            ),
        )


def scan_real(raw: Path = RAW) -> dict[str, dict[str, Any]]:
    """False alarms on real traffic: each line scanned exactly as the parser scans it."""
    cap = GuardrailConfig().max_line_chars
    out: dict[str, dict[str, Any]] = {}
    for name, lines in _real_lines(raw):
        n = hits = 0
        examples: list[str] = []
        for i, raw_line in enumerate(lines):
            line = sanitize(raw_line.rstrip("\n"))[:cap]
            n += 1
            if scan_line(line, i) is not None:
                hits += 1
                if len(examples) < 3:
                    examples.append(line[:160])
        out[name] = {**_rate(hits, n), "examples": examples}
    return out


def evaluate(raw: Path = RAW, *, real_lines: bool = True) -> dict[str, Any]:
    found = attacks(raw)
    if not found:
        return {
            "missing": "download the benchmarks with: aria data download (see data/manifest.yaml)"
        }
    by_source: dict[str, Any] = {}
    for offset, (source, items) in enumerate(sorted(found.items())):
        flags = _flagged(items, seed=SEED + offset)
        groups: Counter[str] = Counter(i.group for i in items)
        hits: Counter[str] = Counter(i.group for i, f in zip(items, flags, strict=True) if f)
        by_source[source] = {
            **_rate(sum(flags), len(items)),
            "groups": {g: _rate(hits[g], n) for g, n in sorted(groups.items())},
            "missed_examples": [i.text[:160] for i, f in zip(items, flags, strict=True) if not f][
                :3
            ],
        }
    harmless = benign(raw)
    flags = _flagged(harmless, seed=SEED + 100)
    groups = Counter(i.group for i in harmless)
    hits = Counter(i.group for i, f in zip(harmless, flags, strict=True) if f)
    every = [t for items in found.values() for t in items]
    caught = sum(v["flagged"] for v in by_source.values())
    return {
        "attacks": _rate(caught, len(every)),
        "by_source": by_source,
        "benign": {
            **_rate(sum(flags), len(harmless)),
            # In the order NotInject builds them: one, two, then three trigger words.
            "groups": {g: _rate(hits[g], n) for g, n in groups.items()},
            "examples": [i.text[:160] for i, f in zip(harmless, flags, strict=True) if f][:3],
        }
        if harmless
        else None,
        "real_lines": scan_real(raw) if real_lines else None,
        "systems": list(SYSTEMS),
    }
