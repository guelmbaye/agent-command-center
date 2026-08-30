"""A breaker must protect, not imprison.

Observed on the deployed instance:

    POST /api/v1/demo/reset -> 502
    "Enterprise systems unreachable at /demo/reset:
     Circuit open on demo after repeated failures"

Two defects at once. The breaker only reset on success — and while open no call
goes through, so no success could occur: it never closed. And the demo controls
were gated by it, so `Reset`, the very control an operator uses to REPAIR a
broken state, was blocked by the breakage it repairs.
"""
from __future__ import annotations

import pytest

from apps.api.services.enterprise_tools import EnterpriseToolClient
from tests.conftest import make_settings


def _tripped(tool: str) -> EnterpriseToolClient:
    client = EnterpriseToolClient(make_settings())
    client._consecutive_failures[tool] = 5
    client._opened_at[tool] = 0.0  # opened long ago
    return client


def test_operator_controls_are_never_gated():
    """The repair must not sit behind the failure it repairs."""
    client = EnterpriseToolClient(make_settings())
    client._consecutive_failures["demo"] = 99
    client._opened_at["demo"] = float("inf")

    assert client._breaker_open("demo") is False
    assert "demo" in client.UNGATED_TOOLS


def test_an_open_breaker_eventually_closes():
    """A breaker that only closes on success can never close."""
    client = _tripped("suppliers")
    assert client._breaker_cooldown_s > 0
    # The cooldown has elapsed: one call is let through (half-open).
    assert client._breaker_open("suppliers") is False


def test_the_breaker_still_protects_before_the_cooldown():
    """Exempting the controls must not disarm the breaker itself."""
    import time

    client = EnterpriseToolClient(make_settings())
    client._consecutive_failures["suppliers"] = 3
    client._opened_at["suppliers"] = time.monotonic()

    assert client._breaker_open("suppliers") is True


def test_half_open_does_not_reset_the_counter_to_zero():
    """One probe, not a clean slate: a still-broken dependency re-opens at once."""
    client = _tripped("suppliers")
    client._breaker_open("suppliers")  # consumes the half-open probe

    assert client._consecutive_failures["suppliers"] == client._breaker_threshold - 1
    assert "suppliers" not in client._opened_at


async def test_reset_works_even_with_a_tripped_breaker(container):
    """The deployed symptom, end to end, against the production application."""
    import httpx

    from apps.api.main import app

    container.tools._consecutive_failures["demo"] = 99
    container.tools._opened_at["demo"] = 0.0

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://acc") as web:
        response = await web.post("/api/v1/demo/reset")

    assert response.status_code == 200, response.text
