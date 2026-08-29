"""In-memory store — local, tests, and demo safety net (Level B, Doc 06 §22)."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from domain.enums import TaskStatus
from domain.errors import StateVersionConflict
from domain.models import (
    AgentExecution,
    AgentRecord,
    Approval,
    AuditEvent,
    Checkpoint,
    MemoryEntry,
    Mission,
    MissionEvent,
    PolicyDecision,
    RecoveryAttempt,
    SecurityEvent,
    Task,
    utcnow,
)


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._missions: dict[str, Mission] = {}
        self._tasks: dict[str, dict[str, Task]] = defaultdict(dict)
        self._events: dict[str, list[MissionEvent]] = defaultdict(list)
        self._executions: dict[str, list[AgentExecution]] = defaultdict(list)
        self._checkpoints: dict[str, list[Checkpoint]] = defaultdict(list)
        self._recoveries: dict[str, list[RecoveryAttempt]] = defaultdict(list)
        self._policies: dict[str, list[PolicyDecision]] = defaultdict(list)
        self._approvals: dict[str, Approval] = {}
        self._memory: dict[str, list[MemoryEntry]] = defaultdict(list)
        self._audit: dict[str, list[AuditEvent]] = defaultdict(list)
        self._security: list[SecurityEvent] = []
        self._agents: dict[str, AgentRecord] = {}
        self._idempotency: dict[str, dict[str, Any]] = {}

    # --- Missions ----------------------------------------------------------
    async def save_mission(self, mission: Mission) -> Mission:
        mission.updated_at = utcnow()
        self._missions[mission.mission_id] = mission
        return mission

    async def get_mission(self, mission_id: str) -> Mission | None:
        return self._missions.get(mission_id)

    async def list_missions(self, status: str | None = None, limit: int = 50) -> list[Mission]:
        items = sorted(self._missions.values(), key=lambda m: m.created_at, reverse=True)
        if status:
            items = [m for m in items if m.status.value == status]
        return items[:limit]

    async def update_mission(self, mission: Mission, expected_version: int) -> Mission:
        """Optimistic concurrency (Doc 08 §28): rejects a stale write."""
        async with self._lock:
            stored = self._missions.get(mission.mission_id)
            if stored is not None and stored.version != expected_version:
                raise StateVersionConflict(
                    "Etat de mission obsolete, rechargez avant d'ecrire",
                    mission_id=mission.mission_id,
                    expected=expected_version,
                    actual=stored.version,
                )
            mission.version = expected_version + 1
            mission.updated_at = utcnow()
            self._missions[mission.mission_id] = mission
            return mission

    # --- Taches ------------------------------------------------------------
    async def save_task(self, task: Task) -> Task:
        task.updated_at = utcnow()
        self._tasks[task.mission_id][task.task_id] = task
        return task

    async def get_task(self, mission_id: str, task_id: str) -> Task | None:
        return self._tasks[mission_id].get(task_id)

    async def list_tasks(self, mission_id: str) -> list[Task]:
        return sorted(self._tasks[mission_id].values(), key=lambda t: (t.order, t.created_at))

    async def claim_task(
        self, mission_id: str, task_id: str, expected: set[str], owner: str
    ) -> Task | None:
        """Atomic claim: only one worker can move a task to RUNNING.

        Pub/Sub guarantees *at least* once delivery. Without this claim, two
        concurrent pushes of the same event would run the task twice.
        """
        async with self._lock:
            task = self._tasks[mission_id].get(task_id)
            if task is None or task.status.value not in expected:
                return None
            task.status = TaskStatus.RUNNING
            task.claimed_by = owner
            task.claimed_at = utcnow()
            task.updated_at = utcnow()
            return task

    # --- Evenements --------------------------------------------------------
    async def append_event(self, event: MissionEvent) -> MissionEvent:
        self._events[event.mission_id].append(event)
        return event

    async def list_events(self, mission_id: str, limit: int = 500) -> list[MissionEvent]:
        return self._events[mission_id][:limit]

    async def last_event_id(self, mission_id: str) -> str | None:
        events = self._events[mission_id]
        return events[-1].event_id if events else None

    # --- Executions --------------------------------------------------------
    async def save_execution(self, execution: AgentExecution) -> AgentExecution:
        bucket = self._executions[execution.mission_id]
        for i, existing in enumerate(bucket):
            if existing.execution_id == execution.execution_id:
                bucket[i] = execution
                return execution
        bucket.append(execution)
        return execution

    async def list_executions(self, mission_id: str) -> list[AgentExecution]:
        return list(self._executions[mission_id])

    # --- Checkpoints -------------------------------------------------------
    async def save_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        self._checkpoints[checkpoint.mission_id].append(checkpoint)
        return checkpoint

    async def get_checkpoint(self, mission_id: str, checkpoint_id: str) -> Checkpoint | None:
        return next(
            (c for c in self._checkpoints[mission_id] if c.checkpoint_id == checkpoint_id), None
        )

    async def list_checkpoints(self, mission_id: str) -> list[Checkpoint]:
        return list(self._checkpoints[mission_id])

    # --- Recovery ----------------------------------------------------------
    async def save_recovery(self, recovery: RecoveryAttempt) -> RecoveryAttempt:
        bucket = self._recoveries[recovery.mission_id]
        for i, existing in enumerate(bucket):
            if existing.recovery_id == recovery.recovery_id:
                bucket[i] = recovery
                return recovery
        bucket.append(recovery)
        return recovery

    async def get_recovery(self, mission_id: str, recovery_id: str) -> RecoveryAttempt | None:
        return next(
            (r for r in self._recoveries[mission_id] if r.recovery_id == recovery_id), None
        )

    async def list_recoveries(self, mission_id: str) -> list[RecoveryAttempt]:
        return list(self._recoveries[mission_id])

    # --- Gouvernance -------------------------------------------------------
    async def save_policy_decision(self, decision: PolicyDecision) -> PolicyDecision:
        self._policies[decision.mission_id].append(decision)
        return decision

    async def list_policy_decisions(self, mission_id: str) -> list[PolicyDecision]:
        return list(self._policies[mission_id])

    async def save_approval(self, approval: Approval) -> Approval:
        self._approvals[approval.approval_id] = approval
        return approval

    async def get_approval(self, approval_id: str) -> Approval | None:
        return self._approvals.get(approval_id)

    async def list_approvals(
        self, mission_id: str | None = None, status: str | None = None
    ) -> list[Approval]:
        items = sorted(self._approvals.values(), key=lambda a: a.requested_at, reverse=True)
        if mission_id:
            items = [a for a in items if a.mission_id == mission_id]
        if status:
            items = [a for a in items if a.status.value == status]
        return items

    # --- Memoire / audit ---------------------------------------------------
    async def save_memory(self, entry: MemoryEntry) -> MemoryEntry:
        self._memory[entry.mission_id].append(entry)
        return entry

    async def list_memory(self, mission_id: str) -> list[MemoryEntry]:
        return list(self._memory[mission_id])

    async def save_audit(self, event: AuditEvent) -> AuditEvent:
        self._audit[event.mission_id].append(event)
        return event

    async def list_audit(self, mission_id: str) -> list[AuditEvent]:
        return list(self._audit[mission_id])

    async def save_security_event(self, event: SecurityEvent) -> SecurityEvent:
        self._security.append(event)
        return event

    async def list_security_events(self, mission_id: str | None = None) -> list[SecurityEvent]:
        if mission_id:
            return [e for e in self._security if e.mission_id == mission_id]
        return list(self._security)

    # --- Registre ----------------------------------------------------------
    async def save_agent(self, agent: AgentRecord) -> AgentRecord:
        agent.updated_at = utcnow()
        self._agents[agent.agent_id] = agent
        return agent

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self._agents.get(agent_id)

    async def list_agents(self) -> list[AgentRecord]:
        return list(self._agents.values())

    # --- Idempotence -------------------------------------------------------
    async def get_idempotent(self, key: str) -> dict[str, Any] | None:
        return self._idempotency.get(key)

    async def put_idempotent(self, key: str, value: dict[str, Any]) -> None:
        self._idempotency[key] = value

    async def reset(self) -> None:
        agents = dict(self._agents)
        self.__init__()  # type: ignore[misc]
        self._agents = agents
