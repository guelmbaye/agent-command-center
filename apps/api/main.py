"""ACC Control Plane — application FastAPI (service Cloud Run `acc-api`)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.core.config import Settings, api_key_source, get_settings
from apps.api.core.errors import register_error_handlers
from apps.api.core.logging import configure_logging, get_logger
from apps.api.core.telemetry import configure_telemetry
from apps.api.routes import agents, approvals, demo, events, health, metrics, missions
from apps.api.routes.deps import request_context
from apps.api.services.container import get_container

settings = get_settings()
configure_logging(settings.acc_log_level)
configure_telemetry(settings)
logger = get_logger("acc.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = get_container()
    await container.startup()
    if container.settings.acc_api_key:
        # Without this message a browser-side 401 has no visible explanation.
        # Above all we report the SOURCE: an environment variable takes
        # precedence over .env, where the line may even be commented out.
        source = api_key_source()
        remedy = (
            "An environment variable is active. To remove it: "
            "PowerShell 'Remove-Item Env:ACC_API_KEY', "
            "cmd 'set ACC_API_KEY=', bash 'unset ACC_API_KEY'."
            if source == "environment" else
            "Defined in the .env file. Comment it out for local use."
        )
        logger.warning("api_key_enforced", extra={
            "source": source or "unknown",
            "hint": f"Every /api/v1/* route requires the x-api-key header. "
                    f"{remedy} Otherwise 'make web' propagates the key to the frontend.",
        })
    try:
        yield
    finally:
        await container.shutdown()


app = FastAPI(
    title="ACC — Autonomous Mission Control",
    description=(
        "Control plane pour missions d'entreprise autonomes, gouvernees et "
        "recuperables. L'agent peut echouer ; la mission n'y est pas obligee."
    ),
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(request_context)],
)

# CORS: Starlette does NOT support wildcards in `allow_origins` — an entry
# like "https://acc-web-*.run.app" is never matched and the browser blocks the
# request. Patterns go through `allow_origin_regex`.
#
# The pattern comes from CONFIGURATION, never from a constant. A hardcoded
# regex here silently ignored ACC_CORS_ORIGIN_REGEX: the operator could set it
# on Cloud Run, see it in the plan, see it in the container environment — and
# it changed nothing. A setting that cannot be overridden is not a setting.
def cors_options(config: Settings) -> dict[str, object]:
    """CORS middleware arguments — the SINGLE source for app and tests.

    Tests used to rebuild this wiring themselves. They therefore validated
    their own copy, and passed for years while production used a hardcoded
    regex that ignored the configuration entirely. A double that reimplements
    what it checks proves nothing about the real path.
    """
    regex = config.acc_cors_origin_regex.strip() or None
    return {
        "allow_origins": ["*"] if not config.is_cloud else config.cors_origins,
        "allow_origin_regex": None if not config.is_cloud else regex,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        "expose_headers": ["x-request-id"],
        "max_age": 600,
    }


app.add_middleware(CORSMiddleware, **cors_options(settings))

register_error_handlers(app)

app.include_router(health.router)
app.include_router(missions.router)
app.include_router(agents.router)
app.include_router(approvals.router)
app.include_router(metrics.router)
app.include_router(events.router)
app.include_router(demo.router)

# FastAPI auto-instrumentation is deliberately NOT enabled.
#
# `opentelemetry-instrumentation-fastapi` < 0.65b0 crashes on FastAPI >= 0.141
# with `'_IncludedRouter' object has no attribute 'path'`. The middleware runs
# BEFORE the CORS one, so every request became a 500 with no CORS headers — the
# browser reported it as a CORS failure, and the real cause was three layers
# down.
#
# A compatibility probe (ADR-014) could not protect against this: the build
# environment had the fixed 0.65b0, while pip backtracked to the broken 0.63b1
# inside the container, constrained by google-adk's opentelemetry-api pin. The
# probe tested a version that was never deployed.
#
# What is lost: automatic HTTP spans. What is kept: everything that carries the
# product value — mission spans, trace_id correlation, the audit trail — all of
# which are ACC's own code and depend on no optional package.


@app.get("/")
async def root() -> dict:
    return {
        "product": "ACC — Autonomous Mission Control",
        "tagline": "The agent can fail. The mission doesn't have to.",
        "docs": "/docs",
        "health": "/healthz",
    }
