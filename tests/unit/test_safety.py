"""The optional content-safety guardrail: reading verdicts and failing closed."""

from __future__ import annotations

import json

import pytest

from aria.config import LLMConfig, ProviderConfig, ProviderKind
from aria.llm.base import ProviderError
from aria.llm.fake import FakeProvider
from aria.llm.router import LLMRouter
from aria.security.safety import check_text, parse_verdict

SAFE = json.dumps({"User Safety": "safe", "Response Safety": "safe"})
UNSAFE = json.dumps(
    {
        "User Safety": "safe",
        "Response Safety": "unsafe",
        "Safety Categories": "Violence, Criminal Planning",
    }
)


def safety_router(fake: FakeProvider, *, safety: bool = True) -> LLMRouter:
    config = LLMConfig(
        providers={
            "llm": ProviderConfig(
                kind=ProviderKind.NVIDIA_NIM,
                base_url="http://x/v1",
                allow_no_key=True,
                chat_model="chat",
                safety_model="guard",
            )
        },
        safety=["llm"] if safety else [],
    )
    fake.kind = ProviderKind.NVIDIA_NIM
    return LLMRouter(config, providers={"llm": fake})


@pytest.mark.parametrize(
    ("text", "safe", "categories"),
    [
        (SAFE, True, []),
        (UNSAFE, False, ["Violence", "Criminal Planning"]),
        ('Verdict: {"response_safety": "Safe"}', True, []),
        ("unsafe\nS1: Violence", False, []),
        ("Safe.", True, []),
        ("I can't help with that.", False, ["unreadable verdict"]),
        ("", False, ["unreadable verdict"]),
        ('{"Response Safety": "maybe"}', False, ["unreadable verdict"]),
    ],
)
def test_verdicts_are_read_and_unreadable_ones_count_as_unsafe(
    text: str, safe: bool, categories: list[str]
) -> None:
    assert parse_verdict(text) == (safe, categories)


async def test_the_check_asks_the_safety_model_about_the_text() -> None:
    fake = FakeProvider(script={"text": [UNSAFE]})
    verdict = await check_text(safety_router(fake), "Wipe the disks and blame the night shift.")
    assert not verdict.safe
    assert verdict.categories == ["Violence", "Criminal Planning"]
    assert verdict.model == "llm/guard"
    assert "Violence" in verdict.describe()
    call = fake.calls[-1]
    assert call["model"] == "guard"
    assert [m.role for m in call["messages"]] == ["user", "assistant"]
    assert call["messages"][1].content == "Wipe the disks and blame the night shift."


async def test_the_check_fails_closed() -> None:
    unconfigured = await check_text(safety_router(FakeProvider(), safety=False), "anything")
    assert not unconfigured.safe
    assert "no safety model" in unconfigured.detail
    assert not (await check_text(None, "anything")).safe

    down = FakeProvider(script={"text": [ProviderError("unavailable", status=503)]})
    verdict = await check_text(safety_router(down), "anything")
    assert not verdict.safe
    assert "did not answer" in verdict.detail
