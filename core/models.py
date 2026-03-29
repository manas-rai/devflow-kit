from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class WorkItem(BaseModel):
    """A unit of work originating from a project management tool (e.g., Jira epic/story)."""
    id: str = Field(description="Unique internal ID from the tracker")
    key: str = Field(description="Human-readable key (e.g., CWH-41)")
    title: str = Field(description="Title or summary of the ticket")
    description: str = Field(description="Raw description from the project tracker")
    status: str = Field(description="Current status (e.g., 'To Do', 'Ready for Dev')")
    item_type: str = Field(description="Type of work item (e.g., 'Story', 'Epic', 'Bug')")
    url: str = Field(description="Direct URL to view the item")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional tracker-specific data (assignee, reporter, story points, etc)")


class Spec(BaseModel):
    """A structured representation of intent and requirements inferred from WorkItems."""
    work_item_key: str = Field(description="The WorkItem key this Spec corresponds to")
    summary: str = Field(description="High-level goal extracted from the description")
    goals: List[str] = Field(default_factory=list, description="Primary business goals")
    acceptance_criteria: List[str] = Field(default_factory=list, description="Strict checkboxes required for validation")
    technical_constraints: List[str] = Field(default_factory=list, description="Explicit constraints (e.g., 'do not touch X', 'must use Y')")
    suggested_approach: Optional[str] = Field(default=None, description="Initial ideas for implementation")


class Task(BaseModel):
    """A granular unit of work decomposed from a larger Spec to be given to an agent."""
    id: str = Field(description="Unique task identifier")
    title: str = Field(description="Short human readable name")
    description: str = Field(description="Detailed instructions for the coding agent")
    target_repo: str = Field(description="Which repository this task belongs to")
    dependencies: List[str] = Field(default_factory=list, description="List of task IDs that must complete before this one")


class TaskGraph(BaseModel):
    """A directed acyclic graph of decomposed tasks derived from a Spec."""
    spec_id: str = Field(description="The source Spec")
    tasks: List[Task] = Field(default_factory=list, description="All granular tasks needed to fulfill the Spec")


class ChangePlan(BaseModel):
    """A proposed set of code changes for a specific task."""
    task_id: str = Field(description="The Task this ChangePlan fulfills")
    files_to_modify: List[str] = Field(default_factory=list, description="Existing files to edit")
    files_to_create: List[str] = Field(default_factory=list, description="Net-new files to define")
    step_by_step: List[str] = Field(default_factory=list, description="Sequential actions the codegen agent should take")


class VerificationResult(BaseModel):
    """Outputs from tests, linters, static/security scanners."""
    tool_name: str = Field(description="Tool that ran the verification (e.g., 'pytest', 'flake8', 'v&v-agent')")
    passed: bool = Field(description="Whether the verification succeeded")
    output: str = Field(description="Raw logs or stdout/stderr")
    errors: List[str] = Field(default_factory=list, description="Extracted error messages if failed")
    timestamp: datetime = Field(default_factory=datetime.now, description="When the check occurred")


class RiskAssessment(BaseModel):
    """Risk scoring heavily relying on LLM heuristic review of ChangePlan and CodeDeltas."""
    score: int = Field(description="1-10 risk score (10 = highest risk)")
    explanation: str = Field(description="Detailed breakdown of why this score was applied")
    requires_human_review: bool = Field(description="Whether this score exceeds the auto-merge threshold")
