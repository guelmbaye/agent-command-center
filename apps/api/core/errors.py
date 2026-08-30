"""FastAPI handlers -> single error contract (Doc 08 §26)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.api.core import context
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import current_trace_id
from domain import ids
from domain.errors import ACCError

logger = get_logger("acc.errors")


def _payload(code: str, message: str, **extra: object) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": context.current().request_id or ids.request_id(),
            "trace_id": current_trace_id(),
            "mission_id": context.current().mission_id,
            **({"details": extra} if extra else {}),
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ACCError)
    async def _acc_error(_: Request, exc: ACCError) -> JSONResponse:
        logger.warning("acc_error", extra={"code": exc.code, "detail": exc.message})
        return JSONResponse(
            status_code=exc.http_status,
            content=_payload(exc.code, exc.message, **exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_payload("VALIDATION_ERROR", "Invalid request", errors=exc.errors()),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error")
        return JSONResponse(
            status_code=500,
            content=_payload("INTERNAL_ERROR", str(exc) or "Internal error"),
        )
