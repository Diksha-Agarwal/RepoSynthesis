"""RQ worker entrypoint with shared configuration and failure handling."""

import os

from rq import Queue, SpawnWorker, Worker

from background_jobs import handle_work_horse_killed
from db import close_database
from job_queue import close_redis_connection, get_redis_connection
from logging_config import configure_logging, get_logger
from settings import SETTINGS


def main() -> None:
    configure_logging()
    logger = get_logger(__name__)
    if SETTINGS.validation_errors:
        logger.critical("configuration_invalid", extra={"errors": list(SETTINGS.validation_errors)})
        raise RuntimeError("Invalid backend configuration: " + "; ".join(SETTINGS.validation_errors))
    connection = get_redis_connection()
    queue = Queue(SETTINGS.rq_queue_name, connection=connection)
    worker_class = SpawnWorker if os.name == "nt" else Worker
    worker = worker_class([queue], connection=connection, work_horse_killed_handler=handle_work_horse_killed)
    logger.info("worker_started", extra={"queue": SETTINGS.rq_queue_name, "worker_class": worker_class.__name__})
    try:
        worker.work(with_scheduler=SETTINGS.job_retry_interval_seconds > 0)
    finally:
        close_redis_connection()
        close_database()
        logger.info("worker_stopped", extra={"queue": SETTINGS.rq_queue_name})


if __name__ == "__main__":
    main()
