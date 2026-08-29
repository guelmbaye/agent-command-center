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
        capabilities=["supplier.read", "supplier.status", "supplier.capacity",
                      "supplier.alternatives"],
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
        capabilities=["risk.assess", "risk.compare", "risk.recommend", "supplier.read"],
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
        capabilities=["supplier.compare", "supplier.read", "supplier.status",
                      "purchase.recommend", "purchase.execute"],
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
                      "recovery.abort", "supplier.read", "supplier.alternatives",
                      "risk.assess"],
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

    async def bootstrap(self) -> list[AgentRecord]:
        """Register the fleet at startup (idempotent)."""
        registered: list[AgentRecord] = []
        for seed in FLEET_SEED:
            existing = await self.store.get_agent(seed.agent_id)
            if existing is None:
                record = seed.model_copy(deep=True)
                record.status = AgentStatus.AVAILABLE
                registered.append(await self.store.save_agent(record))
            else:
                registered.append(existing)
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
