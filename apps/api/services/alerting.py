"""Mission-oriented alerting (Doc 05 §18).

Explicit blueprint rule: "Do not create alerts for every normal agent event."
So we alert only on what threatens a mission or governance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from apps.api.core.logging import get_logger
from apps.api.repositories.base import Store
from domain.enums import ApprovalStatus, MissionStatus, RecoveryStatus, SecurityEventType
from domain.models import utcnow

logger = get_logger("acc.alerting")

Severity = Literal["CRITICAL", "WARNING"]

APPROVAL_DELAY_WARNING_S = 900  # 15 min sans decision humaine


@dataclass
class Alert:
    severity: Severity
    kind: str
    mission_id: str | None
    message: str
    detail: str = ""

    def to_doc(self) -> dict:
        return {
            "severity": self.severity, "kind": self.kind,
            "mission_id": self.mission_id, "message": self.message,
            "detail": self.detail,
        }


class AlertingService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def current(self) -> list[Alert]:
        alerts: list[Alert] = []
        for mission in await self.store.list_missions(limit=100):
            if mission.status.is_terminal and mission.status is not MissionStatus.FAILED:
                continue
            alerts.extend(await self._for_mission(mission))
        alerts.sort(key=lambda a: 0 if a.severity == "CRITICAL" else 1)
        return alerts

    async def _for_mission(self, mission) -> list[Alert]:
        mid = mission.mission_id
        alerts: list[Alert] = []

        # --- CRITICAL: mission at risk --------------------------------------
        # WAITING_APPROVAL is NOT a risk in itself: it is the autonomy
        # boundary working normally. It becomes one when the mission has been
        # disrupted (high risk_level) and can no longer progress on its own.
        blocked_after_disruption = (
            mission.status is MissionStatus.WAITING_APPROVAL
            and mission.risk_level.value in {"HIGH", "CRITICAL"}
        )
        if (mission.status in {MissionStatus.AT_RISK, MissionStatus.RECOVERING}
                or blocked_after_disruption):
            alerts.append(Alert("CRITICAL", "mission_at_risk", mid,
                                f"Mission en risque : {mission.objective}",
                                f"étape {mission.current_stage}"))
        if mission.status is MissionStatus.FAILED:
            alerts.append(Alert("CRITICAL", "mission_failed", mid,
                                f"Mission échouée : {mission.objective}",
                                mission.current_stage))

        # --- CRITICAL: security violation -----------------------------------
        for event in await self.store.list_security_events(mid):
            if event.type in {SecurityEventType.MODEL_THREAT_DETECTED,
                              SecurityEventType.AUTHORIZATION_DENIED,
                              SecurityEventType.POLICY_DENIED}:
                alerts.append(Alert("CRITICAL", "security_violation", mid,
                                    f"Événement de sécurité : {event.type.value}",
                                    event.detail))

        # --- CRITICAL: repeated failing recovery ----------------------------
        recoveries = await self.store.list_recoveries(mid)
        failed = [r for r in recoveries if r.status is RecoveryStatus.FAILED]
        if len(failed) >= 2:
            alerts.append(Alert("CRITICAL", "recovery_failing", mid,
                                f"{len(failed)} recoveries en échec",
                                "intervention humaine probablement requise"))

        # --- WARNING: approval dragging on ----------------------------------
        for approval in await self.store.list_approvals(mid, ApprovalStatus.PENDING.value):
            waiting = (utcnow() - approval.requested_at).total_seconds()
            if waiting > APPROVAL_DELAY_WARNING_S:
                alerts.append(Alert("WARNING", "approval_delayed", mid,
                                    f"Approbation en attente depuis {waiting / 60:.0f} min",
                                    f"{approval.action} · {approval.approval_id}"))

        # --- WARNING: degraded agent ----------------------------------------
        for agent in await self.store.list_agents():
            if agent.status.value in {"DEGRADED", "FAILED", "SUSPENDED"}:
                alerts.append(Alert("WARNING", "agent_degraded", None,
                                    f"Agent {agent.agent_id} en état {agent.status.value}",
                                    agent.name))
        return alerts
