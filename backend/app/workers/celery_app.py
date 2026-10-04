import contextlib

from celery import Celery
from celery.signals import worker_init
from kombu import Queue

from app.config import settings

celery_app = Celery(
    "marketradar", broker=settings.broker_url, backend=settings.result_backend, include=["app.workers.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_redirect_stdouts_level="INFO",
    result_expires=24 * 3600,
    task_default_queue="default",
    task_queues=[Queue("default"), Queue("pipeline"), Queue("briefs")],
    task_routes={
        "app.workers.tasks.check_source": {"queue": "pipeline"},
        "app.workers.tasks.generate_brief": {"queue": "briefs"},
    },
    broker_transport_options={"visibility_timeout": 3600},
    beat_schedule={
        # The platform is autonomous: beat continuously dispatches due sources and briefs.
        "dispatch-due-sources": {"task": "app.workers.tasks.dispatch_due_sources", "schedule": 60.0},
        "dispatch-daily-briefs": {"task": "app.workers.tasks.dispatch_daily_briefs", "schedule": 600.0},
        "reindex-missing-embeddings": {"task": "app.workers.tasks.reindex_embeddings", "schedule": 1800.0},
    },
)


@worker_init.connect
def _init_worker(**_kwargs) -> None:
    from prometheus_client import start_http_server

    from app.core.logging import configure_logging
    from app.core.telemetry import configure_tracing
    from app.db.session import use_worker_engine

    configure_logging()
    configure_tracing("marketradar-worker")
    use_worker_engine()
    with contextlib.suppress(OSError):  # port already bound (e.g. multiple workers on one host)
        start_http_server(settings.worker_metrics_port)
