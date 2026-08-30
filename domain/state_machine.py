"""Mission state machine (Doc 04 §4, Doc 07 §27, Doc 10 §5).

No implicit transition: the engine must go through `assert_transition`.
That is what makes resume-after-interruption deterministic and auditable.
"""
from __future__ import annotations

from domain.enums import AgentStatus, MissionStatus, TaskStatus
from domain.errors import InvalidState

S = MissionStatus

MISSION_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
    S.CREATED: {S.PLANNING, S.EXECUTING, S.ABORTED, S.FAILED},
    S.PLANNING: {S.EXECUTING, S.FAILED, S.ABORTED},
    S.EXECUTING: {S.EXECUTING, S.AT_RISK, S.WAITING_APPROVAL, S.COMPLETED, S.FAILED, S.ABORTED},
    S.AT_RISK: {S.RECOVERING, S.EXECUTING, S.FAILED, S.ABORTED},
    S.RECOVERING: {S.EXECUTING, S.WAITING_APPROVAL, S.RECOVERING, S.AT_RISK, S.FAILED, S.ABORTED},
    S.WAITING_APPROVAL: {S.EXECUTING, S.RECOVERING, S.AT_RISK, S.FAILED, S.ABORTED},
    S.COMPLETED: set(),
    S.FAILED: set(),
    S.ABORTED: set(),
}

TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.FAILED},
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.WAITING, TaskStatus.BLOCKED,
    },
    TaskStatus.WAITING: {TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.FAILED: {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.COMPLETED},
    TaskStatus.BLOCKED: {TaskStatus.PENDING, TaskStatus.FAILED},
    TaskStatus.COMPLETED: set(),
}

# Doc 02 §8: an agent never moves silently from FAILED to EXECUTING.
AGENT_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
    AgentStatus.REGISTERED: {AgentStatus.VALIDATED, AgentStatus.REVOKED},
    AgentStatus.VALIDATED: {AgentStatus.APPROVED, AgentStatus.SUSPENDED, AgentStatus.REVOKED},
    AgentStatus.APPROVED: {AgentStatus.AVAILABLE, AgentStatus.SUSPENDED, AgentStatus.REVOKED},
    AgentStatus.AVAILABLE: {
        AgentStatus.BUSY, AgentStatus.DEGRADED, AgentStatus.FAILED,
        AgentStatus.SUSPENDED, AgentStatus.REVOKED,
    },
    AgentStatus.BUSY: {
        AgentStatus.AVAILABLE, AgentStatus.DEGRADED, AgentStatus.FAILED, AgentStatus.SUSPENDED,
    },
    AgentStatus.DEGRADED: {AgentStatus.RECOVERING, AgentStatus.AVAILABLE, AgentStatus.FAILED},
    AgentStatus.FAILED: {AgentStatus.RECOVERING, AgentStatus.SUSPENDED, AgentStatus.REVOKED},
    AgentStatus.RECOVERING: {AgentStatus.AVAILABLE, AgentStatus.FAILED, AgentStatus.SUSPENDED},
    AgentStatus.SUSPENDED: {AgentStatus.AVAILABLE, AgentStatus.REVOKED},
    AgentStatus.REVOKED: set(),
}


def can_transition(current: MissionStatus, target: MissionStatus) -> bool:
    return target in MISSION_TRANSITIONS.get(current, set())


def assert_transition(current: MissionStatus, target: MissionStatus, mission_id: str = "") -> None:
    if not can_transition(current, target):
        raise InvalidState(
            f"Forbidden mission transition {current.value} -> {target.value}",
            mission_id=mission_id, current=current.value, target=target.value,
        )


def assert_task_transition(current: TaskStatus, target: TaskStatus, task_id: str = "") -> None:
    if target not in TASK_TRANSITIONS.get(current, set()):
        raise InvalidState(
            f"Forbidden task transition {current.value} -> {target.value}",
            task_id=task_id, current=current.value, target=target.value,
        )


def assert_agent_transition(current: AgentStatus, target: AgentStatus, agent_id: str = "") -> None:
    if target not in AGENT_TRANSITIONS.get(current, set()):
        raise InvalidState(
            f"Forbidden agent transition {current.value} -> {target.value}",
            agent_id=agent_id, current=current.value, target=target.value,
        )


# Critical transitions explicitly covered by tests (Doc 07 §27)
CRITICAL_TRANSITIONS = [
    (S.EXECUTING, S.AT_RISK),
    (S.AT_RISK, S.RECOVERING),
    (S.RECOVERING, S.WAITING_APPROVAL),
    (S.WAITING_APPROVAL, S.RECOVERING),
    (S.RECOVERING, S.EXECUTING),
    (S.EXECUTING, S.COMPLETED),
    (S.RECOVERING, S.FAILED),
]
