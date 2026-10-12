from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse

from app import __version__
from app.compiler.domains import ALL_PACKS
from app.core.config import get_settings
from app.core.security import CurrentPrincipal
from app.packaging.signing import SigningKeyError, load_signer
from app.schemas.agent_spec import STEP_KINDS

router = APIRouter(prefix="/system", tags=["system"])


@router.get("")
def system_info(principal: CurrentPrincipal) -> dict[str, Any]:
    """Instance configuration for the workbench (authenticated: it describes the deployment)."""
    settings = get_settings()
    try:
        signer = load_signer(
            settings.signing_key.get_secret_value() if settings.signing_key else None, settings.signing_key_id
        )
    except SigningKeyError:
        signer = None
    return {
        "version": __version__,
        "environment": settings.env,
        "auth_mode": settings.auth_mode,
        "compiler": {
            "engines": ["heuristic", *(["llm"] if settings.llm_provider != "none" else [])],
            "llm_provider": settings.llm_provider,
            "domains": [pack.key for pack in ALL_PACKS],
        },
        "sandbox": {"backend": settings.sandbox_backend, "timeout_seconds": settings.sandbox_timeout_seconds},
        "dispatch": settings.build_dispatch,
        "repair": {"max_attempts": settings.repair_max_attempts, "llm": settings.repair_use_llm},
        "signing": {"enabled": signer is not None, "key_id": signer.key_id if signer else None},
        "limits": {
            "max_requirement_chars": settings.max_requirement_chars,
            "max_active_builds": settings.max_active_builds,
            "build_retention_days": settings.build_retention_days,
        },
        "step_kinds": list(STEP_KINDS),
    }


@router.get("/signing-key", response_class=PlainTextResponse)
def signing_key() -> str:
    """Public key for verifying artifact signatures. Deliberately unauthenticated."""
    settings = get_settings()
    signer = load_signer(
        settings.signing_key.get_secret_value() if settings.signing_key else None, settings.signing_key_id
    )
    if signer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact signing is not configured")
    return signer.public_pem
