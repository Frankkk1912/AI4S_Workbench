"""Workspace path isolation and symlink escape checks (M2 T2.3).

Every backend-resolved path must end up inside a registered workspace root
after symlink resolution, mirroring the audited `work_relative` containment
semantics. Out-pointing symlinks and cross-project paths therefore fail closed
with a readable reason instead of being silently accessed.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class PathEscapeError(ValueError):
    """Raised when a path resolves outside every registered workspace root."""


class PathNotFoundError(ValueError):
    """Raised when a path is required to exist but does not."""


def _containing_root(resolved: Path, roots: Sequence[Path]) -> Path | None:
    for root in roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return root
    return None


def resolve_workspace_path(
    roots: Sequence[str | Path],
    value: str | Path,
    label: str = "path",
    must_exist: bool = False,
) -> Path:
    """Resolve `value` and require it to land inside a registered workspace root.

    Symlink resolution happens first (`Path.resolve` follows the whole chain),
    so a symlink pointing outside the roots is rejected together with a plain
    `..` escape. `must_exist` additionally enforces presence for file reads.
    """
    resolved_roots = [Path(root).resolve() for root in roots]
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = candidate.absolute()
    resolved = candidate.resolve()
    if _containing_root(resolved, resolved_roots) is None:
        raise PathEscapeError(
            f"{label} must resolve inside a registered workspace root; got {resolved}"
        )
    if must_exist and not resolved.exists():
        raise PathNotFoundError(f"{label} does not exist: {resolved}")
    return resolved
