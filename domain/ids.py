"""Readable id generators — one prefix per entity (Doc 08)."""
from __future__ import annotations

import itertools
import threading
import uuid

_LOCK = threading.Lock()
_COUNTERS: dict[str, itertools.count] = {}


def _next(prefix: str, start: int) -> str:
    with _LOCK:
        counter = _COUNTERS.get(prefix)
        if counter is None:
            counter = itertools.count(start)
            _COUNTERS[prefix] = counter
        return f"{prefix}-{next(counter)}"


def mission_id() -> str:
    return _next("MIS", 1001)


def task_id() -> str:
    return _next("TASK", 1)


def execution_id() -> str:
    return _next("EXE", 8801)


def event_id() -> str:
    return _next("EVT", 4401)


def checkpoint_id() -> str:
    return _next("CP", 1)


def recovery_id() -> str:
    return _next("REC", 101)


def policy_decision_id() -> str:
    return _next("POL", 701)


def approval_id() -> str:
    return _next("APR", 8801)


def audit_id() -> str:
    return _next("AUD", 901)


def action_id() -> str:
    return _next("ACT", 501)


def memory_id() -> str:
    return _next("MEM", 301)


def request_id() -> str:
    return _next("REQ", 801)


def trace_id() -> str:
    """Fallback when OpenTelemetry is not active."""
    return uuid.uuid4().hex


def reset_counters() -> None:
    """Used by the tests and by POST /demo/reset."""
    with _LOCK:
        _COUNTERS.clear()
