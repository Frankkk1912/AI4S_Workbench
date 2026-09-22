"""Running-stage online monitoring collection (M1 T1.6).

This module samples only the safe, complete, read-only GROMACS text log by
reusing the audited `parse_log` primitive through module import (D6). It never
samples in-progress binary artifacts (`.edr`/`.xtc`) — derived curves are a
separate, frozen analysis concern (R7), and a half-written binary must not be
misreported. Every sample is explicitly labelled `source: "monitoring"` so it
cannot be mistaken for a frozen analysis result.
"""

from __future__ import annotations

from pathlib import Path

from . import mdcli


class MonitorError(ValueError):
    """Raised when a monitoring sample cannot be produced safely."""


def collect_progress(
    log: Path,
    total_steps: int,
    stale_minutes: float = 180.0,
    collected_at: str | None = None,
) -> dict:
    """Sample a GROMACS text log via the audited `parse_log`.

    The returned document carries the parser's own collection timestamp and
    mtime-derived stale flag plus a `source` label marking it as live
    monitoring data (never a frozen analysis result). ETA is preserved as the
    parser reports it: an unavailable ETA is a non-numeric "unavailable"
    string, never a fake 0.
    """
    module = mdcli.load_md_run_cli()
    data = module.parse_log(log, total_steps, stale_minutes)
    data["source"] = "monitoring"
    if collected_at is not None:
        data["checked_at"] = collected_at
    return data


def read_log_tail(log: Path, offset: int = 0) -> tuple[str, int]:
    """Return the complete log text from `offset` for SSE-style streaming.

    The log is opened read-only and read as text with replacement on decode
    errors; the caller tracks byte offsets across reconnects. No binary
    trajectory/energy file is ever opened here.
    """
    path = Path(log)
    if not path.is_file():
        raise MonitorError(f"GROMACS log does not exist: {path}")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        text = handle.read()
    return text, offset + len(text.encode("utf-8"))
