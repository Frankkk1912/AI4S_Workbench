# pyright: reportMissingImports=false
"""Same-origin browser token handoff for the local workbench (T6.8).

The operator enters the startup token once. The backend compares it in constant
time and sets an HttpOnly, SameSite=Strict cookie. Browser APIs may continue to
send the bearer header, while native EventSource authenticates through the
cookie because it cannot attach an Authorization header.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .security import AUTH_COOKIE_NAME, require_local_request, require_token


class HandoffRequest(BaseModel):
    access_token: str = Field(min_length=1)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/guide", dependencies=[Depends(require_local_request)])
def guide() -> dict[str, str]:
    return {
        "mode": "local-single-user",
        "instruction": (
            "Enter the token printed by the local backend once. It is stored in "
            "a 0600 local file and exchanged for an HttpOnly same-origin cookie."
        ),
    }


@router.post("/handoff", dependencies=[Depends(require_local_request)])
def handoff(payload: HandoffRequest, request: Request, response: Response) -> dict:
    expected = getattr(request.app.state, "token", None)
    if not expected or not secrets.compare_digest(payload.access_token, expected):
        raise HTTPException(status_code=401, detail="invalid local access token")
    response.set_cookie(
        AUTH_COOKIE_NAME,
        payload.access_token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return {"authenticated": True, "transport": "httponly-cookie"}


@router.get(
    "/status",
    dependencies=[Depends(require_token), Depends(require_local_request)],
)
def status() -> dict[str, bool]:
    return {"authenticated": True}


def announce_once(access_token: str, output: Callable[[str], None] = print) -> None:
    """Print the startup handoff once without writing it to application logs."""
    output(f"Local access token (enter once): {access_token}")
