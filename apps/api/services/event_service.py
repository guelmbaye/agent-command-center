"""Event bus — durable asynchronous continuation (Doc 04 §17, Doc 09 §8).

Two implementations:
  inproc : asyncio.Queue + worker (local / tests / demo)
  pubsub : Google Pub/Sub, with a push endpoint -> POST /api/v1/events/pubsub

Long-running execution never depends on an HTTP request (Doc 07 §19).
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from apps.api.core.config import Settings, get_settings
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import current_trace_id
from apps.api.repositories.base import Store
from domain.enums import EventType
from domain.models import MissionEvent

logger = get_logger("acc.events")

Handler = Callable[[MissionEvent], Awaitable[None]]


class EventService:
    def __init__(self, store: Store, settings: Settings | None = None) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self._handler: Handler | None = None
        self._queue: asyncio.Queue[MissionEvent] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._publisher = None
        self._subscribers: list[asyncio.Queue[MissionEvent]] = []

    # --- Lifecycle ---------------------------------------------------------
    def set_handler(self, handler: Handler) -> None:
        self._handler = handler

    async def start(self) -> None:
        if self.settings.acc_event_bus == "inproc" and self._worker is None:
            self._worker = asyncio.create_task(self._run_worker(), name="acc-event-worker")
            logger.info("event_worker_started")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker = None

    # --- Publishing --------------------------------------------------------
    async def publish(
        self,
        mission_id: str,
        type_: EventType,
        message: str = "",
        source: str = "mission-engine",
        actor: str | None = None,
        **payload: object,
    ) -> MissionEvent:
        """Persist first (integrity chaining), publish second."""
        previous = await self.store.last_event_id(mission_id)
        event = MissionEvent(
            mission_id=mission_id, type=type_, source=source, actor=actor,
            message=message, payload=dict(payload), previous_event_id=previous,
            trace_id=current_trace_id(),
        )
        await self.store.append_event(event)
        logger.info("event_published", extra={"event_type": type_.value, "message": message})

        for queue in list(self._subscribers):
            queue.put_nowait(event)

        if self.settings.acc_event_bus == "pubsub":
            await self._publish_pubsub(event)
        else:
            await self._queue.put(event)
        return event

    async def _publish_pubsub(self, event: MissionEvent) -> None:  # pragma: no cover
        try:
            from google.cloud import pubsub_v1
            if self._publisher is None:
                self._publisher = pubsub_v1.PublisherClient()
            topic = self._publisher.topic_path(
                self.settings.google_cloud_project, self.settings.pubsub_topic
            )
            data = json.dumps(event.to_doc()).encode("utf-8")
            future = self._publisher.publish(
                topic, data, event_type=event.type.value, mission_id=event.mission_id
            )
            await asyncio.wrap_future(future)
        except Exception as exc:
            logger.error("pubsub_publish_failed_fallback_inproc", extra={"detail": str(exc)})
            await self._queue.put(event)

    # --- Consumption -------------------------------------------------------
    async def dispatch(self, event: MissionEvent) -> None:
        """Point d'entree unique : worker inproc ET push Pub/Sub arrivent ici."""
        if self._handler is None:
            return
        try:
            await self._handler(event)
        except Exception:
            logger.exception("event_handler_failed", extra={"event_type": event.type.value})

    async def _run_worker(self) -> None:
        while True:
            event = await self._queue.get()
            await self.dispatch(event)
            self._queue.task_done()

    async def drain(self, timeout: float = 30.0) -> None:
        """Used by the tests and the scenario script."""
        await asyncio.wait_for(self._queue.join(), timeout=timeout)

    # --- Real-time stream (SSE) --------------------------------------------
    def subscribe(self) -> asyncio.Queue[MissionEvent]:
        queue: asyncio.Queue[MissionEvent] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[MissionEvent]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)
