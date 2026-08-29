"""Agent Runtime — long-running, no local state (Doc 09 §6).

The runtime is deliberately stateless: all state lives in the store.
Cloud Run can restart, the runtime rebuilds itself, the mission carries on.
"""
from __future__ import annotations

import time
from typing import Any

from agents.base import ACCAgent, make_identity_context
from agents.contracts import AgentInvocation, failure_result
from agents.failure_twin import build_failure_twin
from agents.procurement import build_procurement_agent
from agents.risk import build_risk_agent
from agents.supply import build_supply_agent
from agents.tools.gateway_tools import bind_gateway
from apps.api.core.config import Settings, get_settings
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, current_trace_id, span
from apps.api.repositories.base import Store
from apps.api.services.agent_gateway import AgentGateway
from apps.api.services.model_armor import ModelArmor
from apps.api.services.registry import AgentRegistry
from domain.enums import AgentExecutionStatus, AgentStatus, FailureClass
from domain.errors import ACCError
from domain.models import AgentExecution, AgentIdentity, AgentResult, RecoveryPlan, utcnow
from domain import ids

logger = get_logger("acc.runtime")

FAILURE_TWIN_ID = "failure-twin"


def _indicts_the_agent(result: AgentResult) -> bool:
    """Tell "the agent failed" apart from "the agent reported a failure".

    Marking an agent DEGRADED for faithfully reporting a supplier outage means
    blaming it for doing its job. In fleet health that points the operator at
    the wrong problem: they inspect the agent while the dependency is dead.
    """
    if not result.status.is_failure:
        return False
    exonerating = {
        FailureClass.DEPENDENCY, FailureClass.PERMANENT,
        FailureClass.AUTHORIZATION, FailureClass.SECURITY,
    }
    return result.failure_class not in exonerating


class AgentRuntime:
    """Select, run and trace the fleet agents."""

    def __init__(
        self,
        store: Store,
        registry: AgentRegistry,
        gateway: AgentGateway,
        armor: ModelArmor,
        settings: Settings | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.gateway = gateway
        self.settings = settings or get_settings()
        bind_gateway(gateway)
        kwargs = {"settings": self.settings, "armor": armor}
        self._agents: dict[str, ACCAgent] = {
            "supply-agent": build_supply_agent(**kwargs),
            "risk-agent": build_risk_agent(**kwargs),
            "procurement-agent": build_procurement_agent(**kwargs),
            FAILURE_TWIN_ID: build_failure_twin(**kwargs),
        }

    def get(self, agent_id: str) -> ACCAgent | None:
        return self._agents.get(agent_id)

    # --- Task execution ----------------------------------------------------
    async def run_task(
        self, agent_id: str, invocation: AgentInvocation
    ) -> tuple[AgentResult, AgentExecution]:
        record = await self.registry.require_executable(agent_id)
        agent = self._agents.get(agent_id)
        if agent is None:
            raise ACCError(f"Agent non implemente dans le runtime : {agent_id}")

        execution = AgentExecution(
            mission_id=invocation.mission.mission_id,
            task_id=invocation.identity.task_id or "",
            agent_id=agent_id,
            agent_version=record.version,
            runtime=record.runtime,
            model=agent.model,
            attempt=invocation.inputs.get("attempt", 1),
            trace_id=current_trace_id(),
        )
        await self.store.save_execution(execution)

        if record.status is AgentStatus.AVAILABLE:
            await self.registry.set_status(agent_id, AgentStatus.BUSY)

        started = time.perf_counter()
        try:
            with make_identity_context(invocation):
                with span(Span.AGENT_START, agent_id=agent_id,
                          task_type=invocation.task_type):
                    result = await agent.execute(invocation)
        except ACCError as exc:
            result = failure_result(exc.message, FailureClass.AUTHORIZATION)
        except Exception as exc:  # pragma: no cover - garde-fou runtime
            logger.exception("agent_execution_crashed", extra={"agent_id": agent_id})
            result = failure_result(str(exc), FailureClass.AGENT)

        execution.result = result
        execution.completed_at = utcnow()
        execution.duration_ms = int((time.perf_counter() - started) * 1000)
        execution.status = (
            AgentExecutionStatus.FAILED if result.status.is_failure
            else AgentExecutionStatus.COMPLETED
        )
        await self.store.save_execution(execution)

        # An agent is degraded only if it MALFUNCTIONED. Correctly reporting
        # an unavailable dependency is an agent success, not an agent failure:
        # it is exactly what we expect from it.
        await self._restore_status(agent_id, failed=_indicts_the_agent(result))
        logger.info("agent_executed", extra={
            "agent_id": agent_id, "task_type": invocation.task_type,
            "result_status": result.status.value, "duration_ms": execution.duration_ms,
        })
        return result, execution

    # --- Failure Twin ------------------------------------------------------
    async def plan_recovery(self, invocation: AgentInvocation) -> tuple[RecoveryPlan, AgentExecution]:
        record = await self.registry.require_executable(FAILURE_TWIN_ID)
        agent = self._agents[FAILURE_TWIN_ID]

        execution = AgentExecution(
            mission_id=invocation.mission.mission_id,
            task_id=invocation.identity.task_id or "",
            agent_id=FAILURE_TWIN_ID,
            agent_version=record.version,
            runtime=record.runtime,
            model=agent.model,
            trace_id=current_trace_id(),
        )
        await self.store.save_execution(execution)
        await self.registry.set_status(FAILURE_TWIN_ID, AgentStatus.BUSY)

        started = time.perf_counter()
        try:
            with make_identity_context(invocation):
                with span(Span.RECOVERY_DECISION, agent_id=FAILURE_TWIN_ID):
                    plan = await agent.execute(invocation)  # type: ignore[assignment]
        except Exception as exc:  # pragma: no cover
            logger.exception("failure_twin_crashed")
            plan = None
            _ = exc

        if not isinstance(plan, RecoveryPlan):
            # The Failure Twin must always produce a plan; otherwise escalate.
            from domain.enums import RecoveryStrategy, RiskLevel
            plan = RecoveryPlan(
                diagnosis="The Failure Twin did not produce a usable plan",
                impact=RiskLevel.HIGH,
                selected_strategy=RecoveryStrategy.ESCALATE,
                rationale="Default escalation: no verifiable option.",
                requires_approval=True, confidence=0.0,
            )

        execution.completed_at = utcnow()
        execution.duration_ms = int((time.perf_counter() - started) * 1000)
        execution.status = AgentExecutionStatus.COMPLETED
        execution.result = AgentResult(
            finding=plan.diagnosis,
            recommendation=plan.selected_strategy.value,
            confidence=plan.confidence,
            evidence=plan.evidence,
            data={"selected_parameters": plan.selected_parameters,
                  "options": [o.to_doc() for o in plan.options]},
            requires_approval=plan.requires_approval,
        )
        await self.store.save_execution(execution)
        await self._restore_status(FAILURE_TWIN_ID, failed=False)
        return plan, execution

    async def _restore_status(self, agent_id: str, failed: bool) -> None:
        try:
            target = AgentStatus.DEGRADED if failed else AgentStatus.AVAILABLE
            record = await self.registry.get(agent_id)
            if record.status is AgentStatus.BUSY:
                await self.registry.set_status(agent_id, target)
            if failed:
                await self.registry.set_status(agent_id, AgentStatus.AVAILABLE)
        except Exception:  # pragma: no cover
            logger.warning("agent_status_restore_failed", extra={"agent_id": agent_id})

    def build_identity(
        self, agent_id: str, mission_id: str, task_id: str | None,
        version: str = "1.0.0", authority: Any = None, service_identity: str = "",
    ) -> AgentIdentity:
        from domain.enums import AuthorityLevel
        return AgentIdentity(
            agent_id=agent_id, agent_version=version,
            execution_id=ids.execution_id(), mission_id=mission_id, task_id=task_id,
            service_identity=service_identity or f"acc/agents/{agent_id}",
            authority_level=authority or AuthorityLevel.SUPERVISED,
        )
