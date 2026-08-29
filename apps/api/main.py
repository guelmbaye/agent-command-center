"""ACC Control Plane — application FastAPI (service Cloud Run `acc-api`)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.core.config import api_key_source, get_settings
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
_CORS_ORIGIN_REGEX = (
    r"https://acc-web[-\w]*\.[-\w]*\.?run\.app"  # revisions Cloud Run
    r"|http://(localhost|127\.0\.0\.1)(:\d+)?"      # postes de developpement
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_cloud else [],
    allow_origin_regex=None if not settings.is_cloud else _CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
    max_age=600,
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(missions.router)
app.include_router(agents.router)
app.include_router(approvals.router)
app.include_router(metrics.router)
app.include_router(events.router)
app.include_router(demo.router)

def _otel_instrumentation_is_compatible(application: FastAPI) -> bool:
    """Check that auto-instrumentation can read THIS FastAPI's routes.

    Since FastAPI 0.141, included routers are wrapped in `_IncludedRouter`
    objects that do not expose `.path`. Older versions of
    opentelemetry-instrumentation-fastapi assume they do and raise an
    AttributeError ON EVERY REQUEST — the API becomes unusable.

    So we probe the actually installed function before enabling it, rather than
    trusting a version constraint.
    """
    try:
        from opentelemetry.instrumentation.fastapi import _get_route_details

        scope = {
            "type": "http", "method": "GET", "path": "/healthz",
            "headers": [], "app": application, "root_path": "",
        }
        _get_route_details(scope)
        return True
    except Exception as exc:
        logger.warning("otel_fastapi_instrumentation_incompatible", extra={
            "detail": str(exc),
            "hint": "Le tracage de mission reste actif ; seuls les spans HTTP "
                    "automatiques sont desactives. "
                    "Corriger : pip install -U opentelemetry-instrumentation-fastapi",
        })
        return False


if settings.otel_traces_exporter != "none":
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        if _otel_instrumentation_is_compatible(app):
            FastAPIInstrumentor.instrument_app(app)
            logger.info("otel_fastapi_instrumented")
    except ImportError:
        logger.info("otel_fastapi_instrumentation_absente")


@app.get("/")
async def root() -> dict:
    return {
        "product": "ACC — Autonomous Mission Control",
        "tagline": "The agent can fail. The mission doesn't have to.",
        "docs": "/docs",
        "health": "/healthz",
    }
