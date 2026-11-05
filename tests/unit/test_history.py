"""A system's own history at triage time (severity/history.py): its baseline error ratio and the
patterns reviewers dismissed, read from the database the runner writes to."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aria.contracts.base import SEVERITY_ORDER, EvidenceKind
from aria.contracts.parsing import WindowFeatures
from aria.contracts.run import RunStatus
from aria.data.loghub import LogRecord
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db
from aria.evidence import EvidenceStore
from aria.graph.runner import TriageRunner
from aria.parsing.features import ISSUE_LEVELS
from aria.parsing.parser import ParsedLine
from aria.retrieval import runlog
from aria.services import Services
from aria.severity.engine import SeverityEngine
from aria.severity.history import MAX_BURN, HistoryContext, SystemHistory
from aria.severity.rules import load_rules

RULES = load_rules(Path("config/severity_rules.yaml"))
BURN_RULES = {"error_burn_page", "error_burn_ticket"}


def _finished(
    engine: Any,
    run_id: str,
    system: str,
    *,
    events: int,
    errors: int,
    status: RunStatus = RunStatus.PUBLISHED,
    visitor: str | None = None,
) -> None:
    """A run that got past parsing: its ``merge`` step recorded the window's events and errors."""
    repo.create_run(engine, run_id, request={}, system=system, status=status, visitor=visitor)
    repo.append_event(
        engine,
        run_id,
        "node_finished",
        node="merge",
        payload={"events": events, "errors": errors, "templates": 4, "quarantined": 0},
    )


def _lines(system: str, specs: list[tuple[str | None, str]]) -> list[ParsedLine]:
    return [
        ParsedLine(
            idx=i,
            record=LogRecord(system=system, line_no=i + 1, message=f"m{i}", node="n1", level=level),
            shard_template="t",
            template="t",
            template_id=template,
        )
        for i, (level, template) in enumerate(specs)
    ]


def _window(**overrides: Any) -> WindowFeatures:
    """A busy window with a 5% error ratio on two of four nodes."""
    base: dict[str, Any] = {
        "n_events": 600,
        "n_templates": 12,
        "duration_s": 1_200.0,
        "events_per_min": 30.0,
        "level_counts": {"INFO": 570, "ERROR": 30},
        "error_events": 30,
        "error_ratio": 0.05,
        "keyword_hits": {},
        "burst_score": 0.0,
        "peak_errors_per_min": 3.0,
        "distinct_nodes": 4,
        "error_nodes": 2,
        "node_spread": 0.5,
        "novel_templates": 0,
        "novel_error_templates": 0,
        "components": ["APP"],
        "critical_components": [],
        "max_component_criticality": 0.0,
        "persistence_s": 600.0,
        "issue_events": 30,
    }
    base.update(overrides)
    return WindowFeatures(**base)


# --- the baseline ---------------------------------------------------------------------------------


def test_the_baseline_is_the_median_error_ratio_of_the_systems_recent_finished_runs() -> None:
    engine = get_engine()
    init_db(engine)
    for i, errors in enumerate((10, 20, 30, 40, 50, 500)):
        _finished(engine, f"hdfs-{i}", "hdfs", events=1_000, errors=errors)
    # The run being triaged is still running; a visitor's run and another system's are not hdfs's.
    _finished(engine, "hdfs-now", "hdfs", events=1_000, errors=900, status=RunStatus.RUNNING)
    _finished(engine, "hdfs-theirs", "hdfs", events=1_000, errors=900, visitor="v-1")
    _finished(engine, "bgl-0", "bgl", events=1_000, errors=900)
    history = SystemHistory(engine)
    assert history.baseline("hdfs") == (0.035, 6)
    assert history.baseline("bgl") is None  # one run is too few to call usual
    assert history.baseline_features("hdfs", error_ratio=0.35) == {
        "error_ratio_vs_baseline": 10.0,
        "baseline_error_ratio": 0.035,
        "baseline_runs": 6.0,
    }
    assert history.baseline_features("bgl", error_ratio=0.35) == {}
    assert history.lookup("bgl", error_ratio=0.35) == HistoryContext()


def test_a_system_that_never_logs_errors_still_has_a_baseline_to_burn_against() -> None:
    engine = get_engine()
    init_db(engine)
    for i in range(5):
        _finished(engine, f"mac-{i}", "mac", events=400, errors=0)
    history = SystemHistory(engine)
    assert history.baseline("mac") == (0.0, 5)
    burn = history.baseline_features("mac", error_ratio=0.05)["error_ratio_vs_baseline"]
    assert burn == 50.0  # against a floor of one error in a thousand lines
    assert history.baseline_features("mac", error_ratio=1.0)["error_ratio_vs_baseline"] == MAX_BURN
    assert history.baseline_features("mac", error_ratio=0.0)["error_ratio_vs_baseline"] == 0.0


# --- patterns reviewers dismissed -----------------------------------------------------------------


def test_dismissed_patterns_are_the_issue_lines_of_discarded_or_lowered_runs() -> None:
    engine = get_engine()
    init_db(engine)

    def reviewed(
        run_id: str, decision: str, before: str, after: str, specs: list[tuple[str | None, str]]
    ) -> None:
        repo.create_run(engine, run_id, request={}, system="hdfs", status=RunStatus.PUBLISHED)
        runlog.store_run_lines(engine, run_id, "hdfs", _lines("hdfs", specs))
        value = {"decision": decision, "from": before, "to": after}
        repo.save_feedback(engine, run_id, "review", value, author="raj")

    reviewed("r-reject", "reject", "SEV2", "SEV2", [("WARN", "Tbad"), ("INFO", "Tok")])
    reviewed("r-lowered", "edit", "SEV2", "SEV4", [("WARN", "Tbad"), (None, "Tunlevelled")])
    reviewed("r-kept", "approve", "SEV2", "SEV2", [("WARN", "Tkept")])
    reviewed("r-raised", "edit", "SEV3", "SEV2", [("ERROR", "Traised")])
    assert repo.dismissed_reviews(engine, "hdfs") == ["r-lowered", "r-reject"]
    assert repo.dismissed_reviews(engine, "bgl") == []
    templates = repo.issue_templates_of(
        engine, ["r-reject", "r-lowered", "r-gone"], levels=ISSUE_LEVELS
    )
    assert templates == {"r-reject": {"Tbad"}, "r-lowered": {"Tbad", "Tunlevelled"}}

    patterns = SystemHistory(engine).dismissed("hdfs")
    assert patterns is not None
    assert patterns.reviews == 2
    assert patterns.runs_by_template["Tbad"] == {"r-reject", "r-lowered"}
    assert not {"Tok", "Tkept", "Traised"} & set(patterns.runs_by_template)
    match = patterns.match({"Tbad": 8, "Tnew": 2}, issue_lines=10)
    assert match is not None
    assert (match.reviews, match.matched_lines, match.issue_lines) == (2, 8, 10)
    assert match.templates == ("Tbad",)
    assert patterns.match({"Tbad": 2, "Tnew": 8}, issue_lines=10) is None  # mostly something new
    assert patterns.match({}, issue_lines=0) is None
    assert SystemHistory(engine).dismissed("bgl") is None


# --- the engine reads both ------------------------------------------------------------------------


async def test_the_engine_rates_a_burn_against_the_systems_own_baseline() -> None:
    engine = get_engine()
    init_db(engine)
    for i in range(6):
        _finished(engine, f"hdfs-{i}", "hdfs", events=1_000, errors=1)  # one error a thousand
    evidence = EvidenceStore()
    result = await SeverityEngine(RULES, None, alpha=0.1, history=SystemHistory(engine)).assess(
        _window(), system="hdfs", evidence=evidence
    )
    assert {h.rule_id for h in result.assessment.rule_hits} >= BURN_RULES
    feature = next(e for e in evidence.all() if e.source == "severity.history")
    assert feature.kind is EvidenceKind.FEATURE
    assert feature.data["error_ratio_vs_baseline"] == 50.0  # 5% against a median of 0.1%
    assert feature.data["baseline_runs"] == 6
    # A system with no history, like every offline evaluation, is rated without the burn rules.
    cold = await SeverityEngine(RULES, None, alpha=0.1, history=SystemHistory(engine)).assess(
        _window(), system="bgl", evidence=EvidenceStore()
    )
    assert not BURN_RULES & {h.rule_id for h in cold.assessment.rule_hits}
    offline = await SeverityEngine(RULES, None, alpha=0.1).assess(
        _window(), system="hdfs", evidence=EvidenceStore()
    )
    assert not BURN_RULES & {h.rule_id for h in offline.assessment.rule_hits}


async def test_a_handful_of_lines_is_never_a_burn() -> None:
    engine = get_engine()
    init_db(engine)
    for i in range(6):
        _finished(engine, f"hdfs-{i}", "hdfs", events=1_000, errors=1)
    few = _window(
        n_events=40, level_counts={"INFO": 36, "ERROR": 4}, error_events=4, error_ratio=0.1
    )
    result = await SeverityEngine(RULES, None, alpha=0.1, history=SystemHistory(engine)).assess(
        few, system="hdfs", evidence=EvidenceStore()
    )
    assert not BURN_RULES & {h.rule_id for h in result.assessment.rule_hits}


async def test_dismissed_patterns_inform_the_reviewer_but_never_lower_the_level() -> None:
    engine = get_engine()
    init_db(engine)
    for i in range(3):  # three drafts on hdfs that reviewers discarded, all on one pattern
        run_id = f"hdfs-noise-{i}"
        repo.create_run(engine, run_id, request={}, system="hdfs", status=RunStatus.REJECTED)
        runlog.store_run_lines(
            engine, run_id, "hdfs", _lines("hdfs", [("WARN", "Tnoise"), ("INFO", "Tok")])
        )
        value = {"decision": "reject", "from": "SEV3", "to": "SEV3"}
        repo.save_feedback(engine, run_id, "review", value, author="raj")
    window = _window(
        issue_templates={"Tnoise": 27, "Tnew": 3},
        keyword_hits={"unavailable": 27},
        issue_keyword_hits={"unavailable": 27},
    )
    informed_by = SeverityEngine(RULES, None, alpha=0.1, history=SystemHistory(engine))
    evidence = EvidenceStore()
    informed = await informed_by.assess(window, system="hdfs", evidence=evidence)
    plain = await SeverityEngine(RULES, None, alpha=0.1).assess(
        window, system="hdfs", evidence=EvidenceStore()
    )
    assert informed.assessment.severity == plain.assessment.severity
    assert informed.assessment.prediction_set == plain.assessment.prediction_set
    assert informed.assessment.needs_review == plain.assessment.needs_review
    note = next(e for e in evidence.all() if e.kind is EvidenceKind.FEEDBACK)
    assert note.title == "Reviewers dismissed this pattern 3 times before on hdfs"
    assert (note.data["dismissed_reviews"], note.data["matched_lines"]) == (3, 27)
    claim = next(c for c in informed.assessment.rationale if "dismissed this pattern" in c.text)
    assert note.id in claim.evidence_ids
    # A window whose issue lines are mostly something else gets no such note.
    store = EvidenceStore()
    await informed_by.assess(
        _window(issue_templates={"Tnew": 25, "Tnoise": 5}), system="hdfs", evidence=store
    )
    assert not [e for e in store.all() if e.kind is EvidenceKind.FEEDBACK]


async def test_a_history_lookup_that_fails_does_not_fail_the_triage() -> None:
    class Broken(SystemHistory):
        def lookup(self, system: str, *, error_ratio: float) -> HistoryContext:
            msg = "the database went away"
            raise RuntimeError(msg)

    engine = SeverityEngine(RULES, None, alpha=0.1, history=Broken(get_engine()))
    result = await engine.assess(_window(), system="hdfs", evidence=EvidenceStore())
    assert result.assessment.severity in SEVERITY_ORDER
    assert not BURN_RULES & {h.rule_id for h in result.assessment.rule_hits}


async def test_the_runner_gives_the_severity_engine_the_databases_history() -> None:
    init_db(get_engine())
    services = await Services.create()
    try:
        runner = TriageRunner(services)
        history = services.severity.history
        assert isinstance(history, SystemHistory)
        assert history.engine is services.engine is runner.engine
    finally:
        await services.aclose()
