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

from pathlib import Path

import httpx
import pytest

from apps.api.core.config import Settings
from tests.conftest import make_settings

ROOT = Path(__file__).resolve().parents[2]


def build_app(settings: Settings):
    """Rebuild the application with the given settings."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from apps.api.routes import agents, health

    from apps.api.main import cors_options

    app = FastAPI()
    # The PRODUCTION wiring, not a copy of it. Rebuilding the middleware
    # arguments here is what let a hardcoded regex live in main.py while every
    # CORS test stayed green.
    app.add_middleware(CORSMiddleware, **cors_options(settings))
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


# ---------------------------------------------------------------------------
# The configured regex must be the one that is used
#
# Found on the deployed instance: `main.py` held a hardcoded `_CORS_ORIGIN_REGEX`
# and ignored `ACC_CORS_ORIGIN_REGEX` entirely. The operator could set it in
# Terraform, see it in the plan, see it in the container environment — and it
# changed nothing.
#
# The existing CORS tests passed throughout, because the hardcoded pattern
# happened to match the URLs they tried. They tested the behaviour of a
# constant, never that configuration reached the middleware.
# ---------------------------------------------------------------------------
async def test_a_custom_origin_regex_is_actually_honoured():
    """Set a regex that allows ONE origin and forbids the usual ones."""
    app = build_app(make_settings(
        acc_env="demo",
        acc_cors_origin_regex=r"https://only-this-one\.example\.com",
    ))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as client:
        allowed = await client.options(
            "/api/v1/agents",
            headers={"origin": "https://only-this-one.example.com",
                     "access-control-request-method": "GET"},
        )
        refused = await client.options(
            "/api/v1/agents",
            headers={"origin": "https://acc-web-abc-ew.a.run.app",
                     "access-control-request-method": "GET"},
        )

    assert allowed.headers.get("access-control-allow-origin") == \
        "https://only-this-one.example.com", (
        "the configured regex is ignored — a hardcoded constant is in use"
    )
    assert "access-control-allow-origin" not in refused.headers, (
        "an origin outside the configured regex must be refused"
    )


async def test_deployed_frontend_origin_passes_preflight():
    """The real Cloud Run origin, end to end through the middleware."""
    app = build_app(make_settings(acc_env="demo"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as client:
        for origin in ("https://acc-web-jycspetv4a-ew.a.run.app",
                       "https://acc-web-327474819537.europe-west1.run.app"):
            response = await client.options(
                "/api/v1/missions",
                headers={"origin": origin,
                         "access-control-request-method": "POST"},
            )
            assert response.headers.get("access-control-allow-origin") == origin, (
                f"{origin} would be blocked by the browser"
            )


async def test_exact_origins_list_is_also_honoured():
    """ACC_CORS_ORIGINS was ignored too: it is an exact-match list."""
    app = build_app(make_settings(
        acc_env="demo",
        acc_cors_origins="https://exact.example.com",
        acc_cors_origin_regex="",
    ))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as client:
        response = await client.options(
            "/api/v1/agents",
            headers={"origin": "https://exact.example.com",
                     "access-control-request-method": "GET"},
        )
    assert response.headers.get("access-control-allow-origin") == \
        "https://exact.example.com"


# ---------------------------------------------------------------------------
# No FastAPI auto-instrumentation
#
# `opentelemetry-instrumentation-fastapi` < 0.65b0 crashes on FastAPI >= 0.141
# with `'_IncludedRouter' object has no attribute 'path'`. Its middleware runs
# BEFORE the CORS one, so every request became a 500 with no CORS headers: the
# browser reported a CORS failure whose real cause was three layers down.
#
# The compatibility probe of ADR-014 could not help — the build environment had
# the fixed 0.65b0 while pip backtracked to the broken 0.63b1 in the container.
# ---------------------------------------------------------------------------
def test_fastapi_auto_instrumentation_is_not_enabled():
    source = (ROOT / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "FastAPIInstrumentor" not in code, (
        "auto-instrumentation crashes on FastAPI >= 0.141 with the version pip "
        "resolves inside the container"
    )


def test_the_crashing_package_is_not_a_dependency():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    declared = [
        line for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any("instrumentation-fastapi" in line for line in declared), (
        "pip backtracks to a broken version under google-adk's constraints"
    )


def test_only_the_cors_middleware_is_installed():
    """Anything added before CORS can swallow the preflight."""
    from apps.api.main import app

    assert [m.cls.__name__ for m in app.user_middleware] == ["CORSMiddleware"]


async def test_mission_tracing_survives_without_instrumentation():
    """What carries the product value is ACC's own code, not the package."""
    from apps.api.core.telemetry import span

    with span("mission.test", mission_id="MIS-1"):
        pass  # no exporter configured: must be a no-op, never an error
