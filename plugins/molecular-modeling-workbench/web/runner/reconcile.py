"""Crash-window reconciliation and restart reconnection (M1 T1.3).

Reconcile is fail closed and identity-checked, never name-only:

1. Boot identity changed (host restart) -> every active or undecidable run
   becomes `interrupted`. Containers are never touched, nothing is
   relaunched; resume requires explicit user approval (R6).
2. No container matches the attempt identity:
   - intent-only attempt (crash between intent and `docker run`) -> the run
     stays `queued`; a later retry allocates a NEW attempt.
   - container was recorded but is gone -> facts are undecidable while the
     service is alive -> `unknown` (never silently completed).
3. Exactly one container whose image digest, work_dir hash, command hash,
   container name, and every ownership label match -> adopt it (reconnect
   without creating a new container). A running container -> `running`; an
   exited container -> `attention` ("container exited; finalize pending") —
   completion is only ever concluded by finalize (T1.7), never here.
4. Multiple matches, or any identity mismatch -> `attention` (fail closed);
   the container is never stopped, removed, or relaunched.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess

from . import db

RUN_ID_LABEL = "ai4s.workbench.run_id"


class DockerPort:
    """Thin docker CLI adapter; tests substitute a fake docker executable."""

    def __init__(self, docker_path: str = "docker") -> None:
        self.docker_path = docker_path

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.docker_path, *args], text=True, capture_output=True, check=False
        )

    def is_reachable(self) -> bool:
        return self._run(["version"]).returncode == 0

    def find_by_label(self, key: str, value: str) -> list[dict]:
        """List all containers (any state) carrying a label, with digests."""
        result = self._run(
            ["ps", "-a", "--filter", f"label={key}={value}", "--format", "{{json .}}"]
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker ps failed ({result.returncode}): {result.stderr.strip()}"
            )
        records: list[dict] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise RuntimeError("docker ps returned malformed JSON") from exc
            container_id = row.get("ID")
            raw_labels = row.get("Labels")
            labels = (
                raw_labels
                if isinstance(raw_labels, dict)
                else self._container_labels(container_id)
            )
            records.append(
                {
                    "id": container_id,
                    "name": row.get("Names"),
                    "image_digest": self._repo_digest(container_id),
                    "labels": labels,
                    "state": row.get("State"),
                }
            )
        return records

    def _repo_digest(self, container_id: str | None) -> str | None:
        if not container_id:
            return None
        # Container inspect exposes the exact image reference used at launch.
        # Because launch requires an @sha256 reference, Config.Image is the
        # stable identity; RepoDigests belongs to image inspect, not containers.
        result = self._run(
            ["inspect", "--format", "{{.Config.Image}}", container_id]
        )
        if result.returncode != 0:
            return None
        image = result.stdout.strip()
        return image if "@sha256:" in image else None

    def _container_labels(self, container_id: str | None) -> dict[str, str]:
        if not container_id:
            return {}
        result = self._run(
            ["inspect", "--format", "{{json .Config.Labels}}", container_id]
        )
        if result.returncode != 0:
            return {}
        try:
            labels = json.loads(result.stdout.strip())
        except ValueError:
            return {}
        return labels if isinstance(labels, dict) else {}

    def container_returncode(self, container_id: str) -> int | None:
        """Return Docker's recorded exit code, or None when undecidable."""
        result = self._run(
            ["inspect", "--format", "{{.State.ExitCode}}", container_id]
        )
        if result.returncode != 0:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None


def _identity_matches(attempt: sqlite3.Row, container: dict) -> tuple[bool, str | None]:
    """Full ownership check: digest, work_dir hash, command hash, all labels."""
    try:
        labels = json.loads(attempt["ownership_labels"] or "{}")
    except ValueError:
        return False, "attempt ownership labels are malformed"
    if container.get("name") != attempt["container_name"]:
        return (
            False,
            f"container name {container.get('name')!r} does not match {attempt['container_name']!r}",
        )
    if container.get("image_digest") != attempt["image_digest"]:
        return False, "image digest does not match the attempt record"
    container_labels = container.get("labels")
    if not isinstance(container_labels, dict):
        return False, "container ownership labels are malformed"
    for key in ("ai4s.workbench.work_dir_hash", "ai4s.workbench.command_hash"):
        if container_labels.get(key) != labels.get(key):
            return False, f"ownership label {key} does not match the attempt record"
    for key, value in labels.items():
        if container.get("labels", {}).get(key) != value:
            return False, f"ownership label {key} does not match the attempt record"
    return True, None


def _set_status(
    conn: sqlite3.Connection, run_id: str, status: str, reason: str
) -> None:
    db.set_run_status(conn, run_id, status, detail=reason)


def reconcile(
    conn: sqlite3.Connection,
    docker: DockerPort,
    current_boot: str | None = None,
    actor: str = "runner",
) -> list[dict]:
    """Scan unaccounted runs and reconnect or fail closed. Returns a summary."""
    summary: list[dict] = []
    host_restarted = db.boot_changed(conn, current=current_boot)
    pending = conn.execute(
        "SELECT * FROM runs WHERE status IN ('queued','running','stopping','unknown')"
    ).fetchall()
    for run in pending:
        run_id = run["run_id"]
        attempts = conn.execute(
            "SELECT * FROM attempts WHERE run_id = ? AND stage = ? "
            "ORDER BY attempt_id DESC LIMIT 1",
            (run_id, run["stage"]),
        ).fetchall()
        attempt = attempts[0] if attempts else None

        # Rule 1: host restart is decided by boot identity alone for work that
        # may have started. A queued run with no attempt has no computation to
        # interrupt and remains eligible for its first approved dispatch.
        unstarted = run["status"] == "queued" and attempt is None
        classified = (
            run["status"]
            if unstarted
            else db.classify_after_restart(run["status"], host_restarted)
        )
        if classified != run["status"]:
            _set_status(
                conn,
                run_id,
                classified,
                "host restart detected (boot identity changed)"
                if host_restarted
                else "service-side reconciliation",
            )
            if host_restarted:
                db.audit(
                    conn,
                    actor,
                    "host_restart_detected",
                    subject=run_id,
                    detail=f"boot identity changed; {run['status']} -> interrupted",
                )
            summary.append(
                {
                    "run_id": run_id,
                    "action": "interrupted",
                    "reason": "host restart (boot identity changed)",
                }
            )
            continue

        if attempt is None:
            # No attempt yet: a queued run waiting for its first attempt.
            summary.append(
                {
                    "run_id": run_id,
                    "action": "unchanged",
                    "reason": "no attempt recorded yet",
                }
            )
            continue

        if attempt["kind"] == "analysis":
            # Native analysis subprocesses have no durable container identity
            # that a restarted runner can safely adopt. Once an attempt exists,
            # its outcome is undecidable after service restart, so fail closed
            # and require explicit user approval before a new attempt (T1.7).
            _set_status(
                conn,
                run_id,
                "interrupted",
                "runner restarted during native analysis; outcome requires review",
            )
            conn.execute(
                "UPDATE analysis_sessions SET status = 'interrupted' WHERE run_id = ?",
                (run_id,),
            )
            db.audit(
                conn,
                actor,
                "analysis_interrupted",
                subject=run_id,
                detail=f"attempt_id={attempt['attempt_id']}",
            )
            summary.append(
                {
                    "run_id": run_id,
                    "action": "interrupted",
                    "reason": "native analysis cannot be reattached after runner restart",
                }
            )
            continue

        containers = docker.find_by_label(RUN_ID_LABEL, run_id)
        matching = [c for c in containers if c.get("name") == attempt["container_name"]]

        if attempt["container_at"] is None:
            if not matching and not containers:
                # Rule 2a: crash between intent and docker run; retry will
                # allocate a NEW attempt, never assume this one ran.
                summary.append(
                    {
                        "run_id": run_id,
                        "action": "unchanged",
                        "reason": "intent-only attempt; no container was created",
                    }
                )
                continue
            if not matching and containers:
                _set_status(
                    conn,
                    run_id,
                    "attention",
                    f"unexpected container found for run {run_id} while the latest attempt never started",
                )
                summary.append(
                    {
                        "run_id": run_id,
                        "action": "attention",
                        "reason": "unexpected container under run identity",
                    }
                )
                continue
        else:
            if not matching:
                # Rule 2b: the recorded container is gone; facts undecidable.
                _set_status(
                    conn,
                    run_id,
                    "unknown",
                    f"recorded container {attempt['container_name']} is no longer visible to docker",
                )
                summary.append(
                    {
                        "run_id": run_id,
                        "action": "unknown",
                        "reason": "recorded container vanished",
                    }
                )
                continue

        if len(matching) > 1:
            _set_status(
                conn,
                run_id,
                "attention",
                f"multiple containers match attempt identity {attempt['container_name']}; refusing to adopt any",
            )
            summary.append(
                {
                    "run_id": run_id,
                    "action": "attention",
                    "reason": "multiple matching containers",
                }
            )
            continue
        container = matching[0]
        ok, mismatch = _identity_matches(attempt, container)
        if not ok:
            # Rule 4: identity mismatch -> fail closed.
            _set_status(
                conn,
                run_id,
                "attention",
                f"container {container.get('name')} identity mismatch: {mismatch}",
            )
            summary.append(
                {
                    "run_id": run_id,
                    "action": "attention",
                    "reason": f"identity mismatch: {mismatch}",
                }
            )
            continue

        # Rule 3: adopt the verified container; never create a new one here.
        if attempt["container_at"] is None:
            conn.execute(
                "UPDATE attempts SET status = 'launched', container_at = ? WHERE run_id = ? AND stage = ? AND attempt_id = ?",
                (db.now(), run_id, attempt["stage"], attempt["attempt_id"]),
            )
        conn.execute(
            "INSERT INTO containers(container_id, attempt_id, run_id, stage, name, image_digest, labels, state, first_seen_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(container_id) DO UPDATE SET state = excluded.state",
            (
                container["id"],
                attempt["attempt_id"],
                run_id,
                attempt["stage"],
                container["name"],
                container.get("image_digest"),
                json.dumps(container.get("labels", {}), sort_keys=True),
                container.get("state", "unknown"),
                db.now(),
            ),
        )
        db.audit(
            conn,
            actor,
            "container_adopted",
            subject=run_id,
            detail=f"container={container['id']} state={container.get('state')}",
        )
        if container.get("state") == "running":
            _set_status(
                conn, run_id, "running", "reconnected to a verified running container"
            )
            summary.append(
                {
                    "run_id": run_id,
                    "action": "adopted",
                    "reason": "verified running container reconnected",
                }
            )
        else:
            # Exited without finalize: needs finalize (T1.7); never completed here.
            _set_status(
                conn,
                run_id,
                "attention",
                f"container {container['id']} exited; finalize pending",
            )
            summary.append(
                {
                    "run_id": run_id,
                    "action": "attention",
                    "reason": "container exited; finalize pending",
                }
            )
    return summary
