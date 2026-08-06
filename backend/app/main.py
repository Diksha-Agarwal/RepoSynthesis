import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from langchain_core.messages import AIMessage, HumanMessage
from starlette.exceptions import HTTPException as StarletteHTTPException

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "repo-processing"))
sys.path.insert(0, str(ROOT.parent))

from api_schemas import (
    ActionResponse,
    AnalysisRequest,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    LatestRunsResponse,
    LatestRunStatusResponse,
    RunListResponse,
    RunResponse,
    RunStartResponse,
    ReadinessResponse,
)
from app.models.schemas import AnalysisResult, AnalysisResultListResponse
from background_jobs import run_analysis_job, run_preprocessing_job
from db import Project, check_database, close_database
from ingestion import IngestionError, resolve_uploaded_zip
from job_queue import (
    JobQueueUnavailableError,
    check_redis,
    close_redis_connection,
    enqueue_run,
    reconcile_active_jobs,
)
from logging_config import configure_logging, get_logger
from projects import get_project_or_404, router as projects_router
from run_store import (
    ActiveRunExistsError,
    ProjectNotFoundError,
    create_run,
    get_active_run,
    get_analysis_result,
    get_latest_completed_analysis_result,
    get_latest_run,
    get_run,
    list_completed_analysis_results,
    list_project_runs,
    update_run,
)
from settings import SETTINGS


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if SETTINGS.validation_errors:
        logger.error("configuration_invalid", extra={"errors": list(SETTINGS.validation_errors)})
    else:
        try:
            check_database()
            check_redis()
            reconciled = reconcile_active_jobs()
            logger.info("backend_started", extra={"reconciled_runs": reconciled})
        except Exception:
            logger.exception("startup_dependency_check_failed")
    try:
        yield
    finally:
        close_redis_connection()
        close_database()
        logger.info("backend_stopped")


app = FastAPI(
    title="RepoResearchAI Demo API",
    description="Single-user repository analysis API for the Next.js demo client.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(SETTINGS.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects_router)

BASE_DATA_DIR = SETTINGS.data_dir / "projects"
BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
project_chat_histories: dict[int, list] = {}
vector_store_cache: dict[int, tuple[int, Any]] = {}
llm_instance = None


def _error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = jsonable_encoder(details)
    return JSONResponse(status_code=status_code, content={"error": error})


def _finish_request(request: Request, response: Response, request_id: str, started_at: float) -> Response:
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "api_request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        },
    )
    return response


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    started_at = time.perf_counter()
    if SETTINGS.validation_errors and request.url.path not in {"/health", "/ready", "/docs", "/openapi.json"}:
        response = _error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "configuration_invalid",
            "Backend configuration is invalid",
            {"errors": list(SETTINGS.validation_errors)},
        )
        return _finish_request(request, response, request_id, started_at)
    if request.method == "POST" and request.url.path.rstrip("/") == "/projects/upload":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                request_size = int(content_length)
            except ValueError:
                response = _error_response(400, "invalid_content_length", "Content-Length must be a valid integer")
                return _finish_request(request, response, request_id, started_at)
            multipart_allowance = 1024 * 1024
            if request_size > SETTINGS.max_upload_zip_bytes + multipart_allowance:
                response = _error_response(413, "upload_too_large", "Upload request exceeds the configured size limit")
                return _finish_request(request, response, request_id, started_at)
    response = await call_next(request)
    return _finish_request(request, response, request_id, started_at)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
        return _error_response(exc.status_code, exc.detail["code"], exc.detail["message"], exc.detail.get("details"))
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    details = None if isinstance(exc.detail, str) else exc.detail
    return _error_response(exc.status_code, f"http_{exc.status_code}", message, details)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "validation_error",
        "Request validation failed",
        exc.errors(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception):
    logger.exception("unhandled_api_error", exc_info=exc)
    return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "An unexpected server error occurred")


@app.post("/projects/{project_id}/preprocess", response_model=RunStartResponse)
async def preprocess_project(project: Project = Depends(get_project_or_404)):
    file_path = project.zip_filename or project.github_url
    if not file_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project has no ZIP file or GitHub URL")
    if project.zip_filename:
        try:
            file_path = str(resolve_uploaded_zip(project.zip_filename))
        except IngestionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc

    configuration = {"source_type": "zip" if project.zip_filename else "github"}
    try:
        run = create_run(project.id, "preprocessing", configuration)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from exc
    except ActiveRunExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "active_project_run_exists",
                "message": "Another preprocessing or analysis job is already queued or running for this project",
                "details": {"active_run_id": exc.run_id, "run_type": exc.run_type},
            },
        ) from exc

    try:
        enqueue_run(
            run["run_id"],
            "preprocessing",
            run_preprocessing_job,
            project.id,
            run["run_id"],
            str(file_path),
        )
    except JobQueueUnavailableError as exc:
        update_run(
            run["run_id"],
            status="failed",
            current_activity="Unable to enqueue preprocessing",
            error_message=str(exc),
            log_message=f"Unable to enqueue preprocessing: {exc}",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "job_queue_unavailable", "message": str(exc)},
        ) from exc
    return RunStartResponse(**run)


@app.get("/projects/{project_id}/preprocess/status", response_model=LatestRunStatusResponse)
async def get_preprocess_status(project: Project = Depends(get_project_or_404)):
    run = get_latest_run(project.id, "preprocessing")
    if not run:
        return LatestRunStatusResponse(
            project_id=project.id,
            run_type="preprocessing",
            status="not_started",
            current_activity="Not started",
            current_step="Not started",
        )
    return LatestRunStatusResponse(**run, current_step=run["current_activity"], error=run["error_message"])


@app.post("/projects/{project_id}/analyze/graphflow", response_model=RunStartResponse)
async def start_analysis(payload: AnalysisRequest, project: Project = Depends(get_project_or_404)):
    project_id = project.id
    active_run = get_active_run(project_id)
    if active_run:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "active_project_run_exists",
                "message": "Another preprocessing or analysis job is already queued or running for this project",
                "details": {
                    "active_run_id": active_run["run_id"],
                    "run_type": active_run["run_type"],
                },
            },
        )
    latest_preprocessing = get_latest_run(project_id, "preprocessing")
    if latest_preprocessing is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "preprocessing_required",
                "message": "A completed preprocessing run is required before analysis",
            },
        )
    if latest_preprocessing["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "latest_preprocessing_not_completed",
                "message": "The latest preprocessing run must be completed before analysis",
                "details": {
                    "preprocessing_run_id": latest_preprocessing["run_id"],
                    "status": latest_preprocessing["status"],
                },
            },
        )
    project_dir = BASE_DATA_DIR / str(project_id)
    if not (project_dir / "context.json").exists() or not (project_dir / "vector_store").exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "preprocessing_artifacts_missing",
                "message": "The latest completed preprocessing artifacts are unavailable; run preprocessing again",
            },
        )

    configuration = {
        "personas": payload.personas,
        "depth": payload.depth,
        "verbosity": payload.verbosity,
    }
    try:
        run = create_run(project.id, "analysis", configuration)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from exc
    except ActiveRunExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "active_project_run_exists",
                "message": "Another preprocessing or analysis job is already queued or running for this project",
                "details": {"active_run_id": exc.run_id, "run_type": exc.run_type},
            },
        ) from exc

    personas = ",".join(payload.personas)
    try:
        enqueue_run(
            run["run_id"],
            "analysis",
            run_analysis_job,
            project_id,
            run["run_id"],
            personas,
            payload.depth,
            payload.verbosity,
        )
    except JobQueueUnavailableError as exc:
        update_run(
            run["run_id"],
            status="failed",
            current_activity="Unable to enqueue analysis",
            error_message=str(exc),
            log_message=f"Unable to enqueue analysis: {exc}",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "job_queue_unavailable", "message": str(exc)},
        ) from exc
    return RunStartResponse(**run)


@app.get("/projects/{project_id}/status", response_model=LatestRunStatusResponse)
async def get_status(project: Project = Depends(get_project_or_404)):
    run = get_latest_run(project.id, "analysis")
    if not run:
        return LatestRunStatusResponse(project_id=project.id, run_type="analysis", status="not_started")
    return LatestRunStatusResponse(**run, error=run["error_message"])


@app.get("/projects/{project_id}/runs", response_model=RunListResponse)
async def get_project_runs(project: Project = Depends(get_project_or_404)):
    return RunListResponse(runs=[RunResponse(**run) for run in list_project_runs(project.id)])


@app.get("/projects/{project_id}/runs/latest", response_model=LatestRunsResponse)
async def get_latest_project_runs(project: Project = Depends(get_project_or_404)):
    preprocessing = get_latest_run(project.id, "preprocessing")
    analysis = get_latest_run(project.id, "analysis")
    return LatestRunsResponse(
        preprocessing=RunResponse(**preprocessing) if preprocessing else None,
        analysis=RunResponse(**analysis) if analysis else None,
    )


@app.get("/projects/{project_id}/runs/{run_id}", response_model=RunResponse)
async def get_project_run(run_id: UUID, project: Project = Depends(get_project_or_404)):
    run = get_run(project.id, str(run_id))
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "run_not_found", "message": "Run not found for this project"},
        )
    return RunResponse(**run)


@app.get("/projects/{project_id}/result", response_model=AnalysisResult)
async def get_result(project: Project = Depends(get_project_or_404)):
    result = get_latest_completed_analysis_result(project.id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "result_not_found", "message": "No completed analysis result exists for this project"},
        )
    return AnalysisResult(**result)


@app.get("/projects/{project_id}/results", response_model=AnalysisResultListResponse)
async def get_project_results(project: Project = Depends(get_project_or_404)):
    results = [AnalysisResult(**result) for result in list_completed_analysis_results(project.id)]
    return AnalysisResultListResponse(results=results)


@app.get("/projects/{project_id}/results/{analysis_run_id}", response_model=AnalysisResult)
async def get_result_by_run(analysis_run_id: UUID, project: Project = Depends(get_project_or_404)):
    run = get_run(project.id, str(analysis_run_id))
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "run_not_found", "message": "Analysis run not found for this project"},
        )
    if run["run_type"] != "analysis":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_run_type", "message": "The requested run is not an analysis run"},
        )
    if run["status"] == "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "analysis_run_failed",
                "message": run["error_message"] or "Analysis run failed",
            },
        )
    if run["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "analysis_run_incomplete",
                "message": f"Analysis run is {run['status']} and has no completed result",
            },
        )
    result = get_analysis_result(project.id, str(analysis_run_id))
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "result_not_found", "message": "Completed analysis result is unavailable"},
        )
    return AnalysisResult(**result)


@app.post("/projects/{project_id}/ask", response_model=ChatResponse)
async def ask(payload: ChatRequest, project: Project = Depends(get_project_or_404)):
    from embeddings import load_vector_store

    global llm_instance
    start = time.time()
    project_id = project.id
    project_dir = BASE_DATA_DIR / str(project_id)
    if not (project_dir / "vector_store").exists():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run preprocessing before asking questions")

    try:
        project_chat_histories.setdefault(project_id, [])
        vector_store_dir = project_dir / "vector_store"
        vector_store_version = max(
            (path.stat().st_mtime_ns for path in vector_store_dir.iterdir() if path.is_file()),
            default=0,
        )
        cached_store = vector_store_cache.get(project_id)
        if cached_store is None or cached_store[0] != vector_store_version:
            cached_store = (vector_store_version, load_vector_store(str(vector_store_dir)))
            vector_store_cache[project_id] = cached_store
        vectorstore = cached_store[1]
        if llm_instance is None:
            from langchain_openai import ChatOpenAI
            llm_instance = ChatOpenAI(
                model=SETTINGS.openai_chat_model,
                temperature=SETTINGS.openai_temperature,
                timeout=SETTINGS.openai_request_timeout_seconds,
            )

        docs = vectorstore.as_retriever(search_kwargs={"k": 3}).invoke(payload.question)
        context = "\n\n".join(
            f"[Source {index}: {document.metadata.get('source', 'unknown')}]\n{document.page_content[:1500]}"
            for index, document in enumerate(docs, 1)
        )
        analysis_context = ""
        using_partial = False
        analysis_data = get_latest_completed_analysis_result(project.id)
        sde_report = (analysis_data or {}).get("sde_report") or {}
        if sde_report:
            component_names = ", ".join(item.get("name", "") for item in sde_report.get("components", [])[:5])
            api_names = ", ".join(
                "{} {}".format(item.get("method", ""), item.get("endpoint", ""))
                for item in sde_report.get("apis", [])[:5]
            )
            analysis_context = (
                "Analysis Summary:\n"
                f"Architecture: {sde_report.get('architecture_summary', '')[:300]}\n\n"
                f"Components: {component_names}\n\n"
                f"APIs: {api_names}\n\n"
                f"Database: {str(sde_report.get('database_model', ''))[:200]}"
            )
        latest_analysis_run = get_latest_run(project.id, "analysis")
        if not analysis_context and latest_analysis_run and latest_analysis_run["status"] == "running":
            insights = latest_analysis_run.get("agent_insights", {})
            snippets = [f"{activity}: {str(insight)[:400]}" for activity, insight in list(insights.items())[:3] if insight]
            if snippets:
                using_partial = True
                analysis_context = "Partial Analysis (In Progress):\n" + "\n".join(snippets)

        full_context = f"{analysis_context}\n\nCode Context:\n{context}" if analysis_context else context
        messages = [("system", f"You are a code assistant. Answer concisely and directly using the provided context.\n\n{full_context}\n\nKeep answers brief and specific.")]
        for message in project_chat_histories[project_id][-6:]:
            if isinstance(message, HumanMessage):
                messages.append(("human", str(message.content)[:150]))
            elif isinstance(message, AIMessage):
                messages.append(("ai", str(message.content)[:150]))
        messages.append(("human", payload.question))
        answer = llm_instance.invoke(messages).content
        project_chat_histories[project_id].extend([HumanMessage(content=payload.question), AIMessage(content=answer)])
        project_chat_histories[project_id] = project_chat_histories[project_id][-12:]
        return ChatResponse(
            answer=answer,
            sources=[document.metadata.get("source", document.metadata.get("file", "unknown")) for document in docs],
            time=round(time.time() - start, 2),
            has_analysis=bool(analysis_context),
            using_partial=using_partial,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("chat_failed", extra={"project_id": project_id})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to answer the question") from exc


@app.post("/projects/{project_id}/chat/clear", response_model=ActionResponse)
async def clear_chat_memory(project: Project = Depends(get_project_or_404)):
    project_id = project.id
    had_history = bool(project_chat_histories.pop(project_id, None))
    return ActionResponse(status="cleared" if had_history else "no_history")


@app.post("/projects/{project_id}/cache/clear", response_model=ActionResponse)
async def clear_cache(project: Project = Depends(get_project_or_404)):
    project_id = project.id
    had_cache = vector_store_cache.pop(project_id, None) is not None
    return ActionResponse(status="cache_cleared" if had_cache else "no_cache")


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@app.get("/ready", response_model=ReadinessResponse, responses={503: {"model": ErrorResponse}})
async def ready():
    checks: dict[str, str] = {}
    errors: list[str] = list(SETTINGS.validation_errors)
    checks["configuration"] = "ok" if not SETTINGS.validation_errors else "failed"
    try:
        check_database()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = "failed"
        errors.append(f"Database check failed: {type(exc).__name__}")
        logger.exception("readiness_database_failed")
    try:
        check_redis()
        checks["redis"] = "ok"
        if not SETTINGS.validation_errors and checks.get("database") == "ok":
            reconcile_active_jobs()
    except Exception as exc:
        checks["redis"] = "failed"
        errors.append(f"Redis check failed: {type(exc).__name__}")
        logger.exception("readiness_redis_failed")
    if errors:
        return _error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "backend_not_ready",
            "Backend dependencies are not ready",
            {"checks": checks, "errors": errors},
        )
    return ReadinessResponse(status="ready", checks={"configuration": "ok", "database": "ok", "redis": "ok"})
