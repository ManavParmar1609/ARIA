"""Past incidents a person reviewed, as examples for the severity adjudicator."""

from __future__ import annotations

import json
from dataclasses import replace

from aria.config import LLMConfig, ProviderConfig, ProviderKind
from aria.contracts.base import SEVERITY_ORDER, Evidence, EvidenceKind, Severity
from aria.db.engine import get_engine, init_db
from aria.graph.store import SqlStore
from aria.llm.fake import FakeProvider
from aria.llm.prompts import parse_context
from aria.llm.router import LLMRouter
from aria.retrieval.memory import IncidentMemory, MemoryIncident, incident_run_id, run_incident_id
from aria.retrieval.reviewed import reviewed_examples
from aria.severity.adjudicator import ReviewedExample, adjudicate, levels_outside_set
from aria.severity.policy import Preliminary


def _incident(
    incident_id: str,
    *,
    source: str,
    title: str = "Kernel panics on compute nodes",
    severity: Severity = Severity.SEV2,
) -> MemoryIncident:
    return MemoryIncident(
        id=incident_id,
        title=title,
        system="bgl",
        failure_mode="kernel_panic",
        severity=severity,
        summary="12 error events on 3 of 4 nodes over 5 min (peak 8/min).",
        resolution="Rebooted the nodes.",
        components=["kernel"],
        source=source,  # type: ignore[arg-type]
        synthetic=source == "curated",
    )


async def test_examples_come_only_from_runs_a_person_reviewed_and_are_redacted() -> None:
    engine = get_engine()
    init_db(engine)
    memory = IncidentMemory(engine, None)
    await memory.bulk_insert(
        [
            _incident("syn-1", source="curated"),  # seeded: nobody rated it
            _incident("inc-20260101-aa", source="run"),  # published unattended: no review
            _incident(
                "inc-20260101-bb",
                source="run",
                title="Kernel panics after password=hunter2 was set",
                severity=Severity.SEV1,
            ),
        ]
    )
    store = SqlStore(engine)
    await store.aput(
        ("feedback", "bgl", "kernel_panic"),
        "run-20260101-bb",
        {
            "run_id": "run-20260101-bb",
            "decision": "edit",
            "from": "SEV2",
            "to": "SEV1",
            "failure_mode": "kernel_panic",
            "reviewer": "ana",
        },
    )
    examples = await reviewed_examples(
        memory, store, query="kernel panic compute nodes", system="bgl"
    )
    assert [e.incident_id for e in examples] == ["inc-20260101-bb"]
    [example] = examples
    assert (example.severity, example.aria_severity, example.decision) == (
        Severity.SEV1,
        Severity.SEV2,
        "edit",
    )
    assert "hunter2" not in example.title
    assert "[REDACTED]" in example.title
    assert example.similarity > 0
    assert example.evidence_id is None  # the workflow lists the examples as evidence
    # Another system's reviews, or no feedback store at all, give no examples.
    assert await reviewed_examples(memory, store, query="kernel panic", system="hdfs") == []
    assert await reviewed_examples(memory, None, query="kernel panic", system="bgl") == []
    assert incident_run_id(run_incident_id("run-20260101-bb")) == "run-20260101-bb"


def _pre(raw: list[Severity]) -> Preliminary:
    probabilities = {
        Severity.SEV1: 0.45,
        Severity.SEV2: 0.40,
        Severity.SEV3: 0.10,
        Severity.SEV4: 0.05,
    }
    return Preliminary(
        rule_severity=Severity.SEV2,
        rule_scores=dict.fromkeys(SEVERITY_ORDER, 0.0),
        rule_hits=[],
        floor=None,
        probabilities=probabilities,
        raw_set=raw,
        alpha=0.1,
        model_version="t",
        model_evidence="E1",
    )


EVIDENCE = [
    Evidence(
        id="E1", kind=EvidenceKind.MODEL, title="Severity probabilities", source="severity.model"
    ),
    Evidence(
        id="E2",
        kind=EvidenceKind.FEEDBACK,
        title="Past reviewed incidents like this one",
        source="memory.reviewed",
    ),
]
EXAMPLE = ReviewedExample(
    incident_id="inc-20260101-bb",
    title="Kernel panics on compute nodes",
    summary="12 error events on 3 of 4 nodes.",
    failure_mode="kernel_panic",
    severity=Severity.SEV3,
    aria_severity=Severity.SEV2,
    decision="edit",
    similarity=0.7,
    evidence_id="E2",
)


def _router(fake: FakeProvider) -> LLMRouter:
    config = LLMConfig(
        providers={
            "llm": ProviderConfig(
                kind=ProviderKind.NVIDIA_NIM,
                base_url="http://x/v1",
                allow_no_key=True,
                chat_model="m",
            )
        },
        routing={"adjudicator": ["llm"]},
    )
    fake.kind = ProviderKind.NVIDIA_NIM
    return LLMRouter(config, providers={"llm": fake})


async def test_reviewed_examples_reach_the_adjudicator_fenced_and_the_choice_stays_in_the_set() -> (
    None
):
    fake = FakeProvider()
    result = await adjudicate(
        _pre([Severity.SEV1, Severity.SEV2]),
        system="bgl",
        features={},
        evidence=EVIDENCE,
        router=_router(fake),
        examples=[EXAMPLE],
    )
    assert result.severity in (Severity.SEV1, Severity.SEV2)
    assert result.examples_outside_set == [Severity.SEV3]
    system, user = fake.calls[0]["messages"]
    assert "untrusted_reviewed_incidents" in system.content  # the rules name the block
    assert "<untrusted_reviewed_incidents>" in user.content
    fenced = user.content.split("<untrusted_reviewed_incidents>", 1)[1]
    assert "Kernel panics on compute nodes" in fenced
    context = parse_context([system, user])
    assert context["reviewed_examples"] == [
        {
            "incident_id": "inc-20260101-bb",
            "reviewed_severity": "SEV3",
            "aria_severity": "SEV2",
            "decision": "edit",
            "similarity": 0.7,
            "evidence_id": "E2",
        }
    ]
    assert context["reviewed_levels_outside_set"] == ["SEV3"]
    assert context["prediction_set"] == ["SEV1", "SEV2"]  # the set the schema still offers


async def test_a_model_that_follows_an_example_out_of_the_set_is_refused() -> None:
    swayed = json.dumps(
        {
            "severity": "SEV3",
            "rationale": [
                {"text": "Reviewers rated incidents like this SEV3.", "evidence_ids": ["E2"]}
            ],
            "uncertainty": "",
        }
    )
    fake = FakeProvider(script={"adjudication": [swayed, swayed]})
    result = await adjudicate(
        _pre([Severity.SEV1, Severity.SEV2]),
        system="bgl",
        features={},
        evidence=EVIDENCE,
        router=_router(fake),
        examples=[EXAMPLE],
    )
    assert result.severity is None  # both answers refused: no LLM decision at all
    assert result.examples_outside_set == [Severity.SEV3]  # still reported to the reviewer
    assert "severity must be one of SEV1, SEV2" in fake.calls[1]["messages"][-1].content


def test_levels_outside_the_set_are_named_most_severe_first_and_once() -> None:
    examples = [
        replace(EXAMPLE, severity=level)
        for level in (Severity.SEV4, Severity.SEV1, Severity.SEV4, Severity.SEV2)
    ]
    assert levels_outside_set(examples, [Severity.SEV2, Severity.SEV3]) == [
        Severity.SEV1,
        Severity.SEV4,
    ]
    assert levels_outside_set([], [Severity.SEV2]) == []
