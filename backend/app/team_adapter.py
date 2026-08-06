"""
Adapter to convert preprocessor output to GraphFlow format
"""
import json
from pathlib import Path
from typing import Dict, Any

# Absolute base path for project data
_BASE_DATA_DIR = Path(__file__).parent / "data" / "projects"


def create_graphflow_context(
    project_id: str,
    repo_analysis: Dict[str, Any],
    sections_count: int,
    output_dir: str = None
) -> Dict[str, Any]:
    if output_dir is None:
        output_dir = str(_BASE_DATA_DIR)
    # Convert Pydantic model to dict if needed
    if hasattr(repo_analysis, 'model_dump'):
        repo_analysis = repo_analysis.model_dump()
    elif hasattr(repo_analysis, 'dict'):
        repo_analysis = repo_analysis.dict()
    
    # Extract stack info with fallbacks
    stack = repo_analysis.get("stack", "Unknown")
    framework = repo_analysis.get("framework", "None")
    entry_points = repo_analysis.get("entry_points", [])
    
    # Determine primary language from stack
    if isinstance(stack, str) and stack != "Unknown":
        primary_language = stack.split()[0]
    else:
        primary_language = "Unknown"
    
    # Build context
    context = {
        "project_id": project_id,
        "repo_root": entry_points[0] if entry_points else "unknown",
        "analyzed_at": "2025-11-19T00:00:00Z",  # Could use datetime.utcnow().isoformat()
        "metadata": {
            "primary_language": primary_language,
            "languages": [primary_language],  # Could extract from stack
            "frameworks": [framework] if framework != "None" else [],
            "total_files": sections_count,  # Approximation
            "total_chunks": sections_count,
            "total_size_mb": 0.0  # Optional field
        },
        "files": [],  # Optional - GraphFlow doesn't use this
        "vector_store_path": f"{output_dir}/{project_id}/vector_store",
        "chunk_count": sections_count
    }
    
    return context


def save_for_graphflow(
    project_id: str,
    repo_analysis: Dict[str, Any],
    sections_count: int,
    faiss_store,
    output_dir: str = None
) -> str:
    if output_dir is None:
        output_dir = str(_BASE_DATA_DIR)
    """
    Save preprocessor output in GraphFlow-compatible format
    
    Args:
        project_id: Unique project ID
        repo_analysis: RepoIntel analysis result
        sections_count: Number of code chunks
        faiss_store: The FAISS vector store object
        output_dir: Base output directory
    
    Returns:
        Path to project directory
        
    Raises:
        ValueError: If required fields missing
        IOError: If file operations fail
    """
    # Validate inputs
    if not project_id or not isinstance(project_id, str):
        raise ValueError("project_id must be a non-empty string")
    
    if not repo_analysis or not isinstance(repo_analysis, dict):
        raise ValueError("repo_analysis must be a dictionary")
    
    if sections_count <= 0:
        raise ValueError("sections_count must be positive")
    
    # Create project directory
    project_dir = Path(output_dir) / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Save context.json
    context = create_graphflow_context(
        project_id=project_id,
        repo_analysis=repo_analysis,
        sections_count=sections_count,
        output_dir=output_dir
    )
    
    context_path = project_dir / "context.json"
    try:
        with open(context_path, 'w', encoding='utf-8') as f:
            json.dump(context, f, indent=2)
        print(f"✅ Saved context.json to {context_path}")
    except IOError as e:
        raise IOError(f"Failed to save context.json: {str(e)}")
    
    # 2. Save FAISS vector store
    vector_store_path = project_dir / "vector_store"
    try:
        faiss_store.save_local(str(vector_store_path))
        print(f"✅ Saved FAISS index to {vector_store_path}")
    except Exception as e:
        raise IOError(f"Failed to save FAISS store: {str(e)}")
    
    # 3. Verify files exist
    if not context_path.exists():
        raise IOError("context.json was not created successfully")
    
    faiss_index = vector_store_path / "index.faiss"
    faiss_pkl = vector_store_path / "index.pkl"
    
    if not faiss_index.exists() or not faiss_pkl.exists():
        raise IOError("FAISS index files missing (index.faiss or index.pkl)")
    
    print(f"\n✅ GraphFlow integration ready!")
    print(f"   Project ID: {project_id}")
    print(f"   Location: {project_dir.absolute()}")
    print(f"   Files: context.json, vector_store/")
    
    return str(project_dir)
