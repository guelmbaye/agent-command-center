"""ACC domain enumerations (Doc 08 §3-14)."""
from __future__ import annotations

from enum import Enum


class MissionStatus(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    AT_RISK = "AT_RISK"
    RECOVERING = "RECOVERING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_MISSION


_TERMINAL_MISSION = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.ABORTED}


class MissionHealth(str, Enum):
    """Modele d'affichage simple (Doc 05 §11) — derive du statut."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    AT_RISK = "AT_RISK"
    RECOVERING = "RECOVERING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class AgentStatus(str, Enum):
    """Fleet lifecycle (Doc 02 §8, §22)."""
    REGISTERED = "REGISTERED"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"

    @property
    def can_execute(self) -> bool:
        return self in {AgentStatus.AVAILABLE, AgentStatus.APPROVED, AgentStatus.BUSY}


class AuthorityLevel(str, Enum):
    """Autonomy boundary exposed as a product feature (Doc 03 §7)."""
    AUTONOMOUS = "AUTONOMOUS"
    SUPERVISED = "SUPERVISED"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    BLOCKED = "BLOCKED"


class PolicyDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AgentExecutionStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class AgentResultStatus(str, Enum):
    """Agent output contract (Doc 02 §15)."""
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    NON_RETRYABLE_FAILURE = "NON_RETRYABLE_FAILURE"
    BLOCKED = "BLOCKED"

    @property
    def is_failure(self) -> bool:
        return self in {
            AgentResultStatus.RETRYABLE_FAILURE,
            AgentResultStatus.NON_RETRYABLE_FAILURE,
            AgentResultStatus.BLOCKED,
        }


class FailureClass(str, Enum):
    """Deliberately small taxonomy (Doc 05 §17)."""
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    DEPENDENCY = "DEPENDENCY"
    AUTHORIZATION = "AUTHORIZATION"
    SECURITY = "SECURITY"
    AGENT = "AGENT"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"

    @property
    def retry_allowed(self) -> bool:
        return self in {FailureClass.TRANSIENT, FailureClass.TIMEOUT}

    @property
    def requires_safe_hold(self) -> bool:
        """Doc 03 §20: a security failure never triggers free recovery."""
        return self in {FailureClass.AUTHORIZATION, FailureClass.SECURITY}


class RecoveryStrategy(str, Enum):
    RETRY = "RETRY"
    SWITCH_AGENT = "SWITCH_AGENT"
    SWITCH_DATA_SOURCE = "SWITCH_DATA_SOURCE"
    USE_ALTERNATIVE_SUPPLIER = "USE_ALTERNATIVE_SUPPLIER"
    WAIT_AND_REASSESS = "WAIT_AND_REASSESS"
    ESCALATE = "ESCALATE"
    ABORT = "ABORT"


class RecoveryStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    HELD = "HELD"
    # Deliberate conclusion: nothing useful can be attempted. The recovery
    # worked; it is the situation that is a dead end. Confusing the two would
    # make a correct decision look like a malfunction.
    ABORTED = "ABORTED"


class Sensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventType(str, Enum):
    """Event vocabulary — short and stable (Doc 05 §4, Doc 08 §8)."""
    MISSION_CREATED = "mission.created"
    MISSION_STARTED = "mission.started"
    MISSION_AT_RISK = "mission.at_risk"
    MISSION_RESUMED = "mission.resumed"
    MISSION_COMPLETED = "mission.completed"
    MISSION_FAILED = "mission.failed"

    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"

    SUPPLIER_FAILED = "supplier.failed"
    TOOL_FAILED = "tool.failed"

    POLICY_CHECKED = "policy.checked"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RECEIVED = "approval.received"

    CHECKPOINT_CREATED = "checkpoint.created"

    RECOVERY_STARTED = "recovery.started"
    RECOVERY_SELECTED = "recovery.selected"
    RECOVERY_COMPLETED = "recovery.completed"
    RECOVERY_FAILED = "recovery.failed"

    RUNTIME_INTERRUPTED = "runtime.interrupted"
    MODEL_THREAT_DETECTED = "model.threat_detected"


class SecurityEventType(str, Enum):
    """Doc 03 §18."""
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    MODEL_THREAT_DETECTED = "MODEL_THREAT_DETECTED"
    TOOL_FAILURE = "TOOL_FAILURE"
    AGENT_FAILURE = "AGENT_FAILURE"
    MEMORY_ACCESS = "MEMORY_ACCESS"
    RECOVERY_EXECUTED = "RECOVERY_EXECUTED"


class MemoryType(str, Enum):
    DECISION = "decision"
    FINDING = "finding"
    CONSTRAINT = "constraint"
    FAILURE = "failure"
    RECOVERY = "recovery"
    APPROVAL = "approval"
    EVIDENCE = "evidence"
