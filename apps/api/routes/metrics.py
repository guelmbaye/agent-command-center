"""Fleet metrics API — Mission Continuity Rate first (Doc 05 §23)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.routes.deps import container_dep, require_api_key
from apps.api.services.container import Container

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"],
                   dependencies=[Depends(require_api_key)])


@router.get("")
async def fleet_metrics(c: Container = Depends(container_dep)) -> dict:
    summary = await c.metrics.fleet_summary()
    summary["fleet_health"] = await c.registry.health()
    return summary


@router.get("/alerts")
async def alerts(c: Container = Depends(container_dep)) -> dict:
    """Mission-oriented alerts — never a normal agent event."""
    items = await c.alerts.current()
    return {
        "alerts": [a.to_doc() for a in items],
        "critical": sum(1 for a in items if a.severity == "CRITICAL"),
        "warning": sum(1 for a in items if a.severity == "WARNING"),
    }
