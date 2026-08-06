from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

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


class AnalysisRequest(BaseModel):
    personas: List[Literal["SDE", "PM"]] = Field(default_factory=lambda: ["SDE", "PM"], min_length=1)
    depth: Literal["quick", "standard", "deep"] = "standard"
    verbosity: Literal["low", "medium", "high"] = "medium"


RunType = Literal["preprocessing", "analysis"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class RunStartResponse(BaseModel):
    run_id: UUID
    project_id: int
    run_type: RunType
    status: Literal["queued"]
    configuration: Dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    run_id: UUID
    project_id: int
    run_type: RunType
    status: RunStatus
    progress: int = Field(ge=0, le=100)
    current_activity: Optional[str] = None
    error_message: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)
    logs: List[str] = Field(default_factory=list)
    agent_insights: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime


class RunListResponse(BaseModel):
    runs: List[RunResponse]


class LatestRunStatusResponse(BaseModel):
    run_id: Optional[UUID] = None
    project_id: int
    run_type: RunType
    status: Literal["not_started", "queued", "running", "completed", "failed", "cancelled"]
    progress: int = Field(default=0, ge=0, le=100)
    current_activity: Optional[str] = None
    current_step: Optional[str] = None
    error_message: Optional[str] = None
    error: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)
    logs: List[str] = Field(default_factory=list)
    agent_insights: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LatestRunsResponse(BaseModel):
    preprocessing: Optional[RunResponse] = None
    analysis: Optional[RunResponse] = None


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
