"""One mission must not place two purchase orders.

Observed on the deployed instance, in `hybrid` mode:

    19:32:51  Purchase order PO-8831 for 1200 units from SUP-A ... $4800.00
    19:33:00  Purchase order PO-8832 for 1200 units from SUP-A ... $4800.00
    Duplicates prevented: 0

Two real purchase orders for one mission — against the product's first claim,
"a resumable agent never orders twice".

The idempotency key contained the TASK id. A mission is decomposed into a
planning task and an execution task; the model chose to purchase from both, and
two tasks meant two keys. Deterministic mode hid it completely: only the
execution task purchases there.
"""
from __future__ import annotations

import pytest

from apps.api.services.agent_gateway import GatewayRequest
from domain.models import AgentIdentity


def _request(task_id: str, supplier: str = "SUP-A", amount: float = 4800.0):
    return GatewayRequest(
        identity=AgentIdentity(
            agent_id="procurement-agent", agent_version="1.0.0",
            execution_id=f"EXE-{task_id}", mission_id="MIS-1001",
            task_id=task_id,
        ),
        capability="purchase.execute",
        parameters={"supplier_id": supplier, "units": 1200, "amount": amount},
        amount=amount,
    )


async def test_two_tasks_cannot_place_two_identical_orders(container, enterprise):
    """The exact deployed failure: planning task, then execution task."""
    first = await container.gateway.execute(_request("TASK-3"))
    second = await container.gateway.execute(_request("TASK-4"))

    assert first.status == "SUCCESS", first.error
    assert second.status == "SUCCESS", second.error

    orders = enterprise.purchases
    assert len(orders) == 1, (
        f"{len(orders)} purchase orders placed for one mission: "
        f"{sorted(orders)}"
    )
    assert second.replayed is True, "the second call must be served from cache"


async def test_a_different_supplier_is_a_different_action(container, enterprise):
    """Recovery legitimately buys elsewhere: that must NOT be deduplicated.

    Both amounts stay under the autonomous threshold on purpose. A fallback at
    18 000 $ would be refused by POLICY, and the test would pass or fail for a
    reason that has nothing to do with idempotency.
    """
    first = await container.gateway.execute(_request("TASK-4", supplier="SUP-A"))
    second = await container.gateway.execute(
        _request("TASK-7", supplier="SUP-B", amount=4900.0))
    assert first.status == "SUCCESS" and second.status == "SUCCESS", (
        f"{first.error} / {second.error}"
    )

    suppliers = {order["supplier_id"] for order in enterprise.purchases.values()}
    assert suppliers == {"SUP-A", "SUP-B"}, (
        "a fallback purchase after recovery was wrongly deduplicated"
    )


async def test_a_retry_of_the_same_action_is_deduplicated(container, enterprise):
    """Same task, same action: the original guarantee still holds."""
    await container.gateway.execute(_request("TASK-4"))
    await container.gateway.execute(_request("TASK-4"))

    assert len(enterprise.purchases) == 1
