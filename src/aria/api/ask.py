"""Ask ARIA: questions about a run or about incident history, answered only from evidence.

The question is untrusted input. It is fenced in the prompt like log text, and the answer is
held to the report's rules: every statement cites evidence ARIA has, and no number may appear
that the cited evidence lacks. Without an LLM (or when its answer fails those checks) ARIA
returns the most relevant evidence instead of an answer it cannot back.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from aria.config import BudgetConfig
from aria.contracts.base import Evidence, EvidenceKind, JsonDict
from aria.evidence import EvidenceStore
from aria.llm.base import BudgetExceededError, LLMError
from aria.llm.budget import BudgetGuard
from aria.llm.prompts import build_messages
from aria.llm.router import LLMRouter
from aria.llm.schemas import AnswerOutput, ClaimOut
from aria.reporting.grounding import ungrounded_numbers
from aria.services import Services
from aria.text import headline

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {
        "the", "and", "for", "was", "were", "what", "why", "how", "when", "which", "with",
        "this", "that", "from", "into", "did", "does", "are", "has", "have", "had", "who",
        "whom", "its", "about", "there", "their", "them", "they", "then", "than", "over",
        "under", "any", "all", "not", "but", "get", "got", "gets", "only", "just", "also",
        "very", "much", "more", "still", "out", "off", "too", "yet", "one", "two", "three",
        "need", "needs", "make", "made", "know", "tell", "use", "used", "using", "please",
        "may", "might", "must", "doing", "done", "while", "during", "after", "shall", "these",
        "those", "other", "such", "each", "every",
    }
)  # fmt: skip
MAX_EVIDENCE = 12
# One question's LLM spending: an answer, a repair and one fallback provider at most.
ASK_BUDGET = BudgetConfig(max_tokens=6_000, max_cost_usd=0.05, max_latency_s=30.0, max_llm_calls=3)


def terms(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if len(t) >= 3 and t not in _STOP}


def _forms(word: str) -> set[str]:
    """A word and the roots it may come from, so "disks" finds "disk", "caused" "cause" and
    "failing" "fail". Words are matched whole: "run" does not find "runbook"."""
    forms = {word}
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            root = word[: -len(suffix)]
            forms.update((root, f"{root}e"))
    return forms


def _vocabulary(text: str) -> set[str]:
    return {form for word in _WORD.findall(text.lower()) for form in _forms(word)}


def _found(term: str, vocabulary: set[str]) -> bool:
    return not _forms(term).isdisjoint(vocabulary)


# The everyday words for each kind of evidence, so that a question in plain words ("what did the
# investigation find?", "has this happened before?") reaches it without a model.
_KIND_WORDS: dict[EvidenceKind, str] = {
    EvidenceKind.HYPOTHESIS: "investigation investigated cause caused find found failed failure "
    "broke broken wrong problem",
    EvidenceKind.INCIDENT: "similar before previous history happened fixed resolved",
    EvidenceKind.RUNBOOK: "fix steps first check should next action mitigate",
    EvidenceKind.TEMPLATE: "pattern patterns errors often most",
    EvidenceKind.FEATURE: "errors long many",
    EvidenceKind.RULE: "serious severity rated rating level",
    EvidenceKind.MODEL: "serious severity rated rating level likely confident",
}
# The same for the investigation's own checks, whose records are matched on these words alone:
# their titles are terse summaries and their details raw data. (The investigation's other tools
# repeat evidence cited on its own.)
_TOOL_WORDS = {
    "mcp.node_breakdown": "servers server nodes hosts machines where affected spread",
    "mcp.component_timeline": "component components affected when time timeline started first peak",
    "mcp.get_template_examples": "example examples lines show",
}
_REPEATS = frozenset({"mcp.search_incidents", "mcp.get_runbook", "mcp.list_runbooks"})
# Words that say which kind of answer a question wants rather than what it is about: "has this
# happened before?" asks for history, "has a disk failed before?" for history about disks.
_GENERIC = frozenset(" ".join([*_KIND_WORDS.values(), *_TOOL_WORDS.values()]).split()) | {
    "incident", "incidents", "issue", "issues", "happen", "happens", "past", "ever", "seen",
    "like", "anything", "something", "time", "times", "last", "aria", "run", "runs", "outage",
    "outages", "same", "kind", "sort", "type", "again", "occurred", "occur", "been", "being",
    "will", "would", "could", "can", "our", "your", "you", "some", "here", "now", "today",
    "yesterday", "ago", "recent", "recently", "happening", "going", "on", "matter", "wrong",
}  # fmt: skip

# A question about the state of things now, which no record of the past can answer.
_NOW = re.compile(
    r"\b(?:still|currently|right now|at the moment|ongoing|as we speak|live)\b", re.IGNORECASE
)
# Equal matches go to the kind that answers most directly: a tested cause, then the rating.
_DIRECTNESS = (
    EvidenceKind.HYPOTHESIS,
    EvidenceKind.RULE,
    EvidenceKind.MODEL,
    EvidenceKind.INCIDENT,
    EvidenceKind.RUNBOOK,
    EvidenceKind.TEMPLATE,
    EvidenceKind.LOG,
    EvidenceKind.ALERT,
    EvidenceKind.FEATURE,
    EvidenceKind.TOOL,
)


def rank(
    question: str, evidence: Sequence[Evidence], *, limit: int = MAX_EVIDENCE
) -> list[Evidence]:
    """Evidence ordered by how many of the question's words it contains, matched as whole words.
    Ties go to the kind of evidence that answers more directly, then keep their order.

    A past incident counts only if it mentions at least half of what the question is about (its
    words that say neither which kind of answer it wants nor anything general): history words
    alone ("before", "similar") match every incident, and one shared word ("killed" in "Was a pod
    OOM killed?" and in "killed jobs") does not make an unrelated incident an answer."""
    wanted = terms(question)
    about = wanted - _GENERIC
    scored = []
    for position, item in enumerate(evidence):
        own = _vocabulary(f"{item.title} {item.detail}")
        named = sum(1 for term in about if _found(term, own))
        if about and item.kind is EvidenceKind.INCIDENT and 2 * named < len(about):
            continue
        if item.kind is EvidenceKind.TOOL:
            vocabulary = _vocabulary(_TOOL_WORDS.get(item.source, ""))
        else:
            words = _KIND_WORDS.get(item.kind, "")
            vocabulary = own | _vocabulary(f"{item.source} {item.kind} {words}")
        hits = sum(1 for term in wanted if _found(term, vocabulary))
        if hits:
            direct = _DIRECTNESS.index(item.kind) if item.kind in _DIRECTNESS else len(_DIRECTNESS)
            scored.append((-hits, direct, position, item))
    scored.sort(key=lambda entry: entry[:3])
    return [entry[3] for entry in scored[:limit]]


def asks_about_now(question: str) -> bool:
    """Whether the question asks how things are now ("Is it still happening?")."""
    return _NOW.search(question) is not None


def notes(question: str, cited: Sequence[Evidence], *, run_scoped: bool) -> list[str]:
    """What an answer cannot say, in so many words: that ARIA does not see systems as they are
    now, and which of the question's subjects no cited record mentions."""
    said: list[str] = []
    if asks_about_now(question):
        known = (
            "the logs this triage read and its records"
            if run_scoped
            else "its records of past incidents"
        )
        said.append(f"ARIA can't see your systems as they are now. It knows only {known}.")
    if cited:
        vocabulary = _vocabulary(" ".join(f"{item.title} {item.detail}" for item in cited))
        missing = sorted(
            term for term in terms(question) - _GENERIC if not _found(term, vocabulary)
        )
        if missing:
            quoted = [f"“{term}”" for term in missing[:4]]
            listed = quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} or {quoted[-1]}"
            said.append(f"Nothing below mentions {listed}.")
    return said


def runbook_evidence(
    services: Services, question: str, store: EvidenceStore, limit: int = 2
) -> None:
    """The runbooks a question names most of: what each covers and its first steps."""
    about = terms(question) - _GENERIC
    if not about:
        return
    scored = []
    for runbook in services.runbooks.values():
        if runbook.generic:
            continue
        text = " ".join([runbook.title, runbook.when, *runbook.systems, *runbook.failure_modes])
        own = _vocabulary(text)
        named = sum(1 for term in about if _found(term, own))
        if named and 2 * named >= len(about):
            scored.append((-named, runbook.slug, runbook))
    for _, _, runbook in sorted(scored)[:limit]:
        steps = [
            f"{step.text} [risk: {step.risk}]" if step.risk != "low" else step.text
            for step in runbook.mitigate
        ]
        store.add(
            EvidenceKind.RUNBOOK,
            f"Runbook {runbook.slug}: {runbook.title}",
            source="runbooks",
            detail="\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1)),
            data={
                "slug": runbook.slug,
                "runbook": runbook.slug,
                "risk": runbook.risk,
                "failure_modes": list(runbook.failure_modes),
            },
        )


async def memory_evidence(services: Services, question: str, *, limit: int = 6) -> list[Evidence]:
    """Past incidents that match the question, as citable evidence: the closest of each kind
    (system, failure and fix), since the library keeps several sightings of most kinds and each
    would otherwise read as another source saying the same thing."""
    store = EvidenceStore()
    kinds: set[tuple[str, str, str]] = set()
    for incident, hit in await services.memory.search(question, candidates=limit * 4):
        kind = (incident.system, incident.failure_mode, incident.resolution)
        if kind in kinds:
            continue
        kinds.add(kind)
        if len(kinds) > limit:
            break
        store.add(
            EvidenceKind.INCIDENT,
            f"Past incident {incident.id}: {incident.title} ({incident.severity}, {incident.system})",
            source="memory.search",
            detail=f"Failure mode: {incident.failure_mode}\nResolution: {incident.resolution}\n"
            f"Summary: {incident.summary}",
            data={
                "incident_id": incident.id,
                "title": headline(incident.title),
                "resolution": incident.resolution,
                "source": incident.source,
                "failure_mode": incident.failure_mode,
                "runbook": incident.runbook_slug,
                "score": round(hit.score, 4),
                "synthetic": incident.synthetic,
            },
            ts=incident.last_seen,
        )
    runbook_evidence(services, question, store)
    return store.all()


def _fallback(ranked: Sequence[Evidence]) -> AnswerOutput:
    if not ranked:
        return AnswerOutput(
            answer=[],
            insufficient_evidence=True,
            follow_ups=["Name a run, or ask about a system, component or failure mode."],
        )
    return AnswerOutput(answer=_claims(ranked), insufficient_evidence=False, follow_ups=[])


def _claims(ranked: Sequence[Evidence], *, limit: int = 3) -> list[ClaimOut]:
    """One statement per finding, in rank order. Past incidents that were fixed the same way share
    one statement that cites them all, rather than repeating the fix once for each.

    Each kind of evidence gets a statement before any kind gets a second, so a question in two
    parts ("why was it rated SEV3, and what do I do first?") hears about the rating and the
    runbook. The records of the tools that found incidents and runbooks come in only when nothing
    else matches: the incidents and runbooks say the same in plainer words."""
    plain = [
        item for item in ranked if item.source not in _REPEATS or item.kind is not EvidenceKind.TOOL
    ]
    plain = plain or list(ranked)
    groups: dict[str, list[Evidence]] = {}
    kinds: set[EvidenceKind] = set()
    placed: set[str] = set()
    for new_kinds_only in (True, False):
        for item in plain:
            if item.id in placed:
                continue
            fixed = _fixed(item)
            # Grouped by the fix's first step: a learned incident and a curated one fixed alike
            # are said once, not twice with the same steps.
            key = f"fix:{fixed[1].split(';')[0].lower()}" if fixed else item.id
            if key not in groups:
                if len(groups) >= limit or (new_kinds_only and item.kind in kinds):
                    continue
                groups[key] = []
                kinds.add(item.kind)
            groups[key].append(item)
            placed.add(item.id)
    return [
        ClaimOut(text=_clip(_plain_group(items), 400), evidence_ids=[item.id for item in items])
        for items in groups.values()
    ]


_WORDS = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven")


def _plain_group(items: Sequence[Evidence]) -> str:
    """Several past incidents with one fix, said once: how many, one example, and the fix."""
    if len(items) == 1 or (fixed := _fixed(items[0])) is None:
        return _plain(items[0])
    title, resolution = fixed
    learned = sum(1 for item in items if (item.data or {}).get("source") == "run")
    count = _WORDS[len(items) - 2] if len(items) - 2 < len(_WORDS) else str(len(items))
    samples = sum(1 for item in items if (item.data or {}).get("synthetic"))
    built = (
        " (built from samples)"
        if samples == len(items)
        else " (some built from samples)"
        if samples
        else ""
    )
    if learned == len(items):
        return (
            f"{count.capitalize()} similar past incidents, such as {title}, were triaged "
            f"by ARIA; the reviewers approved the same next steps: {resolution}"
        )
    # ARIA's own reports say what a reviewer approved, not what fixed it: a group that mixes
    # them with recorded fixes was "handled", not "resolved", the same way.
    done = "handled" if learned else "resolved"
    return (
        f"{count.capitalize()} similar past incidents{built}, such as {title}, were "
        f"{done} the same way: {resolution}"
    )


# A past incident as the investigation's search cites it, and the fix its detail records.
_SIMILAR = re.compile(r"^(?:Similar|Past) incident \S+: (?P<title>.+?)(?: \(SEV\d[^)]*\))?$")
_RESOLUTION = re.compile(r"^Resolution: (?P<fix>.+)$", re.MULTILINE)
# The seeded history names the runbook it followed; the runbook is cited on its own.
_FOLLOWED = re.compile(r"^Followed runbook \S+:\s*")


def _steps_text(resolution: str) -> str:
    """A fix as steps a responder reads once: no runbook ID, and no ".;" where steps that end in
    a full stop were joined."""
    parts = [
        p.strip().rstrip(".").strip() for p in _FOLLOWED.sub("", resolution.strip()).split(";")
    ]
    parts = [p for p in parts if p]
    if not parts:
        return resolution.strip()
    return "; ".join([parts[0], *(_sentence(p) for p in parts[1:])]) + "."


def _fixed(item: Evidence) -> tuple[str, str] | None:
    """A past incident's title and how it was resolved, when the evidence says both."""
    if item.kind is not EvidenceKind.INCIDENT:
        return None
    data = item.data or {}
    if data.get("title") and data.get("resolution"):
        return str(data["title"]), _steps_text(str(data["resolution"]))
    title, fix = _SIMILAR.match(item.title), _RESOLUTION.search(item.detail)
    return (title["title"], _steps_text(fix["fix"])) if title and fix else None


def _clip(text: str, limit: int) -> str:
    """At most ``limit`` characters, cut at a word with an ellipsis rather than mid-word."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


_HYPOTHESIS = re.compile(r"^H\d+ (?P<status>\w+): (?P<statement>.+)$", re.DOTALL)
_LINE = re.compile(r"^line (?P<n>\d+): (?P<line>.+)$", re.DOTALL)
_TEMPLATE = re.compile(r"^(?P<count>\d+)x (?P<pattern>.+)$", re.DOTALL)
_RULE = re.compile(
    r"^Rule \S+ \((?P<effect>score|floor) (?P<level>SEV\d)\): (?P<why>.+)$", re.DOTALL
)
_SCORES = re.compile(r"^(?P<by>Severity|Rule-score) probabilities: (?P<shown>.+)$")
_RUNBOOK = re.compile(r"^Runbook \S+: (?P<name>.+)$", re.DOTALL)
_STEP = re.compile(r"^\d+\.\s*(?P<text>.+?)(?:\s*\[risk: (?P<risk>\w+)\])?$")
# What each investigation tool's record says, for when nothing plainer matches a question.
_TOOL_LEADS = {
    "get_template_examples": "Examples of the pattern",
    "node_breakdown": "By server",
    "component_timeline": "Over time",
    "list_runbooks": "Runbooks that match",
    "get_runbook": "The runbook ARIA read",
}


def _levels(levels: Sequence[str]) -> str:
    """SEV2, or SEV2 or SEV3, or SEV1, SEV2 or SEV3."""
    if len(levels) < 2:
        return "".join(levels)
    return f"{', '.join(levels[:-1])} or {levels[-1]}"


def _sentence(text: str) -> str:
    """A clause that can follow a colon: lower-cased first letter unless it starts a name."""
    text = text.rstrip(".")
    return text[:1].lower() + text[1:] if text[1:2].islower() else text


def _plain(item: Evidence) -> str:
    """An answer line without a model: what the evidence says, in words a responder can act on,
    with internal IDs left to the citation chips."""
    data = item.data or {}
    sample = " (built from a sample)" if data.get("synthetic") else ""
    if fixed := _fixed(item):
        title, resolution = fixed
        if data.get("source") == "run":  # ARIA's own report: what was approved, not what fixed it
            return (
                f"A similar past incident, {title}, was triaged by ARIA; the reviewer "
                f"approved these next steps: {resolution}"
            )
        return f"A similar past incident, {title}{sample}, was resolved this way: {resolution}"
    if item.kind is EvidenceKind.INCIDENT and ": " in item.title:
        return f"A similar past incident{sample}: {item.title.split(': ', 1)[1]}"
    if item.kind is EvidenceKind.HYPOTHESIS and (found := _HYPOTHESIS.match(item.title)):
        verdict = {"supported": "supports", "refuted": "rules out"}.get(found["status"])
        statement = found["statement"].rstrip(".")
        if verdict is None:
            return f"The investigation is still testing this cause: {statement}."
        return f"The investigation {verdict} this cause: {statement}."
    if item.kind is EvidenceKind.LOG and (found := _LINE.match(item.title)):
        return f'Line {found["n"]} of the log reads: "{found["line"]}"'
    if item.kind is EvidenceKind.TEMPLATE and (found := _TEMPLATE.match(item.title)):
        pattern = found["pattern"].replace("<*>", "…")
        if found["count"] == "1":
            return f'One log line has a pattern of its own: "{pattern}"'
        return f'{found["count"]} log lines follow one pattern: "{pattern}"'
    if item.kind is EvidenceKind.RULE and (found := _RULE.match(item.title)):
        why = _sentence(found["why"])
        if found["effect"] == "floor":
            return f"A severity rule keeps this at {found['level']} or more serious: {why}."
        return f"A severity rule points to {found['level']}: {why}."
    if item.kind is EvidenceKind.MODEL and (found := _SCORES.match(item.title)):
        return _scores(found["by"], found["shown"], data) or item.title
    if item.kind is EvidenceKind.RUNBOOK and (found := _RUNBOOK.match(item.title)):
        name = found["name"].rstrip(".")
        steps = [line.strip() for line in item.detail.splitlines() if line.strip()]
        step = _STEP.match(steps[0]) if steps else None
        if step is None:
            return f'The runbook to follow is "{name}".'
        risk = f" (risk: {step['risk']})" if step["risk"] else ""
        return f'The runbook "{name}" starts with: {_sentence(step["text"])}{risk}.'
    if item.kind is EvidenceKind.FEATURE and item.source == "parser" and " events, " in item.title:
        return f"This log has {item.title}."
    if item.kind is EvidenceKind.TOOL and ": " in item.title:
        tool, summary = item.title.split(": ", 1)
        if tool == "search_incidents":  # the incidents themselves are cited on their own
            return f"The investigation found {summary.split(': ', 1)[0]}."
        lead = _TOOL_LEADS.get(tool, f"The investigation's {tool.replace('_', ' ')} check")
        return f"{lead}: {summary}"
    return item.title


def _scores(by: str, shown: str, data: JsonDict) -> str | None:
    """The severity model's (or, without it, the rules') most likely level and its short list."""
    try:
        scores = {level: float(p) for level, p in (pair.split(" ") for pair in shown.split(", "))}
    except ValueError:
        return None
    top = max(scores, key=lambda level: scores[level])
    if by == "Rule-score":
        return f"The severity rules give {top} the most weight ({scores[top]:.0%})."
    listed = [str(level) for level in data.get("prediction_set") or []]
    short = f"; its short list of likely levels is {_levels(listed)}" if listed else ""
    return f"The severity model finds {top} most likely ({scores[top]:.0%}){short}."


def check_answer(output: AnswerOutput, known: dict[str, Evidence]) -> list[str]:
    problems = []
    for i, claim in enumerate(output.answer):
        unknown = [e for e in claim.evidence_ids if e not in known]
        if unknown:
            problems.append(f"answer[{i}] cites unknown evidence {', '.join(unknown)}")
            continue
        loose = ungrounded_numbers(claim.text, [known[e] for e in claim.evidence_ids])
        if loose:
            problems.append(f"answer[{i}] has numbers its evidence lacks: {', '.join(loose[:5])}")
    return problems


async def answer(
    services: Services,
    question: str,
    evidence: Sequence[Evidence],
    *,
    use_llm: bool = True,
    router: LLMRouter | None = None,
) -> tuple[AnswerOutput, list[Evidence], str | None]:
    """The answer, the evidence it may cite, and the model that wrote it (None: retrieval).
    ``router``, when given, answers instead of the services' own (a visitor's key)."""
    ranked = rank(question, evidence)
    known = {item.id: item for item in ranked}
    router = router or services.router
    if use_llm and router.has_real_llm("ask") and ranked:
        facts = {"evidence_count": len(evidence)}
        # Evidence titles quote log templates and alert names, so they travel fenced.
        quoted = {"ranked_evidence": [{"id": e.id, "summary": e.title} for e in ranked]}
        try:
            result = await router.structured(
                "ask",
                "answer",
                build_messages(
                    "answer",
                    facts,
                    ranked,
                    untrusted={"question": question},
                    untrusted_data=quoted,
                ),
                AnswerOutput,
                validator=lambda output: check_answer(output, known),
                budget=BudgetGuard(ASK_BUDGET),
                temperature=0.0,
                max_tokens=700,
            )
        except (BudgetExceededError, LLMError):
            pass
        else:
            if not check_answer(result.value, known):
                return result.value, ranked, f"{result.provider}/{result.model}"
    return _fallback(ranked), ranked, None
