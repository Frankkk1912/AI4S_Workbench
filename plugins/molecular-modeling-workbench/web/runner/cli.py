# pyright: reportMissingImports=false
"""User-owned runner lifecycle and diagnostics CLI (T6.7).

``start``, ``status`` and ``stop`` operate only on systemd *user* units. They
never invoke sudo or mutate host-wide services. ``diagnose`` is read-only and
reports the SQLite summary, workbench-labeled containers, boot identity, token
file state, disk capacity, and user-linger status without exposing secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from . import db, lock, reconcile
from .executor import tick
from .migrate import (
    ACCESS_FILE_NAME,
    DB_FILE_NAME,
    data_paths,
    ensure_data_dir,
    migrate,
)

UNITS = ("ai4s-md-runner.service", "ai4s-md-api.service")
RUN_LABEL = "ai4s.workbench.run_id"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def linger_status(command_runner=_run) -> dict[str, Any]:
    result = command_runner(
        ["loginctl", "show-user", str(os.getuid()), "-p", "Linger", "--value"]
    )
    enabled = result.returncode == 0 and result.stdout.strip().casefold() == "yes"
    return {
        "enabled": enabled,
        "warning": None
        if enabled
        else (
            "user linger is not enabled; services may stop after logout. "
            "Enabling linger is a separate user decision."
        ),
    }


def service_control(action: str, command_runner=_run) -> dict[str, Any]:
    if action not in {"start", "stop"}:
        raise ValueError(f"unsupported service action: {action}")
    result = command_runner(["systemctl", "--user", action, *UNITS])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"systemctl {action} failed")
    return {"action": action, "units": list(UNITS), "linger": linger_status(command_runner)}


def service_status(command_runner=_run) -> dict[str, Any]:
    states: dict[str, str] = {}
    for unit in UNITS:
        result = command_runner(["systemctl", "--user", "is-active", unit])
        states[unit] = result.stdout.strip() or "unknown"
    return {"units": states, "linger": linger_status(command_runner)}


def _database_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path)}
    conn = sqlite3.connect(path)
    try:
        version = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        statuses = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT status, COUNT(*) FROM runs GROUP BY status ORDER BY status"
            ).fetchall()
        }
        recorded = conn.execute(
            "SELECT value FROM meta WHERE key = 'boot_id'"
        ).fetchone()
    except sqlite3.Error as exc:
        return {"exists": True, "path": str(path), "error": str(exc)}
    finally:
        conn.close()
    return {
        "exists": True,
        "path": str(path),
        "schema_version": version[0] if version else None,
        "recorded_boot_id": recorded[0] if recorded else None,
        "runs_by_status": statuses,
    }


def _container_summary(docker_path: str, command_runner=_run) -> dict[str, Any]:
    result = command_runner(
        [
            docker_path,
            "ps",
            "-a",
            "--filter",
            f"label={RUN_LABEL}",
            "--format",
            "{{json .}}",
        ]
    )
    if result.returncode != 0:
        return {"reachable": False, "containers": [], "error": result.stderr.strip()}
    containers: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            containers.append(json.loads(line))
        except ValueError as exc:
            return {
                "reachable": False,
                "containers": [],
                "error": f"docker ps returned malformed JSON: {exc}",
            }
    return {"reachable": True, "containers": containers}


def diagnose(
    data_dir: str | Path,
    *,
    docker_path: str = "docker",
    command_runner=_run,
) -> dict[str, Any]:
    root = Path(data_dir).expanduser().resolve()
    disk_probe = root
    while not disk_probe.exists() and disk_probe != disk_probe.parent:
        disk_probe = disk_probe.parent
    usage = shutil.disk_usage(disk_probe)
    db_path = root / DB_FILE_NAME
    access_file = root / ACCESS_FILE_NAME
    access_permissions = (
        oct(access_file.stat().st_mode & 0o777) if access_file.exists() else None
    )
    return {
        "data_dir": str(root),
        "database": _database_summary(db_path),
        "containers": _container_summary(docker_path, command_runner),
        "boot": {"current": db.current_boot_id()},
        "token": {
            "exists": access_file.is_file(),
            "mode": access_permissions,
            "secure": access_file.is_file() and access_permissions == "0o600",
        },
        "disk": {"free_bytes": usage.free, "total_bytes": usage.total},
        "linger": linger_status(command_runner),
    }


def serve(
    data_dir: str | Path,
    *,
    docker_path: str = "docker",
    poll_seconds: float = 30.0,
    once: bool = False,
) -> None:
    """Run the single-instance hosted execution and reconciliation loop."""
    paths = data_paths(data_dir)
    with lock.RunnerLock(paths["root"] / "runner.lock"):
        conn = db.connect(paths["db"])
        schema_path = Path(db.__file__).with_name("schema.sql")
        migrate(conn, schema_path=schema_path, target_version=db.SCHEMA_VERSION)
        current = db.current_boot_id()
        if db.recorded_boot_id(conn) is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('boot_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (current,),
            )
        docker = reconcile.DockerPort(docker_path)
        try:
            while True:
                host_restarted = db.boot_changed(conn, current=current)
                if host_restarted or docker.is_reachable():
                    # A boot change is classified before dispatch/finalize. This
                    # prevents an interrupted computation from being adopted or
                    # relaunched automatically on a new host boot.
                    tick(conn, docker, current_boot=current)
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES ('boot_id', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (current,),
                )
                if once:
                    break
                time.sleep(poll_seconds)
        finally:
            conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start")
    sub.add_parser("status")
    sub.add_parser("stop")
    diagnose_parser = sub.add_parser("diagnose")
    diagnose_parser.add_argument("--data-dir", required=True)
    diagnose_parser.add_argument("--docker-path", default="docker")
    serve_parser = sub.add_parser("serve", help=argparse.SUPPRESS)
    serve_parser.add_argument("--data-dir", required=True)
    serve_parser.add_argument("--docker-path", default="docker")
    serve_parser.add_argument("--poll-seconds", type=float, default=30.0)
    serve_parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command in {"start", "stop"}:
        result = service_control(args.command)
    elif args.command == "status":
        result = service_status()
    elif args.command == "diagnose":
        result = diagnose(args.data_dir, docker_path=args.docker_path)
    else:
        ensure_data_dir(args.data_dir)
        serve(
            args.data_dir,
            docker_path=args.docker_path,
            poll_seconds=args.poll_seconds,
            once=args.once,
        )
        return
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
