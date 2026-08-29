"""Shared FastAPI dependencies: container, auth, request context."""
from __future__ import annotations

import secrets

from fastapi import Depends, Header, Request

from apps.api.core import context
from apps.api.services.container import Container, get_container
from domain import ids
from domain.errors import ACCError, DemoDisabled


class Unauthorized(ACCError):
    code, http_status = "UNAUTHORIZED", 401


def container_dep() -> Container:
    return get_container()


async def request_context(request: Request) -> str:
    """Every request carries a request_id correlatable with traces."""
    rid = request.headers.get("x-request-id") or ids.request_id()
    context.set_context(context.ExecutionContext(request_id=rid))
    return rid


async def require_api_key(
    x_api_key: str | None = Header(default=None),
    c: Container = Depends(container_dep),
) -> None:
    """Protect public Cloud Run URLs (Doc 09 pro-tips).

    Configuration is read from the CONTAINER, not from `get_settings()`.
    Otherwise the application has two sources of truth: services use the
    container settings while routes read the global environment. A local `.env`
    was then enough to change route behaviour without touching any service.
    """
    expected = c.settings.acc_api_key
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise Unauthorized("Cle d'API invalide ou absente")


async def require_demo_mode(c: Container = Depends(container_dep)) -> None:
    """Injection endpoints are disabled outside demo mode (Doc 07 §14)."""
    if not c.settings.acc_demo_mode or c.settings.acc_env == "production":
        raise DemoDisabled("Les endpoints de demonstration sont desactives")
