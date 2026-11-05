"""The language model's choice inside the prediction set, measured.

ARIA lets a model choose a level only inside the conformal prediction set, and only on the
windows the policy does not decide on its own. Nothing published says whether that choice beats
the calibrated model's own top level, or how steady it is, so this suite measures both:

* on the held-out-system windows (ring B): each window is scored by a model fitted without its
  system, as the generalisation suite scores it, and the adjudicator is asked on every window
  that model's policy leaves open;
* on the BGL log's contiguous windows (ring C, with the administrators' alert tags as truth),
  scored by the model fitted without any BGL window, on a seeded sample of the windows left
  open, because the log holds thousands of them.

The other real-data suites label detection, priority or retrieval, not a level, so they have no
truth to score a level against.

The adjudicator is asked ``k`` times on each window, so the suite reports:

* **override benefit**: the model's pick against the calibrated model's top level inside the set,
  and against the policy's own fallback (the most severe level in the set), on the same windows,
  with the exact McNemar tests aria.evals.stats gives: how many windows the pick put right and
  how many it put wrong;
* **consistency**: pass^k, the share of windows on which every one of the k runs was right (and
  on which every run picked the same level), with pass@k, right in any run, beside it for
  contrast.

Offline the fake provider answers: it picks the calibrated top level inside the set, so the
override benefit is nil and every run agrees; the smoke check proves the harness and counts the
calls a live run would make. With ``--llm`` the configured chain answers, each open window
costing k calls, and the router's response cache is off so the k runs are k requests. A live
run's results stay out of docs/evaluation.md until the owner commits one (the CLI writes
docs/eval-llm-choice.json).
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aria.config import AppConfig, LLMConfig, SeverityConfig, get_app_config, get_settings
from aria.contracts.parsing import WindowFeatures
from aria.data.loghub import iter_raw_log, iter_structured_csv
from aria.data.scenarios import Scenario, ScenarioBuilder
from aria.evals import bgl as bg
from aria.evals import metrics as m
from aria.evals import rings
from aria.evals import stats as st
from aria.evidence import EvidenceStore
from aria.llm.cache import ResponseCache
from aria.llm.quota import QuotaLedger
from aria.llm.router import LLMRouter
from aria.severity.adjudicator import adjudicate
from aria.severity.engine import SeverityEngine
from aria.severity.policy import Preliminary
from aria.severity.rules import RuleSet, feature_space
from aria.severity.training import known_templates

K = 3  # runs on each window: pass^k needs every one right
BGL_WINDOWS = 60  # the BGL windows sampled from those the policy leaves open
SEED = 2029


@dataclass
class ChoiceCase:
    """One window the policy left to a model, asked k times."""

    id: str
    source: str  # "held_out_system" or "bgl"
    group: str  # the system held out, or "bgl"
    truth: str
    prediction_set: list[str]
    model_top: str  # the calibrated model's most likely level inside the set
    most_severe: str  # the level the policy takes with no model: the most severe in the set
    choices: list[str | None]  # the level picked on each run; None when no answer was accepted
    reasons: list[str] = field(default_factory=list)  # why a run gave no answer
    providers: list[str] = field(default_factory=list)  # who answered each run

    @property
    def first(self) -> str | None:
        return self.choices[0] if self.choices else None


def offline_router() -> LLMRouter:
    """The fake provider on the adjudicator's role: the smoke check's answerer."""
    config = LLMConfig(providers={}, routing={"adjudicator": ["fake"]})
    return LLMRouter(config, env=get_settings().env)


def live_router() -> LLMRouter:
    """The configured chain, with the response cache off so that k runs are k requests."""
    settings = get_settings()
    app = get_app_config()
    return LLMRouter(
        app.llm,
        env=settings.env,
        models_dir=settings.models_dir,
        ledger=QuotaLedger.from_config(app.llm, path=settings.quota_path),
        cache=ResponseCache(ttl_s=0, max_entries=0),
        datamark=app.guardrails.datamark_untrusted,
    )


async def ask(
    pre: Preliminary,
    *,
    system: str,
    features: WindowFeatures,
    evidence: EvidenceStore,
    router: LLMRouter,
    k: int,
) -> tuple[list[str | None], list[str], list[str]]:
    """The adjudicator's pick on each of ``k`` runs, the reasons it gave none, and who answered."""
    values = {key: v for key, v in feature_space(features).items() if v}
    choices: list[str | None] = []
    reasons: list[str] = []
    providers: list[str] = []
    for _ in range(k):
        result = await adjudicate(
            pre, system=system, features=values, evidence=evidence.all(), router=router
        )
        choices.append(str(result.severity) if result.severity is not None else None)
        if result.reason:
            reasons.append(result.reason)
        if result.provider:
            providers.append(result.provider)
    return choices, reasons, providers


async def judge(
    engine: SeverityEngine,
    *,
    case_id: str,
    source: str,
    group: str,
    system: str,
    features: WindowFeatures,
    truth: str,
    router: LLMRouter,
    k: int,
) -> ChoiceCase | None:
    """The window asked k times, or None when the policy decided it alone (no model is asked)."""
    evidence = EvidenceStore()
    pre = engine.preliminary(features, system=system, evidence=evidence)
    if pre.auto_decision(engine.gate) is not None:
        return None
    choices, reasons, providers = await ask(
        pre, system=system, features=features, evidence=evidence, router=router, k=k
    )
    return ChoiceCase(
        id=case_id,
        source=source,
        group=group,
        truth=truth,
        prediction_set=[str(s) for s in pre.prediction_set],
        model_top=str(pre.top),
        most_severe=str(pre.prediction_set[0]),
        choices=choices,
        reasons=reasons,
        providers=providers,
    )


async def held_out_systems(
    rules: RuleSet,
    test: Sequence[Scenario],
    features: Sequence[WindowFeatures],
    windows: rings.TrainingWindows,
    *,
    config: SeverityConfig,
    router: LLMRouter,
    k: int = K,
    limit: int | None = None,
) -> list[ChoiceCase]:
    """Ring B: each system's test windows, scored by a model fitted without that system, with the
    adjudicator asked on every window left open. ``limit`` caps the windows, spread over the
    systems."""
    by_system: dict[str, list[int]] = defaultdict(list)
    for i, scenario in enumerate(test):
        by_system[scenario.system].append(i)
    per_system = None if limit is None else max(1, -(-limit // max(1, len(by_system))))
    cases: list[ChoiceCase] = []
    for system in sorted(by_system):

        def outside(w: Any, held: str = system) -> bool:
            return bool(w.system != held)

        model = rings.model_without(
            windows,
            outside,
            alpha=config.alpha,
            rules_version=rules.version,
            serious_alpha=config.serious_alpha,
            severe_miss_risk=config.severe_miss_risk,
        )
        engine = SeverityEngine(rules, model, alpha=config.alpha)
        taken = 0
        for i in by_system[system]:
            if per_system is not None and taken >= per_system:
                break
            case = await judge(
                engine,
                case_id=test[i].id,
                source="held_out_system",
                group=system,
                system=system,
                features=features[i],
                truth=str(test[i].severity),
                router=router,
                k=k,
            )
            if case is not None:
                cases.append(case)
                taken += 1
    return cases


async def bgl_windows(
    path: Path,
    *,
    engine: SeverityEngine,
    known: Sequence[str],
    pool: set[str],
    router: LLMRouter,
    k: int = K,
    windows: int = BGL_WINDOWS,
    seed: int = SEED,
) -> tuple[list[ChoiceCase], int]:
    """A seeded sample of the BGL windows the policy leaves open, asked k times, and how many
    windows were open in all. The whole log is read once, as the BGL suite reads it."""
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    kept: list[tuple[int, bg.Window, WindowFeatures, EvidenceStore, Preliminary]] = []
    seen = 0
    tally = bg._Tally()
    for window in bg.stream_windows(iter_raw_log("bgl", path), pool, tally):
        feats = bg._features(window.lines, known)
        evidence = EvidenceStore()
        pre = engine.preliminary(feats, system="bgl", evidence=evidence)
        if pre.auto_decision(engine.gate) is not None:
            continue
        seen += 1
        entry = (seen, window, feats, evidence, pre)
        if len(kept) < windows:
            kept.append(entry)
        else:  # reservoir sampling: every open window has the same chance of being kept
            j = rng.randrange(seen)
            if j < windows:
                kept[j] = entry
    cases: list[ChoiceCase] = []
    for _, window, feats, evidence, pre in sorted(kept, key=lambda entry: entry[0]):
        choices, reasons, providers = await ask(
            pre, system="bgl", features=feats, evidence=evidence, router=router, k=k
        )
        cases.append(
            ChoiceCase(
                id=f"bgl-{window.start.isoformat()}",
                source="bgl",
                group="bgl",
                truth=window.label,
                prediction_set=[str(s) for s in pre.prediction_set],
                model_top=str(pre.top),
                most_severe=str(pre.prediction_set[0]),
                choices=choices,
                reasons=reasons,
                providers=providers,
            )
        )
    return cases, seen


# --- summaries -------------------------------------------------------------------------------


def _share(hits: int, n: int) -> dict[str, Any]:
    low, high = st.wilson(hits, n)
    return {
        "hits": hits,
        "n": n,
        "rate": round(hits / n, 4) if n else None,
        "ci95": [round(low, 4), round(high, 4)],
    }


def _severe(truth: Sequence[str], pred: Sequence[str]) -> dict[str, Any]:
    misses, severe = st.severe_misses(truth, pred)
    return {
        "misses": misses,
        "severe": severe,
        "rate": round(misses / severe, 4) if severe else None,
        "upper95": round(st.upper_bound(misses, severe), 4),
    }


def _method(truth: Sequence[str], pred: Sequence[str]) -> dict[str, Any]:
    return {
        "accuracy": round(m.accuracy(truth, pred), 4) if truth else None,
        "macro_f1": round(m.macro_f1(truth, pred), 4) if truth else None,
        "severe": _severe(truth, pred),
    }


def summarize(cases: Sequence[ChoiceCase], *, k: int = K) -> dict[str, Any]:
    """What the model's picks did on ``cases``: against the calibrated top level and the policy's
    fallback, the overrides' benefit, and the consistency of the k runs."""
    answered = [c for c in cases if c.first is not None]
    unanswered = Counter(next(iter(c.reasons), "no answer") for c in cases if c.first is None)
    truth = [c.truth for c in answered]
    picks = [str(c.first) for c in answered]
    tops = [c.model_top for c in answered]
    fallbacks = [c.most_severe for c in answered]
    overrides = [c for c in answered if c.first != c.model_top]
    put_right = sum(1 for c in overrides if c.first == c.truth)
    put_wrong = sum(1 for c in overrides if c.model_top == c.truth)
    complete = [c for c in cases if len(c.choices) == k and all(ch for ch in c.choices)]
    same = sum(1 for c in complete if len(set(c.choices)) == 1)
    all_right = sum(1 for c in complete if all(ch == c.truth for ch in c.choices))
    any_right = sum(1 for c in complete if any(ch == c.truth for ch in c.choices))
    by_group: dict[str, Any] = {}
    for group in sorted({c.group for c in cases}):
        subset = [c for c in answered if c.group == group]
        by_group[group] = {
            "windows": sum(1 for c in cases if c.group == group),
            "answered": len(subset),
            "pick_accuracy": round(
                m.accuracy([c.truth for c in subset], [str(c.first) for c in subset]), 4
            )
            if subset
            else None,
            "top_accuracy": round(
                m.accuracy([c.truth for c in subset], [c.model_top for c in subset]), 4
            )
            if subset
            else None,
            "overrides": sum(1 for c in subset if c.first != c.model_top),
        }
    return {
        "k": k,
        "windows": len(cases),  # the windows the policy left to a model
        "contested": sum(1 for c in cases if len(c.prediction_set) > 1),
        "answered": len(answered),
        "unanswered": dict(unanswered),
        "calls": sum(len(c.choices) for c in cases),
        "answered_by": dict(Counter(p for c in cases for p in c.providers)),
        "coverage": round(sum(1 for c in cases if c.truth in c.prediction_set) / len(cases), 4)
        if cases
        else None,
        "labels": dict(sorted(Counter(c.truth for c in cases).items())),
        "methods": {
            "model_pick": _method(truth, picks),
            "calibrated_top": _method(truth, tops),
            "most_severe_in_set": _method(truth, fallbacks),
        },
        "override": {
            "windows": len(overrides),
            "put_right": put_right,
            "put_wrong": put_wrong,
            "net": put_right - put_wrong,
            "against_calibrated_top": st.compare(truth, picks, tops),
            "against_most_severe": st.compare(truth, picks, fallbacks),
        },
        "consistency": {
            "complete": len(complete),
            "same_level_every_run": _share(same, len(complete)),
            "right_every_run": _share(all_right, len(complete)),  # pass^k
            "right_in_any_run": _share(any_right, len(complete)),  # pass@k
        },
        "by_group": by_group,
    }


async def evaluate(
    *,
    builder: ScenarioBuilder,
    rules: RuleSet,
    config: AppConfig,
    loghub_dir: Path,
    test: Sequence[Scenario],
    features: Sequence[WindowFeatures],
    windows: rings.TrainingWindows,
    use_llm: bool = False,
    k: int = K,
    limit: int | None = None,
    bgl_sample: int = BGL_WINDOWS,
    bgl_dir: Path = bg.BGL_DIR,
) -> dict[str, Any]:
    """The suite: ring B on ``test``, then the BGL log when it is downloaded."""
    router = live_router() if use_llm else offline_router()
    try:
        ring_b = await held_out_systems(
            rules, test, features, windows, config=config.severity, router=router, k=k, limit=limit
        )
        out: dict[str, Any] = {
            "k": k,
            "model": "the configured chain" if use_llm else "the fake provider (offline)",
            "held_out_systems": summarize(ring_b, k=k),
            "cases": [asdict(c) for c in ring_b],
        }
        path = bg.find_bgl(bgl_dir)
        if path is None:
            out["bgl"] = {"missing": "download it with: aria data download --source loghub-bgl"}
        else:
            unseen = SeverityEngine(
                rules,
                rings.model_without(
                    windows,
                    lambda w: bool(w.system != "bgl"),
                    alpha=config.severity.alpha,
                    rules_version=rules.version,
                    serious_alpha=config.severity.serious_alpha,
                    severe_miss_risk=config.severity.severe_miss_risk,
                ),
                alpha=config.severity.alpha,
            )
            sample = loghub_dir / "BGL" / "BGL_2k.log_structured.csv"
            pool = (
                {r.message for r in iter_structured_csv("bgl", sample)}
                if sample.exists()
                else set()
            )
            cases, open_windows = await bgl_windows(
                path,
                engine=unseen,
                known=known_templates(builder, "bgl"),
                pool=pool,
                router=router,
                k=k,
                windows=limit or bgl_sample,
            )
            out["bgl"] = {
                **summarize(cases, k=k),
                "windows_left_open": open_windows,
                "fitted_without": "every BGL window",
            }
            out["cases"] += [asdict(c) for c in cases]
        out["calls"] = out["held_out_systems"]["calls"] + (out["bgl"].get("calls") or 0)
        return out
    finally:
        await router.aclose()
