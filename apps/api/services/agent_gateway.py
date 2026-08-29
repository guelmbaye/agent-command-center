"""Agent Gateway — the execution boundary between autonomous reasoning and
the real world.

Blueprint Doc 02 §11, Doc 03 §10, Doc 07 §11.

Mandatory pipeline, in this order:
    IDENTITY -> CAPABILITY -> POLICY -> APPROVAL -> IDEMPOTENCY
             -> TOOL -> MODEL ARMOR -> AUDIT

No direct Agent -> ERP / database / procurement API connection exists anywhere
else in the code. That is what makes the "Fortified" claim verifiable rather
than declarative.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from apps.api.core.config import Settings, get_settings
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, current_trace_id, span
from apps.api.repositories.base import Store
from apps.api.services.approval_service import ApprovalService
from apps.api.services.audit_service import AuditService
from apps.api.services.enterprise_tools import (
    REASONING_CAPABILITIES,
    EnterpriseToolClient,
    is_consequential,
    resolve,
)
from apps.api.services.idempotency import IdempotencyGuard, build_key
from apps.api.services.model_armor import ModelArmor
from apps.api.services.policy_engine import PolicyEngine, PolicyRequest
from apps.api.services.registry import AgentRegistry
from domain.enums import (
    ApprovalStatus,
    EventType,
    PolicyDecisionValue,
    RiskLevel,
    SecurityEventType,
)
from domain.errors import CapabilityDenied, IdentityUnverified
from domain.models import AgentIdentity, ToolAction, ToolActionResult
from apps.api.services.event_service import EventService

logger = get_logger("acc.gateway")


@dataclass
class GatewayRequest:
    identity: AgentIdentity
    capability: str
    parameters: dict
    resource: str | None = None
    amount: float | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    evidence: list[str] | None = None
    reason: str = ""
    idempotency_key: str | None = None


class AgentGateway:
    def __init__(
        self,
        store: Store,
        registry: AgentRegistry,
        policy: PolicyEngine,
        approvals: ApprovalService,
        audit: AuditService,
        events: EventService,
        armor: ModelArmor,
        tools: EnterpriseToolClient,
        settings: Settings | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.policy = policy
        self.approvals = approvals
        self.audit = audit
        self.events = events
        self.armor = armor
        self.tools = tools
        self.idempotency = IdempotencyGuard(store)
        self.settings = settings or get_settings()

    async def execute(self, request: GatewayRequest) -> ToolActionResult:
        identity = request.identity
        key = request.idempotency_key or build_key(
            identity.mission_id, identity.task_id, request.capability
        )
        action = ToolAction(
            mission_id=identity.mission_id,
            task_id=identity.task_id,
            agent_id=identity.agent_id,
            capability=request.capability,
            parameters=request.parameters,
            idempotency_key=key,
        )

        # --- 1. IDENTITY ---------------------------------------------------
        record = await self._validate_identity(identity, request.capability)

        # --- 2. CAPABILITY -------------------------------------------------
        if not record.has_capability(request.capability):
            await self.audit.record_security(
                SecurityEventType.AUTHORIZATION_DENIED, mission_id=identity.mission_id,
                agent_id=identity.agent_id, action=request.capability,
                severity=RiskLevel.HIGH,
                detail="Capability not declared, or explicitly denied in the registry",
            )
            await self.audit.record_action(
                identity, request.capability, request.resource, "DENIED",
                detail="Capability missing from the registry",
            )
            raise CapabilityDenied(
                f"Agent {identity.agent_id} does not hold capability {request.capability}",
                agent_id=identity.agent_id, capability=request.capability,
            )

        # --- 3. POLICY -----------------------------------------------------
        outcome = await self.policy.evaluate(PolicyRequest(
            identity=identity, capability=request.capability, resource=request.resource,
            amount=request.amount, risk_level=request.risk_level,
        ))
        await self.events.publish(
            identity.mission_id, EventType.POLICY_CHECKED,
            f"Policy: {request.capability} -> {outcome.decision.value}",
            source="policy-engine", actor=identity.agent_id,
            action=request.capability, decision=outcome.decision.value,
            rule_id=outcome.rule_id, reason=outcome.reason,
        )

        if outcome.decision is PolicyDecisionValue.DENY:
            return await self._denied(action, identity, request, outcome)

        # --- 4. APPROVAL ---------------------------------------------------
        approval_id: str | None = None
        if outcome.needs_approval:
            granted = await self.approvals.find_granted(key, identity.mission_id)
            if granted is None:
                approval = await self.approvals.request(
                    identity=identity, action=request.capability, decision=outcome.record,
                    resource=request.resource, amount=request.amount,
                    risk_level=request.risk_level,
                    reason=request.reason or outcome.reason,
                    evidence=request.evidence or [], idempotency_key=key,
                )
                await self.audit.record_action(
                    identity, request.capability, request.resource, "APPROVAL_REQUIRED",
                    policy_decision=outcome.decision,
                    policy_decision_id=outcome.record.policy_decision_id,
                    approval_id=approval.approval_id,
                )
                return ToolActionResult(
                    action_id=action.action_id, status="APPROVAL_REQUIRED",
                    policy_decision_id=outcome.record.policy_decision_id,
                    approval_id=approval.approval_id, trace_id=current_trace_id(),
                    result={"reason": outcome.reason, "amount": request.amount},
                )
            if granted.status is ApprovalStatus.REJECTED:
                await self.audit.record_action(
                    identity, request.capability, request.resource, "REJECTED",
                    policy_decision=outcome.decision, approval_id=granted.approval_id,
                    detail="Operator rejection: holding",
                )
                return ToolActionResult(
                    action_id=action.action_id, status="REJECTED",
                    approval_id=granted.approval_id,
                    policy_decision_id=outcome.record.policy_decision_id,
                    error_code="APPROVAL_REJECTED",
                    error_message=granted.comment or "Action rejected by the operator",
                    trace_id=current_trace_id(),
                )
            if granted.status is not ApprovalStatus.APPROVED:
                return ToolActionResult(
                    action_id=action.action_id, status="APPROVAL_REQUIRED",
                    approval_id=granted.approval_id,
                    policy_decision_id=outcome.record.policy_decision_id,
                    trace_id=current_trace_id(),
                )
            approval_id = granted.approval_id

        # --- 5. IDEMPOTENCY (before execution, Doc 04 §9) -------------------
        # Consequential actions only. Replaying a READ from cache would stop
        # any retry from seeing a corrected world: recovery could never succeed.
        replay = (await self.idempotency.lookup(key)
                  if is_consequential(request.capability) else None)
        if replay is not None:
            await self.audit.record_action(
                identity, request.capability, request.resource, "REPLAYED",
                policy_decision=outcome.decision, approval_id=approval_id,
                detail="Existing result returned, no double execution",
            )
            return ToolActionResult(
                action_id=action.action_id, status="SUCCESS",
                result=replay["result"], approval_id=approval_id,
                policy_decision_id=outcome.record.policy_decision_id,
                replayed=True, trace_id=current_trace_id(),
            )

        # --- Reasoning capability: no enterprise action ---------------------
        if request.capability in REASONING_CAPABILITIES:
            await self.audit.record_action(
                identity, request.capability, request.resource, "ALLOWED",
                policy_decision=outcome.decision, approval_id=approval_id,
                detail="Reasoning capability, no system call",
            )
            return ToolActionResult(
                action_id=action.action_id, status="SUCCESS",
                result={"authorized": True}, approval_id=approval_id,
                policy_decision_id=outcome.record.policy_decision_id,
                trace_id=current_trace_id(),
            )

        # --- 6. TOOL + MODEL ARMOR on the output ----------------------------
        tool_name, impl = resolve(request.capability)
        with span(Span.TOOL_CALL, capability=request.capability, tool=tool_name):
            call = await impl(self.tools, request.parameters)

        if not call.ok:
            await self.events.publish(
                identity.mission_id, EventType.TOOL_FAILED,
                f"Tool failure {tool_name}: {call.error}",
                source="agent-gateway", actor=identity.agent_id,
                tool=tool_name, status_code=call.status_code,
                failure_class=call.failure_class.value if call.failure_class else "UNKNOWN",
            )
            await self.audit.record_security(
                SecurityEventType.TOOL_FAILURE, mission_id=identity.mission_id,
                agent_id=identity.agent_id, action=request.capability,
                severity=RiskLevel.MEDIUM, detail=call.error or "",
            )
            await self.audit.record_action(
                identity, request.capability, request.resource, "FAILED",
                policy_decision=outcome.decision, approval_id=approval_id,
                detail=call.error or "",
            )
            return ToolActionResult(
                action_id=action.action_id, status="FAILED", result=call.data,
                policy_decision_id=outcome.record.policy_decision_id,
                approval_id=approval_id, error_code="TOOL_UNAVAILABLE",
                error_message=call.error, trace_id=current_trace_id(),
            )

        verdict = await self.armor.scan_tool_output(call.raw_text or json.dumps(call.data),
                                                    tool=tool_name)
        if verdict.blocked:
            return await self._blocked_by_armor(action, identity, request, outcome,
                                                tool_name, verdict, call.data)

        # --- 7. IDEMPOTENT RECORD + AUDIT ----------------------------------
        if is_consequential(request.capability):
            await self.idempotency.remember(key, call.data)
        await self.audit.record_action(
            identity, request.capability, request.resource, "SUCCESS",
            policy_decision=outcome.decision,
            policy_decision_id=outcome.record.policy_decision_id,
            approval_id=approval_id,
        )
        return ToolActionResult(
            action_id=action.action_id, status="SUCCESS", result=call.data,
            policy_decision_id=outcome.record.policy_decision_id,
            approval_id=approval_id, trace_id=current_trace_id(),
        )

    # --- Helpers -----------------------------------------------------------
    async def _validate_identity(self, identity: AgentIdentity, capability: str):
        if not identity.agent_id or not identity.execution_id or not identity.mission_id:
            await self.audit.record_security(
                SecurityEventType.AUTHENTICATION_FAILURE, mission_id=identity.mission_id or None,
                agent_id=identity.agent_id, action=capability, severity=RiskLevel.CRITICAL,
                detail="Incomplete identity context",
            )
            raise IdentityUnverified("Incomplete execution identity: execution refused")
        return await self.registry.require_executable(identity.agent_id)

    async def _denied(self, action, identity, request, outcome) -> ToolActionResult:
        await self.audit.record_security(
            SecurityEventType.POLICY_DENIED, mission_id=identity.mission_id,
            agent_id=identity.agent_id, action=request.capability,
            severity=RiskLevel.HIGH, detail=outcome.reason, rule_id=outcome.rule_id,
        )
        await self.audit.record_action(
            identity, request.capability, request.resource, "DENIED",
            policy_decision=outcome.decision,
            policy_decision_id=outcome.record.policy_decision_id, detail=outcome.reason,
        )
        logger.warning("gateway_denied", extra={
            "capability": request.capability, "rule_id": outcome.rule_id,
        })
        return ToolActionResult(
            action_id=action.action_id, status="DENIED",
            policy_decision_id=outcome.record.policy_decision_id,
            error_code="POLICY_DENIED", error_message=outcome.reason,
            trace_id=current_trace_id(),
        )

    async def _blocked_by_armor(
        self, action, identity, request, outcome, tool_name, verdict, data
    ) -> ToolActionResult:
        """Tool poisoning: untrusted content never redefines authority."""
        await self.events.publish(
            identity.mission_id, EventType.MODEL_THREAT_DETECTED,
            f"Untrusted instruction blocked ({tool_name})",
            source="model-armor", actor=identity.agent_id,
            threat=verdict.threat, reasons=verdict.reasons, provider=verdict.provider,
        )
        await self.audit.record_security(
            SecurityEventType.MODEL_THREAT_DETECTED, mission_id=identity.mission_id,
            agent_id=identity.agent_id, action=request.capability,
            severity=RiskLevel.CRITICAL, detail=verdict.detail, tool=tool_name,
        )
        await self.audit.record_action(
            identity, request.capability, request.resource, "BLOCKED",
            policy_decision=outcome.decision,
            policy_decision_id=outcome.record.policy_decision_id,
            detail=f"Model Armor: {verdict.detail}",
        )
        logger.warning("model_armor_blocked", extra={
            "tool": tool_name, "threat": verdict.threat,
        })
        # The mission continues: sanitised data is returned, never the instruction.
        sanitized = dict(data)
        sanitized["_armor"] = {
            "blocked": True, "threat": verdict.threat, "reasons": verdict.reasons,
            "provider": verdict.provider,
        }
        sanitized.pop("message", None)
        sanitized.pop("notes", None)
        return ToolActionResult(
            action_id=action.action_id, status="SUCCESS", result=sanitized,
            policy_decision_id=outcome.record.policy_decision_id,
            error_code="CONTENT_SANITIZED", error_message=verdict.detail,
            trace_id=current_trace_id(),
        )
