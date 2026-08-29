"""The Gateway is the ONLY door to the enterprise (Doc 03 §10, Doc 07 §11)."""
from __future__ import annotations

import pytest

from apps.api.services.agent_gateway import GatewayRequest
from domain.enums import RiskLevel
from domain.errors import CapabilityDenied, IdentityUnverified
from domain.models import AgentIdentity


def identity(agent_id="procurement-agent", **kw) -> AgentIdentity:
    base = dict(agent_id=agent_id, agent_version="1.0.0", execution_id="EXE-TEST",
                mission_id="MIS-TEST", task_id="TASK-TEST")
    base.update(kw)
    return AgentIdentity(**base)


async def test_read_capability_reaches_the_tool(container):
    result = await container.gateway.execute(GatewayRequest(
        identity("supply-agent"), "supplier.status", {"supplier_id": "SUP-A"},
        resource="SUP-A",
    ))
    assert result.status == "SUCCESS"
    assert result.result["supplier_id"] == "SUP-A"
    assert result.policy_decision_id


async def test_agent_without_capability_is_refused(container):
    """supply-agent a purchase.execute en denied_capabilities."""
    with pytest.raises(CapabilityDenied):
        await container.gateway.execute(GatewayRequest(
            identity("supply-agent"), "purchase.execute",
            {"supplier_id": "SUP-A", "units": 10, "amount": 100.0}, amount=100.0,
        ))


async def test_incomplete_identity_is_refused(container):
    with pytest.raises(IdentityUnverified):
        await container.gateway.execute(GatewayRequest(
            AgentIdentity(agent_id="supply-agent", agent_version="1",
                          execution_id="", mission_id=""),
            "supplier.status", {"supplier_id": "SUP-A"},
        ))


async def test_suspended_agent_cannot_execute(container):
    await container.registry.suspend("supply-agent", "test")
    with pytest.raises(Exception) as exc:
        await container.gateway.execute(GatewayRequest(
            identity("supply-agent"), "supplier.status", {"supplier_id": "SUP-A"},
        ))
    assert "not cleared" in str(exc.value)


async def test_purchase_above_threshold_returns_approval_required(container):
    result = await container.gateway.execute(GatewayRequest(
        identity(), "purchase.execute",
        {"supplier_id": "SUP-B", "units": 1200, "amount": 18_000.0},
        resource="SUP-B", amount=18_000.0, risk_level=RiskLevel.HIGH,
    ))
    assert result.status == "APPROVAL_REQUIRED"
    assert result.approval_id
    # No purchase reached the enterprise system.
    from mock_enterprise.state import STATE
    assert not STATE.purchases


async def test_purchase_above_ceiling_is_denied(container):
    result = await container.gateway.execute(GatewayRequest(
        identity(), "purchase.execute",
        {"supplier_id": "SUP-B", "units": 99_999, "amount": 90_000.0},
        resource="SUP-B", amount=90_000.0,
    ))
    assert result.status == "DENIED"
    assert result.error_code == "POLICY_DENIED"


async def test_idempotency_prevents_double_purchase(container):
    """"Why a resumable agent might order two laptops" (Doc 08 §27)."""
    from mock_enterprise.state import STATE
    request = GatewayRequest(
        identity(), "purchase.execute",
        {"supplier_id": "SUP-A", "units": 1200, "amount": 4_800.0},
        resource="SUP-A", amount=4_800.0,
    )
    first = await container.gateway.execute(request)
    second = await container.gateway.execute(request)

    assert first.status == "SUCCESS" and not first.replayed
    assert second.status == "SUCCESS" and second.replayed
    assert len(STATE.purchases) == 1
    assert second.result["purchase_id"] == first.result["purchase_id"]


async def test_tool_poisoning_is_neutralised(container, enterprise):
    """Hostile content from an external system does not redefine authority."""
    enterprise.suppliers["SUP-B"].poisoned = True
    result = await container.gateway.execute(GatewayRequest(
        identity("supply-agent"), "supplier.status", {"supplier_id": "SUP-B"},
        resource="SUP-B",
    ))
    assert result.status == "SUCCESS"          # la mission continue
    assert result.result["_armor"]["blocked"]  # mais l'instruction est neutralisee
    assert "message" not in result.result
    security = await container.store.list_security_events("MIS-TEST")
    assert any(e.type.value == "MODEL_THREAT_DETECTED" for e in security)


async def test_tool_failure_is_classified(container, enterprise):
    enterprise.suppliers["SUP-A"].failing = True
    result = await container.gateway.execute(GatewayRequest(
        identity("supply-agent"), "supplier.status", {"supplier_id": "SUP-A"},
        resource="SUP-A",
    ))
    assert result.status == "FAILED"
    assert result.error_code == "TOOL_UNAVAILABLE"


async def test_every_call_leaves_an_audit_record(container):
    await container.gateway.execute(GatewayRequest(
        identity("supply-agent"), "supplier.status", {"supplier_id": "SUP-A"},
    ))
    audits = await container.store.list_audit("MIS-TEST")
    assert len(audits) == 1
    entry = audits[0]
    assert entry.agent_id == "supply-agent"
    assert entry.action == "supplier.status"
    assert entry.policy_decision is not None
    assert entry.result == "SUCCESS"


# ---------------------------------------------------------------------------
# Idempotency scope
#
# Major regression observed in use: idempotency applied to EVERY capability,
# reads included. A retry therefore replayed the cached answer — the operator
# could fix the real world (raised capacity, supplier back online) and the
# agent would never see it. Recovery became structurally unable to succeed.
# ---------------------------------------------------------------------------
async def test_reads_are_never_replayed_from_cache(container, enterprise):
    """A read must re-observe the world; that is its entire purpose."""
    identity_ = identity("supply-agent")

    first = await container.gateway.execute(GatewayRequest(
        identity_, "supplier.status", {"supplier_id": "SUP-A"}, resource="SUP-A"))
    assert first.result["capacity_units"] == 1500
    assert not first.replayed

    # The world changes between the two reads.
    enterprise.suppliers["SUP-A"].capacity_units = 3000

    second = await container.gateway.execute(GatewayRequest(
        identity_, "supplier.status", {"supplier_id": "SUP-A"}, resource="SUP-A"))
    assert not second.replayed, "une lecture ne doit jamais venir du cache"
    assert second.result["capacity_units"] == 3000, (
        "l'agent doit voir la correction, sinon aucune recovery ne peut aboutir"
    )


async def test_purchases_are_still_protected_against_duplication(container, enterprise):
    """The fix must not weaken double-purchase protection."""
    request = GatewayRequest(
        identity(), "purchase.execute",
        {"supplier_id": "SUP-A", "units": 1200, "amount": 4_800.0},
        resource="SUP-A", amount=4_800.0,
    )
    first = await container.gateway.execute(request)
    second = await container.gateway.execute(request)

    assert first.status == "SUCCESS" and not first.replayed
    assert second.status == "SUCCESS" and second.replayed
    assert len(enterprise.purchases) == 1
