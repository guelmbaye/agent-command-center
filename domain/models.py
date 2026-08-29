"""ACC entities (Doc 08 §2-15). Pydantic v2, serialisable to Firestore/JSON.

Principle: "Mission state is the source of truth. Agents produce decisions;
the platform records and governs them."
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain import ids
from domain.enums import (
    AgentExecutionStatus,
    AgentResultStatus,
    AgentStatus,
    ApprovalStatus,
    AuthorityLevel,
    EventType,
    FailureClass,
    MemoryType,
    MissionHealth,
    MissionStatus,
    PolicyDecisionValue,
    Priority,
    RecoveryStatus,
    RecoveryStrategy,
    RiskLevel,
    SecurityEventType,
    Sensitivity,
    TaskStatus,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ACCModel(BaseModel):
    model_config = ConfigDict(use_enum_values=False, validate_assignment=False)

    def to_doc(self) -> dict[str, Any]:
        """Persistable representation (Firestore / JSON)."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Identity (Doc 02 §9, Doc 03 §3) — propagated across the whole execution chain
# ---------------------------------------------------------------------------
class AgentIdentity(ACCModel):
    agent_id: str
    agent_version: str
    execution_id: str
    mission_id: str
    task_id: str | None = None
    service_identity: str = "acc/agents/unknown"
    authority_level: AuthorityLevel = AuthorityLevel.SUPERVISED

    @property
    def principal(self) -> str:
        return f"{self.agent_id}:v{self.agent_version}"


# ---------------------------------------------------------------------------
# Agent registry (Doc 02 §7)
# ---------------------------------------------------------------------------
class AgentRecord(ACCModel):
    agent_id: str
    name: str
    version: str = "1.0.0"
    status: AgentStatus = AgentStatus.REGISTERED
    risk_level: RiskLevel = RiskLevel.LOW
    capabilities: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    denied_capabilities: list[str] = Field(default_factory=list)
    authority_level: AuthorityLevel = AuthorityLevel.SUPERVISED
    runtime: str = "google-adk"
    model: str | None = None
    description: str = ""
    service_identity: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def has_capability(self, capability: str) -> bool:
        if capability in self.denied_capabilities:
            return False
        return capability in self.capabilities


# ---------------------------------------------------------------------------
# Mission (Doc 08 §3)
# ---------------------------------------------------------------------------
class MissionContext(ACCModel):
    """Durable business facts of the mission — never rebuilt by an agent."""
    deadline_hours: int = 48
    required_units: int = 1200
    primary_supplier: str = "SUP-A"
    fallback_suppliers: list[str] = Field(default_factory=lambda: ["SUP-B", "SUP-C"])
    selected_supplier: str | None = None
    unit_price: float | None = None
    purchase_amount: float | None = None
    purchase_id: str | None = None
    constraints: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Mission(ACCModel):
    mission_id: str = Field(default_factory=ids.mission_id)
    objective: str
    status: MissionStatus = MissionStatus.CREATED
    priority: Priority = Priority.HIGH
    risk_level: RiskLevel = RiskLevel.LOW
    current_stage: str = "created"
    active_task_id: str | None = None
    active_agent_id: str | None = None
    checkpoint_id: str | None = None
    approval_status: ApprovalStatus | None = None
    pending_approval_id: str | None = None
    progress: int = 0
    version: int = 1  # optimistic concurrency (Doc 08 §28)
    context: MissionContext = Field(default_factory=MissionContext)
    trace_id: str = Field(default_factory=ids.trace_id)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None

    @property
    def health(self) -> MissionHealth:
        mapping = {
            MissionStatus.AT_RISK: MissionHealth.AT_RISK,
            MissionStatus.RECOVERING: MissionHealth.RECOVERING,
            MissionStatus.WAITING_APPROVAL: MissionHealth.DEGRADED,
            MissionStatus.FAILED: MissionHealth.FAILED,
            MissionStatus.ABORTED: MissionHealth.FAILED,
            MissionStatus.COMPLETED: MissionHealth.COMPLETED,
        }
        return mapping.get(self.status, MissionHealth.HEALTHY)


class Task(ACCModel):
    task_id: str = Field(default_factory=ids.task_id)
    mission_id: str
    type: str
    title: str = ""
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent: str | None = None
    attempt: int = 1
    max_attempts: int = 3
    priority: Priority = Priority.HIGH
    depends_on: list[str] = Field(default_factory=list)
    order: int = 0
    injected_by_recovery: str | None = None
    # Task claim: which worker owns the execution (Pub/Sub at-least-once)
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Agent execution and result (Doc 08 §6-7)
# ---------------------------------------------------------------------------
class AgentResult(ACCModel):
    """Single output contract — avoids natural-language chaining."""
    status: AgentResultStatus = AgentResultStatus.SUCCESS
    finding: str = ""
    recommendation: str | None = None
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    next_action: str | None = None
    requires_approval: bool = False
    failure_class: FailureClass | None = None
    failure_detail: str | None = None


class AgentExecution(ACCModel):
    execution_id: str = Field(default_factory=ids.execution_id)
    mission_id: str
    task_id: str
    agent_id: str
    agent_version: str
    status: AgentExecutionStatus = AgentExecutionStatus.RUNNING
    attempt: int = 1
    runtime: str = "google-adk"
    model: str | None = None
    result: AgentResult | None = None
    trace_id: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    duration_ms: int | None = None


# ---------------------------------------------------------------------------
# Events (Doc 08 §8) + integrity chaining (Doc 04 §13)
# ---------------------------------------------------------------------------
class MissionEvent(ACCModel):
    event_id: str = Field(default_factory=ids.event_id)
    mission_id: str
    type: EventType
    source: str = "mission-engine"
    actor: str | None = None
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    previous_event_id: str | None = None
    trace_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Checkpoint (Doc 08 §9) — enough to resume, never the raw transcript
# ---------------------------------------------------------------------------
class Checkpoint(ACCModel):
    checkpoint_id: str = Field(default_factory=ids.checkpoint_id)
    mission_id: str
    mission_version: int
    label: str = ""
    current_stage: str = ""
    mission_status: MissionStatus = MissionStatus.EXECUTING
    completed_tasks: list[str] = Field(default_factory=list)
    active_task_id: str | None = None
    approval_status: ApprovalStatus | None = None
    recovery_status: RecoveryStatus | None = None
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    policy_state: dict[str, Any] = Field(default_factory=dict)
    agent_state_reference: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Recovery (Doc 08 §10)
# ---------------------------------------------------------------------------
class RecoveryOption(ACCModel):
    strategy: RecoveryStrategy
    label: str
    rationale: str = ""
    estimated_risk: RiskLevel = RiskLevel.MEDIUM
    estimated_delay_hours: float = 0.0
    permitted: bool = True
    denial_reason: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class RecoveryPlan(ACCModel):
    """Failure Twin output — then goes through normal governance."""
    diagnosis: str
    impact: RiskLevel = RiskLevel.HIGH
    options: list[RecoveryOption] = Field(default_factory=list)
    selected_strategy: RecoveryStrategy = RecoveryStrategy.ESCALATE
    selected_parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    requires_approval: bool = False
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class RecoveryAttempt(ACCModel):
    recovery_id: str = Field(default_factory=ids.recovery_id)
    mission_id: str
    failure_event_id: str | None = None
    failed_component: str = ""
    failure_class: FailureClass = FailureClass.UNKNOWN
    diagnosis: str = ""
    impact: RiskLevel = RiskLevel.HIGH
    options: list[RecoveryOption] = Field(default_factory=list)
    selected_option: RecoveryStrategy | None = None
    selected_parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    policy_decision_id: str | None = None
    approval_id: str | None = None
    status: RecoveryStatus = RecoveryStatus.IN_PROGRESS
    attempt: int = 1
    trace_id: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None

    @property
    def duration_s(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# Governance (Doc 08 §11-12)
# ---------------------------------------------------------------------------
class PolicyDecision(ACCModel):
    policy_decision_id: str = Field(default_factory=ids.policy_decision_id)
    mission_id: str
    agent_id: str
    action: str
    resource: str | None = None
    decision: PolicyDecisionValue
    reason: str = ""
    rule_id: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    amount: float | None = None
    trace_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)


class Approval(ACCModel):
    approval_id: str = Field(default_factory=ids.approval_id)
    mission_id: str
    task_id: str | None = None
    agent_id: str
    action: str
    resource: str | None = None
    amount: float | None = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    status: ApprovalStatus = ApprovalStatus.PENDING
    policy_decision_id: str | None = None
    idempotency_key: str | None = None
    requested_by: str = "mission-engine"
    decided_by: str | None = None
    comment: str | None = None
    trace_id: str | None = None
    requested_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None
    expires_at: datetime | None = None

    @property
    def latency_s(self) -> float | None:
        if self.decided_at is None:
            return None
        return (self.decided_at - self.requested_at).total_seconds()


# ---------------------------------------------------------------------------
# Mission memory (Doc 08 §13) — structured, scoped, non-rewritable
# ---------------------------------------------------------------------------
class MemoryEntry(ACCModel):
    memory_id: str = Field(default_factory=ids.memory_id)
    mission_id: str
    type: MemoryType
    content: dict[str, Any] = Field(default_factory=dict)
    source: str = "mission-engine"
    created_by: str = "mission-engine"
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Audit and security (Doc 08 §14, Doc 03 §17-18)
# ---------------------------------------------------------------------------
class AuditEvent(ACCModel):
    audit_id: str = Field(default_factory=ids.audit_id)
    mission_id: str
    execution_id: str | None = None
    agent_id: str
    agent_version: str | None = None
    action: str
    target: str | None = None
    policy_decision: PolicyDecisionValue | None = None
    policy_decision_id: str | None = None
    approval_id: str | None = None
    result: str = "SUCCESS"
    detail: str = ""
    trace_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)


class SecurityEvent(ACCModel):
    security_event_id: str = Field(default_factory=ids.audit_id)
    mission_id: str | None = None
    type: SecurityEventType
    agent_id: str | None = None
    action: str | None = None
    severity: RiskLevel = RiskLevel.MEDIUM
    detail: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Tool execution contract (Doc 08 §25)
# ---------------------------------------------------------------------------
class ToolAction(ACCModel):
    action_id: str = Field(default_factory=ids.action_id)
    mission_id: str
    task_id: str | None = None
    agent_id: str
    capability: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class ToolActionResult(ACCModel):
    action_id: str
    status: str  # SUCCESS | APPROVAL_REQUIRED | DENIED | BLOCKED | FAILED
    result: dict[str, Any] = Field(default_factory=dict)
    policy_decision_id: str | None = None
    approval_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    replayed: bool = False
    trace_id: str | None = None
