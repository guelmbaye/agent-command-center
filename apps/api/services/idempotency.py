"""Idempotency — "why a resumable agent might order two laptops" (Doc 08 §27).

Key = mission_id + task_id + action. The attempt number is deliberately NOT in
the key: otherwise a retry after interruption would re-run the purchase.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.api.core.logging import get_logger
from apps.api.repositories.base import Store

logger = get_logger("acc.idempotency")


def build_key(mission_id: str, task_id: str | None, action: str) -> str:
    return f"{mission_id}-{task_id or 'no-task'}-{action}"


class IdempotencyGuard:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def lookup(self, key: str) -> dict[str, Any] | None:
        record = await self.store.get_idempotent(key)
        if record:
            logger.info("idempotent_replay", extra={"idempotency_key": key})
        return record

    async def remember(self, key: str, result: dict[str, Any]) -> None:
        await self.store.put_idempotent(key, {
            "idempotency_key": key,
            "result": result,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
