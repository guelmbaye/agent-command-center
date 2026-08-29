"""Alertes orientees mission et metriques de fiabilite (Doc 05 §7-9, §18)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from domain.models import utcnow


async def test_healthy_mission_raises_no_alert(container):
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    alerts = await container.alerts.current()
    assert not [a for a in alerts if a.mission_id == mission.mission_id], (
        "une mission nominale ne doit generer aucune alerte"
    )


async def test_disrupted_mission_raises_a_critical_alert(container, enterprise):
    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    alerts = await container.alerts.current()
    kinds = {a.kind for a in alerts if a.mission_id == mission.mission_id}
    assert "mission_at_risk" in kinds or "mission_failed" in kinds


async def test_delayed_approval_raises_a_warning(container, enterprise):
    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    approval = pending[0]
    approval.requested_at = utcnow() - timedelta(minutes=30)
    await container.store.save_approval(approval)

    alerts = await container.alerts.current()
    assert any(a.kind == "approval_delayed" and a.severity == "WARNING" for a in alerts)


async def test_reliability_metrics_are_populated(container, enterprise):
    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")
    await container.approvals.decide(purchase.approval_id, True, "operator")
    await container.events.drain(timeout=60)

    metrics = await container.metrics.for_mission(mission.mission_id)
    assert metrics.mission_duration_s is not None and metrics.mission_duration_s >= 0
    assert metrics.agent_latency_ms is not None
    assert metrics.agent_success_rate is not None
    assert metrics.mttr_s is not None, "MTTR doit etre calculable apres une recovery"

    fleet = await container.metrics.fleet_summary()
    assert fleet["mean_time_to_recovery_s"] is not None


async def test_expired_approval_sweep_puts_mission_in_safe_hold(container, enterprise):
    """An approval never handled must not leave the mission hanging."""
    from domain.enums import ApprovalStatus, MissionStatus

    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    for approval in pending:
        approval.expires_at = utcnow() - timedelta(minutes=1)
        await container.store.save_approval(approval)

    expired = await container.approvals.expire_stale(mission.mission_id)
    assert expired
    assert expired[0].status is ApprovalStatus.EXPIRED

    await container.events.drain(timeout=60)
    final = await container.store.get_mission(mission.mission_id)
    assert final.status is MissionStatus.FAILED
    assert final.current_stage == "safe_hold"
    assert not enterprise.purchases


async def test_context_compaction_never_replaces_state(container):
    """The summary is context, never the truth (Doc 04 §22)."""
    from domain.enums import MemoryType

    mission = await container.engine.create_mission("Protect production schedule")
    for i in range(60):
        await container.memory.write(
            mission.mission_id, MemoryType.FINDING, {"n": i}, source="test"
        )

    result = await container.memory.compact(mission.mission_id, keep_last=40)
    assert result["compacted"]

    entries = await container.memory.all(mission.mission_id)
    assert any(e.memory_id == result["summary_id"] for e in entries)
    # Authoritative state is intact: the original entries still exist.
    assert sum(1 for e in entries if e.type is MemoryType.FINDING) >= 60


async def test_routine_approval_does_not_raise_a_critical_alert(container):
    """Over-alerting is not alerting: an approval alone is not a risk."""
    from domain.enums import MissionStatus, RiskLevel

    mission = await container.engine.create_mission("Protect production schedule")
    mission.status = MissionStatus.WAITING_APPROVAL
    mission.risk_level = RiskLevel.LOW  # mission saine, simple franchissement de seuil
    await container.store.save_mission(mission)

    alerts = await container.alerts.current()
    critical = [a for a in alerts
                if a.mission_id == mission.mission_id and a.severity == "CRITICAL"]
    assert not critical


async def test_mission_risk_never_silently_downgrades(container, enterprise):
    """Supplier risk must not erase mission risk."""
    from domain.enums import RiskLevel

    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    final = await container.store.get_mission(mission.mission_id)
    # The SUP-B fallback is rated MEDIUM, but the mission did suffer an outage.
    assert final.risk_level is RiskLevel.HIGH
    assert final.context.extra.get("supplier_risk_level") == "MEDIUM"


# ---------------------------------------------------------------------------
# Metric honesty
#
# Regression observed in use: the dashboard showed "Mission continuity 100 %"
# next to a FAILED mission. The percentage helper returned 100 on a zero
# denominator — missing data turned into a perfect score. On the product's
# north-star metric, that is the worst possible error.
# ---------------------------------------------------------------------------
async def test_continuity_is_not_reported_when_nothing_was_disrupted(container):
    """No disrupted mission => the rate does not exist; it is not 100 %."""
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    fleet = await container.metrics.fleet_summary()
    assert fleet["missions_disrupted"] == 0
    assert fleet["mission_continuity_rate"] is None, (
        "un score parfait ne doit pas etre fabrique a partir d'un echantillon vide"
    )


async def test_failed_mission_never_shows_a_perfect_score(container, enterprise):
    """The exact case encountered: a rejected mission, a rate shown as 100 %."""
    from domain.enums import MissionStatus

    nominal = await container.engine.create_mission(
        "Nominal", context_overrides={"required_units": 1200})
    await container.engine.start(nominal.mission_id)
    await container.events.drain(timeout=60)

    above = await container.engine.create_mission(
        "Au-dessus du seuil", context_overrides={"required_units": 1301})
    await container.engine.start(above.mission_id)
    await container.events.drain(timeout=60)

    pending = await container.approvals.list(above.mission_id, "PENDING")
    await container.approvals.decide(pending[0].approval_id, False, "operator", "NON")
    await container.events.drain(timeout=60)

    failed = await container.store.get_mission(above.mission_id)
    assert failed.status is MissionStatus.FAILED

    fleet = await container.metrics.fleet_summary()
    assert fleet["mission_continuity_rate"] is None
    assert fleet["mission_success_rate"] == 50.0
    assert fleet["mission_failure_rate"] == 50.0


async def test_continuity_is_reported_once_a_mission_is_disrupted(container, enterprise):
    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")
    await container.approvals.decide(purchase.approval_id, True, "operator")
    await container.events.drain(timeout=60)

    fleet = await container.metrics.fleet_summary()
    assert fleet["missions_disrupted"] == 1
    assert fleet["mission_continuity_rate"] == 100.0
