"""Demo controls — deterministic, disabled outside demo mode.

Doc 06 §21: the judges must never depend on a random failure.
Doc 08 §31: these endpoints never mutate production mission state.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.core.logging import get_logger
from apps.api.routes.deps import container_dep, require_api_key, require_demo_mode
from apps.api.schemas.api import DemoScenarioResponse
from apps.api.services.container import Container
from domain import ids
from domain.errors import DemoControlFailed

logger = get_logger("acc.demo")

router = APIRouter(
    prefix="/api/v1/demo", tags=["demo"],
    dependencies=[Depends(require_api_key), Depends(require_demo_mode)],
)


async def _enterprise(c: Container, method: str, path: str, **kwargs) -> dict:
    """Reach the enterprise systems through the SHARED client.

    This helper used to build its own `httpx.AsyncClient`. That client knew
    nothing about Cloud Run identity tokens, so every demo control — reset,
    failure injection, hostile injection — was refused once deployed and
    surfaced as a bare 500.

    The authentication fix (ADR-057) had been applied to `EnterpriseToolClient`
    only. Two clients, one of them corrected: exactly the defect of ADR-051, in
    a second code path.
    """
    result = await c.tools.call("demo", method, path, **kwargs)
    if not result.ok:
        raise DemoControlFailed(
            f"Enterprise systems unreachable at {path}: {result.error}")
    return result.data or {}


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
        detail="SUP-B now injects a policy-bypass instruction",
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
        detail="Mission ready. Start it, then inject the SUP-A failure.",
    )


@router.post("/reset", response_model=DemoScenarioResponse)
async def reset(c: Container = Depends(container_dep)) -> DemoScenarioResponse:
    """Clear ACC and the simulated enterprise systems.

    Each step says which one failed. A bare 500 on a demo control, minutes
    before a recording, tells the operator nothing about where to look.
    """
    try:
        await _enterprise(c, "POST", "/demo/reset")
    except DemoControlFailed:
        raise
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        logger.exception("demo_reset_enterprise_failed")
        raise DemoControlFailed(f"Enterprise reset failed: {exc}") from exc

    try:
        await c.store.reset()
    except NotImplementedError as exc:
        raise DemoControlFailed(
            "Reset is restricted to demo mode (ACC_DEMO_MODE=1)") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("demo_reset_store_failed")
        raise DemoControlFailed(f"Store reset failed: {exc}") from exc

    await c.registry.bootstrap()
    ids.reset_counters()
    logger.info("demo_reset")
    return DemoScenarioResponse(scenario="reset", enabled=True,
                                detail="ACC and enterprise systems reset")
