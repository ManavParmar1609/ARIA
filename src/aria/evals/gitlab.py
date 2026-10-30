"""Similar incidents on GitLab.com's real incident history.

GitLab runs GitLab.com in the open: its production incidents are public issues, labelled by the
responders with the service that failed (``Service::``) and, after review, the root cause
(``RootCause::``). ARIA's retrieval index (BM25 and embeddings fused by reciprocal rank, as
incident memory uses it) holds the incidents opened before ``CUTOFF``, from their titles and
descriptions. Each later incident then asks for similar past incidents from its title alone, as
a responder would at the start. A hit is a past incident with the same service, or the same root
cause, among the first three. Labels never enter the index or the query.

Baselines on the same queries: BM25 alone, the embeddings alone, three labelled past incidents at
random, and always answering with the commonest label. The issues are a live source: the
download keeps the incidents created before a fixed date and records the snapshot's sha256, but
issues can still be edited later, so a fresh download may differ slightly.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from aria.evals import metrics as m
from aria.llm.local_embed import LsaEmbedder
from aria.retrieval.hybrid import Document, HybridIndex

GITLAB_DIR = Path("data/raw/gitlab-incidents")
CUTOFF = "2023-01-01"
TOP = 3
# Labels that say the field is unknown rather than naming a service or cause.
UNKNOWN = {"Needed", "Indeterminate", "NotNeeded"}
MAX_CHARS = 6_000  # of a description: write-ups run long, and their first part names the problem
SEED = 2026


def label(issue: dict[str, Any], key: str) -> str | None:
    """The issue's ``key::value`` label, or None when it has none or it says 'unknown'."""
    value = next(
        (lab.split("::", 1)[1] for lab in issue.get("labels", []) if lab.startswith(f"{key}::")),
        None,
    )
    return None if value in UNKNOWN else value


def load(gitlab_dir: Path = GITLAB_DIR) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    path = gitlab_dir / "issues.json"
    if not path.exists():
        return None
    snapshot = gitlab_dir / "snapshot.json"
    meta = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.exists() else {}
    issues: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return issues, meta


def _hits(ranked: Sequence[str | None], want: str) -> dict[str, float]:
    first = next((i for i, got in enumerate(ranked) if got == want), None)
    return {
        "hit1": float(first == 0),
        "hit3": float(first is not None and first < TOP),
        "rr": 0.0 if first is None else 1.0 / (first + 1),
    }


def _score(rows: Sequence[dict[str, float]]) -> dict[str, Any]:
    n = len(rows)
    hits = int(sum(r["hit3"] for r in rows))
    return {
        "queries": n,
        "recall_at_1": round(sum(r["hit1"] for r in rows) / max(1, n), 4),
        "recall_at_3": round(hits / max(1, n), 4),
        "recall_at_3_ci95": m.exact_interval(hits, n),
        "mrr_at_10": round(sum(r["rr"] for r in rows) / max(1, n), 4),
    }


def evaluate(
    issues: Sequence[dict[str, Any]],
    meta: dict[str, Any] | None = None,
    *,
    cutoff: str = CUTOFF,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    memory = [i for i in issues if i["created_at"] < cutoff]
    later = [i for i in issues if i["created_at"] >= cutoff]
    docs = [
        Document(
            str(i["iid"]),
            f"{i['title']}. {(i.get('description') or '')[:MAX_CHARS]}",
            {"service": label(i, "Service"), "cause": label(i, "RootCause")},
        )
        for i in memory
    ]
    embedder = LsaEmbedder.fit([d.text for d in docs], dims=96)
    vectors = embedder.transform([d.text for d in docs])
    hybrid = HybridIndex(docs, vectors)
    lexical = HybridIndex(docs)
    if progress:
        progress(f"{len(docs):,} past incidents indexed; {len(later):,} later incidents")
    out: dict[str, Any] = {}
    for key, name in (("service", "Service"), ("cause", "RootCause")):
        labelled = [d for d in docs if d.meta[key]]
        queries = [(i, want) for i in later if (want := label(i, name))]
        common = Counter(d.meta[key] for d in labelled).most_common(1)[0][0] if labelled else ""
        rng = random.Random(SEED)  # noqa: S311 - a reproducible baseline, not security
        rows: dict[str, list[dict[str, float]]] = {
            k: [] for k in ("aria", "bm25", "embeddings", "random", "commonest_label")
        }
        index_of = {d.id: d for d in docs}

        def has_label(meta: Mapping[str, Any], key: str = key) -> bool:
            return bool(meta[key])

        for issue, want in queries:
            title = issue["title"]
            vector = embedder.transform([title])[0]
            for method, index, qv in (("aria", hybrid, vector), ("bm25", lexical, None)):
                ranked = index.search(title, query_vector=qv, candidates=10, where=has_label)
                rows[method].append(_hits([index_of[h.id].meta[key] for h in ranked], want))
            order = [i for i in np.argsort(-(vectors @ vector)) if docs[i].meta[key]][:10]
            rows["embeddings"].append(_hits([docs[i].meta[key] for i in order], want))
            rows["random"].append(
                _hits([d.meta[key] for d in rng.sample(labelled, min(10, len(labelled)))], want)
            )
            rows["commonest_label"].append(_hits([common], want))
        out[key] = {
            "labels": len({d.meta[key] for d in labelled}),
            "memory_labelled": len(labelled),
            "commonest": common,
            "methods": {method: _score(r) for method, r in rows.items()},
        }
    return {
        "source": "GitLab.com production incidents (gitlab-com/gl-infra/production)",
        "citation": "GitLab Inc., GitLab.com production incident tracker (public issues).",
        "snapshot": meta or {},
        "incidents": len(issues),
        "cutoff": cutoff,
        "memory": len(memory),
        "later": len(later),
        "top": TOP,
        "by": out,
    }


def summarize(gitlab_dir: Path = GITLAB_DIR) -> dict[str, Any]:
    loaded = load(gitlab_dir)
    if loaded is None:
        return {"missing": "download it with: aria data download --source gitlab-incidents"}
    return evaluate(*loaded)
