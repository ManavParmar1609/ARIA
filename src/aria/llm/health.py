"""Check that configured LLM providers work: credentials, reachability and model IDs.

``aria providers check`` runs this. It reads each provider's model catalog, confirms the
configured model IDs exist (they are marked ``verified: false`` in config until checked), and
sends one tiny chat and embedding request. Keys are never printed; the report only says which
environment variable a key came from.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from aria.config import ProviderConfig, ProviderKind
from aria.llm.base import LLMError, Message


@dataclass
class ProviderCheck:
    name: str
    kind: str
    enabled: bool
    credential: str  # where the credential comes from, never its value
    reachable: bool | None = None
    catalog_size: int | None = None
    models: dict[str, bool | None] = field(default_factory=dict)  # field -> found in catalog
    chat_ok: bool | None = None
    embed_ok: bool | None = None
    latency_ms: float | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.enabled and not self.problems


def _credential(cfg: ProviderConfig) -> str:
    if cfg.kind in (ProviderKind.FAKE, ProviderKind.LOCAL):
        return "not needed"
    if cfg.azure_ad:
        return "Microsoft Entra ID (managed identity)"
    source = cfg.api_key_source()
    if source is not None:
        return f"set via {source}"
    if cfg.allow_no_key:
        return "not needed (allow_no_key)"
    names = cfg.api_key_names()
    return f"missing: set {' or '.join(names)}" if names else "missing"


async def check_provider(
    name: str, cfg: ProviderConfig, provider: Any, *, probe: bool = True
) -> ProviderCheck:
    report = ProviderCheck(
        name=name, kind=str(cfg.kind), enabled=cfg.is_enabled(), credential=_credential(cfg)
    )
    if cfg.kind in (ProviderKind.FAKE, ProviderKind.LOCAL):
        return report
    if not report.enabled:
        missing = "an endpoint (base_url)" if not cfg.base_url else "a credential"
        report.problems.append(f"disabled: needs {missing}")
        return report
    catalog: list[str] = []
    try:
        catalog = await provider.list_models()
        report.reachable, report.catalog_size = True, len(catalog)
    except (LLMError, OSError) as exc:
        report.reachable = False
        report.problems.append(f"model catalog unavailable: {str(exc)[:160]}")
    # The safety model is listed so its ID gets checked, but it is optional (the guardrail is off
    # by default), so only a missing chat model counts as a problem.
    for field_name in ("chat_model", "embedding_model", "rerank_model", "safety_model"):
        model = getattr(cfg, field_name)
        if not model:
            continue
        if cfg.kind is ProviderKind.AZURE_OPENAI or not catalog:
            report.models[field_name] = None  # Azure lists base models, not deployment names
        else:
            report.models[field_name] = model in catalog
            if model not in catalog and field_name == "chat_model":
                report.problems.append(f"{model} is not in {name}'s model catalog")
    if not cfg.chat_model and not (cfg.embedding_model or cfg.rerank_model):
        # It answered its catalog, but every chat request would fail over to the next provider.
        report.problems.append("no chat model configured, so it cannot answer chat requests")
    if not probe:
        return report
    started = time.perf_counter()
    if cfg.chat_model:
        try:
            await provider.chat(
                [Message("user", "Reply with the single word OK.")], max_tokens=5, temperature=0.0
            )
            report.chat_ok = True
        except LLMError as exc:
            report.chat_ok = False
            report.problems.append(f"chat request failed: {str(exc)[:160]}")
    if cfg.embedding_model:
        try:
            vectors = await provider.embed(["disk full on node"], input_type="query")
            report.embed_ok = bool(vectors and vectors[0])
        except LLMError as exc:
            report.embed_ok = False
            report.problems.append(f"embedding request failed: {str(exc)[:160]}")
    report.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return report
