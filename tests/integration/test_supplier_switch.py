"""After a recovery switches supplier, the fleet must act on the NEW one.

Observed on the deployed instance, in `hybrid` mode, with SUP-A failing:

    Recovery selected: USE_ALTERNATIVE_SUPPLIER
    Recovery applied:  USE_ALTERNATIVE_SUPPLIER
    Supply Agent activated: Supplier availability analysis
    Tool failure suppliers: HTTP 503          <- SUP-A again
    ... three times ...
    FAILED · recovery_exhausted

The recovery worked. The agent then re-checked the supplier that had just
failed, because the context exposed `primary_supplier` and `selected_supplier`
side by side and the instruction said "the primary supplier". The deterministic
path read `selected or primary` and never showed the defect.
"""
from __future__ import annotations

import pytest

from agents.contracts import AgentInvocation
from domain.models import AgentIdentity


def _invocation(mission, task_type="supply_analysis"):
    return AgentInvocation(
        identity=AgentIdentity(agent_id="supply-agent", agent_version="1.0.0",
                               execution_id="EXE-1", mission_id=mission.mission_id),
        mission=mission, task_type=task_type,
        policy_summary={}, available_capabilities=["supplier.status"],
    )


async def test_context_resolves_the_supplier_for_the_model(container):
    """The precedence rule is applied once, not left to the model."""
    mission = await container.engine.create_mission("Protect production schedule")

    payload = _invocation(mission).to_prompt_payload()
    assert payload["mission"]["current_supplier"] == "SUP-A"

    mission.context.selected_supplier = "SUP-B"
    payload = _invocation(mission).to_prompt_payload()
    assert payload["mission"]["current_supplier"] == "SUP-B", (
        "after a recovery the model must be handed the NEW supplier"
    )
    # History stays available, for evidence and narrative.
    assert payload["mission"]["primary_supplier"] == "SUP-A"


async def test_prompts_forbid_falling_back_to_the_primary(container):
    """A model applying its own precedence rule reproduced the outage."""
    from agents.base import BASE_GUARDRAILS

    assert "current_supplier" in BASE_GUARDRAILS
    assert "primary_supplier" in BASE_GUARDRAILS

    for agent_id in ("supply-agent", "procurement-agent"):
        instruction = container.runtime.get(agent_id).spec.instruction
        assert "current_supplier" in instruction, (
            f"{agent_id} is not told which supplier to act on"
        )


async def test_the_switch_actually_reaches_the_supply_agent(container, enterprise):
    """End to end: SUP-A down, recovery switches, the retry queries SUP-B."""
    enterprise.suppliers["SUP-A"].failing = True

    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=30)

    refreshed = await container.store.get_mission(mission.mission_id)
    assert refreshed.context.selected_supplier == "SUP-B", (
        "recovery did not switch supplier"
    )

    payload = _invocation(refreshed).to_prompt_payload()
    assert payload["mission"]["current_supplier"] == "SUP-B"


# ---------------------------------------------------------------------------
# The switch must SURVIVE the reload
#
# In `deterministic` mode, with the model out of the picture entirely, the
# retry still queried SUP-A:
#
#     Recovery applied: USE_ALTERNATIVE_SUPPLIER   (SUP-B)
#     Supply Agent activated
#     Tool failure suppliers: HTTP 503             <- SUP-A again
#     ... three times ... FAILED · recovery_exhausted
#
# The recovery mutated `mission.context.selected_supplier` and never saved it.
# The Mission Engine reloads the mission before applying the directive, so the
# switch was discarded.
#
# The in-memory store shares object instances, so the mutation was visible
# without a save and every local test passed. Firestore returns a fresh copy —
# the same trap as ADR-008, which is why this test uses a faithful store.
# ---------------------------------------------------------------------------
@pytest.fixture
async def distributed():
    """Container whose persistence behaves like Firestore: reads return copies."""
    import httpx
    from apps.api.services.container import build_container, set_container
    from domain import ids
    from mock_enterprise.main import app as mock_app
    from mock_enterprise.state import STATE
    from tests.conftest import make_settings
    from tests.integration.test_concurrency import FirestoreLikeStore

    ids.reset_counters()
    STATE.reset()
    container = build_container(
        make_settings(), store=FirestoreLikeStore(),
        enterprise_transport=httpx.ASGITransport(app=mock_app),
    )
    set_container(container)
    await container.startup()
    try:
        yield container
    finally:
        await container.shutdown()
        set_container(None)


async def test_the_switch_survives_a_fresh_read(distributed, enterprise):
    """The whole container on a store that returns copies, as Firestore does."""
    enterprise.suppliers["SUP-A"].failing = True

    mission = await distributed.engine.create_mission("Protect production schedule")
    await distributed.engine.start(mission.mission_id)
    await distributed.events.drain(timeout=30)

    reloaded = await distributed.store.get_mission(mission.mission_id)
    assert reloaded.context.selected_supplier == "SUP-B", (
        "the supplier switch did not survive the reload: the retry queries the "
        "supplier that just failed, and the mission burns its attempt budget"
    )
    assert reloaded.status.value != "FAILED", (
        f"mission failed at stage {reloaded.current_stage}"
    )


async def test_the_switch_lands_in_the_store_not_on_the_callers_object(container):
    """The decisive check: inspect the STORE, with a deliberately stale caller.

    Every earlier test passed whether or not the switch was persisted, because
    the in-memory store shares object instances — mutating the caller's mission
    was indistinguishable from saving it. This one hands the recovery an object
    that is NOT the stored one, and then reads the store.
    """
    from domain.enums import RecoveryStrategy
    from domain.models import RecoveryPlan

    mission = await container.engine.create_mission("Protect production schedule")
    stale = (await container.store.get_mission(mission.mission_id)).model_copy(deep=True)

    plan = RecoveryPlan(
        diagnosis="SUP-A unreachable", impact="HIGH",
        options=[], selected_strategy=RecoveryStrategy.USE_ALTERNATIVE_SUPPLIER,
        selected_parameters={"supplier_id": "SUP-B", "unit_price": 15.0},
        rationale="only permitted option",
    )
    from domain.models import RecoveryAttempt

    attempt = RecoveryAttempt(mission_id=mission.mission_id,
                              failure_event_id="EVT-1",
                              diagnosis=plan.diagnosis, impact=plan.impact)
    await container.recovery._apply(stale, None, plan, attempt)

    stored = await container.store.get_mission(mission.mission_id)
    assert stored.context.selected_supplier == "SUP-B", (
        "the switch stayed on the caller's object and never reached the store"
    )
    assert stored.context.purchase_amount == 18000.0
