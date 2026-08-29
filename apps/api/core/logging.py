"""Structured JSON logs — every line carries mission_id / trace_id (Doc 05 §19)."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from apps.api.core import context

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


class ACCJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(context.as_dict())
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ACCJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "google", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class ACCLoggerAdapter(logging.LoggerAdapter):
    """Guard against collisions between business fields and LogRecord attributes.

    `logging` forbids overriding reserved attributes through `extra`: passing
    extra={"message": ...} raises a KeyError at log time. Since ACC services
    log arbitrary business fields, conflicting keys are silently renamed rather
    than letting a log line bring down a mission.
    """

    def process(self, msg, kwargs):
        extra = kwargs.get("extra")
        if extra:
            kwargs["extra"] = {
                (f"ctx_{key}" if key in _RESERVED else key): value
                for key, value in extra.items()
            }
        return msg, kwargs


def get_logger(name: str) -> ACCLoggerAdapter:
    return ACCLoggerAdapter(logging.getLogger(name), {})
