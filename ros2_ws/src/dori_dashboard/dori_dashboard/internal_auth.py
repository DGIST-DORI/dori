"""Shared local IPC authentication; no compiled-in or development secret."""

import os
import secrets

from fastapi import HTTPException


def internal_token() -> str:
    token = os.environ.get("DORI_INTERNAL_TOKEN", "").strip()
    if len(token) < 32 or token == "default-internal-secret":
        raise RuntimeError("DORI_INTERNAL_TOKEN must be a random secret of at least 32 characters")
    return token


def require_internal_token(candidate: str | None) -> None:
    try:
        expected = internal_token()
    except RuntimeError:
        raise HTTPException(503, "Internal authentication is not configured") from None
    if not candidate or not secrets.compare_digest(candidate.encode(), expected.encode()):
        raise HTTPException(403, "Invalid internal token")
