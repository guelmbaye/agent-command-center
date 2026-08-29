"""Recovery Engine — orchestrates the Failure Twin AND its governance.

Doc 07 §10, critical rule:
    Failure Twin -> Recovery Plan -> Policy Engine -> Approval if required
                 -> Agent Gateway -> Tool
Never: Failure Twin -> direct tool execution.

This is ACC's strongest technical argument: recovery itself is subject to the
same identity, the same policy and the same audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agents.contracts import AgentInvocation
from agents.runtime import FAILURE_TWIN_ID, AgentRuntime
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, current_trace_id, span
from apps.api.repositories.base import Store
from apps.api.services.agent_gateway import AgentGateway, GatewayRequest
from apps.api.services.audit_service import AuditService
from apps.api.services.event_service import EventService
from apps.api.services.memory_service import MemoryService
from apps.api.services.policy_engine import PolicyEngine
from apps.api.services.registry import AgentRegistry
from domain.enums import (
    EventType,
    FailureClass,
    MemoryType,
    RecoveryStatus,
    RecoveryStrategy,
    RiskLevel,
    SecurityEventType,
)
from domain.models import Mission, RecoveryAttempt, RecoveryPlan, Task, utcnow

logger = get_logger("acc.recovery")

Directive = Literal["ADVANCE", "RETRY_TASK", "WAIT_APPROVAL", "WAIT", "FAIL"]


@dataclass
class RecoveryOutcome:
    directive: Directive
    recovery: RecoveryAttempt
    plan: RecoveryPlan
    approval_id: str | None = None
    detail: str = ""


class RecoveryEngine:
    def __init__(
        self,
        store: Store,
        runtime: AgentRuntime,
        registry: AgentRegistry,
        gateway: AgentGateway,
        policy: PolicyEngine,
        events: EventService,
        memory: MemoryService,
        audit: AuditService,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.registry = registry
        self.gateway = gateway
        self.policy = policy
        self.events = events
        self.memory = memory
        self.audit = audit

    # -----------------------------------------------------------------------
    async def recover(
        self,
        mission: Mission,
        task: Task | None,
        failed_component: str,
        failure_class: FailureClass,
        detail: str,
        failure_event_id: str | None = None,
    ) -> RecoveryOutcome:
        previous = await self.store.list_recoveries(mission.mission_id)

        with span(Span.RECOVERY_START, component=failed_component,
                  failure_class=failure_class.value):
            await self.events.publish(
                mission.mission_id, EventType.RECOVERY_STARTED,
                f"Failure Twin activated on {failed_component}",
                source="recovery-engine",
                component=failed_component, failure_class=failure_class.value,
                attempt=len(previous) + 1,
            )

            plan, execution = await self.runtime.plan_recovery(
                await self._build_invocation(mission, task, failed_component,
                                             failure_class, detail, previous)
            )

        recovery = RecoveryAttempt(
            mission_id=mission.mission_id,
            failure_event_id=failure_event_id,
            failed_component=failed_component,
            failure_class=failure_class,
            diagnosis=plan.diagnosis,
            impact=plan.impact,
            options=plan.options,
            selected_option=plan.selected_strategy,
            selected_parameters=plan.selected_parameters,
            reason=plan.rationale,
            attempt=len(previous) + 1,
            trace_id=current_trace_id(),
        )
        await self.store.save_recovery(recovery)

        await self.events.publish(
            mission.mission_id, EventType.RECOVERY_SELECTED,
            f"Recovery selected: {plan.selected_strategy.value}",
            source=FAILURE_TWIN_ID,
            recovery_id=recovery.recovery_id,
            strategy=plan.selected_strategy.value,
            rationale=plan.rationale,
            options=[o.label for o in plan.options],
            permitted_options=[o.label for o in plan.options if o.permitted],
            execution_id=execution.execution_id,
        )
        await self.memory.write(
            mission.mission_id, MemoryType.RECOVERY,
            {
                "failure": failed_component,
                "failure_class": failure_class.value,
                "diagnosis": plan.diagnosis,
                "options": [o.label for o in plan.options],
                "selected": plan.selected_strategy.value,
                "reason": plan.rationale,
            },
            source=FAILURE_TWIN_ID,
        )

        # --- PLAN GOVERNANCE (the point that differentiates ACC) -----------
        identity = self.runtime.build_identity(
            FAILURE_TWIN_ID, mission.mission_id, task.task_id if task else None,
        )
        # An abort is not "applied": it observes. We distinguish it explicitly
        # so that policy does not demand authorisation to act when no action
        # will take place.
        aborting = plan.selected_strategy is RecoveryStrategy.ABORT
        result = await self.gateway.execute(GatewayRequest(
            identity=identity,
            capability="recovery.abort" if aborting else "recovery.apply",
            parameters={"strategy": plan.selected_strategy.value,
                        **plan.selected_parameters},
            resource=failed_component,
            risk_level=plan.impact if not plan.requires_approval else RiskLevel.HIGH,
            reason=plan.rationale,
            evidence=plan.evidence + (
                # Without this reminder the second request is
                # indistinguishable from the first: the operator approves
                # without knowing they already answered.
                [f"attempt {recovery.attempt} on this mission",
                 f"{len(previous)} previous recovery attempt(s)"]
                if previous else []
            ),
            idempotency_key=(f"{mission.mission_id}-{recovery.recovery_id}-"
                             f"{'recovery.abort' if aborting else 'recovery.apply'}"),
        ))
        recovery.policy_decision_id = result.policy_decision_id

        if result.status == "DENIED":
            recovery.status = RecoveryStatus.FAILED
            recovery.completed_at = utcnow()
            await self.store.save_recovery(recovery)
            await self.audit.record_security(
                SecurityEventType.POLICY_DENIED, mission_id=mission.mission_id,
                agent_id=FAILURE_TWIN_ID, action="recovery.apply",
                severity=RiskLevel.HIGH, detail=result.error_message or "",
            )
            await self.events.publish(
                mission.mission_id, EventType.RECOVERY_FAILED,
                "Recovery plan denied by policy",
                source="policy-engine", recovery_id=recovery.recovery_id,
                reason=result.error_message,
            )
            return RecoveryOutcome("FAIL", recovery, plan,
                                   detail=result.error_message or "Recovery refusee")

        if result.status in {"APPROVAL_REQUIRED", "REJECTED"}:
            if result.status == "REJECTED":
                recovery.status = RecoveryStatus.HELD
                recovery.completed_at = utcnow()
                await self.store.save_recovery(recovery)
                return RecoveryOutcome("FAIL", recovery, plan,
                                       detail="Recovery rejected by the operator")
            recovery.approval_id = result.approval_id
            recovery.status = RecoveryStatus.IN_PROGRESS
            await self.store.save_recovery(recovery)
            return RecoveryOutcome("WAIT_APPROVAL", recovery, plan,
                                   approval_id=result.approval_id,
                                   detail="Recovery plan awaiting human authority")

        # --- APPLICATION DU PLAN -------------------------------------------
        directive, detail_msg = await self._apply(mission, task, plan, recovery)
        if directive != "FAIL":
            recovery.status = RecoveryStatus.COMPLETED
        elif aborting:
            # The recovery concluded correctly; it is the situation that is a
            # dead end. Marking it FAILED would make it look like a malfunction.
            recovery.status = RecoveryStatus.ABORTED
        else:
            recovery.status = RecoveryStatus.FAILED
        recovery.completed_at = utcnow()
        await self.store.save_recovery(recovery)

        await self.events.publish(
            mission.mission_id, EventType.RECOVERY_COMPLETED,
            (f"Controlled abort: no action was attempted"
             if aborting else f"Recovery applied: {plan.selected_strategy.value}"),
            source="recovery-engine", recovery_id=recovery.recovery_id,
            directive=directive, duration_s=recovery.duration_s,
        )
        await self.audit.record_security(
            SecurityEventType.RECOVERY_EXECUTED, mission_id=mission.mission_id,
            agent_id=FAILURE_TWIN_ID, action="recovery.apply",
            severity=RiskLevel.MEDIUM, detail=plan.selected_strategy.value,
            recovery_id=recovery.recovery_id,
        )
        return RecoveryOutcome(directive, recovery, plan, detail=detail_msg)

    # -----------------------------------------------------------------------
    async def apply_after_approval(
        self, mission: Mission, recovery: RecoveryAttempt, task: Task | None
    ) -> RecoveryOutcome:
        """Resume after a human decision on a recovery plan."""
        strategy = recovery.selected_option or RecoveryStrategy.ESCALATE
        plan = RecoveryPlan(
            diagnosis=recovery.diagnosis, impact=recovery.impact,
            options=recovery.options,
            selected_strategy=strategy,
            selected_parameters=recovery.selected_parameters, rationale=recovery.reason,
        )

        if strategy is RecoveryStrategy.ESCALATE:
            # ESCALATE means "ask a human". Once the human has decided, the
            # escalation is RESOLVED: replaying it as-is would put the mission
            # back to waiting for an approval that no longer exists — a
            # deadlock with no way out for the operator.
            recovery.status = RecoveryStatus.COMPLETED
            recovery.completed_at = utcnow()
            await self.store.save_recovery(recovery)
            await self.events.publish(
                mission.mission_id, EventType.RECOVERY_COMPLETED,
                "Escalation resolved by the operator: retrying the task",
                source="recovery-engine", recovery_id=recovery.recovery_id,
                directive="RETRY_TASK",
            )
            return RecoveryOutcome(
                "RETRY_TASK", recovery, plan,
                detail="Human authority granted: retrying",
            )

        directive, detail = await self._apply(mission, task, plan, recovery)
        recovery.status = (RecoveryStatus.COMPLETED if directive != "FAIL"
                           else RecoveryStatus.FAILED)
        recovery.completed_at = utcnow()
        await self.store.save_recovery(recovery)
        await self.events.publish(
            mission.mission_id, EventType.RECOVERY_COMPLETED,
            f"Recovery applied after approval: {plan.selected_strategy.value}",
            source="recovery-engine", recovery_id=recovery.recovery_id,
            directive=directive,
        )
        return RecoveryOutcome(directive, recovery, plan, detail=detail)

    # -----------------------------------------------------------------------
    async def _apply(
        self, mission: Mission, task: Task | None, plan: RecoveryPlan,
        recovery: RecoveryAttempt,
    ) -> tuple[Directive, str]:
        strategy = plan.selected_strategy
        params = plan.selected_parameters

        if strategy is RecoveryStrategy.RETRY:
            return "RETRY_TASK", "Retrying the same dependency"

        if strategy in {RecoveryStrategy.USE_ALTERNATIVE_SUPPLIER,
                        RecoveryStrategy.SWITCH_DATA_SOURCE}:
            supplier_id = params.get("supplier_id")
            if not supplier_id:
                return "FAIL", "No alternative supplier in the plan"
            mission.context.selected_supplier = supplier_id
            unit_price = params.get("unit_price")
            if unit_price is not None:
                mission.context.unit_price = float(unit_price)
                mission.context.purchase_amount = round(
                    float(unit_price) * mission.context.required_units, 2
                )
            await self.memory.write(
                mission.mission_id, MemoryType.DECISION,
                {"decision": f"Fournisseur {supplier_id} retenu",
                 "reason": plan.rationale,
                 "amount": mission.context.purchase_amount},
                source="recovery-engine",
            )
            return "RETRY_TASK", f"Switched to {supplier_id}"

        if strategy is RecoveryStrategy.SWITCH_AGENT:
            new_agent = params.get("agent_id")
            if task and new_agent:
                task.assigned_agent = new_agent
                await self.store.save_task(task)
                return "RETRY_TASK", f"Task reassigned to {new_agent}"
            return "FAIL", "No substitute agent available"

        if strategy is RecoveryStrategy.WAIT_AND_REASSESS:
            return "WAIT", "Mission awaiting reassessment"

        if strategy is RecoveryStrategy.ESCALATE:
            return "WAIT_APPROVAL", "Escalation to human authority"

        if strategy is RecoveryStrategy.ABORT:
            return "FAIL", plan.rationale or "Controlled mission abort"

        return "FAIL", f"Strategy not applicable: {strategy.value}"

    # -----------------------------------------------------------------------
    async def _build_invocation(
        self, mission: Mission, task: Task | None, failed_component: str,
        failure_class: FailureClass, detail: str, previous: list[RecoveryAttempt],
    ) -> AgentInvocation:
        """Compact recovery context — never the full transcript (Doc 04 §14)."""
        fleet = await self.registry.list()
        capabilities = sorted({c for a in fleet for c in a.capabilities})
        checkpoint = mission.checkpoint_id
        return AgentInvocation(
            identity=self.runtime.build_identity(
                FAILURE_TWIN_ID, mission.mission_id, task.task_id if task else None
            ),
            mission=mission,
            task_type="recovery_plan",
            task_title="Diagnose and select a permitted recovery",
            memory_recall=await self.memory.recall_for_agent(
                mission, FAILURE_TWIN_ID, mission.mission_id
            ),
            inputs={"latest_checkpoint": checkpoint},
            failure={
                "component": failed_component,
                "failure_class": failure_class.value,
                "detail": detail,
                "attempt": (task.attempt if task else 1),
                "task_type": task.type if task else None,
            },
            previous_recoveries=[
                # The diagnosis is essential: without it the Failure Twin
                # cannot observe that the state is UNCHANGED since the previous
                # attempt, and re-proposes the same plan indefinitely.
                {"strategy": r.selected_option.value if r.selected_option else None,
                 "status": r.status.value, "reason": r.reason,
                 "diagnosis": r.diagnosis, "failed_component": r.failed_component,
                 "was_approved": bool(r.approval_id)}
                for r in previous
            ],
            available_agents=[a.agent_id for a in fleet if a.status.can_execute],
            available_capabilities=capabilities,
            policy_summary=self.policy.describe(),
        )
