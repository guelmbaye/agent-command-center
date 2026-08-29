"""Schemas d'API du Control Plane (Doc 08 §17-31)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from domain.enums import Priority


class CreateMissionRequest(BaseModel):
    objective: str = Field(default="Protect production schedule")
    priority: Priority = Priority.HIGH
    template: str = "protect-production"
    deadline_hours: int | None = None
    required_units: int | None = None
    autostart: bool = True


class CreateMissionResponse(BaseModel):
    mission_id: str
    status: str
    objective: str


class MissionSummary(BaseModel):
    mission_id: str
    objective: str
    status: str
    health: str
    progress: int
    priority: str
    risk_level: str
    current_stage: str
    active_task_id: str | None = None
    active_agent_id: str | None = None
    checkpoint_id: str | None = None
    approval_status: str | None = None
    pending_approval_id: str | None = None
    version: int
    trace_id: str | None = None
    created_at: str
    updated_at: str


class MissionDetail(MissionSummary):
    context: dict[str, Any]
    tasks: list[dict[str, Any]]
    latest_checkpoint: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None


class ApprovalDecisionRequest(BaseModel):
    comment: str | None = None
    decided_by: str = "operator"


class ResumeRequest(BaseModel):
    checkpoint_id: str | None = None


class DemoScenarioResponse(BaseModel):
    scenario: str
    enabled: bool
    detail: str = ""
    mission_id: str | None = None
