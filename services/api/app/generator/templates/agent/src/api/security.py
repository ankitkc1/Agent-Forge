"""API-key authentication with separate approver keys (segregation of duties)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from src.config import Settings


@dataclass(frozen=True)
class Principal:
    key_id: str
    can_approve: bool


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _matches(candidate: str, keys: set[str]) -> bool:
    candidate_digest = hashlib.sha256(candidate.encode()).digest()
    return any(
        hmac.compare_digest(candidate_digest, hashlib.sha256(key.encode()).digest()) for key in keys
    )


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def require_caller(
    request: Request, x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None
) -> Principal:
    settings = get_settings_from_app(request)
    callers, approvers = settings.api_key_set(), settings.approver_key_set()
    if not callers and not approvers and settings.env != "production":
        return Principal(key_id="anonymous-dev", can_approve=True)
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-API-Key header")
    if _matches(x_api_key, approvers):
        return Principal(key_id=_fingerprint(x_api_key), can_approve=True)
    if _matches(x_api_key, callers):
        return Principal(key_id=_fingerprint(x_api_key), can_approve=False)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")


def require_approver(principal: Annotated[Principal, Depends(require_caller)]) -> Principal:
    if not principal.can_approve:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "approver key required for approval decisions")
    return principal
