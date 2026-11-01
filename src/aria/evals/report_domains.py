"""The ``docs/evaluation.md`` sections for the ring C suites (``aria.evals.domains``): data from
domains ARIA was never tuned on. ``report.render`` adds them with one call to :func:`render`.

Every number here is read from the results; nothing is typed in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_LEVELS = ("SEV1", "SEV2", "SEV3", "SEV4")
_STEPS = {
    "network_scans": "Network scans",
    "service_scans": "Service scans",
    "dirb": "Directory brute force",
    "wpscan": "WordPress scan",
    "webshell": "Web shell upload",
    "cracking": "Password cracking",
    "reverse_shell": "Reverse shell",
    "privilege_escalation": "Privilege escalation",
    "service_stop": "Stopped service",
    "dnsteal": "Data theft over DNS",
}
_AIT_METHODS = {
    "aria": "ARIA, offline",
    "rules_only": "ARIA's rules only",
    "model_only": "ARIA's model only",
    "keyword": "Keyword categories",
    "ids_level": "The detectors' own level",
}
_RANKERS = {
    "aria_probability": "ARIA's probability of SEV1-2",
    "aria_level": "ARIA's level",
    "ids_level": "The detectors' highest rule level",
    "alert_count": "Number of alerts",
    "keyword": "Keyword categories",
    "rules_only": "ARIA's rules only",
}
_JIRA_METHODS = {
    "aria": "ARIA's ticket model",
    "at_open": "The priority it opened with",
    "by_issue_type": "Commonest level for the issue's type",
    "majority_class": "Commonest level",
}
_INSTANCES = {"Apache": "Apache's Jira", "Jira": "Atlassian's Jira"}
_SYSTEMS = {
    "SS": "Sock Shop",
    "OB": "Online Boutique",
    "TT": "Train Ticket",
    "SN": "SocialNetwork",
}


def _pct(value: Any) -> str:
    return f"{100 * float(value):.1f}%" if isinstance(value, int | float) else "n/a"


def _ci(pair: Any, *, percent: bool = True) -> str:
    if isinstance(pair, list | tuple) and len(pair) == 2:
        if percent:
            return f"{100 * pair[0]:.1f}–{100 * pair[1]:.1f}%"
        return f"{pair[0]:.3f}–{pair[1]:.3f}"
    return "n/a"


def _share(d: Mapping[str, Any]) -> str:
    return f"{d['hits']:,} of {d['of']:,} ({_pct(d['share'])}, {_ci(d['ci95'])})"


def _num(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, int | float) else "n/a"


def _miss(d: Mapping[str, Any]) -> str:
    return f"{_share(d)}; at most {_pct(d['upper95'])} with 95% confidence"


def _auroc(d: Mapping[str, Any]) -> str:
    return f"{d['auroc']:.3f} ({_ci(d['auroc_ci95'], percent=False)})"


def _naming(d: Mapping[str, Any]) -> str:
    return f"{_share(d['top1'])} | {_share(d['top3'])} |"


def _missing(title: str, section: Mapping[str, Any]) -> list[str] | None:
    if "missing" in section:
        return [title, "", f"No results: {section['missing']}.", ""]
    return None


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _ait(s: Mapping[str, Any]) -> list[str]:
    title = "### Security alerts from attacked networks"
    if (gone := _missing(title, s)) is not None:
        return gone
    steps = s["steps"]["aria"]["by_step"]
    rates = s["rates"]
    per = s["per_scenario_auroc"]
    return [
        title,
        "",
        (
            f"{s['alerts']:,} alerts from {s['scenarios']} simulated company networks, each attacked "
            "once in several steps and watched by three intrusion detection systems (Wazuh, "
            f"Suricata and AMiner). Source: {s['source']}; {s['citation']} The alerts are cut into "
            f"{s['windows']:,} contiguous {s['window_min']}-minute windows: {s['attack_windows']} "
            f"overlap an attack step and {s['routine_windows']:,} hold only routine alerts, most of "
            "them false positives from ordinary users. ARIA rates each window from its alert lines "
            "alone, remembering the routine templates of the network's earlier windows as a "
            f"deployment would; {s['windows_over_line_cap']} windows hold more than the per-run "
            f"line cap of {s['line_cap']:,}, and ARIA reads up to the cap."
        ),
        "",
        "| Ranks attack windows above routine ones | AUROC (95% CI) |",
        "|---|---|",
        *(f"| {_RANKERS[k]} | {_auroc(v)} |" for k, v in s["ranking"].items() if k in _RANKERS),
        "",
        (
            f"Across the networks, the median AUROC of ARIA's probability is "
            f"{_num(per['median'])}, the worst {_num(per['worst'])}, and {per['below_0_5']} of "
            f"{s['scenarios']} networks rank attack windows below routine ones."
        ),
        "",
        (
            "| Method | Attack windows flagged | Attack windows paged | Routine windows flagged | "
            "Routine windows paged |"
        ),
        "|---|---|---|---|---|",
        *(
            f"| {_AIT_METHODS[k]} | {_share(r['attack_flagged'])} | {_share(r['attack_paged'])} | "
            f"{_share(r['routine_flagged'])} | {_share(r['routine_paged'])} |"
            for k, r in rates.items()
        ),
        "",
        (
            "The steps that mean a compromise or harm are a web shell, password cracking, a "
            "reverse shell, privilege escalation, a stopped service and data theft over DNS. A step "
            "counts as missed when no window overlapping it was paged (SEV1-2). Steps minutes "
            "apart share a window, so a page set off by a scan also counts for a web shell "
            "uploaded just after it. Severe misses, "
            f"ARIA: {_miss(s['steps']['aria']['severe_miss'])}. The detectors' own level: "
            f"{_miss(s['steps']['ids_level']['severe_miss'])}."
            + (
                f" {silent} of these steps overlap no window that holds an alert."
                if (silent := s["steps"]["aria"]["harmful_without_alerts"])
                else ""
            )
        ),
        "",
        "| Attack step | Occurrences | With any alert | Flagged by ARIA | Paged by ARIA |",
        "|---|---|---|---|---|",
        *(
            f"| {_STEPS.get(k, k)} | {v['occurrences']} | {v['with_alerts']} | {v['flagged']} | "
            f"{v['paged']} |"
            for k, v in steps.items()
        ),
        "",
    ]


def _rcaeval(s: Mapping[str, Any]) -> list[str]:
    title = "### Code-level faults in microservice shops"
    if (gone := _missing(title, s)) is not None:
        return gone
    aria, base = s["aria"], s["baselines"]
    systems = _join([f"{n} in {_SYSTEMS.get(k, k)}" for k, n in s["by_system"].items()])
    paired = aria["paired"]
    random = base["naming_random_expected"]
    return [
        title,
        "",
        (
            f"{s['cases']} code-level faults injected into microservice shops ({systems}). "
            f"Source: {s['source']}; {s['citation']} Each case gives two windows, every service's "
            "logs from before the fault and from the fault on, each triaged offline, end to end, "
            "with its lines led by their container's name. "
            f"{s['windows_over_line_cap']} of the {s['windows']} windows hold more than the "
            f"per-run line cap of {s['line_cap']:,}; ARIA reads up to the cap."
        ),
        "",
        "| Method | Faulty windows flagged (95% CI) | Healthy windows flagged |",
        "|---|---|---|",
        (
            f"| ARIA, end to end | {_share(aria['faulty_flagged'])} | "
            f"{_share(aria['healthy_flagged'])} |"
        ),
        (
            f"| ARIA, paged (SEV1-2) | {_share(aria['paged']['faulty_flagged'])} | "
            f"{_share(aria['paged']['healthy_flagged'])} |"
        ),
        (
            f"| Any error line | {_share(base['any_error_line']['faulty_flagged'])} | "
            f"{_share(base['any_error_line']['healthy_flagged'])} |"
        ),
        "",
        (
            f"In {paired['higher']} cases ARIA rated the faulty window above its own healthy "
            f"window, in {paired['same']} the same and in {paired['lower']} below. ARIA's "
            f"probability of SEV1-2 ranks faulty windows above healthy ones with AUROC "
            f"{_auroc(aria['ranking'])}; the count of error lines does so with "
            f"{_auroc(base['error_count_ranking'])}."
        ),
        "",
        "| Names the service at fault | First suspect | Among the first three |",
        "|---|---|---|",
        f"| ARIA | {_naming(aria['naming'])}",
        f"| Most error lines | {_naming(base['naming_most_errors'])}",
        (
            f"| Largest change in log share (reads both windows) | "
            f"{_naming(base['naming_most_changed'])}"
        ),
        f"| A container at random (expected) | {_pct(random['top1'])} | {_pct(random['top3'])} |",
        "",
    ]


def _anomod(s: Mapping[str, Any]) -> list[str]:
    title = "### Anomalies at four levels in two microservice systems"
    if (gone := _missing(title, s)) is not None:
        return gone
    aria, base = s["aria"], s["baselines"]
    normal = _join([f"{_SYSTEMS.get(k, k)} {v}" for k, v in aria["normal_severity"].items()])
    random = base["naming_random_expected"]
    return [
        title,
        "",
        (
            f"{s['anomalous']} anomalies injected at four levels (performance, service, database "
            f"and code) into SocialNetwork and Train Ticket, plus {s['normal']} normal runs. "
            f"Source: {s['source']}; {s['citation']} Each run's newest log lines, up to the "
            f"per-run cap of {s['line_cap']:,}, are triaged offline, end to end."
        ),
        "",
        (
            f"ARIA flagged {_share(aria['anomalous_flagged'])} anomalous runs and paged "
            f"{_share(aria['anomalous_paged'])}; a rule that flags any run with an error line flagged "
            f"{_share(base['any_error_line']['anomalous_flagged'])}. The normal runs: {normal} (too few "
            "to estimate a false-alarm rate)."
        ),
        "",
        "| Level | Runs | Flagged (95% CI) | " + " | ".join(_LEVELS) + " |",
        "|---|---|---|" + "---|" * len(_LEVELS),
        *(
            f"| {level.capitalize()} | {v['runs']} | {_share(v['flagged'])} | "
            + " | ".join(str(v["severity"].get(sev, 0)) for sev in _LEVELS)
            + " |"
            for level, v in s["by_level"].items()
        ),
        "",
        "| Names the targeted service | First suspect | Among the first three |",
        "|---|---|---|",
        f"| ARIA | {_naming(aria['naming'])}",
        f"| Most error lines | {_naming(base['naming_most_errors'])}",
        f"| A service at random (expected) | {_pct(random['top1'])} | {_pct(random['top3'])} |",
        "",
    ]


def _itbench(s: Mapping[str, Any]) -> list[str]:
    title = "### Kubernetes incidents"
    if (gone := _missing(title, s)) is not None:
        return gone
    aria, base = s["aria"], s["baselines"]
    random = base["naming_random_expected"]
    skipped = s.get("found", s["scenarios"]) - s["scenarios"]
    return [
        title,
        "",
        (
            f"{s['scenarios']} incident snapshots of a Kubernetes cluster running a demo shop, "
            f"each with one injected fault. Source: {s['source']}; {s['citation']} Each is "
            "triaged offline, end to end, from the alerts in alerting state when the incident was "
            f"raised and the {s['window_min']} minutes of Kubernetes events and service logs "
            "before it. Every scenario is an incident, so false alarms are measured on the healthy "
            "windows above instead."
            + (
                f" {skipped} scenario has no incident time (its alerts never fired) and is left out."
                if skipped == 1
                else f" {skipped} scenarios have no incident time and are left out."
                if skipped
                else ""
            )
        ),
        "",
        (
            f"ARIA flagged {_share(aria['flagged'])} incidents and paged {_share(aria['paged'])}; "
            f"missed (SEV4): {_miss(aria['missed'])}. The alerts' own severity flagged "
            f"{_share(base['alert_severity']['flagged'])} and paged "
            f"{_share(base['alert_severity']['paged'])}."
        ),
        "",
        (
            f"The service at fault is a workload marked as the root cause or, when the root cause "
            "is not a workload (a ConfigMap, a namespace quota, an autoscaler), the first workloads "
            f"it spreads to; {s['with_named_service']} scenarios have one."
        ),
        "",
        "| Names the service at fault | First suspect | Among the first three |",
        "|---|---|---|",
        f"| ARIA | {_naming(aria['naming'])}",
        f"| The services the alerts name | {_naming(base['naming_alerted_service'])}",
        f"| Most error lines | {_naming(base['naming_most_errors'])}",
        f"| A service at random (expected) | {_pct(random['top1'])} | {_pct(random['top3'])} |",
        "",
    ]


def _jira(s: Mapping[str, Any]) -> list[str]:
    title = "### Ticket priority in public issue trackers"
    if (gone := _missing(title, s)) is not None:
        return gone
    lines = [
        title,
        "",
        (
            f"{s['test_tickets']:,} recent issues from public Jira instances (the newest 30% of "
            "each), scored against the priority people set; the other "
            f"{s['reference_tickets']:,} set the simple baselines. Source: {s['source']}; "
            f"{s['citation']} ARIA's ticket "
            "model was trained on one company's ServiceNow desk and reads a ticket's category, "
            "subcategory, configuration item and open time; Jira has no impact or urgency, so the "
            "model, not the impact x urgency matrix, decides every ticket. Urgent means levels "
            "1-2 (Blocker and Critical, or Highest and High)."
        ),
        "",
    ]
    for key, block in s["instances"].items():
        levels = ", ".join(f"level {k}: {v:,}" for k, v in block["levels"].items())
        lines += [
            (
                f"{_INSTANCES.get(key, key)}: {block['tickets']:,} tickets ({levels}); the priority "
                f"changed after the issue opened for {_share(block['changed_after_open'])}. ARIA's "
                f"conformal set held the true level for {_pct(block['set_coverage'])} of them."
            ),
            "",
            "| Method | Accuracy (95% CI) | Macro-F1 (95% CI) | Urgent tickets rated 3-4 |",
            "|---|---|---|---|",
            *(
                f"| {_JIRA_METHODS[name]} | {_pct(r['accuracy'])} ({_ci(r['accuracy_ci95'])}) | "
                f"{r['macro_f1']:.3f} ({_ci(r['macro_f1_ci95'], percent=False)}) | "
                f"{_miss(r['urgent_missed'])} |"
                for name, r in block["methods"].items()
            ),
            "",
        ]
    return lines


def _hadoop_labels(hadoop: Mapping[str, Any]) -> list[str]:
    issue = hadoop.get("label_issue")
    if not isinstance(issue, Mapping):
        return []
    without, proposed = issue["without_disputed"], issue["with_proposed_labels"]
    return [
        "### The Hadoop jobs whose labels are disputed",
        "",
        (
            f"Loghub issue #56 ({issue['source']}) says {len(issue['jobs'])} of the PageRank jobs "
            "may be mislabelled, and the maintainer closed it with a warning rather than a fix. "
            "Without those jobs, ARIA flagged "
            f"{without['failed_flagged']} of {without['failed']} failed jobs and "
            f"{without['normal_flagged']} of {without['normal']} healthy ones; with the labels "
            f"the issue proposes, {proposed['failed_flagged']} of {proposed['failed']} failed "
            f"and {proposed['normal_flagged']} of {proposed['normal']} healthy."
        ),
        "",
        "| Job | Label in the data | Label the issue proposes | ARIA's severity |",
        "|---|---|---|---|",
        *(
            f"| {j['job']} | {j['label'].replace('_', ' ')} | {j['proposed'].replace('_', ' ')} | "
            f"{j['severity']} |"
            for j in issue["jobs"]
        ),
        "",
    ]


def render(results: Mapping[str, Any]) -> list[str]:
    """The new-domain sections, and the Hadoop label note, from a results document."""
    domains = results.get("domains") or {}
    hadoop = (results.get("real") or {}).get("hadoop") or {}
    lines = _hadoop_labels(hadoop) if isinstance(hadoop, Mapping) else []
    if not domains:
        return lines
    lines += [
        "## New domains: data ARIA was never tuned on",
        "",
        (
            "These suites read public, labelled data from domains outside ARIA's training: "
            "security alerts, microservice faults, Kubernetes incidents and issue-tracker "
            "priority. No rule, lexicon entry, threshold or model was changed for them; a change "
            "made after reading them would turn them into tuning data, and their results would "
            "move to a post hoc section with the date. None of them labels incident severity, so "
            "they measure detection, ranking, naming the service at fault and ticket priority, "
            "not SEV accuracy. Their labels come from injected faults and scripted attacks, "
            "except Jira's, which people set. See the data card for each dataset's licence and "
            "known label problems."
        ),
        "",
    ]
    renderers = {
        "ait-ads": _ait,
        "rcaeval": _rcaeval,
        "anomod": _anomod,
        "itbench": _itbench,
        "jira": _jira,
    }
    for name, renderer in renderers.items():
        if isinstance(domains.get(name), Mapping):
            lines += renderer(domains[name])
    return lines
