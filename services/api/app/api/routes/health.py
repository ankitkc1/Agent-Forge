from fastapi import APIRouter, HTTPException, status
from redis import Redis
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
def ready(db: DbSession) -> dict[str, str]:
    checks = {"database": "ok", "queue": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    settings = get_settings()
    if settings.build_dispatch == "inline":
        checks["queue"] = "not used (inline dispatch)"
        return {"status": "ready", **checks}
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        client.close()
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "queue unavailable") from exc
    return {"status": "ready", **checks}
