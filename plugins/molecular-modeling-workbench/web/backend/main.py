"""uvicorn entry point for the local MD workbench backend (M2 T2.1).

The server binds 127.0.0.1 only (never a routable interface). On startup it
creates or reuses the local token file (0600), prints the token exactly once
for operator handoff, and serves the FastAPI application. Same-origin static
frontend serving and the full token handoff flow are deferred to T6.8.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .app import create_app
from .config import HOST, PORT, load_or_create_token


def uvicorn_config(
    token_path: str | Path,
    workspace_roots: list[str | Path],
    db_path: str | Path | None = None,
) -> uvicorn.Config:
    """Build the production uvicorn config, always bound to 127.0.0.1."""
    token = load_or_create_token(Path(token_path))
    app = create_app(
        token=token,
        workspace_roots=workspace_roots,
        db_path=db_path,
    )
    return uvicorn.Config(app, host=HOST, port=PORT, log_level="info")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--token-file", required=True, help="Path to the 0600 token file."
    )
    parser.add_argument(
        "--workspace-root", action="append", required=True, dest="workspace_roots"
    )
    parser.add_argument("--db-path", default="runner.db", help="Runner SQLite path.")
    args = parser.parse_args(argv)

    token = load_or_create_token(Path(args.token_file))
    # Printed exactly once at startup for local operator handoff (T6.8 wires the
    # browser-side handoff; this is the single source of the token).
    print(f"Local access token: {token}")
    app = create_app(
        token=token,
        workspace_roots=args.workspace_roots,
        db_path=args.db_path,
    )
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
