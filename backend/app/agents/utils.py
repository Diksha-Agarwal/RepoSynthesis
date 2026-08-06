"""
Utility functions for agents
"""

from typing import Dict, List, Any, Optional


def search_code(query: str, k: int = 5, vector_store_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search the vector database for relevant code chunks.
    
    This is called by agents to retrieve relevant context from the codebase.
    
    Args:
        query: Natural language query
        k: Number of results to return
        vector_store_path: Path to FAISS vector store
        
    Returns:
        List of dicts with 'content', 'file_path', 'language', 'semantic_type'
    """
    if vector_store_path is None:
        # Stub implementation for testing
        return [
            {
                "content": "# Example code chunk",
                "file_path": "main.py",
                "language": "Python",
                "semantic_type": "source"
            }
        ]
    
    # Real implementation using embeddings module (repo-processing/ is in sys.path)
    from embeddings import load_vector_store
    
    vector_store = load_vector_store(vector_store_path)
    docs = vector_store.similarity_search(query, k=k)
    
    results = []
    for doc in docs:
        results.append({
            "content": doc.page_content,
            "file_path": doc.metadata.get('file_path', ''),
            "language": doc.metadata.get('language', ''),
            "semantic_type": doc.metadata.get('semantic_type', ''),
            "chunk_index": doc.metadata.get('chunk_index', 0)
        })
    
    return results
