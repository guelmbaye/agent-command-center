"""Composition root — the single place where dependencies are wired.

The Gateway is mounted inside acc-api (Doc 09 §13): modular, not distributed.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.runtime import AgentRuntime
from apps.api.core.config import Settings, get_settings
from apps.api.core.logging import get_logger
from apps.api.repositories.base import Store
from apps.api.repositories.factory import get_store
from apps.api.services.agent_gateway import AgentGateway
from apps.api.services.alerting import AlertingService
from apps.api.services.approval_service import ApprovalService
from apps.api.services.audit_service import AuditService
from apps.api.services.checkpoint_service import CheckpointService
from apps.api.services.enterprise_tools import EnterpriseToolClient
from apps.api.services.event_service import EventService
from apps.api.services.memory_service import MemoryService
from apps.api.services.metrics import MetricsService
from apps.api.services.mission_engine import MissionEngine
from apps.api.services.model_armor import ModelArmor
from apps.api.services.policy_engine import PolicyEngine
from apps.api.services.recovery_engine import RecoveryEngine
from apps.api.services.registry import AgentRegistry
from apps.api.services.trace_builder import TraceBuilder

logger = get_logger("acc.container")


@dataclass
class Container:
    settings: Settings
    store: Store
    events: EventService
    registry: AgentRegistry
    policy: PolicyEngine
    armor: ModelArmor
    audit: AuditService
    memory: MemoryService
    checkpoints: CheckpointService
    approvals: ApprovalService
    tools: EnterpriseToolClient
    gateway: AgentGateway
    runtime: AgentRuntime
    recovery: RecoveryEngine
    engine: MissionEngine
    metrics: MetricsService
    traces: TraceBuilder
    alerts: AlertingService

    async def startup(self) -> None:
        await self.registry.bootstrap()
        await self.events.start()
        logger.info("acc_ready", extra={
            "persistence": self.settings.acc_persistence,
            "event_bus": self.settings.acc_event_bus,
            "agent_mode": self.settings.acc_agent_mode,
            "model_armor": self.settings.acc_model_armor,
        })

    async def shutdown(self) -> None:
        await self.events.stop()
        await self.tools.close()


def build_container(
    settings: Settings | None = None,
    store: Store | None = None,
    enterprise_transport: object | None = None,
) -> Container:
    settings = settings or get_settings()
    store = store or get_store(settings)

    events = EventService(store, settings)
    registry = AgentRegistry(store)
    policy = PolicyEngine(store, settings)
    armor = ModelArmor(settings)
    audit = AuditService(store)
    memory = MemoryService(store)
    checkpoints = CheckpointService(store)
    approvals = ApprovalService(store, events, audit)
    tools = EnterpriseToolClient(settings, transport=enterprise_transport)

    gateway = AgentGateway(store, registry, policy, approvals, audit, events,
                           armor, tools, settings)
    runtime = AgentRuntime(store, registry, gateway, armor, settings)
    recovery = RecoveryEngine(store, runtime, registry, gateway, policy,
                              events, memory, audit)
    engine = MissionEngine(store, registry, runtime, events, checkpoints, memory,
                           approvals, recovery, policy, audit)

    return Container(
        settings=settings, store=store, events=events, registry=registry, policy=policy,
        armor=armor, audit=audit, memory=memory, checkpoints=checkpoints,
        approvals=approvals, tools=tools, gateway=gateway, runtime=runtime,
        recovery=recovery, engine=engine, metrics=MetricsService(store),
        traces=TraceBuilder(store), alerts=AlertingService(store),
    )


_container: Container | None = None


def get_container() -> Container:
    global _container
    if _container is None:
        _container = build_container()
    return _container


def set_container(container: Container | None) -> None:
    global _container
    _container = container
