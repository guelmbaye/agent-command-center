"""Policy Engine — the last authorisation boundary before enterprise action.

Doc 03 §5-6, Doc 07 §12, Doc 10 §8.
Deterministic by construction: "Simple, visible and enforceable beats complex."
The LLM never takes part in the authorisation decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.api.core.config import Settings, get_settings
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, current_trace_id, span
from apps.api.repositories.base import Store
from domain.enums import AuthorityLevel, PolicyDecisionValue, RiskLevel
from domain.models import AgentIdentity, PolicyDecision

logger = get_logger("acc.policy")

D = PolicyDecisionValue

# Resources forbidden regardless of identity (Doc 03 §4)
FORBIDDEN_CAPABILITIES = {"employee.read", "payroll.write", "customer.export",
                          "secret.read", "iam.write"}

# Read-only capabilities -> autonomous
READ_ONLY_CAPABILITIES = {
    "supplier.read", "supplier.status", "supplier.capacity", "supplier.alternatives",
    "supplier.compare", "production.read", "risk.assess", "risk.compare", "risk.recommend",
    "purchase.recommend", "recovery.diagnose", "recovery.plan",
}


@dataclass
class PolicyRequest:
    identity: AgentIdentity
    capability: str
    resource: str | None = None
    amount: float | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    context: dict[str, Any] | None = None


@dataclass
class PolicyOutcome:
    decision: PolicyDecisionValue
    reason: str
    rule_id: str
    record: PolicyDecision

    @property
    def allowed(self) -> bool:
        return self.decision is D.ALLOW

    @property
    def needs_approval(self) -> bool:
        return self.decision is D.APPROVAL_REQUIRED


Rule = Callable[[PolicyRequest, Settings], tuple[PolicyDecisionValue, str, str] | None]


# --- Rules -------------------------------------------------------------------
def rule_identity_present(req: PolicyRequest, _: Settings):
    """Doc 03 §7 — unknown security state => DENY. Fail securely."""
    ident = req.identity
    if not ident or not ident.agent_id or not ident.execution_id or not ident.mission_id:
        return D.DENY, "Execution identity missing or incomplete", "IDENTITY-000"
    return None


def rule_forbidden_resource(req: PolicyRequest, _: Settings):
    if req.capability in FORBIDDEN_CAPABILITIES:
        return D.DENY, f"Restricted resource: {req.capability}", "RESOURCE-001"
    return None


def rule_blocked_authority(req: PolicyRequest, _: Settings):
    if req.identity.authority_level is AuthorityLevel.BLOCKED:
        return D.DENY, "Agent authority level is BLOCKED", "AUTHORITY-002"
    return None


def rule_read_only(req: PolicyRequest, _: Settings):
    if req.capability in READ_ONLY_CAPABILITIES:
        return D.ALLOW, "Read-only capability, no enterprise impact", "READ-010"
    return None


def rule_purchase_thresholds(req: PolicyRequest, settings: Settings):
    """Purchase thresholds (Doc 10 §8): <=5k autonomous, <=25k approval, above DENY."""
    if req.capability != "purchase.execute":
        return None
    amount = req.amount
    if amount is None:
        return D.DENY, "Purchase amount missing: authority cannot be evaluated", "PURCHASE-019"
    if amount <= settings.policy_purchase_autonomous_max:
        return (D.ALLOW,
                f"Amount {amount:,.0f} within autonomous authority "
                f"(<= {settings.policy_purchase_autonomous_max:,.0f})", "PURCHASE-020")
    if amount <= settings.policy_purchase_approval_max:
        return (D.APPROVAL_REQUIRED,
                f"Amount {amount:,.0f} exceeds autonomous authority "
                f"(> {settings.policy_purchase_autonomous_max:,.0f})", "PURCHASE-021")
    return (D.DENY,
            f"Amount {amount:,.0f} above the approval ceiling "
            f"({settings.policy_purchase_approval_max:,.0f})", "PURCHASE-022")


def rule_recovery_abort(req: PolicyRequest, _: Settings):
    """A controlled abort executes NO enterprise action.

    ACC requires authorisation to act, not to abstain. Asking the operator to
    approve an abort forced them to click "Approve" with no way to tell they
    were authorising the end of the mission. The decision is still evaluated
    and traced by the Policy Engine — it simply requires no extra authority.
    """
    if req.capability != "recovery.abort":
        return None
    return (D.ALLOW,
            "Controlled abort: no enterprise action is executed",
            "RECOVERY-032")


def rule_recovery_apply(req: PolicyRequest, _: Settings):
    """Doc 03 §20-21: recovery itself is governed."""
    if req.capability != "recovery.apply":
        return None
    if req.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        return (D.APPROVAL_REQUIRED,
                "High-risk recovery plan: human authority required", "RECOVERY-030")
    return D.ALLOW, "Recovery plan within autonomous limits", "RECOVERY-031"


def rule_supervised_default(req: PolicyRequest, _: Settings):
    if req.identity.authority_level is AuthorityLevel.HUMAN_APPROVAL:
        return D.APPROVAL_REQUIRED, "Agent configured for mandatory human approval", "AUTHORITY-040"
    return None


def rule_default_deny(_: PolicyRequest, __: Settings):
    """No explicit rule covers the action: deny (Doc 03 §7)."""
    return D.DENY, "No rule explicitly authorises this action", "DEFAULT-999"


RULES: list[Rule] = [
    rule_identity_present,
    rule_forbidden_resource,
    rule_blocked_authority,
    rule_read_only,
    rule_purchase_thresholds,
    rule_recovery_abort,
    rule_recovery_apply,
    rule_supervised_default,
    rule_default_deny,
]


class PolicyEngine:
    def __init__(self, store: Store, settings: Settings | None = None) -> None:
        self.store = store
        self.settings = settings or get_settings()

    async def evaluate(self, request: PolicyRequest) -> PolicyOutcome:
        with span(Span.POLICY_CHECK, capability=request.capability,
                  resource=request.resource):
            decision, reason, rule_id = D.DENY, "Non evalue", "DEFAULT-999"
            for rule in RULES:
                verdict = rule(request, self.settings)
                if verdict is not None:
                    decision, reason, rule_id = verdict
                    break

            record = PolicyDecision(
                mission_id=request.identity.mission_id,
                agent_id=request.identity.agent_id,
                action=request.capability,
                resource=request.resource,
                decision=decision,
                reason=reason,
                rule_id=rule_id,
                risk_level=request.risk_level,
                amount=request.amount,
                trace_id=current_trace_id(),
            )
            await self.store.save_policy_decision(record)
            logger.info("policy_decision", extra={
                "action": request.capability, "decision": decision.value, "rule_id": rule_id,
            })
            return PolicyOutcome(decision, reason, rule_id, record)

    def describe(self) -> dict[str, Any]:
        """Expose the autonomy boundary as a product feature (Doc 03 §7)."""
        return {
            "autonomous": sorted(READ_ONLY_CAPABILITIES),
            # Amounts are formatted by the frontend (operator locale): the
            # backend exposes raw values, not localised strings.
            "approval_required": [
                "purchase.execute above the autonomous threshold",
                "recovery.apply (HIGH/CRITICAL risk)",
            ],
            "blocked": sorted(FORBIDDEN_CAPABILITIES),
            # The agent mode the fleet is ACTUALLY running. The UI used to
            # print "deterministic" as a literal string, so a deployment in
            # `hybrid` displayed the wrong mode — and an operator read a
            # two-minute run as a performance problem rather than as evidence
            # that a model was being called.
            "agent_mode": self.settings.acc_agent_mode,
            "thresholds": {
                "purchase_autonomous_max": self.settings.policy_purchase_autonomous_max,
                "purchase_approval_max": self.settings.policy_purchase_approval_max,
            },
            "default": "DENY",
        }
