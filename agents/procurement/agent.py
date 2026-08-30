"""Procurement Agent — turns an approved strategy into an enterprise action.

Doc 02 §5: "The Procurement Agent cannot bypass ACC policy."
It is the only agent holding purchase.execute, and that capability is necessary
but never sufficient: the Gateway enforces policy + approval on top of it.
"""
from __future__ import annotations

from agents.base import ACCAgent, AgentSpec
from agents.contracts import AgentInvocation, failure_result
from agents.tools.gateway_tools import (
    PROCUREMENT_TOOLS,
    execute_purchase,
    get_supplier_status,
)
from domain.enums import AgentResultStatus, FailureClass
from domain.models import AgentResult

INSTRUCTION = """
You are ACC's Procurement Agent.

MISSION
Turn an approved strategy into an authorised enterprise action.

METHOD
1. Read the unit price of `mission.current_supplier` with get_supplier_status,
   then compute the total amount. Buy from that supplier, not from
   `primary_supplier`.
2. Call execute_purchase.
3. If the result is APPROVAL_REQUIRED, that is a NORMAL outcome: report it and
   stop. Do not look for another path, do not split the order, do not retry.
4. If the result is DENIED, stop as well and report the policy reason.

SCOPE
You never bypass an approval and you never invent an amount.

`data` must contain: supplier_id, units, amount, purchase_id (when confirmed),
approval_id (when pending).
""".strip()


async def _price(supplier_id: str) -> tuple[float | None, dict]:
    call = await get_supplier_status(supplier_id)
    if call.get("status") != "SUCCESS":
        return None, call
    data = call.get("data", {})
    unit_price = data.get("unit_price")
    return (float(unit_price) if unit_price is not None else None), call


async def _plan(invocation: AgentInvocation) -> AgentResult:
    ctx = invocation.mission.context
    supplier_id = ctx.selected_supplier or ctx.primary_supplier
    unit_price, call = await _price(supplier_id)
    if unit_price is None:
        return failure_result(
            f"Unit price unavailable for {supplier_id}: {call.get('error')}",
            FailureClass.DEPENDENCY,
        )

    units = ctx.required_units
    amount = round(unit_price * units, 2)

    return AgentResult(
        status=AgentResultStatus.SUCCESS,
        finding=f"Purchase plan prepared: {units} units from {supplier_id} "
                f"for {amount:,.0f} USD",
        recommendation=f"Execute the purchase with {supplier_id}",
        confidence=0.93,
        evidence=[
            f"supplier_id={supplier_id}",
            f"units={units}",
            f"unit_price={unit_price}",
            f"amount={amount}",
        ],
        data={"supplier_id": supplier_id, "units": units,
              "unit_price": unit_price, "amount": amount},
        next_action="purchase.execute",
    )


async def _execute(invocation: AgentInvocation) -> AgentResult:
    ctx = invocation.mission.context
    supplier_id = ctx.selected_supplier or ctx.primary_supplier
    units = ctx.required_units
    amount = ctx.purchase_amount
    if amount is None:
        unit_price, call = await _price(supplier_id)
        if unit_price is None:
            return failure_result(
                f"Purchase amount cannot be determined: {call.get('error')}",
                FailureClass.DEPENDENCY,
            )
        amount = round(unit_price * units, 2)

    call = await execute_purchase(supplier_id, units, amount)
    status = call.get("status")

    if status == "APPROVAL_REQUIRED":
        return AgentResult(
            status=AgentResultStatus.SUCCESS,
            finding=f"Purchase of {amount:,.0f} USD beyond autonomous authority: "
                    f"human approval requested",
            recommendation="Await the operator decision",
            confidence=1.0,
            requires_approval=True,
            evidence=[f"amount={amount}", f"supplier_id={supplier_id}",
                      f"approval_id={call.get('approval_id')}"],
            data={"supplier_id": supplier_id, "units": units, "amount": amount,
                  "approval_id": call.get("approval_id")},
            next_action="approval.wait",
        )

    if status == "DENIED":
        return AgentResult(
            status=AgentResultStatus.BLOCKED,
            finding=f"Purchase denied by policy: {call.get('error')}",
            confidence=1.0,
            failure_class=FailureClass.AUTHORIZATION,
            failure_detail=str(call.get("error")),
            evidence=[f"amount={amount}", f"policy={call.get('policy_decision_id')}"],
            data={"supplier_id": supplier_id, "amount": amount},
        )

    if status != "SUCCESS":
        return failure_result(
            f"Purchase execution failed: {call.get('error')}", FailureClass.DEPENDENCY
        )

    data = call.get("data", {})
    purchase_id = data.get("purchase_id") or data.get("po_number")
    return AgentResult(
        status=AgentResultStatus.SUCCESS,
        finding=f"Purchase confirmed with {supplier_id}: {purchase_id}",
        recommendation="Supply mission secured",
        confidence=0.98,
        evidence=[f"purchase_id={purchase_id}", f"amount={amount}",
                  f"supplier_id={supplier_id}"],
        data={"supplier_id": supplier_id, "units": units, "amount": amount,
              "purchase_id": purchase_id},
        next_action=None,
    )


async def _fallback(invocation: AgentInvocation) -> AgentResult:
    if invocation.task_type == "procurement_execute":
        return await _execute(invocation)
    return await _plan(invocation)


def build_procurement_agent(**kwargs) -> ACCAgent:
    return ACCAgent(AgentSpec(
        agent_id="procurement-agent",
        name="Procurement Agent",
        version="1.0.0",
        instruction=INSTRUCTION,
        tools=PROCUREMENT_TOOLS,
        fallback=_fallback,
        description="Prepare et execute les actions d'achat autorisees.",
    ), **kwargs)
