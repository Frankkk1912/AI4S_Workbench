"""Local security boundary (M2 T2.2): Host/Origin/CSRF and token checks.

The API is single-user and localhost-only, so it rejects any Host or Origin
that is not a loopback address (fail closed) and requires a non-simple custom
header on every write operation to defeat cross-site request forgery. The token
dependency is the primary authentication boundary and runs first so a request
without a token is a clean 401.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from fastapi import HTTPException, Request

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
CSRF_HEADER = "X-AI4S-Request"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _host_and_port(value: str) -> tuple[str, int | None]:
    """Split a Host/Origin netloc into (hostname, port-or-None)."""
    value = (value or "").strip()
    if value.startswith("["):
        close = value.find("]")
        if close == -1:
            return value, None
        host = value[1:close]
        rest = value[close + 1 :]
        port = rest[1:] if rest.startswith(":") and rest[1:].isdigit() else None
        return host, int(port) if port else None
    if value.count(":") == 1:
        host, _, port = value.partition(":")
        if port.isdigit():
            return host, int(port)
        return host, None
    return value, None


def validate_host(host_header: str | None) -> str:
    """Reject any Host header that is not a loopback name/address."""
    host, _ = _host_and_port(host_header or "")
    if host not in ALLOWED_HOSTS:
        raise HTTPException(
            status_code=403,
            detail=f"untrusted Host header: {host_header!r}",
        )
    return host


def validate_origin(origin_header: str | None, host_header: str | None) -> None:
    """Require a same-origin loopback Origin; absent Origin is allowed (non-browser)."""
    if not origin_header:
        return
    parsed = urlparse(origin_header)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=403, detail="untrusted Origin scheme/host")
    origin_host = parsed.hostname
    if origin_host not in ALLOWED_HOSTS:
        raise HTTPException(status_code=403, detail="untrusted Origin host")
    host, host_port = _host_and_port(host_header or "")
    if origin_host != host:
        raise HTTPException(status_code=403, detail="cross-origin request rejected")
    origin_port = parsed.port
    if origin_port is not None and host_port is not None and origin_port != host_port:
        raise HTTPException(status_code=403, detail="cross-origin port mismatch")


def validate_csrf(request: Request) -> None:
    """Write operations must carry a non-simple custom header (CSRF defense)."""
    if request.method in SAFE_METHODS:
        return
    if not request.headers.get(CSRF_HEADER):
        raise HTTPException(
            status_code=403,
            detail=(
                f"write operations require the non-simple custom header {CSRF_HEADER}"
            ),
        )


def extract_token(request: Request) -> str | None:
    """Return the bearer token from Authorization or the X-AI4S-Token header."""
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        return authorization[len("Bearer ") :]
    return request.headers.get("X-AI4S-Token")


def require_token(request: Request) -> None:
    """Primary auth dependency: every API requires the local token (401)."""
    expected = getattr(request.app.state, "token", None)
    provided = extract_token(request)
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="missing or invalid local token")


def require_local_request(request: Request) -> None:
    """Host/Origin/CSRF dependency: untrusted sources fail closed (403)."""
    validate_host(request.headers.get("host"))
    validate_origin(request.headers.get("origin"), request.headers.get("host"))
    validate_csrf(request)
