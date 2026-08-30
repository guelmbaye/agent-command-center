"""Contrat d'API du Control Plane (Doc 08 §17-26)."""
from __future__ import annotations

import httpx
import pytest

from apps.api.core.errors import register_error_handlers
from apps.api.routes import agents, approvals, health, metrics, missions
from apps.api.routes.deps import request_context
from fastapi import Depends, FastAPI


@pytest.fixture
def api(container) -> FastAPI:
    app = FastAPI(dependencies=[Depends(request_context)])
    register_error_handlers(app)
    for module in (health, missions, agents, approvals, metrics):
        app.include_router(module.router)
    return app


@pytest.fixture
async def client(api):
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as c:
        yield c


async def test_healthz(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_policy_boundary_is_public(client):
    """The autonomy boundary is a product feature, not a secret."""
    body = (await client.get("/api/v1/policy")).json()
    assert body["default"] == "DENY"
    assert body["thresholds"]["purchase_autonomous_max"] == 5000.0
    assert "employee.read" in body["blocked"]


async def test_fleet_is_discoverable(client):
    body = (await client.get("/api/v1/agents")).json()
    ids = {a["agent_id"] for a in body["agents"]}
    assert ids == {"supply-agent", "risk-agent", "procurement-agent", "failure-twin"}
    procurement = next(a for a in body["agents"] if a["agent_id"] == "procurement-agent")
    assert "purchase.execute" in procurement["capabilities"]
    assert "employee.read" in procurement["denied_capabilities"]


async def test_mission_lifecycle_over_http(client, container, enterprise):
    enterprise.suppliers["SUP-A"].failing = True

    created = await client.post("/api/v1/missions",
                                json={"objective": "Protect production schedule"})
    assert created.status_code == 201
    mission_id = created.json()["mission_id"]
    await container.events.drain(timeout=60)

    detail = (await client.get(f"/api/v1/missions/{mission_id}")).json()
    assert detail["status"] == "WAITING_APPROVAL"
    assert detail["context"]["selected_supplier"] == "SUP-B"

    timeline = (await client.get(f"/api/v1/missions/{mission_id}/timeline")).json()
    assert any(e["type"] == "recovery.selected" for e in timeline["events"])

    recoveries = (await client.get(f"/api/v1/missions/{mission_id}/recoveries")).json()
    options = recoveries["recoveries"][0]["options"]
    assert any(not o["permitted"] for o in options)

    pending = (await client.get("/api/v1/approvals?status=PENDING")).json()
    approval_id = next(a["approval_id"] for a in pending["approvals"]
                       if a["action"] == "purchase.execute")

    decided = await client.post(f"/api/v1/approvals/{approval_id}/approve",
                                json={"decided_by": "operator", "comment": "OK"})
    assert decided.status_code == 200
    await container.events.drain(timeout=60)

    final = (await client.get(f"/api/v1/missions/{mission_id}/state")).json()
    assert final["status"] == "COMPLETED"
    assert final["context"]["purchase_id"]


async def test_unknown_mission_returns_contract_error(client):
    response = await client.get("/api/v1/missions/MIS-does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "MISSION_NOT_FOUND"
    assert error["request_id"]


async def test_fleet_metrics_expose_continuity_rate(client):
    body = (await client.get("/api/v1/metrics")).json()
    assert "mission_continuity_rate" in body
    assert "fleet_health" in body


# ---------------------------------------------------------------------------
# Authentification du Control Plane
#
# Regression: route dependencies read `get_settings()` (cached global
# environment) instead of the container settings. A `.env` containing
# ACC_API_KEY then made the whole API suite fail with 401s — and, more
# seriously, the application had two sources of truth for its configuration.
# ---------------------------------------------------------------------------
@pytest.fixture
async def secured_client(container, api):
    """Container with an actually configured API key."""
    container.settings.acc_api_key = "cle-de-test"
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as c:
        yield c


async def test_missing_api_key_is_rejected(secured_client):
    response = await secured_client.get("/api/v1/agents")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_wrong_api_key_is_rejected(secured_client):
    response = await secured_client.get(
        "/api/v1/agents", headers={"x-api-key": "mauvaise-cle"}
    )
    assert response.status_code == 401


async def test_correct_api_key_is_accepted(secured_client):
    response = await secured_client.get(
        "/api/v1/agents", headers={"x-api-key": "cle-de-test"}
    )
    assert response.status_code == 200
    assert len(response.json()["agents"]) == 4


async def test_healthz_stays_open_for_probes(secured_client):
    """Cloud Run must be able to probe the service without a key."""
    assert (await secured_client.get("/healthz")).status_code == 200


async def test_route_auth_follows_the_container_not_the_environment(
    container, api, monkeypatch,
):
    """An environment variable must not change route behaviour."""
    monkeypatch.setenv("ACC_API_KEY", "cle-venue-de-l-environnement")
    container.settings.acc_api_key = ""  # le container fait autorité

    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as c:
        assert (await c.get("/api/v1/agents")).status_code == 200


async def test_policy_route_requires_the_api_key(secured_client):
    """The autonomy boundary is visible to the operator, not to the internet.

    Publishing "purchase <= 5 000 $ is autonomous" without authentication would
    tell an attacker how to size an action that stays under the limit. This
    route initially lived in the unprotected `health` router — by convenience,
    not by decision.
    """
    assert (await secured_client.get("/api/v1/policy")).status_code == 401
    authorized = await secured_client.get(
        "/api/v1/policy", headers={"x-api-key": "cle-de-test"}
    )
    assert authorized.status_code == 200
    assert authorized.json()["default"] == "DENY"


async def test_healthz_stays_minimal_in_cloud_mode(container, api):
    """A public probe must not describe the service posture."""
    container.settings.acc_env = "demo"
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as c:
        body = (await c.get("/healthz")).json()

    assert body["status"] == "ok"
    assert body["service"] == "acc-api"  # identification stable pour le doctor
    for leak in ("demo_mode", "model_armor", "agent_mode", "persistence"):
        assert leak not in body, f"{leak} ne doit pas fuiter sur une URL publique"


async def test_healthz_is_detailed_locally(client):
    body = (await client.get("/healthz")).json()
    assert body["service"] == "acc-api"
    assert "agent_mode" in body and "demo_mode" in body


# ---------------------------------------------------------------------------
# Mission differentiation
#
# Usage regression: the frontend always created the default mission. Every
# mission was a clone — same objective, same supplier, same amount — and
# nothing in the list allowed telling them apart.
# ---------------------------------------------------------------------------
async def test_mission_parameters_are_honoured(client, container):
    created = await client.post("/api/v1/missions", json={
        "objective": "Ligne Assembly-7", "required_units": 800,
        "deadline_hours": 24, "priority": "CRITICAL",
    })
    assert created.status_code == 201
    await container.events.drain(timeout=60)

    detail = (await client.get(
        f"/api/v1/missions/{created.json()['mission_id']}")).json()
    assert detail["objective"] == "Ligne Assembly-7"
    assert detail["context"]["required_units"] == 800
    assert detail["context"]["deadline_hours"] == 24
    assert detail["priority"] == "CRITICAL"


async def test_mission_list_exposes_distinguishing_details(client, container):
    """A list of ids with no context is unusable."""
    for objective, units in (("Ligne A", 1200), ("Ligne B", 900)):
        await client.post("/api/v1/missions", json={
            "objective": objective, "required_units": units,
        })
    await container.events.drain(timeout=60)

    listed = (await client.get("/api/v1/missions")).json()["missions"]
    by_objective = {m["objective"]: m for m in listed}
    assert {"Ligne A", "Ligne B"} <= set(by_objective)
    assert by_objective["Ligne A"]["required_units"] == 1200
    assert by_objective["Ligne B"]["required_units"] == 900
    for mission in listed:
        for field in ("required_units", "deadline_hours", "selected_supplier",
                      "purchase_amount"):
            assert field in mission


async def test_volume_alone_crosses_the_authority_boundary(client, container):
    """Volume alone changes the narrative, with no failure injected.

    1200 u -> 4 800 $: below the autonomous threshold, the mission completes
    on its own. 1500 u -> 6 000 $: above it, human authority becomes necessary.
    """
    autonomous = await client.post("/api/v1/missions", json={
        "objective": "Volume nominal", "required_units": 1200})
    await container.events.drain(timeout=60)
    state = (await client.get(
        f"/api/v1/missions/{autonomous.json()['mission_id']}/state")).json()
    assert state["status"] == "COMPLETED"
    assert state["context"]["purchase_amount"] == 4_800.0

    supervised = await client.post("/api/v1/missions", json={
        "objective": "Volume eleve", "required_units": 1500})
    await container.events.drain(timeout=60)
    state = (await client.get(
        f"/api/v1/missions/{supervised.json()['mission_id']}/state")).json()
    assert state["status"] == "WAITING_APPROVAL"
    assert state["context"]["purchase_amount"] == 6_000.0


async def test_capacity_shortfall_activates_the_failure_twin(client, container):
    """Beyond SUP-A capacity, recovery takes over."""
    created = await client.post("/api/v1/missions", json={
        "objective": "Grande serie", "required_units": 2000})
    mission_id = created.json()["mission_id"]
    await container.events.drain(timeout=60)

    recoveries = (await client.get(
        f"/api/v1/missions/{mission_id}/recoveries")).json()["recoveries"]
    assert recoveries, "un manque de capacité doit déclencher le Failure Twin"
    assert "capacity" in recoveries[0]["diagnosis"].lower()
    assert not any(o["permitted"] and o["strategy"] == "USE_ALTERNATIVE_SUPPLIER"
                   for o in recoveries[0]["options"])


# ---------------------------------------------------------------------------
# SSE authentication
#
# `EventSource` — the browser API behind SSE — CANNOT set request headers.
# The live stream therefore answered 401 and Mission Control silently fell back
# to polling: the demo lost its real-time timeline, and no error explained why.
# ---------------------------------------------------------------------------
async def test_api_key_is_accepted_as_a_query_parameter():
    from apps.api.routes.deps import require_api_key
    from apps.api.services.container import build_container
    from apps.api.repositories.factory import reset_store
    from apps.api.routes.deps import Unauthorized
    from tests.conftest import make_settings

    reset_store()
    container = build_container(make_settings(acc_api_key="secret-key"))

    await require_api_key(x_api_key="secret-key", api_key=None, c=container)
    await require_api_key(x_api_key=None, api_key="secret-key", c=container)

    for bad in (None, "", "wrong"):
        with pytest.raises(Unauthorized):
            await require_api_key(x_api_key=None, api_key=bad, c=container)
    reset_store()


async def test_stream_refuses_a_request_without_a_key(secured_client):
    """The stream is protected like every other /api/v1 route."""
    response = await secured_client.get("/api/v1/missions/MIS-1/stream")
    assert response.status_code == 401
