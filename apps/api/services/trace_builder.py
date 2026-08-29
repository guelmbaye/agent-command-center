"""Timeline and trace tree exposed to Mission Control (Doc 08 §19-20).

The frontend never reaches the OpenTelemetry backend directly: ACC exposes a
readable projection, correlated by mission_id / trace_id.
"""
from __future__ import annotations

from typing import Any

from apps.api.repositories.base import Store
from domain.enums import EventType

_ICON = {
    EventType.MISSION_CREATED: "mission",
    EventType.MISSION_STARTED: "mission",
    EventType.MISSION_AT_RISK: "alert",
    EventType.MISSION_RESUMED: "resume",
    EventType.MISSION_COMPLETED: "success",
    EventType.MISSION_FAILED: "failure",
    EventType.AGENT_STARTED: "agent",
    EventType.AGENT_COMPLETED: "agent",
    EventType.AGENT_FAILED: "failure",
    EventType.SUPPLIER_FAILED: "alert",
    EventType.TOOL_FAILED: "alert",
    EventType.POLICY_CHECKED: "policy",
    EventType.APPROVAL_REQUESTED: "approval",
    EventType.APPROVAL_RECEIVED: "approval",
    EventType.CHECKPOINT_CREATED: "checkpoint",
    EventType.RECOVERY_STARTED: "recovery",
    EventType.RECOVERY_SELECTED: "recovery",
    EventType.RECOVERY_COMPLETED: "recovery",
    EventType.RECOVERY_FAILED: "failure",
    EventType.RUNTIME_INTERRUPTED: "alert",
    EventType.MODEL_THREAT_DETECTED: "security",
}


class TraceBuilder:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def timeline(self, mission_id: str) -> list[dict[str, Any]]:
        events = await self.store.list_events(mission_id)
        return [
            {
                "event_id": e.event_id,
                "type": e.type.value,
                "timestamp": e.timestamp.isoformat(),
                "message": e.message,
                "source": e.source,
                "actor": e.actor,
                "kind": _ICON.get(e.type, "event"),
                "payload": e.payload,
                "trace_id": e.trace_id,
            }
            for e in events
        ]

    async def trace(self, mission_id: str) -> dict[str, Any]:
        """Simplified tree: agents, failures, recovery, policy, approvals."""
        mission = await self.store.get_mission(mission_id)
        executions = await self.store.list_executions(mission_id)
        recoveries = await self.store.list_recoveries(mission_id)
        policies = await self.store.list_policy_decisions(mission_id)
        approvals = await self.store.list_approvals(mission_id)
        audits = await self.store.list_audit(mission_id)

        nodes: list[dict[str, Any]] = []
        for execution in executions:
            result = execution.result
            nodes.append({
                "type": "agent",
                "name": execution.agent_id,
                "status": execution.status.value,
                "execution_id": execution.execution_id,
                "duration_ms": execution.duration_ms,
                "finding": result.finding if result else None,
                "confidence": result.confidence if result else None,
                "evidence": result.evidence if result else [],
                "trace_id": execution.trace_id,
                "timestamp": execution.started_at.isoformat(),
            })
        for recovery in recoveries:
            nodes.append({
                "type": "recovery",
                "name": "Failure Twin",
                "status": recovery.status.value,
                "recovery_id": recovery.recovery_id,
                "diagnosis": recovery.diagnosis,
                "impact": recovery.impact.value,
                "options": [
                    {"label": o.label, "strategy": o.strategy.value,
                     "permitted": o.permitted, "denial_reason": o.denial_reason,
                     "risk": o.estimated_risk.value}
                    for o in recovery.options
                ],
                "selected": recovery.selected_option.value if recovery.selected_option else None,
                "reason": recovery.reason,
                "timestamp": recovery.started_at.isoformat(),
            })
        for policy in policies:
            nodes.append({
                "type": "policy",
                "name": policy.action,
                "decision": policy.decision.value,
                "reason": policy.reason,
                "rule_id": policy.rule_id,
                "amount": policy.amount,
                "timestamp": policy.timestamp.isoformat(),
            })
        for approval in approvals:
            nodes.append({
                "type": "approval",
                "name": approval.action,
                "status": approval.status.value,
                "approval_id": approval.approval_id,
                "decided_by": approval.decided_by,
                "amount": approval.amount,
                "latency_s": approval.latency_s,
                "timestamp": approval.requested_at.isoformat(),
            })
        for audit in audits:
            if audit.result in {"BLOCKED", "DENIED", "REPLAYED"}:
                nodes.append({
                    "type": "security",
                    "name": audit.action,
                    "status": audit.result,
                    "detail": audit.detail,
                    "timestamp": audit.timestamp.isoformat(),
                })

        nodes.sort(key=lambda n: n["timestamp"])
        return {
            "mission_id": mission_id,
            "objective": mission.objective if mission else None,
            "status": mission.status.value if mission else None,
            "trace_id": mission.trace_id if mission else None,
            "trace": nodes,
        }

    async def evidence(self, mission_id: str) -> dict[str, Any]:
        """Structured explainability — never chain-of-thought (Doc 05 §12-13)."""
        recoveries = await self.store.list_recoveries(mission_id)
        approvals = await self.store.list_approvals(mission_id)
        memory = await self.store.list_memory(mission_id)
        decisions = []
        for recovery in recoveries:
            decisions.append({
                "question": "Que s'est-il passe ?",
                "answer": recovery.diagnosis,
                "what_acc_did": f"Activation du Failure Twin, "
                                f"{len(recovery.options)} options evaluees",
                "alternatives": [o.label for o in recovery.options],
                "permitted_alternatives": [o.label for o in recovery.options if o.permitted],
                "selected": recovery.selected_option.value if recovery.selected_option else None,
                "why": recovery.reason,
                "human_approval_required": bool(recovery.approval_id),
            })
        return {
            "mission_id": mission_id,
            "decisions": decisions,
            "approvals": [
                {"action": a.action, "amount": a.amount, "status": a.status.value,
                 "reason": a.reason, "decided_by": a.decided_by,
                 "evidence": a.evidence}
                for a in approvals
            ],
            "memory": [
                {"type": m.type.value, "content": m.content, "source": m.source}
                for m in memory
            ],
        }
