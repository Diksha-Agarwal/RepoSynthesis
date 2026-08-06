from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ProjectCreateRequest(BaseModel):
    """JSON request for a GitHub-backed project."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    github_url: str = Field(min_length=1, max_length=2048)


class ProjectResponse(BaseModel):
    id: int
    name: str
    github_url: Optional[str] = None
    uploaded_filename: Optional[str] = None
    has_analysis: bool


class ProjectListResponse(BaseModel):
    projects: List[ProjectResponse]


class ActionResponse(BaseModel):
    status: str


class DeleteResponse(ActionResponse):
    project_id: int


class PreprocessStatusResponse(BaseModel):
    status: Literal["not_started", "running", "completed", "failed"]
    current_step: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


class AnalysisRequest(BaseModel):
    personas: List[Literal["SDE", "PM"]] = Field(default_factory=lambda: ["SDE", "PM"], min_length=1)
    depth: Literal["quick", "standard", "deep"] = "standard"
    verbosity: Literal["low", "medium", "high"] = "medium"


class AnalysisStartResponse(ActionResponse):
    config: AnalysisRequest


class AnalysisStatusResponse(BaseModel):
    status: Literal["not_started", "running", "completed", "failed"]
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    current_activity: Optional[str] = None
    logs: List[str] = Field(default_factory=list)
    agent_insights: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None


class AnalysisResultResponse(BaseModel):
    result: dict[str, Any]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)


class ChatResponse(BaseModel):
    answer: str
    sources: List[str]
    time: float
    has_analysis: bool
    using_partial: bool
