"""Deterministic groundedness checks for reports and communications.

A report passes only when:

* every claim, timeline entry and action cites at least one evidence item that exists;
* every number in a claim appears in the evidence it cites (allowing for rounding, and for
  ratios written as percentages);
* the severity matches the severity assessment;
* no text contains a secret or an instruction aimed at a model;
* every action that names a runbook names a real one, at no lower risk than that runbook's
  matching step.

And it is flagged, with a warning that removes nothing, when a claim cites evidence about
something else: the claim names a factor (a lexicon category such as ``resource`` for disk
space, or ``security`` for failed logins) and a cited item is about other factors only and
shares no key term with the claim. A sentence about disk space that cites an authentication
failure is flagged; one that cites a count or a model score (evidence with no factor of its own)
is not.

These checks do not judge meaning; the LLM critic does that. They catch what can be checked
exactly, every time, at no cost.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aria.contracts.base import Evidence, Severity
from aria.contracts.report import IncidentReport, ValidationIssue, ValidationResult
from aria.parsing.catalog import load_lexicon
from aria.retrieval.runbooks import Runbook
from aria.security.injection import scan_line
from aria.security.redaction import Redactor

_DATETIME = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2}| UTC)?)?\b"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?(?: UTC)?\b"
)
# A standalone number: not part of an identifier such as SEV2, E12, R02-M1 or blk_-123.
_NUMBER = re.compile(r"(?<![\w.\-/])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(%|x\b)?(?![\w\-/])")
_WORD = re.compile(r"[a-z0-9_]{3,}")
_RISK = {"low": 0, "medium": 1, "high": 2}
_CLAIM_SECTIONS = ("summary", "impact", "suspected_cause")


@dataclass(frozen=True)
class Number:
    value: float
    decimals: int
    percent: bool

    @property
    def tolerance(self) -> float:
        return 0.5 * math.pow(10, -self.decimals) + 1e-9


def numbers_in(text: str) -> list[Number]:
    stripped = _DATETIME.sub(" ", text)
    found = []
    for match in _NUMBER.finditer(stripped):
        whole, fraction, suffix = match.group(1), match.group(2), match.group(3)
        value = float(whole.replace(",", "") + (f".{fraction}" if fraction else ""))
        found.append(Number(value, len(fraction or ""), suffix == "%"))
    return found


def _flatten(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        if math.isfinite(value):
            yield float(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _flatten(item)
    elif isinstance(value, str):
        for number in numbers_in(value):
            yield number.value


def evidence_numbers(items: Sequence[Evidence]) -> list[float]:
    values: list[float] = []
    for item in items:
        values.extend(n.value for n in numbers_in(f"{item.title}\n{item.detail}"))
        values.extend(_flatten(item.data))
    derived = [v * 100 for v in values if 0 <= v <= 1]  # ratios written as percentages
    derived += [v / 60 for v in values if v >= 60]  # seconds written as minutes
    return values + derived


def grounded(number: Number, values: Sequence[float]) -> bool:
    return any(abs(number.value - v) <= number.tolerance for v in values)


def ungrounded_numbers(text: str, cited: Sequence[Evidence]) -> list[str]:
    values = evidence_numbers(cited)
    return [
        f"{n.value:g}{'%' if n.percent else ''}"
        for n in numbers_in(text)
        if not grounded(n, values)
    ]


def _overlap(a: str, b: str) -> float:
    left, right = set(_WORD.findall(a.lower())), set(_WORD.findall(b.lower()))
    return len(left & right) / max(1, len(left))


def contains_secret(text: str) -> bool:
    redactor = Redactor(pseudonymize_ips=False)
    redactor.redact(text)
    return bool(redactor.counts)


# --- does the cited evidence support the factor a claim names? ----------------------------------

_KEY = re.compile(r"[a-z][a-z0-9]{3,}")
# Words any claim or log line may use whatever the factor: they tie a claim to nothing.
_GENERIC_WORDS = """
about above across after again against also among because been before being below between both
could does doing down during each from further have having here into itself just more most much
must only other over same seen should since some such than that their them then there these they
this those through under until upon very were what when where which while with within would your
error errors failed failing failure failures fail fails warn warning warnings issue issues problem
problems incident incidents event events line lines log logs logged logging message messages
template templates node nodes host hosts server servers service services system systems component
components instance instances process processes cluster window count counts total number rate
rates time times minute minutes second seconds hour hours first last several many high higher
lower likely possible suspected cause causes caused impact impacts affected affecting affects
report reports reported shows showed show points point evidence severity level levels rated
rating model rule rules occurred occurrences started stopped began ended still ongoing appears
appeared
"""
_GENERIC = frozenset(_GENERIC_WORDS.split())


def _stem(word: str) -> str:
    """A word without its common endings, so "panics" meets "panic" and "stopping" meets
    "stopp"."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def key_terms(text: str) -> frozenset[str]:
    """The words of ``text`` that can tie a claim to its evidence: not stop words, not words
    every incident uses, stemmed."""
    return frozenset(_stem(w) for w in _KEY.findall(text.lower()) if w not in _GENERIC)


def factors(text: str) -> frozenset[str]:
    """The lexicon categories ``text`` names: "no space left on device" is ``resource``, a
    failed password ``security``."""
    lowered = text.lower()
    return frozenset(name for name, pattern in load_lexicon().items() if pattern.search(lowered))


def _evidence_words(item: Evidence) -> str:
    """Everything an evidence item says in words: its title, detail and text data."""
    return "\n".join([item.title, item.detail, *_flatten_strings(item.data)])


def _flatten_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _flatten_strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _flatten_strings(item)


def off_topic(text: str, cited: Sequence[Evidence]) -> list[tuple[Evidence, frozenset[str]]]:
    """The cited items about something other than the factor ``text`` claims, each with the
    factors it is about. An item counts when it names factors, none of them the claim's, and
    shares no key term with the claim; evidence that names no factor (a count, a model score)
    can support any claim, and a claim that names no factor is not checked."""
    claimed = factors(text)
    if not claimed:
        return []
    terms = key_terms(text)
    out = []
    for item in cited:
        words = _evidence_words(item)
        about = factors(words)
        if about and not about & claimed and not terms & key_terms(words):
            out.append((item, about))
    return out


def _mismatch_message(text: str, mismatched: Sequence[tuple[Evidence, frozenset[str]]]) -> str:
    claimed = ", ".join(sorted(factors(text)))
    cited = "; ".join(
        f"{item.id} is about {', '.join(sorted(about))}" for item, about in mismatched
    )
    return (
        f"the claim is about {claimed}, but {cited}, and shares no key term with it: "
        "check that the evidence supports the claim"
    )


@dataclass
class _Checked:
    path: str
    text: str
    evidence_ids: list[str]


def validate_report(
    report: IncidentReport,
    *,
    evidence: Sequence[Evidence],
    expected_severity: Severity | None = None,
    runbooks: Mapping[str, Runbook] | None = None,
    strict: bool = False,
) -> ValidationResult:
    """Check a report. ``strict`` also treats claim-number mismatches in actions as errors."""
    by_id = {item.id: item for item in evidence}
    issues: list[ValidationIssue] = []

    def issue(code: str, message: str, path: str | None, level: str = "error") -> None:
        issues.append(ValidationIssue(code=code, message=message, path=path, level=level))  # type: ignore[arg-type]

    checked: list[_Checked] = [
        _Checked(p, c.text, list(c.evidence_ids)) for p, c in report.claims()
    ]
    checked += [
        _Checked(f"timeline[{i}]", t.text, list(t.evidence_ids))
        for i, t in enumerate(report.timeline)
    ]
    actions = [
        _Checked(f"actions[{i}]", a.text, list(a.evidence_ids))
        for i, a in enumerate(report.actions)
    ]

    clean = 0
    for item in [*checked, *actions]:
        ok = True
        if not item.evidence_ids:
            issue("missing_citation", "cites no evidence", item.path)
            ok = False
        unknown = [e for e in item.evidence_ids if e not in by_id]
        if unknown:
            issue(
                "unknown_evidence",
                f"cites evidence that does not exist: {', '.join(unknown)}",
                item.path,
            )
            ok = False
        cited = [by_id[e] for e in item.evidence_ids if e in by_id]
        if cited:
            loose = ungrounded_numbers(item.text, cited)
            is_action = item.path.startswith("actions")
            if loose:
                level = "error" if (strict or not is_action) else "warning"
                issue(
                    "ungrounded_number",
                    f"numbers not found in the cited evidence: {', '.join(loose[:5])}",
                    item.path,
                    level,
                )
                ok = ok and level != "error"
            # A claim that cites evidence about another factor is flagged for the reviewer,
            # never removed: the check reads words, and a person decides.
            if item.path.startswith(_CLAIM_SECTIONS) and (
                mismatched := off_topic(item.text, cited)
            ):
                issue(
                    "evidence_mismatch",
                    _mismatch_message(item.text, mismatched),
                    item.path,
                    "warning",
                )
        if contains_secret(item.text):
            issue("secret_in_text", "text looks like it contains a credential", item.path)
            ok = False
        if scan_line(item.text, 0) is not None:
            issue(
                "instruction_in_text",
                "text contains instruction-like content aimed at a model",
                item.path,
            )
            ok = False
        clean += ok

    if expected_severity is not None and report.severity != expected_severity:
        issue(
            "severity_mismatch",
            f"report says {report.severity} but the assessment decided {expected_severity}",
            "severity",
        )
    if contains_secret(report.title) or scan_line(report.title, 0) is not None:
        issue("unsafe_title", "title contains a credential or an instruction", "title")
    if not report.summary:
        issue("empty_summary", "the summary has no claims", "summary")

    for i, action in enumerate(report.actions):
        if action.runbook_slug is None or runbooks is None:
            continue
        runbook = runbooks.get(action.runbook_slug)
        if runbook is None:
            issue(
                "unknown_runbook", f"runbook {action.runbook_slug} does not exist", f"actions[{i}]"
            )
            continue
        steps = [*runbook.mitigate, *runbook.diagnose]
        best = max(steps, key=lambda s: _overlap(action.text, s.text), default=None)
        if best is None or _overlap(action.text, best.text) < 0.3:
            issue(
                "action_not_in_runbook",
                f"no step of {runbook.slug} matches this action",
                f"actions[{i}]",
                "warning",
            )
        elif _RISK[action.risk] < _RISK[best.risk]:
            issue(
                "risk_downgraded",
                f"risk {action.risk} is lower than the runbook step's {best.risk}",
                f"actions[{i}]",
            )

    total = len(checked) + len(actions)
    errors = [i for i in issues if i.level == "error"]
    return ValidationResult(
        ok=not errors,
        issues=issues,
        citation_coverage=round(clean / total, 4) if total else 0.0,
        checked_claims=total,
    )


# --- communications ----------------------------------------------------------------------------

_INTERNAL_IDS: dict[str, re.Pattern[str]] = {
    "pseudonym": re.compile(r"\b(?:ip|email)-[0-9a-f]{8}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "evidence_id": re.compile(r"\bE\d{1,5}\b"),
    "template_id": re.compile(r"\bT[0-9a-f]{10}\b"),
    "node_name": re.compile(
        r"\b[A-Za-z]{1,6}\d{1,3}(?:-[A-Za-z]{1,3}\d{1,3}){1,}\b|\b[a-z]+-node-\d+\b"
    ),
    "internal_host": re.compile(r"\b[a-z0-9-]+\.(?:internal|local|corp|lan|svc|cluster\.local)\b"),
    "file_path": re.compile(r"(?<![\w])/(?:[\w.-]+/){2,}[\w.-]*"),
}
_SPECULATION = re.compile(r"\b(root cause (?:is|was)|caused by|because of|due to)\b", re.IGNORECASE)
# Updates outside the team point to nothing: a link or a phone number in one is how a label or a
# model could send customers somewhere else. A link is a URL, "www." or a bare domain such as
# status-help.com.
_LINK = re.compile(
    r"https?://|\bwww\.|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|io|co|dev|app|info|biz|me|ly|example)\b",
    re.IGNORECASE,
)
_NUMBER_RUN = re.compile(r"\+?\(?\d[\d ().-]{6,}\d")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?: \d{2})?")


def _has_phone_number(text: str) -> bool:
    """A run of digits dialled as a number: international (+...) or nine digits or more, and
    not a date."""
    for match in _NUMBER_RUN.finditer(text):
        run = match.group().strip()
        if _DATE.fullmatch(run):
            continue
        if run.startswith("+") or sum(c.isdigit() for c in run) >= 9:
            return True
    return False


def validate_external_text(text: str, *, audience: str) -> list[str]:
    """Problems that make text unfit to leave the team (stakeholders or customers)."""
    problems = [
        f"contains an internal identifier ({name})"
        for name, rx in _INTERNAL_IDS.items()
        if rx.search(text)
    ]
    if contains_secret(text):
        problems.append("contains a credential")
    if scan_line(text, 0) is not None:
        problems.append("contains instruction-like content")
    if _LINK.search(text):
        problems.append("contains a link")
    if _has_phone_number(text):
        problems.append("contains a phone number")
    if audience == "customers" and _SPECULATION.search(text):
        problems.append("speculates about the cause in a customer-facing update")
    return problems
