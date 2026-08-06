"""
Analysis Configuration Module
Manages analysis depth, verbosity, features, and templates for AutoGen pipeline
"""

from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field, validator
from pathlib import Path
import json


class DiagramPreferences(BaseModel):
    """Diagram generation preferences"""
    enabled: List[Literal["architecture", "sequence", "er", "flowchart"]] = Field(
        default=["architecture"],
        description="Which diagram types to generate"
    )
    format: Literal["mermaid", "plantuml"] = Field(
        default="mermaid",
        description="Diagram output format"
    )


class FeaturesEnabled(BaseModel):
    """Feature toggles for analysis agents"""
    structure: bool = Field(default=True, description="Enable structural analysis (Semantic Query Agent)")
    api_db: bool = Field(default=True, description="Enable API/DB analysis")
    best_practices: bool = Field(default=True, description="Enable best practices review")
    pm_insights: bool = Field(default=True, description="Enable PM insights generation")


class AnalysisConfig(BaseModel):
    """Complete analysis configuration"""
    depth: Literal["quick", "standard", "deep"] = Field(
        default="standard",
        description="Analysis depth - affects LLM calls and detail level"
    )
    verbosity: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Output verbosity level"
    )
    features_enabled: FeaturesEnabled = Field(
        default_factory=FeaturesEnabled,
        description="Which analysis features to enable"
    )
    diagram_preferences: DiagramPreferences = Field(
        default_factory=DiagramPreferences,
        description="Diagram generation settings"
    )
    template_id: Optional[str] = Field(
        default=None,
        description="Optional template ID for predefined configs"
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model to use"
    )
    max_tokens: int = Field(
        default=4000,
        description="Max tokens per agent response"
    )
    temperature: float = Field(
        default=0.3,
        description="LLM temperature (0.0-1.0)"
    )
    
    @validator('temperature')
    def validate_temperature(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError("Temperature must be between 0.0 and 1.0")
        return v


# Predefined templates
TEMPLATES = {
    "quick_scan": {
        "depth": "quick",
        "verbosity": "low",
        "features_enabled": {
            "structure": True,
            "api_db": False,
            "best_practices": False,
            "pm_insights": False
        },
        "diagram_preferences": {
            "enabled": ["architecture"],
            "format": "mermaid"
        },
        "llm_model": "gpt-4o-mini",
        "max_tokens": 2000,
        "temperature": 0.2
    },
    
    "full_analysis": {
        "depth": "deep",
        "verbosity": "high",
        "features_enabled": {
            "structure": True,
            "api_db": True,
            "best_practices": True,
            "pm_insights": True
        },
        "diagram_preferences": {
            "enabled": ["architecture", "sequence", "er"],
            "format": "mermaid"
        },
        "llm_model": "gpt-4o",
        "max_tokens": 4000,
        "temperature": 0.3
    },
    
    "sde_focused": {
        "depth": "deep",
        "verbosity": "high",
        "features_enabled": {
            "structure": True,
            "api_db": True,
            "best_practices": True,
            "pm_insights": False
        },
        "diagram_preferences": {
            "enabled": ["architecture", "sequence", "er"],
            "format": "mermaid"
        },
        "llm_model": "gpt-4o",
        "max_tokens": 4000,
        "temperature": 0.2
    },
    
    "pm_focused": {
        "depth": "standard",
        "verbosity": "medium",
        "features_enabled": {
            "structure": True,
            "api_db": False,
            "best_practices": True,
            "pm_insights": True
        },
        "diagram_preferences": {
            "enabled": ["flowchart"],
            "format": "mermaid"
        },
        "llm_model": "gpt-4o-mini",
        "max_tokens": 3000,
        "temperature": 0.4
    }
}


def load_config(project_id: str) -> AnalysisConfig:
    """
    Load analysis config for a project.
    First checks for project-specific config, then falls back to default.
    
    Args:
        project_id: Project UUID
        
    Returns:
        AnalysisConfig instance
    """
    config_path = Path(f"data/projects/{project_id}/analysis_config.json")
    
    if config_path.exists():
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        return AnalysisConfig(**config_data)
    else:
        # Return default config
        return AnalysisConfig()


def save_config(project_id: str, config: AnalysisConfig) -> None:
    """
    Save analysis config for a project.
    
    Args:
        project_id: Project UUID
        config: AnalysisConfig to save
    """
    config_path = Path(f"data/projects/{project_id}/analysis_config.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, 'w') as f:
        f.write(config.model_dump_json(indent=2))


def apply_template(template_id: str) -> AnalysisConfig:
    """
    Apply a predefined template to create an AnalysisConfig.
    
    Args:
        template_id: One of: quick_scan, full_analysis, sde_focused, pm_focused
        
    Returns:
        AnalysisConfig with template settings
        
    Raises:
        ValueError: If template_id not found
    """
    if template_id not in TEMPLATES:
        raise ValueError(
            f"Template '{template_id}' not found. "
            f"Available: {list(TEMPLATES.keys())}"
        )
    
    template_data = TEMPLATES[template_id]
    return AnalysisConfig(**template_data, template_id=template_id)


def validate_config(config: AnalysisConfig) -> tuple[bool, Optional[str]]:
    """
    Validate analysis configuration.
    
    Args:
        config: AnalysisConfig to validate
        
    Returns:
        (is_valid, error_message)
    """
    try:
        # Pydantic already validates on construction, but we can add custom checks
        
        # Check if at least one feature is enabled
        features = config.features_enabled
        if not any([features.structure, features.api_db, features.best_practices, features.pm_insights]):
            return False, "At least one feature must be enabled"
        
        # Check diagram preferences
        if not config.diagram_preferences.enabled:
            return False, "At least one diagram type must be enabled"
        
        # Validate depth vs features
        if config.depth == "quick" and len(config.diagram_preferences.enabled) > 1:
            return False, "Quick analysis should only generate one diagram type"
        
        return True, None
        
    except Exception as e:
        return False, f"Validation error: {str(e)}"


def get_depth_parameters(depth: str) -> Dict:
    """
    Get LLM parameters based on analysis depth.
    
    Args:
        depth: Analysis depth level
        
    Returns:
        Dict with chunk_limit, detail_level, retrieval_k
    """
    params = {
        "quick": {
            "chunk_limit": 10,
            "detail_level": "high-level overview",
            "retrieval_k": 3,
            "max_iterations": 2
        },
        "standard": {
            "chunk_limit": 25,
            "detail_level": "detailed analysis",
            "retrieval_k": 5,
            "max_iterations": 3
        },
        "deep": {
            "chunk_limit": 50,
            "detail_level": "comprehensive deep-dive",
            "retrieval_k": 10,
            "max_iterations": 5
        }
    }
    
    return params.get(depth, params["standard"])


def get_verbosity_instructions(verbosity: str) -> str:
    """
    Get prompt instructions based on verbosity level.
    
    Args:
        verbosity: Verbosity level
        
    Returns:
        String instructions for LLM prompts
    """
    instructions = {
        "low": "Be concise. Use bullet points. Limit explanations to 1-2 sentences.",
        "medium": "Provide clear explanations. Balance brevity with completeness.",
        "high": "Provide detailed explanations, examples, and context. Be thorough."
    }
    
    return instructions.get(verbosity, instructions["medium"])


# Example usage
if __name__ == "__main__":
    # Create default config
    default = AnalysisConfig()
    print("Default config:", default.model_dump_json(indent=2))
    
    # Apply template
    full_config = apply_template("full_analysis")
    print("\nFull analysis template:", full_config.model_dump_json(indent=2))
    
    # Validate
    is_valid, error = validate_config(full_config)
    print(f"\nValidation: {is_valid}, Error: {error}")
    
    # Get depth parameters
    params = get_depth_parameters("deep")
    print(f"\nDeep analysis params: {params}")
