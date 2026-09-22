"""Shared fixtures for the M1 web runner unittest suite.

Loads the audited md_run_cli module and the shared mock docker executable from
the source skill (no Docker daemon or GPU is ever required), and builds
temporary SQLite databases and minimal manifests/stage plans for finalize.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
MD_RUN_CLI_PATH = (
    PLUGIN_ROOT / "source-skills" / "md-simulation-run" / "scripts" / "md_run_cli.py"
)
MOCK_DOCKER_PATH = (
    PLUGIN_ROOT / "source-skills" / "md-simulation-run" / "tests" / "mock_docker.py"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_mock_docker():
    return load_module("mock_docker", MOCK_DOCKER_PATH)


def load_md_run_cli():
    return load_module("md_run_cli", MD_RUN_CLI_PATH)


def make_db(path: Path, boot_id: str | None = None) -> sqlite3.Connection:
    from web.runner import db

    conn = db.connect(path)
    db.init(conn, boot_id=boot_id)
    return conn


def write_stage_plan(root: Path, stage: str = "em", deffnm: str = "em") -> Path:
    module = load_md_run_cli()
    plan = module.build_stage_plan(stage, deffnm, "linux-gpu", 8, False)
    path = root / f"{deffnm}_stage_plan.json"
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return path


def write_manifest(root: Path, work: Path, profile: str = "linux-gpu") -> Path:
    path = root / "md_run_manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact_type": "md_run_manifest",
                "work_dir": str(work.resolve()),
                "duration_plan": {"profile": profile},
            }
        ),
        encoding="utf-8",
    )
    return path
