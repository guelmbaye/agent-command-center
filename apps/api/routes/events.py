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
    token: str | None = None,
    x_pubsub_token: str | None = Header(default=None),
    c: Container = Depends(container_dep),
) -> Response:
    """Receive a Pub/Sub push message and route it to the Mission Engine.

    The shared token arrives in the QUERY STRING, not in a header: a Pub/Sub
    push subscription cannot send custom headers. It only carries an OIDC token
    in `Authorization`, which Cloud Run verifies before the request ever
    reaches this code.

    Checking a header Pub/Sub cannot send rejected every push with 401. The
    subscription retried, the messages expired, and missions stayed frozen at
    `planning` with no error visible anywhere in the application.

    The header is still accepted, for a caller that can set one.
    """
    expected = c.settings.pubsub_push_token
    if expected and expected not in (token, x_pubsub_token):
        logger.warning("pubsub_push_rejected", extra={
            "reason": "token mismatch",
            "hint": "the subscription must carry ?token=... in its push endpoint",
        })
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
