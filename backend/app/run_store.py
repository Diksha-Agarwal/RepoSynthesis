from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from db import AnalysisRun, Project, SessionLocal, utc_now


ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
RUN_TYPES = ("preprocessing", "analysis")


class ActiveRunExistsError(RuntimeError):
    pass


class ProjectNotFoundError(RuntimeError):
    pass


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def run_to_dict(run: AnalysisRun) -> Dict[str, Any]:
    return {
        "run_id": run.id,
        "project_id": run.project_id,
        "run_type": run.run_type,
        "status": run.status,
        "progress": run.progress,
        "current_activity": run.current_activity,
        "error_message": run.error_message,
        "configuration": run.configuration or {},
        "logs": run.logs or [],
        "agent_insights": run.agent_insights or {},
        "created_at": _as_utc(run.created_at),
        "started_at": _as_utc(run.started_at),
        "completed_at": _as_utc(run.completed_at),
        "updated_at": _as_utc(run.updated_at),
    }


def create_run(project_id: int, run_type: str, configuration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if run_type not in RUN_TYPES:
        raise ValueError("Unsupported run type")

    with SessionLocal() as db:
        if db.get(Project, project_id) is None:
            raise ProjectNotFoundError("Project not found")
        active_run = (
            db.query(AnalysisRun)
            .filter(
                AnalysisRun.project_id == project_id,
                AnalysisRun.run_type == run_type,
                AnalysisRun.status.in_(ACTIVE_STATUSES),
            )
            .first()
        )
        if active_run:
            raise ActiveRunExistsError(active_run.id)

        run = AnalysisRun(
            id=str(uuid4()),
            project_id=project_id,
            run_type=run_type,
            status="queued",
            progress=0,
            current_activity="Queued",
            configuration=configuration or {},
            logs=["Run queued"],
            agent_insights={},
        )
        db.add(run)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ActiveRunExistsError("active") from exc
        db.refresh(run)
        return run_to_dict(run)


def update_run(
    run_id: str,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    current_activity: Optional[str] = None,
    error_message: Optional[str] = None,
    log_message: Optional[str] = None,
    insight_activity: Optional[str] = None,
    insight: Any = None,
) -> Optional[Dict[str, Any]]:
    with SessionLocal() as db:
        run = db.get(AnalysisRun, run_id)
        if run is None:
            return None
        if run.status in TERMINAL_STATUSES:
            return run_to_dict(run)

        now = utc_now()
        if status is not None:
            run.status = status
            if status == "running" and run.started_at is None:
                run.started_at = now
            if status in TERMINAL_STATUSES:
                run.completed_at = now
        if progress is not None:
            run.progress = max(0, min(100, int(progress)))
        if current_activity is not None:
            run.current_activity = current_activity
        if error_message is not None:
            run.error_message = error_message
        if log_message:
            run.logs = list(run.logs or []) + [log_message]
        if insight_activity and insight is not None:
            insights = dict(run.agent_insights or {})
            insights[insight_activity] = insight
            run.agent_insights = insights
        run.updated_at = now
        db.commit()
        db.refresh(run)
        return run_to_dict(run)


def get_run(project_id: int, run_id: str) -> Optional[Dict[str, Any]]:
    with SessionLocal() as db:
        run = (
            db.query(AnalysisRun)
            .filter(AnalysisRun.id == run_id, AnalysisRun.project_id == project_id)
            .first()
        )
        return run_to_dict(run) if run else None


def list_project_runs(project_id: int) -> List[Dict[str, Any]]:
    with SessionLocal() as db:
        runs = (
            db.query(AnalysisRun)
            .filter(AnalysisRun.project_id == project_id)
            .order_by(AnalysisRun.created_at.desc())
            .all()
        )
        return [run_to_dict(run) for run in runs]


def get_latest_run(project_id: int, run_type: str) -> Optional[Dict[str, Any]]:
    with SessionLocal() as db:
        run = (
            db.query(AnalysisRun)
            .filter(AnalysisRun.project_id == project_id, AnalysisRun.run_type == run_type)
            .order_by(AnalysisRun.created_at.desc())
            .first()
        )
        return run_to_dict(run) if run else None


def cancel_orphaned_active_runs() -> int:
    """Cancel work that cannot survive an application-process restart."""
    with SessionLocal() as db:
        active_runs = db.query(AnalysisRun).filter(AnalysisRun.status.in_(ACTIVE_STATUSES)).all()
        if not active_runs:
            return 0
        now = utc_now()
        for run in active_runs:
            run.status = "cancelled"
            run.current_activity = "Cancelled after backend restart"
            run.error_message = "The backend restarted before this in-process run finished"
            run.completed_at = now
            run.updated_at = now
            run.logs = list(run.logs or []) + ["Run cancelled during backend startup reconciliation"]
        db.commit()
        return len(active_runs)
