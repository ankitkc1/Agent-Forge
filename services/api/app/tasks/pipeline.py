from sqlalchemy.exc import OperationalError

from app.services.pipeline import execute_build
from app.tasks.celery_app import celery


@celery.task(
    name="app.tasks.pipeline.run_build",
    bind=True,
    acks_late=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def run_build(self, build_id: str) -> str:  # type: ignore[no-untyped-def]
    """Run the pipeline. Gate failures are terminal build states, not task errors, so only
    infrastructure errors (database connectivity) are retried."""
    return execute_build(build_id)
