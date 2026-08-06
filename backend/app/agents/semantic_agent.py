"""
Semantic Query Agent
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
import os

from app.config.analysis_config import AnalysisConfig, get_depth_parameters, get_verbosity_instructions


def create_semantic_query_agent(config: AnalysisConfig) -> AssistantAgent:
    """
    Creates the Semantic Query Agent.
    
    This agent analyzes the codebase structure using RAG retrieval to identify:
    - Components and their relationships
    - API endpoints
    - Data entities
    - Data flows
    - Key files
    
    Args:
        config: Analysis configuration
        
    Returns:
        Configured AssistantAgent
    """
    
    depth_params = get_depth_parameters(config.depth)
    verbosity_instr = get_verbosity_instructions(config.verbosity)
    
    system_message = f"""You are a Semantic Code Analysis Agent. Your job is to analyze a codebase and extract its structural components.

**Analysis Depth**: {config.depth}
**Retrieval Limit**: Use top {depth_params['retrieval_k']} chunks per query
**Detail Level**: {depth_params['detail_level']}

**Your Task**:
1. Analyze the provided code samples and metadata
2. Identify components, APIs, entities, data flows, and key files
3. Return results in strict JSON format matching the SemanticQueryOutput schema

**Output Requirements**:
- Provide ONLY valid JSON, no markdown, no explanations outside the JSON
- Include all required fields
- {verbosity_instr}

**EXACT JSON Schema Required**:
{{
  "components": [
    {{
      "name": "ComponentName",
      "type": "service|controller|model|util|etc",
      "file_paths": ["path/to/file.py"],
      "description": "What it does",
      "dependencies": ["OtherComponent"]
    }}
  ],
  "apis": [
    {{
      "method": "GET",
      "path": "/api/endpoint",
      "handler": "function_name",
      "file_path": "path/to/handler.py",
      "description": "What it does",
      "parameters": ["param1", "param2"]
    }}
  ],
  "entities": [
    {{
      "name": "EntityName",
      "type": "model|schema|table",
      "file_path": "path/to/model.py",
      "fields": ["field1", "field2"],
      "relationships": ["RelatedEntity"]
    }}
  ],
  "data_flows": [
    {{
      "source": "ComponentA",
      "target": "ComponentB",
      "data_type": "UserData",
      "description": "Flow description"
    }}
  ],
  "key_files": [
    {{
      "path": "main.py",
      "role": "entrypoint",
      "importance": "Why important"
    }}
  ],
  "stack_summary": "Brief tech stack summary"
}}

CRITICAL: ALL fields shown above are REQUIRED. Output ONLY valid JSON."""

    # Get API key from environment
    api_key = os.getenv("OPENAI_API_KEY")
    
    # Create model client
    model_client = OpenAIChatCompletionClient(
        model=config.llm_model,
        api_key=api_key,
        temperature=config.temperature,
        max_tokens=config.max_tokens
    )

    return AssistantAgent(
        name="semantic_query_agent",
        description="Analyzes codebase structure and extracts components",
        model_client=model_client,
        system_message=system_message
    )


# ============================================================================
