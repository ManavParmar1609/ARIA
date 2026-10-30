"""Offline embeddings, so retrieval works with no API key.

* ``LsaEmbedder``: TF-IDF over words and word bigrams, reduced with truncated SVD (latent
  semantic analysis) and L2-normalised. Fitted on the incident corpus and stored as ``.npz``
  arrays plus a JSON vocabulary: no pickle, so loading a model file cannot run code.
* ``HashingEmbedder``: signed feature hashing into a fixed number of dimensions. It needs no
  fitting and is the fallback before a corpus exists.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy import sparse
from sklearn.decomposition import TruncatedSVD

from aria.config import ProviderKind

_TOKEN = re.compile(r"[a-z][a-z0-9_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
Matrix = NDArray[np.float32]


def tokenize(text: str) -> list[str]:
    words = _TOKEN.findall(_CAMEL.sub(" ", text).lower())
    return words + [f"{a}_{b}" for a, b in itertools.pairwise(words)]


def _l2(matrix: Matrix) -> Matrix:
    """Unit-normalise rows. Rows with (numerically) no signal stay zero instead of becoming noise."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    empty = norms < 1e-6
    norms[empty] = 1.0
    out = (matrix / norms).astype(np.float32)
    out[empty[:, 0]] = 0.0
    return out


class HashingEmbedder:
    def __init__(self, dims: int = 256) -> None:
        self.dims = dims
        self.model_id = f"hashing-{dims}"

    def _slot(self, token: str) -> tuple[int, float]:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        return value % self.dims, 1.0 if (value >> 63) & 1 else -1.0

    def transform(self, texts: Sequence[str]) -> Matrix:
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for row, text in enumerate(texts):
            for token, count in Counter(tokenize(text)).items():
                slot, sign = self._slot(token)
                out[row, slot] += sign * (1.0 + math.log(count))
        return _l2(out)


class LsaEmbedder:
    def __init__(
        self, vocabulary: dict[str, int], idf: NDArray[np.float64], components: Matrix
    ) -> None:
        self.vocabulary = vocabulary
        self.idf = idf
        self.components = components
        fingerprint = hashlib.sha256(components.tobytes()).hexdigest()[:10]
        self.model_id = f"lsa-{components.shape[0]}-{fingerprint}"

    @property
    def dims(self) -> int:
        return int(self.components.shape[0])

    def _tfidf(self, texts: Sequence[str]) -> sparse.csr_matrix:
        rows, cols, vals = [], [], []
        for row, text in enumerate(texts):
            for token, count in Counter(tokenize(text)).items():
                col = self.vocabulary.get(token)
                if col is not None:
                    rows.append(row)
                    cols.append(col)
                    vals.append((1.0 + math.log(count)) * self.idf[col])
        matrix = sparse.csr_matrix((vals, (rows, cols)), shape=(len(texts), len(self.vocabulary)))
        norms = np.sqrt(matrix.multiply(matrix).sum(axis=1)).A1
        norms[norms == 0] = 1.0
        return sparse.csr_matrix(sparse.diags(1.0 / norms) @ matrix)

    def transform(self, texts: Sequence[str]) -> Matrix:
        projected = np.asarray(self._tfidf(texts) @ self.components.T, dtype=np.float32)
        return _l2(projected)

    @classmethod
    def fit(
        cls, corpus: Sequence[str], *, dims: int = 128, max_features: int = 20_000, seed: int = 0
    ) -> LsaEmbedder:
        docs = [set(tokenize(text)) for text in corpus]
        df = Counter(token for doc in docs for token in doc)
        if len(corpus) < 3 or len(df) < 3:
            msg = "LSA needs at least three documents with some shared vocabulary"
            raise ValueError(msg)
        ranked = sorted(df, key=lambda t: (-df[t], t))[:max_features]
        vocabulary = {token: i for i, token in enumerate(sorted(ranked))}
        n = len(corpus)
        idf = np.array(
            [
                math.log((1 + n) / (1 + df[t])) + 1.0
                for t in sorted(vocabulary, key=vocabulary.__getitem__)
            ]
        )
        k = max(1, min(dims, n - 1, len(vocabulary) - 1))
        provisional = cls(vocabulary, idf, np.zeros((k, len(vocabulary)), dtype=np.float32))
        svd = TruncatedSVD(n_components=k, algorithm="randomized", n_iter=7, random_state=seed)
        svd.fit(provisional._tfidf(corpus))
        return cls(vocabulary, idf, svd.components_.astype(np.float32))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        terms = sorted(self.vocabulary, key=self.vocabulary.__getitem__)
        with path.open("wb") as handle:
            np.savez_compressed(
                handle,
                idf=self.idf,
                components=self.components.astype(np.float16),
                vocabulary=np.frombuffer(json.dumps(terms).encode(), dtype=np.uint8),
            )

    @classmethod
    def load(cls, path: Path) -> LsaEmbedder:
        with np.load(path, allow_pickle=False) as data:
            terms = json.loads(data["vocabulary"].tobytes().decode())
            return cls(
                {term: i for i, term in enumerate(terms)},
                data["idf"].astype(np.float64),
                data["components"].astype(np.float32),
            )


class LocalEmbeddingProvider:
    """Embedding provider over a fitted LSA model, or feature hashing when none is fitted."""

    kind = ProviderKind.LOCAL

    def __init__(self, name: str = "local", *, model_path: Path | None = None) -> None:
        self.name = name
        self.model_path = model_path
        self._embedder: LsaEmbedder | HashingEmbedder | None = None

    @property
    def embedder(self) -> LsaEmbedder | HashingEmbedder:
        if self._embedder is None:
            if self.model_path is not None and self.model_path.exists():
                self._embedder = LsaEmbedder.load(self.model_path)
            else:
                self._embedder = HashingEmbedder()
        return self._embedder

    @property
    def model(self) -> str:
        return self.embedder.model_id

    def use(self, embedder: LsaEmbedder | HashingEmbedder) -> None:
        self._embedder = embedder

    async def embed(
        self, texts: Sequence[str], *, input_type: Literal["query", "passage"] = "passage"
    ) -> list[list[float]]:
        del input_type  # symmetric model
        vectors: list[list[float]] = self.embedder.transform(list(texts)).tolist()
        return vectors
