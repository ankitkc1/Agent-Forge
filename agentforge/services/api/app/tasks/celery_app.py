from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery = Celery("agentforge", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=3600,
    task_routes={"app.tasks.pipeline.run_build": {"queue": "builds"}},
    task_default_queue="builds",
    broker_connection_retry_on_startup=True,
)
celery.autodiscover_tasks(["app.tasks"])
