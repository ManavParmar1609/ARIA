"""Offline embeddings: LSA fit, persistence without pickle, and the hashing fallback."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from aria.llm.local_embed import HashingEmbedder, LocalEmbeddingProvider, LsaEmbedder, tokenize

CORPUS = [
    "kernel panic on compute node after machine check exception",
    "machine check exception and kernel panic on node rack R02",
    "disk full on storage node, write failed with no space left",
    "no space left on device while writing block to datanode",
    "network link down, packets dropped on torus interconnect",
    "torus link errors and dropped packets between nodes",
    "authentication failure for user, invalid password from host",
]


def test_tokenize_splits_camel_case_and_adds_bigrams() -> None:
    assert tokenize("DataNode writeBlock failed") == [
        "data", "node", "write", "block", "failed", "data_node", "node_write", "write_block", "block_failed",
    ]  # fmt: skip


def test_lsa_puts_related_documents_closer_than_unrelated_ones() -> None:
    model = LsaEmbedder.fit(CORPUS, dims=4)
    vectors = model.transform(["kernel panic machine check", "no space left on disk", *CORPUS])
    query_kernel, query_disk, docs = vectors[0], vectors[1], vectors[2:]
    assert np.argmax(docs @ query_kernel) in (0, 1)
    assert np.argmax(docs @ query_disk) in (2, 3)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_lsa_round_trips_through_npz_without_pickle(tmp_path: Path) -> None:
    model = LsaEmbedder.fit(CORPUS, dims=3)
    path = tmp_path / "embed.npz"
    model.save(path)
    loaded = LsaEmbedder.load(path)
    with np.load(path, allow_pickle=False) as data:
        assert all(data[name].dtype != object for name in data.files)
    assert np.allclose(model.transform(CORPUS), loaded.transform(CORPUS), atol=1e-2)
    assert loaded.dims == 3


def test_lsa_needs_a_real_corpus() -> None:
    with pytest.raises(ValueError, match="at least three"):
        LsaEmbedder.fit(["one doc"])


def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    embedder = HashingEmbedder(dims=64)
    a, b, empty = embedder.transform(["disk full", "disk full", ""])
    assert np.array_equal(a, b)
    assert np.isclose(np.linalg.norm(a), 1.0)
    assert not empty.any()


async def test_provider_uses_fitted_model_when_present(tmp_path: Path) -> None:
    path = tmp_path / "embed_local.npz"
    fallback = LocalEmbeddingProvider(model_path=path)
    assert fallback.model == "hashing-256"
    LsaEmbedder.fit(CORPUS, dims=3).save(path)
    fitted = LocalEmbeddingProvider(model_path=path)
    assert fitted.model.startswith("lsa-3-")
    vectors = await fitted.embed(["kernel panic"], input_type="query")
    assert len(vectors[0]) == 3
    fitted.use(HashingEmbedder(dims=8))
    assert fitted.model == "hashing-8"
