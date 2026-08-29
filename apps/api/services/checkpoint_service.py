"""Checkpoints — the mission, not the container, is the durable unit (Doc 04 §5-7)."""
from __future__ import annotations

from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, span
from apps.api.repositories.base import Store
from domain.enums import RecoveryStatus, TaskStatus
from domain.models import Checkpoint, Mission

logger = get_logger("acc.checkpoint")

# Checkpoint labels (Doc 02 §18). A checkpoint label must describe what
# actually happened: the operator reconstructs the mission from this list.
CP_LABELS = {
    "created": "Mission planned",
    "supply_analysis": "Supply analysis complete",
    "risk_assessment": "Risk assessment complete",
    "procurement_planned": "Purchase plan prepared",
    "awaiting_approval": "Purchase awaiting approval",
    "failure_detected": "Supplier failure detected",
    "recovery_selected": "Recovery plan selected",
    "recovery_awaiting_approval": "Recovery plan awaiting approval",
    "approval_received": "Human approval received",
    "procurement_completed": "Purchase executed",
    "completed": "Mission completed",
}


class CheckpointService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def create(
        self, mission: Mission, stage: str, recovery_status: RecoveryStatus | None = None
    ) -> Checkpoint:
        tasks = await self.store.list_tasks(mission.mission_id)
        completed = [t.task_id for t in tasks if t.status is TaskStatus.COMPLETED]
        with span(Span.CHECKPOINT_CREATE, stage=stage):
            checkpoint = Checkpoint(
                mission_id=mission.mission_id,
                mission_version=mission.version,
                label=CP_LABELS.get(stage, stage),
                current_stage=stage,
                mission_status=mission.status,
                completed_tasks=completed,
                active_task_id=mission.active_task_id,
                approval_status=mission.approval_status,
                recovery_status=recovery_status,
                # Persist structured state, never the raw model context (Doc 04 §6)
                context_snapshot=mission.context.to_doc(),
                policy_state={"pending_approval_id": mission.pending_approval_id},
            )
            await self.store.save_checkpoint(checkpoint)
        mission.checkpoint_id = checkpoint.checkpoint_id
        logger.info("checkpoint_created", extra={
            "checkpoint_id": checkpoint.checkpoint_id, "stage": stage,
        })
        return checkpoint

    async def latest(self, mission_id: str) -> Checkpoint | None:
        checkpoints = await self.store.list_checkpoints(mission_id)
        return checkpoints[-1] if checkpoints else None

    async def get(self, mission_id: str, checkpoint_id: str) -> Checkpoint | None:
        return await self.store.get_checkpoint(mission_id, checkpoint_id)

    async def list(self, mission_id: str) -> list[Checkpoint]:
        return await self.store.list_checkpoints(mission_id)
