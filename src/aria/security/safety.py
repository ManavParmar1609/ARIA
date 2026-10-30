"""The optional content-safety guardrail: a safety model reads LLM-written text first.

On when ``guardrails.safety_model`` is true. The LLM config's ``safety`` chain names the providers
to ask (NVIDIA NIM by default, with an open Nemotron content-safety model as ``safety_model``).
ARIA sends the text as the assistant turn after a one-line description of the task and reads
the verdict. NemoGuard-style models answer with JSON such as
``{"User Safety": "safe", "Response Safety": "unsafe", "Safety Categories": "Violence"}``; a
plain ``safe`` or ``unsafe`` answer is read too.

The check fails closed: a verdict it cannot read, or a safety model it cannot reach, counts as
flagged, and the caller publishes its deterministic draft instead of the LLM's text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from aria.llm.base import BudgetExceededError, LLMError, Message
from aria.llm.budget import BudgetGuard
from aria.llm.router import LLMRouter

_JSON = re.compile(r"\{.*\}", re.DOTALL)
TASK = "Draft an incident report and responder messages from the log evidence provided."


@dataclass(frozen=True)
class SafetyVerdict:
    safe: bool
    categories: list[str] = field(default_factory=list)
    model: str | None = None
    detail: str = ""

    def describe(self) -> str:
        if self.safe:
            return "passed the content-safety check"
        why = ", ".join(self.categories) or self.detail or "unsafe"
        return f"flagged by the content-safety check ({why})"


def parse_verdict(text: str) -> tuple[bool, list[str]]:
    """Whether the response was judged safe, and the categories named; unreadable is unsafe."""
    match = _JSON.search(text)
    if match:
        try:
            raw: Any = json.loads(match.group(0))
        except json.JSONDecodeError:
            raw = None
        if isinstance(raw, dict):
            fields = {str(k).lower().replace("_", " "): v for k, v in raw.items()}
            verdict = str(fields.get("response safety", "")).strip().lower()
            categories = [
                c.strip()
                for c in str(fields.get("safety categories", "") or "").split(",")
                if c.strip()
            ]
            if verdict in ("safe", "unsafe"):
                return verdict == "safe", categories
    first = text.strip().split(maxsplit=1)[0].lower().strip(".,:;\"'") if text.strip() else ""
    if first in ("safe", "unsafe"):
        return first == "safe", []
    return False, ["unreadable verdict"]


def configured(router: LLMRouter | None) -> bool:
    return router is not None and any(router.is_available(n) for n in router.config.safety)


async def check_text(
    router: LLMRouter | None, text: str, *, budget: BudgetGuard | None = None
) -> SafetyVerdict:
    """Ask the safety chain about ``text``. Fails closed when no safety model can answer."""
    if router is None or not configured(router):
        return SafetyVerdict(False, detail="no safety model is configured")
    messages = [Message(role="user", content=TASK), Message(role="assistant", content=text)]
    try:
        result = await router.complete(
            "safety",
            messages,
            budget=budget,
            temperature=0.0,
            max_tokens=120,
            model_field="safety_model",
            chain=router.config.safety,
        )
    except BudgetExceededError as exc:
        return SafetyVerdict(False, detail=f"the run's {exc.reason} budget is spent")
    except LLMError as exc:
        return SafetyVerdict(False, detail=f"the safety model did not answer: {exc}")
    safe, categories = parse_verdict(result.value)
    return SafetyVerdict(safe, categories, model=f"{result.provider}/{result.model}")
