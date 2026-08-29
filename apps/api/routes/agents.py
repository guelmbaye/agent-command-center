"""API Agent Registry (Doc 08 §21)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.routes.deps import container_dep, require_api_key
from apps.api.services.container import Container

router = APIRouter(prefix="/api/v1/agents", tags=["agents"],
                   dependencies=[Depends(require_api_key)])


@router.get("")
async def list_agents(c: Container = Depends(container_dep)) -> dict:
    agents = await c.registry.list()
    return {"agents": [a.to_doc() for a in agents], "count": len(agents)}


@router.get("/health")
async def fleet_health(c: Container = Depends(container_dep)) -> dict:
    return await c.registry.health()


@router.get("/{agent_id}")
async def get_agent(agent_id: str, c: Container = Depends(container_dep)) -> dict:
    return (await c.registry.get(agent_id)).to_doc()


@router.post("/{agent_id}/suspend")
async def suspend_agent(
    agent_id: str, reason: str = "Incident de securite",
    c: Container = Depends(container_dep),
) -> dict:
    """Fleet governance: a suspended agent takes no further missions."""
    return (await c.registry.suspend(agent_id, reason)).to_doc()
