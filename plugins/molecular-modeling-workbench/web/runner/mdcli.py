"""Audited md_run_cli loader for the web runner (D6: module import first).

The runner reuses the audited primitives (parse_log, plan_hash,
read_stage_plan, validate_stage_prerequisites, validate_receipt,
collect_stage_artifacts, stage_outcome, launch_container_name) by importing
the skill's module directly. The module import is primary; a subprocess
fallback is available for environments where the import path cannot be
resolved. Logic is never copied out of the audited CLI.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
MD_RUN_CLI_PATH = (
    PLUGIN_ROOT / "source-skills" / "md-simulation-run" / "scripts" / "md_run_cli.py"
)
_MODULE = None


def load_md_run_cli():
    """Import the audited md_run_cli module (cached). Raises if unavailable."""
    global _MODULE
    if _MODULE is not None:
        return _MODULE
    spec = importlib.util.spec_from_file_location("md_run_cli", MD_RUN_CLI_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load audited md_run_cli from {MD_RUN_CLI_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE = module
    return module


def parse_log_via_cli(log: Path, total_steps: int, stale_minutes: float) -> dict:
    """Subprocess fallback: ask the audited CLI for a progress document."""
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "manifest.json"
        manifest.write_text('{"work_dir": "' + str(Path.cwd()) + '"}')
        output = Path(tmp) / "progress.json"
        result = subprocess.run(
            [
                sys.executable,
                str(MD_RUN_CLI_PATH),
                "status",
                "--manifest",
                str(manifest),
                "--log",
                str(log),
                "--total-steps",
                str(total_steps),
                "--stale-after-minutes",
                str(stale_minutes),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError(
                f"md_run_cli status fallback failed: {result.stderr.strip()}"
            )
        import json

        return json.loads(output.read_text(encoding="utf-8"))
