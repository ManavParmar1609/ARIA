"""Render evaluation results as ``docs/evaluation.md``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

METHOD_NAMES = {
    "aria_policy": "ARIA policy (offline)",
    "model_with_floors": "Calibrated model + rule floors",
    "model_only": "Calibrated model only",
    "rules_only": "Rules only",
    "tfidf_logreg": "TF-IDF + logistic regression (raw text)",
    "majority_class": "Majority class",
}


def _pct(value: Any) -> str:
    return f"{100 * float(value):.1f}%" if isinstance(value, int | float) else "n/a"


def _ci(pair: Any, *, percent: bool = True) -> str:
    if isinstance(pair, list | tuple) and len(pair) == 2:
        if percent:
            return f"{100 * pair[0]:.1f}–{100 * pair[1]:.1f}%"
        return f"{pair[0]:.3f}–{pair[1]:.3f}"
    return "n/a"


def _counts(counts: Mapping[str, Any]) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in counts.items()) or "none"


def _severity(section: Mapping[str, Any]) -> list[str]:
    lines = [
        "## Severity",
        "",
        f"{section['n']} held-out windows. Labels: {_counts(section['label_distribution'])}.",
        "",
        (
            "| Method | Accuracy (95% CI) | Macro-F1 (95% CI) | Weighted kappa | Under-triage | "
            "SEV1/2 rated SEV3/4 |"
        ),
        "|---|---|---|---|---|---|",
    ]
    for key, label in METHOD_NAMES.items():
        r = section["methods"].get(key)
        if r is None:
            continue
        lines.append(
            f"| {label} | {_pct(r['accuracy'])} ({_ci(r['accuracy_ci95'])}) | "
            f"{r['macro_f1']:.3f} ({_ci(r['macro_f1_ci95'], percent=False)}) | "
            f"{r['quadratic_kappa']:.3f} | "
            f"{_pct(r['under_triage'])} | {_pct(r['severe_under_triage'])} |"
        )
    cal, conf, auto = section["calibration"], section["conformal"], section["automation"]
    lines += [
        "",
        f"Calibration of the model's probabilities: ECE {cal['ece']:.3f}, Brier {cal['brier']:.3f}.",
        "",
        (
            f"Conformal prediction sets (alpha {conf['alpha']}, target coverage "
            f"{_pct(conf['target_coverage'])}): coverage {_pct(conf['coverage_raw'])} before the rule "
            f"floors, {_pct(conf['coverage_with_floors'])} after; mean set size "
            f"{conf['mean_set_size']}."
        ),
        "",
        (
            f"Automation: {_pct(auto['auto_decided'])} of windows were decided without review, with "
            f"{_pct(auto['accuracy_when_auto'])} accuracy; the rest were flagged for review "
            f"({_pct(auto['accuracy_when_flagged'])} accuracy for the conservative choice)."
        ),
        "",
        "| System | Windows | Accuracy | SEV1/2 rated SEV3/4 | Labels from |",
        "|---|---|---|---|---|",
    ]
    for system, r in section["by_system"].items():
        lines.append(
            f"| {system} | {r['n']} | {_pct(r['accuracy'])} | {_pct(r['severe_under_triage'])} | "
            f"{r['label_source']} |"
        )
    return [*lines, ""]


def _pipeline(section: Mapping[str, Any], title: str) -> list[str]:
    g, r, inv, lat, b = (
        section["groundedness"],
        section["retrieval"],
        section["investigation"],
        section["latency"],
        section["budgets"],
    )
    sev = section["severity"]
    stage_rows = [
        f"| {stage} | {lat['stage_p50_ms'][stage]:.0f} | {lat['stage_p95_ms'][stage]:.0f} |"
        for stage in lat["stage_p50_ms"]
    ]
    if b["mean_llm_calls"]:
        llm = (
            f" LLM calls: p50 {lat['llm_call_p50_ms'] / 1000:.1f} s, "
            f"p95 {lat['llm_call_p95_ms'] / 1000:.1f} s."
        )
        tokens = (
            f"at most {b['max_tokens_used']} tokens per run (limit {b['token_limit']}); "
            f"{b['runs_over_token_limit']} runs over the limit; "
        )
    else:
        llm, tokens = " No LLM calls (offline).", ""
    return [
        title,
        "",
        (
            f"{section['n']} runs through the full graph to the review pause. Statuses: "
            f"{_counts(section['statuses'])}."
        ),
        "",
        (
            f"- Severity: accuracy {_pct(sev['accuracy'])}, macro-F1 {sev['macro_f1']:.3f}, SEV1/2 "
            f"rated SEV3/4 {_pct(sev['severe_under_triage'])}."
        ),
        (
            f"- Reports that passed validation: {_pct(g['valid_reports'])}; reports in which every "
            f"claim, timeline entry and action cites existing evidence: {_pct(g['every_claim_cited'])};"
            f" mean citation coverage {_pct(g['mean_citation_coverage'])}. Written by: "
            f"{_counts(g['written_by'])}."
        ),
        (
            f"- Similar incidents ({r['n']} incident runs): Recall@1 {_pct(r['recall_at_1'])}, "
            f"Recall@3 {_pct(r['recall_at_3'])}, MRR {r['mrr']:.3f} (a hit shares the true failure "
            "mode)."
        ),
        (
            f"- Investigation: leading hypothesis names the true failure mode in "
            f"{_pct(inv['leading_hypothesis_correct'])} of incident runs; "
            f"{_pct(inv['has_supported_hypothesis'])} end with a supported hypothesis; "
            f"{_pct(inv['replanned'])} of runs replanned. False alarms: "
            f"{_pct(inv.get('false_alarms'))} of {inv.get('quiet_runs', 0)} quiet windows ended "
            "with a supported hypothesis."
        ),
        (
            f"- Time to review: p50 {lat['time_to_review_p50_s']:.2f} s, p95 "
            f"{lat['time_to_review_p95_s']:.2f} s.{llm}"
        ),
        (
            f"- Budgets: {tokens}{b['runs_with_exhausted_budget']} runs hit a budget and fell "
            f"back; {b['mean_llm_calls']} LLM calls and {b['mean_tool_calls']} tool calls per run "
            "on average."
        ),
        "",
        "| Stage | p50 ms | p95 ms |",
        "|---|---|---|",
        *stage_rows,
        "",
    ]


def _robustness(section: Mapping[str, Any]) -> list[str]:
    return [
        "## Prompt-injection robustness",
        "",
        (
            f"{section['n']} incident windows, each run clean and again with "
            f"{section['attacks_per_case']} injected instruction lines (override, role hijack, "
            "severity tampering, alert suppression, review bypass)."
        ),
        "",
        f"- Severity unchanged: {_pct(section['severity_invariant'])}.",
        f"- Investigator tool calls unchanged: {_pct(section['tool_use_invariant'])}.",
        f"- Every injected line quarantined: {_pct(section['all_attacks_quarantined'])}.",
        f"- Reports containing injected text: {section['reports_with_injected_text']}.",
        "",
    ]


def render(results: Mapping[str, Any], live: Mapping[str, Any] | None = None) -> str:
    lines = [
        "# Evaluation",
        "",
        (
            "> Generated by `make eval` "
            f"({results['created_at']}, commit {results.get('git_sha') or 'unknown'}). "
            "Do not edit by hand."
        ),
        "",
        (
            "**Data.** Every number here comes from semi-synthetic incident windows: real lines from "
            "the public Loghub samples, composed into incidents by ARIA's scenario builder. Severity "
            "labels come from the BGL alert-tag rubric for BGL windows and from the documented "
            "scenario policy elsewhere. The windows use held-out seeds "
            f"{', '.join(map(str, results['data']['test_seeds']))}, which no model was trained, "
            "calibrated or seeded on "
            "(incident memory uses seeds 51-52). These results show how ARIA behaves on that "
            "distribution; they are not a measurement of accuracy on production incidents."
        ),
        "",
    ]
    if results["data"].get("fixtures"):
        lines += [
            (
                "> **These numbers come from the small test fixtures, not the Loghub 2k samples.** "
                "Run `make data` and regenerate before quoting them."
            ),
            "",
        ]
    if "severity" in results:
        lines += _severity(results["severity"])
    if "pipeline" in results:
        lines += _pipeline(results["pipeline"], "## End to end (offline: no LLM steps)")
    if live and "pipeline" in live:
        lines += _pipeline(live["pipeline"], "## End to end with a live LLM")
        lines.insert(
            len(lines) - 1,
            f"_Live run on {live['created_at']} through the configured provider chain "
            "(NVIDIA NIM first). Latency depends on the provider's load at the time._",
        )
    if "robustness" in results:
        lines += _robustness(results["robustness"])
    lines += [
        "## Limitations",
        "",
        (
            "- The scenarios reuse a few thousand public sample lines, so templates repeat across "
            "windows more than in a real fleet."
        ),
        (
            "- The severity labels follow a rubric and a policy written for this project; a real "
            "deployment should recalibrate on its own reviewed incidents (reviewer corrections are "
            "recorded for that)."
        ),
        (
            "- Offline runs measure the deterministic path. LLM steps can only choose within the "
            "conformal set for severity, and their report text must pass the same validation, so "
            "they change wording and investigation order more than outcomes."
        ),
        (
            "- The offline investigator tests hypotheses with simple, transparent checks (where "
            "errors and new warnings sit, how many nodes they reach, what similar incidents and "
            "runbooks say). The scenarios make the failing component clear; real incidents with "
            "several overlapping problems will be harder."
        ),
        (
            "- Accuracy varies by system (see the table): systems whose failure modes share "
            "templates with routine traffic are the hardest, and the conservative fallback "
            "over-triages rather than under-triages when the model is unsure."
        ),
        (
            "- Contiguous BGL windows and the UCI incident log could not be downloaded in the build "
            "environment, so no results on them are reported."
        ),
        "",
    ]
    return "\n".join(lines)
