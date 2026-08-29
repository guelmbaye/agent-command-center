"""OpenTelemetry — the mission is the unit of observability (Doc 05 §2-4).

Deliberately small span vocabulary. Every span carries
mission_id / execution_id / agent_id for correlation (Doc 05 §20).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from apps.api.core import context
from apps.api.core.config import Settings

try:  # OpenTelemetry is optional locally
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    _OTEL = True
except Exception:  # pragma: no cover
    _OTEL = False


class Span:
    """ACC span vocabulary (Doc 05 §4)."""
    MISSION_START = "mission.start"
    MISSION_COMPLETE = "mission.complete"
    MISSION_RESUME = "mission.resume"
    AGENT_START = "agent.start"
    AGENT_COMPLETE = "agent.complete"
    AGENT_FAILURE = "agent.failure"
    MODEL_CALL = "model.call"
    TOOL_CALL = "tool.call"
    POLICY_CHECK = "policy.check"
    APPROVAL_REQUEST = "approval.request"
    APPROVAL_DECISION = "approval.decision"
    CHECKPOINT_CREATE = "checkpoint.create"
    RECOVERY_START = "recovery.start"
    RECOVERY_DECISION = "recovery.decision"
    RECOVERY_COMPLETE = "recovery.complete"
    ARMOR_SCAN = "security.model_armor"


_tracer: Any = None


def configure_telemetry(settings: Settings) -> None:
    global _tracer
    if not _OTEL or settings.otel_traces_exporter == "none":
        _tracer = None
        return
    resource = Resource.create({
        "service.name": settings.otel_service_name,
        "service.namespace": "acc",
        "deployment.environment": settings.acc_env,
    })
    provider = TracerProvider(resource=resource)
    exporter = _build_exporter(settings)
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    _otel_trace.set_tracer_provider(provider)
    _tracer = _otel_trace.get_tracer("acc")


def _build_exporter(settings: Settings):  # pragma: no cover - depend de l'env
    kind = settings.otel_traces_exporter
    if kind == "console":
        return ConsoleSpanExporter()
    if kind == "otlp":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        return OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint or None)
    if kind == "gcp":
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        return CloudTraceSpanExporter(project_id=settings.google_cloud_project or None)
    return None


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Open a span, automatically injecting the execution context."""
    attrs = {f"acc.{k}": v for k, v in context.as_dict().items()}
    attrs.update({f"acc.{k}": v for k, v in attributes.items() if v is not None})
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name, attributes=attrs) as s:  # pragma: no cover
        yield s


def current_trace_id() -> str | None:
    if not _OTEL or _tracer is None:  # pragma: no cover
        return context.current().trace_id
    ctx = _otel_trace.get_current_span().get_span_context()
    if ctx and ctx.trace_id:
        return format(ctx.trace_id, "032x")
    return context.current().trace_id
