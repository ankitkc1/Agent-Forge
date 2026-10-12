from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.builds import purge_expired
from app.tasks.celery_app import celery


@celery.task(name="app.tasks.maintenance.purge_expired_builds")
def purge_expired_builds() -> int:
    """Delete finished builds (and their artifacts) older than the retention period."""
    with SessionLocal() as session:
        return purge_expired(session, get_settings())
