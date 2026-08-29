"""The Policy Engine is deterministic and denies by default (Doc 03 §5-7)."""
from __future__ import annotations

import pytest

from apps.api.repositories.memory_store import InMemoryStore
from apps.api.services.policy_engine import PolicyEngine, PolicyRequest
from domain.enums import AuthorityLevel, PolicyDecisionValue, RiskLevel
from domain.models import AgentIdentity
from tests.conftest import make_settings

D = PolicyDecisionValue


def identity(**kw) -> AgentIdentity:
    base = dict(agent_id="procurement-agent", agent_version="1.0.0",
                execution_id="EXE-1", mission_id="MIS-1", task_id="TASK-1")
    base.update(kw)
    return AgentIdentity(**base)


@pytest.fixture
def engine() -> PolicyEngine:
    # make_settings() disables `.env` reading: the thresholds tested here are
    # the product's, not the developer workstation's.
    return PolicyEngine(InMemoryStore(), make_settings())


async def test_read_only_is_autonomous(engine):
    outcome = await engine.evaluate(PolicyRequest(identity(), "supplier.status"))
    assert outcome.decision is D.ALLOW
    assert outcome.rule_id == "READ-010"


@pytest.mark.parametrize("amount,expected,rule", [
    (4_800.0, D.ALLOW, "PURCHASE-020"),             # scenario nominal SUP-A
    (5_000.0, D.ALLOW, "PURCHASE-020"),             # borne inferieure incluse
    (5_000.01, D.APPROVAL_REQUIRED, "PURCHASE-021"),
    (18_000.0, D.APPROVAL_REQUIRED, "PURCHASE-021"),  # scenario hero SUP-B
    (25_000.0, D.APPROVAL_REQUIRED, "PURCHASE-021"),
    (25_000.01, D.DENY, "PURCHASE-022"),
])
async def test_purchase_thresholds(engine, amount, expected, rule):
    outcome = await engine.evaluate(
        PolicyRequest(identity(), "purchase.execute", amount=amount)
    )
    assert outcome.decision is expected
    assert outcome.rule_id == rule


async def test_purchase_without_amount_is_denied(engine):
    """A missing amount is an unknown security state: deny."""
    outcome = await engine.evaluate(PolicyRequest(identity(), "purchase.execute"))
    assert outcome.decision is D.DENY


async def test_forbidden_resource_always_denied(engine):
    for capability in ("employee.read", "payroll.write", "customer.export"):
        outcome = await engine.evaluate(PolicyRequest(identity(), capability))
        assert outcome.decision is D.DENY
        assert outcome.rule_id == "RESOURCE-001"


async def test_unknown_capability_defaults_to_deny(engine):
    outcome = await engine.evaluate(PolicyRequest(identity(), "wire.transfer"))
    assert outcome.decision is D.DENY
    assert outcome.rule_id == "DEFAULT-999"


async def test_incomplete_identity_is_denied(engine):
    broken = AgentIdentity(agent_id="x", agent_version="1", execution_id="", mission_id="")
    outcome = await engine.evaluate(PolicyRequest(broken, "supplier.status"))
    assert outcome.decision is D.DENY
    assert outcome.rule_id == "IDENTITY-000"


async def test_blocked_authority_is_denied(engine):
    outcome = await engine.evaluate(PolicyRequest(
        identity(authority_level=AuthorityLevel.BLOCKED), "supplier.status"
    ))
    assert outcome.decision is D.DENY


async def test_high_risk_recovery_requires_approval(engine):
    """Recovery itself is governed (Doc 03 §20-21)."""
    high = await engine.evaluate(PolicyRequest(
        identity(), "recovery.apply", risk_level=RiskLevel.HIGH))
    medium = await engine.evaluate(PolicyRequest(
        identity(), "recovery.apply", risk_level=RiskLevel.MEDIUM))
    assert high.decision is D.APPROVAL_REQUIRED
    assert medium.decision is D.ALLOW


async def test_every_decision_is_persisted(engine):
    await engine.evaluate(PolicyRequest(identity(), "supplier.status"))
    await engine.evaluate(PolicyRequest(identity(), "purchase.execute", amount=99_000))
    decisions = await engine.store.list_policy_decisions("MIS-1")
    assert len(decisions) == 2
    assert all(d.rule_id and d.reason for d in decisions)


async def test_controlled_abort_needs_no_authorisation(engine):
    """ACC requires authorisation to ACT, not to ABSTAIN.

    Usage regression: a controlled abort went through `recovery.apply` with
    CRITICAL impact, hence APPROVAL_REQUIRED. The operator had to click
    "Approve" with no way to tell they were authorising the end of the mission.
    """
    outcome = await engine.evaluate(PolicyRequest(
        identity(agent_id="failure-twin"), "recovery.abort",
        risk_level=RiskLevel.CRITICAL))
    assert outcome.decision is D.ALLOW
    assert outcome.rule_id == "RECOVERY-032"


async def test_abort_decision_is_still_recorded(engine):
    """Requiring no authorisation does not mean escaping governance."""
    await engine.evaluate(PolicyRequest(
        identity(agent_id="failure-twin"), "recovery.abort"))
    decisions = await engine.store.list_policy_decisions("MIS-1")
    assert any(d.action == "recovery.abort" and d.reason for d in decisions)


async def test_applying_a_recovery_still_requires_authority(engine):
    """The fix must not relax governance of active recoveries."""
    outcome = await engine.evaluate(PolicyRequest(
        identity(agent_id="failure-twin"), "recovery.apply",
        risk_level=RiskLevel.HIGH))
    assert outcome.decision is D.APPROVAL_REQUIRED
