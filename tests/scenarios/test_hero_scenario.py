"""End-to-end hero scenario plus validation-matrix variants.

Doc 06 §11-17 (deroule) et Doc 10 §23 (matrice).
"""
from __future__ import annotations

import pytest

from domain.enums import ApprovalStatus, MissionStatus, RecoveryStrategy, TaskStatus


async def _run_until_settled(container, mission_id: str):
    await container.events.drain(timeout=60)
    return await container.store.get_mission(mission_id)


@pytest.fixture
async def disrupted_mission(container, enterprise):
    """Mission started with SUP-A down: WAITING_APPROVAL is expected."""
    enterprise.suppliers["SUP-A"].failing = True
    enterprise.suppliers["SUP-A"].status = "UNAVAILABLE"
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    return await _run_until_settled(container, mission.mission_id)


# ---------------------------------------------------------------------------
# Chemin nominal : aucune disruption -> aucune approbation
# ---------------------------------------------------------------------------
async def test_nominal_mission_completes_autonomously(container):
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    mission = await _run_until_settled(container, mission.mission_id)

    assert mission.status is MissionStatus.COMPLETED
    assert mission.context.selected_supplier == "SUP-A"
    assert mission.context.purchase_amount == 4_800.0  # sous le seuil autonome
    approvals = await container.approvals.list(mission.mission_id)
    assert approvals == []


# ---------------------------------------------------------------------------
# Chemin hero
# ---------------------------------------------------------------------------
async def test_supplier_failure_triggers_governed_recovery(disrupted_mission, container):
    mission = disrupted_mission
    assert mission.status is MissionStatus.WAITING_APPROVAL

    recoveries = await container.store.list_recoveries(mission.mission_id)
    assert len(recoveries) == 1
    recovery = recoveries[0]
    assert recovery.selected_option is RecoveryStrategy.USE_ALTERNATIVE_SUPPLIER
    assert recovery.selected_parameters["supplier_id"] == "SUP-B"
    # The recovery plan itself went through the Policy Engine.
    assert recovery.policy_decision_id


async def test_best_operational_option_is_rejected_when_not_permitted(disrupted_mission,
                                                                     container):
    """SUP-C is cheaper and lower risk, but 60h > 48h: not permitted."""
    recovery = (await container.store.list_recoveries(disrupted_mission.mission_id))[0]
    by_label = {o.label: o for o in recovery.options}
    sup_c = by_label["Switch to SUP-C"]
    sup_b = by_label["Switch to SUP-B"]

    assert not sup_c.permitted
    assert "60" in sup_c.denial_reason and "48" in sup_c.denial_reason
    assert sup_b.permitted
    assert "not permitted" in recovery.reason.lower()


async def test_retry_is_not_permitted_on_dependency_failure(disrupted_mission, container):
    recovery = (await container.store.list_recoveries(disrupted_mission.mission_id))[0]
    retry = next(o for o in recovery.options if o.strategy is RecoveryStrategy.RETRY)
    assert not retry.permitted
    assert "DEPENDENCY" in retry.denial_reason


async def test_authority_boundary_stops_the_purchase(disrupted_mission, container,
                                                     enterprise):
    pending = await container.approvals.list(disrupted_mission.mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")
    assert purchase.amount == 18_000.0
    assert not enterprise.purchases  # rien n'a atteint le systeme d'achat


async def test_approval_completes_the_mission(disrupted_mission, container, enterprise):
    pending = await container.approvals.list(disrupted_mission.mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")

    await container.approvals.decide(purchase.approval_id, True, "operator", "OK")
    mission = await _run_until_settled(container, disrupted_mission.mission_id)

    assert mission.status is MissionStatus.COMPLETED
    assert mission.context.selected_supplier == "SUP-B"
    assert mission.context.purchase_id
    assert len(enterprise.purchases) == 1  # exactement un achat


async def test_rejection_produces_a_safe_hold(disrupted_mission, container, enterprise):
    pending = await container.approvals.list(disrupted_mission.mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")

    await container.approvals.decide(purchase.approval_id, False, "operator", "Trop cher")
    mission = await _run_until_settled(container, disrupted_mission.mission_id)

    assert mission.status is MissionStatus.FAILED
    assert mission.current_stage == "safe_hold"
    assert mission.approval_status is ApprovalStatus.REJECTED
    assert not enterprise.purchases  # aucune execution malgre le rejet


# ---------------------------------------------------------------------------
# Interruption de runtime
# ---------------------------------------------------------------------------
async def test_runtime_interruption_preserves_mission_state(disrupted_mission, container):
    mission_id = disrupted_mission.mission_id
    before = await container.checkpoints.list(mission_id)
    pending_before = await container.approvals.list(mission_id, "PENDING")

    await container.engine.interrupt(mission_id)
    resumed = await container.engine.resume(mission_id)
    await container.events.drain(timeout=30)

    assert resumed.status is MissionStatus.WAITING_APPROVAL
    assert resumed.context.selected_supplier == "SUP-B"
    after = await container.approvals.list(mission_id, "PENDING")
    assert {a.approval_id for a in after} == {a.approval_id for a in pending_before}
    assert len(await container.checkpoints.list(mission_id)) >= len(before)


async def test_resume_does_not_replay_completed_work(disrupted_mission, container,
                                                     enterprise):
    mission_id = disrupted_mission.mission_id
    tasks_before = {t.task_id: t.status for t in await container.store.list_tasks(mission_id)}

    await container.engine.interrupt(mission_id)
    await container.engine.resume(mission_id)
    await container.events.drain(timeout=30)

    tasks_after = await container.store.list_tasks(mission_id)
    for task in tasks_after:
        if tasks_before[task.task_id] is TaskStatus.COMPLETED:
            assert task.status is TaskStatus.COMPLETED
    assert not enterprise.purchases


# ---------------------------------------------------------------------------
# Securite
# ---------------------------------------------------------------------------
async def test_malicious_supplier_content_does_not_change_authority(container, enterprise):
    enterprise.suppliers["SUP-A"].failing = True
    enterprise.suppliers["SUP-B"].poisoned = True

    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    mission = await _run_until_settled(container, mission.mission_id)

    security = await container.store.list_security_events(mission.mission_id)
    assert any(e.type.value == "MODEL_THREAT_DETECTED" for e in security)
    # The injection asked for "do not request approval": the approval is still there.
    pending = await container.approvals.list(mission.mission_id, "PENDING")
    assert any(a.action == "purchase.execute" for a in pending)
    assert not enterprise.purchases


# ---------------------------------------------------------------------------
# Preuves d'audit et metriques
# ---------------------------------------------------------------------------
async def test_audit_trail_and_metrics_are_complete(disrupted_mission, container):
    mission_id = disrupted_mission.mission_id
    pending = await container.approvals.list(mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")
    await container.approvals.decide(purchase.approval_id, True, "operator")
    await container.events.drain(timeout=60)

    metrics = await container.metrics.for_mission(mission_id)
    assert metrics.disrupted
    assert metrics.recovery_success == 1
    assert metrics.approvals_granted == 1
    assert metrics.policy_violations == 0
    assert metrics.duplicate_executions == 0

    fleet = await container.metrics.fleet_summary()
    assert fleet["mission_continuity_rate"] == 100.0

    audits = await container.store.list_audit(mission_id)
    purchase_audit = [a for a in audits if a.action == "purchase.execute"
                      and a.result == "SUCCESS"]
    assert purchase_audit and purchase_audit[0].approval_id == purchase.approval_id


async def test_timeline_and_evidence_are_exposed(disrupted_mission, container):
    mission_id = disrupted_mission.mission_id
    timeline = await container.traces.timeline(mission_id)
    types = {e["type"] for e in timeline}
    assert {"mission.created", "mission.started", "supplier.failed", "mission.at_risk",
            "recovery.started", "recovery.selected", "approval.requested"} <= types

    # Integrity chaining: every event points to the previous one.
    events = await container.store.list_events(mission_id)
    assert events[0].previous_event_id is None
    for previous, current in zip(events, events[1:]):
        assert current.previous_event_id == previous.event_id

    evidence = await container.traces.evidence(mission_id)
    decision = evidence["decisions"][0]
    assert decision["selected"] == "USE_ALTERNATIVE_SUPPLIER"
    assert "Switch to SUP-C" in decision["alternatives"]
    assert "Switch to SUP-C" not in decision["permitted_alternatives"]
