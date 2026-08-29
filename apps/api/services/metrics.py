"""ACC metrics — Mission Continuity Rate as the north star (Doc 05 §7-9)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.api.repositories.base import Store
from domain.enums import (
    AgentExecutionStatus,
    ApprovalStatus,
    MissionStatus,
    PolicyDecisionValue,
    RecoveryStatus,
    RecoveryStrategy,
)

DISRUPTED_MARKERS = {MissionStatus.AT_RISK, MissionStatus.RECOVERING}


@dataclass
class MissionMetrics:
    mission_id: str
    status: str
    progress: int
    disrupted: bool = False
    recovery_attempts: int = 0
    recovery_success: int = 0
    recovery_duration_s: float | None = None
    approvals_requested: int = 0
    approvals_granted: int = 0
    approval_latency_s: float | None = None
    policy_denials: int = 0
    blocked_actions: int = 0
    policy_violations: int = 0
    agents_involved: int = 0
    duplicate_executions: int = 0
    mission_duration_s: float | None = None
    agent_latency_ms: float | None = None
    agent_success_rate: float | None = None
    mttr_s: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class MetricsService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def for_mission(self, mission_id: str) -> MissionMetrics:
        mission = await self.store.get_mission(mission_id)
        if mission is None:
            raise KeyError(mission_id)

        events = await self.store.list_events(mission_id)
        recoveries = await self.store.list_recoveries(mission_id)
        approvals = await self.store.list_approvals(mission_id)
        policies = await self.store.list_policy_decisions(mission_id)
        audits = await self.store.list_audit(mission_id)
        executions = await self.store.list_executions(mission_id)

        disrupted = any(e.type.value in {"mission.at_risk", "supplier.failed", "agent.failed"}
                        for e in events)
        durations = [r.duration_s for r in recoveries if r.duration_s is not None]
        latencies = [a.latency_s for a in approvals if a.latency_s is not None]
        agent_latencies = [e.duration_ms for e in executions if e.duration_ms is not None]
        agent_ok = sum(1 for e in executions
                       if e.status is AgentExecutionStatus.COMPLETED)

        end = mission.completed_at or mission.updated_at
        mission_duration = (end - mission.created_at).total_seconds()

        # MTTR (Doc 05 §9): failure detection -> end of recovery.
        mttr: float | None = None
        failure_events = [e for e in events
                          if e.type.value in {"supplier.failed", "agent.failed"}]
        finished = [r for r in recoveries if r.completed_at is not None]
        if failure_events and finished:
            mttr = (finished[-1].completed_at - failure_events[0].timestamp).total_seconds()

        return MissionMetrics(
            mission_id=mission_id,
            status=mission.status.value,
            progress=mission.progress,
            disrupted=disrupted,
            recovery_attempts=len(recoveries),
            # An escalation or an abort did NOT restore the mission: counting
            # them as successes would inflate the recovery rate with exactly
            # the cases where ACC handed off.
            recovery_success=sum(
                1 for r in recoveries
                if r.status is RecoveryStatus.COMPLETED
                and r.selected_option not in {RecoveryStrategy.ESCALATE,
                                              RecoveryStrategy.ABORT}
            ),
            recovery_duration_s=round(sum(durations), 1) if durations else None,
            approvals_requested=len(approvals),
            approvals_granted=sum(1 for a in approvals
                                  if a.status is ApprovalStatus.APPROVED),
            approval_latency_s=round(sum(latencies) / len(latencies), 1) if latencies else None,
            policy_denials=sum(1 for p in policies
                               if p.decision is PolicyDecisionValue.DENY),
            blocked_actions=sum(1 for a in audits if a.result == "BLOCKED"),
            # A violation = a consequential action executed without valid authorisation.
            policy_violations=sum(
                1 for a in audits
                if a.result == "SUCCESS"
                and a.policy_decision is PolicyDecisionValue.APPROVAL_REQUIRED
                and not a.approval_id
            ),
            agents_involved=len({e.agent_id for e in executions}),
            duplicate_executions=sum(1 for a in audits if a.result == "REPLAYED"),
            mission_duration_s=round(mission_duration, 1),
            agent_latency_ms=(round(sum(agent_latencies) / len(agent_latencies))
                              if agent_latencies else None),
            agent_success_rate=(round(agent_ok / len(executions) * 100, 1)
                                if executions else None),
            mttr_s=round(mttr, 1) if mttr is not None else None,
            evidence={
                "checkpoints": len(await self.store.list_checkpoints(mission_id)),
                "events": len(events),
                "audit_records": len(audits),
            },
        )

    async def fleet_summary(self) -> dict[str, Any]:
        missions = await self.store.list_missions(limit=200)
        total = len(missions)
        completed = sum(1 for m in missions if m.status is MissionStatus.COMPLETED)
        failed = sum(1 for m in missions if m.status is MissionStatus.FAILED)
        at_risk = sum(1 for m in missions if m.status in DISRUPTED_MARKERS)
        active = sum(1 for m in missions if not m.status.is_terminal)

        disrupted_total = 0
        disrupted_recovered = 0
        autonomous_recoveries = 0
        mttr_values: list[float | None] = []
        for mission in missions:
            metrics = await self.for_mission(mission.mission_id)
            mttr_values.append(metrics.mttr_s)
            if metrics.disrupted:
                disrupted_total += 1
                if mission.status is MissionStatus.COMPLETED:
                    disrupted_recovered += 1
                    if metrics.approvals_granted == 0:
                        autonomous_recoveries += 1

        def pct(num: int, den: int) -> float | None:
            """None when there is nothing to measure.

            Returning 100 % on a zero denominator manufactures a perfect score
            out of missing data: the dashboard showed "Continuity 100 %" next
            to a failed mission. For the product north-star metric that is
            indefensible.
            """
            return round(num / den * 100, 1) if den else None

        mttrs = [m for m in mttr_values if m is not None]
        return {
            "mission_continuity_rate": pct(disrupted_recovered, disrupted_total),
            "mean_time_to_recovery_s": (round(sum(mttrs) / len(mttrs), 1)
                                        if mttrs else None),
            "mission_success_rate": pct(completed, total),
            "mission_failure_rate": pct(failed, total),
            "recovery_success_rate": pct(disrupted_recovered, disrupted_total),
            "autonomous_recovery_rate": pct(autonomous_recoveries, disrupted_total),
            "missions_total": total,
            "missions_active": active,
            "missions_at_risk": at_risk,
            "missions_disrupted": disrupted_total,
            "missions_recovered": disrupted_recovered,
        }
