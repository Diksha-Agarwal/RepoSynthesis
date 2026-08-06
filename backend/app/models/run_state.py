"""
Analysis Run State Management
Similar to ChatGPT Research - long-running sessions with pause/resume
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import uuid


class RunStatus(str, Enum):
    """Analysis run status."""
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentStep(BaseModel):
    """Individual agent execution step."""
    agent_name: str
    status: str  # "pending", "running", "completed", "failed"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AnalysisRun(BaseModel):
    """
    Represents a single analysis run session.
    
    Like ChatGPT Research, this tracks:
    - Long-running analysis state
    - Current progress
    - Intermediate outputs
    - User instructions/context
    """
    
    # Run identification
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    
    # Status tracking
    status: RunStatus = RunStatus.RUNNING
    current_step: int = 0
    total_steps: int = 6  # Coordinator, Semantic, BP, SDE, PM, QA
    progress_percent: float = 0.0
    
    # Timestamps
    started_at: datetime = Field(default_factory=datetime.now)
    paused_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Agent pipeline
    steps: List[AgentStep] = Field(default_factory=lambda: [
        AgentStep(agent_name="coordinator_agent", status="pending"),
        AgentStep(agent_name="semantic_query_agent", status="pending"),
        AgentStep(agent_name="best_practice_agent", status="pending"),
        AgentStep(agent_name="sde_writer_agent", status="pending"),
        AgentStep(agent_name="pm_writer_agent", status="pending"),
        AgentStep(agent_name="qa_agent", status="pending"),
    ])
    
    # Intermediate outputs
    intermediate_outputs: Dict[str, Any] = Field(default_factory=dict)
    
    # User interaction
    user_instructions: List[str] = Field(default_factory=list)
    user_questions: List[Dict[str, str]] = Field(default_factory=list)  # {question, answer, timestamp}
    
    # Team state (for save/load)
    team_state: Optional[Dict[str, Any]] = None
    message_thread: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Configuration
    config: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    
    def get_current_agent(self) -> Optional[str]:
        """Get the name of the currently executing agent."""
        if self.current_step < len(self.steps):
            return self.steps[self.current_step].agent_name
        return None
    
    def mark_step_running(self, step_index: int):
        """Mark a step as currently running."""
        self.steps[step_index].status = "running"
        self.steps[step_index].started_at = datetime.now()
        self.current_step = step_index
        self.progress_percent = (step_index / self.total_steps) * 100
    
    def mark_step_completed(self, step_index: int, output: Dict[str, Any]):
        """Mark a step as completed."""
        self.steps[step_index].status = "completed"
        self.steps[step_index].completed_at = datetime.now()
        self.steps[step_index].output = output
        self.intermediate_outputs[self.steps[step_index].agent_name] = output
        self.progress_percent = ((step_index + 1) / self.total_steps) * 100
    
    def mark_step_failed(self, step_index: int, error: str):
        """Mark a step as failed."""
        self.steps[step_index].status = "failed"
        self.steps[step_index].completed_at = datetime.now()
        self.steps[step_index].error = error
    
    def pause(self):
        """Pause the run."""
        self.status = RunStatus.PAUSED
        self.paused_at = datetime.now()
    
    def resume(self):
        """Resume the run."""
        self.status = RunStatus.RUNNING
        self.paused_at = None
    
    def complete(self):
        """Mark run as completed."""
        self.status = RunStatus.COMPLETED
        self.completed_at = datetime.now()
        self.progress_percent = 100.0
    
    def add_user_instruction(self, instruction: str):
        """Add user instruction/context."""
        self.user_instructions.append(instruction)
    
    def add_user_question(self, question: str, answer: str):
        """Log a user question and answer."""
        self.user_questions.append({
            "question": question,
            "answer": answer,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the run state."""
        completed_steps = sum(1 for step in self.steps if step.status == "completed")
        
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "current_agent": self.get_current_agent(),
            "progress": f"{completed_steps}/{self.total_steps} steps",
            "progress_percent": round(self.progress_percent, 1),
            "user_instructions_count": len(self.user_instructions),
            "started_at": self.started_at.isoformat(),
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
