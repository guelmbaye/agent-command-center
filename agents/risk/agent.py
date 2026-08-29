"""Risk Agent — conseille, n'autorise pas (Doc 02 §4)."""
from __future__ import annotations

from agents.base import ACCAgent, AgentSpec
from agents.contracts import AgentInvocation, failure_result
from agents.tools.gateway_tools import RISK_TOOLS, assess_supplier_risk
from domain.enums import AgentResultStatus, FailureClass
from domain.models import AgentResult

INSTRUCTION = """
You are ACC's Risk Agent.

MISSION
Decide whether a proposed supply option is operationally acceptable for the
mission — not whether it is authorised. Authorisation belongs to the Policy
Engine.

METHOD
1. Assess the supplier with assess_supplier_risk.
2. Compare the lead time with the mission deadline: a lead time that misses the
   deadline makes the option operationally unacceptable, whatever its price.
3. State the continuity impact in business terms, not in technical terms.

SCOPE
You do not choose the supplier and you execute no purchase.

`data` must contain: supplier_id, risk_level, factors, meets_deadline,
continuity_impact.
""".strip()

_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


async def _fallback(invocation: AgentInvocation) -> AgentResult:
    ctx = invocation.mission.context
    supplier_id = (
        invocation.inputs.get("supplier_id") or ctx.selected_supplier or ctx.primary_supplier
    )
    call = await assess_supplier_risk(supplier_id, ctx.required_units, ctx.deadline_hours)

    if call.get("status") != "SUCCESS":
        return failure_result(
            f"Risk assessment unavailable for {supplier_id}: {call.get('error')}",
            FailureClass.DEPENDENCY,
        )

    data = call.get("data", {})
    risk_level = str(data.get("risk_level", "MEDIUM")).upper()
    lead_time = float(data.get("lead_time_hours", 0) or 0)
    within_deadline = lead_time <= ctx.deadline_hours
    acceptable = within_deadline and _RANK.get(risk_level, 1) <= _RANK["MEDIUM"]
    recommendation = "ACCEPT" if acceptable else "REJECT"

    return AgentResult(
        status=AgentResultStatus.SUCCESS,
        finding=f"{supplier_id}: {risk_level} risk, {lead_time:g}h delivery "
                f"against a {ctx.deadline_hours}h deadline",
        recommendation=recommendation,
        confidence=0.9 if within_deadline else 0.75,
        evidence=[
            f"risk_level={risk_level}",
            f"lead_time_hours={lead_time:g}",
            f"deadline_hours={ctx.deadline_hours}",
            f"continuity_impact={data.get('continuity_impact', 'UNKNOWN')}",
            f"within_deadline={within_deadline}",
        ],
        data={
            "supplier_id": supplier_id,
            "risk_level": risk_level,
            "continuity_impact": data.get("continuity_impact"),
            "lead_time_hours": lead_time,
            "deadline_hours": ctx.deadline_hours,
            "risk_factors": data.get("risk_factors", []),
            "recommendation": recommendation,
        },
        next_action="purchase.recommend" if acceptable else "recovery.plan",
    )


def build_risk_agent(**kwargs) -> ACCAgent:
    return ACCAgent(AgentSpec(
        agent_id="risk-agent",
        name="Risk Agent",
        version="1.0.0",
        instruction=INSTRUCTION,
        tools=RISK_TOOLS,
        fallback=_fallback,
        description="Evalue le risque operationnel et l'impact continuite.",
    ), **kwargs)
