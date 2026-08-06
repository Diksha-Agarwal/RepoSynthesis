"""
QA Agent
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
import os

from app.config.analysis_config import AnalysisConfig, get_depth_parameters, get_verbosity_instructions


def create_qa_agent(config: AnalysisConfig) -> AssistantAgent:
    """
    Creates the QA Agent that validates and enhances SDE and PM outputs.
    
    This agent:
    - Reviews SDE technical documentation for completeness and accuracy
    - Reviews PM product documentation for clarity and user value
    - Identifies gaps or inconsistencies
    - Suggests enhancements
    - Validates that outputs match schemas
    """
    
    system_message = f"""You are the Quality Assurance Agent for codebase analysis outputs.

**Your Role**:
You receive the SDE technical report and PM product report, then validate and enhance them.

**Validation Checks**:

For SDE Report:
- Are all major components documented?
- Is the architecture description clear and accurate?
- Are setup instructions complete?
- Are dependencies listed correctly?
- Is there a clear flow from setup to deployment?

For PM Report:
- Is the product summary user-friendly?
- Do features have clear user value propositions?
- Are user journeys realistic and complete?
- Are risks and constraints identified?
- Are roadmap ideas actionable?

**Your Task**:
1. Review both reports thoroughly
2. Identify strengths and gaps
3. Suggest specific enhancements
4. Provide an overall quality score

**Output Format** (JSON matching QAOutput schema):
{{
  "sde_validation": {{
    "completeness_score": 0-100,
    "strengths": ["Well-documented architecture", "Clear setup steps"],
    "gaps": ["Missing error handling documentation"],
    "enhancement_suggestions": ["Add troubleshooting section", "Include performance benchmarks"]
  }},
  "pm_validation": {{
    "completeness_score": 0-100,
    "strengths": ["Clear feature descriptions", "Good user journeys"],
    "gaps": ["Limited competitive analysis"],
    "enhancement_suggestions": ["Add target audience demographics", "Include success metrics"]
  }},
  "overall_assessment": {{
    "overall_score": 0-100,
    "summary": "Both reports are comprehensive with minor gaps in...",
    "critical_issues": [],
    "recommended_next_steps": ["Add performance documentation", "Expand user personas"]
  }}
}}

Be constructive and specific. Focus on actionable improvements."""

    api_key = os.getenv("OPENAI_API_KEY")
    
    model_client = OpenAIChatCompletionClient(
        model=config.llm_model,
        api_key=api_key,
        temperature=0.4,  # Moderate temperature for balanced critique
        max_tokens=config.max_tokens
    )

    return AssistantAgent(
        name="qa_agent",
        description="Validates and enhances technical and product documentation",
        model_client=model_client,
        system_message=system_message
    )

