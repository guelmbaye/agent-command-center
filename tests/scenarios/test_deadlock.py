"""Anti-deadlock: a mission always has a lever or an explicit end.

Regression observee en usage reel : les systemes entreprise etaient
injoignables, le Failure Twin a choisi ESCALATE, l'operateur a approuve — et la
mission est restee figee en WAITING_APPROVAL avec `pending_approval_id = None`.
Approbation consommee, recovery COMPLETED, et plus aucune action possible.

This is the worst possible defect for a product whose promise is "the mission
survives": it does not survive, it freezes without saying so.
"""
from __future__ import annotations

import pytest

from apps.api.repositories.factory import reset_store
from apps.api.services.container import build_container, set_container
from domain import ids
from domain.enums import MissionStatus, RecoveryStrategy
from tests.conftest import make_settings

DEAD_PORT = "http://127.0.0.1:9"  # discard : rien n'y repond jamais


@pytest.fixture
async def unreachable_enterprise():
    """Systemes entreprise totalement injoignables (mock eteint)."""
    reset_store()
    ids.reset_counters()
    c = build_container(make_settings(
        acc_enterprise_base_url=DEAD_PORT, acc_enterprise_timeout_s=1.0,
    ))
    set_container(c)
    await c.startup()
    try:
        yield c
    finally:
        await c.shutdown()
        set_container(None)


async def _settle(c, mission_id):
    await c.events.drain(timeout=60)
    return await c.store.get_mission(mission_id)


async def test_approved_escalation_never_deadlocks(unreachable_enterprise):
    """After approval the mission must advance — never sit with no lever."""
    c = unreachable_enterprise
    mission = await c.engine.create_mission("Protect production schedule")
    await c.engine.start(mission.mission_id)
    mission = await _settle(c, mission.mission_id)

    assert mission.status is MissionStatus.WAITING_APPROVAL
    pending = await c.approvals.list(mission.mission_id, "PENDING")
    escalation = next(a for a in pending if a.action == "recovery.apply")

    await c.approvals.decide(escalation.approval_id, True, "operator")
    mission = await _settle(c, mission.mission_id)

    if mission.status is MissionStatus.WAITING_APPROVAL:
        # Waiting is acceptable, but only if a real request exists.
        assert mission.pending_approval_id, (
            "mission figee : en attente d'une approbation inexistante"
        )
        still_pending = await c.approvals.list(mission.mission_id, "PENDING")
        assert still_pending, "aucune approbation en attente : l'operateur n'a plus de levier"
    else:
        assert mission.status in {MissionStatus.EXECUTING, MissionStatus.RECOVERING,
                                  MissionStatus.FAILED, MissionStatus.AT_RISK}


async def test_repeated_failures_converge_to_an_explicit_failure(unreachable_enterprise):
    """The attempt budget must bound the recovery loop."""
    c = unreachable_enterprise
    mission = await c.engine.create_mission("Protect production schedule")
    await c.engine.start(mission.mission_id)
    await _settle(c, mission.mission_id)

    for _ in range(8):
        current = await c.store.get_mission(mission.mission_id)
        if current.status.is_terminal:
            break
        pending = await c.approvals.list(mission.mission_id, "PENDING")
        assert pending, (
            f"mission en {current.status.value} sans approbation en attente : "
            "aucune action possible"
        )
        await c.approvals.decide(pending[0].approval_id, True, "operator")
        await _settle(c, mission.mission_id)

    final = await c.store.get_mission(mission.mission_id)
    assert final.status is MissionStatus.FAILED, (
        "une dependance durablement morte doit produire un echec explicite, "
        "pas une boucle sans fin"
    )
    # Three possible endings, all explicit — never a mute "failed":
    #   situation_unchanged : nothing moved, ACC stops re-asking
    #   recovery_exhausted  : attempt budget spent
    #   recovery_failed     : no applicable option
    assert final.current_stage in {
        "situation_unchanged", "recovery_exhausted", "recovery_failed",
    }, f"etape terminale peu informative : {final.current_stage}"

    # "Explainable": the failure event must carry a readable reason, whatever
    # the exact cause (budget spent, situation unchanged, ...).
    timeline = await c.traces.timeline(mission.mission_id)
    failures = [e for e in timeline if e["type"] == "mission.failed"]
    assert failures, "un echec doit produire un evenement mission.failed"
    reason = failures[-1]["message"]
    assert len(reason) > 30, f"raison trop laconique : {reason!r}"
    assert any(marker in reason.lower() for marker in
               ("attempt", "unchanged", "identical", "reject")), (
        f"la raison n'explique pas l'echec : {reason!r}"
    )


async def test_escalation_is_resolved_not_replayed(unreachable_enterprise):
    """Rejouer ESCALATE apres approbation recreerait l'attente indefiniment."""
    c = unreachable_enterprise
    mission = await c.engine.create_mission("Protect production schedule")
    await c.engine.start(mission.mission_id)
    await _settle(c, mission.mission_id)

    pending = await c.approvals.list(mission.mission_id, "PENDING")
    first = pending[0]
    await c.approvals.decide(first.approval_id, True, "operator")
    await _settle(c, mission.mission_id)

    recoveries = await c.store.list_recoveries(mission.mission_id)
    resolved = [r for r in recoveries if r.approval_id == first.approval_id]
    assert resolved and resolved[0].status.value == "COMPLETED"
    assert resolved[0].selected_option is RecoveryStrategy.ESCALATE

    # Any new wait must correspond to a NEW request.
    current = await c.store.get_mission(mission.mission_id)
    if current.pending_approval_id:
        assert current.pending_approval_id != first.approval_id
