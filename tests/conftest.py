"""Fixtures ACC — container isole, mock entreprise en ASGI direct."""
from __future__ import annotations

import httpx
import pytest

from apps.api.core.config import Settings
from apps.api.repositories.factory import reset_store
from apps.api.services.container import Container, build_container, set_container
from domain import ids
from mock_enterprise.main import app as mock_app
from mock_enterprise.state import STATE


def make_settings(**overrides) -> Settings:
    """HERMETIC test settings.

    `_env_file=None` disables `.env` reading. Without it, a local file (policy
    thresholds, Model Armor mode, API key...) silently changes the behaviour of
    the suite: one developer's tests pass and another's fail on the same commit.
    """
    base = dict(
        acc_env="local",
        acc_persistence="memory",
        acc_event_bus="inproc",
        acc_agent_mode="deterministic",
        acc_model_armor="heuristic",
        acc_enterprise_base_url="http://mock-enterprise",
        acc_demo_mode=True,
        acc_api_key="",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
async def container() -> Container:
    reset_store()
    ids.reset_counters()
    STATE.reset()
    c = build_container(
        make_settings(), enterprise_transport=httpx.ASGITransport(app=mock_app)
    )
    set_container(c)
    await c.startup()
    try:
        yield c
    finally:
        await c.shutdown()
        set_container(None)


@pytest.fixture
def enterprise():
    """Direct access to enterprise state, used to arm failures."""
    return STATE
