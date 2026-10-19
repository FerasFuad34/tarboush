"""
تهيئة Celery — طابور المهام الحقيقي
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "tarboush",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Aden",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=2400,
    task_soft_time_limit=2280,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=25,
    broker_connection_retry_on_startup=True,
)
