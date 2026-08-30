"""Enterprise tool layer — the only door to real systems (Doc 09 §14).

No agent calls these functions directly: they are reachable only through the
Agent Gateway, after identity + capability + policy + approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from apps.api.core.config import Settings, get_settings
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, span
from apps.api.services.failure_classifier import classify_exception, classify_http
from domain.enums import FailureClass
from domain.errors import ToolUnavailable

logger = get_logger("acc.tools")


@dataclass
class ToolCallResult:
    ok: bool
    data: dict[str, Any]
    status_code: int = 200
    failure_class: FailureClass | None = None
    error: str | None = None
    raw_text: str = ""


class EnterpriseToolClient:
    """HTTP client to acc-mock-enterprise (bounded timeouts + circuit breaker)."""

    def __init__(self, settings: Settings | None = None,
                 transport: Any | None = None) -> None:
        self.settings = settings or get_settings()
        # `transport` lets the mock app be wired in directly over ASGI (tests,
        # local scenario) without starting a second HTTP server.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._consecutive_failures: dict[str, int] = {}
        self._breaker_threshold = 3
        self._identity_token: str | None = None

    def _fetch_identity_token(self) -> str | None:
        """Prove who we are to another Cloud Run service.

        The enterprise systems only accept `acc-api` (roles/run.invoker), and
        Cloud Run checks that through an OIDC identity token — not through the
        application API key. Without it the call is refused before reaching the
        container.

        Returns None outside Google Cloud, where there is no metadata server
        and no restriction to satisfy.
        """
        if self._identity_token is not None:
            return self._identity_token
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            audience = self.settings.acc_enterprise_base_url
            request = google.auth.transport.requests.Request()
            self._identity_token = google.oauth2.id_token.fetch_id_token(
                request, audience)
            logger.info("enterprise_identity_token_acquired",
                        extra={"audience": audience})
        except Exception as exc:  # local run, or no metadata server
            logger.info("enterprise_identity_token_unavailable",
                        extra={"detail": str(exc)[:120]})
            self._identity_token = ""
        return self._identity_token or None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs: dict[str, Any] = {
                "base_url": self.settings.acc_enterprise_base_url,
                "timeout": self.settings.acc_enterprise_timeout_s,
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            elif self.settings.acc_enterprise_base_url.startswith("https://"):
                token = self._fetch_identity_token()
                if token:
                    kwargs["headers"] = {"Authorization": f"Bearer {token}"}
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _breaker_open(self, tool: str) -> bool:
        return self._consecutive_failures.get(tool, 0) >= self._breaker_threshold

    async def call(
        self, tool: str, method: str, path: str, **kwargs: Any
    ) -> ToolCallResult:
        if self._breaker_open(tool):
            logger.warning("circuit_breaker_open", extra={"tool": tool})
            return ToolCallResult(
                ok=False, data={}, status_code=0,
                failure_class=FailureClass.DEPENDENCY,
                error=f"Circuit open on {tool} after repeated failures",
            )
        with span(Span.TOOL_CALL, tool=tool, path=path):
            try:
                client = await self._http()
                response = await client.request(method, path, **kwargs)
                text = response.text
                if response.status_code >= 400:
                    self._consecutive_failures[tool] = (
                        self._consecutive_failures.get(tool, 0) + 1
                    )
                    return ToolCallResult(
                        ok=False, data=_safe_json(response), status_code=response.status_code,
                        failure_class=classify_http(response.status_code),
                        error=f"HTTP {response.status_code}", raw_text=text,
                    )
                self._consecutive_failures[tool] = 0
                return ToolCallResult(ok=True, data=_safe_json(response),
                                      status_code=response.status_code, raw_text=text)
            except Exception as exc:
                self._consecutive_failures[tool] = self._consecutive_failures.get(tool, 0) + 1
                logger.error("tool_call_failed", extra={"tool": tool, "detail": str(exc)})
                return ToolCallResult(
                    ok=False, data={}, status_code=0,
                    failure_class=classify_exception(exc), error=str(exc),
                )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"items": payload}
    except Exception:
        return {"raw": response.text}


# ---------------------------------------------------------------------------
# Catalogue de capacites -> implementation outil
# ---------------------------------------------------------------------------
ToolImpl = Callable[["EnterpriseToolClient", dict[str, Any]], Awaitable[ToolCallResult]]


async def _supplier_read(client: EnterpriseToolClient, p: dict[str, Any]) -> ToolCallResult:
    supplier_id = p.get("supplier_id", "SUP-A")
    return await client.call("suppliers", "GET", f"/suppliers/{supplier_id}")


async def _supplier_alternatives(client: EnterpriseToolClient, p: dict[str, Any]) -> ToolCallResult:
    return await client.call("suppliers", "GET", "/suppliers",
                             params={"exclude": p.get("exclude", ""),
                                     "min_units": p.get("min_units", 0)})


async def _production_read(client: EnterpriseToolClient, p: dict[str, Any]) -> ToolCallResult:
    return await client.call("production", "GET", "/production/schedule")


async def _risk_assess(client: EnterpriseToolClient, p: dict[str, Any]) -> ToolCallResult:
    return await client.call("risk", "POST", "/risk/assess", json=p)


async def _purchase_execute(client: EnterpriseToolClient, p: dict[str, Any]) -> ToolCallResult:
    return await client.call("procurement", "POST", "/procurement/purchase", json=p)


CAPABILITY_TOOLS: dict[str, tuple[str, ToolImpl]] = {
    "supplier.read": ("suppliers", _supplier_read),
    "supplier.status": ("suppliers", _supplier_read),
    "supplier.capacity": ("suppliers", _supplier_read),
    "supplier.alternatives": ("suppliers", _supplier_alternatives),
    "supplier.compare": ("suppliers", _supplier_alternatives),
    "production.read": ("production", _production_read),
    "risk.assess": ("risk", _risk_assess),
    "purchase.execute": ("procurement", _purchase_execute),
}

# CONSEQUENTIAL capabilities: they mutate the enterprise and must be protected
# against double execution.
#
# Idempotency applies ONLY to them. Applied to a read, it freezes the
# observation: a retry would replay the stale answer forever, and a real-world
# correction (raised capacity, supplier back online) would never be seen.
# Recovery would then be structurally unable to succeed.
CONSEQUENTIAL_CAPABILITIES = {"purchase.execute"}


def is_consequential(capability: str) -> bool:
    return capability in CONSEQUENTIAL_CAPABILITIES


# Pure reasoning capabilities: no enterprise action
REASONING_CAPABILITIES = {
    "risk.compare", "risk.recommend", "purchase.recommend",
    "recovery.diagnose", "recovery.plan", "recovery.apply", "recovery.abort",
}


def resolve(capability: str) -> tuple[str, ToolImpl]:
    if capability not in CAPABILITY_TOOLS:
        raise ToolUnavailable(f"Aucun outil entreprise pour la capacite {capability}",
                              capability=capability)
    return CAPABILITY_TOOLS[capability]
