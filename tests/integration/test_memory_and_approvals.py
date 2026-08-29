"""Isolation memoire et durabilite de l'autorite humaine (Doc 04 §10, §20)."""
from __future__ import annotations

import pytest

from domain.enums import ApprovalStatus, MemoryType, Sensitivity
from domain.errors import InvalidState, PolicyDenied
from domain.models import AgentIdentity, PolicyDecision
from domain.enums import PolicyDecisionValue


async def test_memory_is_scoped_to_its_mission(container):
    a = await container.engine.create_mission("Mission A")
    b = await container.engine.create_mission("Mission B")
    await container.memory.write(a.mission_id, MemoryType.DECISION,
                                 {"secret": "fournisseur A"}, source="test")

    recall_b = await container.memory.recall_for_agent(b, "supply-agent", b.mission_id)
    assert not any("fournisseur A" in entry for entry in recall_b)

    with pytest.raises(PolicyDenied):
        await container.memory.recall_for_agent(a, "supply-agent", b.mission_id)


async def test_confidential_memory_never_reaches_an_agent(container):
    mission = await container.engine.create_mission("Mission")
    await container.memory.write(
        mission.mission_id, MemoryType.EVIDENCE, {"pii": "IBAN FR76..."},
        source="test", sensitivity=Sensitivity.RESTRICTED,
    )
    recall = await container.memory.recall_for_agent(
        mission, "supply-agent", mission.mission_id)
    assert not any("IBAN" in entry for entry in recall)


def _decision(mission_id: str) -> PolicyDecision:
    return PolicyDecision(mission_id=mission_id, agent_id="procurement-agent",
                          action="purchase.execute",
                          decision=PolicyDecisionValue.APPROVAL_REQUIRED,
                          reason="au-dela du seuil")


async def test_agent_cannot_approve_its_own_action(container):
    mission = await container.engine.create_mission("Mission")
    identity = AgentIdentity(agent_id="procurement-agent", agent_version="1.0.0",
                             execution_id="EXE-1", mission_id=mission.mission_id)
    approval = await container.approvals.request(
        identity, "purchase.execute", _decision(mission.mission_id), amount=18_000.0)

    with pytest.raises(InvalidState):
        await container.approvals.decide(approval.approval_id, True, "procurement-agent")


async def test_approval_cannot_be_decided_twice(container):
    mission = await container.engine.create_mission("Mission")
    identity = AgentIdentity(agent_id="procurement-agent", agent_version="1.0.0",
                             execution_id="EXE-1", mission_id=mission.mission_id)
    approval = await container.approvals.request(
        identity, "purchase.execute", _decision(mission.mission_id), amount=18_000.0)

    await container.approvals.decide(approval.approval_id, True, "operator")
    with pytest.raises(InvalidState):
        await container.approvals.decide(approval.approval_id, False, "operator")


async def test_approval_survives_as_durable_state(container):
    """An approval is not a UI session: it lives in the store."""
    mission = await container.engine.create_mission("Mission")
    identity = AgentIdentity(agent_id="procurement-agent", agent_version="1.0.0",
                             execution_id="EXE-1", mission_id=mission.mission_id)
    approval = await container.approvals.request(
        identity, "purchase.execute", _decision(mission.mission_id), amount=18_000.0)

    reloaded = await container.store.get_approval(approval.approval_id)
    assert reloaded.status is ApprovalStatus.PENDING
    assert reloaded.expires_at is not None
    assert reloaded.amount == 18_000.0
