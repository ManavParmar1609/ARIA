"""Similar incidents across three clouds' public post-mortems.

The post-mortems Li et al. collected for "Going through the Life Cycle of Faults in Clouds:
Guidelines on Fault Handling" (ISSRE 2022): public write-ups of AWS, Azure and Google Cloud
incidents from 2011 to 2021, each structured by the researchers with its layered root cause and
the mitigations that ended it. ARIA's retrieval index (BM25 and embeddings fused by reciprocal
rank, as incident memory uses it) holds the post-mortems of incidents before ``CUTOFF``, from
their whole write-ups. Each later one then asks for similar past incidents from its title and
summary of impact, what a responder knows first. A hit is a past incident among the first three
with the same specific root cause (a configuration change, a code change, a flood of requests, a
power outage) or ended by the same kind of fix (a rollback, a hotfix, shifting traffic, adding
capacity). Labels never enter the index or the query.

The researchers wrote each mitigation in their own words ("roll back deployment", "revert
change", "rollback"), so ``FIXES`` sorts them into kinds by the words they use. Baselines on the
same queries: BM25 alone, the embeddings alone, labelled past incidents at random, and always
answering with the commonest label.
"""

from __future__ import annotations

import ast
import json
import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from aria.evals.gitlab import score
from aria.llm.local_embed import LsaEmbedder
from aria.retrieval.hybrid import Document, HybridIndex

POSTMORTEM_DIR = Path("data/raw/cloud-postmortems")
POSTMORTEM_CITATION = (
    "X. Li et al. Going through the Life Cycle of Faults in Clouds: Guidelines on Fault "
    "Handling. ISSRE 2022."
)
MISSING = {"missing": "download it with: aria data download --source cloud-postmortems"}
CLOUDS = {"AWS": "AWS", "Azure": "Azure", "Google": "Google Cloud"}  # by folder
CUTOFF = "2019-01-01"
TOP = 3
MAX_CHARS = 6_000
SEED = 2026
# A root cause the researchers left open says nothing to match on.
_NO_CAUSE = {"", "none", "others", "unknown"}
# The kind of fix, from the words of each mitigation; the first kind that matches wins, so "roll
# back configuration change" is a rollback and "reduce traffic" sheds load.
FIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rollback", ("roll back", "rollback", "rolled back", "revert")),
    ("hotfix", ("hotfix", "hot fix", "fix bug", "fix the bug", "a fix", "patch")),
    ("configuration", ("config",)),
    ("load", ("load", "throttl", "rate limit", "reduce traffic", "limit traffic")),
    ("traffic", ("traffic", "failover", "fail over", "reroute", "redirect", "divert")),
    ("restart", ("restart", "reboot", "recycle")),
    ("capacity", ("capacity", "scale", "add resource", "add more")),
    ("hardware", ("power", "fiber", "hardware", "cooling", "repair", "replace")),
    ("self_healed", ("self heal", "self-heal", "automatically", "auto-recover")),
)


@dataclass(frozen=True)
class PostMortem:
    id: str
    cloud: str  # AWS, Azure or Google
    date: str  # ISO date the incident began
    title: str
    summary: str  # the impact, as the post-mortem opens with it
    details: str
    causes: frozenset[str]  # specific root causes, e.g. "config", "code change"
    fixes: frozenset[str]  # kinds of fix, e.g. "rollback"
    fix_labels: int  # mitigation labels written
    fix_labels_sorted: int  # of those, the ones a kind of fix matched


def _literal(value: Any) -> Any:
    """The fields are Python literals written as strings ("{'label': [...]}")."""
    if not isinstance(value, str):
        return value
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None


def _labels(value: Any) -> list[Any]:
    parsed = _literal(value)
    labels = parsed.get("label") if isinstance(parsed, dict) else None
    if isinstance(labels, dict):
        return [labels]
    return labels if isinstance(labels, list) else []


def fix_kind(mitigation: str) -> str | None:
    text = mitigation.lower()
    return next((kind for kind, words in FIXES if any(w in text for w in words)), None)


def load(root: Path = POSTMORTEM_DIR) -> list[PostMortem]:
    """Every structured post-mortem, oldest first; a write-up filed twice counts once."""
    collection = root / "anomaly_collection"
    out: dict[tuple[str, str, str], PostMortem] = {}
    for path in sorted(collection.rglob("*.json")):
        folder = path.relative_to(collection).parts[0]
        cloud = CLOUDS.get(folder, folder)
        items = json.loads(path.read_text(encoding="utf-8"))
        for key, item in items.items() if isinstance(items, dict) else ():
            try:
                raw = str(item.get("time", "")).strip()
                date = datetime.strptime(raw, "%m/%d/%Y").replace(tzinfo=UTC).date().isoformat()
            except ValueError:
                continue
            title = str(item.get("title") or "").strip()
            mitigations = [m for m in _labels(item.get("mitigation")) if isinstance(m, str)]
            causes = {
                str(c.get("layer-3") or "").strip().lower()
                for c in _labels(item.get("root cause"))
                if isinstance(c, dict)
            }
            out.setdefault(
                (cloud, title, date),
                PostMortem(
                    id=f"{folder}/{key}",
                    cloud=cloud,
                    date=date,
                    title=title,
                    summary=str(item.get("summary") or "").strip(),
                    details=str(item.get("details") or "").strip(),
                    causes=frozenset(causes - _NO_CAUSE),
                    fixes=frozenset(k for m in mitigations if (k := fix_kind(m))),
                    fix_labels=len(mitigations),
                    fix_labels_sorted=sum(1 for m in mitigations if fix_kind(m)),
                ),
            )
    return sorted(out.values(), key=lambda p: (p.date, p.id))


def _hits(ranked: Sequence[frozenset[str]], want: frozenset[str]) -> dict[str, float]:
    first = next((i for i, got in enumerate(ranked) if got & want), None)
    return {
        "hit1": float(first == 0),
        "hit3": float(first is not None and first < TOP),
        "rr": 0.0 if first is None else 1.0 / (first + 1),
    }


def evaluate(
    postmortems: Sequence[PostMortem],
    *,
    cutoff: str = CUTOFF,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    memory = [p for p in postmortems if p.date < cutoff]
    later = [p for p in postmortems if p.date >= cutoff]
    docs = [
        Document(
            p.id,
            f"{p.title}. {p.summary} {p.details}"[:MAX_CHARS],
            {"cause": p.causes, "fix": p.fixes},
        )
        for p in memory
    ]
    if len(docs) < 3:
        return {"missing": f"only {len(docs)} post-mortems before {cutoff}, too few to index"}
    embedder = LsaEmbedder.fit([d.text for d in docs], dims=96)
    vectors = embedder.transform([d.text for d in docs])
    hybrid = HybridIndex(docs, vectors)
    lexical = HybridIndex(docs)
    index_of = {d.id: d for d in docs}
    if progress:
        progress(f"{len(docs):,} past post-mortems indexed; {len(later):,} later ones")
    out: dict[str, Any] = {}
    for key, wanted in (("cause", "causes"), ("fix", "fixes")):
        labelled = [d for d in docs if d.meta[key]]
        queries = [(p, want) for p in later if (want := getattr(p, wanted))]
        tally = Counter(label for d in labelled for label in d.meta[key])
        common = tally.most_common(1)[0][0] if tally else ""
        rng = random.Random(SEED)  # noqa: S311 - a reproducible baseline, not security
        rows: dict[str, list[dict[str, float]]] = {
            k: [] for k in ("aria", "bm25", "embeddings", "random", "commonest_label")
        }

        def has_label(meta: Mapping[str, Any], key: str = key) -> bool:
            return bool(meta[key])

        for postmortem, want in queries:
            text = f"{postmortem.title}. {postmortem.summary}"
            vector = embedder.transform([text])[0]
            for method, index, qv in (("aria", hybrid, vector), ("bm25", lexical, None)):
                ranked = index.search(text, query_vector=qv, candidates=10, where=has_label)
                rows[method].append(_hits([index_of[h.id].meta[key] for h in ranked], want))
            order = [i for i in np.argsort(-(vectors @ vector)) if docs[i].meta[key]][:10]
            rows["embeddings"].append(_hits([docs[i].meta[key] for i in order], want))
            sample = rng.sample(labelled, min(10, len(labelled)))
            rows["random"].append(_hits([d.meta[key] for d in sample], want))
            rows["commonest_label"].append(_hits([frozenset({common})], want))
        out[key] = {
            "labels": len(tally),
            "memory_labelled": len(labelled),
            "commonest": common,
            "label_counts": dict(tally.most_common()),
            "methods": {method: score(r) for method, r in rows.items()},
        }
    fix_labels = sum(p.fix_labels for p in postmortems)
    return {
        "source": "the Post-mortems-Analysis collection (IntelligentDDS)",
        "citation": POSTMORTEM_CITATION,
        "postmortems": len(postmortems),
        "by_cloud": dict(sorted(Counter(p.cloud for p in postmortems).items())),
        "first": postmortems[0].date if postmortems else "",
        "last": postmortems[-1].date if postmortems else "",
        "cutoff": cutoff,
        "memory": len(memory),
        "later": len(later),
        "top": TOP,
        "fix_kinds": [kind for kind, _ in FIXES],
        "fix_labels": fix_labels,
        "fix_labels_sorted": round(
            sum(p.fix_labels_sorted for p in postmortems) / max(1, fix_labels), 4
        ),
        "by": out,
    }


def summarize(root: Path = POSTMORTEM_DIR) -> dict[str, Any]:
    postmortems = load(root)
    if not postmortems:
        return dict(MISSING)
    return evaluate(postmortems)
