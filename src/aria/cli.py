"""Command-line entry point: ``aria --help``."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, help="ARIA incident triage.")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations.")
data_app = typer.Typer(no_args_is_help=True, help="Download and ingest the public datasets.")
train_app = typer.Typer(
    help="Train and export the severity and ticket models.", invoke_without_command=True
)
providers_app = typer.Typer(no_args_is_help=True, help="Inspect LLM providers.")
eval_app = typer.Typer(no_args_is_help=True, help="Evaluate ARIA and gate regressions.")
app.add_typer(eval_app, name="eval")
app.add_typer(db_app, name="db")
app.add_typer(data_app, name="data")
app.add_typer(train_app, name="train")
app.add_typer(providers_app, name="providers")
console = Console()


@app.callback()
def main() -> None:
    """Load a local .env file (if present) before any command runs."""
    from aria.config import load_dotenv_file

    load_dotenv_file()


@app.command()
def version() -> None:
    """Print the installed ARIA version."""
    from aria import __version__

    console.print(__version__)


# --- database ----------------------------------------------------------------------------------


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply migrations up to REVISION (default: head)."""
    from aria.db.migrate import upgrade

    upgrade(revision)
    console.print(f"database upgraded to {revision}")


@db_app.command("current")
def db_current() -> None:
    """Show the current migration revision."""
    from aria.db.migrate import current

    current()


# --- data --------------------------------------------------------------------------------------


@data_app.command("download")
def data_download(
    source: Annotated[list[str] | None, typer.Option(help="Only these source ids.")] = None,
) -> None:
    """Download sources from data/manifest.yaml into data/raw and verify their checksums."""
    from aria.config import get_settings
    from aria.data.download import download
    from aria.data.manifest import load_manifest

    settings = get_settings()
    failures = 0
    for name, item in load_manifest().sources.items():
        if source and name not in source:
            continue
        try:
            path = download(item, settings.data_dir / "raw")
            console.print(f"[green]ok[/] {name} -> {path}")
        except Exception as exc:
            failures += 1
            console.print(f"[red]failed[/] {name}: {exc}")
    if failures:
        raise typer.Exit(code=1)


@data_app.command("ingest")
def data_ingest(bgl_max_lines: int = 500_000) -> None:
    """Load every downloaded dataset into the database (missing ones are skipped)."""
    from aria.config import get_settings
    from aria.data.ingest import ingest_all
    from aria.db.engine import get_engine

    settings = get_settings()
    for result in ingest_all(get_engine(), settings.data_dir / "raw", bgl_max_lines=bgl_max_lines):
        console.print(result)


# --- training ----------------------------------------------------------------------------------


def _loghub_dir() -> Path:
    from aria.config import get_settings
    from aria.evals.run import FIXTURES_DIR

    real = get_settings().data_dir / "raw" / "loghub-2k"
    if real.exists():
        return real
    console.print("[yellow]data/raw/loghub-2k not found (make data); using the test fixtures[/]")
    return FIXTURES_DIR


@train_app.callback()
def train_all(ctx: typer.Context) -> None:
    """With no subcommand, train every model."""
    if ctx.invoked_subcommand is None:
        train_severity()
        train_tickets()


@train_app.command("severity")
def train_severity(
    workers: Annotated[int, typer.Option(help="Parser processes.")] = min(4, os.cpu_count() or 1),
    per_mode: int = 6,
) -> None:
    """Fit, calibrate and export the log-severity model (models/severity_log.json)."""
    from aria.config import get_app_config
    from aria.severity.rules import load_rules
    from aria.severity.training import train_from_loghub

    config = get_app_config().severity
    rules = load_rules(config.rules_file)
    model, report = train_from_loghub(
        _loghub_dir(), rules, alpha=config.alpha, per_mode=per_mode, workers=workers
    )
    model.save(config.log_model_file)
    report_path = config.log_model_file.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    console.print(f"saved {config.log_model_file} ({model.version}); report: {report_path}")
    console.print_json(json.dumps(report["conformal_split"]))


@train_app.command("tickets")
def train_tickets() -> None:
    """Fit the UCI ticket priority and SLA models (needs `aria data ingest` with UCI data)."""
    from sqlalchemy import select

    from aria.config import get_app_config
    from aria.db.engine import get_engine, session_scope
    from aria.db.models import ItsmIncidentRow
    from aria.severity.ticket import fit_ticket_models

    config = get_app_config().severity
    with session_scope(get_engine()) as session:
        rows = [
            {c.name: getattr(row, c.name) for c in ItsmIncidentRow.__table__.columns}
            for row in session.scalars(select(ItsmIncidentRow))
        ]
    if not rows:
        console.print("[yellow]no UCI incidents in the database; skipping the ticket models[/]")
        return
    models, report = fit_ticket_models(rows, alpha=config.alpha)
    models.save(config.ticket_model_file)
    console.print(f"saved {config.ticket_model_file} ({models.version})")
    console.print_json(json.dumps(report, default=str))


# --- knowledge ---------------------------------------------------------------------------------


@app.command()
def seed(
    workers: Annotated[int, typer.Option(help="Parser processes.")] = min(4, os.cpu_count() or 1),
    per_mode: int = 3,
) -> None:
    """Load runbooks, seed incident memory (synthetic, labelled) and fit offline embeddings."""
    from aria.config import get_settings
    from aria.data.scenarios import LinePools, ScenarioBuilder
    from aria.db.engine import get_engine
    from aria.llm.local_embed import LsaEmbedder
    from aria.retrieval.memory import IncidentMemory
    from aria.retrieval.runbooks import load_runbooks, sync_runbooks
    from aria.retrieval.seed import seed_incidents

    settings = get_settings()
    engine = get_engine()
    runbooks = load_runbooks(settings.runbooks_dir)
    console.print(f"runbooks: {sync_runbooks(engine, runbooks)}")
    builder = ScenarioBuilder(LinePools.from_loghub(_loghub_dir()))
    incidents = seed_incidents(builder, settings.runbooks_dir, per_mode=per_mode, workers=workers)
    corpus = [i.document().text for i in incidents] + [rb.search_text() for rb in runbooks.values()]
    model_path = settings.models_dir / "embed_local.npz"
    LsaEmbedder.fit(corpus, dims=128).save(model_path)
    from aria.llm.router import get_router

    memory = IncidentMemory(engine, get_router().embedding_provider())

    async def store() -> int:
        return await memory.bulk_insert(incidents)

    count = asyncio.run(store())
    console.print(
        f"incident memory: {count} synthetic incidents (embeddings: {memory.embedding_model}); "
        f"offline embedder: {model_path}"
    )
    from aria.graph.store import SqlStore
    from aria.retrieval.seed import seed_known_templates

    templates = asyncio.run(seed_known_templates(SqlStore(engine), builder))
    console.print(f"template memory: {templates} routine-traffic templates")


@app.command()
def mcp(
    transport: Annotated[str, typer.Option(help="stdio or streamable-http")] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8001,
) -> None:
    """Run ARIA's read-only MCP server."""
    from aria.config import get_settings
    from aria.mcp.server import build_server
    from aria.observability.logging import configure_logging

    if transport not in ("stdio", "streamable-http"):
        raise typer.BadParameter("transport must be stdio or streamable-http")
    settings = get_settings()
    configure_logging(settings.log_level, "json" if transport == "stdio" else settings.log_format)
    server = build_server()
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=host, port=port)


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: Annotated[bool, typer.Option(help="Restart on code changes (development).")] = False,
) -> None:
    """Run the API: REST and SSE, MCP at /mcp, A2A at /a2a and AG-UI at /agui."""
    import uvicorn

    uvicorn.run(
        "aria.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        proxy_headers=True,
        log_level="info",
    )


@app.command()
def worker(
    concurrency: Annotated[int, typer.Option(min=1, max=64)] = 4,
    interval: Annotated[float, typer.Option(help="Seconds between queue polls.")] = 2.0,
) -> None:
    """Run queued triage runs from the database (for ARIA_WORKER_MODE=external)."""
    from aria.api.worker import poll_forever
    from aria.config import get_settings
    from aria.graph.runner import TriageRunner
    from aria.observability.logging import configure_logging
    from aria.services import Services

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    async def main() -> None:
        services = await Services.create()
        try:
            await poll_forever(TriageRunner(services), concurrency=concurrency, interval_s=interval)
        finally:
            await services.aclose()

    asyncio.run(main())


@app.command()
def triage(
    logs: Annotated[Path | None, typer.Argument(help="A log file (one line per event).")] = None,
    system: Annotated[str, typer.Option(help="Log format, e.g. bgl, hdfs, openssh.")] = "generic",
    scenario: Annotated[
        str | None, typer.Option(help="Use a semi-synthetic scenario, e.g. bgl.kernel_panic.")
    ] = None,
    approve: Annotated[bool, typer.Option(help="Approve and publish after the run.")] = False,
    use_llm: Annotated[bool, typer.Option(help="Allow LLM steps.")] = True,
) -> None:
    """Triage a log file (or a scenario) end to end and print the report."""
    from aria.contracts.inputs import RunOptions, TriageRequest
    from aria.data.scenarios import LinePools, ScenarioBuilder
    from aria.db import repository as repo
    from aria.graph.runner import TriageRunner
    from aria.services import Services

    synthetic = False
    if scenario:
        built = ScenarioBuilder(LinePools.from_loghub(_loghub_dir())).build(scenario, seed=1)
        lines, system, synthetic = built.lines, built.system, True
    elif logs is not None:
        lines = [line for line in logs.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        raise typer.BadParameter("give a log file or --scenario")
    request = TriageRequest(
        system=system, logs=lines, synthetic=synthetic, options=RunOptions(use_llm=use_llm)
    )

    async def main() -> None:
        services = await Services.create()
        try:
            runner = TriageRunner(services)
            outcome = await runner.start(request, trigger="cli")
            console.print(f"run {outcome.run_id}: {outcome.status}")
            if outcome.interrupt and approve:
                outcome = await runner.resume(
                    outcome.run_id, {"decision": "approve", "reviewer": "cli"}
                )
                console.print(f"after review: {outcome.status}")
            stored = repo.get_report(services.engine, f"rpt-{outcome.run_id}")
            if stored is not None:
                console.print(stored[1], markup=False, highlight=False)
        finally:
            await services.aclose()

    asyncio.run(main())


@eval_app.command("run")
def eval_run(
    *,
    suite: Annotated[
        str, typer.Option(help="smoke, severity, pipeline, robustness or all")
    ] = "smoke",
    gate: Annotated[bool, typer.Option(help="Fail when a threshold is missed (CI).")] = False,
    llm: Annotated[bool, typer.Option(help="Use the configured LLM chain (costs calls).")] = False,
    limit: Annotated[int | None, typer.Option(help="Cap end-to-end and robustness cases.")] = None,
    workers: Annotated[int, typer.Option(help="Parser processes.")] = 0,
    docs: Annotated[Path, typer.Option(help="Where `--suite all` writes the report.")] = Path(
        "docs/evaluation.md"
    ),
) -> None:
    """Run an evaluation suite; `--suite all` also regenerates docs/evaluation.md."""
    import json

    from aria.evals import report
    from aria.evals.run import check_gate, default_workers, run, save

    results = asyncio.run(
        run(
            suite,
            loghub_dir=_loghub_dir(),
            use_llm=llm,
            workers=workers or default_workers(),
            limit=limit,
        )
    )
    console.print(f"results: {save(results)}")
    for section in ("severity", "pipeline", "robustness"):
        if section in results:
            headline = {
                k: v
                for k, v in results[section].items()
                if k
                in ("n", "groundedness", "retrieval", "severity_invariant", "tool_use_invariant")
            }
            if section == "severity":
                headline["aria_policy"] = {
                    k: results[section]["methods"]["aria_policy"][k]
                    for k in ("accuracy", "macro_f1", "severe_under_triage")
                }
            console.print(f"[bold]{section}[/bold] {json.dumps(headline, default=str)}")
    if suite == "all" and not llm:
        live_path = Path("reports/eval/pipeline-llm.json")
        live = json.loads(live_path.read_text()) if live_path.exists() else None
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(report.render(results, live), encoding="utf-8")
        Path("docs/eval-results.json").write_text(
            json.dumps({k: v for k, v in results.items() if not k.endswith("_cases")}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        console.print(f"wrote {docs}")
    if gate:
        failures = check_gate(results, suite)
        for failure in failures:
            console.print(f"[red]gate:[/red] {failure}")
        if failures:
            raise typer.Exit(1)
        console.print("[green]gate passed[/green]")


@app.command()
def openapi(
    out: Annotated[Path, typer.Option(help="Where to write the schema.")] = Path("openapi.json"),
) -> None:
    """Export the API's OpenAPI schema (for generating the web client)."""
    import json

    from aria.api.app import create_app

    schema = create_app().openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    console.print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")


# --- providers ---------------------------------------------------------------------------------


@providers_app.command("list")
def providers_list() -> None:
    """Show every configured provider, whether it is enabled, and which roles use it."""
    from aria.llm.router import get_router

    table = Table("provider", "kind", "enabled", "chat model", "verified", "roles")
    for status in get_router().status():
        table.add_row(
            status.name,
            status.kind,
            "yes" if status.enabled else "no",
            status.chat_model or "-",
            "yes" if status.verified else "no",
            ", ".join(status.roles),
        )
    console.print(table)


@providers_app.command("check")
def providers_check(
    name: Annotated[str | None, typer.Argument(help="Only this provider.")] = None,
    probe: Annotated[bool, typer.Option(help="Send one tiny chat and embedding request.")] = True,
) -> None:
    """Verify keys, reachability and model IDs for the configured LLM providers."""
    from aria.llm.health import ProviderCheck, check_provider
    from aria.llm.router import get_router

    router = get_router()
    names = [name] if name else [n for n in router.config.providers if n not in ("fake", "local")]

    async def run() -> list[ProviderCheck]:
        try:
            reports = []
            for n in names:
                cfg = router.config.providers[n]
                provider = router.provider(n) if cfg.is_enabled() else None
                reports.append(await check_provider(n, cfg, provider, probe=probe))
            return reports
        finally:
            await router.aclose()

    table = Table(
        "provider", "credential", "reachable", "models in catalog", "chat", "embed", "problems"
    )

    def mark(value: bool | None) -> str:
        return "-" if value is None else ("yes" if value else "NO")

    failed = False
    for report in asyncio.run(run()):
        models = (
            ", ".join(f"{k.removesuffix('_model')}: {mark(v)}" for k, v in report.models.items())
            or "-"
        )
        failed = failed or (report.enabled and bool(report.problems))
        table.add_row(
            report.name,
            report.credential,
            mark(report.reachable),
            models,
            mark(report.chat_ok),
            mark(report.embed_ok),
            "; ".join(report.problems) or "ok",
        )
    console.print(table)
    if failed:
        raise typer.Exit(code=1)


@providers_app.command("models")
def providers_models(name: str) -> None:
    """List the models a provider serves (reads its /models endpoint)."""
    from aria.llm.router import get_router

    router = get_router()
    provider = router.provider(name)
    if not hasattr(provider, "list_models"):
        console.print(f"{name} has no model catalog")
        raise typer.Exit(code=1)

    async def fetch() -> list[str]:
        try:
            models: list[str] = await provider.list_models()
            return models
        finally:
            await router.aclose()

    for model in asyncio.run(fetch()):
        console.print(model)
