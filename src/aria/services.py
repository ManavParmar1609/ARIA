"""Long-lived services shared by the API, the worker, the MCP server and the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import Engine

from aria.config import AppConfig, Settings, get_app_config, get_settings
from aria.db.engine import get_engine
from aria.llm.router import LLMRouter, get_router
from aria.observability.logging import get_logger
from aria.retrieval.memory import IncidentMemory
from aria.retrieval.retriever import Retriever
from aria.retrieval.runbooks import Runbook, load_runbooks
from aria.severity.engine import SeverityEngine
from aria.severity.ticket import TicketModels

log = get_logger(__name__)


def _load_ticket_models(path: Path) -> TicketModels | None:
    if not path.exists():
        log.info("services.ticket_models_missing", path=str(path))
        return None
    return TicketModels.load(path)


@dataclass
class Services:
    settings: Settings
    config: AppConfig
    engine: Engine
    router: LLMRouter
    runbooks: dict[str, Runbook]
    memory: IncidentMemory
    retriever: Retriever
    severity: SeverityEngine
    tickets: TicketModels | None

    @classmethod
    async def create(
        cls,
        *,
        settings: Settings | None = None,
        config: AppConfig | None = None,
        engine: Engine | None = None,
        router: LLMRouter | None = None,
    ) -> Services:
        settings = settings or get_settings()
        config = config or get_app_config()
        engine = engine or get_engine()
        router = router or get_router()
        runbooks = load_runbooks(Path(settings.runbooks_dir))
        memory = IncidentMemory(engine, router.embedding_provider(), rrf_k=config.retrieval.rrf_k)
        await memory.refresh()
        retriever = Retriever(
            memory, runbooks, engine=engine, router=router, config=config.retrieval
        )
        tickets = _load_ticket_models(Path(config.severity.ticket_model_file))
        return cls(
            settings=settings,
            config=config,
            engine=engine,
            router=router,
            runbooks=runbooks,
            memory=memory,
            retriever=retriever,
            severity=SeverityEngine.load(config.severity),
            tickets=tickets,
        )

    async def aclose(self) -> None:
        await self.router.aclose()
