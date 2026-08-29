"""ADK tools backed by the Agent Gateway.

An ADK agent never receives an enterprise HTTP client. It receives functions
that mandatorily traverse: identity -> capability -> policy -> approval ->
idempotency -> tool -> Model Armor -> audit.

The current identity is read from the execution context (contextvars), so a
prompt cannot fabricate it.
"""
from __future__ import annotations

from typing import Any

from apps.api.core import context
from apps.api.core.logging import get_logger
from apps.api.services.agent_gateway import AgentGateway, GatewayRequest
from domain.enums import RiskLevel
from domain.errors import ACCError

logger = get_logger("acc.agent.tools")

_GATEWAY: AgentGateway | None = None


def bind_gateway(gateway: AgentGateway) -> None:
    """Inject the Gateway once at runtime startup."""
    global _GATEWAY
    _GATEWAY = gateway


async def _call(capability: str, parameters: dict[str, Any],
                resource: str | None = None, amount: float | None = None,
                risk_level: RiskLevel = RiskLevel.LOW) -> dict[str, Any]:
    identity = context.current().identity
    if _GATEWAY is None or identity is None:
        return {"status": "DENIED",
                "error": "Contexte d'execution absent : appel outil refuse"}
    try:
        result = await _GATEWAY.execute(GatewayRequest(
            identity=identity, capability=capability, parameters=parameters,
            resource=resource, amount=amount, risk_level=risk_level,
        ))
        return {
            "status": result.status,
            "data": result.result,
            "approval_id": result.approval_id,
            "policy_decision_id": result.policy_decision_id,
            "error": result.error_message,
        }
    except ACCError as exc:
        logger.warning("tool_denied", extra={"capability": capability, "code": exc.code})
        return {"status": "DENIED", "error": exc.message, "code": exc.code}


# ---------------------------------------------------------------------------
# Outils exposes aux agents ADK (signatures typees = schema d'outil ADK)
# ---------------------------------------------------------------------------
async def get_supplier_status(supplier_id: str) -> dict[str, Any]:
    """Fetch a supplier's status, capacity and lead time.

    Args:
        supplier_id: Supplier identifier, for example "SUP-A".

    Returns:
        Call status and sanitised supplier data.
    """
    return await _call("supplier.status", {"supplier_id": supplier_id}, resource=supplier_id)


async def list_alternative_suppliers(exclude: str = "", min_units: int = 0) -> dict[str, Any]:
    """List the available alternative suppliers.

    Args:
        exclude: Supplier to exclude (the one that failed).
        min_units: Minimum required capacity in units.

    Returns:
        Candidate suppliers with capacity, lead time and unit price.
    """
    return await _call("supplier.alternatives",
                       {"exclude": exclude, "min_units": min_units})


async def get_production_schedule() -> dict[str, Any]:
    """Fetch the current production schedule and its deadline window."""
    return await _call("production.read", {})


async def assess_supplier_risk(supplier_id: str, required_units: int,
                               deadline_hours: int) -> dict[str, Any]:
    """Assess a supplier's operational risk for this requirement.

    Args:
        supplier_id: Supplier under assessment.
        required_units: Volume needed.
        deadline_hours: Delivery window in hours.

    Returns:
        Risk level, factors and continuity impact.
    """
    return await _call("risk.assess", {
        "supplier_id": supplier_id, "required_units": required_units,
        "deadline_hours": deadline_hours,
    }, resource=supplier_id)


async def execute_purchase(supplier_id: str, units: int, amount: float) -> dict[str, Any]:
    """Execute a purchase. May return APPROVAL_REQUIRED: that is a normal result.

    Never try to work around an APPROVAL_REQUIRED or a DENIED.

    Args:
        supplier_id: Selected supplier.
        units: Quantity ordered.
        amount: Total amount in USD.

    Returns:
        SUCCESS with a purchase order number, or APPROVAL_REQUIRED, or DENIED.
    """
    return await _call("purchase.execute",
                       {"supplier_id": supplier_id, "units": units, "amount": amount},
                       resource=supplier_id, amount=amount, risk_level=RiskLevel.HIGH)


SUPPLY_TOOLS = [get_supplier_status, list_alternative_suppliers, get_production_schedule]
RISK_TOOLS = [assess_supplier_risk, get_supplier_status, get_production_schedule]
PROCUREMENT_TOOLS = [get_supplier_status, list_alternative_suppliers, execute_purchase]
FAILURE_TWIN_TOOLS = [get_supplier_status, list_alternative_suppliers,
                      get_production_schedule, assess_supplier_risk]
