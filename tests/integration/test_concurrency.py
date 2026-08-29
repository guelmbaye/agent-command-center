"""Pub/Sub "at least once" delivery (Doc 07 §26, Doc 08 §28).

The in-memory store returns the SAME object instances, which hides every race:
a mutation by one coroutine is instantly visible to the others. Firestore
returns a fresh copy on each read. These tests therefore reproduce Firestore
semantics — network latency AND deserialisation — otherwise they would validate
a property production does not have.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from apps.api.repositories.memory_store import InMemoryStore
from apps.api.services.container import build_container, set_container
from domain import ids
from domain.enums import MissionStatus, TaskStatus
from mock_enterprise.main import app as mock_app
from mock_enterprise.state import STATE
from tests.conftest import make_settings

LATENCY = 0.01  # ordre de grandeur d'un aller-retour Firestore


class FirestoreLikeStore(InMemoryStore):
    """Faithful store: every read yields AND returns a fresh object."""

    async def get_mission(self, *a, **k):
        await asyncio.sleep(LATENCY)
        mission = await super().get_mission(*a, **k)
        return mission.model_copy(deep=True) if mission else None

    async def list_tasks(self, *a, **k):
        await asyncio.sleep(LATENCY)
        return [t.model_copy(deep=True) for t in await super().list_tasks(*a, **k)]

    async def get_task(self, *a, **k):
        await asyncio.sleep(LATENCY)
        task = await super().get_task(*a, **k)
        return task.model_copy(deep=True) if task else None

    async def save_task(self, *a, **k):
        await asyncio.sleep(LATENCY)
        return await super().save_task(*a, **k)

    async def save_mission(self, *a, **k):
        await asyncio.sleep(LATENCY)
        return await super().save_mission(*a, **k)


@pytest.fixture
async def distributed():
    """Container whose persistence behaves like Firestore."""
    ids.reset_counters()
    STATE.reset()
    c = build_container(
        make_settings(), store=FirestoreLikeStore(),
        enterprise_transport=httpx.ASGITransport(app=mock_app),
    )
    set_container(c)
    await c.startup()
    try:
        yield c
    finally:
        await c.shutdown()
        set_container(None)


async def test_concurrent_delivery_runs_each_task_once(distributed):
    """Three concurrent pushes of the same event: one agent run per task."""
    mission = await distributed.engine.create_mission("Protect production schedule")
    mission.status = MissionStatus.EXECUTING
    await distributed.store.save_mission(mission)

    await asyncio.gather(
        *[distributed.engine.advance(mission.mission_id) for _ in range(3)],
        return_exceptions=True,
    )
    await distributed.events.drain(timeout=60)

    executions = await distributed.store.list_executions(mission.mission_id)
    per_task: dict[str, int] = {}
    for execution in executions:
        per_task[execution.task_id] = per_task.get(execution.task_id, 0) + 1

    assert per_task, "aucune execution enregistree"
    assert all(count == 1 for count in per_task.values()), (
        f"execution dupliquee detectee : {per_task}"
    )
    assert len(STATE.purchases) == 1


async def test_claim_is_exclusive(distributed):
    """The claim itself: only one caller obtains the task."""
    mission = await distributed.engine.create_mission("Protect production schedule")
    task = (await distributed.store.list_tasks(mission.mission_id))[0]

    results = await asyncio.gather(*[
        distributed.store.claim_task(
            mission.mission_id, task.task_id,
            {TaskStatus.PENDING.value, TaskStatus.FAILED.value}, f"worker-{i}",
        )
        for i in range(5)
    ])

    granted = [r for r in results if r is not None]
    assert len(granted) == 1
    assert granted[0].claimed_by is not None
    assert granted[0].status is TaskStatus.RUNNING


async def test_replaying_processed_events_is_inert(container):
    """Late redelivery: no re-execution, no duplicate purchase."""
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await container.events.drain(timeout=60)

    before = len(await container.store.list_executions(mission.mission_id))
    purchases_before = len(STATE.purchases)

    for event in await container.store.list_events(mission.mission_id):
        await container.engine.process_event(event)
    await container.events.drain(timeout=60)

    assert len(await container.store.list_executions(mission.mission_id)) == before
    assert len(STATE.purchases) == purchases_before


async def test_stale_mission_write_is_rejected(container):
    """Optimistic concurrency: a stale write cannot overwrite state."""
    from domain.errors import StateVersionConflict

    mission = await container.engine.create_mission("Protect production schedule")
    stale_version = mission.version

    await container.store.update_mission(mission, stale_version)  # v -> v+1

    with pytest.raises(StateVersionConflict):
        await container.store.update_mission(mission, stale_version)
