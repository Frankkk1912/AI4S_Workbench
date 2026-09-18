"""Single-instance runner lock (M1 T1.4).

A second runner process must refuse to start while another one holds the
lockfile, so concurrent docker submissions cannot race on the same SQLite
state and the same work directories.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path


class LockHeldError(RuntimeError):
    """Raised when another runner instance already holds the lock."""


class RunnerLock:
    """Advisory-but-exclusive process lock via flock plus a pid record."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> RunnerLock:
        # The handle must stay open for the lock's lifetime (flock is tied to the
        # open file description), so a context manager is deliberately not used here.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.seek(0)
            held = handle.read().strip()
            handle.close()
            suffix = f" (holder pid {held})" if held else ""
            raise LockHeldError(
                f"Another runner instance holds {self.path}{suffix}. Refusing to start a second runner."
            ) from None
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle
        return self

    def release(self) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None

    def __enter__(self) -> RunnerLock:
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
