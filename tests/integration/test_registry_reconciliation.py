"""A redeployment must be able to correct what the code declares.

Observed on the deployed instance: the fleet panel showed `4 capabilities` for
Supply Agent while the source declared 3, and the trace kept reporting

    production.read  DENIED  Capability missing from the registry

for a capability the source had granted. The registry lives in Firestore and
`bootstrap()` returned the stored record untouched whenever the agent existed,
so no deployment could ever fix it.

In a project whose argument is that the registry governs authority, a registry
no deployment can update is the wrong kind of durable.
"""
from __future__ import annotations

import pytest

from domain.enums import AgentStatus


async def test_capabilities_are_corrected_on_redeploy(container):
    """The exact deployed symptom: a stale capability set."""
    record = await container.registry.get("supply-agent")
    record.capabilities = ["supplier.read", "supplier.capacity",
                           "supplier.status", "supplier.alternatives"]
    await container.store.save_agent(record)

    await container.registry.bootstrap()

    reconciled = await container.registry.get("supply-agent")
    assert "production.read" in reconciled.capabilities, (
        "a redeployment did not restore the declared capabilities"
    )
    assert "supplier.read" not in reconciled.capabilities, (
        "a capability removed from the code must disappear from the registry"
    )


async def test_a_suspended_agent_stays_suspended(container):
    """Operational state belongs to the fleet, not to the code.

    Fleet governance (Doc 02 §22) means a revoked agent stays revoked. A
    bootstrap that reset every status would silently re-admit an agent an
    operator had removed.
    """
    record = await container.registry.get("procurement-agent")
    record.status = AgentStatus.SUSPENDED
    await container.store.save_agent(record)

    await container.registry.bootstrap()

    assert (await container.registry.get("procurement-agent")).status \
        is AgentStatus.SUSPENDED


async def test_reconciliation_is_silent_when_nothing_changed(container, caplog):
    """A redeploy that changes nothing must not look like a change."""
    await container.registry.bootstrap()
    caplog.clear()
    await container.registry.bootstrap()

    assert not [r for r in caplog.records
                if r.getMessage() == "agent_declaration_reconciled"]


@pytest.mark.parametrize("agent_id", [
    "supply-agent", "risk-agent", "procurement-agent", "failure-twin",
])
async def test_declared_authority_survives_a_redeploy(agent_id, container):
    """Authority level and denied capabilities are code, not stored opinion."""
    record = await container.registry.get(agent_id)
    record.denied_capabilities = []
    record.authority_level = "AUTONOMOUS"
    await container.store.save_agent(record)

    await container.registry.bootstrap()

    reconciled = await container.registry.get(agent_id)
    assert reconciled.denied_capabilities, (
        f"{agent_id} lost its explicit denials on redeploy"
    )
