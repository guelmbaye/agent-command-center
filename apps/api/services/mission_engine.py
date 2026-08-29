"""Mission Engine — "What should happen next?" (Doc 07 §4-5).

The engine is deterministic: it decides state, never the model.
It is driven by durable events, so no mission depends on the lifetime of an
HTTP request or of a Cloud Run instance (Doc 07 §19).
"""
from __future__ import annotations

from typing import Any

from agents.contracts import AgentInvocation, failure_result
from agents.runtime import AgentRuntime
from apps.api.core import context
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, span
from apps.api.repositories.base import Store
from apps.api.services.approval_service import ApprovalService
from apps.api.services.audit_service import AuditService
from apps.api.services.checkpoint_service import CheckpointService
from apps.api.services.event_service import EventService
from apps.api.services.memory_service import MemoryService
from apps.api.services.policy_engine import PolicyEngine
from apps.api.services.recovery_engine import RecoveryEngine
from apps.api.services.registry import AgentRegistry
from domain import ids
from domain.enums import (
    ApprovalStatus,
    EventType,
    FailureClass,
    MemoryType,
    MissionStatus,
    Priority,
    RecoveryStatus,
    RiskLevel,
    TaskStatus,
)
from domain.errors import ACCError, InvalidState, MissionNotFound
from domain.models import Mission, MissionContext, MissionEvent, Task, AgentResult, utcnow
from domain.plans import MissionTemplate, get_template
from domain.state_machine import assert_transition

logger = get_logger("acc.mission")

_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1,
               RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}

# Checkpoint stage produced at the end of each task type (Doc 02 §18).
# Each task produces a checkpoint that SAYS what it did. The initial mapping
# was copied from the blueprint example, written for the hero scenario: a
# nominal mission displayed "Recovery plan selected" after merely preparing a
# purchase. A false label in the audit trail is as harmful as an invented
# event.
CHECKPOINT_AFTER_TASK = {
    "supply_analysis": "supply_analysis",
    "risk_assessment": "risk_assessment",
    "procurement_plan": "procurement_planned",
    "procurement_execute": "procurement_completed",
}


class MissionEngine:
    def __init__(
        self,
        store: Store,
        registry: AgentRegistry,
        runtime: AgentRuntime,
        events: EventService,
        checkpoints: CheckpointService,
        memory: MemoryService,
        approvals: ApprovalService,
        recovery: RecoveryEngine,
        policy: PolicyEngine,
        audit: AuditService,
    ) -> None:
        self.store = store
        self.registry = registry
        self.runtime = runtime
        self.events = events
        self.checkpoints = checkpoints
        self.memory = memory
        self.approvals = approvals
        self.recovery = recovery
        self.policy = policy
        self.audit = audit
        events.set_handler(self.process_event)

    # =======================================================================
    # Cycle de vie
    # =======================================================================
    async def create_mission(
        self,
        objective: str,
        priority: Priority = Priority.HIGH,
        template_key: str = "protect-production",
        context_overrides: dict[str, Any] | None = None,
    ) -> Mission:
        template = get_template(template_key)
        mission = Mission(
            objective=objective or template.objective,
            priority=priority,
            context=MissionContext(**(context_overrides or {})),
            current_stage="created",
        )
        await self.store.save_mission(mission)
        await self._create_tasks(mission, template)

        await self.events.publish(
            mission.mission_id, EventType.MISSION_CREATED,
            f"Mission created: {mission.objective}",
            objective=mission.objective, priority=priority.value,
            deadline_hours=mission.context.deadline_hours,
        )
        await self.memory.write(
            mission.mission_id, MemoryType.CONSTRAINT,
            {"deadline_hours": mission.context.deadline_hours,
             "required_units": mission.context.required_units,
             "objective": mission.objective},
            source="mission-engine",
        )
        await self.checkpoints.create(mission, "created")
        await self.store.save_mission(mission)
        logger.info("mission_created", extra={"mission_id": mission.mission_id})
        return mission

    async def _create_tasks(self, mission: Mission, template: MissionTemplate) -> list[Task]:
        by_type: dict[str, str] = {}
        tasks: list[Task] = []
        for spec in template.tasks:
            task = Task(
                mission_id=mission.mission_id, type=spec.type, title=spec.title,
                assigned_agent=spec.agent_id, order=spec.order, priority=spec.priority,
            )
            by_type[spec.type] = task.task_id
            tasks.append(task)
        for spec, task in zip(template.tasks, tasks):
            task.depends_on = [by_type[d] for d in spec.depends_on_types if d in by_type]
            await self.store.save_task(task)
        return tasks

    async def start(self, mission_id: str) -> Mission:
        mission = await self._require(mission_id)
        if mission.status is not MissionStatus.CREATED:
            raise InvalidState("Mission already started", mission_id=mission_id,
                               status=mission.status.value)
        with span(Span.MISSION_START, mission_id=mission_id):
            await self._set_status(mission, MissionStatus.EXECUTING, stage="planning")
        await self.events.publish(
            mission_id, EventType.MISSION_STARTED, "Mission started, fleet activated",
        )
        return mission

    # =======================================================================
    # Boucle evenementielle
    # =======================================================================
    async def process_event(self, event: MissionEvent) -> None:
        """Point d'entree unique : worker inproc et push Pub/Sub arrivent ici."""
        with context.bind(mission_id=event.mission_id, trace_id=event.trace_id):
            if event.type in {EventType.MISSION_STARTED, EventType.TASK_COMPLETED,
                              EventType.MISSION_RESUMED}:
                await self.advance(event.mission_id)
            elif event.type is EventType.APPROVAL_RECEIVED:
                await self.on_approval(event)

    async def advance(self, mission_id: str) -> Mission:
        """Select and run the next runnable task."""
        mission = await self._require(mission_id)
        if mission.status.is_terminal:
            return mission
        if mission.status is MissionStatus.WAITING_APPROVAL:
            return mission

        tasks = await self.store.list_tasks(mission_id)
        completed = {t.task_id for t in tasks if t.status is TaskStatus.COMPLETED}

        if len(completed) == len(tasks) and tasks:
            return await self._complete(mission)

        nxt = next(
            (t for t in tasks
             if t.status in {TaskStatus.PENDING, TaskStatus.FAILED}
             and all(d in completed for d in t.depends_on)),
            None,
        )
        if nxt is None:
            logger.info("mission_no_runnable_task", extra={"mission_id": mission_id})
            return mission
        return await self._run_task(mission, nxt)

    # =======================================================================
    # Task execution
    # =======================================================================
    async def _run_task(self, mission: Mission, task: Task) -> Mission:
        agent_id = task.assigned_agent or "supply-agent"

        # Atomic claim BEFORE any execution. Pub/Sub delivers at least once:
        # without this, two concurrent pushes of the same event would run the
        # same agent twice (double model cost, polluted audit).
        owner = f"{ids.execution_id()}"
        claimed = await self.store.claim_task(
            mission.mission_id, task.task_id,
            {TaskStatus.PENDING.value, TaskStatus.FAILED.value}, owner,
        )
        if claimed is None:
            logger.info("task_already_claimed", extra={
                "task_id": task.task_id, "mission_id": mission.mission_id,
            })
            return mission
        task = claimed

        record = await self.registry.get(agent_id)
        mission.active_task_id = task.task_id
        mission.active_agent_id = agent_id
        mission.current_stage = get_template().stage_by_task_type.get(task.type, task.type)
        await self.store.save_mission(mission)

        await self.events.publish(
            mission.mission_id, EventType.AGENT_STARTED,
            f"{record.name} activated: {task.title}",
            source=agent_id, actor=agent_id, task_id=task.task_id, task_type=task.type,
        )

        identity = self.runtime.build_identity(
            agent_id, mission.mission_id, task.task_id,
            version=record.version, authority=record.authority_level,
            service_identity=record.service_identity,
        )
        invocation = AgentInvocation(
            identity=identity,
            mission=mission,
            task_type=task.type,
            task_title=task.title,
            memory_recall=await self.memory.recall_for_agent(
                mission, agent_id, mission.mission_id
            ),
            inputs={"attempt": task.attempt,
                    "supplier_id": mission.context.selected_supplier
                    or mission.context.primary_supplier},
            available_capabilities=record.capabilities,
            policy_summary=self.policy.describe(),
        )

        with context.bind(mission_id=mission.mission_id, task_id=task.task_id,
                          agent_id=agent_id, execution_id=identity.execution_id):
            try:
                result, execution = await self.runtime.run_task(agent_id, invocation)
            except ACCError as exc:
                # An unavailable, suspended or revoked agent must NEVER leave
                # the mission frozen: being unable to launch an agent is a
                # mission failure like any other, not an exception that
                # silently bubbles up to the bus (Doc 03 §19).
                logger.warning("agent_launch_refused", extra={
                    "agent_id": agent_id, "code": exc.code, "detail": exc.message,
                })
                return await self._on_task_failure(
                    mission, task,
                    failure_result(exc.message, FailureClass.AUTHORIZATION),
                    agent_id,
                )

        if result.status.is_failure:
            return await self._on_task_failure(mission, task, result, agent_id)
        return await self._on_task_success(mission, task, result, agent_id, execution.execution_id)

    async def _on_task_success(
        self, mission: Mission, task: Task, result: AgentResult,
        agent_id: str, execution_id: str,
    ) -> Mission:
        self._absorb_result(mission, task, result)

        await self.memory.write(
            mission.mission_id, MemoryType.FINDING,
            {"task": task.type, "finding": result.finding,
             "recommendation": result.recommendation, "confidence": result.confidence},
            source=agent_id, evidence_refs=result.evidence,
        )
        await self.events.publish(
            mission.mission_id, EventType.AGENT_COMPLETED, result.finding,
            source=agent_id, actor=agent_id, task_id=task.task_id,
            confidence=result.confidence, evidence=result.evidence,
            execution_id=execution_id,
        )

        # Authority boundary reached: the mission waits for a human.
        if result.requires_approval:
            task.status = TaskStatus.WAITING
            await self.store.save_task(task)
            mission.pending_approval_id = result.data.get("approval_id")
            mission.approval_status = ApprovalStatus.PENDING
            await self._set_status(mission, MissionStatus.WAITING_APPROVAL,
                                   stage="awaiting_approval")
            await self.checkpoints.create(mission, "awaiting_approval")
            await self.store.save_mission(mission)
            logger.info("mission_waiting_approval", extra={
                "mission_id": mission.mission_id,
                "approval_id": mission.pending_approval_id,
            })
            return mission

        task.status = TaskStatus.COMPLETED
        await self.store.save_task(task)

        tasks = await self.store.list_tasks(mission.mission_id)
        done = sum(1 for t in tasks if t.status is TaskStatus.COMPLETED)
        mission.progress = int(done / max(len(tasks), 1) * 100)
        mission.active_task_id = None
        if mission.status in {MissionStatus.RECOVERING, MissionStatus.AT_RISK}:
            await self._set_status(mission, MissionStatus.EXECUTING)
        await self.store.save_mission(mission)

        stage = CHECKPOINT_AFTER_TASK.get(task.type)
        if stage:
            await self.checkpoints.create(mission, stage)
            await self.store.save_mission(mission)

        # Context compaction (Doc 04 §21): a long mission accumulates entries.
        # The summary NEVER replaces authoritative state; it only keeps the
        # context handed to agents from growing without bound.
        await self.memory.compact(mission.mission_id)

        await self.events.publish(
            mission.mission_id, EventType.TASK_COMPLETED,
            f"Task completed: {task.title}",
            task_id=task.task_id, task_type=task.type, progress=mission.progress,
        )
        return mission

    def _absorb_result(self, mission: Mission, task: Task, result: AgentResult) -> None:
        """Only the engine writes to mission state (Doc 04 §11-12)."""
        data = result.data or {}
        ctx = mission.context
        if task.type in {"supply_analysis", "procurement_plan"}:
            if data.get("supplier_id"):
                ctx.selected_supplier = data["supplier_id"]
            if data.get("unit_price") is not None:
                ctx.unit_price = float(data["unit_price"])
            if data.get("amount") is not None:
                ctx.purchase_amount = float(data["amount"])
        if task.type == "procurement_execute" and data.get("purchase_id"):
            ctx.purchase_id = data["purchase_id"]
        # SUPPLIER risk is not MISSION risk. A mission that suffered a
        # disruption does not drop back because the fallback is rated
        # "medium": mission risk is a high-water mark, and it only falls when
        # the mission resolves.
        if data.get("risk_level"):
            try:
                assessed = RiskLevel(str(data["risk_level"]).upper())
                mission.context.extra["supplier_risk_level"] = assessed.value
                if _RISK_ORDER[assessed] > _RISK_ORDER[mission.risk_level]:
                    mission.risk_level = assessed
            except (ValueError, KeyError):
                pass

    # =======================================================================
    # Echec -> Failure Twin
    # =======================================================================
    async def _on_task_failure(
        self, mission: Mission, task: Task, result: AgentResult, agent_id: str
    ) -> Mission:
        failure_class = result.failure_class or FailureClass.UNKNOWN
        detail = result.failure_detail or result.finding
        component = mission.context.selected_supplier or mission.context.primary_supplier

        task.status = TaskStatus.FAILED
        await self.store.save_task(task)

        await self.events.publish(
            mission.mission_id, EventType.AGENT_FAILED,
            f"{agent_id} failed: {detail}",
            source=agent_id, actor=agent_id, task_id=task.task_id,
            failure_class=failure_class.value,
        )
        failure_event = await self.events.publish(
            mission.mission_id, EventType.SUPPLIER_FAILED,
            f"Dependency unavailable: {component}",
            source=agent_id, component=component, detail=detail,
            failure_class=failure_class.value,
        )
        await self.memory.write(
            mission.mission_id, MemoryType.FAILURE,
            {"component": component, "failure_class": failure_class.value,
             "detail": detail, "task": task.type},
            source=agent_id,
        )

        await self._set_status(mission, MissionStatus.AT_RISK, stage="failure_detected")
        mission.risk_level = RiskLevel.HIGH
        await self.checkpoints.create(mission, "failure_detected")
        await self.store.save_mission(mission)
        await self.events.publish(
            mission.mission_id, EventType.MISSION_AT_RISK,
            "Mission at risk: objective threatened",
            component=component, failure_class=failure_class.value,
        )

        await self._set_status(mission, MissionStatus.RECOVERING, stage="recovery")
        await self.store.save_mission(mission)

        outcome = await self.recovery.recover(
            mission, task, component, failure_class, detail, failure_event.event_id
        )
        return await self._apply_directive(mission, task, outcome)

    async def _apply_directive(self, mission: Mission, task: Task | None, outcome) -> Mission:
        mission = await self._require(mission.mission_id)
        directive = outcome.directive

        if directive == "RETRY_TASK" and task is not None:
            fresh = await self.store.get_task(mission.mission_id, task.task_id)
            if fresh:
                # Attempt budget: unbounded, a permanently dead dependency
                # would loop the mission forever.
                if fresh.attempt >= fresh.max_attempts:
                    return await self._fail(
                        mission,
                        f"Final failure after {fresh.attempt} attempts on "
                        f"{fresh.title}: {outcome.detail}",
                        stage="recovery_exhausted",
                    )
                fresh.status = TaskStatus.PENDING
                fresh.attempt += 1
                await self.store.save_task(fresh)
            await self._set_status(mission, MissionStatus.EXECUTING, stage="recovery_applied")
            await self.checkpoints.create(mission, "recovery_selected")
            await self.store.save_mission(mission)
            return await self.advance(mission.mission_id)

        if directive == "WAIT_APPROVAL":
            # Structural guard: waiting on an approval that does not exist
            # freezes the mission with no lever for the operator. Fail
            # explicitly rather than allow a silent deadlock.
            if not outcome.approval_id:
                logger.error("wait_approval_without_approval_id", extra={
                    "mission_id": mission.mission_id,
                    "directive": directive, "detail": outcome.detail,
                })
                return await self._fail(
                    mission,
                    "Safe hold: awaiting an approval that was never requested "
                    f"({outcome.detail})",
                    stage="safe_hold",
                )
            mission.pending_approval_id = outcome.approval_id
            mission.approval_status = ApprovalStatus.PENDING
            await self._set_status(mission, MissionStatus.WAITING_APPROVAL,
                                   stage="awaiting_approval")
            await self.checkpoints.create(mission, "recovery_awaiting_approval")
            await self.store.save_mission(mission)
            return mission

        if directive == "WAIT":
            await self._set_status(mission, MissionStatus.AT_RISK, stage="waiting_reassessment")
            await self.store.save_mission(mission)
            return mission

        if directive == "ADVANCE":
            await self._set_status(mission, MissionStatus.EXECUTING)
            await self.store.save_mission(mission)
            return await self.advance(mission.mission_id)

        # Name the cause of failure: a bare "failed" does not say whether
        # recovery was abandoned for lack of change, exhausted, or refused.
        from domain.enums import RecoveryStrategy as _Strategy

        stage = ("situation_unchanged"
                 if outcome.plan.selected_strategy is _Strategy.ABORT
                 else "recovery_failed")
        return await self._fail(
            mission, outcome.detail or "Recovery not possible", stage=stage)

    # =======================================================================
    # Autorite humaine
    # =======================================================================
    async def on_approval(self, event: MissionEvent) -> Mission:
        approval_id = event.payload.get("approval_id")
        mission = await self._require(event.mission_id)
        if not approval_id:
            return mission
        approval = await self.approvals.get(approval_id)

        if approval.status is ApprovalStatus.REJECTED:
            # Validation matrix : rejet -> SAFE HOLD, jamais d'execution.
            mission.approval_status = ApprovalStatus.REJECTED
            await self._close_pending_recovery(mission, approval, RecoveryStatus.HELD)
            await self.store.save_mission(mission)
            return await self._fail(
                mission, f"Safe hold: action rejected by {approval.decided_by}",
                stage="safe_hold",
            )

        if approval.status is ApprovalStatus.EXPIRED:
            mission.approval_status = ApprovalStatus.EXPIRED
            await self._close_pending_recovery(mission, approval, RecoveryStatus.HELD)
            await self.store.save_mission(mission)
            return await self._fail(
                mission, "Safe hold: approval expired without a decision",
                stage="safe_hold",
            )

        if approval.status is not ApprovalStatus.APPROVED:
            return mission

        mission.approval_status = ApprovalStatus.APPROVED
        mission.pending_approval_id = None
        await self.store.save_mission(mission)
        await self.checkpoints.create(mission, "approval_received")
        await self.store.save_mission(mission)

        # Case 1: a RECOVERY PLAN was awaiting the decision.
        if approval.action == "recovery.apply":
            recovery = next(
                (r for r in await self.store.list_recoveries(mission.mission_id)
                 if r.approval_id == approval_id), None
            )
            if recovery is not None:
                task = (await self.store.get_task(mission.mission_id, approval.task_id)
                        if approval.task_id else None)
                await self._set_status(mission, MissionStatus.RECOVERING, stage="recovery")
                await self.store.save_mission(mission)
                outcome = await self.recovery.apply_after_approval(mission, recovery, task)
                return await self._apply_directive(mission, task, outcome)

        # Case 2: an ENTERPRISE ACTION (purchase) was awaiting the decision.
        task = None
        if approval.task_id:
            task = await self.store.get_task(mission.mission_id, approval.task_id)
        if task is not None:
            task.status = TaskStatus.PENDING
            await self.store.save_task(task)
        await self._set_status(mission, MissionStatus.EXECUTING, stage="authorized_execution")
        await self.store.save_mission(mission)
        await self.events.publish(
            mission.mission_id, EventType.MISSION_RESUMED,
            "Mission resumed after human authorisation",
            approval_id=approval_id, latency_s=approval.latency_s,
        )
        return mission

    async def _close_pending_recovery(
        self, mission: Mission, approval, status: RecoveryStatus
    ) -> None:
        """Close the recovery that was waiting on this decision.

        Without it, a rejection left the recovery IN_PROGRESS forever: the
        trace showed an "in progress" recovery on a finished mission, and its
        duration stayed incomputable for lack of `completed_at`.
        """
        mission.pending_approval_id = None
        for recovery in await self.store.list_recoveries(mission.mission_id):
            if recovery.approval_id != approval.approval_id:
                continue
            if recovery.completed_at is not None:
                continue
            recovery.status = status
            recovery.completed_at = utcnow()
            recovery.reason = (
                f"{recovery.reason} — decision humaine : {approval.status.value}"
            ).strip(" —")
            await self.store.save_recovery(recovery)
            logger.info("recovery_closed_by_decision", extra={
                "recovery_id": recovery.recovery_id,
                "decision": approval.status.value,
            })

    # =======================================================================
    # Resume after runtime interruption (Doc 04 §7-8)
    # =======================================================================
    async def interrupt(self, mission_id: str) -> Mission:
        """Simulate the runtime disappearing: state stays, compute does not."""
        mission = await self._require(mission_id)
        # Interrupting an already finished mission makes no sense and would
        # inject an event that never happened into its timeline. An audit
        # trail containing invented facts proves nothing.
        if mission.status.is_terminal:
            raise InvalidState(
                "Terminal mission: there is no runtime left to interrupt",
                mission_id=mission_id, status=mission.status.value,
            )
        task = None
        if mission.active_task_id:
            task = await self.store.get_task(mission_id, mission.active_task_id)
        if task and task.status is TaskStatus.RUNNING:
            task.status = TaskStatus.PENDING
            await self.store.save_task(task)
        await self.events.publish(
            mission_id, EventType.RUNTIME_INTERRUPTED,
            "Agent runtime interrupted — mission state persisted",
            source="demo-controller", checkpoint_id=mission.checkpoint_id,
        )
        logger.warning("runtime_interrupted", extra={
            "mission_id": mission_id, "checkpoint_id": mission.checkpoint_id,
        })
        return mission

    async def resume(self, mission_id: str, checkpoint_id: str | None = None) -> Mission:
        """RUNTIME FAILURE -> LOAD CHECKPOINT -> VALIDATE -> RESTORE -> RESUME."""
        mission = await self._require(mission_id)
        if mission.status.is_terminal:
            raise InvalidState("Terminal mission: cannot be resumed",
                               mission_id=mission_id, status=mission.status.value)

        checkpoint = (await self.checkpoints.get(mission_id, checkpoint_id)
                      if checkpoint_id else await self.checkpoints.latest(mission_id))
        if checkpoint is None:
            raise InvalidState("No checkpoint available", mission_id=mission_id)

        with span(Span.MISSION_RESUME, checkpoint_id=checkpoint.checkpoint_id):
            # 1. Restaurer le contexte structure
            mission.context = MissionContext(**checkpoint.context_snapshot)
            mission.current_stage = checkpoint.current_stage
            mission.checkpoint_id = checkpoint.checkpoint_id
            # 2. Restore approval state (durable, not UI)
            mission.approval_status = checkpoint.approval_status
            mission.pending_approval_id = checkpoint.policy_state.get("pending_approval_id")

            # 3. A still-PENDING approval means we keep waiting
            if mission.pending_approval_id:
                approval = await self.store.get_approval(mission.pending_approval_id)
                if approval and approval.status is ApprovalStatus.PENDING:
                    await self.store.save_mission(mission)
                    await self.events.publish(
                        mission_id, EventType.MISSION_RESUMED,
                        "State restored — mission still awaiting approval",
                        checkpoint_id=checkpoint.checkpoint_id, resumed=False,
                    )
                    return mission

            # 4. Resume the pending task without replaying completed work
            for task in await self.store.list_tasks(mission_id):
                if task.status is TaskStatus.RUNNING:
                    task.status = TaskStatus.PENDING
                    await self.store.save_task(task)

            if mission.status is not MissionStatus.EXECUTING:
                await self._set_status(mission, MissionStatus.EXECUTING, stage="resumed")
            await self.store.save_mission(mission)

        await self.events.publish(
            mission_id, EventType.MISSION_RESUMED,
            f"Mission resumed from {checkpoint.checkpoint_id}",
            checkpoint_id=checkpoint.checkpoint_id, resumed=True,
        )
        logger.info("mission_resumed", extra={
            "mission_id": mission_id, "checkpoint_id": checkpoint.checkpoint_id,
        })
        return mission

    # =======================================================================
    # Terminaison
    # =======================================================================
    async def _complete(self, mission: Mission) -> Mission:
        with span(Span.MISSION_COMPLETE):
            await self._set_status(mission, MissionStatus.COMPLETED, stage="completed")
            mission.progress = 100
            mission.completed_at = utcnow()
            mission.active_task_id = None
            mission.active_agent_id = None
            await self.store.save_mission(mission)
            await self.checkpoints.create(mission, "completed")
            await self.store.save_mission(mission)
        await self.memory.write(
            mission.mission_id, MemoryType.DECISION,
            {"outcome": "COMPLETED", "supplier": mission.context.selected_supplier,
             "purchase_id": mission.context.purchase_id,
             "amount": mission.context.purchase_amount},
            source="mission-engine",
        )
        await self.events.publish(
            mission.mission_id, EventType.MISSION_COMPLETED,
            "Mission completed successfully",
            purchase_id=mission.context.purchase_id,
            supplier=mission.context.selected_supplier,
        )
        logger.info("mission_completed", extra={"mission_id": mission.mission_id})
        return mission

    async def _fail(self, mission: Mission, reason: str, stage: str = "failed") -> Mission:
        await self._set_status(mission, MissionStatus.FAILED, stage=stage)
        mission.completed_at = utcnow()
        await self.store.save_mission(mission)
        await self.events.publish(
            mission.mission_id, EventType.MISSION_FAILED, reason, reason=reason, stage=stage,
        )
        logger.warning("mission_failed", extra={
            "mission_id": mission.mission_id, "reason": reason,
        })
        return mission

    # =======================================================================
    # Helpers
    # =======================================================================
    async def _require(self, mission_id: str) -> Mission:
        mission = await self.store.get_mission(mission_id)
        if mission is None:
            raise MissionNotFound(f"Mission not found: {mission_id}", mission_id=mission_id)
        return mission

    async def _set_status(
        self, mission: Mission, target: MissionStatus, stage: str | None = None
    ) -> Mission:
        if mission.status is target and stage is None:
            return mission
        assert_transition(mission.status, target, mission.mission_id)
        previous = mission.status
        mission.status = target
        if stage:
            mission.current_stage = stage
        await self.store.update_mission(mission, mission.version)
        logger.info("mission_status", extra={
            "mission_id": mission.mission_id,
            "from": previous.value, "to": target.value, "stage": mission.current_stage,
        })
        return mission
