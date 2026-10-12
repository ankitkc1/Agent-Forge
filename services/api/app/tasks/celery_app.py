from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
celery = Celery(
    "agentforge",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.pipeline", "app.tasks.maintenance"],
)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.sandbox_timeout_seconds * 4 + 300,
    task_soft_time_limit=settings.sandbox_timeout_seconds * 4 + 240,
    result_expires=3600,
    task_routes={
        "app.tasks.pipeline.run_build": {"queue": "builds"},
        "app.tasks.maintenance.purge_expired_builds": {"queue": "maintenance"},
    },
    task_default_queue="builds",
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "purge-expired-builds": {
            "task": "app.tasks.maintenance.purge_expired_builds",
            "schedule": crontab(hour=3, minute=17),
        }
    },
)
