"""Health probe and autonomy boundary description."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.routes.deps import container_dep, require_api_key
from apps.api.services.container import Container

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(c: Container = Depends(container_dep)) -> dict:
    """Open probe: Cloud Run must be able to call it without credentials.

    In cloud mode the response stays minimal. Detailing the configuration on a
    public URL would tell an attacker about the service posture (demo mode on,
    model protection off, and so on).
    """
    payload = {
        "status": "ok",
        "service": "acc-api",  # champ d'identification stable
        "env": c.settings.acc_env,
    }
    if not c.settings.is_cloud:
        payload.update({
            "persistence": c.settings.acc_persistence,
            "event_bus": c.settings.acc_event_bus,
            "agent_mode": c.settings.acc_agent_mode,
            "model_armor": c.settings.acc_model_armor,
            "demo_mode": c.settings.acc_demo_mode,
        })
    return payload


@router.get("/api/v1/policy", dependencies=[Depends(require_api_key)])
async def policy_boundary(c: Container = Depends(container_dep)) -> dict:
    """Autonomy boundary — visible to the operator, not to the internet.

    ACC deliberately exposes its authority limits: a buyer must be able to
    answer "what does this agent do without me?". But publishing the thresholds
    without authentication would tell an attacker how to size an action that
    stays under the autonomous limit. The route is therefore protected like the
    rest of /api/v1.
    """
    return c.policy.describe()
