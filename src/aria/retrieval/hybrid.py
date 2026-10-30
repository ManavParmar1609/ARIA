"""Hybrid search: BM25 plus dense embeddings, fused with reciprocal-rank fusion.

BM25 catches exact error strings and identifiers; embeddings catch paraphrases. Reciprocal-rank
fusion (Cormack et al., 2009) combines the two rankings without tuning score scales:
``score(d) = sum over rankings of 1 / (k + rank(d))``.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from aria.llm.local_embed import tokenize

Vector = NDArray[np.float32]


class BM25:
    """Okapi BM25 over an inverted index (k1=1.5, b=0.75)."""

    def __init__(
        self, documents: Sequence[Sequence[str]], *, k1: float = 1.5, b: float = 0.75
    ) -> None:
        self.k1, self.b = k1, b
        self.n = len(documents)
        self.lengths = np.array([len(doc) for doc in documents], dtype=np.float64)
        self.avg_len = float(self.lengths.mean()) if self.n else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, doc in enumerate(documents):
            for term, tf in Counter(doc).items():
                self.postings[term].append((i, tf))
        self.idf = {
            term: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5))
            for term, p in self.postings.items()
        }

    def scores(self, query: Sequence[str]) -> NDArray[np.float64]:
        out = np.zeros(self.n, dtype=np.float64)
        if not self.n:
            return out
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in self.postings[term]:
                norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg_len or 1))
                out[i] += idf * tf * (self.k1 + 1) / norm
        return out

    def max_score(self, query: Sequence[str]) -> float:
        """Upper bound of a document's score for this query (every term at saturation)."""
        return sum(self.idf.get(t, 0.0) * (self.k1 + 1) for t in set(query))


@dataclass
class Document:
    id: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    id: str
    score: float  # fused RRF score
    lexical: float  # BM25 score normalised by the query's maximum (0..1)
    dense: float  # cosine similarity (-1..1); 0 when no embeddings
    lexical_rank: int | None
    dense_rank: int | None
    meta: dict[str, Any]
    rerank: float | None = None


class HybridIndex:
    def __init__(
        self,
        documents: Sequence[Document],
        vectors: Vector | None = None,
        *,
        embedding_model: str | None = None,
        rrf_k: int = 60,
    ) -> None:
        self.documents = list(documents)
        self.tokens = [tokenize(doc.text) for doc in self.documents]
        self.bm25 = BM25(self.tokens)
        if vectors is not None and len(vectors) != len(self.documents):
            msg = "one vector per document is required"
            raise ValueError(msg)
        self.vectors = vectors
        self.embedding_model = embedding_model
        self.rrf_k = rrf_k

    def __len__(self) -> int:
        return len(self.documents)

    def search(
        self,
        query: str,
        *,
        query_vector: Vector | None = None,
        candidates: int = 12,
        where: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> list[Hit]:
        if not self.documents:
            return []
        q_tokens = tokenize(query)
        allowed = np.array(
            [where(doc.meta) if where else True for doc in self.documents], dtype=bool
        )
        lexical = self.bm25.scores(q_tokens)
        ceiling = self.bm25.max_score(q_tokens) or 1.0
        lex_order = [
            int(i) for i in np.argsort(-lexical, kind="stable") if allowed[i] and lexical[i] > 0
        ]
        dense: NDArray[np.float64] = np.zeros(len(self.documents))
        dense_order: list[int] = []
        if self.vectors is not None and query_vector is not None:
            dense = np.asarray(self.vectors @ query_vector, dtype=np.float64)
            dense_order = [
                int(i) for i in np.argsort(-dense, kind="stable") if allowed[i] and dense[i] > 0
            ]
        fused: dict[int, float] = defaultdict(float)
        lex_rank = {i: r for r, i in enumerate(lex_order[: candidates * 3], 1)}
        dense_rank = {i: r for r, i in enumerate(dense_order[: candidates * 3], 1)}
        for i, rank in lex_rank.items():
            fused[i] += 1.0 / (self.rrf_k + rank)
        for i, rank in dense_rank.items():
            fused[i] += 1.0 / (self.rrf_k + rank)
        ranked = sorted(fused, key=lambda i: (-fused[i], i))[:candidates]
        return [
            Hit(
                id=self.documents[i].id,
                score=round(fused[i], 6),
                lexical=round(float(min(1.0, lexical[i] / ceiling)), 4),
                dense=round(float(dense[i]), 4),
                lexical_rank=lex_rank.get(i),
                dense_rank=dense_rank.get(i),
                meta=self.documents[i].meta,
            )
            for i in ranked
        ]
