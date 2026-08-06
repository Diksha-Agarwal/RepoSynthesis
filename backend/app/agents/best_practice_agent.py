"""
Best Practice Agent
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
import os

from app.config.analysis_config import AnalysisConfig, get_depth_parameters, get_verbosity_instructions


def create_best_practice_agent(config: AnalysisConfig) -> AssistantAgent:
    """
    Creates the Best Practice Agent.
    
    This agent reviews the codebase against best practices for the detected stack/framework.
    
    Args:
        config: Analysis configuration
        
    Returns:
        Configured AssistantAgent
    """
    
    verbosity_instr = get_verbosity_instructions(config.verbosity)
    
    system_message = f"""You are a Best Practice Review Agent. You analyze codebases for adherence to industry best practices.

**Your Task**:
1. Review the semantic analysis results (components, APIs, entities)
2. Review the tech stack and frameworks detected
3. **Search online for current best practices, security advisories, and framework-specific guidelines** for the detected technologies
4. Identify strengths, risks, and provide recommendations based on industry standards
5. Return results in strict JSON format matching the BestPracticeOutput schema

**Focus Areas**:
- Architecture patterns (MVC, microservices, layering)
- Security practices (auth, input validation, secrets management, known CVEs)
- Code organization and modularity
- Testing coverage and quality
- Performance considerations
- Error handling
- Documentation
- Framework-specific best practices (e.g., FastAPI security, Django ORM patterns, React hooks)

**Output Requirements**:
- Provide ONLY valid JSON, no markdown, no explanations outside the JSON
- Include all required fields
- {verbosity_instr}
- Severity levels: low, medium, high, critical
- Priority levels: low, medium, high

**EXACT JSON Schema Required**:
{{
  "strengths": [
    {{
      "category": "architecture|security|testing|etc",
      "description": "What is done well",
      "evidence": "Where observed"
    }}
  ],
  "risks": [
    {{
      "severity": "low|medium|high|critical",
      "category": "security|performance|maintainability|etc",
      "description": "Risk description",
      "location": "Where found",
      "impact": "Potential impact"
    }}
  ],
  "recommendations": [
    {{
      "priority": "low|medium|high",
      "category": "architecture|security|testing|etc",
      "recommendation": "What to do",
      "rationale": "Why recommended",
      "effort": "small|medium|large"
    }}
  ],
  "overall_assessment": "Overall quality summary"
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
        name="best_practice_agent",
        description="Reviews code against best practices",
        model_client=model_client,
        system_message=system_message
    )


# ============================================================================
