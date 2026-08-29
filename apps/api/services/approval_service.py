"""Human authority — an approval is DURABLE state, not a UI session.

Doc 03 §8-9, Doc 04 §10.
If the runtime dies while waiting, the mission stays WAITING_APPROVAL and
resumes when the human answers, even two hours later.
"""
from __future__ import annotations

from datetime import timedelta

from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, current_trace_id, span
from apps.api.repositories.base import Store
from domain.enums import ApprovalStatus, EventType, RiskLevel, SecurityEventType
from domain.errors import ApprovalNotFound, InvalidState
from domain.models import AgentIdentity, Approval, PolicyDecision, utcnow
from apps.api.services.audit_service import AuditService
from apps.api.services.event_service import EventService

logger = get_logger("acc.approvals")

DEFAULT_TTL_HOURS = 24


class ApprovalService:
    def __init__(self, store: Store, events: EventService, audit: AuditService) -> None:
        self.store = store
        self.events = events
        self.audit = audit

    async def request(
        self,
        identity: AgentIdentity,
        action: str,
        decision: PolicyDecision,
        resource: str | None = None,
        amount: float | None = None,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        reason: str = "",
        evidence: list[str] | None = None,
        idempotency_key: str | None = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> Approval:
        with span(Span.APPROVAL_REQUEST, action=action):
            approval = Approval(
                mission_id=identity.mission_id,
                task_id=identity.task_id,
                agent_id=identity.agent_id,
                action=action,
                resource=resource,
                amount=amount,
                risk_level=risk_level,
                reason=reason or decision.reason,
                evidence=evidence or [],
                policy_decision_id=decision.policy_decision_id,
                idempotency_key=idempotency_key,
                trace_id=current_trace_id(),
                expires_at=utcnow() + timedelta(hours=ttl_hours),
            )
            await self.store.save_approval(approval)
        await self.events.publish(
            identity.mission_id, EventType.APPROVAL_REQUESTED,
            f"Approval required: {action}",
            source="policy-engine", actor=identity.agent_id,
            approval_id=approval.approval_id, action=action, amount=amount,
            risk_level=risk_level.value,
        )
        await self.audit.record_security(
            SecurityEventType.APPROVAL_REQUESTED, mission_id=identity.mission_id,
            agent_id=identity.agent_id, action=action, severity=risk_level,
            detail=approval.reason, approval_id=approval.approval_id,
        )
        logger.info("approval_requested", extra={"approval_id": approval.approval_id})
        return approval

    async def get(self, approval_id: str) -> Approval:
        approval = await self.store.get_approval(approval_id)
        if approval is None:
            raise ApprovalNotFound(f"Approval not found: {approval_id}",
                                   approval_id=approval_id)
        return approval

    async def list(
        self, mission_id: str | None = None, status: str | None = None
    ) -> list[Approval]:
        return await self.store.list_approvals(mission_id, status)

    async def decide(
        self, approval_id: str, approved: bool, decided_by: str, comment: str | None = None
    ) -> Approval:
        """An agent can never approve its own action (Doc 03 §8)."""
        approval = await self.get(approval_id)
        if approval.status is not ApprovalStatus.PENDING:
            raise InvalidState(
                f"Approval already decided ({approval.status.value})",
                approval_id=approval_id, status=approval.status.value,
            )
        if decided_by == approval.agent_id or decided_by.endswith("-agent"):
            raise InvalidState(
                "An agent cannot approve its own action",
                approval_id=approval_id, decided_by=decided_by,
            )
        if approval.expires_at and utcnow() > approval.expires_at:
            approval.status = ApprovalStatus.EXPIRED
            await self.store.save_approval(approval)
            raise InvalidState("Approval expired", approval_id=approval_id)

        with span(Span.APPROVAL_DECISION, approved=approved):
            approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            approval.decided_by = decided_by
            approval.comment = comment
            approval.decided_at = utcnow()
            await self.store.save_approval(approval)

        await self.events.publish(
            approval.mission_id, EventType.APPROVAL_RECEIVED,
            f"Approval {approval.status.value} by {decided_by}",
            source="operator", actor=decided_by,
            approval_id=approval.approval_id, decision=approval.status.value,
            latency_s=approval.latency_s,
        )
        if not approved:
            await self.audit.record_security(
                SecurityEventType.APPROVAL_REJECTED, mission_id=approval.mission_id,
                agent_id=approval.agent_id, action=approval.action,
                severity=RiskLevel.HIGH, detail=comment or "Operator rejection",
                approval_id=approval.approval_id,
            )
        logger.info("approval_decided", extra={
            "approval_id": approval_id, "status": approval.status.value,
            "latency_s": approval.latency_s,
        })
        return approval

    async def expire_stale(self, mission_id: str | None = None) -> list[Approval]:
        """Move approvals past their TTL to EXPIRED.

        Without this sweep a mission could stay WAITING_APPROVAL forever on a
        request nobody will ever handle.
        """
        expired: list[Approval] = []
        for approval in await self.store.list_approvals(mission_id, "PENDING"):
            if approval.expires_at and utcnow() > approval.expires_at:
                approval.status = ApprovalStatus.EXPIRED
                approval.decided_at = utcnow()
                await self.store.save_approval(approval)
                await self.events.publish(
                    approval.mission_id, EventType.APPROVAL_RECEIVED,
                    f"Approval expired without a decision: {approval.action}",
                    source="approval-service",
                    approval_id=approval.approval_id, decision="EXPIRED",
                )
                expired.append(approval)
                logger.warning("approval_expired", extra={
                    "approval_id": approval.approval_id,
                })
        return expired

    async def find_granted(self, idempotency_key: str, mission_id: str) -> Approval | None:
        """The Gateway checks that a VALID approval covers exactly this action."""
        for approval in await self.store.list_approvals(mission_id):
            if approval.idempotency_key == idempotency_key:
                return approval
        return None
