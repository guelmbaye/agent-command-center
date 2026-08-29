"""Execution context propagated through contextvars.

Lets any layer (ADK tool, gateway, logger) know mission_id / execution_id /
trace_id without threading them through every signature.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Iterator

from domain.models import AgentIdentity


@dataclass(frozen=True)
class ExecutionContext:
    mission_id: str | None = None
    task_id: str | None = None
    execution_id: str | None = None
    agent_id: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    identity: AgentIdentity | None = None


_CTX: ContextVar[ExecutionContext] = ContextVar("acc_ctx", default=ExecutionContext())


def current() -> ExecutionContext:
    return _CTX.get()


def as_dict() -> dict[str, str]:
    ctx = current()
    return {
        k: v for k, v in {
            "mission_id": ctx.mission_id,
            "task_id": ctx.task_id,
            "execution_id": ctx.execution_id,
            "agent_id": ctx.agent_id,
            "trace_id": ctx.trace_id,
            "request_id": ctx.request_id,
        }.items() if v
    }


@contextmanager
def bind(**kwargs: object) -> Iterator[ExecutionContext]:
    ctx = replace(current(), **kwargs)  # type: ignore[arg-type]
    token = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)


def set_context(ctx: ExecutionContext) -> None:
    _CTX.set(ctx)
