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
    try:
        db.execute(text("SELECT 1"))
        client = Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        client.ping()
        client.close()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="dependencies unavailable"
        ) from exc
    return {"status": "ready", "database": "ok", "queue": "ok"}
