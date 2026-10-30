"""`aria providers check`: catalog, model IDs and probes, with mocked HTTP."""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from aria.cli import app
from aria.config import ProviderConfig, ProviderKind
from aria.llm.health import check_provider
from aria.llm.openai_compat import OpenAICompatibleProvider

NIM = "https://integrate.api.nvidia.com/v1"


def _cfg(**overrides: object) -> ProviderConfig:
    base: dict[str, object] = {
        "kind": ProviderKind.NVIDIA_NIM,
        "base_url": NIM,
        "api_key_env": "NVIDIA_API_KEY",
        "chat_model": "openai/gpt-oss-20b",
        "embedding_model": "nvidia/nemotron-3.5-embed-1b",
        "max_retries": 0,
    }
    base.update(overrides)
    return ProviderConfig(**base)  # type: ignore[arg-type]


def _mock_nim(catalog: list[str]) -> None:
    respx.get(f"{NIM}/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": m} for m in catalog]})
    )
    respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "OK"}}], "usage": {}}
        )
    )
    respx.post(f"{NIM}/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    )


@respx.mock
async def test_healthy_provider_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    _mock_nim(["openai/gpt-oss-20b", "nvidia/nemotron-3.5-embed-1b"])
    cfg = _cfg()
    report = await check_provider("nim", cfg, OpenAICompatibleProvider("nim", cfg))
    assert report.ok
    assert report.credential == "set via NVIDIA_API_KEY"
    assert report.models == {"chat_model": True, "embedding_model": True}
    assert (report.chat_ok, report.embed_ok) == (True, True)


@respx.mock
async def test_a_provider_with_no_chat_model_is_not_reported_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A self-hosted NIM set up with only its URL failed every call, yet the check said ok."""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    _mock_nim(["meta/llama-4-scout"])
    cfg = _cfg(chat_model=None, embedding_model=None)
    report = await check_provider("nim-local", cfg, OpenAICompatibleProvider("nim-local", cfg))
    assert not report.ok
    assert "no chat model configured" in "; ".join(report.problems)


@respx.mock
async def test_the_safety_model_id_is_checked_but_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    _mock_nim(["openai/gpt-oss-20b", "nvidia/nemotron-3.5-embed-1b"])
    cfg = _cfg(safety_model="nvidia/nemotron-3.5-content-safety")
    report = await check_provider("nim", cfg, OpenAICompatibleProvider("nim", cfg), probe=False)
    assert report.models["safety_model"] is False
    assert report.ok  # reported in the table, not failed: the guardrail is optional
    _mock_nim(["openai/gpt-oss-20b", "nvidia/nemotron-3.5-content-safety"])
    found = await check_provider("nim", cfg, OpenAICompatibleProvider("nim", cfg), probe=False)
    assert found.models["safety_model"] is True


@respx.mock
async def test_unknown_model_and_failed_chat_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    respx.get(f"{NIM}/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "other"}]})
    )
    respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(404, json={"detail": "Function not found for account"})
    )
    cfg = _cfg(embedding_model=None)
    report = await check_provider("nim", cfg, OpenAICompatibleProvider("nim", cfg))
    assert not report.ok
    assert report.models["chat_model"] is False
    assert any("not in nim's model catalog" in p for p in report.problems)
    assert any("chat request failed" in p for p in report.problems)
    assert "nvapi-test" not in " ".join(report.problems)


async def test_disabled_provider_explains_what_is_missing() -> None:
    report = await check_provider("nim", _cfg(), None)  # no NVIDIA_API_KEY in tests
    assert not report.enabled
    assert report.credential == "missing: set NVIDIA_API_KEY"
    assert report.problems == ["disabled: needs a credential"]


GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"


def _gemini_cfg() -> ProviderConfig:
    return ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url=GEMINI,
        api_key_env=["GEMINI_API_KEY", "gemini_api_key"],
        chat_model="gemini-3.6-flash",
        max_retries=0,
    )


async def test_a_missing_key_names_every_variable_it_may_come_from() -> None:
    report = await check_provider("gemini", _gemini_cfg(), None)
    assert report.credential == "missing: set GEMINI_API_KEY or gemini_api_key"


@respx.mock
async def test_gemini_ids_match_its_catalog_without_the_models_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("gemini_api_key", "AIza-test")
    respx.get(f"{GEMINI}/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "models/gemini-3.6-flash"}, {"id": "models/gemma-4"}]}
        )
    )
    respx.post(f"{GEMINI}/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "OK"}}], "usage": {}}
        )
    )
    cfg = _gemini_cfg()
    report = await check_provider("gemini", cfg, OpenAICompatibleProvider("gemini", cfg))
    assert report.ok
    assert report.credential == "set via gemini_api_key"  # names the variable, never the key
    assert report.models == {"chat_model": True}


@respx.mock
async def test_azure_deployments_are_not_matched_against_the_catalog() -> None:
    cfg = ProviderConfig(
        kind=ProviderKind.AZURE_OPENAI,
        base_url="https://r.openai.azure.com",
        allow_no_key=True,
        chat_model="my-deployment",
    )
    respx.get("https://r.openai.azure.com/openai/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gpt-5.1"}]})
    )
    report = await check_provider("azure", cfg, OpenAICompatibleProvider("azure", cfg), probe=False)
    assert report.models == {"chat_model": None}
    assert report.ok


def test_cli_check_exits_zero_when_only_disabled_providers_exist() -> None:
    result = CliRunner().invoke(app, ["providers", "check", "--no-probe"])
    assert result.exit_code == 0, result.output
    assert "disabled" in result.output
