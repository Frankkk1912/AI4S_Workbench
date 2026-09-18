"""Backend configuration and local token file management (M2 T2.1).

The backend is single-user and bound to 127.0.0.1 only. On startup a random
local token is generated (or the existing token file is reused), stored in a
0600-permission file, and printed exactly once so the operator can hand it to
the local frontend. The full same-origin static-frontend handoff is T6.8; this
module only establishes the token boundary every API requires.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
TOKEN_BYTES = 32


class ConfigError(ValueError):
    """Raised when a configuration invariant cannot be satisfied."""


def generate_token() -> str:
    """Return a fresh URL-safe random token (32 bytes of entropy)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def create_token_file(path: Path) -> str:
    """Create a token file with 0600 permissions and return its token.

    The file is opened with mode 0o600 at creation time so the secret is never
    briefly world-readable; a pre-existing file is overwritten atomically via a
    temp file + rename (the temp file is also 0600).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = generate_token()
    fd, tmp = -1, None
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return token


def load_token(path: Path) -> str:
    """Read an existing token file (no generation)."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Token file does not exist: {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ConfigError(f"Token file is empty: {path}")
    return token


def load_or_create_token(path: Path) -> str:
    """Reuse an existing token file or create a fresh 0600 one."""
    path = Path(path)
    if path.is_file():
        return load_token(path)
    return create_token_file(path)
