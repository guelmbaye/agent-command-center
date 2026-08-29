"""CORS and instrumentation — two traps found by real execution.

1. Starlette does NOT support wildcards in `allow_origins`. An entry like
   "https://acc-web-*.run.app" is never treated as a pattern: it is compared
   for strict equality. The deployed frontend was therefore blocked by CORS,
   which only showed up after deployment.

2. FastAPI >= 0.141 wraps included routers in `_IncludedRouter` objects with no
   `.path` attribute. Older versions of opentelemetry-instrumentation-fastapi
   raise an AttributeError on EVERY request, making the API unusable.
"""
from __future__ import annotations

import httpx
import pytest

from apps.api.core.config import Settings
from tests.conftest import make_settings


def build_app(settings: Settings):
    """Rebuild the application with the given settings."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from apps.api.routes import agents, health

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_cloud else settings.cors_origins,
        allow_origin_regex=(None if not settings.is_cloud
                            else settings.acc_cors_origin_regex),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(agents.router)
    return app


async def _preflight(app, origin: str) -> str | None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as c:
        response = await c.options(
            "/api/v1/agents",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
    return response.headers.get("access-control-allow-origin")


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
async def test_local_mode_allows_the_dev_server(container):
    app = build_app(make_settings(acc_env="local"))
    assert await _preflight(app, "http://localhost:3000") is not None


@pytest.mark.parametrize("origin", [
    "https://acc-web-abc123-ew.a.run.app",            # ancien format Cloud Run
    "https://acc-web-123456789.europe-west1.run.app",  # format actuel
    "http://localhost:3000",
])
async def test_cloud_mode_allows_cloud_run_and_dev(container, origin):
    app = build_app(make_settings(acc_env="demo"))
    assert await _preflight(app, origin) is not None, (
        f"{origin} doit etre autorisee : le frontend deploye serait bloque"
    )


@pytest.mark.parametrize("origin", [
    "https://evil.example.com",
    "https://acc-web-abc.run.app.evil.com",  # tentative de suffixe
    "http://acc-web-abc.a.run.app",          # http et non https
])
async def test_cloud_mode_rejects_foreign_origins(container, origin):
    app = build_app(make_settings(acc_env="demo"))
    assert await _preflight(app, origin) is None


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------
def test_probe_detects_an_incompatible_instrumentation(monkeypatch):
    """Broken instrumentation must be disabled, not endured."""
    pytest.importorskip("opentelemetry.instrumentation.fastapi")
    import opentelemetry.instrumentation.fastapi as otel_fastapi

    from apps.api.main import _otel_instrumentation_is_compatible, app

    def broken(scope):
        raise AttributeError("'_IncludedRouter' object has no attribute 'path'")

    monkeypatch.setattr(otel_fastapi, "_get_route_details", broken)
    assert _otel_instrumentation_is_compatible(app) is False


def test_probe_accepts_a_working_instrumentation(monkeypatch):
    pytest.importorskip("opentelemetry.instrumentation.fastapi")
    import opentelemetry.instrumentation.fastapi as otel_fastapi

    from apps.api.main import _otel_instrumentation_is_compatible, app

    monkeypatch.setattr(otel_fastapi, "_get_route_details", lambda scope: "/healthz")
    assert _otel_instrumentation_is_compatible(app) is True


async def test_every_router_is_reachable_despite_wrapping(container):
    """FastAPI 0.141 encapsule les routers : les routes doivent rester servies."""
    from apps.api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as c:
        schema = (await c.get("/openapi.json")).json()

    paths = set(schema["paths"])
    for expected in ("/healthz", "/api/v1/policy", "/api/v1/agents",
                     "/api/v1/missions", "/api/v1/approvals", "/api/v1/metrics"):
        assert expected in paths, f"{expected} absente du schema OpenAPI"
