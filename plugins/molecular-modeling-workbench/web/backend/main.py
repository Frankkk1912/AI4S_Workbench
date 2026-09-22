# pyright: reportMissingImports=false
"""uvicorn entry point for the local MD workbench backend (M2 T2.1).

The server binds 127.0.0.1 only (never a routable interface). On startup it
creates or reuses the local token file (0600), prints the token exactly once
for operator handoff, migrates the runner database, and serves the production
frontend from the same origin. Development mode leaves frontend serving to the
Vite proxy while retaining the same API security checks.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from web.runner import migrate

from .app import create_app
from .config import HOST, PORT, load_or_create_token
from .token_handoff import announce_once


def uvicorn_config(
    token_path: str | Path,
    workspace_roots: list[str | Path],
    db_path: str | Path | None = None,
    frontend_dist: str | Path | None = None,
) -> uvicorn.Config:
    """Build the production uvicorn config, always bound to 127.0.0.1."""
    token = load_or_create_token(Path(token_path))
    app = create_app(
        token=token,
        workspace_roots=workspace_roots,
        db_path=db_path,
        frontend_dist=frontend_dist,
    )
    return uvicorn.Config(app, host=HOST, port=PORT, log_level="info")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--token-file", help="Path to the 0600 token file (defaults under data-dir)."
    )
    parser.add_argument(
        "--workspace-root", action="append", required=True, dest="workspace_roots"
    )
    parser.add_argument("--data-dir", help="Private workbench data directory.")
    parser.add_argument("--db-path", help="Runner SQLite path (defaults under data-dir).")
    parser.add_argument(
        "--frontend-dist",
        help="Production frontend build directory (defaults to web/frontend/dist).",
    )
    parser.add_argument(
        "--development",
        action="store_true",
        help="Do not mount static assets; use the Vite development proxy.",
    )
    args = parser.parse_args(argv)

    data_dir = migrate.resolve_data_dir(args.workspace_roots[0], args.data_dir)
    paths = migrate.data_paths(data_dir)
    token_path = Path(args.token_file).expanduser() if args.token_file else paths["token"]
    db_path = Path(args.db_path).expanduser() if args.db_path else paths["db"]
    frontend_dist = None
    if not args.development:
        frontend_dist = Path(args.frontend_dist).expanduser() if args.frontend_dist else (
            Path(__file__).resolve().parents[1] / "frontend" / "dist"
        )

    token = load_or_create_token(token_path)
    announce_once(token)
    app = create_app(
        token=token,
        workspace_roots=args.workspace_roots,
        db_path=db_path,
        frontend_dist=frontend_dist,
    )
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
