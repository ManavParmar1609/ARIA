"""Render evaluation results as ``docs/evaluation.md`` and as the results quoted in other docs.

Docs that quote results hold them in generated blocks, which ``make eval`` rewrites::

    <!-- generated:results -->
    ...
    <!-- /generated:results -->
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
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
            "ARIA parses each window itself and sees one window at a time. The severity engine "
            "rarely flags a block on its own: a block is a handful of lines, far from the windows "
            "its model learned from, so the model steps aside and the rules alone decide."
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


_BGL_METHODS = {
    "aria_policy": "ARIA (rules, model and policy, offline)",
    "rules_only": "The rules alone",
    "model_only": "The model alone",
    "keyword": "Keyword categories",
    "highest_level": "Highest log level in the window",
    "majority_class": "The commonest label",
}


def _bgl(section: Mapping[str, Any]) -> list[str]:
    lines = ["## Real logs, a supercomputer's alert tags", ""]
    if "missing" in section:
        return [*lines, f"No results: {section['missing']}.", ""]
    labels, methods = section["labels"], section["methods"]
    severe = sum(n for c, n in labels.items() if c in ("SEV1", "SEV2"))
    quiet = labels.get("SEV4", 0)
    aria, conf, auto = methods["aria_policy"], section["conformal"], section["automation"]
    overlap = section["overlap_with_training_sample"]
    classes = section["confusion"]["classes"]
    return [
        *lines,
        (
            f"The whole log of LLNL's BlueGene/L supercomputer: {section['lines']:,} lines over "
            f"{section['days']:g} days, {section['alert_lines']:,} of them tagged as alerts by "
            f"the machine's administrators. Source: {section['source']}; {section['citation']} "
            f"ARIA rated every {section['window_min']}-minute window that holds lines "
            f"({section['windows']:,} windows) from the lines alone: the tags are removed before "
            "parsing, and nothing was tuned on this log. Each window's label comes from its tags "
            "through the rubric that also labels the BGL training scenarios: "
            + ", ".join(f"{n:,} × {c}" for c, n in labels.items())
            + "."
        ),
        "",
        (
            "| Method | Accuracy (95% CI) | Macro-F1 (95% CI) | "
            f"SEV1-2 windows rated SEV3-4 (of {severe:,}) | SEV4 windows rated SEV1-2 "
            f"(of {quiet:,}) |"
        ),
        "|---|---|---|---|---|",
        *(
            f"| {label} | {_pct(methods[key]['accuracy'])} ({_ci(methods[key]['accuracy_ci95'])}) "
            f"| {methods[key]['macro_f1']:.3f} ({_ci(methods[key]['macro_f1_ci95'], percent=False)}) "
            f"| {methods[key]['severe_missed']:,} | {methods[key]['quiet_paged']:,} |"
            for key, label in _BGL_METHODS.items()
            if key in methods
        ),
        "",
        (
            "- **Recall by label** (ARIA): "
            + ", ".join(f"{c} {_pct(r)}" for c, r in aria["recall"].items())
            + "."
        ),
        (
            f"- **Prediction sets** held the label for {_pct(conf['coverage'])} of windows "
            f"(target {_pct(conf['target_coverage'])}), with {conf['mean_set_size']} levels on "
            f"average. {_pct(auto['auto_decided'])} of windows were decided without review, at "
            f"{_pct(auto['accuracy_when_auto'])} accuracy."
        ),
        (
            f"- **Overlap with training data**: {_pct(overlap['share'])} of these lines carry a "
            "message that also appears in Loghub's 2,000-line BGL sample, which the training "
            "scenarios are composed from. The scenarios re-time and recombine those lines; no "
            "window here was seen in training."
        ),
        (
            f"- **Lines left out or cut**: {section['lines_without_time']:,} lines carry no "
            f"timestamp and cannot be placed in a window. {section['windows_over_line_cap']:,} "
            f"windows hold more than the per-run line cap of {section['line_cap']:,}; ARIA reads "
            "their first lines up to the cap, as a deployment would."
        ),
        "",
        "Where ARIA's ratings fell (rows: the rubric's label; columns: ARIA):",
        "",
        "| Label | " + " | ".join(classes) + " |",
        "|---|" + "---|" * len(classes),
        *(
            f"| {c} | " + " | ".join(f"{n:,}" for n in row) + " |"
            for c, row in zip(classes, section["confusion"]["matrix"], strict=True)
        ),
        "",
    ]


_HADOOP_LABELS = {
    "normal": "Healthy",
    "machine_down": "Machine down",
    "network_disconnection": "Network disconnection",
    "disk_full": "Disk full",
}


def _flagged(d: Mapping[str, Any]) -> str:
    return (
        f"{d['failed_flagged']} of {d['failed']} ({_pct(d['recall'])}, {_ci(d['recall_ci95'])}) "
        f"| {d['normal_flagged']} of {d['normal']} |"
    )


def _hadoop(section: Mapping[str, Any]) -> list[str]:
    lines = ["## Real failures, a Hadoop cluster's jobs", ""]
    if "missing" in section:
        return [*lines, f"No results: {section['missing']}.", ""]
    labels = section["by_label"]
    order = [k for k in _HADOOP_LABELS if k in labels]
    sevs = ("SEV1", "SEV2", "SEV3", "SEV4")
    base = section["baselines"]
    return [
        *lines,
        (
            f"Every container log of {section['jobs']} MapReduce jobs on a real Hadoop cluster "
            f"({section['lines']:,} lines): "
            + ", ".join(f"{labels[k]} {_HADOOP_LABELS[k].lower()}" for k in order)
            + f". Source: {section['source']}; {section['citation']} Each job was triaged "
            "offline, end to end, as one run, and ARIA never saw its label. A job counts as "
            f"flagged when ARIA rates it SEV1-SEV3. {section['capped_jobs']} jobs hold more than "
            f"the per-run line cap of {section['line_cap']:,}; ARIA reads their first lines up to "
            "the cap, as a deployment would."
        ),
        "",
        "| Method | Failed jobs flagged (95% CI) | Healthy jobs flagged |",
        "|---|---|---|",
        f"| ARIA, end to end | {_flagged(section['aria'])}",
        f"| Any ERROR or FATAL line | {_flagged(base['any_error_line'])}",
        f"| Keyword categories | {_flagged(base['keyword'])}",
        "",
        "| Label | Jobs | " + " | ".join(sevs) + " | ARIA's leading hypothesis |",
        "|---|---|" + "---|" * len(sevs) + "---|",
        *(
            f"| {_HADOOP_LABELS[k]} | {labels[k]} | "
            + " | ".join(str(section["severity_by_label"][k].get(s, 0)) for s in sevs)
            + " | "
            + ", ".join(
                f"{_MODE_NAMES.get(mode, mode.replace('_', ' '))} ({n})"
                for mode, n in section["leading_mode_by_label"][k].items()
            )
            + " |"
            for k in order
        ),
        "",
        (
            "ARIA's catalog has a mode for tasks that cannot reach the ResourceManager and one for "
            "HDFS lease renewal failures, but none for a full disk. "
            f"{_pct(section['overlap_with_training_sample'])} of these lines carry a message that "
            "also appears in Loghub's 2,000-line Hadoop sample, which the training scenarios are "
            "composed from."
        ),
        "",
    ]


def _share(d: Mapping[str, Any]) -> str:
    return f"{d['flagged']} of {d['of']} ({_pct(d['share'])}, {_ci(d['ci95'])})"


_SUBSYSTEMS = {
    "Nova": "Nova (compute)",
    "Cinder": "Cinder (volumes)",
    "Neutron": "Neutron (networks)",
}


def _auroc(d: Mapping[str, Any]) -> str:
    return f"{d['auroc']:.3f} ({_ci(d['auroc_ci95'], percent=False)})"


def _unsure(section: Mapping[str, Any]) -> str:
    review = section["review"]
    decided = review["decided"]
    text = (
        f"ARIA was unsure of {_share(review['failed'])} failed runs and "
        f"{_share(review['healthy'])} healthy runs: their prediction set held several labels, so "
        "the conservative policy chose the most severe of them and sent the run to a reviewer."
    )
    total = decided["failed"] + decided["normal"]
    if total and not decided["normal"]:
        text += (
            f" Every one of the {total} runs it decided by itself had failed, and it flagged "
            f"{decided['failed_flagged']} of them."
        )
    elif total:
        text += (
            f" Of the {total} runs it decided by itself, it flagged "
            f"{decided['failed_flagged']} of {decided['failed']} failed and "
            f"{decided['normal_flagged']} of {decided['normal']} healthy."
        )
    return text


def _capped(capped: int, cap: int) -> str:
    if not capped:
        return f"No run holds more than the per-run line cap of {cap:,}."
    many = "runs hold" if capped > 1 else "run holds"
    return f"{capped:,} {many} more than the per-run line cap of {cap:,}; ARIA reads up to the cap."


def _all_of(hits: int, of: int) -> str:
    return f"all {of:,}" if hits == of and of > 1 else f"{hits:,} of the {of:,}"


def _openstack(section: Mapping[str, Any]) -> list[str]:
    lines = ["## Real failures, bugs injected into OpenStack", ""]
    if "missing" in section:
        return [*lines, f"No results: {section['missing']}.", ""]
    aria, base = section["aria"], section["baselines"]
    errors = base["any_error_line"]
    subsystems = section["by_subsystem"]
    sevs = ("SEV1", "SEV2", "SEV3", "SEV4")
    outcomes = {"failed": "Failed", "healthy": "Did not fail"}
    ranks = {"ARIA's probability of SEV1-2": aria, "ERROR and CRITICAL lines, counted": errors}
    return [
        *lines,
        (
            f"{section['experiments']} fault-injection experiments on OpenStack ("
            + ", ".join(f"{n} in {k}" for k, n in subsystems.items())
            + f"; {section['lines']:,} lines). In each, one bug was injected into the code (a "
            "wrong return value, a missing call, a thrown exception, wrong or missing "
            "parameters) and a workload then created and used VMs, volumes and networks. "
            f"{section['failed']} runs failed: {section['reported']} with an API error that told "
            f"the user, and {section['silent']} silently, caught only by the experimenters' own "
            "checks. A healthy run is one whose bug caused no failure. "
            f"Source: {section['source']}; {section['citation']} Each run's service logs "
            "from the faulty round were triaged offline, end to end, as one run; ARIA never saw "
            "the label, the client's output or the injector's traces. A run counts as flagged "
            "when ARIA rates it SEV1-SEV3, and as paged at SEV1-2, the level the BGL section counts "
            f"as severe. {_capped(section['capped'], section['line_cap'])}"
        ),
        "",
        "| Method | Failed runs flagged (95% CI) | Healthy runs flagged |",
        "|---|---|---|",
        f"| ARIA, end to end | {_flagged(aria)}",
        f"| ARIA, paging only (SEV1-2) | {_flagged(aria['paged'])}",
        f"| ARIA's rules alone | {_flagged(base['rules_only'])}",
        f"| Any ERROR or CRITICAL line | {_flagged(errors)}",
        f"| Keyword categories | {_flagged(base['keyword'])}",
        "",
        _unsure(section),
        "",
        "| Failed runs | ARIA flagged | Any ERROR or CRITICAL line |",
        "|---|---|---|",
        f"| Reported by an API error | {_share(aria['reported'])} | {_share(errors['reported'])} |",
        f"| Silent: no API error | {_share(aria['silent'])} | {_share(errors['silent'])} |",
        "",
        (
            "An API error is the signal the user already had: it reports every failure in the "
            "first row and none in the second."
        ),
        "",
        (
            "Free of any threshold: how well each score ranks failed runs above healthy ones "
            "(AUROC; 0.5 is chance, 1 is perfect)."
        ),
        "",
        "| Score | Every run (95% CI) | Silent failures against healthy runs |",
        "|---|---|---|",
        *(
            f"| {name} | {_auroc(d['ranking']['all'])} | {_auroc(d['ranking']['silent'])} |"
            for name, d in ranks.items()
        ),
        "",
        "| Bug injected into | Failed runs flagged | Healthy runs flagged |",
        "|---|---|---|",
        *(
            f"| {_SUBSYSTEMS.get(k, k)} | {_flagged(d)}"
            for k, d in section["by_subsystem_detail"].items()
        ),
        "",
        "| Outcome | " + " | ".join(sevs) + " | ARIA's leading hypothesis |",
        "|---|" + "---|" * len(sevs) + "---|",
        *(
            f"| {label} | "
            + " | ".join(str(section["severity_by_outcome"][k].get(s, 0)) for s in sevs)
            + " | "
            + ", ".join(
                f"{_MODE_NAMES.get(mode, mode.replace('_', ' '))} ({n})"
                for mode, n in section["leading_mode_by_outcome"][k].items()
            )
            + " |"
            for k, label in outcomes.items()
        ),
        "",
        (
            f"{_pct(section['overlap_with_training_sample'])} of these lines carry a message that "
            "also appears in Loghub's 2,000-line OpenStack sample, which the training scenarios "
            "are composed from; that sample comes from another OpenStack deployment."
        ),
        "",
    ]


_MODE_NAMES = {
    "resourcemanager_unreachable": "ResourceManager unreachable",
    "hdfs_lease_renewal": "HDFS lease renewal",
    "component_errors": "errors in one component",
    "none": "no hypothesis held",
}


_INJECTION_SOURCES = {
    "bipia": "BIPIA, indirect injections in text and code tasks (Yi et al.)",
    "injecagent": "InjecAgent, instructions planted in tool outputs (Zhan et al.)",
    "cyberseceval": "CyberSecEval 2, prompt-injection cases (Meta)",
    "tensor_trust": "Tensor Trust, hijacking attacks written by players (Toyer et al.)",
    "giskard": "Giskard's curated collection",
    "jailbreaks": "Jailbreak prompts collected in the wild (Shen et al.)",
}


def _injection(section: Mapping[str, Any]) -> list[str]:
    lines = ["## Prompt injection, public benchmarks", ""]
    if "missing" in section:
        return [*lines, f"No results: {section['missing']}.", ""]
    total, sources = section["attacks"], section["by_source"]
    lines += [
        (
            "The edge-case attacks above were written by this project, which also wrote the "
            "detector. These were written by others, and the detector was never tuned on them. "
            "Each attack is flattened to one line, hidden in a log line the way the edge-case "
            "suite hides its own, and parsed by the production parser on its own."
        ),
        "",
        "| Benchmark | Attacks | Caught (95% CI) |",
        "|---|---|---|",
        *(
            f"| {_INJECTION_SOURCES.get(key, key)} | {r['n']:,} | {r['flagged']:,} "
            f"({_pct(r['rate'])}, {_ci(r['ci95'])}) |"
            for key, r in sources.items()
        ),
        (
            f"| All | {total['n']:,} | {total['flagged']:,} ({_pct(total['rate'])}, "
            f"{_ci(total['ci95'])}) |"
        ),
        "",
    ]
    benign = section.get("benign")
    if benign:
        lines.append(
            f"- **Over-defence**: of NotInject's {benign['n']} benign sentences that use the words "
            f"injections use, the detector flagged {benign['flagged']} ({_pct(benign['rate'])}, "
            f"{_ci(benign['ci95'])}): "
            + ", ".join(
                f"{g['flagged']} of {g['n']} with {name}" for name, g in benign["groups"].items()
            )
            + "."
        )
    real = section.get("real_lines") or {}
    if real:
        n = sum(r["n"] for r in real.values())
        hits = sum(r["flagged"] for r in real.values())
        names = {"hdfs": "HDFS", "bgl": "BGL", "hadoop": "Hadoop"}
        parts = ", ".join(f"{names.get(k, k)} {r['n']:,}" for k, r in real.items())
        if hits == 0:
            bound = 1 / (1 - 0.025 ** (1 / n))
            lines.append(
                f"- **Real traffic**: none of the {n:,} real log lines the other evaluations read "
                f"was flagged ({parts}); at 95% confidence the rate is below one line in "
                f"{round(bound):,}."
            )
        else:
            lines.append(
                f"- **Real traffic**: {hits:,} of the {n:,} real log lines the other evaluations "
                f"read were flagged ({parts})."
            )
    lines += [
        (
            "- **What it misses**: attacks phrased as ordinary requests (most of BIPIA's and "
            "InjecAgent's), which no pattern can tell from a log message. The detector is the "
            "first of several layers: a line it misses still reaches a model only fenced as "
            "evidence, severity cannot leave the prediction set, the tools are read-only, and "
            "nothing is sent before a person approves (see the robustness results)."
        ),
        "",
    ]
    return lines


_RETRIEVAL_METHODS = {
    "aria": "ARIA (BM25 and embeddings, fused by rank)",
    "bm25": "BM25 alone",
    "embeddings": "Embeddings alone",
    "random": "Three labelled past incidents at random",
    "commonest_label": "Always the commonest label",
}


def _gitlab(section: Mapping[str, Any]) -> list[str]:
    lines = ["## Real incidents, similar past incidents", ""]
    if "missing" in section:
        return [*lines, f"No results: {section['missing']}.", ""]
    snap = section.get("snapshot") or {}
    taken = (
        f" (snapshot of {snap['downloaded_at'][:10]}, sha256 `{snap['sha256'][:12]}`)"
        if snap.get("sha256")
        else ""
    )
    lines += [
        (
            f"GitLab.com's own production incidents{taken}: {section['incidents']:,} public "
            "issues, labelled by GitLab's responders with the service that failed and, after "
            f"review, the root cause. Source: {section['source']}. ARIA's retrieval index holds "
            f"the {section['memory']:,} incidents opened before {section['cutoff']}, from their "
            f"titles and descriptions. Each of the {section['later']:,} later incidents asks for "
            "similar past incidents from its title alone, as a responder would at the start; a "
            f"hit is a past incident with the same label among the first {section['top']}. "
            "Labels never enter the index or the query."
        ),
        "",
    ]
    names = {"service": "same service", "cause": "same root cause"}
    for key, by in section["by"].items():
        methods = by["methods"]
        n = methods["aria"]["queries"]
        lines += [
            (
                f"**{names.get(key, key).capitalize()}** ({n:,} later incidents with a label; "
                f"{by['labels']} labels among {by['memory_labelled']:,} labelled past incidents):"
            ),
            "",
            "| Method | Hit in the first 3 (95% CI) | Hit first | MRR@10 |",
            "|---|---|---|---|",
            *(
                f"| {label} | {_pct(methods[m]['recall_at_3'])} "
                f"({_ci(methods[m]['recall_at_3_ci95'])}) | {_pct(methods[m]['recall_at_1'])} | "
                f"{methods[m]['mrr_at_10']:.3f} |"
                for m, label in _RETRIEVAL_METHODS.items()
                if m in methods
            ),
            "",
        ]
    lines += [
        (
            "The issues are a live source: the download keeps the incidents created before a "
            "fixed date and records the snapshot's checksum, but issues can be edited later, so "
            "a fresh download may differ slightly."
        ),
        "",
    ]
    return lines


_FIX_NAMES = {
    "rollback": "a rollback",
    "hotfix": "a hotfix",
    "configuration": "a configuration change",
    "load": "shedding load",
    "traffic": "moving traffic",
    "restart": "a restart",
    "capacity": "added capacity",
    "hardware": "power or hardware repair",
    "self_healed": "recovering by itself",
}


def _and(items: Sequence[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _postmortems(section: Mapping[str, Any]) -> list[str]:
    lines = ["## Real incidents, three clouds' post-mortems", ""]
    if "missing" in section:
        return [*lines, f"No results: {section['missing']}.", ""]
    clouds = ", ".join(f"{n} from {k}" for k, n in section["by_cloud"].items())
    lines += [
        (
            f"{section['postmortems']:,} public post-mortems ({clouds}) of incidents from "
            f"{section['first'][:4]} to {section['last'][:4]}, each structured by researchers "
            "with its layered root cause and the mitigations that ended it. Source: "
            f"{section['source']}; {section['citation']} ARIA's retrieval index holds the "
            f"{section['memory']:,} post-mortems of incidents before {section['cutoff']}, from "
            f"their whole write-ups. Each of the {section['later']:,} later ones asks for similar "
            "past incidents from its title and summary of impact, what a responder knows first; "
            f"a hit is a past incident among the first {section['top']} with the same specific "
            "root cause, or ended by the same kind of fix. Labels never enter the index or the "
            "query."
        ),
        "",
        (
            "The researchers wrote each fix in their own words, so ARIA's evaluation sorts them "
            "by the words they use into "
            + _and([_FIX_NAMES.get(k, k) for k in section["fix_kinds"]])
            + f": {_pct(section['fix_labels_sorted'])} of the {section['fix_labels']:,} "
            "mitigations written fall into one of these."
        ),
        "",
    ]
    names = {"cause": "same specific root cause", "fix": "same kind of fix"}
    for key, by in section["by"].items():
        methods = by["methods"]
        n = methods["aria"]["queries"]
        top = list(by["label_counts"].items())[:3]
        lines += [
            (
                f"**{names.get(key, key).capitalize()}** ({n:,} later incidents with a label; "
                f"{by['labels']} labels among {by['memory_labelled']:,} labelled past incidents; "
                "the commonest: " + _and([f"{_FIX_NAMES.get(k, k)} ({c})" for k, c in top]) + "):"
            ),
            "",
            "| Method | Hit in the first 3 (95% CI) | Hit first | MRR@10 |",
            "|---|---|---|---|",
            *(
                f"| {label} | {_pct(methods[m]['recall_at_3'])} "
                f"({_ci(methods[m]['recall_at_3_ci95'])}) | {_pct(methods[m]['recall_at_1'])} | "
                f"{methods[m]['mrr_at_10']:.3f} |"
                for m, label in _RETRIEVAL_METHODS.items()
                if m in methods
            ),
            "",
        ]
    lines += [
        (
            "A summary of impact says what customers saw, which seldom says what broke, and a few "
            "labels cover most incidents, so three past incidents at random already share a label "
            "with many of them."
        ),
        "",
    ]
    return lines


_SLA_BASELINES = {
    "first_assignment_group": "Breach rate of the ticket's first assignment group",
    "category": "Breach rate of the ticket's category",
    "location": "Breach rate of the ticket's location",
    "priority_at_open": "Breach rate of the ticket's opening priority",
}


def _tickets(section: Mapping[str, Any]) -> list[str]:
    lines = ["## Real tickets, a ServiceNow service desk", ""]
    if "missing" in section or "stale" in section:
        why = section.get("missing") or section.get("stale")
        return [*lines, f"No results: {why}.", ""]
    split, pri, sla = section["split"], section["priority"], section["sla"]
    names = {
        "aria": "ARIA (impact x urgency matrix learned from training tickets)",
        "model_only": "The ticket model alone",
        "priority_at_open": "The priority the ticket opened with",
        "majority_class": "The commonest priority",
    }
    severe = sum(n for p, n in section["test_by_priority"].items() if p in ("1", "2"))
    conf, esc = section["conformal"], section["escalated"]
    return [
        *lines,
        (
            f"Real tickets from an IT company's ServiceNow service desk: {section['incidents']:,} "
            f"incidents ({section['events']:,} audit events) opened from "
            f"{section['opened_from']} to {section['opened_to']}, with anonymised codes and no "
            f"free text. Source: {section['source']}; {section['citation']} ARIA uses only the "
            "fields a ticket has when it opens, and splits by open time: the oldest "
            f"{split['train']:,} train the models, the next {split['calib']:,} calibrate them, and "
            f"the newest {split['test']:,} are scored here ({severe} of them priority 1 or 2). "
            f"Model `{section['model_version']}`."
        ),
        "",
        "| Final priority | Accuracy (95% CI) | Macro-F1 | Priority 1-2 rated 3-4 |",
        "|---|---|---|---|",
        *(
            f"| {label} | {_pct(pri[key]['accuracy'])} ({_ci(pri[key]['accuracy_ci95'])}) | "
            f"{pri[key]['macro_f1']:.3f} | {pri[key]['severe_missed']} of {severe} |"
            for key, label in names.items()
        ),
        "",
        (
            f"- **The priority follows the matrix**: {_pct(section['same_as_at_open'])} of these "
            "tickets ended at the priority they opened with, which impact and urgency set. ARIA "
            "learns the matrix from training tickets and decides by it (here for "
            f"{_pct(section['decided_by_matrix'])} of tickets). The model alone was less "
            "accurate, so it decides only for impact and urgency pairs the matrix has not seen."
        ),
        (
            f"- **Escalations**: {esc['tickets']} tickets were raised after they opened, and ARIA "
            f"foresaw {esc['foreseen'] or 'none'} of them. Nothing a ticket holds when it opens "
            "predicts them in this log, and they are most of the severe tickets rated 3 or 4."
        ),
        (
            f"- **Prediction sets** hold the final priority for {_pct(conf['coverage'])} of "
            f"tickets (target {_pct(conf['target_coverage'])}), with {conf['mean_set_size']} "
            "levels on average."
        ),
        "",
        (
            f"The SLA breach risk, scored on the same {sla['n']:,} tickets "
            f"({_pct(sla['breach_rate'])} of them breached):"
        ),
        "",
        "| SLA breach risk | AUROC (95% CI) |",
        "|---|---|",
        f"| ARIA's SLA model | {sla['auroc']:.3f} ({_ci(sla['auroc_ci95'], percent=False)}) |",
        *(
            f"| {_SLA_BASELINES.get(key, key)} | {value:.3f} |"
            for key, value in sla["baselines_auroc"].items()
        ),
        "",
        (
            f"Brier score {sla['brier']:.3f}, against {sla['brier_base_rate']:.3f} for always "
            f"predicting the base rate; calibration error {sla['ece']:.3f}. Each baseline is one "
            "field's breach rate among training tickets."
        ),
        "",
    ]


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
    corrected = section.get("corrected")

    def fixed(r: Mapping[str, Any]) -> str:
        value = r.get("grouping_accuracy_corrected")
        return f" {value:.3f} |" if value is not None else " not relabelled |"

    rows = [
        f"| {system} | {r['lines']} | {r['events']} | {r['templates']} | "
        f"{r['grouping_accuracy']:.3f} |" + (fixed(r) if corrected else "")
        for system, r in section["systems"].items()
    ]
    note = ""
    if corrected:
        changed = ", ".join(corrected["changed_systems"]) or "none"
        note = (
            f" Against the corrected labels of Loghub-2.0 ({corrected['citation']}), which cover "
            f"{corrected['n_systems']} of the systems, the mean is "
            f"{corrected['mean_grouping_accuracy']:.3f}, against "
            f"{corrected['original_mean_grouping_accuracy']:.3f} with the original labels on the "
            f"same systems; the corrections change the grouping score for: {changed}."
        )
    header = "| System | Lines | True events | Templates found | Grouping accuracy |"
    rule = "|---|---|---|---|---|"
    if corrected:
        header += " Against corrected labels |"
        rule += "---|"
    return [
        "## Log parsing",
        "",
        (
            f"Grouping accuracy against Loghub's hand-labelled templates, {section['lines']} lines "
            f"from {section['n_systems']} systems, through the production parser (redaction, "
            "injection guard, per-system Drain settings from the Loghub benchmark). Mean "
            f"{section['mean_grouping_accuracy']:.3f}. Real log lines flagged as injection: "
            f"{section['real_lines_flagged_as_injection']}.{note}"
        ),
        "",
        header,
        rule,
        *rows,
        "",
        *_gaia(section.get("gaia") or {}, section["systems"]),
    ]


_GAIA_NAMES = {
    "apache": "Apache",
    "arangodb": "ArangoDB",
    "clickhouse": "ClickHouse",
    "hadoop": "Hadoop",
    "kafka": "Kafka",
    "linux": "Linux",
    "mac": "Mac",
    "openstack": "OpenStack",
    "proxifier": "Proxifier",
    "redis": "Redis",
    "spark": "Spark",
    "ssh": "OpenSSH",
    "tengine": "Tengine",
    "zookeeper": "ZooKeeper",
}


def _gaia(gaia: Mapping[str, Any], loghub: Mapping[str, Any]) -> list[str]:
    if "systems" not in gaia:
        return [f"No results on GAIA's labelled logs: {gaia['missing']}.", ""] if gaia else []
    known, new = gaia["known"], gaia["new"]
    names = [_GAIA_NAMES.get(n, n) for n in new["systems"]]

    def sample(r: Mapping[str, Any]) -> str:
        if not r["aria_system"]:
            return "new to ARIA"
        on = loghub.get(r["aria_system"])
        return f"{on['grouping_accuracy']:.3f}" if on else "not downloaded"

    split = [
        f"{_GAIA_NAMES.get(n, n)}'s commonest event covers {_pct(r['commonest_event_share'])} "
        "of its lines"
        for n, r in gaia["systems"].items()
        if r["grouping_accuracy"] < 0.5 and r["commonest_event_share"] >= 0.5
    ]
    return [
        "### GAIA's labelled logs",
        "",
        (
            f"{gaia['lines']:,} lines from {gaia['n_systems']} systems in {gaia['source']}, each "
            "labelled with its template and parsed as production would parse it. Of these, "
            f"{known['n_systems']} are Loghub systems, parsed with the same settings; "
            f"{_and(names)} have no format or Drain settings in ARIA, so they get the "
            "generic settings any new system would. The lines are messages without their headers. "
            f"Mean grouping accuracy {gaia['mean_grouping_accuracy']:.3f}: "
            f"{known['mean_grouping_accuracy']:.3f} on the Loghub systems and "
            f"{new['mean_grouping_accuracy']:.3f} on the new ones. Real log lines flagged as "
            f"injection: {gaia['real_lines_flagged_as_injection']}. Source: {gaia['citation']}"
        ),
        "",
        "| System | Lines | True events | Templates found | Grouping accuracy | On Loghub's sample |",
        "|---|---|---|---|---|---|",
        *(
            f"| {_GAIA_NAMES.get(n, n)} | {r['lines']:,} | {r['events']} | {r['templates']} | "
            f"{r['grouping_accuracy']:.3f} | {sample(r)} |"
            for n, r in sorted(
                gaia["systems"].items(), key=lambda kv: _GAIA_NAMES.get(kv[0], kv[0])
            )
        ),
        "",
        *(
            [
                (
                    "Grouping accuracy credits only exact groups, so splitting one large event "
                    "costs every line in it: " + "; ".join(split) + "."
                ),
                "",
            ]
            if split
            else []
        ),
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


# What each real-data section measures on, in the order the report shows them.
_REAL_SOURCES = {
    "hdfs": "a Hadoop cluster's log, with its experts' label for each storage block",
    "bgl": "the whole BlueGene/L log, with its administrators' alert tags",
    "hadoop": "Hadoop jobs, with the failure injected into each",
    "openstack": "OpenStack runs, with a bug injected into each and the outcome it had",
    "uci_tickets": "a ServiceNow service desk's tickets, with their outcomes",
    "gitlab": "GitLab.com's production incidents, with their responders' labels",
    "postmortems": (
        "AWS, Azure and Google Cloud post-mortems, with the root cause and fix researchers "
        "recorded for each"
    ),
}


def _measured(section: Any) -> bool:
    return isinstance(section, Mapping) and bool(section) and "missing" not in section


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{'; '.join(items[:-1])}; and {items[-1]}"


def _data_paragraph(results: Mapping[str, Any]) -> str:
    real = results.get("real") or {}
    sources = [text for key, text in _REAL_SOURCES.items() if _measured(real.get(key))]
    lead = (
        f"**Data.** The first sections use real data, with labels its owners gave it: "
        f"{_join(sources)}. "
        if sources
        else "**Data.** "
    )
    if _measured(results.get("injection_benchmarks")):
        lead += "The public prompt-injection benchmarks are real attacks, written by others. "
    rest = "Every other number" if sources else "Every number"
    return (
        f"{lead}{rest} comes from semi-synthetic incident windows: real lines from the public "
        "Loghub samples, composed into incidents by ARIA's scenario builder. Severity labels "
        "come from the BGL alert-tag rubric for BGL windows and from the documented scenario "
        "policy elsewhere. The windows use held-out seeds "
        f"{', '.join(map(str, results['data']['test_seeds']))}, which no model was trained, "
        "calibrated or seeded on (incident memory uses seeds 51-52). These results show how ARIA "
        "behaves on that distribution; they are not a measurement of accuracy on production "
        "incidents."
    )


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
        _data_paragraph(results),
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
        if "bgl" in results["real"]:
            lines += _bgl(results["real"]["bgl"])
        if "hadoop" in results["real"]:
            lines += _hadoop(results["real"]["hadoop"])
        if "openstack" in results["real"]:
            lines += _openstack(results["real"]["openstack"])
        if "uci_tickets" in results["real"]:
            lines += _tickets(results["real"]["uci_tickets"])
        if "gitlab" in results["real"]:
            lines += _gitlab(results["real"]["gitlab"])
        if "postmortems" in results["real"]:
            lines += _postmortems(results["real"]["postmortems"])
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
    if "injection_benchmarks" in results:
        lines += _injection(results["injection_benchmarks"])
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
            "- The HDFS section measures one kind of failure signal, units of work that stop "
            "partway, and its labels say whether a block failed, not how severe the incident was. "
            "The BGL section's severity labels come from the administrators' tags through a "
            "rubric written for this project. The Hadoop, OpenStack, ticket and incident sections "
            "measure detection, priority and retrieval, not the reports ARIA writes."
        ),
        *_unmeasured(results.get("real") or {}),
        "",
    ]
    return "\n".join(lines)


def _unmeasured(real: Mapping[str, Any]) -> list[str]:
    """A limitation line for each real source that produced no results this time."""
    names = {
        "bgl": "contiguous BGL windows",
        "hadoop": "the Hadoop jobs",
        "openstack": "the OpenStack fault-injection runs",
        "uci_tickets": "the UCI incident log",
        "gitlab": "GitLab.com's incidents",
        "postmortems": "the cloud post-mortems",
    }
    missing = [
        label for key, label in names.items() if "missing" in (real.get(key) or {"missing": 1})
    ]
    if not missing:
        return []
    return [
        (
            f"- No results on {', '.join(missing[:-1]) + ' or ' if missing[1:] else ''}"
            f"{missing[-1]} are reported: the data was not downloaded "
            "(or the model not trained) when this report was generated."
        )
    ]


def _provenance(results: Mapping[str, Any], *, real: bool = False) -> str:
    seeds = ", ".join(map(str, results["data"]["test_seeds"]))
    which = "Apart from the real-data results, the data" if real else "The data"
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


def _bgl_summary(section: Mapping[str, Any]) -> list[str]:
    if "methods" not in section:
        return []
    methods = section["methods"]
    aria = methods["aria_policy"]
    severe = sum(n for c, n in section["labels"].items() if c in ("SEV1", "SEV2"))
    # Next to the strongest baselines, not the weakest: ARIA's own rules and the highest level.
    against = [
        f"{label}: {methods[key]['severe_missed']:,} and {methods[key]['quiet_paged']:,}"
        for key, label in (
            ("rules_only", "ARIA's rules alone"),
            ("highest_level", "the highest log level"),
        )
        if key in methods
    ]
    return [
        (
            f"**Real severity**: on all {section['windows']:,} {section['window_min']}-minute "
            f"windows of a supercomputer's {section['days']:g}-day log, labelled by its "
            f"administrators' alert tags, ARIA rated {aria['severe_missed']:,} of the "
            f"{severe:,} SEV1-2 windows as SEV3-4 and paged on {aria['quiet_paged']:,} of "
            f"{section['labels'].get('SEV4', 0):,} quiet windows"
            + (f" ({'; '.join(against)})" if against else "")
            + f"; accuracy {_pct(aria['accuracy'])} ({_ci(aria['accuracy_ci95'])}), "
            f"macro-F1 {aria['macro_f1']:.3f}."
        ),
        "",
    ]


def _hadoop_summary(section: Mapping[str, Any]) -> list[str]:
    if "aria" not in section:
        return []
    aria, errors = section["aria"], section["baselines"]["any_error_line"]
    return [
        (
            f"**Real failed jobs**: of {aria['failed']} Hadoop jobs with a failure injected, ARIA "
            f"flagged {aria['failed_flagged']} ({_ci(aria['recall_ci95'])}), and "
            f"{aria['normal_flagged']} of {aria['normal']} healthy jobs; a rule on ERROR lines "
            f"flags {errors['failed_flagged']} and {errors['normal_flagged']}."
        ),
        "",
    ]


def _openstack_summary(section: Mapping[str, Any]) -> list[str]:
    if "aria" not in section:
        return []
    aria, errors = section["aria"], section["baselines"]["any_error_line"]
    silent, review, paged = aria["silent"], section["review"], aria["paged"]
    unsure = review["failed"]["flagged"] + review["healthy"]["flagged"]
    return [
        (
            f"**Real injected bugs**: of {aria['failed']:,} OpenStack runs that failed after a "
            f"bug was injected into the code, ARIA flagged {aria['failed_flagged']:,} "
            f"({_ci(aria['recall_ci95'])}), including {_all_of(silent['flagged'], silent['of'])} "
            "that no API error reported, and "
            f"{_all_of(aria['normal_flagged'], aria['normal'])} runs that did not fail: it was "
            f"unsure of {unsure:,} of the {section['experiments']:,} runs and sent them to a "
            f"reviewer. Paging only at SEV1-2, it caught {paged['failed_flagged']:,} failed and "
            f"{paged['normal_flagged']:,} healthy runs, where a rule on ERROR lines flags "
            f"{errors['failed_flagged']:,} and {errors['normal_flagged']:,}; ranking failed above "
            f"healthy runs, it scores AUROC {_auroc(aria['ranking']['all'])}, against "
            f"{errors['ranking']['all']['auroc']:.3f} for counting ERROR lines."
        ),
        "",
    ]


def _gaia_summary(gaia: Mapping[str, Any]) -> str:
    if "systems" not in gaia:
        return ""
    new = gaia["new"]
    return (
        f", and {gaia['mean_grouping_accuracy']:.3f} on GAIA's {gaia['lines']:,} labelled lines "
        f"from {gaia['n_systems']} systems: {new['mean_grouping_accuracy']:.3f} on the "
        f"{new['n_systems']} that ARIA has no format or settings for"
    )


def _postmortems_summary(section: Mapping[str, Any]) -> list[str]:
    if "by" not in section or "cause" not in section["by"]:
        return []
    cause, fix = section["by"]["cause"]["methods"], section["by"].get("fix", {}).get("methods")
    aria, chance = cause["aria"], cause["random"]
    fixed = (
        f"; a past incident fixed the same way, for {_pct(fix['aria']['recall_at_3'])} "
        f"(at random: {_pct(fix['random']['recall_at_3'])})"
        if fix
        else ""
    )
    return [
        (
            f"**Real post-mortems**: from its title and summary of impact, ARIA's incident memory "
            f"put a past AWS, Azure or Google Cloud incident with the same specific root cause "
            f"among the first three for {_pct(aria['recall_at_3'])} "
            f"({_ci(aria['recall_at_3_ci95'])}) of {aria['queries']:,} later incidents, against "
            f"{_pct(chance['recall_at_3'])} at random{fixed}."
        ),
        "",
    ]


def _gitlab_summary(section: Mapping[str, Any]) -> list[str]:
    if "by" not in section or "service" not in section["by"]:
        return []
    methods = section["by"]["service"]["methods"]
    aria, chance, bm25 = methods["aria"], methods["random"], methods.get("bm25")
    better = (
        f" BM25 alone did better, at {_pct(bm25['recall_at_3'])}: the offline embeddings it "
        "fuses in cost recall here."
        if bm25 and bm25["recall_at_3"] > aria["recall_at_3"]
        else ""
    )
    return [
        (
            f"**Real incidents**: asked from its title alone, ARIA's incident memory put a past "
            f"GitLab.com incident on the same service among the first three for "
            f"{_pct(aria['recall_at_3'])} ({_ci(aria['recall_at_3_ci95'])}) of "
            f"{aria['queries']:,} later incidents, against {_pct(chance['recall_at_3'])} at "
            f"random.{better}"
        ),
        "",
    ]


def _tickets_summary(section: Mapping[str, Any]) -> list[str]:
    if "priority" not in section:
        return []
    aria, sla = section["priority"]["aria"], section["sla"]
    best = max(sla["baselines_auroc"].values(), default=0.5)
    return [
        (
            f"**Real tickets**: on the newest {section['test']:,} of {section['incidents']:,} "
            "tickets from a ServiceNow service desk, ARIA's priority matched the final priority "
            f"for {_pct(aria['accuracy'])} ({_ci(aria['accuracy_ci95'])}), the same as the "
            "impact x urgency matrix it learns, and its SLA model ranks breaches at AUROC "
            f"{sla['auroc']:.3f} ({_ci(sla['auroc_ci95'], percent=False)}), against {best:.3f} "
            "for the best single field."
        ),
        "",
    ]


def _injection_summary(bench: Mapping[str, Any]) -> list[str]:
    if "attacks" not in bench:
        return []
    total, benign = bench["attacks"], bench.get("benign") or {}
    real = bench.get("real_lines") or {}
    text = (
        f"**Prompt injection, public benchmarks**: of {total['n']:,} attacks from "
        f"{len(bench['by_source'])} public benchmarks the detector was never tuned on, it caught "
        f"{_pct(total['rate'])} ({_ci(total['ci95'])})"
    )
    if benign:
        text += f"; it flagged {_pct(benign['rate'])} of {benign['n']} benign look-alikes"
    if real:
        text += (
            f" and {sum(r['flagged'] for r in real.values()):,} of "
            f"{sum(r['n'] for r in real.values()):,} real log lines"
        )
    return [text + ". Fencing, the prediction set and approval do not rely on it.", ""]


def _results(results: Mapping[str, Any], live: Mapping[str, Any] | None) -> list[str]:
    """The README's summary: headline numbers, each linked to its section of the full report."""
    lines = [_provenance(results, real="real" in results), ""]
    if results["data"].get("fixtures"):
        lines += ["**These numbers come from the small test fixtures.** Run `make data` first.", ""]
    if "real" in results:
        lines += _real_summary(results["real"])
        lines += _bgl_summary(results["real"].get("bgl") or {})
        lines += _hadoop_summary(results["real"].get("hadoop") or {})
        lines += _openstack_summary(results["real"].get("openstack") or {})
        lines += _tickets_summary(results["real"].get("uci_tickets") or {})
        lines += _gitlab_summary(results["real"].get("gitlab") or {})
        lines += _postmortems_summary(results["real"].get("postmortems") or {})
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
                "systems)" + _gaia_summary(parsing.get("gaia") or {}) + "."
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
    lines += _injection_summary(results.get("injection_benchmarks") or {})
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
