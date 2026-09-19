# pyright: reportMissingImports=false
"""FastAPI application factory (M2 T2.1/T2.2/T2.4/T2.5/T2.6).

`create_app` wires the routers behind the shared token + local-request security
dependencies and initializes the runner SQLite authority when a DB path is
provided. The application is always served on 127.0.0.1 (enforced by main.py's
uvicorn config), and every route requires the local token.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.runner import db

from .routers import params, runs, stream
from .routers.analysis import router as analysis_router
from .token_handoff import router as token_handoff_router


def create_app(
    token: str,
    workspace_roots: list[str | Path],
    db_path: str | Path | None = None,
    title: str = "md-local-workbench",
    frontend_dist: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(title=title)
    app.state.token = token
    app.state.workspace_roots = [str(Path(root).resolve()) for root in workspace_roots]
    app.state.db_path = str(Path(db_path).resolve()) if db_path is not None else None

    if app.state.db_path is not None:
        conn = db.connect(app.state.db_path)
        db.init(conn)
        conn.close()

    app.include_router(runs.router)
    app.include_router(stream.router)
    app.include_router(params.router)
    app.include_router(analysis_router)
    app.include_router(token_handoff_router)

    if frontend_dist is not None:
        frontend = Path(frontend_dist).resolve()
        if not frontend.is_dir():
            raise ValueError(f"frontend build directory does not exist: {frontend}")
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
    return app
