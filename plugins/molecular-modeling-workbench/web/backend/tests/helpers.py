"""Shared fixtures for the M2 backend unittest suite (no server is started)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from web.backend.app import create_app

TOKEN = "test-token-0123456789abcdef"


def make_client(workspace: Path | None = None):
    """Build a TestClient wired to a temporary workspace and runner DB."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    workspace_root = workspace if workspace is not None else (root / "workspace")
    workspace_root.mkdir(parents=True, exist_ok=True)
    app = create_app(
        token=TOKEN,
        workspace_roots=[workspace_root],
        db_path=root / "runner.db",
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    return client, tmp, workspace_root


def auth_headers(**extra: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    headers.update(extra)
    return headers
