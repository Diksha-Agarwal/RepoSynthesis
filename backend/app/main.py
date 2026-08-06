import asyncio
import sys
import time
import traceback
from pathlib import Path
from threading import Thread
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, HumanMessage
from starlette.exceptions import HTTPException as StarletteHTTPException

ROOT = Path(__file__).parent
load_dotenv(ROOT.parent.parent / ".env")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "repo-processing"))
sys.path.insert(0, str(ROOT.parent))

from api_schemas import (
    ActionResponse,
    AnalysisRequest,
    ChatRequest,
    ChatResponse,
    LatestRunsResponse,
    LatestRunStatusResponse,
    RunListResponse,
    RunResponse,
    RunStartResponse,
)
from app.models.schemas import AnalysisResult, AnalysisResultListResponse
from db import Project
from ingestion import IngestionError, SETTINGS, resolve_uploaded_zip
from projects import get_project_or_404, router as projects_router
from run_store import (
    ActiveRunExistsError,
    ProjectNotFoundError,
    cancel_orphaned_active_runs,
    create_run,
    finalize_analysis_run,
    get_analysis_result,
    get_latest_completed_analysis_result,
    get_latest_run,
    get_run,
    list_completed_analysis_results,
    list_project_runs,
    update_run,
)


app = FastAPI(
    title="RepoResearchAI Demo API",
    description="Single-user repository analysis API for the Next.js demo client.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects_router)

BASE_DATA_DIR = ROOT / "data" / "projects"
BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
project_chat_histories: dict[str, list] = {}
vector_store_cache: dict[str, Any] = {}
llm_instance = None


@app.on_event("startup")
def reconcile_interrupted_runs():
    cancel_orphaned_active_runs()


def _error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = jsonable_encoder(details)
    return JSONResponse(status_code=status_code, content={"error": error})


@app.middleware("http")
async def reject_oversized_upload_requests(request: Request, call_next):
    if request.method == "POST" and request.url.path.rstrip("/") == "/projects/upload":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                request_size = int(content_length)
            except ValueError:
                return _error_response(400, "invalid_content_length", "Content-Length must be a valid integer")
            multipart_allowance = 1024 * 1024
            if request_size > SETTINGS.max_upload_zip_bytes + multipart_allowance:
                return _error_response(413, "upload_too_large", "Upload request exceeds the configured size limit")
    return await call_next(request)


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
    traceback.print_exception(exc)
    return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "An unexpected server error occurred")


def run_preprocessing(project_id: str, run_id: str, file_path: str):
    from pipeline import process_repository_for_graphflow

    progress_by_activity = {
        "Loading repository files...": 10,
        "Extracting code sections...": 30,
        "Analyzing repository structure...": 50,
        "Generating embeddings...": 70,
        "Saving project data...": 90,
    }
    try:
        update_run(
            run_id,
            status="running",
            progress=1,
            current_activity="Starting preprocessing...",
            log_message="Preprocessing started",
        )

        def update_step(message: str):
            progress = progress_by_activity.get(message, 5)
            update_run(
                run_id,
                progress=progress,
                current_activity=message,
                log_message=f"[{progress}%] {message}",
            )

        update_step("Cloning GitHub repository..." if file_path.startswith("http") else "Extracting ZIP file...")
        process_repository_for_graphflow(file_path, project_id=project_id, status_callback=update_step)
        update_run(
            run_id,
            status="completed",
            progress=100,
            current_activity="Preprocessing complete",
            log_message="[100%] Preprocessing complete",
        )
        vector_store_cache.pop(project_id, None)
    except Exception as exc:
        traceback.print_exc()
        if "Failed to clone repository" in str(exc):
            message = "Failed to clone GitHub repository. Check the URL and ensure the repository is public."
        elif "Invalid input type" in str(exc):
            message = "Invalid file path or GitHub URL."
        else:
            message = str(exc)
        update_run(
            run_id,
            status="failed",
            current_activity="Preprocessing failed",
            error_message=message,
            log_message=f"Preprocessing failed: {message}",
        )


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
            detail={"code": "active_run_exists", "message": "A preprocessing run is already queued or running"},
        ) from exc

    try:
        Thread(
            target=run_preprocessing,
            args=(str(project.id), run["run_id"], str(file_path)),
            daemon=True,
        ).start()
    except Exception as exc:
        update_run(
            run["run_id"],
            status="failed",
            current_activity="Unable to start preprocessing",
            error_message=str(exc),
        )
        raise
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


async def run_graphflow_analysis(
    project_id: str,
    run_id: str,
    personas: str = "SDE,PM",
    depth: str = "standard",
    verbosity: str = "medium",
):
    def update(activity: str, progress: int, insight: str = None):
        update_run(
            run_id,
            progress=progress,
            current_activity=activity,
            log_message=f"[{progress}%] {activity}",
            insight_activity=activity if insight else None,
            insight=insight,
        )

    try:
        update_run(
            run_id,
            status="running",
            progress=1,
            current_activity="Starting analysis...",
            log_message="Analysis started",
        )
        from app.config.analysis_config import AnalysisConfig, FeaturesEnabled
        from app.teams.graphflow_team import GraphFlowCoordinator

        personas_list = [persona.strip() for persona in personas.split(",")]
        config = AnalysisConfig(
            depth=depth,
            verbosity=verbosity,
            features_enabled=FeaturesEnabled(
                structure=True,
                api_db=True,
                best_practices=True,
                pm_insights="PM" in personas_list,
            ),
        )
        update("Creating analysis coordinator...", 5)
        coordinator = GraphFlowCoordinator(
            project_id,
            config,
            project_dir=BASE_DATA_DIR / project_id,
            analysis_run_id=run_id,
        )
        coordinator.selected_personas = personas_list
        coordinator.status_callback = update

        update("Running agent pipeline...", 10)
        result = await coordinator.run_analysis()
        error_message = "; ".join(result.errors) if result.errors else None
        finalize_analysis_run(
            int(project_id),
            run_id,
            result.model_dump(mode="json"),
            success=result.success,
            error_message=error_message,
        )
        if not result.success:
            return
    except Exception as exc:
        traceback.print_exc()
        error_message = f"{type(exc).__name__}: {exc}"
        update_run(
            run_id,
            status="failed",
            current_activity="Analysis failed",
            error_message=error_message,
            log_message=f"Analysis failed: {error_message}",
        )


@app.post("/projects/{project_id}/analyze/graphflow", response_model=RunStartResponse)
async def start_analysis(payload: AnalysisRequest, project: Project = Depends(get_project_or_404)):
    project_id = str(project.id)
    project_dir = BASE_DATA_DIR / project_id
    if not (project_dir / "context.json").exists() or not (project_dir / "vector_store").exists():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run preprocessing before analysis")

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
            detail={"code": "active_run_exists", "message": "An analysis run is already queued or running"},
        ) from exc

    personas = ",".join(payload.personas)
    try:
        asyncio.create_task(run_graphflow_analysis(project_id, run["run_id"], personas, payload.depth, payload.verbosity))
    except Exception as exc:
        update_run(
            run["run_id"],
            status="failed",
            current_activity="Unable to start analysis",
            error_message=str(exc),
        )
        raise
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
    project_id = str(project.id)
    project_dir = BASE_DATA_DIR / project_id
    if not (project_dir / "vector_store").exists():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run preprocessing before asking questions")

    try:
        project_chat_histories.setdefault(project_id, [])
        if project_id not in vector_store_cache:
            vector_store_cache[project_id] = load_vector_store(str(project_dir / "vector_store"))
        vectorstore = vector_store_cache[project_id]
        if llm_instance is None:
            from langchain_openai import ChatOpenAI
            llm_instance = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

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
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to answer the question") from exc


@app.post("/projects/{project_id}/chat/clear", response_model=ActionResponse)
async def clear_chat_memory(project: Project = Depends(get_project_or_404)):
    project_id = str(project.id)
    had_history = bool(project_chat_histories.pop(project_id, None))
    return ActionResponse(status="cleared" if had_history else "no_history")


@app.post("/projects/{project_id}/cache/clear", response_model=ActionResponse)
async def clear_cache(project: Project = Depends(get_project_or_404)):
    project_id = str(project.id)
    had_cache = vector_store_cache.pop(project_id, None) is not None
    return ActionResponse(status="cache_cleared" if had_cache else "no_cache")


@app.get("/health", response_model=ActionResponse)
async def health():
    return ActionResponse(status="ok")
