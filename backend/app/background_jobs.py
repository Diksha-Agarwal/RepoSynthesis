"""RQ jobs for the existing preprocessing and GraphFlow analysis pipelines."""

import asyncio
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "repo-processing"))
sys.path.insert(0, str(APP_DIR.parent))

from logging_config import configure_logging, get_logger
from run_store import finalize_analysis_run, update_run
from settings import SETTINGS


configure_logging()
logger = get_logger(__name__)
BASE_DATA_DIR = SETTINGS.data_dir / "projects"


def _failure_message(exc: BaseException) -> str:
    if "Failed to clone repository" in str(exc):
        return "Failed to clone GitHub repository. Check the URL and ensure the repository is public."
    if "Invalid input type" in str(exc):
        return "Invalid file path or GitHub URL."
    return f"{type(exc).__name__}: {exc}"


def run_preprocessing_job(project_id: str, run_id: str, file_path: str) -> None:
    from pipeline import process_repository_for_graphflow

    progress_by_activity = {
        "Loading repository files...": 10,
        "Extracting code sections...": 30,
        "Analyzing repository structure...": 50,
        "Generating embeddings...": 70,
        "Saving project data...": 90,
    }
    logger.info("preprocessing_started", extra={"project_id": project_id, "run_id": run_id})
    update_run(run_id, status="running", progress=1, current_activity="Starting preprocessing...", log_message="Preprocessing started", clear_error=True)

    def update_step(message: str) -> None:
        progress = progress_by_activity.get(message, 5)
        update_run(run_id, progress=progress, current_activity=message, log_message=f"[{progress}%] {message}")
        logger.info("preprocessing_progress", extra={"project_id": project_id, "run_id": run_id, "progress": progress, "activity": message})

    try:
        update_step("Cloning GitHub repository..." if file_path.startswith("http") else "Extracting ZIP file...")
        process_repository_for_graphflow(file_path, project_id=project_id, status_callback=update_step)
        update_run(run_id, status="completed", progress=100, current_activity="Preprocessing complete", log_message="[100%] Preprocessing complete", clear_error=True)
        logger.info("preprocessing_completed", extra={"project_id": project_id, "run_id": run_id})
    except Exception as exc:
        logger.exception("preprocessing_attempt_failed", extra={"project_id": project_id, "run_id": run_id, "error": _failure_message(exc)})
        raise


async def _run_analysis(project_id: str, run_id: str, personas: str, depth: str, verbosity: str) -> None:
    def update(activity: str, progress: int, insight: str | None = None) -> None:
        update_run(
            run_id,
            progress=progress,
            current_activity=activity,
            log_message=f"[{progress}%] {activity}",
            insight_activity=activity if insight else None,
            insight=insight,
        )
        logger.info("analysis_progress", extra={"project_id": project_id, "run_id": run_id, "progress": progress, "activity": activity})

    update_run(run_id, status="running", progress=1, current_activity="Starting analysis...", log_message="Analysis started", clear_error=True)
    from app.config.analysis_config import AnalysisConfig, FeaturesEnabled
    from app.teams.graphflow_team import GraphFlowCoordinator

    personas_list = [persona.strip() for persona in personas.split(",")]
    config = AnalysisConfig(
        depth=depth,
        verbosity=verbosity,
        features_enabled=FeaturesEnabled(structure=True, api_db=True, best_practices=True, pm_insights="PM" in personas_list),
        llm_model=SETTINGS.openai_model,
        temperature=SETTINGS.openai_temperature,
        max_tokens=SETTINGS.openai_max_tokens,
        request_timeout=SETTINGS.openai_request_timeout_seconds,
    )
    update("Creating analysis coordinator...", 5)
    coordinator = GraphFlowCoordinator(project_id, config, project_dir=BASE_DATA_DIR / project_id, analysis_run_id=run_id)
    coordinator.selected_personas = personas_list
    coordinator.status_callback = update
    update("Running agent pipeline...", 10)
    result = await coordinator.run_analysis()
    error_message = "; ".join(result.errors) if result.errors else None
    finalize_analysis_run(int(project_id), run_id, result.model_dump(mode="json"), success=result.success, error_message=error_message)


def run_analysis_job(project_id: str, run_id: str, personas: str, depth: str, verbosity: str) -> None:
    logger.info("analysis_started", extra={"project_id": project_id, "run_id": run_id})
    try:
        asyncio.run(_run_analysis(project_id, run_id, personas, depth, verbosity))
        logger.info("analysis_completed", extra={"project_id": project_id, "run_id": run_id})
    except Exception as exc:
        logger.exception("analysis_attempt_failed", extra={"project_id": project_id, "run_id": run_id, "error": _failure_message(exc)})
        raise


def handle_job_failure(job, connection, exception_type, exception_value, traceback, *args, **kwargs) -> None:
    retries_left = int(getattr(job, "retries_left", 0) or 0)
    message = _failure_message(exception_value)
    if retries_left > 0:
        update_run(job.id, status="queued", current_activity=f"Retry scheduled ({retries_left} remaining)", error_message=message, log_message=f"Job attempt failed; {retries_left} retries remaining: {message}")
        logger.warning("job_retry_scheduled", extra={"run_id": job.id, "retries_left": retries_left, "error": message})
        return
    update_run(job.id, status="failed", current_activity="Background job failed", error_message=message, log_message=f"Background job failed: {message}")
    logger.error("job_failed", extra={"run_id": job.id, "error": message})


def handle_job_stopped(job, connection, *args, **kwargs) -> None:
    update_run(job.id, status="cancelled", current_activity="Background job stopped", error_message="The background job was stopped", log_message="Background job stopped")
    logger.warning("job_stopped", extra={"run_id": job.id})


def handle_work_horse_killed(job, retpid, ret_val, rusage) -> None:
    job.retries_left = 0
    update_run(
        job.id,
        status="failed",
        current_activity="Background job interrupted",
        error_message="The worker process terminated unexpectedly or exceeded its resource/time limit",
        log_message=f"Worker process terminated with return value {ret_val}",
    )
    logger.error("job_process_terminated", extra={"run_id": job.id, "return_value": ret_val})
