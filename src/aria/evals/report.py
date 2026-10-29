"""Render evaluation results as ``docs/evaluation.md`` and as the results quoted in other docs.

Docs that quote results hold them in generated blocks, which ``make eval`` rewrites::

    <!-- generated:results -->
    ...
    <!-- /generated:results -->
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Docs with generated blocks, rewritten by `make eval` alongside docs/evaluation.md.
QUOTING_DOCS = (Path("README.md"), Path("docs/model-card.md"))
_BLOCK = re.compile(
    r"(?P<open><!-- generated:(?P<name>[a-z-]+) -->\n)"
    r"(?P<body>.*?)"
    r"(?P<close><!-- /generated:(?P=name) -->)",
    re.DOTALL,
)

METHOD_NAMES = {
    "aria_policy": "ARIA policy (offline)",
    "model_with_floors": "Calibrated model + rule floors",
    "model_only": "Calibrated model only",
    "rules_only": "Rules only",
    "keyword": "Keyword categories only",
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


def _severity(section: Mapping[str, Any], heading: str = "## Severity") -> list[str]:
    lines = [
        heading,
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
    risk = section.get("risk_coverage") or {"points": [], "aurc": 0.0}
    if "tfidf_logreg" in section["methods"]:
        lines += [
            "",
            (
                "The text baseline reads each window's raw lines, minus the alert tag that BGL and "
                "Thunderbird lines open with: the BGL labels come from that tag."
            ),
        ]
    curve = ", ".join(
        f"{_pct(p['risk'])} error at {_pct(p['coverage'])} coverage" for p in risk["points"]
    )
    lines += [
        "",
        f"Calibration of the model's probabilities: ECE {cal['ece']:.3f}, Brier {cal['brier']:.3f}.",
        "",
        (
            "Risk–coverage (the calibrated model answering only its most confident windows): "
            f"{curve or 'n/a'}; AURC {risk['aurc']:.3f}."
        ),
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
            f"Recall@3 {_pct(r['recall_at_3'])}, MRR {r['mrr']:.3f}, nDCG@3 "
            f"{r.get('ndcg_at_3', 0.0):.3f} (a hit shares the true failure mode)."
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
        *_providers(section.get("providers") or {}),
    ]


def _detection_row(label: str, r: Mapping[str, Any]) -> str:
    healthy = r["fp"] + r["tn"]
    return (
        f"| {label} | {_pct(r['precision'])} ({_ci(r['precision_ci95'])}) | "
        f"{_pct(r['recall'])} ({_ci(r['recall_ci95'])}) | {r['f1']:.3f} | "
        f"{r['fp']:,} of {healthy:,} ({_pct(r['false_alarm_rate'])}) |"
    )


def _real(section: Mapping[str, Any]) -> list[str]:
    hdfs = section.get("hdfs") or {}
    lines = ["## Real logs, expert labels", ""]
    if "missing" in hdfs:
        return [*lines, f"The HDFS sample is not downloaded: {hdfs['missing']}.", ""]
    if hdfs.get("fixture"):
        lines += [
            (
                "> **These numbers come from the small committed HDFS cut, not the full sample.** "
                "Run `aria data download --source hdfs-100k` and regenerate before quoting them."
            ),
            "",
        ]
    rp, life, steps = hdfs["replay"], hdfs["lifecycle"], hdfs["steps"]
    base, head = hdfs["baselines"], hdfs.get("contiguous")
    failures, unjudged = (
        hdfs["anomalous_blocks"],
        hdfs["anomalous_blocks"] - hdfs["judged_anomalous"],
    )
    extent = (
        f"the first {head['lines']:,} lines ({head['minutes']} minutes) of the log of a Hadoop "
        f"cluster of more than 200 nodes, plus {head['tail_lines']:,} later lines of the blocks "
        f"those lines started ({hdfs['lines']:,} lines over {hdfs['minutes']} minutes; no block "
        "starts in that tail)"
        if head
        else f"{hdfs['lines']:,} lines ({hdfs['minutes']} minutes) of the log of a Hadoop cluster "
        "of more than 200 nodes"
    )
    lines += [
        (
            f"Real lines that no scenario builder touched: {extent}, and the label Hadoop experts "
            f"gave each of its {hdfs['blocks']:,} storage blocks ({failures} failed). Source: "
            f"{hdfs['source']}; {hdfs['citation']}"
        ),
        "",
        (
            "This is an offline replay of ARIA's lifecycle check, not of the deployed log scan: "
            f"{rp['windows']} overlapping {rp['window_min']:g}-minute windows, one every "
            f"{rp['step_min']:g} minutes, each parsed by the production parser. The parser learns "
            "from each window which steps of a block's life come in equal numbers, and flags "
            "blocks that break them. It never sees a label. Each block was judged in the first "
            f"window that saw it from start to finish: {hdfs['judged']:,} of the "
            f"{hdfs['blocks']:,} blocks ({_pct(hdfs['coverage'])}), {hdfs['judged_anomalous']} of "
            f"them failures. The cluster logged up to {hdfs['peak_lines_per_min']:,} lines a "
            f"minute, so the replay raises the per-run line cap from {rp['default_max_lines']:,} to "
            f"{rp['max_lines']:,}. The deployed scan opens a run on a burst of ERROR or FATAL "
            "lines, and this log has none, so on its own it would not open a run here."
        ),
        "",
        "| Method, per judged block | Precision (95% CI) | Recall (95% CI) | F1 | False alarms |",
        "|---|---|---|---|---|",
        _detection_row("ARIA lifecycle check, one window at a time", life),
        _detection_row("Rare step counts (shared by fewer than 1% of blocks)", base["rare_steps"]),
        _detection_row("Count-equality pairs mined over the whole sample", base["count_pairs"]),
        _detection_row("PCA on event counts (Xu et al. 2009)", base["pca"]),
        _detection_row("Isolation forest on event counts", base["isolation_forest"]),
        _detection_row(
            "ARIA severity engine, each block on its own (no lifecycle check)",
            base["engine_per_block"],
        ),
        _detection_row("Keyword categories, each block on its own", base["keyword_per_block"]),
        "",
        (
            "Intervals are exact (Clopper-Pearson). No baseline uses a label. The four standard "
            "detectors read the experts' event templates and fit on the whole sample at once; "
            "ARIA parses each window itself and sees one window at a time."
        ),
        "",
        (
            f"- **Recall over every labelled failure**: {life['tp']} of {failures} "
            f"({_pct(hdfs['recall_all'])}, {_ci(hdfs['recall_all_ci95'])}). The {unjudged} "
            "failures in blocks that no window saw from start to finish were never judged."
        ),
        (
            f"- **What the misses look like**: ARIA flagged all {steps['distinct']['caught']} "
            "failures whose step counts no healthy block shares, and "
            f"{steps['look_alike']['caught']} of the {steps['look_alike']['failures']} whose "
            f"counts some healthy blocks share. Each of the {steps['missed']['failures']} it "
            "missed takes exactly the steps, the same number of times, of one of "
            f"{steps['missed']['patterns']} common healthy patterns, each shared by at least "
            f"{steps['missed']['healthy_twins_min']:,} healthy blocks, so step counts alone "
            "cannot set them apart."
        ),
    ]
    if head:
        lines.append(
            f"- **The log as written, without the tail**: on the first {head['lines']:,} lines "
            f"alone, ARIA judged {head['judged']:,} blocks and flagged {head['tp'] + head['fp']}, "
            f"{_pct(head['precision'])} of them real failures: {_pct(head['recall_all'])} of all "
            f"{failures} labelled failures. The tail completes blocks the head cuts off."
        )
    lines.append(
        "- **How the flagged failures broke**: "
        + "; ".join(f"{p['pattern']} ({p['blocks']})" for p in hdfs["top_patterns"])
        + "."
    )
    if hdfs["false_alarms"]:
        lines.append(
            "- **False alarms**: "
            + "; ".join(f"{f['block']}: {f['reason']}" for f in hdfs["false_alarms"])
            + "."
        )
    severities = Counter(w.get("severity") for w in hdfs["windows"] if w.get("severity"))
    if severities:
        lines.append(
            "- **Severity**: ARIA's offline policy rated the windows "
            + ", ".join(f"{n} × {sev}" for sev, n in sorted(severities.items()))
            + "."
        )
    overlap = hdfs.get("overlap_with_scenario_pool")
    if overlap:
        lines.append(
            f"- **Overlap with training data**: {overlap['lines']} of these lines "
            f"({overlap['blocks']} blocks) also appear in the Loghub HDFS 2k sample the scenario "
            "builder draws on. The lifecycle check uses no trained model; the severity baseline does."
        )
    lines += [
        "",
        (
            "How much the result depends on the window length, the setting that matters most: a "
            "block can only be judged in a window that holds its whole life. ARIA uses "
            f"{rp['window_min']:g} minutes."
        ),
        "",
        "| Window | Judged | Precision | Recall, judged | Recall, all failures | False alarms |",
        "|---|---|---|---|---|---|",
        *(
            f"| {r['window_min']:g} min | {r['judged']:,} | {_pct(r['precision'])} | "
            f"{_pct(r['recall'])} | {_pct(r['recall_all'])} | {r['fp']} |"
            for r in hdfs["window_lengths"]
        ),
        "",
        (
            "And on two settings of the check: the share of a window's blocks on which a step pair "
            "must hold, and how long ARIA waits before judging a block (the quantile of complete "
            f"blocks' durations). ARIA uses {rp['min_support']:g} and {rp['settle_quantile']:g}. "
            "These were chosen on this log, with its labels in view; no other system has been "
            "measured."
        ),
        "",
        "| Pair support | Settle quantile | Judged | Precision | Recall | F1 | False alarms |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {r['min_support']:g} | {r['settle_quantile']:g} | {r['judged']:,} | "
            f"{_pct(r['precision'])} | {_pct(r['recall'])} | {r['f1']:.3f} | {r['fp']} |"
            for r in hdfs["sensitivity"]
        ),
        "",
        (
            "At a pair support of 0.98, a window in which more than 2% of blocks fail stops ARIA "
            "learning the pair those failures break, which is why ARIA uses 0.95."
        ),
        "",
    ]
    return lines


def _cost(value: float | None) -> str:
    return "not priced" if value is None else f"${value:.4f}"


def _providers(providers: Mapping[str, Mapping[str, Any]]) -> list[str]:
    if not providers:
        return []
    rows = [
        f"| {name} | {', '.join(p['models']) or 'n/a'} | {p['calls']} | {p['failures']} | "
        f"{p['latency_p50_ms'] / 1000:.1f} | {p['latency_p95_ms'] / 1000:.1f} | "
        f"{p['tokens_in']} / {p['tokens_out']} | "
        f"{_cost(p['cost_usd'])} |"
        for name, p in providers.items()
    ]
    return [
        "| Provider | Models | Calls | Failed | p50 s | p95 s | Tokens in / out | Cost |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]


def _parsing(section: Mapping[str, Any]) -> list[str]:
    rows = [
        f"| {system} | {r['lines']} | {r['events']} | {r['templates']} | "
        f"{r['grouping_accuracy']:.3f} |"
        for system, r in section["systems"].items()
    ]
    return [
        "## Log parsing",
        "",
        (
            f"Grouping accuracy against Loghub's hand-labelled templates, {section['lines']} lines "
            f"from {section['n_systems']} systems, through the production parser (redaction, "
            "injection guard, per-system Drain settings from the Loghub benchmark). Mean "
            f"{section['mean_grouping_accuracy']:.3f}. Real log lines flagged as injection: "
            f"{section['real_lines_flagged_as_injection']}."
        ),
        "",
        "| System | Lines | True events | Templates found | Grouping accuracy |",
        "|---|---|---|---|---|",
        *rows,
        "",
    ]


def _edge(section: Mapping[str, Any]) -> list[str]:
    families = ", ".join(
        f"{family.replace('_', ' ')} {_pct(recall)}"
        for family, recall in section["recall_by_family"].items()
    )
    return [
        "## Edge cases and prompt injection",
        "",
        (
            f"{section['n']} inputs, each parsed on its own: {section['attacks']} injection "
            f"attempts in eleven families, hidden in messages, usernames, request paths and user "
            f"agents, and {section['benign']} benign inputs (malformed and extreme lines, and log "
            "messages that use the same words for ordinary reasons)."
        ),
        "",
        f"- Parser errors: {section['parser_errors']}.",
        f"- Attacks quarantined: {_pct(section['attack_recall'])} ({families}).",
        f"- Benign inputs quarantined: {_pct(section['benign_false_positive_rate'])}.",
        (
            "- The attack families come from public prompt-injection taxonomies, but this project "
            "wrote both the corpus and the detector, and the detector was tuned on it (URL "
            "encoding, leetspeak, base64 and five other languages were added after the first run "
            "missed them). Treat the recall as an upper bound. An attack that is not caught is "
            "analysed as an ordinary log line, and reaches a model only as fenced, untrusted "
            "evidence."
        ),
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
            "**Data.** The first section uses real logs with labels from the system's experts. "
            "Every other number comes from semi-synthetic incident windows: real lines from "
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
    if "real" in results:
        lines += _real(results["real"])
    if "severity" in results:
        lines += _severity(results["severity"])
    if "pipeline" in results:
        lines += _pipeline(results["pipeline"], "## End to end (offline: no LLM steps)")
    if live and "pipeline" in live:
        lines += _pipeline(live["pipeline"], "## End to end with a live LLM")
        lines += [
            (
                f"_Live run on {live['created_at']} (commit {live.get('git_sha') or 'unknown'}) "
                "through the configured provider chain, NVIDIA NIM first. Latency depends on the "
                "provider's load at the time._"
            ),
            "",
        ]
    if "parsing" in results:
        lines += _parsing(results["parsing"])
    if "edge" in results:
        lines += _edge(results["edge"])
    if "robustness" in results:
        lines += _robustness(results["robustness"])
    lines += [
        "## Limitations",
        "",
        (
            "- Every split draws its lines from the same public 2,000-line samples, and some "
            "failure modes rest on a handful of distinct messages. Test windows therefore reuse "
            "messages and templates seen in training, and templates repeat more than in a real "
            "fleet."
        ),
        (
            "- The severity labels follow a rubric and a policy written for this project. Outside "
            "BGL, the policy labels a window from its true node count and peak error rate, which "
            "ARIA's features estimate: not circular, but closer to ARIA's view than real on-call "
            "labels would be. A deployment's own incidents differ, so ARIA recalibrates its "
            "prediction sets on reviewed incidents once enough reviews have gathered "
            "(`aria train recalibrate`)."
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
            "- The real-log section covers one system (HDFS) and one kind of failure signal: units "
            "of work that stop partway. Its labels say whether a block failed, not how severe the "
            "incident was, so it measures detection, not severity."
        ),
        (
            "- Contiguous BGL windows and the UCI incident log could not be downloaded in the build "
            "environment, so no results on them are reported."
        ),
        "",
    ]
    return "\n".join(lines)


def _provenance(results: Mapping[str, Any], *, real: bool = False) -> str:
    seeds = ", ".join(map(str, results["data"]["test_seeds"]))
    which = "Apart from the real-log results, the data" if real else "The data"
    return (
        f"Generated by `make eval` at commit `{results.get('git_sha') or 'unknown'}`; do not edit "
        f"by hand. {which} is **semi-synthetic**: real lines from the public Loghub samples, "
        f"composed into incidents by ARIA's scenario builder, on held-out seeds {seeds}. These "
        "numbers show how ARIA behaves on that distribution, not its accuracy on production "
        "incidents."
    )


def _real_summary(section: Mapping[str, Any]) -> list[str]:
    hdfs = section.get("hdfs") or {}
    if "lifecycle" not in hdfs:
        return []
    life, base = hdfs["lifecycle"], hdfs["baselines"]
    standard = {
        "PCA (Xu et al. 2009)": base["pca"],
        "an isolation forest": base["isolation_forest"],
    }
    detectors = [base["rare_steps"], base["count_pairs"], *standard.values()]
    flagged = life["tp"] + life["fp"]
    note = " (from the small committed cut, not the full sample)" if hdfs.get("fixture") else ""
    lead = (
        "matches or beats each standard detector on the same blocks"
        if all(life["f1"] >= d["f1"] for d in detectors)
        else "compares with standard detectors on the same blocks"
    )
    return [
        (
            f"**Real logs, expert labels**{note}: on a real Hadoop cluster's log (more than 200 "
            "nodes, every storage block labelled by Hadoop experts), ARIA's lifecycle check "
            f"flagged {flagged} of the {hdfs['judged']:,} blocks it judged, "
            f"{_pct(life['precision'])} of them real failures ({life['fp']} false alarms among "
            f"{life['fp'] + life['tn']:,} healthy blocks): {_pct(life['recall'])} of the "
            f"{hdfs['judged_anomalous']} failures it judged, {_pct(hdfs['recall_all'])} of all "
            f"{hdfs['anomalous_blocks']} in the sample. It {lead}, though they see the whole "
            "sample at once: "
            + ", ".join(
                f"{name} finds {_pct(d['recall'])} with {d['fp']} false alarms"
                for name, d in standard.items()
            )
            + ", and a rule that flags rare step counts ties it. An offline replay of the "
            "check, not of the deployed log scan."
        ),
        "",
    ]


def _results(results: Mapping[str, Any], live: Mapping[str, Any] | None) -> list[str]:
    """The README's summary: headline numbers, each linked to its section of the full report."""
    lines = [_provenance(results, real="real" in results), ""]
    if results["data"].get("fixtures"):
        lines += ["**These numbers come from the small test fixtures.** Run `make data` first.", ""]
    if "real" in results:
        lines += _real_summary(results["real"])
    if "severity" in results:
        sev = results["severity"]
        lines += [
            f"**Severity**, {sev['n']} held-out windows:",
            "",
            "| Method | Accuracy (95% CI) | Macro-F1 | SEV1/2 rated SEV3/4 |",
            "|---|---|---|---|",
        ]
        for key in ("aria_policy", "tfidf_logreg", "rules_only", "keyword", "majority_class"):
            r = sev["methods"].get(key)
            if r is not None:
                lines.append(
                    f"| {METHOD_NAMES[key]} | {_pct(r['accuracy'])} ({_ci(r['accuracy_ci95'])}) | "
                    f"{r['macro_f1']:.3f} | {_pct(r['severe_under_triage'])} |"
                )
        cal, conf, auto = sev["calibration"], sev["conformal"], sev["automation"]
        lines += [
            "",
            (
                f"- Calibration: ECE {cal['ece']:.3f}. Conformal prediction sets hold the true "
                f"severity in {_pct(conf['coverage_with_floors'])} of windows (target "
                f"{_pct(conf['target_coverage'])}), with {conf['mean_set_size']} labels on average."
            ),
            (
                f"- Automation: {_pct(auto['auto_decided'])} of windows are decided without review, "
                f"at {_pct(auto['accuracy_when_auto'])} accuracy; the rest go to a reviewer."
            ),
            "",
        ]
    if "pipeline" in results:
        pipe = results["pipeline"]
        g, r, lat = pipe["groundedness"], pipe["retrieval"], pipe["latency"]
        lines += [
            (
                f"**End to end**, {pipe['n']} offline runs through the whole graph: "
                f"{_pct(g['valid_reports'])} of reports pass validation and "
                f"{_pct(g['every_claim_cited'])} cite existing evidence for every claim; similar "
                f"incidents Recall@3 {_pct(r['recall_at_3'])}; time to review p50 "
                f"{lat['time_to_review_p50_s']:.2f} s, p95 {lat['time_to_review_p95_s']:.2f} s."
            ),
            "",
        ]
    if live and "pipeline" in live:
        pipe = live["pipeline"]
        g, lat = pipe["groundedness"], pipe["latency"]
        lines += [
            (
                f"**With a live LLM** (NVIDIA NIM, {pipe['n']} runs at commit "
                f"`{live.get('git_sha') or 'unknown'}`): the LLM wrote "
                f"{g['written_by'].get('llm', 0)} of the {pipe['n']} reports, and "
                f"{_pct(g['every_claim_cited'])} cite evidence for every claim; time to review p50 "
                f"{lat['time_to_review_p50_s']:.1f} s, mostly waiting on the provider (LLM call p50 "
                f"{lat['llm_call_p50_ms'] / 1000:.1f} s)."
            ),
            "",
        ]
    if "parsing" in results:
        parsing = results["parsing"]
        lines += [
            (
                f"**Log parsing**: grouping accuracy {parsing['mean_grouping_accuracy']:.3f} against "
                f"Loghub's labelled templates ({parsing['lines']:,} lines, {parsing['n_systems']} "
                "systems)."
            ),
            "",
        ]
    if "edge" in results and "robustness" in results:
        edge, rob = results["edge"], results["robustness"]
        lines += [
            (
                f"**Prompt injection**: the guard quarantined {_pct(edge['attack_recall'])} of "
                f"{edge['attacks']:,} attacks (an upper bound: the detector was tuned on this corpus) "
                f"and {_pct(edge['benign_false_positive_rate'])} of {edge['benign']:,} benign inputs. With "
                f"{rob['attacks_per_case']} injected lines in each of {rob['n']} incident windows, "
                f"severity was unchanged in {_pct(rob['severity_invariant'])} and tool calls in "
                f"{_pct(rob['tool_use_invariant'])}."
            ),
            "",
        ]
    lines.append("Every section, with its method: [docs/evaluation.md](docs/evaluation.md).")
    return lines


def blocks(results: Mapping[str, Any], live: Mapping[str, Any] | None = None) -> dict[str, str]:
    """The content of each generated block, by name."""
    out = {"results": "\n".join(_results(results, live))}
    if "severity" in results:
        out["severity-metrics"] = "\n".join(
            [
                _provenance(results),
                "",
                *_severity(results["severity"], heading="### Held-out results"),
            ]
        ).rstrip()
    return out


def fill(text: str, content: Mapping[str, str]) -> str:
    """``text`` with every generated block rewritten from ``content``."""

    def swap(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in content:
            raise ValueError(f"no content for the generated block {name!r}")
        return f"{match['open']}{content[name].rstrip()}\n{match['close']}"

    return _BLOCK.sub(swap, text)
