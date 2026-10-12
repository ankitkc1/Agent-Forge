from app.services.pipeline import execute_build
from app.tasks.celery_app import celery


@celery.task(name="app.tasks.pipeline.run_build", bind=True, max_retries=2)
def run_build(self, build_id: str) -> None:
    try:
        execute_build(build_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(30, 2**self.request.retries)) from exc
