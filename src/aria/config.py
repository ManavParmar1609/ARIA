"""Runtime configuration.

Two layers:

* ``Settings`` comes from ``ARIA_*`` environment variables (and ``.env``): deployment facts such
  as the database URL, API keys and telemetry exporters.
* ``AppConfig`` comes from ``config/aria.yaml``: behaviour such as LLM providers and per-role
  routing, budgets, guardrails and retrieval knobs. String values may reference environment
  variables as ``${NAME}`` or ``${NAME:-default}``.

Secrets never live in the YAML file. A provider names the environment variable that holds its
key, and a provider whose key is missing is treated as disabled, so fallback chains skip it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_ENV_REF = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::-(?P<default>[^}]*))?\}")
_RESET_HOOKS: list[Callable[[], None]] = []


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class ProviderKind(StrEnum):
    NVIDIA_NIM = "nvidia_nim"
    AZURE_OPENAI = "azure_openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    FAKE = "fake"
    LOCAL = "local"


class StructuredOutputMode(StrEnum):
    """How a provider is asked for JSON that matches a schema."""

    JSON_SCHEMA = "json_schema"  # response_format={"type": "json_schema", strict}
    JSON_OBJECT = "json_object"  # response_format={"type": "json_object"} plus schema in prompt
    GUIDED_JSON = "guided_json"  # NIM / vLLM nvext.guided_json
    PROMPT = "prompt"  # schema in the prompt only; validation and repair do the rest


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(_Strict):
    kind: ProviderKind
    base_url: str | None = None
    api_key_env: str | None = None
    allow_no_key: bool = False
    azure_ad: bool = False
    api_version: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    rerank_model: str | None = None
    rerank_url: str | None = None
    safety_model: str | None = None
    structured_output: StructuredOutputMode = StructuredOutputMode.JSON_SCHEMA
    supports_streaming: bool = True
    # Stream every request, so a model that stalls (sends nothing for stall_timeout_s) fails
    # over quickly instead of holding the run until the full timeout.
    stream_always: bool = False
    stall_timeout_s: float | None = Field(default=None, gt=0)
    reasoning_effort: str | None = None  # sent only when set: low | medium | high
    extra_body: dict[str, Any] = Field(default_factory=dict)
    timeout_s: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=6)
    price_input_per_mtok: float | None = Field(default=None, ge=0)
    price_output_per_mtok: float | None = Field(default=None, ge=0)
    verified: bool = False
    notes: str | None = None

    @field_validator(
        "base_url",
        "chat_model",
        "embedding_model",
        "rerank_model",
        "rerank_url",
        "safety_model",
        "reasoning_effort",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        # `${VAR:-}` interpolates to "" when VAR is unset; treat that as "not configured".
        return None if isinstance(value, str) and not value.strip() else value

    def api_key(self) -> SecretStr | None:
        if not self.api_key_env:
            return None
        value = os.environ.get(self.api_key_env, "").strip()
        return SecretStr(value) if value else None

    def is_enabled(self) -> bool:
        """A provider is usable when it has an endpoint and a credential (or needs none)."""
        if self.kind in (ProviderKind.FAKE, ProviderKind.LOCAL):
            return True
        if not self.base_url:
            return False
        return self.allow_no_key or self.azure_ad or self.api_key() is not None


class LLMConfig(_Strict):
    providers: dict[str, ProviderConfig]
    routing: dict[str, list[str]] = Field(default_factory=dict)
    embeddings: list[str] = Field(default_factory=lambda: ["local"])
    rerank: list[str] = Field(default_factory=list)
    safety: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _chains_reference_known_providers(self) -> LLMConfig:
        # The offline providers always exist so every chain can end somewhere that works.
        self.providers.setdefault("fake", ProviderConfig(kind=ProviderKind.FAKE, verified=True))
        self.providers.setdefault("local", ProviderConfig(kind=ProviderKind.LOCAL, verified=True))
        chains = [*self.routing.values(), self.embeddings, self.rerank, self.safety]
        unknown = sorted({name for chain in chains for name in chain} - self.providers.keys())
        if unknown:
            msg = f"routing references unknown providers: {', '.join(unknown)}"
            raise ValueError(msg)
        return self

    def chain(self, role: str) -> list[str]:
        """Provider names to try for a role, falling back to the fake provider."""
        return self.routing.get(role) or self.routing.get("default") or ["fake"]


class BudgetConfig(_Strict):
    max_tokens: int = Field(default=60_000, gt=0)
    max_cost_usd: float = Field(default=0.50, ge=0)
    max_latency_s: float = Field(default=180.0, gt=0)
    max_steps: int = Field(default=80, gt=0)
    max_tool_calls: int = Field(default=40, gt=0)
    max_llm_calls: int = Field(default=16, ge=0)


class GuardrailConfig(_Strict):
    redact_pii: bool = True
    pseudonymize_ips: bool = True
    detect_injection: bool = True
    safety_model: bool = False
    max_line_chars: int = Field(default=2_000, gt=80)
    max_lines: int = Field(default=20_000, gt=0)


class SeverityConfig(_Strict):
    alpha: float = Field(default=0.10, gt=0, lt=0.5)
    rules_file: Path = Path("config/severity_rules.yaml")
    service_catalog_file: Path = Path("config/service_catalog.yaml")
    log_model_file: Path = Path("models/severity_log.json")
    ticket_model_file: Path = Path("models/severity_ticket.json")
    # Active learning: recalibrate the conformal threshold on reviewed incidents once this many
    # new human reviews have gathered, checking every recalibrate_check_s seconds (0: never).
    recalibrate_after: int = Field(default=30, ge=10, le=100_000)
    recalibrate_check_s: int = Field(default=600, ge=0)


class RetrievalConfig(_Strict):
    k: int = Field(default=3, ge=1, le=20)
    candidates: int = Field(default=12, ge=1, le=200)
    widen_candidates: int = Field(default=40, ge=1, le=500)
    min_grade: float = Field(default=0.35, ge=0, le=1)
    max_attempts: int = Field(default=3, ge=1, le=6)
    rrf_k: int = Field(default=60, ge=1)


class ScanSource(_Strict):
    """A log file the periodic scan tails, and the log format (system) its lines are in."""

    system: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    path: Path


class TriggerConfig(_Strict):
    alert_group_window_s: int = Field(default=300, ge=10)
    # The periodic log scan: off at 0. Every interval it reads the lines appended to each source
    # and opens a run when the recent window's error burst score reaches the minimum.
    scan_interval_s: int = Field(default=0, ge=0)
    scan_min_burst_score: float = Field(default=3.0, ge=0)
    scan_window_lines: int = Field(default=2000, ge=50, le=20000)
    scan_sources: list[ScanSource] = Field(default_factory=list)

    @field_validator("scan_sources", mode="before")
    @classmethod
    def _split_sources(cls, value: Any) -> Any:
        # From an environment variable: "hdfs=/var/log/hdfs.log, openssh=/var/log/auth.log".
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
            return [
                dict(zip(("system", "path"), item.split("=", 1), strict=False)) for item in items
            ]
        return value


class CommsConfig(_Strict):
    slack_webhook_env: str = "SLACK_WEBHOOK_URL"
    teams_webhook_env: str = "TEAMS_WEBHOOK_URL"
    generic_webhook_env: str = "ARIA_OUTBOUND_WEBHOOK_URL"
    # Name of the variable holding the HMAC key that signs generic webhook deliveries.
    generic_webhook_secret_env: str = "ARIA_OUTBOUND_WEBHOOK_SECRET"  # noqa: S105
    timeout_s: float = Field(default=10.0, gt=0, le=60)


class InvestigationConfig(_Strict):
    max_steps: int = Field(default=6, ge=0, le=20)  # tool calls per investigation
    max_rounds: int = Field(default=2, ge=1, le=10)  # decision rounds (one LLM call each)
    max_parallel: int = Field(default=5, ge=1, le=10)  # tool calls one round may run at once
    max_hypotheses: int = Field(default=4, ge=1, le=10)


class AppConfig(_Strict):
    llm: LLMConfig
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    guardrails: GuardrailConfig = Field(default_factory=GuardrailConfig)
    severity: SeverityConfig = Field(default_factory=SeverityConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    investigation: InvestigationConfig = Field(default_factory=InvestigationConfig)
    triggers: TriggerConfig = Field(default_factory=TriggerConfig)
    comms: CommsConfig = Field(default_factory=CommsConfig)


class Settings(BaseSettings):
    """Deployment settings from ``ARIA_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="ARIA_", env_file=".env", extra="ignore")

    env: Environment = Environment.DEV
    database_url: str = "sqlite:///data/aria.db"
    database_auth: Literal["default", "entra"] = "default"
    config_file: Path = Path("config/aria.yaml")
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    runbooks_dir: Path = Path("runbooks")
    api_keys: SecretStr | None = None
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"
    otel_exporter: Literal["none", "console", "otlp", "azure"] = "none"
    otlp_endpoint: str | None = None
    worker_mode: Literal["inprocess", "external"] = "inprocess"
    # Bring the schema to the latest migration when the API starts (containers). Run one API
    # replica while a release migrates, or run `aria db upgrade` as a job instead.
    migrate_on_start: bool = False
    worker_concurrency: int = Field(default=4, ge=1, le=64)
    # An HTTP port where `aria worker` answers liveness probes from its heartbeat (Container Apps
    # probes over HTTP and ignores the image's HEALTHCHECK). Unset: no endpoint.
    worker_health_port: int | None = Field(default=None, ge=1, le=65_535)
    require_approval: bool = True
    rate_limit_per_minute: int = Field(default=120, ge=1)
    # Largest request body the API reads; 20,000 lines of 2,000 characters fit with room to spare.
    max_body_bytes: int = Field(default=48 * 1024 * 1024, ge=1024)
    public_base_url: str = "http://localhost:8000"
    # Where people open a run (the web console). Messages link there; without it they link to
    # the run in the API.
    console_url: str | None = None
    web_dist_dir: Path | None = None
    # Keys each run's pseudonym salt as HMAC(key, run id), so pseudonyms stay stable when a run
    # retries or resumes and no salt is stored in graph state. When unset, a random key is made
    # at process start.
    pseudonym_key: SecretStr | None = None
    # The investigator calls tools on this MCP endpoint (streamable HTTP) when set, otherwise on
    # an in-process server that shares the caller's services.
    mcp_url: str | None = None
    mcp_token: SecretStr | None = None

    @field_validator("api_keys", "pseudonym_key", "mcp_token", "mcp_url", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        # Compose and shell defaults pass "" for an unset variable; an empty secret must not
        # count as configured (an empty pseudonym key would make pseudonyms linkable).
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_prod(self) -> bool:
        return self.env is Environment.PROD


def _interpolate(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_REF.sub(
            lambda m: os.environ.get(m.group("name"), m.group("default") or ""), value
        )
    if isinstance(value, dict):
        return {key: _interpolate(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_interpolate(item) for item in value]
    return value


def load_app_config(path: Path) -> AppConfig:
    """Load ``AppConfig`` from YAML, substituting ``${ENV}`` references."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        msg = f"{path} must contain a mapping"
        raise ValueError(msg)
    return AppConfig.model_validate(_interpolate(raw))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    return load_app_config(get_settings().config_file)


def load_dotenv_file(path: Path = Path(".env")) -> bool:
    """Load ``.env`` into the process environment without overriding variables already set.

    Provider keys (``NVIDIA_API_KEY``, ``AZURE_OPENAI_API_KEY``, ...) are read with
    ``os.environ``, so entry points call this once at startup for local development. Real
    deployments set environment variables (or Key Vault references) instead.
    """
    if not path.is_file() or os.environ.get("ARIA_ENV") == "test":
        return False  # tests stay hermetic: a developer's real keys never leak into them
    from dotenv import load_dotenv  # noqa: PLC0415 - ships with pydantic-settings

    loaded = bool(load_dotenv(path, override=False))
    reset_caches()
    return loaded


def register_reset_hook(hook: Callable[[], None]) -> None:
    """Register a cache that depends on settings, so ``reset_caches`` clears it too."""
    if hook not in _RESET_HOOKS:
        _RESET_HOOKS.append(hook)


def reset_caches() -> None:
    """Clear cached settings and everything built from them; tests call this between cases."""
    get_settings.cache_clear()
    get_app_config.cache_clear()
    for hook in _RESET_HOOKS:
        hook()
