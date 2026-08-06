from fastapi import FastAPI, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv
import sys

ROOT = Path(__file__).parent
load_dotenv(ROOT.parent.parent / ".env")  # Load .env from project root

sys.path.insert(0, str(ROOT))               # backend/app/ — for auth, projects, admin, db
sys.path.insert(0, str(ROOT / "repo-processing"))  # for pipeline, embeddings
sys.path.insert(0, str(ROOT.parent))        # backend/ — for app.xxx imports

import auth
import projects
import admin

app = FastAPI(title="RepoResearchAI", description="AI-powered repository analysis")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use absolute path to avoid issues when running from different directories
BASE_DATA_DIR = ROOT / "data" / "projects"
BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
preprocess_status = {}  # Track preprocessing progress
analysis_status = {}    # Track analysis progress

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(admin.router)


def run_preprocessing(project_id: str, file_path: str):
    from pipeline import process_repository_for_graphflow
    preprocess_status[project_id] = {"status": "running", "current_step": "Starting preprocessing..."}
    try:
        def update_step(msg):
            preprocess_status[project_id] = {"status": "running", "current_step": msg}
        
        # Show appropriate status for GitHub vs ZIP
        if file_path.startswith("http"):
            update_step("Cloning GitHub repository...")
        else:
            update_step("Extracting ZIP file...")
        
        process_repository_for_graphflow(file_path, project_id=project_id, status_callback=update_step)
        preprocess_status[project_id] = {"status": "completed", "current_step": "Preprocessing complete"}
        
        # Clear vector store cache to force reload with new data
        if project_id in vector_store_cache:
            del vector_store_cache[project_id]
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        # User-friendly error messages
        if "Failed to clone repository" in str(e):
            user_msg = "Failed to clone GitHub repository. Please check the URL and ensure the repository is public."
        elif "Invalid input type" in str(e):
            user_msg = "Invalid file path or GitHub URL."
        else:
            user_msg = str(e)
        
        preprocess_status[project_id] = {
            "status": "failed", 
            "error": user_msg,
            "details": error_msg
        }

@app.post("/projects/{project_id}/preprocess")
async def preprocess_project(project_id: str):
    from db import SessionLocal, Project
    from threading import Thread
    
    with SessionLocal() as db:
        project = db.query(Project).filter(Project.id == int(project_id)).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Validate that we have a file path
        file_path = project.zip_filename or project.github_url
        if not file_path:
            raise HTTPException(status_code=400, detail="Project has no file or GitHub URL")
        
        file_path = str(file_path)
        
        # Validate file exists if it's a ZIP
        if not file_path.startswith("http"):
            if not Path(file_path).exists():
                raise HTTPException(
                    status_code=400, 
                    detail=f"Uploaded file not found at: {file_path}. Please re-upload the project."
                )
    
    Thread(target=run_preprocessing, args=(project_id, file_path), daemon=True).start()
    return {"status": "started"}

@app.get("/projects/{project_id}/preprocess/status")
async def get_preprocess_status(project_id: str):
    # Return not_started instead of 404 to avoid errors in frontend
    if project_id not in preprocess_status:
        return {"status": "not_started", "current_step": "Not started"}
    return preprocess_status[project_id]


async def run_graphflow_analysis(project_id: str, personas: str = "SDE,PM", depth: str = "standard", verbosity: str = "medium"):
    import json
    import traceback

    def _update(activity: str, progress: int, insight: str = None):
        if project_id in analysis_status:
            analysis_status[project_id]["current_activity"] = activity
            analysis_status[project_id]["progress"] = progress
            analysis_status[project_id]["logs"].append(f"[{progress}%] {activity}")
            if insight:
                analysis_status[project_id]["agent_insights"][activity] = insight

    print(f"[analysis] Starting for project {project_id} | personas={personas} depth={depth} verbosity={verbosity}")
    _update("Importing modules...", 2)

    try:
        from app.teams.graphflow_team import GraphFlowCoordinator
        from app.config.analysis_config import AnalysisConfig, FeaturesEnabled
    except Exception as e:
        msg = f"Import error: {e}\n{traceback.format_exc()}"
        print(f"[analysis] {msg}")
        analysis_status[project_id] = {"status": "failed", "error": msg}
        return

    try:
        personas_list = [p.strip() for p in personas.split(",")]
        depth_val = depth if depth in ("quick", "standard", "deep") else "standard"
        verbosity_val = verbosity if verbosity in ("low", "medium", "high") else "medium"

        config = AnalysisConfig(
            depth=depth_val,
            verbosity=verbosity_val,
            features_enabled=FeaturesEnabled(
                structure=True, api_db=True, best_practices=True,
                pm_insights="PM" in personas_list,
            ),
        )

        _update("Creating analysis coordinator...", 5)
        absolute_project_dir = BASE_DATA_DIR / project_id
        coordinator = GraphFlowCoordinator(project_id, config, project_dir=absolute_project_dir)
        coordinator.selected_personas = personas_list
        coordinator.status_callback = _update

        _update("Running agent pipeline...", 10)
        print(f"[analysis] Running coordinator.run_analysis()...")
        result = await coordinator.run_analysis()
        print(f"[analysis] Completed in {result.execution_time_seconds}s  success={result.success}")

        if not result.success:
            error_detail = "; ".join(result.errors) if result.errors else "Unknown agent error"
            print(f"[analysis] Pipeline returned success=False: {error_detail}")
            analysis_status[project_id] = {"status": "failed", "error": error_detail}
            return

        result_data = {
            "config": {"personas": personas, "depth": depth, "verbosity": verbosity},
            "sde_report": result.sde_report.model_dump() if result.sde_report and "SDE" in personas_list else None,
            "pm_report": result.pm_report.model_dump() if result.pm_report and "PM" in personas_list else None,
            "time": result.execution_time_seconds,
        }

        # Save to file
        project_dir = BASE_DATA_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        with open(project_dir / "analysis_result.json", "w") as f:
            json.dump(result_data, f, indent=2)

        analysis_status[project_id] = {
            "status": "completed",
            "result": result_data,
        }
        print(f"[analysis] Saved results for {project_id}")

    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"[analysis] FAILED: {msg}")
        traceback.print_exc()
        analysis_status[project_id] = {"status": "failed", "error": msg}


@app.post("/projects/{project_id}/analyze/graphflow")
async def start_analysis(
    project_id: str,
    personas: str = Form("SDE,PM"),
    depth: str = Form("standard"),
    verbosity: str = Form("medium")
):
    project_dir = BASE_DATA_DIR / project_id
    if not (project_dir / "context.json").exists():
        raise HTTPException(status_code=400, detail="context.json not found - run preprocessing first")
    if not (project_dir / "vector_store").exists():
        raise HTTPException(status_code=400, detail="vector_store not found - run preprocessing first")
    
    # Initialize status IMMEDIATELY to prevent race condition with status polling
    analysis_status[project_id] = {
        "status": "running",
        "progress": 0,
        "current_activity": "Starting analysis...",
        "logs": ["Analysis queued"],
        "agent_insights": {},
        "paused": False
    }
    
    # Start analysis task
    import asyncio
    asyncio.create_task(run_graphflow_analysis(project_id, personas, depth, verbosity))
    
    return {"status": "started", "config": {"personas": personas, "depth": depth, "verbosity": verbosity}}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/projects/{project_id}/status")
async def get_status(project_id: str):
    import json
    # Return in-memory status if available
    if project_id in analysis_status:
        return analysis_status[project_id]

    # Fallback: check if result file exists on disk (e.g. after server restart)
    result_file = BASE_DATA_DIR / project_id / "analysis_result.json"
    if result_file.exists():
        try:
            with open(result_file, "r") as f:
                result_data = json.load(f)
            return {"status": "completed", "result": result_data}
        except Exception:
            pass

    return {"status": "not_started"}



# LangChain imports for conversational AI (v1.0.x)
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage

# Performance optimization: Cache vector stores and LLM instances
project_chat_histories = {}  # Store per-project chat history (list of messages)
vector_store_cache = {}  # Cache loaded vector stores (key: project_id)
llm_instance = None  # Reuse single LLM instance across requests

@app.post("/projects/{project_id}/ask")
async def ask(project_id: str, question: str = Form(...)):
    from embeddings import load_vector_store
    import os
    import time
    global llm_instance
    
    start = time.time()
    project_dir = BASE_DATA_DIR / project_id
    if not (project_dir / "vector_store").exists():
        raise HTTPException(status_code=400, detail="Run preprocessing first")
    
    try:
        # Initialize chat history for this project
        if project_id not in project_chat_histories:
            project_chat_histories[project_id] = []
        
        # OPTIMIZATION: Cache vector store
        t1 = time.time()
        if project_id not in vector_store_cache:
            vector_store_cache[project_id] = load_vector_store(str(project_dir / "vector_store"))
        vectorstore = vector_store_cache[project_id]
        
        # OPTIMIZATION: Reuse LLM instance
        if llm_instance is None:
            from langchain_openai import ChatOpenAI as LLM
            llm_instance = LLM(model="gpt-4o-mini", temperature=0.3)
        
        # Retrieve relevant documents (top 3 for better context)
        retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
        docs = retriever.invoke(question)
        
        # Build context from documents with better formatting
        context_parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get('source', 'unknown')
            content = doc.page_content[:1500]  # Increased from 1200
            context_parts.append(f"[Source {i}: {source}]\n{content}")
        
        context = "\n\n".join(context_parts)
        
        # Load analysis results if available to enrich context
        analysis_context = ""
        analysis_file = project_dir / "analysis_result.json"
        using_partial = False
        
        # First check for completed analysis
        if analysis_file.exists():
            try:
                import json
                with open(analysis_file, 'r', encoding='utf-8') as f:
                    analysis_data = json.load(f)
                    
                # Extract relevant parts of analysis
                sde_report = analysis_data.get('sde_report', {})
                if sde_report:
                    arch_summary = sde_report.get('architecture_summary', '')
                    components = sde_report.get('components', [])
                    apis = sde_report.get('apis', [])
                    db_model = sde_report.get('database_model', '')
                    
                    analysis_context = f"""
Analysis Summary:
Architecture: {arch_summary[:300]}

Components: {', '.join([c.get('name', '') for c in components[:5]])}

APIs: {', '.join([f"{a.get('method', '')} {a.get('endpoint', '')}" for a in apis[:5]])}

Database: {db_model[:200]}
"""
            except:
                pass
        
        # If no complete analysis, check for partial agent insights (during analysis)
        if not analysis_context and project_id in analysis_status:
            status_data = analysis_status[project_id]
            if status_data.get("status") == "running":
                agent_insights = status_data.get("agent_insights", {})
                if agent_insights:
                    using_partial = True
                    # Build context from available agent insights
                    insights_text = []
                    for activity, insight in list(agent_insights.items())[:3]:  # Use first 3 completed agents
                        if insight:
                            insights_text.append(f"{activity}: {str(insight)[:400]}")
                    
                    if insights_text:
                        analysis_context = f"""
Partial Analysis (In Progress):
{chr(10).join(insights_text)}
"""
        
        # Build concise prompt with recent history only (last 6 messages)
        chat_history = project_chat_histories[project_id][-6:]
        
        full_context = f"{analysis_context}\n\nCode Context:\n{context}" if analysis_context else context
        
        system_prompt = f"""You are a code assistant. Answer concisely and directly using the provided context.

{full_context}

Keep answers brief and specific."""
        
        messages = [("system", system_prompt)]
        
        # Add recent chat history (truncated)
        for msg in chat_history:
            if isinstance(msg, HumanMessage):
                messages.append(("human", str(msg.content)[:150]))
            elif isinstance(msg, AIMessage):
                messages.append(("ai", str(msg.content)[:150]))
        
        messages.append(("human", question))
        
        # Generate response
        response = llm_instance.invoke(messages)
        answer = response.content
        
        # Update chat history (keep last 12 messages)
        project_chat_histories[project_id].append(HumanMessage(content=question))
        project_chat_histories[project_id].append(AIMessage(content=answer))
        if len(project_chat_histories[project_id]) > 12:
            project_chat_histories[project_id] = project_chat_histories[project_id][-12:]
        
        return {
            "answer": answer,
            "sources": [doc.metadata.get('source', doc.metadata.get('file', 'unknown')) for doc in docs],
            "time": round(time.time()-start, 2),
            "has_analysis": bool(analysis_context),
            "using_partial": using_partial
        }
        
    except Exception as e:
        import traceback
        print(f"❌ Error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/projects/{project_id}/chat/clear")
async def clear_chat_memory(project_id: str):
    """Clear conversation history for a project"""
    if project_id in project_chat_histories:
        project_chat_histories[project_id] = []
        return {"status": "cleared"}
    return {"status": "no_history"}

@app.post("/projects/{project_id}/cache/clear")
async def clear_cache(project_id: str):
    """Clear vector store cache for a project (use after reprocessing)"""
    if project_id in vector_store_cache:
        del vector_store_cache[project_id]
        return {"status": "cache_cleared"}
    return {"status": "no_cache"}