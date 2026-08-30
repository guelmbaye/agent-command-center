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
    """Key for an observation, scoped to the task that made it."""
    return f"{mission_id}-{task_id or 'no-task'}-{action}"


def build_action_key(mission_id: str, action: str,
                     parameters: dict[str, Any] | None = None) -> str:
    """Key for a CONSEQUENTIAL action, scoped to the MISSION.

    The task id must not appear here. A mission is decomposed into a planning
    task and an execution task; with the task in the key, the same purchase
    made from both produced two different keys and two real purchase orders:

        19:32:51  Purchase order PO-8831 ... $4800.00
        19:33:00  Purchase order PO-8832 ... $4800.00

    Deterministic mode hid it — only the execution task purchases there. A
    model choosing its own tools bought during planning as well.

    The business parameters ARE part of the identity: buying 1200 units from
    SUP-B after a recovery is a different action from buying them from SUP-A,
    and must not be deduplicated away. What must be deduplicated is the same
    action, whichever task attempts it.
    """
    parts = [mission_id, action]
    for field in ("supplier_id", "units", "amount"):
        value = (parameters or {}).get(field)
        if value is not None:
            parts.append(f"{field}={value}")
    return "-".join(parts)


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
