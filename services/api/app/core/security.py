"""Authentication for the AgentForge API.

Modes (``AGENTFORGE_AUTH_MODE``):

* ``none``           – development only; refused in production by settings validation.
* ``api_key``        – ``X-API-Key`` or ``Authorization: Bearer`` matched by SHA-256 digest in
  constant time against ``AGENTFORGE_API_KEYS`` (raw keys or ``sha256:<hex>`` entries).
* ``trusted_header`` – identity asserted by an authenticating reverse proxy (oauth2-proxy,
  Cloudflare Access, ...) in ``AGENTFORGE_TRUSTED_USER_HEADER``. Only safe when the proxy strips
  that header from client requests.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class Principal:
    id: str
    method: str


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.headers.get("X-API-Key")


def authenticate(request: Request, settings: Settings) -> Principal:
    if settings.auth_mode == "none":
        return Principal(id="anonymous", method="none")
    if settings.auth_mode == "trusted_header":
        identity = request.headers.get(settings.trusted_user_header, "").strip()
        if not identity or len(identity) > 200:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        return Principal(id=identity, method="trusted_header")
    key = _bearer(request)
    if not key:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "API key required", headers={"WWW-Authenticate": "Bearer"}
        )
    candidate = hashlib.sha256(key.encode()).hexdigest()
    matched = False
    for digest in settings.api_key_digests:
        matched |= hmac.compare_digest(candidate, digest)
    if not matched:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid API key", headers={"WWW-Authenticate": "Bearer"}
        )
    return Principal(id=f"key:{candidate[:10]}", method="api_key")


def require_principal(request: Request) -> Principal:
    principal = authenticate(request, get_settings())
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]
