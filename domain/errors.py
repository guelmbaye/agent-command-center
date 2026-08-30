"""Unified error contract (Doc 08 §26)."""
from __future__ import annotations


class ACCError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class MissionNotFound(ACCError):
    code, http_status = "MISSION_NOT_FOUND", 404


class TaskNotFound(ACCError):
    code, http_status = "TASK_NOT_FOUND", 404


class AgentUnavailable(ACCError):
    code, http_status = "AGENT_UNAVAILABLE", 409


class PolicyDenied(ACCError):
    code, http_status = "POLICY_DENIED", 403


class ApprovalRequired(ACCError):
    code, http_status = "APPROVAL_REQUIRED", 202


class ApprovalRejected(ACCError):
    code, http_status = "APPROVAL_REJECTED", 409


class ApprovalNotFound(ACCError):
    code, http_status = "APPROVAL_NOT_FOUND", 404


class ToolUnavailable(ACCError):
    code, http_status = "TOOL_UNAVAILABLE", 502


class IdempotencyConflict(ACCError):
    code, http_status = "IDEMPOTENCY_CONFLICT", 409


class InvalidState(ACCError):
    code, http_status = "INVALID_STATE", 409


class StateVersionConflict(ACCError):
    code, http_status = "STATE_VERSION_CONFLICT", 409


class RecoveryFailed(ACCError):
    code, http_status = "RECOVERY_FAILED", 500


class SecurityThreatDetected(ACCError):
    code, http_status = "SECURITY_THREAT_DETECTED", 403


class IdentityUnverified(ACCError):
    """Doc 03 §7 — unknown security state => we do not execute."""
    code, http_status = "IDENTITY_UNVERIFIED", 403


class CapabilityDenied(ACCError):
    code, http_status = "CAPABILITY_DENIED", 403


class DemoControlFailed(ACCError):
    """A demo control could not complete, and says which step failed.

    A bare 500 on a demo control, minutes before a recording, tells the
    operator nothing about where to look.
    """

    code, http_status = "DEMO_CONTROL_FAILED", 502


class DemoDisabled(ACCError):
    code, http_status = "DEMO_DISABLED", 403
