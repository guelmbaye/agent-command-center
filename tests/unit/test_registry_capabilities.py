"""Declared capabilities must match the tools an agent actually holds.

Found on the deployed instance, in `hybrid` mode:

    get_supplier_status failed with CAPABILITY_DENIED for agent failure-twin
    get_production_schedule failed with CAPABILITY_DENIED for agent failure-twin

Every one of the four agents was missing at least one capability its tools
invoke, and seven declared capabilities matched no tool at all.

Deterministic mode hid it completely: it calls a fixed subset. Only a model
choosing its own tools reaches the gaps — so the defect appeared for the first
time in the deployed demo.
"""
from __future__ import annotations

import inspect
import re

import pytest

import agents.tools.gateway_tools as gateway_tools

# Capabilities exercised by reasoning, with no enterprise tool behind them.
REASONING_ONLY = {
    "recovery.diagnose", "recovery.plan", "recovery.apply", "recovery.abort",
}


def _tool_capabilities() -> dict[str, str]:
    """Map each ADK tool function to the capability it requests."""
    source = inspect.getsource(gateway_tools)
    mapping: dict[str, str] = {}
    for match in re.finditer(
        r"async def (\w+)\(.*?\n(.*?)(?=\nasync def |\Z)", source, re.S
    ):
        capabilities = re.findall(r'"([a-z]+\.[a-z_]+)"', match.group(2))
        if capabilities:
            mapping[match.group(1)] = capabilities[0]
    return mapping


@pytest.fixture
def fleet(container):
    return container


AGENTS = ["supply-agent", "risk-agent", "procurement-agent", "failure-twin"]


@pytest.mark.parametrize("agent_id", AGENTS)
async def test_every_tool_has_its_capability(agent_id, container):
    """A tool without its capability is a CAPABILITY_DENIED at runtime."""
    mapping = _tool_capabilities()
    agent = container.runtime.get(agent_id)
    record = await container.registry.get(agent_id)

    needed = {mapping[tool.__name__] for tool in agent.spec.tools
              if tool.__name__ in mapping}
    missing = needed - set(record.capabilities)
    assert not missing, (
        f"{agent_id} holds tools requiring {sorted(missing)} but does not "
        f"declare them: the Gateway will refuse the call"
    )


@pytest.mark.parametrize("agent_id", AGENTS)
async def test_no_capability_without_a_tool(agent_id, container):
    """Least privilege: a capability matching no tool is unjustified authority."""
    mapping = _tool_capabilities()
    agent = container.runtime.get(agent_id)
    record = await container.registry.get(agent_id)

    needed = {mapping[tool.__name__] for tool in agent.spec.tools
              if tool.__name__ in mapping}
    extra = set(record.capabilities) - needed - REASONING_ONLY
    assert not extra, (
        f"{agent_id} declares {sorted(extra)} with no tool behind them"
    )


async def test_no_agent_declares_a_capability_it_is_denied(container):
    """A capability both granted and denied is a contradiction in the registry."""
    for agent_id in AGENTS:
        record = await container.registry.get(agent_id)
        overlap = set(record.capabilities) & set(record.denied_capabilities)
        assert not overlap, f"{agent_id}: {sorted(overlap)} both granted and denied"


async def test_only_procurement_can_purchase(container):
    """The whole authority story rests on this one being true."""
    for agent_id in AGENTS:
        record = await container.registry.get(agent_id)
        holds = "purchase.execute" in record.capabilities
        assert holds == (agent_id == "procurement-agent"), (
            f"{agent_id} should {'' if agent_id == 'procurement-agent' else 'not '}"
            f"hold purchase.execute"
        )
