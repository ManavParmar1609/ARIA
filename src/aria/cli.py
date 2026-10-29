"""Command-line entry point."""

import typer

app = typer.Typer(no_args_is_help=True, help="ARIA incident triage.")


@app.command()
def version() -> None:
    """Print the installed ARIA version."""
    from aria import __version__

    print(__version__)
