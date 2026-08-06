"""Redis/RQ integration and database reconciliation for analysis runs."""

from typing import Callable

from redis import Redis
from redis.exceptions import RedisError
from rq import Callback, Queue, Retry
from rq.exceptions import NoSuchJobError
from rq.job import Job

from logging_config import get_logger
from run_store import list_active_runs, update_run
from settings import SETTINGS


logger = get_logger(__name__)
_redis_connection: Redis | None = None


class JobQueueUnavailableError(RuntimeError):
    pass


def get_redis_connection() -> Redis:
    global _redis_connection
    if _redis_connection is None:
        _redis_connection = Redis.from_url(
            SETTINGS.redis_url,
            decode_responses=False,
            socket_connect_timeout=SETTINGS.redis_connect_timeout_seconds,
            health_check_interval=SETTINGS.redis_health_check_interval_seconds,
        )
    return _redis_connection


def close_redis_connection() -> None:
    global _redis_connection
    if _redis_connection is not None:
        _redis_connection.connection_pool.disconnect()
        _redis_connection = None


def check_redis() -> None:
    get_redis_connection().ping()


def get_queue() -> Queue:
    return Queue(SETTINGS.rq_queue_name, connection=get_redis_connection())


def enqueue_run(run_id: str, run_type: str, function: Callable, *args) -> Job:
    timeout = (
        SETTINGS.preprocessing_job_timeout_seconds
        if run_type == "preprocessing"
        else SETTINGS.analysis_job_timeout_seconds
    )
    retry = None
    if SETTINGS.job_retry_max > 0:
        retry = Retry(max=SETTINGS.job_retry_max, interval=SETTINGS.job_retry_interval_seconds)
    try:
        job = get_queue().enqueue(
            function,
            *args,
            job_id=run_id,
            job_timeout=timeout,
            retry=retry,
            result_ttl=86400,
            failure_ttl=604800,
            on_failure=Callback("background_jobs.handle_job_failure", timeout=30),
            on_stopped=Callback("background_jobs.handle_job_stopped", timeout=30),
            description=f"{run_type} run {run_id}",
        )
        logger.info("job_enqueued", extra={"run_id": run_id, "run_type": run_type, "queue": SETTINGS.rq_queue_name})
        return job
    except RedisError as exc:
        raise JobQueueUnavailableError("Redis job queue is unavailable") from exc
    except Exception as exc:
        raise JobQueueUnavailableError("Unable to enqueue background job") from exc


def _status_value(job: Job) -> str:
    rq_status = job.get_status(refresh=True)
    return rq_status.value if hasattr(rq_status, "value") else str(rq_status)


def reconcile_active_jobs() -> int:
    """Resolve DB runs whose corresponding RQ job is already terminal or missing."""
    connection = get_redis_connection()
    reconciled = 0
    for run in list_active_runs():
        try:
            job = Job.fetch(run["run_id"], connection=connection)
            job_status = _status_value(job)
        except NoSuchJobError:
            job_status = "missing"
            job = None

        if job_status in {"queued", "started", "scheduled", "deferred", "ready_to_enqueue", "rate_limited"}:
            continue
        if job_status == "canceled":
            target_status = "cancelled"
            message = "The background job was cancelled"
        elif job_status == "finished":
            target_status = "failed"
            message = "The background job finished without recording a terminal run status"
        else:
            target_status = "failed"
            message = "The background job is missing, failed, stopped, or was interrupted"
            if job is not None and job.exc_info:
                message = job.exc_info.strip().splitlines()[-1][:2000]
        update_run(
            run["run_id"],
            status=target_status,
            current_activity="Background job cancelled" if target_status == "cancelled" else "Background job failed",
            error_message=message,
            log_message=f"Run reconciled from RQ status: {job_status}",
        )
        reconciled += 1
        logger.warning("job_reconciled", extra={"run_id": run["run_id"], "rq_status": job_status})
    return reconciled
