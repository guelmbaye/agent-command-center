"""Demo controls — deterministic, disabled outside demo mode.

Doc 06 §21: the judges must never depend on a random failure.
Doc 08 §31: these endpoints never mutate production mission state.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends

from apps.api.core.logging import get_logger
from apps.api.routes.deps import container_dep, require_api_key, require_demo_mode
from apps.api.schemas.api import DemoScenarioResponse
from apps.api.services.container import Container
from domain import ids

logger = get_logger("acc.demo")

router = APIRouter(
    prefix="/api/v1/demo", tags=["demo"],
    dependencies=[Depends(require_api_key), Depends(require_demo_mode)],
)


async def _enterprise(c: Container, method: str, path: str, **kwargs) -> dict:
    async with httpx.AsyncClient(base_url=c.settings.acc_enterprise_base_url,
                                 timeout=5.0) as client:
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()


@router.post("/fail/supplier-a", response_model=DemoScenarioResponse)
async def fail_supplier_a(c: Container = Depends(container_dep)) -> DemoScenarioResponse:
    """The hero moment: the primary supplier answers 503."""
    await _enterprise(c, "POST", "/demo/suppliers/SUP-A/fail")
    logger.warning("demo_supplier_failure_injected")
    return DemoScenarioResponse(scenario="supplier_failure", enabled=True,
                                detail="SUP-A renvoie desormais HTTP 503")


@router.post("/restore/supplier-a", response_model=DemoScenarioResponse)
async def restore_supplier_a(c: Container = Depends(container_dep)) -> DemoScenarioResponse:
    await _enterprise(c, "POST", "/demo/suppliers/SUP-A/restore")
    return DemoScenarioResponse(scenario="supplier_failure", enabled=False,
                                detail="SUP-A de nouveau disponible")


@router.post("/inject/malicious-input", response_model=DemoScenarioResponse)
async def inject_malicious_input(c: Container = Depends(container_dep)) -> DemoScenarioResponse:
    """The fallback supplier returns a hostile instruction in its response."""
    await _enterprise(c, "POST", "/demo/suppliers/SUP-B/poison")
    return DemoScenarioResponse(
        scenario="malicious_input", enabled=True,
        detail="SUP-B injecte une instruction de contournement de politique",
    )


@router.post("/clean/malicious-input", response_model=DemoScenarioResponse)
async def clean_malicious_input(c: Container = Depends(container_dep)) -> DemoScenarioResponse:
    await _enterprise(c, "POST", "/demo/suppliers/SUP-B/clean")
    return DemoScenarioResponse(scenario="malicious_input", enabled=False,
                                detail="Contenu hostile retire")


@router.post("/interrupt-agent", response_model=DemoScenarioResponse)
async def interrupt_agent(
    mission_id: str, c: Container = Depends(container_dep)
) -> DemoScenarioResponse:
    """Kill the runtime: mission state must survive."""
    mission = await c.engine.interrupt(mission_id)
    return DemoScenarioResponse(
        scenario="runtime_interruption", enabled=True, mission_id=mission_id,
        detail=f"Runtime interrompu — dernier checkpoint {mission.checkpoint_id}",
    )


@router.post("/scenario/hero", response_model=DemoScenarioResponse)
async def run_hero_scenario(c: Container = Depends(container_dep)) -> DemoScenarioResponse:
    """Prepare the hero scenario: mission created, failure armed, not triggered."""
    await _enterprise(c, "POST", "/demo/reset")
    mission = await c.engine.create_mission("Protect production schedule")
    return DemoScenarioResponse(
        scenario="hero", enabled=True, mission_id=mission.mission_id,
        detail="Mission prete. Demarrer, puis injecter la panne SUP-A.",
    )


@router.post("/reset", response_model=DemoScenarioResponse)
async def reset(c: Container = Depends(container_dep)) -> DemoScenarioResponse:
    await _enterprise(c, "POST", "/demo/reset")
    await c.store.reset()
    await c.registry.bootstrap()
    ids.reset_counters()
    logger.info("demo_reset")
    return DemoScenarioResponse(scenario="reset", enabled=True,
                                detail="Etat ACC et systemes entreprise reinitialises")
