"""
PM Writer Agent
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
import os

from app.config.analysis_config import AnalysisConfig, get_depth_parameters, get_verbosity_instructions


def create_pm_writer_agent(config: AnalysisConfig) -> AssistantAgent:
    """
    Creates the PM (Product Manager) Writer Agent.
    
    This agent produces product-focused documentation for stakeholders.
    
    Args:
        config: Analysis configuration
        
    Returns:
        Configured AssistantAgent
    """
    
    verbosity_instr = get_verbosity_instructions(config.verbosity)
    
    system_message = f"""You are a Product Documentation Writer Agent for product managers and stakeholders.

**Your Task**:
1. Review the semantic analysis and best practices results
2. Write product-focused documentation explaining WHAT the system does and WHY
3. Identify user journeys, features, and business value
4. Return results in strict JSON format matching the PMOutput schema

**Documentation Focus**:
- Product summary (what problem does this solve?)
- Key features (from user perspective)
- User journeys (how users interact with the system)
- Constraints and limitations
- Product/business risks
- Roadmap ideas for future development

**Perspective**:
- Think like a PM, not an engineer
- Focus on user value, not technical details
- Identify business impact
- Consider product evolution

**Output Requirements**:
- Provide ONLY valid JSON, no markdown, no explanations outside the JSON
- {verbosity_instr}
- User-friendly language, avoid jargon

**EXACT JSON Schema Required**:
{{
  "product_summary": "High-level product description",
  "key_features": [
    {{
      "name": "Feature name",
      "description": "What it does",
      "user_value": "Value to users"
    }}
  ],
  "user_journeys": [
    {{
      "persona": "User type",
      "goal": "What they want",
      "steps": ["Step 1", "Step 2"],
      "pain_points": ["Pain point 1"]
    }}
  ],
  "constraints": [
    {{
      "type": "technical|business|resource|etc",
      "description": "Constraint description",
      "impact": "How it affects product"
    }}
  ],
  "risks": ["Risk 1", "Risk 2"],
  "roadmap_ideas": [
    {{
      "category": "feature|improvement|tech debt|etc",
      "idea": "The idea",
      "rationale": "Why valuable",
      "estimated_effort": "Effort estimate"
    }}
  ],
  "diagrams": [
    {{
      "type": "architecture|sequence|er|flowchart",
      "title": "Diagram title",
      "mermaid_code": "graph TD\\n  A-->B",
      "description": "What this shows"
    }}
  ]
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
        name="pm_writer_agent",
        description="Writes product documentation for stakeholders",
        model_client=model_client,
        system_message=system_message
    )

