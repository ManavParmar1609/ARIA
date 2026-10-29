"""Run ARIA's MCP server: ``python -m aria.mcp [--transport stdio|streamable-http]``."""

from __future__ import annotations

import argparse

from aria.config import get_settings, load_dotenv_file
from aria.mcp.server import build_server
from aria.observability.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    load_dotenv_file()
    settings = get_settings()
    # stdio carries the protocol on stdout, so logs must stay on stderr (structlog's default).
    configure_logging(
        settings.log_level, "json" if args.transport == "stdio" else settings.log_format
    )
    server = build_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
