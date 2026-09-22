"""SSE progress/log streaming router (M2 T2.5).

Progress is sampled through the audited `parse_log` primitive via the M1
`monitor.collect_progress` wrapper (no binary artifacts are ever read), and the
GROMACS text log is streamed incrementally by byte offset so a reconnect with
`Last-Event-ID` resumes without duplicating or dropping lines. The response is
a non-blocking `StreamingResponse` whose generator returns after the current
snapshot; a live poll loop can be layered on top in M3/M4.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from web.runner import monitor

from ..paths import PathEscapeError, PathNotFoundError, resolve_workspace_path
from ..security import require_local_request, require_token

router = APIRouter(
    prefix="/stream",
    tags=["stream"],
    dependencies=[Depends(require_token), Depends(require_local_request)],
)


def sse_event(event: str, data: str, event_id: str | None = None) -> str:
    """Serialize one Server-Sent Events event block."""
    lines = [f"event: {event}"]
    for chunk in data.splitlines() or [""]:
        lines.append(f"data: {chunk}")
    if event_id is not None:
        lines.append(f"id: {event_id}")
    return "\n".join(lines) + "\n\n"


def _resolve_log(roots: Sequence[str | Path], value: str) -> Path:
    try:
        return resolve_workspace_path(roots, value, label="log", must_exist=True)
    except (PathEscapeError, PathNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/log")
def stream_log(
    request: Request,
    log: str = Query(...),
    total_steps: int = Query(..., gt=0),
    stale_minutes: float = Query(180.0),
) -> StreamingResponse:
    roots = request.app.state.workspace_roots
    log_path = _resolve_log(roots, log)
    raw_offset = request.headers.get("last-event-id")
    try:
        offset = int(raw_offset) if raw_offset else 0
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="invalid Last-Event-ID offset"
        ) from exc
    if offset < 0:
        raise HTTPException(status_code=400, detail="invalid Last-Event-ID offset")

    def events():
        progress = monitor.collect_progress(log_path, total_steps, stale_minutes)
        yield sse_event(
            "progress", json.dumps(progress, sort_keys=True), event_id="progress"
        )
        text, next_offset = monitor.read_log_tail(log_path, offset)
        yield sse_event("log", text, event_id=str(next_offset))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
