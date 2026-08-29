"""Pub/Sub push endpoint — asynchronous continuation on Cloud Run (Doc 09 §8)."""
from __future__ import annotations

import base64
import json

from fastapi import APIRouter, Depends, Header, Response

from apps.api.core.logging import get_logger
from apps.api.routes.deps import container_dep
from apps.api.services.container import Container
from domain.models import MissionEvent

logger = get_logger("acc.events.push")
router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("/pubsub")
async def pubsub_push(
    payload: dict,
    x_pubsub_token: str | None = Header(default=None),
    c: Container = Depends(container_dep),
) -> Response:
    """Receive a Pub/Sub push message and route it to the Mission Engine."""
    expected = c.settings.pubsub_push_token
    if expected and x_pubsub_token != expected:
        return Response(status_code=401)

    message = payload.get("message", {})
    raw = message.get("data")
    if not raw:
        return Response(status_code=204)
    try:
        decoded = json.loads(base64.b64decode(raw).decode("utf-8"))
        event = MissionEvent.model_validate(decoded)
    except Exception as exc:
        logger.error("pubsub_payload_invalid", extra={"detail": str(exc)})
        # 204: avoid infinite redelivery of a corrupted message.
        return Response(status_code=204)

    await c.events.dispatch(event)
    return Response(status_code=204)
