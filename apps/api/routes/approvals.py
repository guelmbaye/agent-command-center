"""Approvals API — human authority is durable state (Doc 08 §22)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from apps.api.routes.deps import container_dep, require_api_key
from apps.api.schemas.api import ApprovalDecisionRequest
from apps.api.services.container import Container

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"],
                   dependencies=[Depends(require_api_key)])


@router.get("")
async def list_approvals(
    status: str | None = Query(default=None),
    mission_id: str | None = Query(default=None),
    c: Container = Depends(container_dep),
) -> dict:
    approvals = await c.approvals.list(mission_id, status)
    return {"approvals": [a.to_doc() for a in approvals], "count": len(approvals)}


@router.get("/{approval_id}")
async def get_approval(approval_id: str, c: Container = Depends(container_dep)) -> dict:
    return (await c.approvals.get(approval_id)).to_doc()


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: str, payload: ApprovalDecisionRequest | None = None,
    c: Container = Depends(container_dep),
) -> dict:
    body = payload or ApprovalDecisionRequest()
    approval = await c.approvals.decide(approval_id, True, body.decided_by, body.comment)
    return approval.to_doc()


@router.post("/{approval_id}/reject")
async def reject(
    approval_id: str, payload: ApprovalDecisionRequest | None = None,
    c: Container = Depends(container_dep),
) -> dict:
    body = payload or ApprovalDecisionRequest()
    approval = await c.approvals.decide(approval_id, False, body.decided_by, body.comment)
    return approval.to_doc()
