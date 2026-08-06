"""
SDE Writer Agent
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
import os

from app.config.analysis_config import AnalysisConfig, get_depth_parameters, get_verbosity_instructions


def create_sde_writer_agent(config: AnalysisConfig) -> AssistantAgent:
    
    verbosity_instr = get_verbosity_instructions(config.verbosity)
    diagrams_enabled = config.diagram_preferences.enabled
    
    system_message = f"""You are a Technical Documentation Writer Agent for software engineers.

**Your Task**:
1. Review the semantic analysis and best practices results
2. Write clear, technical documentation for developers
3. Generate Mermaid diagram specifications
4. Return results in strict JSON format matching the SDEOutput schema

**Documentation Focus**:
- Architecture overview (how components interact)
- Component documentation (purpose, interfaces, dependencies)
- API documentation (if APIs exist)
- Database model (if entities exist)
- Technical notes and gotchas

**Diagram Requirements**:
Generate Mermaid code for: {', '.join(diagrams_enabled)}
- Use proper Mermaid syntax
- Keep diagrams focused and readable
- Include meaningful labels

**Output Requirements**:
- Provide ONLY valid JSON, no markdown, no explanations outside the JSON
- {verbosity_instr}
- All Mermaid code must be syntactically correct

**EXACT JSON Schema Required**:
{{
  "architecture_summary": "High-level architecture description",
  "components": [
    {{
      "name": "ComponentName",
      "purpose": "What it does",
      "key_files": ["file1.py", "file2.py"],
      "interfaces": ["How others interact"],
      "dependencies": ["What it depends on"]
    }}
  ],
  "apis": [
    {{
      "endpoint": "/api/path",
      "method": "GET|POST|PUT|DELETE",
      "description": "What it does",
      "request_format": "Request body/params or N/A",
      "response_format": "Response format or N/A"
    }}
  ],
  "database_model": "Database description or null",
  "diagrams": [
    {{
      "type": "architecture|sequence|er|flowchart",
      "title": "Diagram title",
      "mermaid_code": "graph TD\\n  A-->B",
      "description": "What this shows"
    }}
  ],
  "technical_notes": ["Note 1", "Note 2"]
}}

CRITICAL: ALL fields shown above are REQUIRED. Output ONLY valid JSON."""

    api_key = os.getenv("OPENAI_API_KEY")
    
    model_client = OpenAIChatCompletionClient(
        model=config.llm_model,
        api_key=api_key,
        temperature=config.temperature,
        max_tokens=config.max_tokens
    )

    return AssistantAgent(
        name="sde_writer_agent",
        description="Writes technical documentation for developers",
        model_client=model_client,
        system_message=system_message
    )

