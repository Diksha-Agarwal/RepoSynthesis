"""
Coordinator Agent
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
import os

from app.config.analysis_config import AnalysisConfig, get_depth_parameters, get_verbosity_instructions


def create_coordinator_agent(config: AnalysisConfig) -> AssistantAgent:
    """
    Creates the Coordinator Agent that initiates the analysis pipeline.
    
    This agent:
    - Receives the initial project context
    - Formulates the analysis strategy
    - Kicks off the workflow with clear instructions
    """
    
    system_message = f"""You are the Coordinator Agent for codebase analysis.

**Your Role**:
You receive project metadata and initiate a comprehensive analysis by providing clear instructions to downstream agents.

**Input**: Project context including:
- Project ID and metadata
- File list and primary language
- Detected frameworks
- Vector store availability

**Your Task**:
1. Summarize the project scope
2. Identify key analysis priorities
3. Formulate specific questions for the Semantic Query Agent

**Output Format** (JSON):
{{
  "project_summary": "Brief overview of what this codebase appears to be",
  "analysis_priorities": ["Priority 1", "Priority 2"],
  "semantic_queries": [
    "Find main application entry points",
    "Identify API routes and handlers",
    "Locate database models and schemas",
    "Find configuration files"
  ]
}}

Keep output concise and actionable."""

    api_key = os.getenv("OPENAI_API_KEY")
    
    model_client = OpenAIChatCompletionClient(
        model=config.llm_model,
        api_key=api_key,
        temperature=0.2,
        max_tokens=config.max_tokens
    )

    return AssistantAgent(
        name="coordinator_agent",
        description="Orchestrates the codebase analysis workflow",
        model_client=model_client,
        system_message=system_message
    )


