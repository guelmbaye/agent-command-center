"""API Missions (Doc 08 §18-20, §23)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from apps.api.routes.deps import container_dep, require_api_key
from apps.api.schemas.api import (
    CreateMissionRequest,
    CreateMissionResponse,
    ResumeRequest,
)
from apps.api.services.container import Container
from domain.models import Mission

router = APIRouter(prefix="/api/v1/missions", tags=["missions"],
                   dependencies=[Depends(require_api_key)])


def _summary(mission: Mission) -> dict[str, Any]:
    return {
        "mission_id": mission.mission_id,
        "objective": mission.objective,
        "status": mission.status.value,
        "health": mission.health.value,
        "progress": mission.progress,
        "priority": mission.priority.value,
        "risk_level": mission.risk_level.value,
        "current_stage": mission.current_stage,
        "active_task_id": mission.active_task_id,
        "active_agent_id": mission.active_agent_id,
        "checkpoint_id": mission.checkpoint_id,
        "approval_status": mission.approval_status.value if mission.approval_status else None,
        "pending_approval_id": mission.pending_approval_id,
        "version": mission.version,
        "trace_id": mission.trace_id,
        # Distinguishing fields: without them, two missions from the same
        # template are indistinguishable in a list (same objective, same
        # supplier).
        "required_units": mission.context.required_units,
        "deadline_hours": mission.context.deadline_hours,
        "selected_supplier": mission.context.selected_supplier,
        "purchase_amount": mission.context.purchase_amount,
        "created_at": mission.created_at.isoformat(),
        "updated_at": mission.updated_at.isoformat(),
    }


@router.post("", response_model=CreateMissionResponse, status_code=201)
async def create_mission(
    payload: CreateMissionRequest, c: Container = Depends(container_dep)
) -> CreateMissionResponse:
    overrides: dict[str, Any] = {}
    if payload.deadline_hours is not None:
        overrides["deadline_hours"] = payload.deadline_hours
    if payload.required_units is not None:
        overrides["required_units"] = payload.required_units

    mission = await c.engine.create_mission(
        payload.objective, payload.priority, payload.template, overrides
    )
    if payload.autostart:
        # Execution goes to the bus: the HTTP response never blocks.
        mission = await c.engine.start(mission.mission_id)
    return CreateMissionResponse(mission_id=mission.mission_id,
                                 status=mission.status.value,
                                 objective=mission.objective)


@router.get("")
async def list_missions(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    c: Container = Depends(container_dep),
) -> dict:
    missions = await c.store.list_missions(status, limit)
    return {"missions": [_summary(m) for m in missions], "count": len(missions)}


@router.get("/{mission_id}")
async def get_mission(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    mission = await c.engine._require(mission_id)  # noqa: SLF001 - controlled read
    tasks = await c.store.list_tasks(mission_id)
    checkpoint = await c.checkpoints.latest(mission_id)
    metrics = await c.metrics.for_mission(mission_id)
    return {
        **_summary(mission),
        "context": mission.context.to_doc(),
        "tasks": [t.to_doc() for t in tasks],
        "latest_checkpoint": checkpoint.to_doc() if checkpoint else None,
        "metrics": metrics.__dict__,
    }


@router.get("/{mission_id}/state")
async def get_state(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    mission = await c.engine._require(mission_id)  # noqa: SLF001
    return {"mission_id": mission_id, "status": mission.status.value,
            "health": mission.health.value, "stage": mission.current_stage,
            "progress": mission.progress, "version": mission.version,
            "checkpoint_id": mission.checkpoint_id,
            "context": mission.context.to_doc()}


@router.get("/{mission_id}/timeline")
async def get_timeline(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    return {"mission_id": mission_id, "events": await c.traces.timeline(mission_id)}


@router.get("/{mission_id}/trace")
async def get_trace(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    return await c.traces.trace(mission_id)


@router.get("/{mission_id}/evidence")
async def get_evidence(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    return await c.traces.evidence(mission_id)


@router.get("/{mission_id}/checkpoints")
async def get_checkpoints(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    checkpoints = await c.checkpoints.list(mission_id)
    return {"mission_id": mission_id,
            "checkpoints": [cp.to_doc() for cp in checkpoints]}


@router.get("/{mission_id}/recoveries")
async def get_recoveries(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    recoveries = await c.store.list_recoveries(mission_id)
    return {"mission_id": mission_id, "recoveries": [r.to_doc() for r in recoveries]}


@router.get("/{mission_id}/audit")
async def get_audit(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    audits = await c.store.list_audit(mission_id)
    security = await c.store.list_security_events(mission_id)
    return {"mission_id": mission_id,
            "audit_events": [a.to_doc() for a in audits],
            "security_events": [s.to_doc() for s in security]}


@router.get("/{mission_id}/memory")
async def get_memory(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    entries = await c.memory.all(mission_id)
    return {"mission_id": mission_id, "memory": [e.to_doc() for e in entries]}


@router.get("/{mission_id}/metrics")
async def get_metrics(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    return (await c.metrics.for_mission(mission_id)).__dict__


@router.post("/{mission_id}/start")
async def start_mission(mission_id: str, c: Container = Depends(container_dep)) -> dict:
    mission = await c.engine.start(mission_id)
    return _summary(mission)


@router.post("/{mission_id}/resume")
async def resume_mission(
    mission_id: str, payload: ResumeRequest | None = None,
    c: Container = Depends(container_dep),
) -> dict:
    mission = await c.engine.resume(mission_id,
                                    payload.checkpoint_id if payload else None)
    return _summary(mission)


@router.get("/{mission_id}/stream")
async def stream_mission(mission_id: str, c: Container = Depends(container_dep)):
    """SSE: Mission Control observes state without polling (Doc 07 §23)."""
    queue = c.events.subscribe()

    async def generator():
        try:
            snapshot = await c.engine._require(mission_id)  # noqa: SLF001
            yield f"data: {json.dumps({'type': 'snapshot', **_summary(snapshot)})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event.mission_id != mission_id:
                    continue
                yield f"data: {json.dumps(event.to_doc())}\n\n"
        finally:
            c.events.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")
