"""Store Firestore — source de verite durable (Doc 08 §16, Doc 09 §7).

Structure :
  /missions/{mission_id}
  /missions/{mission_id}/tasks|events|checkpoints|recoveries|approvals|memory|audit|executions|policies
  /agents/{agent_id}
  /idempotency/{key}
  /security_events/{id}

Per-mission isolation "by construction": one mission's memory cannot be read
from another without changing path (Doc 04 §20).
"""
from __future__ import annotations

from typing import Any, TypeVar

from domain.enums import TaskStatus
from domain.errors import StateVersionConflict
from domain.models import (
    ACCModel,
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

T = TypeVar("T", bound=ACCModel)

MISSIONS = "missions"
AGENTS = "agents"
IDEMPOTENCY = "idempotency"
SECURITY = "security_events"


class FirestoreStore:
    def __init__(self, project: str, database: str = "(default)") -> None:
        from google.cloud import firestore  # late import: optional locally

        self._fs = firestore
        self.db = firestore.AsyncClient(project=project or None, database=database)

    # --- Helpers -----------------------------------------------------------
    def _mission_doc(self, mission_id: str):
        return self.db.collection(MISSIONS).document(mission_id)

    def _sub(self, mission_id: str, name: str):
        return self._mission_doc(mission_id).collection(name)

    @staticmethod
    def _load(model: type[T], data: dict[str, Any] | None) -> T | None:
        return model.model_validate(data) if data else None

    async def _list(self, ref, model: type[T], order: str | None = None, limit: int = 500) -> list[T]:
        query = ref
        if order:
            query = query.order_by(order)
        query = query.limit(limit)
        return [model.model_validate(doc.to_dict()) async for doc in query.stream()]

    # --- Missions ----------------------------------------------------------
    async def save_mission(self, mission: Mission) -> Mission:
        mission.updated_at = utcnow()
        await self._mission_doc(mission.mission_id).set(mission.to_doc())
        return mission

    async def get_mission(self, mission_id: str) -> Mission | None:
        snap = await self._mission_doc(mission_id).get()
        return self._load(Mission, snap.to_dict() if snap.exists else None)

    async def list_missions(self, status: str | None = None, limit: int = 50) -> list[Mission]:
        query = self.db.collection(MISSIONS)
        if status:
            query = query.where(filter=self._fs.FieldFilter("status", "==", status))
        query = query.order_by("created_at", direction=self._fs.Query.DESCENDING).limit(limit)
        return [Mission.model_validate(d.to_dict()) async for d in query.stream()]

    async def update_mission(self, mission: Mission, expected_version: int) -> Mission:
        """Transaction with version checking (Doc 08 §28)."""
        ref = self._mission_doc(mission.mission_id)
        transaction = self.db.transaction()

        @self._fs.async_transactional
        async def _txn(txn) -> Mission:
            snap = await ref.get(transaction=txn)
            if snap.exists:
                current = snap.to_dict().get("version", 1)
                if current != expected_version:
                    raise StateVersionConflict(
                        "Etat de mission obsolete, rechargez avant d'ecrire",
                        mission_id=mission.mission_id,
                        expected=expected_version, actual=current,
                    )
            mission.version = expected_version + 1
            mission.updated_at = utcnow()
            txn.set(ref, mission.to_doc())
            return mission

        return await _txn(transaction)

    # --- Taches ------------------------------------------------------------
    async def save_task(self, task: Task) -> Task:
        task.updated_at = utcnow()
        await self._sub(task.mission_id, "tasks").document(task.task_id).set(task.to_doc())
        return task

    async def get_task(self, mission_id: str, task_id: str) -> Task | None:
        snap = await self._sub(mission_id, "tasks").document(task_id).get()
        return self._load(Task, snap.to_dict() if snap.exists else None)

    async def list_tasks(self, mission_id: str) -> list[Task]:
        return await self._list(self._sub(mission_id, "tasks"), Task, order="order")

    async def claim_task(
        self, mission_id: str, task_id: str, expected: set[str], owner: str
    ) -> Task | None:
        """Atomic transactional claim (Pub/Sub delivers at least once).

        Unlike the in-memory store, Firestore returns a fresh copy on every
        read: without a transaction, two concurrent pushes would both read
        PENDING and run the task twice.
        """
        ref = self._sub(mission_id, "tasks").document(task_id)
        transaction = self.db.transaction()

        @self._fs.async_transactional
        async def _txn(txn) -> Task | None:
            snap = await ref.get(transaction=txn)
            if not snap.exists:
                return None
            task = Task.model_validate(snap.to_dict())
            if task.status.value not in expected:
                return None
            task.status = TaskStatus.RUNNING
            task.claimed_by = owner
            task.claimed_at = utcnow()
            task.updated_at = utcnow()
            txn.set(ref, task.to_doc())
            return task

        return await _txn(transaction)

    # --- Evenements --------------------------------------------------------
    async def append_event(self, event: MissionEvent) -> MissionEvent:
        await self._sub(event.mission_id, "events").document(event.event_id).set(event.to_doc())
        return event

    async def list_events(self, mission_id: str, limit: int = 500) -> list[MissionEvent]:
        return await self._list(self._sub(mission_id, "events"), MissionEvent,
                                order="timestamp", limit=limit)

    async def last_event_id(self, mission_id: str) -> str | None:
        query = (self._sub(mission_id, "events")
                 .order_by("timestamp", direction=self._fs.Query.DESCENDING).limit(1))
        async for doc in query.stream():
            return doc.to_dict().get("event_id")
        return None

    # --- Executions --------------------------------------------------------
    async def save_execution(self, execution: AgentExecution) -> AgentExecution:
        await (self._sub(execution.mission_id, "executions")
               .document(execution.execution_id).set(execution.to_doc()))
        return execution

    async def list_executions(self, mission_id: str) -> list[AgentExecution]:
        return await self._list(self._sub(mission_id, "executions"), AgentExecution,
                                order="started_at")

    # --- Checkpoints -------------------------------------------------------
    async def save_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        await (self._sub(checkpoint.mission_id, "checkpoints")
               .document(checkpoint.checkpoint_id).set(checkpoint.to_doc()))
        return checkpoint

    async def get_checkpoint(self, mission_id: str, checkpoint_id: str) -> Checkpoint | None:
        snap = await self._sub(mission_id, "checkpoints").document(checkpoint_id).get()
        return self._load(Checkpoint, snap.to_dict() if snap.exists else None)

    async def list_checkpoints(self, mission_id: str) -> list[Checkpoint]:
        return await self._list(self._sub(mission_id, "checkpoints"), Checkpoint,
                                order="created_at")

    # --- Recovery ----------------------------------------------------------
    async def save_recovery(self, recovery: RecoveryAttempt) -> RecoveryAttempt:
        await (self._sub(recovery.mission_id, "recoveries")
               .document(recovery.recovery_id).set(recovery.to_doc()))
        return recovery

    async def get_recovery(self, mission_id: str, recovery_id: str) -> RecoveryAttempt | None:
        snap = await self._sub(mission_id, "recoveries").document(recovery_id).get()
        return self._load(RecoveryAttempt, snap.to_dict() if snap.exists else None)

    async def list_recoveries(self, mission_id: str) -> list[RecoveryAttempt]:
        return await self._list(self._sub(mission_id, "recoveries"), RecoveryAttempt,
                                order="started_at")

    # --- Gouvernance -------------------------------------------------------
    async def save_policy_decision(self, decision: PolicyDecision) -> PolicyDecision:
        await (self._sub(decision.mission_id, "policies")
               .document(decision.policy_decision_id).set(decision.to_doc()))
        return decision

    async def list_policy_decisions(self, mission_id: str) -> list[PolicyDecision]:
        return await self._list(self._sub(mission_id, "policies"), PolicyDecision,
                                order="timestamp")

    async def save_approval(self, approval: Approval) -> Approval:
        await (self._sub(approval.mission_id, "approvals")
               .document(approval.approval_id).set(approval.to_doc()))
        # flat index for GET /approvals?status=PENDING
        await self.db.collection("approvals_index").document(approval.approval_id).set(
            {"approval_id": approval.approval_id, "mission_id": approval.mission_id,
             "status": approval.status.value, "requested_at": approval.requested_at.isoformat()}
        )
        return approval

    async def get_approval(self, approval_id: str) -> Approval | None:
        snap = await self.db.collection("approvals_index").document(approval_id).get()
        if not snap.exists:
            return None
        mission_id = snap.to_dict()["mission_id"]
        doc = await self._sub(mission_id, "approvals").document(approval_id).get()
        return self._load(Approval, doc.to_dict() if doc.exists else None)

    async def list_approvals(
        self, mission_id: str | None = None, status: str | None = None
    ) -> list[Approval]:
        if mission_id:
            items = await self._list(self._sub(mission_id, "approvals"), Approval,
                                     order="requested_at")
            return [a for a in items if not status or a.status.value == status]
        query = self.db.collection("approvals_index")
        if status:
            query = query.where(filter=self._fs.FieldFilter("status", "==", status))
        out: list[Approval] = []
        async for doc in query.limit(100).stream():
            approval = await self.get_approval(doc.to_dict()["approval_id"])
            if approval:
                out.append(approval)
        return out

    # --- Memoire / audit ---------------------------------------------------
    async def save_memory(self, entry: MemoryEntry) -> MemoryEntry:
        await self._sub(entry.mission_id, "memory").document(entry.memory_id).set(entry.to_doc())
        return entry

    async def list_memory(self, mission_id: str) -> list[MemoryEntry]:
        return await self._list(self._sub(mission_id, "memory"), MemoryEntry, order="created_at")

    async def save_audit(self, event: AuditEvent) -> AuditEvent:
        await self._sub(event.mission_id, "audit").document(event.audit_id).set(event.to_doc())
        return event

    async def list_audit(self, mission_id: str) -> list[AuditEvent]:
        return await self._list(self._sub(mission_id, "audit"), AuditEvent, order="timestamp")

    async def save_security_event(self, event: SecurityEvent) -> SecurityEvent:
        await self.db.collection(SECURITY).document(event.security_event_id).set(event.to_doc())
        return event

    async def list_security_events(self, mission_id: str | None = None) -> list[SecurityEvent]:
        query = self.db.collection(SECURITY)
        if mission_id:
            query = query.where(filter=self._fs.FieldFilter("mission_id", "==", mission_id))
        return [SecurityEvent.model_validate(d.to_dict()) async for d in query.limit(200).stream()]

    # --- Registre ----------------------------------------------------------
    async def save_agent(self, agent: AgentRecord) -> AgentRecord:
        agent.updated_at = utcnow()
        await self.db.collection(AGENTS).document(agent.agent_id).set(agent.to_doc())
        return agent

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        snap = await self.db.collection(AGENTS).document(agent_id).get()
        return self._load(AgentRecord, snap.to_dict() if snap.exists else None)

    async def list_agents(self) -> list[AgentRecord]:
        return [AgentRecord.model_validate(d.to_dict())
                async for d in self.db.collection(AGENTS).stream()]

    # --- Idempotence -------------------------------------------------------
    async def get_idempotent(self, key: str) -> dict[str, Any] | None:
        snap = await self.db.collection(IDEMPOTENCY).document(key).get()
        return snap.to_dict() if snap.exists else None

    async def put_idempotent(self, key: str, value: dict[str, Any]) -> None:
        await self.db.collection(IDEMPOTENCY).document(key).set(value)

    async def reset(self) -> None:
        """Deliberately inert outside demo mode: production is never purged."""
        raise NotImplementedError("reset() est reserve au store memoire / mode demo")
