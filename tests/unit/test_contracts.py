"""Robust parsing of model output (Doc 02 §14-15)."""
from __future__ import annotations

from agents.contracts import extract_json, failure_result, parse_agent_result, parse_recovery_plan
from domain.enums import AgentResultStatus, FailureClass, RecoveryStrategy


def test_extract_json_from_fenced_block():
    assert extract_json('Voici :\n```json\n{"a": 1}\n```\nVoila') == {"a": 1}


def test_extract_json_from_surrounding_prose():
    assert extract_json('Analyse terminee. {"status": "SUCCESS"} Fin.') == {"status": "SUCCESS"}


def test_extract_json_returns_none_on_garbage():
    assert extract_json("aucun json ici") is None
    assert extract_json("") is None


def test_parse_agent_result_normalises_status():
    result = parse_agent_result('{"status":"success","finding":"ok","confidence":0.8}')
    assert result.status is AgentResultStatus.SUCCESS
    assert result.confidence == 0.8


def test_parse_agent_result_degrades_to_partial_on_bad_enum():
    result = parse_agent_result('{"status":"MAYBE","finding":"flou"}')
    assert result.status is AgentResultStatus.PARTIAL
    assert result.finding == "flou"


def test_parse_recovery_plan_reads_options():
    plan = parse_recovery_plan("""{
      "diagnosis": "SUP-A hors service",
      "impact": "HIGH",
      "options": [{"strategy":"USE_ALTERNATIVE_SUPPLIER","label":"SUP-B",
                   "estimated_risk":"MEDIUM","estimated_delay_hours":36,
                   "parameters":{"supplier_id":"SUP-B"}}],
      "selected_strategy": "USE_ALTERNATIVE_SUPPLIER",
      "selected_parameters": {"supplier_id":"SUP-B"},
      "rationale": "seule option dans les delais"
    }""")
    assert plan.selected_strategy is RecoveryStrategy.USE_ALTERNATIVE_SUPPLIER
    assert plan.selected_parameters["supplier_id"] == "SUP-B"
    assert len(plan.options) == 1


def test_parse_recovery_plan_returns_none_on_garbage():
    assert parse_recovery_plan("le fournisseur est en panne") is None


def test_security_failure_becomes_blocked_not_retryable():
    """A security failure must never be retryable."""
    assert failure_result("injection", FailureClass.SECURITY).status is AgentResultStatus.BLOCKED
    assert failure_result("403", FailureClass.AUTHORIZATION).status is AgentResultStatus.BLOCKED
    assert (failure_result("timeout", FailureClass.TIMEOUT).status
            is AgentResultStatus.RETRYABLE_FAILURE)
    assert (failure_result("503", FailureClass.DEPENDENCY).status
            is AgentResultStatus.NON_RETRYABLE_FAILURE)
