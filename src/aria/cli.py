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
app.add_typer(db_app, name="db")
app.add_typer(data_app, name="data")
app.add_typer(train_app, name="train")
app.add_typer(providers_app, name="providers")
console = Console()


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

    real = get_settings().data_dir / "raw" / "loghub-2k"
    if real.exists():
        return real
    console.print("[yellow]data/raw/loghub-2k not found; training on the small test fixtures[/]")
    return Path("tests/fixtures/loghub")


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
