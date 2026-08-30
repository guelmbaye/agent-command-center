"""Supply Agent — an accurate picture of supplier availability (Doc 02 §3).

It never executes a purchase.
"""
from __future__ import annotations

from agents.base import ACCAgent, AgentSpec
from agents.contracts import AgentInvocation, failure_result
from agents.tools.gateway_tools import (
    SUPPLY_TOOLS,
    get_production_schedule,
    get_supplier_status,
)
from domain.enums import AgentResultStatus, FailureClass
from domain.models import AgentResult

INSTRUCTION = """
You are ACC's Supply Agent (Autonomous Mission Control).

MISSION
Maintain an accurate picture of supplier availability for the current mission.

METHOD
1. Fetch `mission.current_supplier` status with get_supplier_status. That
   field already accounts for any recovery; never fall back to
   `primary_supplier` yourself.
2. If needed, check the production window with get_production_schedule.
3. If the primary supplier is unavailable, or the tool returns an error, do NOT
   try to solve the problem yourself: that is the Failure Twin's role.
   Return status = RETRYABLE_FAILURE (technical outage, 5xx, timeout) or
   NON_RETRYABLE_FAILURE (supplier definitively out of capacity).
4. You may list alternative candidates, but you do not select them.

SCOPE
You do not compare risks, you do not recommend a purchase, you execute nothing.

`data` must contain: supplier_id, status, capacity_units, capacity_pct,
lead_time_hours, unit_price, candidate_alternatives.
""".strip()


async def _fallback(invocation: AgentInvocation) -> AgentResult:
    ctx = invocation.mission.context
    supplier_id = ctx.selected_supplier or ctx.primary_supplier
    call = await get_supplier_status(supplier_id)

    if call.get("status") != "SUCCESS":
        return failure_result(
            f"Supplier {supplier_id} status unreachable: {call.get('error')}",
            FailureClass.DEPENDENCY,
        )

    data = call.get("data", {})
    status = str(data.get("status", "UNKNOWN")).upper()
    capacity = int(data.get("capacity_units", 0) or 0)
    required = ctx.required_units

    if status != "AVAILABLE" or capacity < required:
        return failure_result(
            f"Supplier {supplier_id} unavailable (status {status}, "
            f"capacity {capacity}/{required})",
            FailureClass.DEPENDENCY,
        )

    return AgentResult(
        status=AgentResultStatus.SUCCESS,
        finding=f"Supplier {supplier_id} available: {capacity} units, "
                f"lead time {data.get('lead_time_hours')}h",
        recommendation=f"Proceed with {supplier_id}",
        confidence=0.94,
        evidence=[
            f"supplier.status={status}",
            f"capacity_units={capacity}",
            f"lead_time_hours={data.get('lead_time_hours')}",
            f"required_units={required}",
        ],
        data={
            "supplier_id": supplier_id,
            "status": status,
            "capacity_units": capacity,
            "capacity_pct": data.get("capacity_pct"),
            "lead_time_hours": data.get("lead_time_hours"),
            "unit_price": data.get("unit_price"),
        },
        next_action="risk.assess",
    )


def build_supply_agent(**kwargs) -> ACCAgent:
    return ACCAgent(AgentSpec(
        agent_id="supply-agent",
        name="Supply Agent",
        version="1.0.0",
        instruction=INSTRUCTION,
        tools=SUPPLY_TOOLS,
        fallback=_fallback,
        description="Analyse la disponibilite et la capacite fournisseur.",
    ), **kwargs)
