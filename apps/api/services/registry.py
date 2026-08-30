"""Agent Registry — fleet discovery, versioning and trust (Doc 02 §7, §22).

ACC's equivalent of the GEAP Agent Registry: no agent takes part in a mission
without registration, declared capabilities and a trust status.
"""
from __future__ import annotations

from apps.api.core.logging import get_logger
from apps.api.repositories.base import Store
from domain.enums import AgentStatus, AuthorityLevel, RiskLevel
from domain.errors import AgentUnavailable
from domain.models import AgentRecord
from domain.state_machine import assert_agent_transition

logger = get_logger("acc.registry")

# --- MVP fleet (Doc 02 §24): 3 operational agents + 1 recovery intelligence
FLEET_SEED: list[AgentRecord] = [
    AgentRecord(
        agent_id="supply-agent",
        name="Supply Agent",
        version="1.0.0",
        status=AgentStatus.APPROVED,
        risk_level=RiskLevel.LOW,
        # Exactly what its tools can invoke. A capability that matches no tool
        # is dead weight; a tool without its capability is a CAPABILITY_DENIED
        # the operator has to decipher.
        capabilities=["supplier.status", "supplier.alternatives",
                      "production.read"],
        allowed_tools=["suppliers", "production"],
        denied_capabilities=["purchase.execute", "employee.read", "payroll.write",
                             "customer.export"],
        authority_level=AuthorityLevel.AUTONOMOUS,
        service_identity="acc/agents/supply/v1",
        description="Maintains an accurate picture of supplier availability.",
    ),
    AgentRecord(
        agent_id="risk-agent",
        name="Risk Agent",
        version="1.0.0",
        status=AgentStatus.APPROVED,
        risk_level=RiskLevel.MEDIUM,
        capabilities=["risk.assess", "supplier.status", "production.read"],
        allowed_tools=["risk", "suppliers"],
        denied_capabilities=["purchase.execute", "employee.read", "payroll.write",
                             "customer.export"],
        authority_level=AuthorityLevel.AUTONOMOUS,
        service_identity="acc/agents/risk/v1",
        description="Determines whether a proposed recovery is operationally acceptable.",
    ),
    AgentRecord(
        agent_id="procurement-agent",
        name="Procurement Agent",
        version="1.0.0",
        status=AgentStatus.APPROVED,
        risk_level=RiskLevel.HIGH,
        capabilities=["supplier.status", "supplier.alternatives",
                      "purchase.execute"],
        allowed_tools=["suppliers", "procurement"],
        denied_capabilities=["employee.read", "payroll.write", "customer.export"],
        authority_level=AuthorityLevel.SUPERVISED,
        service_identity="acc/agents/procurement/v1",
        description="Turns an approved strategy into an authorised enterprise action.",
    ),
    AgentRecord(
        agent_id="failure-twin",
        name="Failure Twin",
        version="1.0.0",
        status=AgentStatus.APPROVED,
        risk_level=RiskLevel.MEDIUM,
        capabilities=["recovery.diagnose", "recovery.plan", "recovery.apply",
                      "recovery.abort", "supplier.status",
                      "supplier.alternatives", "production.read", "risk.assess"],
        allowed_tools=["suppliers", "risk", "production"],
        denied_capabilities=["purchase.execute", "employee.read", "payroll.write",
                             "customer.export"],
        authority_level=AuthorityLevel.SUPERVISED,
        service_identity="acc/agents/failure-twin/v1",
        description="Diagnoses failures and determines permitted recovery paths.",
    ),
]


class AgentRegistry:
    def __init__(self, store: Store) -> None:
        self.store = store

    # Fields the code owns. Anything else is operational state that belongs to
    # the running fleet and must survive a redeployment.
    DECLARED_FIELDS = ("capabilities", "denied_capabilities", "authority_level",
                       "risk_level", "version", "name", "description")

    async def bootstrap(self) -> list[AgentRecord]:
        """Register the fleet at startup, and RECONCILE what the code declares.

        This used to return the stored record untouched when an agent already
        existed. The registry lives in Firestore, so a deployment could never
        correct an agent's capabilities: fixing them in code changed nothing,
        and the deployed fleet kept answering CAPABILITY_DENIED for a capability
        the source had granted.

        In a project whose whole argument is that the registry governs
        authority, a registry no deployment can update is the wrong kind of
        durable.

        Operational state — status, current execution — is NOT overwritten: a
        suspended agent stays suspended across a redeploy, which is exactly
        what fleet governance means (Doc 02 §22).
        """
        registered: list[AgentRecord] = []
        for seed in FLEET_SEED:
            existing = await self.store.get_agent(seed.agent_id)
            if existing is None:
                record = seed.model_copy(deep=True)
                record.status = AgentStatus.AVAILABLE
                registered.append(await self.store.save_agent(record))
                continue

            changed = {
                field: getattr(seed, field)
                for field in self.DECLARED_FIELDS
                if getattr(existing, field) != getattr(seed, field)
            }
            if not changed:
                registered.append(existing)
                continue

            for field, value in changed.items():
                setattr(existing, field, value)
            logger.info("agent_declaration_reconciled", extra={
                "agent_id": seed.agent_id,
                "fields": sorted(changed),
            })
            registered.append(await self.store.save_agent(existing))

        logger.info("fleet_registered", extra={"count": len(registered)})
        return registered

    async def get(self, agent_id: str) -> AgentRecord:
        record = await self.store.get_agent(agent_id)
        if record is None:
            raise AgentUnavailable(f"Agent inconnu du registre : {agent_id}", agent_id=agent_id)
        return record

    async def list(self) -> list[AgentRecord]:
        return await self.store.list_agents()

    async def require_executable(self, agent_id: str) -> AgentRecord:
        """Zero trust: fleet membership is not enough (Doc 03 §2)."""
        record = await self.get(agent_id)
        if record.status in {AgentStatus.SUSPENDED, AgentStatus.REVOKED}:
            raise AgentUnavailable(
                f"Agent {agent_id} not cleared (status {record.status.value})",
                agent_id=agent_id, status=record.status.value,
            )
        if not record.status.can_execute:
            raise AgentUnavailable(
                f"Agent {agent_id} unavailable (status {record.status.value})",
                agent_id=agent_id, status=record.status.value,
            )
        return record

    async def set_status(self, agent_id: str, target: AgentStatus) -> AgentRecord:
        record = await self.get(agent_id)
        assert_agent_transition(record.status, target, agent_id)
        record.status = target
        logger.info("agent_status_changed", extra={"agent_id": agent_id, "status": target.value})
        return await self.store.save_agent(record)

    async def suspend(self, agent_id: str, reason: str) -> AgentRecord:
        """Doc 02 §22: fleet governance, not mere orchestration."""
        logger.warning("agent_suspended", extra={"agent_id": agent_id, "reason": reason})
        return await self.set_status(agent_id, AgentStatus.SUSPENDED)

    async def health(self) -> dict[str, int]:
        agents = await self.list()
        buckets = {"healthy": 0, "executing": 0, "degraded": 0, "failed": 0,
                   "recovering": 0, "suspended": 0}
        for a in agents:
            if a.status in {AgentStatus.AVAILABLE, AgentStatus.APPROVED}:
                buckets["healthy"] += 1
            elif a.status is AgentStatus.BUSY:
                buckets["executing"] += 1
            elif a.status is AgentStatus.DEGRADED:
                buckets["degraded"] += 1
            elif a.status is AgentStatus.FAILED:
                buckets["failed"] += 1
            elif a.status is AgentStatus.RECOVERING:
                buckets["recovering"] += 1
            elif a.status in {AgentStatus.SUSPENDED, AgentStatus.REVOKED}:
                buckets["suspended"] += 1
        return buckets
