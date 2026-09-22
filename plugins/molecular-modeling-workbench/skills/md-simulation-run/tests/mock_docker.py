"""Shared mock docker executable for md-simulation-run and web runner tests.

install_mock_docker() writes an executable fake docker whose recorded call log
and canned container state live under the fixture root, so tests never need a
Docker daemon or GPU. `run` prints and cidfile-writes a deterministic container
id; `ps -a --filter label=...` and `inspect` report the container records the
test has injected into the state file using docker-compatible JSON keys; the
later suites (stop/resume, extend, web runner) reuse this same fixture.
"""

import json
import os
import stat
import sys
from pathlib import Path

SCRIPT_BODY = """#!{python}
import json, os, sys, pathlib
_here = pathlib.Path(__file__).resolve().parent
state_path = _here / "fake_docker_state.json"
calls_path = _here / "fake_docker_calls.log"
state = json.loads(state_path.read_text()) if state_path.exists() else {{"containers": []}}
args = sys.argv[1:]
with calls_path.open("a") as log:
    log.write(json.dumps(args) + "\\n")
if not args:
    raise SystemExit(2)
verb = args[0]
if verb == "run":
    run = dict(state.get("run_result", {{"returncode": 0, "container_id": ""}}))
    if not run.get("container_id"):
        run["container_id"] = "f" * 64
    labels = {{}}
    if "--label" in args:
        pos = args.index("--label")
        while pos + 1 < len(args) and args[pos] == "--label" and "=" in args[pos + 1]:
            key, value = args[pos + 1].split("=", 1)
            labels[key] = value
            pos += 2
    if "--cidfile" in args:
        cidfile = pathlib.Path(args[args.index("--cidfile") + 1])
        cidfile.parent.mkdir(parents=True, exist_ok=True)
        cidfile.write_text(run["container_id"])
        state.setdefault("containers", []).append({{
            "ID": run["container_id"],
            "Names": args[args.index("--name") + 1],
            "Image": args[args.index("gmx") - 1],
            "Labels": labels,
            "State": state.get("run_container_state", "running"),
        }})
        state_path.write_text(json.dumps(state))
    print(run["container_id"])
    raise SystemExit(run["returncode"])
if verb == "ps":
    containers = state.get("containers", [])
    if "--filter" in args:
        for pair in args[args.index("--filter") + 1:]:
            if pair.startswith("--"):
                break
            if pair.startswith("label="):
                rest = pair[len("label="):]
                if "=" in rest:
                    key, value = rest.split("=", 1)
                    containers = [c for c in containers if (c.get("Labels") or {{}}).get(key) == value]
    for container in containers:
        print(json.dumps(container))
    raise SystemExit(0)
if verb == "inspect":
    wanted = args[-1]
    containers = [c for c in state.get("containers", []) if str(c["ID"]).startswith(wanted) or c["Names"] == wanted]
    if not containers:
        raise SystemExit(1)
    if "--format" in args:
        fmt = args[args.index("--format") + 1]
        if "RepoDigests" in fmt:
            print(json.dumps([containers[0]["Image"]]))
        else:
            print(containers[0]["Image"])
    raise SystemExit(0)
if verb == "version":
    raise SystemExit(state.get("version_returncode", 0))
raise SystemExit(2)
"""


def install_mock_docker(root: Path) -> tuple[Path, dict, dict]:
    """Create the fake docker executable plus its state/call files.

    Returns (docker_path, env, state) where env must be merged into the
    subprocess environment of any CLI invocation using this mock, and state is
    the mutable container/behavior handle tests use to inject containers.
    """
    docker = root / "fake-docker"
    docker.write_text(SCRIPT_BODY.format(python=sys.executable))
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    state_path = root / "fake_docker_state.json"
    calls_path = root / "fake_docker_calls.log"
    state_path.write_text(json.dumps({"containers": []}))
    calls_path.write_text("")
    env = {
        **os.environ,
        "FAKE_DOCKER_STATE": str(state_path),
        "FAKE_DOCKER_CALLS": str(calls_path),
    }
    return (
        docker,
        env,
        {"containers": [], "state_path": state_path, "calls_path": calls_path},
    )


def inject_containers(state: dict, containers: list[dict]) -> None:
    """Replace the mock docker container table (docker ps/inspect view)."""
    state["containers"] = containers
    serializable = {
        key: value
        for key, value in state.items()
        if key not in ("state_path", "calls_path")
    }
    Path(state["state_path"]).write_text(json.dumps(serializable))


def recorded_calls(calls_path: Path) -> list[list[str]]:
    return [
        json.loads(line) for line in Path(calls_path).read_text().splitlines() if line
    ]
