"""Failure classification — a short, actionable taxonomy (Doc 05 §17)."""
from __future__ import annotations

import re

from domain.enums import FailureClass

_HTTP_MAP = {
    408: FailureClass.TIMEOUT,
    429: FailureClass.TRANSIENT,
    500: FailureClass.DEPENDENCY,
    502: FailureClass.DEPENDENCY,
    503: FailureClass.DEPENDENCY,
    504: FailureClass.TIMEOUT,
    401: FailureClass.AUTHORIZATION,
    403: FailureClass.AUTHORIZATION,
    404: FailureClass.PERMANENT,
    409: FailureClass.PERMANENT,
    422: FailureClass.PERMANENT,
}


def classify_http(status_code: int) -> FailureClass:
    return _HTTP_MAP.get(status_code, FailureClass.UNKNOWN)


def classify_exception(exc: BaseException) -> FailureClass:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return FailureClass.TIMEOUT
    if "connect" in name or "unavailable" in text or "connection" in text:
        return FailureClass.DEPENDENCY
    if "permission" in text or "unauthorized" in text or "forbidden" in text:
        return FailureClass.AUTHORIZATION
    if "threat" in text or "injection" in text or "armor" in text:
        return FailureClass.SECURITY
    match = re.search(r"\b([45]\d{2})\b", text)
    if match:
        return classify_http(int(match.group(1)))
    return FailureClass.AGENT


def retry_allowed(failure: FailureClass, attempt: int, max_attempts: int = 3) -> bool:
    """Never retry blindly (Doc 02 §15)."""
    if failure.requires_safe_hold:
        return False
    return failure.retry_allowed and attempt < max_attempts
