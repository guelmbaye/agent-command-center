"""ACC Memory Bank — structured, mission-scoped, non-rewritable memory.

Doc 04 §2, §11-12, §18, §20-22.
Core rule: MODEL MEMORY != MISSION STATE.
An agent proposes an observation; only the Mission Engine makes it durable.
"""
from __future__ import annotations

from typing import Any

from apps.api.core.logging import get_logger
from apps.api.repositories.base import Store
from domain.enums import MemoryType, Sensitivity
from domain.errors import PolicyDenied
from domain.models import MemoryEntry, Mission

logger = get_logger("acc.memory")

# Sensitivity levels an agent never receives in its context
_AGENT_VISIBLE = {Sensitivity.PUBLIC, Sensitivity.INTERNAL}


class MemoryService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def write(
        self,
        mission_id: str,
        type_: MemoryType,
        content: dict[str, Any],
        source: str,
        created_by: str = "mission-engine",
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        evidence_refs: list[str] | None = None,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            mission_id=mission_id, type=type_, content=content, source=source,
            created_by=created_by, sensitivity=sensitivity,
            evidence_refs=evidence_refs or [],
        )
        await self.store.save_memory(entry)
        logger.info("memory_written", extra={"memory_type": type_.value, "source": source})
        return entry

    async def all(self, mission_id: str) -> list[MemoryEntry]:
        return await self.store.list_memory(mission_id)

    async def recall_for_agent(
        self, mission: Mission, agent_id: str, requesting_mission_id: str, limit: int = 12
    ) -> list[str]:
        """Doc 04 §18-20: relevant context, never the full transcript.

        Isolation is checked explicitly: an agent on mission A cannot retrieve
        mission B's memory.
        """
        if requesting_mission_id != mission.mission_id:
            raise PolicyDenied(
                "Acces memoire hors perimetre de mission",
                agent_id=agent_id, requested=mission.mission_id,
                scope=requesting_mission_id,
            )
        entries = await self.store.list_memory(mission.mission_id)
        visible = [e for e in entries if e.sensitivity in _AGENT_VISIBLE]
        return [self._render(e) for e in visible[-limit:]]

    @staticmethod
    def _render(entry: MemoryEntry) -> str:
        parts = [f"{k}={v}" for k, v in entry.content.items() if v is not None]
        return f"[{entry.type.value}] " + ", ".join(parts)

    async def compact(self, mission_id: str, keep_last: int = 40) -> dict[str, Any]:
        """Context compaction (Doc 04 §21) — the summary never replaces state."""
        entries = await self.store.list_memory(mission_id)
        if len(entries) <= keep_last:
            return {"compacted": False, "entries": len(entries)}
        by_type: dict[str, int] = {}
        for entry in entries[:-keep_last]:
            by_type[entry.type.value] = by_type.get(entry.type.value, 0) + 1
        summary = await self.write(
            mission_id, MemoryType.EVIDENCE,
            {"summary": "Compaction d'historique", "counts": by_type},
            source="memory-service",
        )
        return {"compacted": True, "summary_id": summary.memory_id, "counts": by_type}
