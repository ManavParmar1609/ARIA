"""Runbooks, hybrid search, incident memory, ticket history and agentic retrieval."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import insert

from aria.config import GuardrailConfig, RetrievalConfig
from aria.contracts.base import EvidenceKind, Severity
from aria.contracts.inputs import TicketContext
from aria.contracts.retrieval import Hypothesis
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db.engine import get_engine, init_db, session_scope
from aria.db.models import ItsmIncidentRow
from aria.evidence import EvidenceStore
from aria.llm.local_embed import HashingEmbedder, LocalEmbeddingProvider
from aria.parsing.parser import parse_lines
from aria.retrieval.hybrid import BM25, Document, HybridIndex
from aria.retrieval.memory import IncidentMemory, MemoryIncident
from aria.retrieval.retriever import Retriever, build_query, deterministic_rewrite, grade_hits
from aria.retrieval.runbooks import load_runbooks, parse_runbook, sync_runbooks
from aria.retrieval.seed import incident_from_scenario
from aria.retrieval.tickets import ticket_history

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"


@pytest.fixture(scope="module")
def builder() -> ScenarioBuilder:
    return ScenarioBuilder(LinePools.from_loghub(FIXTURES))


@pytest.fixture(scope="module")
def seeded(builder: ScenarioBuilder) -> list[MemoryIncident]:
    runbooks = load_runbooks(Path("runbooks"))
    incidents = []
    for i, mode in enumerate(builder.pools.available_modes()):
        for seed in (1, 2):
            scenario = builder.build(
                mode,
                seed=500 + 10 * i + seed,
                nodes=3,
                duration_min=6,
                background_per_min=6,
                incident_per_min=8,
            )
            incidents.append(incident_from_scenario(scenario, runbooks))
    return incidents


@pytest.fixture
async def memory(seeded: list[MemoryIncident]) -> IncidentMemory:
    engine = get_engine()
    init_db(engine)
    store = IncidentMemory(engine, LocalEmbeddingProvider(model_path=None))
    await store.bulk_insert(seeded)
    return store


# --- runbooks ----------------------------------------------------------------------------------


def test_repo_runbooks_parse_with_risk_tags() -> None:
    runbooks = load_runbooks(Path("runbooks"))
    assert len(runbooks) >= 18
    assert "generic-triage" in runbooks
    quorum = runbooks["zookeeper-quorum-loss"]
    assert quorum.risk == "high"
    assert any(step.risk == "high" for step in quorum.mitigate)
    assert quorum.matches("zookeeper", "quorum_connection_loss")
    assert not quorum.matches("bgl", "quorum_connection_loss")
    # every failure mode in the scenario catalog that names a runbook has one
    from aria.data.scenarios import load_catalog

    missing = {
        m.runbook for m in load_catalog().values() if m.runbook and m.runbook not in runbooks
    }
    assert not missing


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no front matter", "front matter"),
        ("---\nslug: x\ntitle: t\n---\n## Mitigate\n", "front matter needs failure_modes"),
        ("---\nslug: x\ntitle: t\nfailure_modes: [a]\n---\n## Diagnose\n1. look\n", "Mitigate"),
        (
            "---\nslug: x\ntitle: t\nfailure_modes: [a]\nrisk: extreme\n---\n## Mitigate\n1. do\n",
            "risk must be",
        ),
    ],
)
def test_bad_runbooks_fail_loudly(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_runbook(text, path="x.md")


def test_runbooks_sync_to_the_database() -> None:
    engine = get_engine()
    init_db(engine)
    assert sync_runbooks(engine, load_runbooks(Path("runbooks"))) >= 18


# --- hybrid search -----------------------------------------------------------------------------


def test_bm25_prefers_documents_with_rare_query_terms() -> None:
    docs = [["disk", "full", "node"], ["kernel", "panic", "node"], ["node", "ok"]]
    scores = BM25(docs).scores(["kernel", "panic"])
    assert int(np.argmax(scores)) == 1
    assert scores[2] == 0


def test_hybrid_index_fuses_rankings_and_filters() -> None:
    docs = [
        Document("a", "kernel panic stopping execution on compute node", {"system": "bgl"}),
        Document("b", "disk full no space left on device", {"system": "hdfs"}),
        Document("c", "kernel terminated after machine check", {"system": "bgl"}),
    ]
    embedder = HashingEmbedder(64)
    index = HybridIndex(docs, embedder.transform([d.text for d in docs]))
    query = "kernel panic"
    hits = index.search(query, query_vector=embedder.transform([query])[0], candidates=3)
    assert hits[0].id == "a"
    assert hits[0].lexical_rank == 1
    assert 0 < hits[0].lexical <= 1
    filtered = index.search("disk", where=lambda meta: meta["system"] == "bgl")
    assert all(h.meta["system"] == "bgl" for h in filtered)
    assert HybridIndex([]).search("x") == []
    with pytest.raises(ValueError, match="one vector per document"):
        HybridIndex(docs, embedder.transform(["one"]))


# --- incident memory ---------------------------------------------------------------------------


async def test_memory_finds_the_matching_failure_mode(memory: IncidentMemory) -> None:
    pairs = await memory.search("rts panic stopping execution kernel", system="bgl")
    assert pairs
    assert pairs[0][0].failure_mode == "kernel_panic"
    assert all(inc.synthetic for inc, _ in pairs)


async def test_repeat_history_aggregates_the_failure_mode(memory: IncidentMemory) -> None:
    pairs = await memory.search("Failed password for invalid user", system="openssh")
    incident = pairs[0][0]
    history = memory.history(incident)
    assert history.occurrences == 2  # two seeded scenarios per mode
    assert history.first_seen is not None
    assert history.last_seen is not None
    assert history.first_seen <= history.last_seen
    assert history.mttr_minutes is None  # never invented for synthetic history


async def test_remember_adds_an_incident_and_reembeds_on_model_change(
    memory: IncidentMemory, seeded: list[MemoryIncident]
) -> None:
    new = MemoryIncident(
        id="run-123",
        title="Lustre mount failures on 4 I/O nodes",
        system="bgl",
        failure_mode="lustre_mount_failure",
        severity=Severity.SEV2,
        summary="Mounts failed after an LNET outage.",
        resolution="Restored the LNET route and remounted.",
        source="run",
        mttr_minutes=42.0,
    )
    await memory.remember(new)
    assert memory.get("run-123") is not None
    assert memory.history(new).occurrences == 3
    assert memory.history(new).mttr_minutes == 42.0
    memory.embedder.use(HashingEmbedder(32))  # a different embedding model
    await memory.refresh()
    assert memory.index.vectors is not None
    assert memory.index.vectors.shape == (len(seeded) + 1, 32)


# --- ticket history ----------------------------------------------------------------------------


def _tickets(n: int) -> list[dict[str, object]]:
    start = datetime(2016, 3, 1, tzinfo=UTC)
    return [
        {
            "number": f"INC{i:07d}",
            "opened_at": start + timedelta(hours=i),
            "category": "Category 26" if i % 2 else "Category 9",
            "subcategory": "Subcategory 174",
            "symptom": "Symptom 491" if i % 4 == 1 else "Symptom 2",
            "final_assignment_group": "Group 70",
            "made_sla": i % 3 != 0,
            "reopen_count": 1 if i % 10 == 0 else 0,
            "reassignment_count": i % 3,
            "resolution_hours": float(i % 48),
            "closed_code": "code 6",
            "n_events": 3,
            "split": "train",
        }
        for i in range(n)
    ]


def test_ticket_history_backs_off_until_enough_tickets_match() -> None:
    engine = get_engine()
    init_db(engine)
    assert ticket_history(engine, TicketContext(category="Category 26")) is None  # empty table
    with session_scope(engine) as session:
        session.execute(insert(ItsmIncidentRow), _tickets(400))
    exact = ticket_history(
        engine,
        TicketContext(category="Category 26", subcategory="Subcategory 174", symptom="Symptom 491"),
    )
    assert exact is not None
    assert exact.backoff_level == 0
    assert exact.n_similar == 100
    assert exact.top_assignment_groups == ["Group 70"]
    assert exact.sla_breach_rate is not None
    rare = ticket_history(
        engine,
        TicketContext(category="Category 26", subcategory="Subcategory 174", symptom="Symptom 999"),
    )
    assert rare is not None
    assert rare.backoff_level == 1  # symptom too rare, so category + subcategory
    past = ticket_history(
        engine,
        TicketContext(category="Category 26", opened_at=datetime(2016, 3, 1, 10, tzinfo=UTC)),
        min_n=1,
    )
    assert past is not None
    assert past.n_similar == 5  # only tickets opened before the request: no peeking ahead


# --- agentic retrieval -------------------------------------------------------------------------


def _retriever(memory: IncidentMemory, **config: object) -> Retriever:
    return Retriever(
        memory,
        load_runbooks(Path("runbooks")),
        engine=memory.engine,
        router=None,
        config=RetrievalConfig(**config),  # type: ignore[arg-type]
    )


async def test_retrieval_returns_cited_incidents_and_runbooks(
    memory: IncidentMemory, builder: ScenarioBuilder
) -> None:
    scenario = builder.build(
        "bgl.kernel_panic",
        seed=999,
        nodes=4,
        duration_min=8,
        background_per_min=6,
        incident_per_min=10,
    )
    batch = parse_lines(
        scenario.lines, system="bgl", guard=GuardrailConfig(), evidence=EvidenceStore()
    ).batch
    query = build_query(
        batch,
        [
            Hypothesis(
                id="H1", statement="kernel panics", failure_mode="kernel_panic", confidence=0.6
            )
        ],
    )
    assert "kernel_panic" in query.text
    store = EvidenceStore()
    result = await _retriever(memory).retrieve(query, evidence=store, use_llm=False)
    assert result.incidents[0].failure_mode == "kernel_panic"
    assert result.incidents[0].evidence_id in store
    assert result.runbooks[0].slug == "bgl-kernel-panic"
    assert {e.kind for e in store.all()} >= {EvidenceKind.INCIDENT, EvidenceKind.RUNBOOK}
    assert result.attempts[0].attempt == 1
    assert 0 <= result.grade <= 1


async def test_weak_results_trigger_rewrite_and_widening(
    memory: IncidentMemory, builder: ScenarioBuilder
) -> None:
    scenario = builder.build_quiet("hdfs", seed=3, duration_min=4, background_per_min=6)
    batch = parse_lines(
        scenario.lines, system="hdfs", guard=GuardrailConfig(), evidence=EvidenceStore()
    ).batch
    query = build_query(batch)
    result = await _retriever(memory, min_grade=0.99, max_attempts=3).retrieve(
        query, evidence=EvidenceStore(), use_llm=False
    )
    assert len(result.attempts) == 3
    assert result.attempts[1].widened
    assert result.attempts[2].filters == {}  # the last attempt drops the system filter
    assert result.attempts[1].query == deterministic_rewrite(query)


def test_grade_rewards_agreement_and_hypothesis_match(seeded: list[MemoryIncident]) -> None:
    from aria.retrieval.hybrid import Hit

    def hit(score: float) -> Hit:
        return Hit("x", score, lexical=0.8, dense=0.6, lexical_rank=1, dense_rank=1, meta={})

    same = [(seeded[0], hit(0.03)), (seeded[1], hit(0.02))]
    mixed = [(seeded[0], hit(0.03)), (seeded[2], hit(0.02))]
    assert grade_hits(same, [], k=2) > grade_hits(mixed, [], k=2)
    assert grade_hits(same, [seeded[0].failure_mode], k=2) > grade_hits(same, ["other"], k=2)
    assert grade_hits([], [], k=3) == 0.0


async def test_slow_query_embeddings_fall_back_to_lexical_search(memory: IncidentMemory) -> None:
    class Slow:
        model = memory.embedding_model

        async def embed(self, texts: list[str], *, input_type: str) -> list[list[float]]:
            await asyncio.sleep(5)
            return [[0.0]]

    memory.embedder = Slow()
    memory.query_timeout_s = 0.05
    pairs = await memory.search("rts panic stopping execution kernel", system="bgl")
    assert pairs
    assert pairs[0][0].failure_mode == "kernel_panic"
    assert all(hit.dense_rank is None for _, hit in pairs)
