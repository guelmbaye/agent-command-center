"""Audit trail and security events (Doc 03 §17-18)."""
from __future__ import annotations

from apps.api.core.logging import get_logger
from apps.api.core.telemetry import current_trace_id
from apps.api.repositories.base import Store
from domain.enums import PolicyDecisionValue, RiskLevel, SecurityEventType
from domain.models import AgentIdentity, AuditEvent, SecurityEvent

logger = get_logger("acc.audit")


class AuditService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def record_action(
        self,
        identity: AgentIdentity,
        action: str,
        target: str | None,
        result: str,
        policy_decision: PolicyDecisionValue | None = None,
        policy_decision_id: str | None = None,
        approval_id: str | None = None,
        detail: str = "",
    ) -> AuditEvent:
        """Who did what, on which resource, under which policy, with which approval."""
        event = AuditEvent(
            mission_id=identity.mission_id,
            execution_id=identity.execution_id,
            agent_id=identity.agent_id,
            agent_version=identity.agent_version,
            action=action,
            target=target,
            policy_decision=policy_decision,
            policy_decision_id=policy_decision_id,
            approval_id=approval_id,
            result=result,
            detail=detail,
            trace_id=current_trace_id(),
        )
        await self.store.save_audit(event)
        logger.info("audit", extra={"action": action, "result": result, "target": target})
        return event

    async def record_security(
        self,
        type_: SecurityEventType,
        mission_id: str | None = None,
        agent_id: str | None = None,
        action: str | None = None,
        severity: RiskLevel = RiskLevel.MEDIUM,
        detail: str = "",
        **payload: object,
    ) -> SecurityEvent:
        event = SecurityEvent(
            mission_id=mission_id, type=type_, agent_id=agent_id, action=action,
            severity=severity, detail=detail, payload=dict(payload),
            trace_id=current_trace_id(),
        )
        await self.store.save_security_event(event)
        logger.warning("security_event", extra={"type": type_.value, "detail": detail})
        return event

    async def list_for_mission(self, mission_id: str) -> list[AuditEvent]:
        return await self.store.list_audit(mission_id)
