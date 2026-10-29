from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from aria.config import (
    AppConfig,
    ProviderConfig,
    ProviderKind,
    get_app_config,
    get_settings,
    load_app_config,
    reset_caches,
)


def test_repo_config_loads_and_every_chain_ends_offline() -> None:
    config = get_app_config()
    for role in ("adjudicator", "investigator", "reporter", "critic", "comms", "ask"):
        chain = config.llm.chain(role)
        assert chain[-1] == "fake", role
    assert config.llm.embeddings[-1] == "local"


def test_providers_without_credentials_are_disabled() -> None:
    providers = get_app_config().llm.providers
    assert providers["fake"].is_enabled()
    assert providers["local"].is_enabled()
    assert not providers["nim"].is_enabled()  # no NVIDIA_API_KEY in tests
    assert not providers["azure"].is_enabled()  # no endpoint in tests


def test_provider_becomes_enabled_when_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    reset_caches()
    nim = get_app_config().llm.providers["nim"]
    assert nim.is_enabled()
    assert nim.base_url == "https://integrate.api.nvidia.com/v1"
    key = nim.api_key()
    assert key is not None
    assert key.get_secret_value() == "nvapi-test-key"
    assert "nvapi-test-key" not in repr(nim.api_key())


def test_env_interpolation_uses_defaults_and_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "aria.yaml"
    path.write_text(
        "llm:\n"
        "  providers:\n"
        "    nim:\n"
        "      kind: nvidia_nim\n"
        "      base_url: ${TEST_NIM_URL:-https://default.example/v1}\n"
        "      chat_model: ${TEST_NIM_MODEL}\n"
        "    fake: {kind: fake}\n"
        "  routing: {default: [nim, fake]}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_NIM_MODEL", "nvidia/test-model")
    config = load_app_config(path)
    nim = config.llm.providers["nim"]
    assert nim.base_url == "https://default.example/v1"
    assert nim.chat_model == "nvidia/test-model"


def test_unknown_provider_in_routing_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown providers: ghost"):
        AppConfig.model_validate(
            {"llm": {"providers": {"fake": {"kind": "fake"}}, "routing": {"x": ["ghost"]}}}
        )


def test_allow_no_key_enables_self_hosted_endpoint() -> None:
    provider = ProviderConfig(
        kind=ProviderKind.NVIDIA_NIM, base_url="http://nim:8000/v1", allow_no_key=True
    )
    assert provider.is_enabled()


def test_settings_split_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARIA_CORS_ORIGINS", "http://a.test, http://b.test")
    reset_caches()
    assert get_settings().cors_origins == ["http://a.test", "http://b.test"]
