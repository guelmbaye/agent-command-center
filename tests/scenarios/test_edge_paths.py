"""Edge paths from the validation matrix (Doc 10 §14) and Doc 03 §19-20."""
from __future__ import annotations

import pytest

from domain.enums import (
    AgentStatus, ApprovalStatus, FailureClass, MissionStatus, RecoveryStrategy,
    TaskStatus,
)


async def _settle(container, mission_id: str):
    await container.events.drain(timeout=60)
    return await container.store.get_mission(mission_id)


# ---------------------------------------------------------------------------
# Recovery exhaustion: the last row of the matrix
# ---------------------------------------------------------------------------
@pytest.fixture
async def exhausted(container, enterprise):
    """Every supplier goes down: no acceptable autonomous option."""
    for supplier_id in ("SUP-A", "SUP-B", "SUP-C"):
        enterprise.suppliers[supplier_id].failing = True
        enterprise.suppliers[supplier_id].status = "UNAVAILABLE"
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    return await _settle(container, mission.mission_id)


async def test_exhausted_recovery_escalates_instead_of_guessing(exhausted, container):
    """With no viable option, ACC asks a human — it does not invent a solution."""
    assert exhausted.status is MissionStatus.WAITING_APPROVAL

    recovery = (await container.store.list_recoveries(exhausted.mission_id))[0]
    assert recovery.selected_option is RecoveryStrategy.ESCALATE
    assert not any(
        o.permitted and o.strategy is RecoveryStrategy.USE_ALTERNATIVE_SUPPLIER
        for o in recovery.options
    )
    pending = await container.approvals.list(exhausted.mission_id, "PENDING")
    assert any(a.action == "recovery.apply" for a in pending)


async def test_rejected_escalation_fails_explainably(exhausted, container, enterprise):
    """Matrix row: recovery failure -> FAILED + explainable."""
    pending = await container.approvals.list(exhausted.mission_id, "PENDING")
    escalation = next(a for a in pending if a.action == "recovery.apply")

    await container.approvals.decide(
        escalation.approval_id, False, "operator", "Aucun fournisseur viable"
    )
    mission = await _settle(container, exhausted.mission_id)

    assert mission.status is MissionStatus.FAILED
    assert mission.current_stage == "safe_hold"
    assert not enterprise.purchases

    # "Explainable" is not decorative: the evidence must be readable.
    evidence = await container.traces.evidence(mission.mission_id)
    decision = evidence["decisions"][0]
    assert decision["why"]
    assert decision["alternatives"]
    assert decision["selected"] == "ESCALATE"


# ---------------------------------------------------------------------------
# Gouvernance de flotte en cours de mission (Doc 03 §19)
# ---------------------------------------------------------------------------
async def test_suspended_agent_stops_the_mission_safely(container, enterprise):
    """A suspended agent must produce a SAFE HOLD, not a freeze.

    Assertion volontairement stricte : « statut != COMPLETED » serait satisfait
    by a permanently frozen mission, which is exactly the defect Doc 03 §19
    forbids. So we require an observable transition, a released task and a
    traced escalation.
    """
    mission = await container.engine.create_mission("Protect production schedule")

    await container.registry.suspend("procurement-agent", "Vulnérabilité détectée")
    await container.engine.start(mission.mission_id)
    mission = await _settle(container, mission.mission_id)

    assert (await container.registry.get("procurement-agent")).status is (
        AgentStatus.SUSPENDED
    )
    # 1. The mission reached an explicit halt state, not EXECUTING.
    assert mission.status in {MissionStatus.WAITING_APPROVAL, MissionStatus.FAILED}

    # 2. No task is left locked in RUNNING.
    tasks = await container.store.list_tasks(mission.mission_id)
    assert not any(t.status is TaskStatus.RUNNING for t in tasks)

    # 3. The incident is traced and escalated, not swallowed.
    recoveries = await container.store.list_recoveries(mission.mission_id)
    assert recoveries and recoveries[0].selected_option is RecoveryStrategy.ESCALATE
    assert recoveries[0].failure_class is FailureClass.AUTHORIZATION

    timeline = await container.traces.timeline(mission.mission_id)
    assert any(e["type"] == "mission.at_risk" for e in timeline)

    assert not enterprise.purchases


async def test_revoked_agent_cannot_be_reinstated_silently(container):
    from domain.errors import InvalidState

    await container.registry.suspend("supply-agent", "test")
    await container.registry.set_status("supply-agent", AgentStatus.REVOKED)
    with pytest.raises(InvalidState):
        await container.registry.set_status("supply-agent", AgentStatus.AVAILABLE)


# ---------------------------------------------------------------------------
# Deferred approval and expiry (Doc 04 §24, Doc 03 §8)
# ---------------------------------------------------------------------------
async def test_delayed_approval_still_completes_the_mission(container, enterprise):
    """The operator answers much later: the mission still resumes."""
    from datetime import timedelta
    from domain.models import utcnow

    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    mission = await _settle(container, mission.mission_id)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")

    # Push the request back two hours: the asynchronous wait is real.
    purchase.requested_at = utcnow() - timedelta(hours=2)
    await container.store.save_approval(purchase)

    await container.approvals.decide(purchase.approval_id, True, "operator")
    mission = await _settle(container, mission.mission_id)

    assert mission.status is MissionStatus.COMPLETED
    decided = await container.approvals.get(purchase.approval_id)
    assert decided.latency_s is not None and decided.latency_s > 3600


async def test_expired_approval_cannot_be_granted(container):
    """An expired approval cannot authorise an action (Doc 03 §8)."""
    from datetime import timedelta

    from domain.enums import PolicyDecisionValue
    from domain.errors import InvalidState
    from domain.models import AgentIdentity, PolicyDecision, utcnow

    mission = await container.engine.create_mission("Protect production schedule")
    identity = AgentIdentity(agent_id="procurement-agent", agent_version="1.0.0",
                             execution_id="EXE-1", mission_id=mission.mission_id)
    approval = await container.approvals.request(
        identity, "purchase.execute",
        PolicyDecision(mission_id=mission.mission_id, agent_id="procurement-agent",
                       action="purchase.execute",
                       decision=PolicyDecisionValue.APPROVAL_REQUIRED, reason="seuil"),
        amount=18_000.0,
    )
    approval.expires_at = utcnow() - timedelta(minutes=1)
    await container.store.save_approval(approval)

    with pytest.raises(InvalidState):
        await container.approvals.decide(approval.approval_id, True, "operator")

    assert (await container.approvals.get(approval.approval_id)).status is (
        ApprovalStatus.EXPIRED
    )


# ---------------------------------------------------------------------------
# Repeated recovery: the second failure must know about the first (Doc 04 §14)
# ---------------------------------------------------------------------------
async def test_second_failure_triggers_a_second_governed_recovery(container, enterprise):
    """SUP-A goes down, ACC switches to SUP-B, then SUP-B goes down too."""
    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    mission = await _settle(container, mission.mission_id)

    first = await container.store.list_recoveries(mission.mission_id)
    assert len(first) == 1
    assert first[0].selected_parameters["supplier_id"] == "SUP-B"

    # The fallback collapses in turn, while awaiting approval.
    enterprise.suppliers["SUP-B"].failing = True
    pending = await container.approvals.list(mission.mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")
    await container.approvals.decide(purchase.approval_id, True, "operator")
    mission = await _settle(container, mission.mission_id)

    recoveries = await container.store.list_recoveries(mission.mission_id)
    assert len(recoveries) >= 2, "un second échec doit produire une seconde recovery"

    second = recoveries[-1]
    assert second.attempt == len(recoveries)
    # SUP-C is still out of deadline: no autonomous switch is permitted.
    assert second.selected_option in {
        RecoveryStrategy.ESCALATE, RecoveryStrategy.WAIT_AND_REASSESS,
    }
    # Every recovery stays governed: none short-circuited policy.
    assert all(r.policy_decision_id for r in recoveries)
    assert not enterprise.purchases


async def test_recovery_context_carries_previous_attempts(container, enterprise):
    """The Failure Twin must not replay an already exhausted strategy."""
    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    mission = await _settle(container, mission.mission_id)

    invocation = await container.recovery._build_invocation(  # noqa: SLF001
        mission, None, "SUP-B", FailureClass.DEPENDENCY, "503",
        await container.store.list_recoveries(mission.mission_id),
    )
    payload = invocation.to_prompt_payload()
    assert payload["previous_recovery_attempts"]
    assert payload["previous_recovery_attempts"][0]["strategy"] == (
        "USE_ALTERNATIVE_SUPPLIER"
    )
    assert payload["policy_boundaries"]["default"] == "DENY"


async def test_retry_observes_a_corrected_world(container, enterprise):
    """The exact case encountered: the operator fixes things, the mission must go on.

    Volume 1501 > SUP-A capacity (1500) => failure, escalation. The operator
    raises capacity then approves the retry: the new attempt must see 3000
    units, not the value cached on the first read.
    """
    mission = await container.engine.create_mission(
        "Serie renforcee", context_overrides={"required_units": 1501})
    await container.engine.start(mission.mission_id)
    mission = await _settle(container, mission.mission_id)
    assert mission.status is MissionStatus.WAITING_APPROVAL

    # The operator fixes the real world.
    enterprise.suppliers["SUP-A"].capacity_units = 3000

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    escalation = next(a for a in pending if a.action == "recovery.apply")
    await container.approvals.decide(escalation.approval_id, True, "operator")
    await _settle(container, mission.mission_id)

    executions = await container.store.list_executions(mission.mission_id)
    supply_runs = [e for e in executions if e.agent_id == "supply-agent"]
    assert len(supply_runs) >= 2
    assert supply_runs[-1].result is not None
    assert "3000" in supply_runs[-1].result.finding, (
        "la nouvelle tentative doit observer la capacité corrigée"
    )

    tasks = {t.type: t for t in await container.store.list_tasks(mission.mission_id)}
    assert tasks["supply_analysis"].status is TaskStatus.COMPLETED
    assert tasks["risk_assessment"].status is TaskStatus.COMPLETED

    audits = await container.store.list_audit(mission.mission_id)
    replayed_reads = [a for a in audits
                      if a.result == "REPLAYED" and a.action != "purchase.execute"]
    assert not replayed_reads, f"lectures rejouées depuis le cache : {replayed_reads}"


# ---------------------------------------------------------------------------
# Unchanged situation: do not endlessly re-ask the same question
#
# Usage regression: the operator approved THREE identical escalations, on a
# strictly unchanged world state, before the mission failed. Every retry was
# doomed to the same failure, and the Failure Twin re-proposed the same plan
# without ever noticing nothing had moved.
# ---------------------------------------------------------------------------
async def test_unchanged_situation_stops_asking_the_same_question(container):
    """Nothing changed => explicit abort, not an n-th approval."""
    mission = await container.engine.create_mission(
        "Serie renforcee", context_overrides={"required_units": 1501})
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    approvals_given = 0
    for _ in range(6):
        current = await container.store.get_mission(mission.mission_id)
        if current.status.is_terminal:
            break
        pending = await container.approvals.list(mission.mission_id, "PENDING")
        assert pending, "ni terminal, ni décision possible"
        await container.approvals.decide(pending[0].approval_id, True, "operator")
        approvals_given += 1
        await _settle(container, mission.mission_id)

    final = await container.store.get_mission(mission.mission_id)
    assert final.status is MissionStatus.FAILED
    assert approvals_given <= 2, (
        f"{approvals_given} approbations pour un état inchangé : ACC repose la "
        "même question au lieu de constater que rien n'a bougé"
    )

    timeline = await container.traces.timeline(mission.mission_id)
    assert any("unchanged" in e["message"].lower() or "identical" in e["message"].lower()
               for e in timeline), "the abort reason must be readable"


async def test_a_corrected_world_still_completes_the_mission(container, enterprise):
    """The guard must not stop a legitimate retry from succeeding."""
    mission = await container.engine.create_mission(
        "Serie renforcee", context_overrides={"required_units": 1501})
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    # The operator actually fixes the environment before approving.
    enterprise.suppliers["SUP-A"].capacity_units = 3000

    for _ in range(6):
        current = await container.store.get_mission(mission.mission_id)
        if current.status.is_terminal:
            break
        pending = await container.approvals.list(mission.mission_id, "PENDING")
        if not pending:
            break
        await container.approvals.decide(pending[0].approval_id, True, "operator")
        await _settle(container, mission.mission_id)

    final = await container.store.get_mission(mission.mission_id)
    assert final.status is MissionStatus.COMPLETED, (
        "une correction réelle du monde doit permettre à la mission d'aboutir"
    )
    assert final.context.purchase_id


async def test_repeated_approval_requests_carry_their_history(container):
    """A second request must be distinguishable from the first in its evidence."""
    mission = await container.engine.create_mission(
        "Serie renforcee", context_overrides={"required_units": 1501})
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    first = (await container.approvals.list(mission.mission_id, "PENDING"))[0]
    await container.approvals.decide(first.approval_id, True, "operator")
    await _settle(container, mission.mission_id)

    later = [a for a in await container.approvals.list(mission.mission_id)
             if a.approval_id != first.approval_id]
    if later:
        assert any("attempt" in e for e in later[0].evidence), (
            "la demande répétée doit indiquer qu'elle en suit une autre"
        )


async def test_abort_is_not_submitted_for_approval(container):
    """An abort is observed; it is not authorised."""
    from domain.enums import RecoveryStatus, RecoveryStrategy as Strategy

    mission = await container.engine.create_mission(
        "Serie", context_overrides={"required_units": 1501})
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    # A single approved escalation is enough to reach the abort.
    pending = await container.approvals.list(mission.mission_id, "PENDING")
    await container.approvals.decide(pending[0].approval_id, True, "operator")
    await _settle(container, mission.mission_id)

    final = await container.store.get_mission(mission.mission_id)
    assert final.status is MissionStatus.FAILED
    assert final.current_stage == "situation_unchanged"

    # No extra approval was demanded in order to abort.
    assert len(await container.approvals.list(mission.mission_id)) == 1

    recoveries = await container.store.list_recoveries(mission.mission_id)
    abort = recoveries[-1]
    assert abort.selected_option is Strategy.ABORT
    # A deliberate abort is not a recovery malfunction.
    assert abort.status is RecoveryStatus.ABORTED

    # The decision is still traced by the Policy Engine.
    decisions = await container.store.list_policy_decisions(mission.mission_id)
    assert any(d.action == "recovery.abort" for d in decisions)


async def test_dependency_failure_does_not_blame_the_agent(container, enterprise):
    """A dead supplier must not make the agent look broken."""
    from domain.enums import AgentStatus

    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    supply = await container.registry.get("supply-agent")
    assert supply.status is AgentStatus.AVAILABLE, (
        "le Supply Agent a correctement détecté et signalé la panne : "
        "le dégrader dirigerait l'opérateur vers le mauvais problème"
    )

    health = await container.registry.health()
    assert health["degraded"] == 0


async def test_escalation_is_not_counted_as_a_successful_recovery(container):
    """Escalating is handing off — not restoring the mission."""
    mission = await container.engine.create_mission(
        "Serie", context_overrides={"required_units": 1601})
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    await container.approvals.decide(pending[0].approval_id, True, "operator")
    await _settle(container, mission.mission_id)

    metrics = await container.metrics.for_mission(mission.mission_id)
    assert metrics.recovery_attempts >= 2
    assert metrics.recovery_success == 0, (
        "aucune recovery n'a rétabli la mission : le compteur ne doit pas "
        "être gonflé par les escalades et les abandons"
    )


async def test_rejection_closes_the_pending_recovery(container):
    """A terminal mission must contain no "in progress" state.

    Usage regression: after a rejection the trace showed "Failure Twin —
    IN_PROGRESS" on a FAILED mission, its duration stayed incomputable for lack
    of `completed_at`, and `pending_approval_id` still pointed at an already
    decided request.
    """
    from domain.enums import RecoveryStatus

    mission = await container.engine.create_mission(
        "Serie", context_overrides={"required_units": 1701})
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    await container.approvals.decide(pending[0].approval_id, False, "operator", "Non")
    final = await _settle(container, mission.mission_id)

    assert final.status is MissionStatus.FAILED
    assert final.current_stage == "safe_hold"
    assert final.pending_approval_id is None, (
        "une mission close ne doit pas désigner une approbation en attente"
    )

    recoveries = await container.store.list_recoveries(mission.mission_id)
    assert recoveries
    for recovery in recoveries:
        assert recovery.status is not RecoveryStatus.IN_PROGRESS, (
            "recovery restée « en cours » sur une mission terminée"
        )
        assert recovery.completed_at is not None, (
            "sans completed_at, la durée de recovery est incalculable"
        )

    metrics = await container.metrics.for_mission(mission.mission_id)
    assert metrics.recovery_duration_s is not None


async def test_terminal_missions_have_no_dangling_state(container, enterprise):
    """General invariant: nothing stays "in progress" after a mission ends."""
    from domain.enums import RecoveryStatus, TaskStatus as TS

    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    purchase = next(a for a in pending if a.action == "purchase.execute")
    await container.approvals.decide(purchase.approval_id, False, "operator")
    final = await _settle(container, mission.mission_id)

    assert final.status.is_terminal
    assert final.pending_approval_id is None
    assert not [t for t in await container.store.list_tasks(mission.mission_id)
                if t.status is TS.RUNNING]
    assert not [r for r in await container.store.list_recoveries(mission.mission_id)
                if r.status is RecoveryStatus.IN_PROGRESS]
    assert not await container.approvals.list(mission.mission_id, "PENDING")


async def test_a_terminal_mission_cannot_be_interrupted(container):
    """A timeline must not contain an event that never happened.

    Regression: "Kill the runtime" answered 200 on an already finished mission
    and published `runtime.interrupted` in its timeline. An audit trail
    containing invented facts proves nothing.
    """
    from domain.errors import InvalidState

    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    final = await _settle(container, mission.mission_id)
    assert final.status is MissionStatus.COMPLETED

    with pytest.raises(InvalidState):
        await container.engine.interrupt(mission.mission_id)

    timeline = await container.traces.timeline(mission.mission_id)
    assert not [e for e in timeline if e["type"] == "runtime.interrupted"]


async def test_a_terminal_mission_cannot_be_resumed(container):
    from domain.errors import InvalidState

    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    with pytest.raises(InvalidState):
        await container.engine.resume(mission.mission_id)


async def test_a_live_mission_can_still_be_interrupted(container, enterprise):
    """The guard must not break the resume demonstration."""
    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    interrupted = await container.engine.interrupt(mission.mission_id)
    assert not interrupted.status.is_terminal

    timeline = await container.traces.timeline(mission.mission_id)
    assert [e for e in timeline if e["type"] == "runtime.interrupted"]

    resumed = await container.engine.resume(mission.mission_id)
    assert resumed.status is MissionStatus.WAITING_APPROVAL
