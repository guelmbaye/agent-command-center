"""Demo controls are EXECUTED, not merely inspected.

Two failures in a row came from tests that read the source as text:

  * `logger.info(...)` in a module defining no `logger` -> NameError, 500
  * `result.status` on a `ToolCallResult` that exposes `ok` -> AttributeError

Both were invisible to a test asserting that a string appears in a file. These
tests call the routes.
"""
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def client(container):
    """The PRODUCTION application, not a rebuilt copy.

    The existing `api` fixture reassembles its own FastAPI instance and does
    not even include the demo router — so no test could reach these routes.
    Rebuilding the app is how a defect hides from its own test suite
    (ADR-051).
    """
    from apps.api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as c:
        yield c


async def test_reset_clears_missions_and_enterprise_state(client, enterprise):
    """The control the operator presses before every rehearsal."""
    created = await client.post("/api/v1/missions", json={"objective": "X"})
    assert created.status_code == 201

    response = await client.post("/api/v1/demo/reset")
    assert response.status_code == 200, response.text
    assert response.json()["scenario"] == "reset"

    listed = await client.get("/api/v1/missions")
    assert listed.json()["count"] == 0, "missions survived the reset"


async def test_reset_answers_in_english(client):
    response = await client.post("/api/v1/demo/reset")
    detail = response.json()["detail"]
    assert detail == "ACC and enterprise systems reset"


@pytest.mark.parametrize("path", [
    "/api/v1/demo/reset",
    "/api/v1/demo/fail/supplier-a",
    "/api/v1/demo/inject/malicious-input",
])
async def test_every_demo_control_reaches_the_enterprise_systems(path, client):
    """Each one goes through the shared client; none may 500."""
    response = await client.post(path)
    assert response.status_code == 200, f"{path} -> {response.status_code} {response.text}"


async def test_a_failing_enterprise_names_the_step(client, monkeypatch):
    """A bare 500 tells the operator nothing about where to look."""
    from apps.api.services.container import get_container
    from apps.api.services.enterprise_tools import ToolCallResult

    async def broken(*args, **kwargs):
        return ToolCallResult(ok=False, data={}, error="simulated outage")

    monkeypatch.setattr(get_container().tools, "call", broken)
    response = await client.post("/api/v1/demo/reset")

    assert response.status_code == 502
    body = response.json()["error"]
    assert body["code"] == "DEMO_CONTROL_FAILED"
    assert "simulated outage" in body["message"]
