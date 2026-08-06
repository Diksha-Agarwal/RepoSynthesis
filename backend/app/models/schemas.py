"""
Agent Output Schemas
Defines flexible JSON structures for each AutoGen agent's output
Designed to handle variable LLM responses gracefully
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Union


# ============================================================================
# AGENT A: Semantic Query Agent Schemas
# ============================================================================

class Component(BaseModel):
    """A structural component in the codebase"""
    name: str = Field(default="Unknown", description="Component name")
    type: str = Field(default="module", description="Type: module, service, controller, model, util, etc.")
    file_paths: List[str] = Field(default_factory=list, description="Files that comprise this component")
    description: str = Field(default="N/A", description="What this component does")
    dependencies: List[str] = Field(default_factory=list, description="Other components it depends on")


class APIEndpoint(BaseModel):
    """An API endpoint discovered in the codebase"""
    method: str = Field(default="GET", description="HTTP method: GET, POST, PUT, DELETE, etc.")
    path: str = Field(default="/", description="Endpoint path")
    handler: str = Field(default="N/A", description="Function/method that handles this endpoint")
    file_path: str = Field(default="N/A", description="File containing the handler")
    description: str = Field(default="N/A", description="What this endpoint does")
    parameters: List[str] = Field(default_factory=list, description="Expected parameters")


class Entity(BaseModel):
    """A data entity/model in the codebase"""
    name: str = Field(default="Unknown", description="Entity name")
    type: str = Field(default="model", description="Type: model, schema, table, collection, etc.")
    file_path: str = Field(default="N/A", description="File where entity is defined")
    fields: List[str] = Field(default_factory=list, description="Entity fields/columns")
    relationships: List[str] = Field(default_factory=list, description="Related entities")


class DataFlow(BaseModel):
    """A data flow between components"""
    source: str = Field(default="N/A", description="Source component")
    target: str = Field(default="N/A", description="Target component")
    data_type: str = Field(default="N/A", description="Type of data flowing")
    description: str = Field(default="N/A", description="Description of the flow")


class KeyFile(BaseModel):
    """An important file in the codebase"""
    path: str = Field(default="N/A", description="File path")
    role: str = Field(default="N/A", description="Role: entrypoint, config, router, etc.")
    importance: str = Field(default="N/A", description="Why this file is important")


class SemanticQueryOutput(BaseModel):
    """Complete output from Semantic Query Agent"""
    components: List[Component] = Field(default_factory=list, description="Discovered components")
    apis: List[APIEndpoint] = Field(default_factory=list, description="API endpoints")
    entities: List[Entity] = Field(default_factory=list, description="Data entities")
    data_flows: List[DataFlow] = Field(default_factory=list, description="Data flows between components")
    key_files: List[KeyFile] = Field(default_factory=list, description="Important files")
    stack_summary: str = Field(default="N/A", description="Brief summary of tech stack")


# ============================================================================
# AGENT B: Best Practice Agent Schemas
# ============================================================================

class Strength(BaseModel):
    """A strength found in the codebase"""
    category: str = Field(default="general", description="Category: architecture, security, testing, etc.")
    description: str = Field(default="N/A", description="What is done well")
    evidence: str = Field(default="N/A", description="Where/how this was observed")


class Risk(BaseModel):
    """A risk or issue found in the codebase"""
    severity: str = Field(default="medium", description="Severity: low, medium, high, critical")
    category: str = Field(default="general", description="Category: security, performance, maintainability, etc.")
    description: str = Field(default="N/A", description="Description of the risk")
    location: str = Field(default="N/A", description="Where the risk was found")
    impact: str = Field(default="N/A", description="Potential impact if not addressed")


class Recommendation(BaseModel):
    """A recommendation for improvement"""
    priority: str = Field(default="medium", description="Priority: low, medium, high")
    category: str = Field(default="general", description="Category: architecture, security, testing, etc.")
    recommendation: str = Field(default="N/A", description="What should be done")
    rationale: str = Field(default="N/A", description="Why this is recommended")
    effort: str = Field(default="medium", description="Estimated effort: small, medium, large")


class BestPracticeOutput(BaseModel):
    """Complete output from Best Practice Agent"""
    strengths: List[Strength] = Field(default_factory=list, description="Things done well")
    risks: List[Risk] = Field(default_factory=list, description="Risks and issues found")
    recommendations: List[Recommendation] = Field(default_factory=list, description="Recommendations for improvement")
    overall_assessment: str = Field(default="N/A", description="Overall quality assessment")


# ============================================================================
# AGENT C: SDE Writer Schemas
# ============================================================================

class DiagramSpec(BaseModel):
    """Specification for a diagram in Mermaid format"""
    type: str = Field(default="flowchart", description="Diagram type: architecture, sequence, er, flowchart")
    title: str = Field(default="Diagram", description="Diagram title")
    mermaid_code: str = Field(default="graph LR\nA[Start]", description="Mermaid diagram code")
    description: str = Field(default="N/A", description="What this diagram shows")


class ComponentDoc(BaseModel):
    """Documentation for a component"""
    name: str = Field(default="Unknown", description="Component name")
    purpose: str = Field(default="N/A", description="What this component does")
    key_files: List[str] = Field(default_factory=list, description="Main files in this component")
    interfaces: List[str] = Field(default_factory=list, description="How other components interact with this")
    dependencies: List[str] = Field(default_factory=list, description="What this component depends on")


class APIDoc(BaseModel):
    """API documentation"""
    endpoint: str = Field(description="Endpoint path")
    method: str = Field(description="HTTP method")
    description: str = Field(description="What this endpoint does")
    request_format: str = Field(default="N/A", description="Expected request format")
    response_format: str = Field(default="N/A", description="Response format")


class SDEOutput(BaseModel):
    """Complete output from SDE Writer Agent"""
    architecture_summary: str = Field(default="N/A", description="High-level architecture overview")
    components: List[ComponentDoc] = Field(default_factory=list, description="Component documentation")
    apis: List[APIDoc] = Field(default_factory=list, description="API documentation")
    database_model: Optional[Any] = Field(default=None, description="Database model description (string or object)")
    diagrams: List[DiagramSpec] = Field(default_factory=list, description="Diagram specifications")
    technical_notes: List[str] = Field(default_factory=list, description="Additional technical notes")


# ============================================================================
# AGENT D: PM Writer Schemas
# ============================================================================

class Feature(BaseModel):
    """A product feature"""
    name: str = Field(default="Unknown", description="Feature name")
    description: str = Field(default="N/A", description="What the feature does")
    user_value: str = Field(default="N/A", description="Value to end users")


class UserJourney(BaseModel):
    """A user journey through the system"""
    persona: str = Field(default="User", description="User persona")
    goal: str = Field(default="N/A", description="What the user wants to accomplish")
    steps: List[str] = Field(default_factory=list, description="Steps in the journey")
    pain_points: List[str] = Field(default_factory=list, description="Potential pain points")


class Constraint(BaseModel):
    """A constraint or limitation"""
    type: str = Field(default="general", description="Type: technical, business, resource, etc.")
    description: str = Field(default="N/A", description="Description of the constraint")
    impact: str = Field(default="N/A", description="How this affects the product")


class RoadmapIdea(BaseModel):
    """A roadmap idea for future development"""
    category: str = Field(default="feature", description="Category: feature, improvement, tech debt, etc.")
    idea: str = Field(default="N/A", description="The idea")
    rationale: str = Field(default="N/A", description="Why this would be valuable")
    estimated_effort: str = Field(default="medium", description="Rough effort estimate")


class PMOutput(BaseModel):
    """Complete output from PM Writer Agent"""
    product_summary: str = Field(default="N/A", description="High-level product description")
    key_features: List[Feature] = Field(default_factory=list, description="Key product features")
    user_journeys: List[UserJourney] = Field(default_factory=list, description="User journeys")
    constraints: List[Constraint] = Field(default_factory=list, description="Constraints and limitations")
    risks: List[str] = Field(default_factory=list, description="Product/business risks")
    roadmap_ideas: List[RoadmapIdea] = Field(default_factory=list, description="Future roadmap ideas")
    diagrams: List[DiagramSpec] = Field(default_factory=list, description="Product flow diagrams")


# ============================================================================
# AGENT E: Coordinator Agent Schemas
# ============================================================================

class CoordinatorOutput(BaseModel):
    """Output from Coordinator Agent"""
    project_summary: str = Field(default="N/A", description="Brief overview of the project")
    analysis_priorities: List[str] = Field(default_factory=list, description="Key priorities for analysis")
    semantic_queries: List[str] = Field(default_factory=list, description="Specific queries for semantic analysis")


# ============================================================================
# AGENT F: Quality Assurance Agent Schemas
# ============================================================================

class ValidationResult(BaseModel):
    """Validation result for a report"""
    completeness_score: Union[int, float] = Field(default=50, description="Score 0-100 for completeness", ge=0, le=100)
    strengths: List[str] = Field(default_factory=list, description="What was done well")
    gaps: List[str] = Field(default_factory=list, description="What is missing or incomplete")
    enhancement_suggestions: List[str] = Field(default_factory=list, description="Specific suggestions for improvement")


class OverallAssessment(BaseModel):
    """Overall quality assessment"""
    overall_score: Union[int, float] = Field(default=50.0, description="Overall quality score 0-100", ge=0, le=100)
    summary: str = Field(default="N/A", description="Summary of the assessment")
    critical_issues: List[str] = Field(default_factory=list, description="Critical issues that must be addressed")
    recommended_next_steps: List[str] = Field(default_factory=list, description="Recommended next steps")


class QAOutput(BaseModel):
    """Complete output from QA Agent"""
    sde_validation: Optional[ValidationResult] = Field(default=None, description="Validation of SDE report")
    pm_validation: Optional[ValidationResult] = Field(default=None, description="Validation of PM report")
    overall_assessment: Optional[OverallAssessment] = Field(default=None, description="Overall assessment")


# ============================================================================
# Final Combined Output
# ============================================================================

class AnalysisResult(BaseModel):
    """Final combined analysis result from all agents"""
    project_id: str = Field(description="Project UUID")
    config_used: Dict[str, Any] = Field(description="Analysis configuration used")
    coordinator_output: Optional[CoordinatorOutput] = Field(default=None, description="Coordinator analysis")
    semantic_analysis: Optional[SemanticQueryOutput] = Field(default=None)
    best_practices: Optional[BestPracticeOutput] = Field(default=None)
    sde_report: Optional[SDEOutput] = Field(default=None)
    pm_report: Optional[PMOutput] = Field(default=None)
    qa_report: Optional[QAOutput] = Field(default=None, description="Quality assurance validation")
    agent_results: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw results from each agent"
    )
    execution_time_seconds: float = Field(description="Total execution time")
    success: bool = Field(description="Whether analysis completed successfully")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
