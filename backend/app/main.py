import asyncio
import json
import sys
import time
import traceback
from pathlib import Path
from threading import Thread
from typing import Any

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
    AnalysisResultResponse,
    AnalysisStartResponse,
    AnalysisStatusResponse,
    ChatRequest,
    ChatResponse,
    PreprocessStatusResponse,
)
from db import Project
from ingestion import IngestionError, SETTINGS, resolve_uploaded_zip
from projects import get_project_or_404, router as projects_router


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
preprocess_status: dict[str, dict[str, Any]] = {}
analysis_status: dict[str, dict[str, Any]] = {}
project_chat_histories: dict[str, list] = {}
vector_store_cache: dict[str, Any] = {}
llm_instance = None


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


def run_preprocessing(project_id: str, file_path: str):
    from pipeline import process_repository_for_graphflow

    preprocess_status[project_id] = {"status": "running", "current_step": "Starting preprocessing..."}
    try:
        def update_step(message: str):
            preprocess_status[project_id] = {"status": "running", "current_step": message}

        update_step("Cloning GitHub repository..." if file_path.startswith("http") else "Extracting ZIP file...")
        process_repository_for_graphflow(file_path, project_id=project_id, status_callback=update_step)
        preprocess_status[project_id] = {"status": "completed", "current_step": "Preprocessing complete"}
        vector_store_cache.pop(project_id, None)
    except Exception as exc:
        traceback.print_exc()
        if "Failed to clone repository" in str(exc):
            message = "Failed to clone GitHub repository. Check the URL and ensure the repository is public."
        elif "Invalid input type" in str(exc):
            message = "Invalid file path or GitHub URL."
        else:
            message = str(exc)
        failure = {"status": "failed", "error": message}
        if isinstance(exc, IngestionError):
            failure["error_code"] = exc.code
        preprocess_status[project_id] = failure


@app.post("/projects/{project_id}/preprocess", response_model=ActionResponse)
async def preprocess_project(project: Project = Depends(get_project_or_404)):
    file_path = project.zip_filename or project.github_url
    if not file_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project has no ZIP file or GitHub URL")
    if project.zip_filename:
        try:
            file_path = str(resolve_uploaded_zip(project.zip_filename))
        except IngestionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc

    project_id = str(project.id)
    Thread(target=run_preprocessing, args=(project_id, str(file_path)), daemon=True).start()
    return ActionResponse(status="started")


@app.get("/projects/{project_id}/preprocess/status", response_model=PreprocessStatusResponse)
async def get_preprocess_status(project: Project = Depends(get_project_or_404)):
    project_id = str(project.id)
    return preprocess_status.get(project_id, {"status": "not_started", "current_step": "Not started"})


async def run_graphflow_analysis(project_id: str, personas: str = "SDE,PM", depth: str = "standard", verbosity: str = "medium"):
    def update(activity: str, progress: int, insight: str = None):
        if project_id in analysis_status:
            current_status = analysis_status[project_id]
            current_status["current_activity"] = activity
            current_status["progress"] = progress
            current_status["logs"].append(f"[{progress}%] {activity}")
            if insight:
                current_status["agent_insights"][activity] = insight

    try:
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
        coordinator = GraphFlowCoordinator(project_id, config, project_dir=BASE_DATA_DIR / project_id)
        coordinator.selected_personas = personas_list
        coordinator.status_callback = update

        update("Running agent pipeline...", 10)
        result = await coordinator.run_analysis()
        if not result.success:
            analysis_status[project_id] = {
                "status": "failed",
                "error": "; ".join(result.errors) if result.errors else "Unknown agent error",
            }
            return

        result_data = {
            "config": {"personas": personas, "depth": depth, "verbosity": verbosity},
            "sde_report": result.sde_report.model_dump() if result.sde_report and "SDE" in personas_list else None,
            "pm_report": result.pm_report.model_dump() if result.pm_report and "PM" in personas_list else None,
            "time": result.execution_time_seconds,
        }
        project_dir = BASE_DATA_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        with (project_dir / "analysis_result.json").open("w", encoding="utf-8") as result_file:
            json.dump(result_data, result_file, indent=2)
        analysis_status[project_id] = {"status": "completed", "result": result_data}
    except Exception as exc:
        traceback.print_exc()
        analysis_status[project_id] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


@app.post("/projects/{project_id}/analyze/graphflow", response_model=AnalysisStartResponse)
async def start_analysis(payload: AnalysisRequest, project: Project = Depends(get_project_or_404)):
    project_id = str(project.id)
    project_dir = BASE_DATA_DIR / project_id
    if not (project_dir / "context.json").exists() or not (project_dir / "vector_store").exists():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run preprocessing before analysis")

    analysis_status[project_id] = {
        "status": "running",
        "progress": 0,
        "current_activity": "Starting analysis...",
        "logs": ["Analysis queued"],
        "agent_insights": {},
    }
    personas = ",".join(payload.personas)
    asyncio.create_task(run_graphflow_analysis(project_id, personas, payload.depth, payload.verbosity))
    return AnalysisStartResponse(status="started", config=payload)


@app.get("/projects/{project_id}/status", response_model=AnalysisStatusResponse)
async def get_status(project: Project = Depends(get_project_or_404)):
    project_id = str(project.id)
    if project_id in analysis_status:
        return analysis_status[project_id]
    result_file = BASE_DATA_DIR / project_id / "analysis_result.json"
    if result_file.exists():
        try:
            with result_file.open("r", encoding="utf-8") as source:
                return {"status": "completed", "result": json.load(source)}
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stored analysis result could not be read")
    return {"status": "not_started"}


@app.get("/projects/{project_id}/result", response_model=AnalysisResultResponse)
async def get_result(project: Project = Depends(get_project_or_404)):
    result_file = BASE_DATA_DIR / str(project.id) / "analysis_result.json"
    if not result_file.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis result not found")
    try:
        with result_file.open("r", encoding="utf-8") as source:
            return AnalysisResultResponse(result=json.load(source))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stored analysis result could not be read")


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
        analysis_file = project_dir / "analysis_result.json"
        if analysis_file.exists():
            try:
                with analysis_file.open("r", encoding="utf-8") as source:
                    analysis_data = json.load(source)
                sde_report = analysis_data.get("sde_report") or {}
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
            except (OSError, json.JSONDecodeError):
                pass
        if not analysis_context and analysis_status.get(project_id, {}).get("status") == "running":
            insights = analysis_status[project_id].get("agent_insights", {})
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
